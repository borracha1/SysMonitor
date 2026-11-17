"""Disks: activity, read/write rates and space per volume, for the widget column and the disk window.

The pure part (snapshot, alert, formatting, the window's view) has no ctypes and no Tk. The Win32
part (PDH counters, volumes, device model) is used only by DiskSource/DiskMonitor at run time.
"""
from collections import namedtuple
import re
import struct
import threading
import time

from usage_limits import usage_color

Volume = namedtuple('Volume', 'letter label total used free')  # bytes, or None when unknown
Disk = namedtuple('Disk', 'index model active read write volumes')  # active 0-100|None, B/s|None

_INSTANCE = re.compile(r'^(\d+)((?:\s+[A-Za-z]:)*)\s*$')


def parse_instance(name):
    """'1 D: F:' -> (1, ('D', 'F')); '_Total' or anything else -> None."""
    match = _INSTANCE.match(name or '')
    if match is None:
        return None
    letters = tuple(part[0].upper() for part in match.group(2).split())
    return int(match.group(1)), letters


def _activity(idle):
    if idle is None:
        return None
    return float(min(100.0, max(0.0, 100.0 - idle)))


def build_snapshot(counters, volumes, models):
    disks = []
    for instance, values in counters.items():
        parsed = parse_instance(instance)
        if parsed is None:
            continue
        index, letters = parsed
        own = tuple(volumes[letter] for letter in sorted(letters) if letter in volumes)
        if not own:
            continue
        disks.append(Disk(index, models.get(index), _activity(values.get('idle')),
                          values.get('read'), values.get('write'), own))
    disks.sort(key=lambda disk: disk.index)
    return tuple(disks)


def alert_disk(snapshot, limits):
    """(letter, activity) of the busiest disk at or above Low, or None."""
    best = None
    for disk in snapshot or ():
        if disk.active is None or disk.active < limits[0] or not disk.volumes:
            continue
        if best is None or disk.active > best.active:  # Strict: a tie keeps the lower index.
            best = disk
    return None if best is None else (best.volumes[0].letter, best.active)


def _number(value):
    return f'{value:.1f}'.replace('.', ',') if value < 100 else f'{int(value + 0.5)}'


def fmt_rate(bps):
    if bps is None:
        return '--'
    if bps < 1024:
        return f'{int(bps + 0.5)} B/s'
    for unit, size in (('KB/s', 1024), ('MB/s', 1024 ** 2), ('GB/s', 1024 ** 3)):
        if bps < size * 1024 or unit == 'GB/s':
            return f'{_number(bps / size)} {unit}'


def fmt_size(size):
    if size is None:
        return '--'
    gb = size / 1024 ** 3
    if gb < 1000:
        return f'{gb:.1f}'.replace('.', ',') + ' GB'
    return f'{gb / 1024:.1f}'.replace('.', ',') + ' TB'


def space_color(percent, limits, normal, colors):
    """Space bar: High from `high`, Warning from `warning`, else Low; no reading keeps `normal`."""
    if percent is None:
        return normal
    warning, high = limits
    low_color, warning_color, high_color = colors
    return high_color if percent >= high else warning_color if percent >= warning else low_color


def disk_view(snapshot, prefs, normal):
    """What the window shows, already formatted and coloured; 'key' identifies its structure."""
    colors = prefs['colors']
    view = []
    for disk in snapshot or ():
        volumes = []
        for volume in disk.volumes:
            fraction = None
            if volume.total and volume.used is not None:
                fraction = max(0.0, min(1.0, volume.used / volume.total))
            name = f'{volume.letter}:' + (f'  {volume.label}' if volume.label else '')
            volumes.append({
                'letter': volume.letter, 'name': name, 'fraction': fraction,
                'bar_color': space_color(None if fraction is None else 100 * fraction,
                                         prefs['disk_space'], normal, colors),
                'space': f'{fmt_size(volume.used)} / {fmt_size(volume.total)}',
                'free': f'{fmt_size(volume.free)} livre'})
        view.append({
            'key': (disk.index, tuple(volume.letter for volume in disk.volumes)),
            'title': f'Disco {disk.index}' + (f' · {disk.model}' if disk.model else ''),
            'activity': 'atividade ' + ('--' if disk.active is None else f'{disk.active:.0f}%'),
            'activity_color': usage_color(disk.active, prefs['disk'], normal, colors),
            'rates': f'leitura {fmt_rate(disk.read)}   escrita {fmt_rate(disk.write)}',
            'volumes': volumes})
    return view


def _ascii_at(buf, offset):
    if not offset or offset >= len(buf):
        return ''
    end = buf.find(b'\0', offset)
    return bytes(buf[offset:end if end >= 0 else len(buf)]).decode('ascii', 'replace').strip()


def parse_device_descriptor(buf):
    """Model ('vendor product') from a STORAGE_DEVICE_DESCRIPTOR, or None."""
    if len(buf) < 20:
        return None
    vendor_at, product_at = struct.unpack_from('<II', buf, 12)
    text = ' '.join(part for part in (_ascii_at(buf, vendor_at), _ascii_at(buf, product_at)) if part)
    return text or None


def parse_disk_extents(buf):
    """DiskNumber of the first extent of a VOLUME_DISK_EXTENTS, or None."""
    if len(buf) < 12 or struct.unpack_from('<I', buf, 0)[0] < 1:
        return None
    return struct.unpack_from('<I', buf, 8)[0]


# -- Win32 collection ---------------------------------------------------------
PDH_FMT_DOUBLE = 0x00000200
PDH_FMT_NOCAP100 = 0x00008000
PDH_MORE_DATA = 0x800007D2
PDH_PATHS = {'idle': r'\PhysicalDisk(*)\% Idle Time',
             'read': r'\PhysicalDisk(*)\Disk Read Bytes/sec',
             'write': r'\PhysicalDisk(*)\Disk Write Bytes/sec'}


class PdhReader:
    """English counter paths (PdhAddEnglishCounterW) so a Portuguese Windows works too. No admin."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self._ctypes = ctypes

        class Value(ctypes.Structure):
            _fields_ = [('CStatus', wintypes.DWORD), ('doubleValue', ctypes.c_double)]

        class Item(ctypes.Structure):
            _fields_ = [('szName', wintypes.LPWSTR), ('FmtValue', Value)]

        self._Item = Item
        pdh = ctypes.WinDLL('pdh')  # Private instance: argtypes stay local.
        handle = wintypes.HANDLE
        pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(handle)]
        pdh.PdhAddEnglishCounterW.argtypes = [handle, wintypes.LPCWSTR, ctypes.c_size_t, ctypes.POINTER(handle)]
        pdh.PdhCollectQueryData.argtypes = [handle]
        pdh.PdhGetFormattedCounterArrayW.argtypes = [handle, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                                     ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        pdh.PdhCloseQuery.argtypes = [handle]
        for name in ('PdhOpenQueryW', 'PdhAddEnglishCounterW', 'PdhCollectQueryData',
                     'PdhGetFormattedCounterArrayW', 'PdhCloseQuery'):
            getattr(pdh, name).restype = wintypes.DWORD
        self._pdh = pdh
        self._query = handle()
        self._check(pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query)), 'PdhOpenQueryW')
        self._counters = {}
        try:
            for key, path in PDH_PATHS.items():
                counter = handle()
                self._check(pdh.PdhAddEnglishCounterW(self._query, path, 0, ctypes.byref(counter)), path)
                self._counters[key] = counter
            self._check(pdh.PdhCollectQueryData(self._query), 'PdhCollectQueryData')  # Rates need two.
        except OSError:
            self.close()
            raise

    @staticmethod
    def _check(status, what):
        if status != 0:
            raise OSError(f'pdh: {what} failed: {status & 0xFFFFFFFF:#x}')

    def _array(self, counter):
        ctypes = self._ctypes
        from ctypes import wintypes
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        fmt = PDH_FMT_DOUBLE | PDH_FMT_NOCAP100
        status = self._pdh.PdhGetFormattedCounterArrayW(counter, fmt, ctypes.byref(size), ctypes.byref(count), None)
        if status != PDH_MORE_DATA:
            self._check(status, 'PdhGetFormattedCounterArrayW(size)')
            return {}
        buffer = ctypes.create_string_buffer(size.value)
        self._check(self._pdh.PdhGetFormattedCounterArrayW(counter, fmt, ctypes.byref(size), ctypes.byref(count),
                                                           buffer), 'PdhGetFormattedCounterArrayW')
        items = ctypes.cast(buffer, ctypes.POINTER(self._Item))
        result = {}
        for i in range(count.value):
            item = items[i]
            valid = item.FmtValue.CStatus in (0, 1)  # PDH_CSTATUS_VALID_DATA / NEW_DATA
            result[item.szName] = float(item.FmtValue.doubleValue) if valid else None
        return result

    def read(self, letters=None):  # `letters` is accepted for the PsutilCounters interface.
        self._check(self._pdh.PdhCollectQueryData(self._query), 'PdhCollectQueryData')
        arrays = {key: self._array(counter) for key, counter in self._counters.items()}
        names = set().union(*(set(values) for values in arrays.values()))
        return {name: {key: arrays[key].get(name) for key in PDH_PATHS} for name in names}

    def close(self):
        if self._query:
            self._pdh.PdhCloseQuery(self._query)
            self._query = self._ctypes.c_void_p(None)


def _kernel32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL('kernel32', use_last_error=True)  # Private instance.
    k.GetLogicalDrives.restype = wintypes.DWORD
    k.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    k.GetDriveTypeW.restype = wintypes.UINT
    k.GetDiskFreeSpaceExW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_ulonglong),
                                      ctypes.POINTER(ctypes.c_ulonglong), ctypes.POINTER(ctypes.c_ulonglong)]
    k.GetDiskFreeSpaceExW.restype = wintypes.BOOL
    k.GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                                        ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
    k.GetVolumeInformationW.restype = wintypes.BOOL
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                              wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k.CreateFileW.restype = wintypes.HANDLE
    k.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    k.DeviceIoControl.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    return k


DRIVE_FIXED = 3


def fixed_volumes():
    import ctypes
    k = _kernel32()
    mask = k.GetLogicalDrives()
    result = {}
    for bit in range(26):
        if not mask & (1 << bit):
            continue
        letter = chr(ord('A') + bit)
        root = f'{letter}:\\'
        if k.GetDriveTypeW(root) != DRIVE_FIXED:
            continue
        caller, total, free = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
        if k.GetDiskFreeSpaceExW(root, ctypes.byref(caller), ctypes.byref(total), ctypes.byref(free)):
            sizes = (total.value, total.value - free.value, free.value)
        else:
            sizes = (None, None, None)
        name = ctypes.create_unicode_buffer(261)
        label = name.value if k.GetVolumeInformationW(root, name, 261, None, None, None, None, 0) else ''
        result[letter] = Volume(letter, label, *sizes)
    return result


_OPEN_EXISTING, _SHARE_RW = 3, 0x1 | 0x2
_INVALID_HANDLE = -1
IOCTL_STORAGE_QUERY_PROPERTY = 0x2D1400
IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = 0x560000


def _device_ioctl(path, code, inbuf=b''):
    """Open with access 0 (no admin needed for these FILE_ANY_ACCESS ioctls) and return the output."""
    import ctypes
    from ctypes import wintypes
    k = _kernel32()
    handle = k.CreateFileW(path, 0, _SHARE_RW, None, _OPEN_EXISTING, 0, None)
    if handle is None or handle == ctypes.c_void_p(_INVALID_HANDLE).value:
        return None
    try:
        out = ctypes.create_string_buffer(1024)
        returned = wintypes.DWORD(0)
        source = ctypes.create_string_buffer(inbuf, len(inbuf)) if inbuf else None
        if not k.DeviceIoControl(handle, code, source, len(inbuf), out, len(out), ctypes.byref(returned), None):
            return None
        return out.raw[:returned.value]
    finally:
        k.CloseHandle(handle)


def read_model(index):
    query = struct.pack('<II4x', 0, 0)  # StorageDeviceProperty, PropertyStandardQuery
    data = _device_ioctl(rf'\\.\PhysicalDrive{index}', IOCTL_STORAGE_QUERY_PROPERTY, query)
    return None if data is None else parse_device_descriptor(data)


def volume_disk_number(letter):
    data = _device_ioctl(rf'\\.\{letter}:', IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS)
    return None if data is None else parse_disk_extents(data)


class PsutilCounters:
    """Fallback without PDH: rates from psutil deltas, activity unknown (None)."""

    def __init__(self, volume_disk=volume_disk_number, io=None, clock=None):
        self.volume_disk = volume_disk
        self.io = io
        self.clock = clock or time.monotonic
        self._disk_of = {}
        self._previous, self._previous_at = None, None

    def read(self, letters):
        if self.io is None:
            import psutil
            self.io = lambda: psutil.disk_io_counters(perdisk=True)
        groups = {}
        for letter in sorted(letters):
            if letter not in self._disk_of:
                self._disk_of[letter] = self.volume_disk(letter)
            index = self._disk_of[letter]
            if index is not None:
                groups.setdefault(index, []).append(letter)
        now, sample = self.clock(), self.io() or {}
        elapsed = None if self._previous_at is None else now - self._previous_at
        result = {}
        for index, own in groups.items():
            rates = {'read': None, 'write': None}
            current, before = sample.get(f'PhysicalDrive{index}'), (self._previous or {}).get(f'PhysicalDrive{index}')
            if current is not None and before is not None and elapsed and elapsed > 0:
                for key in ('read', 'write'):
                    delta = getattr(current, key + '_bytes') - getattr(before, key + '_bytes')
                    rates[key] = delta / elapsed if delta >= 0 else 0.0
            result[f'{index} ' + ' '.join(f'{letter}:' for letter in own)] = dict(idle=None, **rates)
        self._previous, self._previous_at = sample, now
        return result


class DiskSource:
    """Counters every read; space every `space_every` reads; models when the disk set changes."""

    def __init__(self, counters=None, fallback=None, volumes=fixed_volumes, model=read_model, space_every=5,
                 log=lambda message: None):
        self._counters = counters
        self._fallback = fallback
        self._volumes_fn, self._model_fn = volumes, model
        self.space_every = space_every
        self.log = log
        self._volumes, self._reads = {}, 0
        self._models, self._instances = {}, None

    def _counter_values(self):
        if self._counters is None:
            try:
                self._counters = PdhReader()
            except OSError as exc:
                self.log(f'disks: pdh unavailable, using psutil: {exc}')
                self._counters = self._fallback or PsutilCounters()
        try:
            return self._counters.read(tuple(self._volumes))
        except OSError as exc:
            if self._counters is self._fallback:
                raise
            self.log(f'disks: pdh failed, using psutil: {exc}')
            self._counters = self._fallback = self._fallback or PsutilCounters()
            return self._counters.read(tuple(self._volumes))

    def read(self):
        if self._reads % self.space_every == 0:
            self._volumes = self._volumes_fn()
        self._reads += 1
        counters = self._counter_values()
        instances = frozenset(counters)
        if instances != self._instances:
            self._instances = instances
            self._models = {}
            for name in sorted(counters):
                parsed = parse_instance(name)
                if parsed is not None:
                    self._models[parsed[0]] = self._model_fn(parsed[0])
        return build_snapshot(counters, self._volumes, self._models)


class DiskMonitor(threading.Thread):
    """One per process: collects every interval_s and keeps the last snapshot for the Tk thread."""

    def __init__(self, source=None, interval_s=1.0, log=lambda message: None):
        super().__init__(daemon=True, name='DiskMonitor')
        self.source = source
        self.interval_s = interval_s
        self.log = log
        self._lock = threading.Lock()
        self._snapshot = None
        self._stop_evt = threading.Event()  # Not "_stop": that would shadow Thread's own.
        self._failing = False

    def snapshot(self):
        with self._lock:
            return self._snapshot

    def stop(self):
        self._stop_evt.set()

    def cycle(self):
        try:
            if self.source is None:
                self.source = DiskSource(log=self.log)
            result = self.source.read()
        except Exception as exc:  # Never let a disk reading take anything down.
            if not self._failing:
                self._failing = True
                self.log(f'disks: collection failed: {exc}')
            return
        if self._failing:
            self._failing = False
            self.log('disks: collection recovered')
        with self._lock:
            self._snapshot = result

    def run(self):
        while not self._stop_evt.is_set():
            self.cycle()
            self._stop_evt.wait(self.interval_s)
