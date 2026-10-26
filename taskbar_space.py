"""Taskbar UIA sampling (worker only) and pure, screen-coordinate layout policy."""
from dataclasses import dataclass
import math
import os
import sys
import threading
import time


@dataclass(frozen=True)
class SpaceSnapshot:
    hwnd: int
    bounds: tuple
    left: tuple
    right: tuple


@dataclass(frozen=True)
class Layout:
    side: str
    level: int
    x: int
    width: int
    overflow: bool = False


def choose_layout(snapshot, widths, tray_right):
    """Prefer fuller levels, trying right then left at each level."""
    if snapshot is None:
        return Layout('right', 0, tray_right - widths[0], widths[0])
    for level, width in enumerate(widths):
        for side in ('right', 'left'):
            begin, end = getattr(snapshot, side)
            if end - begin >= width:
                return Layout(side, level, end - width if side == 'right' else begin, width)
    return Layout('right', 2, tray_right - widths[2], widths[2], True)


def valid_rect(rect):
    return (len(rect) == 4 and all(math.isfinite(v) and abs(v) < 10**8 for v in rect)
            and rect[2] > rect[0] and rect[3] > rect[1])


def build_regions(hwnd, bounds, elements, own_pid=None):
    """Elements: (automation_id, class_name, rect, process_id), no COM here."""
    if not valid_rect(bounds):
        return None
    left, top, right, bottom = bounds
    clean = []
    for aid, cls, rect, pid in elements:
        if cls.startswith('Tk') or (own_pid is not None and pid == own_pid):
            continue
        if not valid_rect(rect):
            continue
        if rect[0] < left or rect[2] > right or rect[1] >= bottom or rect[3] <= top:
            continue
        clean.append((aid, cls, rect))
    starts = [rect for aid, cls, rect in clean if aid == 'StartButton']
    if not starts:
        return None
    start = min(starts, key=lambda rect: rect[0])
    icons = [rect[2] for aid, cls, rect in clean
             if cls == 'Taskbar.TaskListButtonAutomationPeer']
    trays = [rect[0] for aid, cls, rect in clean if cls.startswith('SystemTray.')]
    if not trays:
        return None  # An incomplete scan must not invent free space.
    icon_end = max([start[2]] + icons)
    left_end = max([left] + [rect[2] for aid, cls, rect in clean if rect[2] <= start[0]])
    return SpaceSnapshot(hwnd, tuple(bounds), (int(left_end + 10), int(start[0] - 10)),
                         (int(icon_end + 10), int(min(trays))))


class TaskbarSpaceMonitor(threading.Thread):
    """One daemon, no Tk calls/GUI joins; scan errors retain data until stale.

    A stuck COM provider can stall only this worker. Never spawn replacement
    workers on timeouts; expire its published data instead.
    """
    def __init__(self, on_event=lambda message: None, interval=2.0):
        super().__init__(daemon=True, name='taskbar-uia')
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._target = None
        self._targets = {}
        self._generation = 0
        self._values = {}
        self._warned = set()
        self._on_event = on_event
        self.interval = interval

    def set_target(self, hwnd):
        # Compatibility for a standalone, single-bar embedder.
        self._target = hwnd
        self.set_targets({hwnd} if hwnd else set())

    def set_targets(self, hwnds):
        wanted = set(hwnds)
        with self._lock:
            for hwnd in set(self._targets) - wanted:
                del self._targets[hwnd]
                self._values.pop(hwnd, None)
            for hwnd in wanted - set(self._targets):
                self._generation += 1
                self._targets[hwnd] = self._generation

    def snapshot(self, hwnd=None):
        with self._lock:
            value, stamp = self._values.get(hwnd if hwnd is not None else self._target, (None, 0))
            return value if time.monotonic() - stamp < 6 else None

    def stop(self):
        self._stop_event.set()

    def _failure(self, exc, hwnd=None):
        if hwnd is None:
            with self._lock:
                self._values.clear()
        if hwnd not in self._warned:
            self._warned.add(hwnd)
            if hwnd is None:
                self._on_event(f'taskbar UIA unavailable (hwnd={hwnd}); using fallback: {exc}')
            else:
                self._on_event(f'taskbar UIA scan failed (hwnd={hwnd}); keeping last layout: {exc}')

    def _scan_targets(self, automation):
        with self._lock:
            targets = tuple(self._targets.items())
        for hwnd, generation in targets:
            if self._stop_event.is_set():
                break
            try:
                value = self._scan(automation, hwnd)
                if value is None:
                    raise ValueError('incomplete taskbar regions')
                with self._lock:
                    if self._targets.get(hwnd) == generation:
                        self._values[hwnd] = value, time.monotonic()
            except Exception as exc:
                self._failure(exc, hwnd)

    def run(self):
        # Importing comtypes initializes COM: even the import belongs here.
        com = None
        try:
            # comtypes initializes the importing thread automatically. Request
            # MTA on its first import; otherwise initialize this worker explicitly.
            loaded = 'comtypes' in sys.modules
            previous = getattr(sys, 'coinit_flags', None)
            try:
                sys.coinit_flags = 0
                import comtypes as com
            finally:
                if previous is None:
                    del sys.coinit_flags
                else:
                    sys.coinit_flags = previous
            if loaded:
                com.CoInitializeEx(0)
            import comtypes.client
            api = comtypes.client.GetModule('UIAutomationCore.dll')
            automation = comtypes.client.CreateObject(api.CUIAutomation, interface=api.IUIAutomation)
            try:
                options = automation.QueryInterface(api.IUIAutomation2)
                options.ConnectionTimeout = 1000
                options.TransactionTimeout = 1000
            except (AttributeError, com.COMError):
                pass
            while not self._stop_event.is_set():
                self._scan_targets(automation)
                self._stop_event.wait(self.interval)
        except Exception as exc:
            self._failure(exc)
        finally:
            if com is not None:
                com.CoUninitialize()

    @staticmethod
    def _scan(automation, hwnd):
        root = automation.ElementFromHandle(hwnd)
        def rect(element):
            r = element.CurrentBoundingRectangle
            return (r.left, r.top, r.right, r.bottom)
        bounds = rect(root)
        items = root.FindAll(4, automation.CreateTrueCondition())  # TreeScope_Descendants
        elements = []
        for index in range(items.Length):
            element = items.GetElement(index)
            cls = element.CurrentClassName
            pid = element.CurrentProcessId
            if cls.startswith('Tk') or pid == os.getpid():
                continue
            elements.append((element.CurrentAutomationId, cls, rect(element), pid))
        return build_regions(hwnd, bounds, elements, os.getpid())
