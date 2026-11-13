"""Top 3 programs by CPU and by memory, for the widget tooltip and the tray icons.

Aggregation and formatting are pure; ProcessSampler reads the processes through an
injected iterator (psutil.process_iter by default), and TopProcessesMonitor samples
on its own thread so the Tk/Win32 threads never wait for it.
"""
from collections import namedtuple
import struct
import threading
import time

TOP_N = 3
IGNORED_NAMES = frozenset({'system idle process'})
PRIME_WAIT_S = 0.5  # Between the priming read (always 0 %) and the one that is published.

ProcRow = namedtuple('ProcRow', 'pid name cpu rss')  # cpu: psutil percent (100 per logical CPU)
Entry = namedtuple('Entry', 'name value percent')  # CPU: value == percent of the machine
TopLists = namedtuple('TopLists', 'cpu mem')


def top_lists(rows, cpu_count, total_ram):
    """Sum the rows by program name and return the TOP_N largest of each kind."""
    cpus = max(1, cpu_count or 1)
    totals = {}  # lower-case name -> [display name, cpu, rss]
    for pid, name, cpu, rss in rows:
        if pid == 0 or name.lower() in IGNORED_NAMES:
            continue
        item = totals.setdefault(name.lower(), [name, 0.0, 0])
        item[1] += cpu or 0.0
        item[2] += rss or 0

    def largest(index, build):
        items = [item for item in totals.values() if item[index] > 0]
        items.sort(key=lambda item: (-item[index], item[0].lower()))
        return [build(item) for item in items[:TOP_N]]

    return TopLists(
        largest(1, lambda item: Entry(item[0], item[1] / cpus, item[1] / cpus)),
        largest(2, lambda item: Entry(item[0], item[2], 100.0 * item[2] / total_ram if total_ram else 0.0)))


# -- formatting ---------------------------------------------------------------
def _comma(text):
    return text.replace('.', ',')


def fmt_percent(value):
    return _comma(f'{value:.1f}') + '%' if value < 10 else f'{int(value + 0.5)}%'


def fmt_memory(size):
    if size >= 1024 ** 3:
        return _comma(f'{size / 1024 ** 3:.1f}') + ' GB'
    return f'{int(size / 1024 ** 2 + 0.5)} MB'


def format_cpu(entry):
    return f'{entry.name}  {fmt_percent(entry.percent)}'


def format_mem(entry):
    return f'{entry.name}  {fmt_memory(entry.value)} ({fmt_percent(entry.percent)})'


def widget_text(kind, top):
    """Tooltip text of the widget: a title and one line per program."""
    title = 'Maiores em CPU' if kind == 'cpu' else 'Maiores em memória'
    if top is None:
        return title + '\ncoletando…'
    entries = top.cpu if kind == 'cpu' else top.mem
    if not entries:
        return title + '\nsem uso relevante'
    fmt = format_cpu if kind == 'cpu' else format_mem
    return '\n'.join([title] + [fmt(entry) for entry in entries])


def shorten(name, limit):
    if len(name) <= limit:
        return name
    return name[:limit - 1] + '…' if limit > 1 else '…'


def tray_tooltip(head, kind, top, extra=None, limit=127):
    """Tray tooltip: the usual head plus the top programs, names cut to fit the limit.
    `extra` (a warning) is appended only if it still fits after the programs."""
    entries = [] if top is None else (top.cpu if kind == 'cpu' else top.mem)
    parts = [(entry.name, fmt_percent(entry.percent) if kind == 'cpu' else fmt_memory(entry.value))
             for entry in entries]
    names = [name for name, _ in parts]

    def text():
        lines = [head] + [f'{name} {value}' for name, (_, value) in zip(names, parts)]
        return '\n'.join(lines)

    while len(text()) > limit:
        longest = max(range(len(names)), key=lambda i: len(names[i]), default=None)
        if longest is None or len(names[longest]) <= 1:
            break
        names[longest] = shorten(names[longest], len(names[longest]) - 1)
    result = text()
    if len(result) > limit:  # Still too long: keep the head and as many programs as fit.
        lines = result.split('\n')
        while len('\n'.join(lines)) > limit and len(lines) > 1:
            lines.pop()
        result = '\n'.join(lines)[:limit]
    if extra and len(result) + 1 + len(extra) <= limit:
        result += '\n' + extra
    return result


def tooltip_origin(label_rect, size, screen):
    """Top-left of a tooltip of `size` next to a label: above it, below if there is no room."""
    left, top, _, bottom = label_rect
    width, height = size
    screen_left, screen_top, screen_right, _ = screen
    x = max(screen_left, min(left, screen_right - width))
    y = top - height - 4
    if y < screen_top:
        y = bottom + 4
    return x, y


# -- sampling -----------------------------------------------------------------
RawProc = namedtuple('RawProc', 'pid created name cpu_s rss')  # cpu_s: CPU seconds used so far


class ProcessSampler:
    """CPU % comes from the delta of each process' CPU seconds between two readings
    (the first reading of every process is 0), keyed by pid + creation time."""

    def __init__(self, reader=None, cpu_count=None, total_ram=None, clock=time.monotonic):
        if reader is None or cpu_count is None or total_ram is None:
            import psutil
            reader = reader or default_reader()
            cpu_count = cpu_count or psutil.cpu_count(logical=True) or 1
            total_ram = total_ram or psutil.virtual_memory().total
        self._reader = reader
        self.cpu_count = cpu_count
        self.total_ram = total_ram
        self._clock = clock
        self._previous = {}
        self._previous_at = None

    def sample(self):
        now = self._clock()
        elapsed = None if self._previous_at is None else now - self._previous_at
        current, rows = {}, []
        for proc in self._reader():
            if proc.pid == 0:
                continue
            key = (proc.pid, proc.created)
            current[key] = proc.cpu_s
            before = self._previous.get(key)
            cpu = 0.0
            if before is not None and elapsed and elapsed > 0 and proc.cpu_s >= before:
                cpu = 100.0 * (proc.cpu_s - before) / elapsed
            rows.append(ProcRow(proc.pid, proc.name, cpu, proc.rss))
        self._previous, self._previous_at = current, now
        return top_lists(rows, self.cpu_count, self.total_ram)


def psutil_reader(process_iter=None, errors=None):
    """Slow fallback (each process is asked on its own); denied/vanished ones are skipped."""
    if process_iter is None or errors is None:
        import psutil
        process_iter = process_iter or psutil.process_iter
        errors = errors or (psutil.Error, OSError)

    def read():
        for process in process_iter():
            try:
                pid = process.pid
                if pid == 0:
                    continue
                name = process.name()
                created = process.create_time()
            except errors:
                continue
            try:
                times = process.cpu_times()
                cpu_s = times.user + times.system
            except errors:
                cpu_s = 0.0
            try:
                rss = process.memory_info().rss
            except errors:
                rss = 0
            yield RawProc(pid, created, name, cpu_s, rss)
    return read


# SYSTEM_PROCESS_INFORMATION offsets on 64-bit Windows (one call lists every process).
_SPI_CREATE, _SPI_USER, _SPI_KERNEL = 32, 40, 48
_SPI_NAME_LEN, _SPI_NAME_PTR, _SPI_PID, _SPI_WORKING_SET = 56, 64, 80, 144
_SPI_MIN_SIZE = 152


def parse_process_buffer(buffer, base):
    """Records of a SystemProcessInformation buffer that starts at address `base`."""
    offset, size = 0, len(buffer)
    while offset + _SPI_MIN_SIZE <= size:
        next_offset = struct.unpack_from('<I', buffer, offset)[0]
        created, user, kernel = struct.unpack_from('<qqq', buffer, offset + _SPI_CREATE)
        name_len = struct.unpack_from('<H', buffer, offset + _SPI_NAME_LEN)[0]
        name_ptr = struct.unpack_from('<Q', buffer, offset + _SPI_NAME_PTR)[0]
        pid = struct.unpack_from('<Q', buffer, offset + _SPI_PID)[0]
        working_set = struct.unpack_from('<Q', buffer, offset + _SPI_WORKING_SET)[0]
        start = name_ptr - base
        name = ''
        if name_len and 0 <= start and start + name_len <= size:
            name = bytes(buffer[start:start + name_len]).decode('utf-16-le', 'replace')
        yield RawProc(pid, created, name, (user + kernel) / 1e7, working_set)
        if not next_offset:
            break
        offset += next_offset


def ctypes_reader():
    """Task Manager's source: ONE NtQuerySystemInformation call for all processes, with
    explicit argtypes (see armadilhas.md). Needs no privilege. Raises OSError if unusable."""
    import ctypes
    from ctypes import wintypes
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        raise OSError('64-bit Python required')
    ntdll = ctypes.WinDLL('ntdll')  # Private instance: argtypes stay local.
    query = ntdll.NtQuerySystemInformation
    query.argtypes = [wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
    query.restype = ctypes.c_long
    state = {'size': 1 << 20}

    def read():
        for _ in range(8):
            buffer = ctypes.create_string_buffer(state['size'])
            needed = wintypes.ULONG(0)
            status = query(5, buffer, state['size'], ctypes.byref(needed))
            if status == 0:
                data = buffer.raw[:state['size']]
                return list(parse_process_buffer(data, ctypes.addressof(buffer)))
            if status & 0xFFFFFFFF != 0xC0000004:  # STATUS_INFO_LENGTH_MISMATCH
                raise OSError(f'NtQuerySystemInformation failed: {status & 0xFFFFFFFF:#x}')
            state['size'] = max(needed.value, state['size']) + (256 << 10)
        raise OSError('process list kept growing')
    return read


def default_reader():
    """The bulk reader when it works (checked against this very process), else psutil."""
    try:
        read = ctypes_reader()
        import os
        mine = [proc for proc in read() if proc.pid == os.getpid()]
        if mine and mine[0].name and mine[0].rss > 0:
            return read
    except (OSError, AttributeError, ValueError):
        pass
    return psutil_reader()


class TopProcessesMonitor(threading.Thread):
    """Samples every interval_s while at least one owner (a hovered widget, the tray) is
    active, and keeps the last result for snapshot(); readers never block on the sampling."""

    def __init__(self, sampler=None, interval_s=2.0, clock=time.monotonic, log=lambda message: None):
        super().__init__(daemon=True, name='TopProcesses')
        self.sampler = sampler
        self.interval_s = interval_s
        self.clock = clock
        self.log = log
        self._lock = threading.Lock()
        self._owners = set()
        self._snapshot = None
        self._taken = None
        self._active = threading.Event()
        self._stop_evt = threading.Event()  # Not "_stop": that would shadow Thread's own.
        self._failed_logged = False

    @property
    def active(self):
        return self._active.is_set()

    def set_active(self, owner, active):
        with self._lock:
            if active:
                self._owners.add(owner)
            else:
                self._owners.discard(owner)
            if self._owners:
                self._active.set()
            else:
                self._active.clear()

    def snapshot(self):
        with self._lock:
            return self._snapshot

    def stop(self):
        self._stop_evt.set()
        self._active.set()

    def cycle(self, wait=None):
        """One sampling; primes the CPU counters first when the data is missing or old."""
        wait = wait or self._stop_evt.wait
        try:
            if self.sampler is None:
                self.sampler = ProcessSampler()
            now = self.clock()
            if self._taken is None or now - self._taken > 2 * self.interval_s + 1:
                self.sampler.sample()
                wait(PRIME_WAIT_S)
            result = self.sampler.sample()
        except Exception as exc:  # Never let the sampling take anything down.
            if not self._failed_logged:
                self._failed_logged = True
                self.log(f'top processes: sampling failed: {exc}')
            return
        with self._lock:
            self._snapshot = result
            self._taken = self.clock()

    def run(self):
        while not self._stop_evt.is_set():
            if not self._active.wait(timeout=1.0):
                continue
            if self._stop_evt.is_set():
                break
            self.cycle()
            self._stop_evt.wait(self.interval_s)
