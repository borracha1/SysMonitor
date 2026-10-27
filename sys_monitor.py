"""
sys_monitor.py — Lightweight system monitor widget (TrafficMonitor replacement).

Shows, embedded in the Windows taskbar just left of the tray (default mode):
  - Network upload/download speed (psutil, no driver needed)
  - CPU usage % (psutil)
  - CPU temperature (LibreHardwareMonitor's local web server — needs LHM
    running; it reads the sensor via the signed PawnIO driver, HVCI-safe)
  - GPU usage % and temperature (NVIDIA's NVML — signed driver, works with
    Memory Integrity/HVCI ON)
  - Memory usage %

Display modes (config.ini -> [window] display_mode):
  - "taskbar"  : embedded INSIDE the taskbar, left of the tray chevron,
                 TrafficMonitor-style (child window of Shell_TrayWnd).
                 Falls back to "docked" for the session if embedding fails.
  - "docked"   : thin strip just ABOVE the taskbar.
  - "floating" : draggable box.

Design choices:
  - Pure stdlib GUI (tkinter) + psutil: no heavy GUI framework to install.
  - Sensor reading is best-effort (sensors.py): if LHM/NVML fail, CPU/GPU temps
    show "--" instead of crashing (mirrors the failure mode we fixed in
    TrafficMonitor, but gracefully instead of an unhandled exception).
  - Single instance enforced via a named mutex so you can't accidentally
    start it twice.
"""
import sys
import time
import ctypes
import ctypes.wintypes as wintypes
import threading
import traceback
import configparser
from app_paths import data_dir
from datetime import datetime
from typing import Any

import psutil
import tkinter as tk
import tkinter.font as tkfont

from sensors import SensorReader
from ping_monitor import (PingMonitor, ping_settings, parse_ping_groups, fmt_ping_line,
                          ping_has_problem, ping_marker, ping_column_width, initial_ping_family)
from ping_config import save_ping_settings, save_window_settings
from net_split import PacketCounters, split_rates, net_column_width
from taskbar_space import TaskbarSpaceMonitor, choose_layout
from taskbar_session import TaskbarSession
from usage_limits import load_preferences, usage_color

APP_NAME = "SysMonitor"
CONFIG_PATH = data_dir() / "config.ini"
CRASH_LOG_PATH = data_dir() / "crash.log"
EVENT_LOG_PATH = data_dir() / "sysmon.log"


# ---------------------------------------------------------------------------
# Diagnostic crash logging — DEBUG-9f3a
#
# The process was observed dying silently a few seconds after Windows boot
# (window flashes then disappears), with NO Windows Error Reporting APPCRASH
# entry for python.exe — meaning it's a normal Python process exit from an
# uncaught exception (interpreter prints traceback + exits), not an OS-level
# crash. Since the console window is hidden right after startup, that
# traceback is invisible. This logs it to crash.log instead, on both the
# main thread and any background thread (e.g. the Collector).
# ---------------------------------------------------------------------------
def _log_crash(kind: str, exc_type, exc_value, exc_tb):
    try:
        with open(CRASH_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n--- {kind} crash at {datetime.now().isoformat()} ---\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    except Exception:
        pass  # logging itself must never raise


def _install_crash_logging():
    def excepthook(exc_type, exc_value, exc_tb):
        _log_crash("main-thread", exc_type, exc_value, exc_tb)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def thread_excepthook(args):
        _log_crash(f"thread({args.thread.name})", args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook


_install_crash_logging()


def _log_event(msg: str):
    """Non-crash lifecycle events (embedding, Explorer restarts, fallbacks)."""
    try:
        if EVENT_LOG_PATH.exists() and EVENT_LOG_PATH.stat().st_size > 256_000:
            EVENT_LOG_PATH.unlink()
        with open(EVENT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Hide the console window (if any) as soon as we start.
#
# We intentionally run under regular python.exe (not pythonw.exe): on this
# machine, pythonw.exe's layered/alpha-blended Tkinter window silently fails
# to paint (a known Tcl/Tk-on-Windows quirk when no console is attached to
# the process). Using python.exe renders correctly, so instead we just hide
# the console window it creates, right after startup.
# ---------------------------------------------------------------------------
def hide_console_window():
    try:
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            SW_HIDE = 0
            user32.ShowWindow(hwnd, SW_HIDE)
    except Exception:
        pass  # non-fatal: worst case the console stays visible


hide_console_window()


# ---------------------------------------------------------------------------
# Single instance guard
# ---------------------------------------------------------------------------
def ensure_single_instance():
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, f"Global\\{APP_NAME}_SingleInstance")
    last_error = ctypes.GetLastError()
    ERROR_ALREADY_EXISTS = 183
    if last_error == ERROR_ALREADY_EXISTS:
        _log_crash("single-instance-exit", SystemExit, SystemExit(0),
                   None)
        print(f"{APP_NAME} already running. Exiting.")
        sys.exit(0)
    return mutex  # keep a reference alive for the process lifetime


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DEFAULTS = {
    "window": {
        # "taskbar" = embedded inside the taskbar (TrafficMonitor-style),
        # "docked" = strip just above the taskbar, "floating" = draggable box
        "display_mode": "taskbar",
        "net_split": "false",
        "x": "auto",       # "auto" = bottom-right near tray; else integer (floating mode only)
        "y": "auto",
        "opacity": "0.95",       # docked/floating only
        "always_on_top": "true",  # docked/floating only
        "font_size": "8",
        "bg_color": "#000000",   # docked/floating only (taskbar mode is transparent)
        "fg_color": "#e6e6e6",
        "accent_up": "#5fb0ff",
        "accent_down": "#ff9d5f",
        "update_interval_ms": "1000",
        "taskbar_width": "220",  # docked mode only (taskbar mode sizes itself from the font)
        "docked_height": "36",   # docked mode only
    },
    # Internet packet-loss monitor (ICMP, see ping_monitor.py)
    "ping": {
        "enabled": "true",
        "targets_v4": "8.8.8.8,1.1.1.1",
        "targets_v6": "2001:4860:4860::8888,2606:4700:4700::1111",
        "mode": "auto",
        "preferred": "ipv4",
        "return_clean_cycles": "60",
        "interval_ms": "1000",
        "timeout_ms": "1000",
        "window": "60",         # cycles in the sliding loss window (~1 min at 1 s)
        "notify": "true",       # Windows toast on loss / recovery
        "alert_after": "1",     # consecutive lost cycles before alerting
        "cooldown_s": "60",     # min seconds between loss toasts
        "mute_after_alerts": "5",  # 0 disables per-IP unstable notification muting
        "mute_window_s": "120",
        "unmute_after_s": "1800",
    },
}


def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(CONFIG_PATH, encoding="utf-8")
        # Resolve legacy keys before applying new defaults, or migration is masked.
        if not cfg.has_section("ping"):
            cfg.add_section("ping")
        settings = ping_settings(cfg["ping"])
        for key in ("targets_v4", "targets_v6"):
            cfg["ping"][key] = ",".join(settings[key])
        for section, values in DEFAULTS.items():
            if not cfg.has_section(section):
                cfg.add_section(section)
            for key, value in values.items():
                if key not in cfg[section]:
                    cfg[section][key] = value
    else:
        cfg.read_dict(DEFAULTS)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            cfg.write(f)
    return cfg


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def fmt_speed(bytes_per_sec: float) -> str:
    """Format a byte/s rate as Mbps (megabits/s, decimal — matches how
    ISPs and routers report speed: 1 Mbps = 1,000,000 bits/s)."""
    mbps = (bytes_per_sec * 8) / 1_000_000
    if mbps < 1:
        kbps = (bytes_per_sec * 8) / 1_000
        return f"{kbps:.0f} Kbps"
    return f"{mbps:.1f} Mbps"


PING_LOSS_COLOR = "#ff6b6b"


def fmt_temp(value) -> str:
    if value is None:
        return "--"
    return f"{value:.0f}"


# ---------------------------------------------------------------------------
# Taskbar geometry (Win32) — used by "docked" display mode
# ---------------------------------------------------------------------------
_user32 = ctypes.windll.user32


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


# HWND_TOPMOST re-assertion — DEBUG-9f3a follow-up (docked/floating modes)
#
# Windows keeps its own z-order *within* the topmost band. Explorer/the
# taskbar periodically re-asserts itself topmost, which silently pushes a
# top-level window behind it even though its WS_EX_TOPMOST flag never
# changes. tkinter's `-topmost` is "set once", so we re-assert every tick.
# Not needed in "taskbar" mode: there the widget is a child of the taskbar.
_HWND_TOPMOST = ctypes.wintypes.HWND(-1)
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOACTIVATE = 0x0010


def _reassert_topmost(hwnd: int):
    try:
        _user32.SetWindowPos(
            hwnd, _HWND_TOPMOST, 0, 0, 0, 0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE,
        )
    except Exception:
        pass  # best-effort; a missed re-assert just means we retry next tick


def get_taskbar_rect():
    """
    Returns the main taskbar rect (Shell_TrayWnd) plus the left edge of the
    tray notification area. Returns None if the taskbar window can't be
    found (e.g. Explorer restarting).
    """
    tray = _user32.FindWindowW("Shell_TrayWnd", None)
    if not tray:
        return None
    rect = _RECT()
    if not _user32.GetWindowRect(tray, ctypes.byref(rect)):
        return None
    notify = _user32.FindWindowExW(tray, None, "TrayNotifyWnd", None)
    notify_left = rect.right
    if notify:
        nrect = _RECT()
        if _user32.GetWindowRect(notify, ctypes.byref(nrect)):
            notify_left = nrect.left
    return {
        "left": rect.left, "top": rect.top,
        "right": rect.right, "bottom": rect.bottom,
        "height": rect.bottom - rect.top,
        "notify_left": notify_left,
    }


# ---------------------------------------------------------------------------
# Taskbar embedding — display_mode = "taskbar" (TrafficMonitor technique)
#
# TrafficMonitor's Win11 taskbar window (Win11TaskbarDlg.cpp/TaskBarDlg.cpp)
# is an ordinary window made a *child* of Shell_TrayWnd via SetParent and
# placed left of TrayNotifyWnd, with a colour-keyed transparent background.
# Being part of the taskbar's own window tree, Explorer composites it with
# the taskbar: no z-order fight, it stays visible with the Start menu open.
#
# Two details are required for it to paint (found with isolated PoCs):
#  1. After SetParent, window coordinates are relative to the taskbar, so
#     y must be 0. Using the screen y (e.g. 1392) puts the window far below
#     the 48px-tall parent, i.e. invisible — this is why the first SetParent
#     attempt looked like a failure.
#  2. WS_EX_LAYERED must be applied AFTER SetParent. A non-layered child is
#     covered by the taskbar's XAML content bridge; layered + LWA_COLORKEY
#     applied post-reparent paints on top, with the key colour transparent.
#     So no Tk "-alpha"/"-topmost" in this mode (-alpha makes the window
#     layered before the reparent).
# Colour-keyed text pixels remain click-through; an alpha=1 sibling underneath
# catches background clicks across the entire widget without an opaque panel.
#
# Caveat: a cross-process parent/child attaches input queues, so the Tk
# thread must never block (all slow I/O lives in the Collector thread).
# ---------------------------------------------------------------------------
_u32 = ctypes.WinDLL("user32", use_last_error=True)
_u32.FindWindowW.restype = wintypes.HWND
_u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_u32.FindWindowExW.restype = wintypes.HWND
_u32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
_u32.GetParent.restype = wintypes.HWND
_u32.GetParent.argtypes = [wintypes.HWND]
_u32.SetParent.restype = wintypes.HWND
_u32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
_u32.GetWindow.restype = wintypes.HWND
_u32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_u32.IsWindow.restype = wintypes.BOOL
_u32.IsWindow.argtypes = [wintypes.HWND]
_u32.GetWindowRect.restype = wintypes.BOOL
_u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
_u32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
_u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
_u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
_u32.SetLayeredWindowAttributes.restype = wintypes.BOOL
_u32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, ctypes.c_ubyte, wintypes.DWORD]
_u32.SetWindowPos.restype = wintypes.BOOL
_u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT]
_u32.GetCursorPos.restype = wintypes.BOOL
_u32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
_u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_u32.ShowWindow.restype = wintypes.BOOL
_u32.IsWindowVisible.argtypes = [wintypes.HWND]
_u32.IsWindowVisible.restype = wintypes.BOOL

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
LWA_COLORKEY = 0x1
LWA_ALPHA = 0x2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
GW_CHILD = 5

# Not pure black: TrafficMonitor notes pure-black keys break the right-click
# menu in Win11 dark mode. COLORREF is 0x00BBGGRR.
EMBED_KEY_COLOR = "#010101"
EMBED_KEY_COLORREF = 0x00010101


def _enable_dpi_awareness():
    """Per-monitor DPI awareness, so our coordinates match Explorer's
    (which is per-monitor aware) once we live inside its window tree."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _win_rect(hwnd):
    if not hwnd:
        return None
    r = wintypes.RECT()
    if not _u32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return r


def find_taskbar():
    """Returns (Shell_TrayWnd, TrayNotifyWnd) handles; either may be None."""
    tray = _u32.FindWindowW("Shell_TrayWnd", None)
    if not tray:
        return None, None
    return tray, _u32.FindWindowExW(tray, None, "TrayNotifyWnd", None)


def wait_for_taskbar(timeout_s: float, wait=None, should_stop=None) -> bool:
    """At logon (or right after an Explorer restart) the taskbar may not
    exist yet; wait for it instead of falling back immediately."""
    deadline = time.monotonic() + timeout_s
    while True:
        if should_stop is not None and should_stop():
            return False
        tray, notify = find_taskbar()
        if tray and notify:
            return True
        if time.monotonic() >= deadline:
            return False
        if wait is not None:
            wait()
        else:
            time.sleep(1)


def enumerate_secondary_taskbars():
    """Enumerate top-level secondary bars, without assuming monitor count/order."""
    result = []
    previous = None
    while True:
        hwnd = _u32.FindWindowExW(None, previous, 'Shell_SecondaryTrayWnd', None)
        if not hwnd:
            return result
        result.append(hwnd)
        previous = hwnd


class TaskbarEmbedder:
    """Keeps one top-level HWND embedded in Shell_TrayWnd, docked just left
    of TrayNotifyWnd, and re-docks it when the tray width / taskbar height
    changes or Explorer is restarted."""

    def __init__(self, hwnd: int, width: int, on_height_change=None, catcher_hwnd=None,
                 target_tray=None, managed_targets=False):
        self.target_tray = target_tray
        self.managed_targets = managed_targets
        self._hidden = False
        self.catcher_hwnd = catcher_hwnd
        self.hwnd = hwnd
        self.width = width
        self.on_height_change = on_height_change
        self.tray = None
        self._height = None
        self.space_monitor = None
        self.widths = None
        self.width_provider = None
        self.on_layout_change = None
        self._layout_key = None
        self._overflow_situations = set()
        self._positioning = False

    def embed(self) -> bool:
        tray = self.target_tray if self.target_tray is not None else find_taskbar()[0]
        if not tray:
            return False
        if self.catcher_hwnd and not self._embed_catcher(tray):
            return False
        h = self.hwnd
        # Layered must be (re)applied only after the reparent (see header).
        ex = _u32.GetWindowLongPtrW(h, GWL_EXSTYLE)
        _u32.SetWindowLongPtrW(h, GWL_EXSTYLE, ex & ~WS_EX_LAYERED)
        style = _u32.GetWindowLongPtrW(h, GWL_STYLE)
        _u32.SetWindowLongPtrW(h, GWL_STYLE, (style & ~WS_POPUP) | WS_CHILD)
        ctypes.set_last_error(0)
        _u32.SetParent(h, tray)
        if _u32.GetParent(h) != tray:
            _log_event(f"embed: SetParent refused (err={ctypes.get_last_error()})")
            _u32.SetWindowLongPtrW(h, GWL_STYLE, style)
            return False
        ex = _u32.GetWindowLongPtrW(h, GWL_EXSTYLE)
        _u32.SetWindowLongPtrW(h, GWL_EXSTYLE, ex | WS_EX_LAYERED)
        if not _u32.SetLayeredWindowAttributes(h, EMBED_KEY_COLORREF, 0, LWA_COLORKEY):
            _log_event(f"embed: SetLayeredWindowAttributes failed (err={ctypes.get_last_error()})")
        self.tray = tray
        self._height = None
        self.reposition()
        _log_event(f"embedded into taskbar (tray hwnd={tray}, width={self.width})")
        return True

    def _embed_catcher(self, tray):
        h = self.catcher_hwnd
        if not _u32.IsWindow(h):
            return False
        ex = _u32.GetWindowLongPtrW(h, GWL_EXSTYLE)
        _u32.SetWindowLongPtrW(h, GWL_EXSTYLE, ex & ~WS_EX_LAYERED)
        style = _u32.GetWindowLongPtrW(h, GWL_STYLE)
        _u32.SetWindowLongPtrW(h, GWL_STYLE, (style & ~WS_POPUP) | WS_CHILD)
        _u32.SetParent(h, tray)
        if _u32.GetParent(h) != tray:
            return False
        _u32.SetWindowLongPtrW(h, GWL_EXSTYLE, ex | WS_EX_LAYERED)
        return bool(_u32.SetLayeredWindowAttributes(h, 0, 1, LWA_ALPHA))

    def healthy(self) -> bool:
        if not self.tray or not _u32.IsWindow(self.hwnd):
            return False
        tray = self.target_tray if self.target_tray is not None else find_taskbar()[0]
        return (tray == self.tray and _u32.IsWindow(tray) and _u32.GetParent(self.hwnd) == self.tray
                and (not self.catcher_hwnd or (_u32.IsWindow(self.catcher_hwnd)
                     and _u32.GetParent(self.catcher_hwnd) == self.tray)))

    def _set_visible(self, visible):
        if self._hidden == (not visible):
            return
        self._hidden = not visible
        for hwnd in (self.hwnd, self.catcher_hwnd):
            if hwnd:
                _u32.ShowWindow(hwnd, 4 if visible else 0)  # SW_SHOWNOACTIVATE / SW_HIDE

    def reposition(self):
        if self._positioning:
            return
        self._positioning = True
        try:
            self._reposition()
        finally:
            self._positioning = False

    def _reposition(self):
        tray = self.tray
        tr = _win_rect(tray)
        if tr is None:
            return
        nr = _win_rect(_u32.FindWindowExW(tray, None, "TrayNotifyWnd", None))
        right = nr.left if (nr and nr.right > nr.left) else tr.right
        height = tr.bottom - tr.top
        x = right - tr.left - self.width  # relative to the taskbar
        snapshot = None
        if self.space_monitor is not None:
            if self.managed_targets:
                snapshot = self.space_monitor.snapshot(tray)
            else:
                self.space_monitor.set_target(tray)
                snapshot = self.space_monitor.snapshot()
            bounds = (tr.left, tr.top, tr.right, tr.bottom)
            if snapshot is not None and (snapshot.hwnd != tray or snapshot.bounds != bounds):
                snapshot = None
            if self.target_tray is not None and snapshot is None:
                self._set_visible(False)
                return
            if self.target_tray is not None:
                right = snapshot.right[1]  # No TrayNotifyWnd on secondary bars.
            widths = self.width_provider() if self.width_provider else self.widths
            if widths is not None:
                layout = choose_layout(snapshot, widths, right)
                key = (layout.side, layout.level)
                self.width = layout.width
                x = layout.x - tr.left
                if key != self._layout_key:
                    self._layout_key = key
                    if self.on_layout_change:
                        self.on_layout_change(layout.level)
                if layout.overflow and snapshot is not None:
                    situation = (tray, bounds, snapshot.left, snapshot.right, widths)
                    if situation not in self._overflow_situations:
                        self._overflow_situations.add(situation)
                        _log_event(f'taskbar: no layout fits; using right level 2: {situation}')
        if self.target_tray is not None and snapshot is None:
            self._set_visible(False)
            return
        self._set_visible(True)
        if height != self._height:
            self._height = height
            if self.on_height_change:
                self.on_height_change(height)
        cur = _win_rect(self.hwnd)
        want = (tr.left + x, tr.top, tr.left + x + self.width, tr.top + height)
        if cur is None or (cur.left, cur.top, cur.right, cur.bottom) != want:
            _u32.SetWindowPos(self.hwnd, None, x, 0, self.width, height,
                              SWP_NOZORDER | SWP_NOACTIVATE)
        if self.catcher_hwnd:
            # First raise text; then insert the catcher immediately below it.
            _u32.SetWindowPos(self.hwnd, None, 0, 0, 0, 0,
                              SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            _u32.SetWindowPos(self.catcher_hwnd, self.hwnd, x, 0, self.width, height,
                              SWP_NOACTIVATE)
        # Stay above the taskbar's own XAML content-bridge sibling.
        if _u32.GetWindow(tray, GW_CHILD) != self.hwnd:
            _u32.SetWindowPos(self.hwnd, None, 0, 0, 0, 0,
                              SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


# ---------------------------------------------------------------------------
# Data collector (runs in a background thread; GUI never blocks on I/O)
# ---------------------------------------------------------------------------
class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.up_speed = 0.0
        self.down_speed = 0.0
        self.net_rates = None
        self.cpu_percent = 0.0
        self.mem_percent = 0.0
        self.cpu_temp = None
        self.gpu_temp = None
        self.gpu_usage = None
        self.cpu_temp_error = None
        self.gpu_error = None
        self.ping: tuple[tuple[str, float, float | None, bool], ...] | None = None
        self.ping_family = "ipv4"
        self.ping_auto = True
        self.ping_other = ()

    def snapshot(self):
        with self.lock:
            return dict(
                up_speed=self.up_speed,
                down_speed=self.down_speed,
                net_rates=self.net_rates,
                cpu_percent=self.cpu_percent,
                mem_percent=self.mem_percent,
                cpu_temp=self.cpu_temp,
                gpu_temp=self.gpu_temp,
                gpu_usage=self.gpu_usage,
                cpu_temp_error=self.cpu_temp_error,
                gpu_error=self.gpu_error,
                ping=self.ping,
                ping_family=self.ping_family,
                ping_auto=self.ping_auto,
                ping_other=self.ping_other,
            )


class Collector(threading.Thread):
    def __init__(self, metrics: Metrics, interval_s: float = 1.0):
        super().__init__(daemon=True)
        self.metrics = metrics
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._sensors = SensorReader()
        self._last_net = psutil.net_io_counters()
        self._last_net_time = time.time()
        self._packets = PacketCounters(_log_event)
        self._last_packets = None

    def stop(self):
        self._stop.set()

    def run(self):
        # Prime psutil's internal CPU counter (first call after interval=None is always 0.0)
        psutil.cpu_percent(interval=None)
        while not self._stop.is_set():
            self._collect_once()
            self._stop.wait(self.interval_s)

    def _collect_once(self):
        now = time.time()
        net = psutil.net_io_counters()
        dt = max(now - self._last_net_time, 1e-6)
        up = (net.bytes_sent - self._last_net.bytes_sent) / dt
        down = (net.bytes_recv - self._last_net.bytes_recv) / dt
        self._last_net = net
        self._last_net_time = now

        cpu_percent = psutil.cpu_percent(interval=None)
        mem_percent = psutil.virtual_memory().percent

        packets = self._packets.read()
        rates = split_rates(up, down, self._last_packets, packets)
        self._last_packets = packets
        sensors = self._sensors.read()

        with self.metrics.lock:
            self.metrics.up_speed = up
            self.metrics.down_speed = down
            self.metrics.net_rates = rates
            self.metrics.cpu_percent = cpu_percent
            self.metrics.mem_percent = mem_percent
            for key, value in sensors.items():
                setattr(self.metrics, key, value)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class MonitorWindow:
    """One visible widget. Lives in a Toplevel of the process-wide hidden
    Tk root (`master`); rebuilt (new Toplevel, same Tk) after Explorer
    restarts.

    Why not a fresh tk.Tk() per rebuild: the old Tk ends up in a reference
    cycle, so Python's *cyclic GC* frees it — and GC can run on the
    Collector thread. Freeing a Tcl interpreter from a thread other than
    its creator makes Tcl abort the whole process ("Tcl_AsyncDelete: async
    handler deleted by the wrong thread", exit 3). Reproduced in isolation;
    a single long-lived Tk + per-window Toplevel does not crash."""

    def __init__(self, master: tk.Tk, cfg: configparser.ConfigParser, metrics: Metrics, mode: str, ping_monitor=None,
                 space_monitor=None, taskbar_hwnd=None, session=None):
        self.session = session
        self.taskbar_hwnd = taskbar_hwnd
        self.space_monitor = space_monitor
        self._space_level = 0
        self.master = master
        self.ping_monitor = ping_monitor
        self.reconfigure_requested = False
        self._ping_editor = None
        self.full_cfg = cfg
        self.cfg = cfg["window"]
        self.metrics = metrics
        self.mode = mode
        self.exit_requested = False  # True only when the user chose "Fechar"
        self.embed_failed = False
        self.click_catcher = None
        self.embedder = None
        self._closing = False
        self._after_id = None
        self._redock_counter = 0

        self.root = tk.Toplevel(master)
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)  # borderless
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        if self.mode == "taskbar":
            self.root.configure(bg=EMBED_KEY_COLOR)
        else:
            self.root.attributes("-topmost", self.cfg.getboolean("always_on_top"))
            self.root.attributes("-alpha", self.cfg.getfloat("opacity"))
            self.root.configure(bg=self.cfg["bg_color"])

        self._drag = {"x": 0, "y": 0}
        self.ping_enabled = cfg.getboolean("ping", "enabled", fallback=True)
        settings = ping_settings(cfg["ping"])
        self.ping_groups = {"ipv4": settings["targets_v4"], "ipv6": settings["targets_v6"]}
        self._ping_layout_family = initial_ping_family(settings["mode"], settings["preferred"], self.ping_groups)
        self.ping_timeout_ms = cfg.getint("ping", "timeout_ms", fallback=1000)
        self.ping_labels = []
        self._fg = self.cfg["fg_color"]
        self.net_split = self.cfg.getboolean("net_split", fallback=False)
        self._net_active = False
        self._net_cells = []
        try:
            self._build_ui()
            self._place_window()
            self._bind_drag()
            self._bind_menu()
        except Exception:
            if self.taskbar_hwnd is not None:
                self._destroy()
            raise

        self._after_id = self.root.after(200, self._tick)

    # -- layout ---------------------------------------------------------
    def _build_ui(self):
        if self.mode == "taskbar":
            self._build_embedded_ui()
            return

        bg = self.cfg["bg_color"]
        fg = self.cfg["fg_color"]
        font_size = self.cfg.getint("font_size")
        font = ("Segoe UI", font_size)

        frame = tk.Frame(self.root, bg=bg)
        frame.pack(fill="both", expand=True)

        if self.mode == "docked":
            # Compact horizontal layout: two columns (net / cpu+gpu) + mem
            col1 = tk.Frame(frame, bg=bg)
            col2 = tk.Frame(frame, bg=bg)
            col1.pack(side="left", fill="y", padx=(8, 4))
            col2.pack(side="left", fill="y", padx=(4, 8))

            self.lbl_up = tk.Label(col1, text="↑ --", fg=self.cfg["accent_up"], bg=bg, font=font, anchor="w")
            self.lbl_down = tk.Label(col1, text="↓ --", fg=self.cfg["accent_down"], bg=bg, font=font, anchor="w")
            self.lbl_up.pack(anchor="w")
            self.lbl_down.pack(anchor="w")

            if self.ping_enabled:
                colp = self._build_ping_panel(frame, bg, font)
                colp.pack(side="left", fill="y", padx=(4, 4), before=col2)

            self.cpu_row = self._build_hardware_row(col2, 'cpu', bg, fg, font)
            self.gpu_row = self._build_hardware_row(col2, 'gpu', bg, fg, font)
            self.cpu_row.pack(anchor="w")
            self.gpu_row.pack(anchor="w")

            self.lbl_mem = tk.Label(frame, text="MEM --%", fg=fg, bg=bg, font=font, anchor="w")
            self.lbl_mem.pack(side="left", padx=(0, 8))
            self.lbl_status = tk.Label(frame, text="", fg="#ff6b6b", bg=bg, font=("Segoe UI", 7))
            self.lbl_status.pack(side="left")
        else:
            pad = dict(padx=6, pady=1)
            self.lbl_up = tk.Label(frame, text="↑ -- KB/s", fg=self.cfg["accent_up"], bg=bg, font=font, anchor="w")
            self.lbl_down = tk.Label(frame, text="↓ -- KB/s", fg=self.cfg["accent_down"], bg=bg, font=font, anchor="w")
            if self.ping_enabled:
                self.ping_panel = self._build_ping_panel(frame, bg, font)
            self.cpu_row = self._build_hardware_row(frame, 'cpu', bg, fg, font)
            self.gpu_row = self._build_hardware_row(frame, 'gpu', bg, fg, font)
            self.lbl_mem = tk.Label(frame, text="MEM: --%", fg=fg, bg=bg, font=font, anchor="w")
            self.lbl_status = tk.Label(frame, text="", fg="#ff6b6b", bg=bg, font=("Segoe UI", 7), anchor="w")

            widgets = (self.lbl_up, self.lbl_down) + ((self.ping_panel,) if self.ping_enabled else ()) \
                + (self.cpu_row, self.gpu_row, self.lbl_mem)
            for w in widgets:
                w.pack(fill="x", **pad)
            self.lbl_status.pack(fill="x", padx=6)

            close_btn = tk.Label(frame, text="✕", fg=fg, bg=bg, font=("Segoe UI", 8), cursor="hand2")
            close_btn.place(relx=1.0, y=2, anchor="ne")
            close_btn.bind("<Button-1>", lambda e: self.quit())

    def _build_hardware_row(self, parent, metric, bg, fg, font):
        row = tk.Frame(parent, bg=bg, padx=2, pady=1)
        common: dict[str, Any] = dict(fg=fg, bg=bg, font=font, anchor="w", bd=0, padx=0, pady=0,
                      highlightthickness=0)
        prefix = metric.upper() + (': --%  ' if self.mode == 'floating' else ' --% ')
        usage = tk.Label(row, text=prefix, **common)
        temp = tk.Label(row, text='--°C' if self.mode == 'floating' else '--°', **common)
        usage.pack(side='left')
        temp.pack(side='left')
        setattr(self, 'lbl_' + metric, usage)
        setattr(self, 'lbl_' + metric + '_temp', temp)
        return row

    def _position_hardware_parts(self):
        if self.mode != 'taskbar' or not hasattr(self, 'lbl_cpu_temp'):
            return
        x, width = self._cols['hw']
        for metric in ('cpu', 'gpu'):
            usage = getattr(self, 'lbl_' + metric)
            temp = getattr(self, 'lbl_' + metric + '_temp')
            used = min(width, self.font.measure(usage.cget('text')))
            y = int(usage.place_info().get('y', 0))
            usage.place(x=x, y=y, width=used, height=self._line_h)
            temp.place(x=x + used, y=y, width=max(0, width - used), height=self._line_h)

    def _build_ping_panel(self, parent, bg, font):
        measured = tkfont.Font(root=self.root, font=font)
        width = ping_column_width(measured.measure, self.ping_groups[self._ping_layout_family], self.ping_timeout_ms)
        marker_width = measured.measure("v6·A ")
        height = measured.metrics("linespace")
        panel = tk.Frame(parent, bg=bg, width=width, height=2 * height)
        self.ping_panel = panel
        self._ping_font = measured
        panel.pack_propagate(False)
        common = dict(bg=bg, fg=self._fg, font=font, anchor="w", bd=0, padx=0, pady=0)
        self.ping_marker_label = tk.Label(panel, text="", **common)
        self.ping_marker_label.place(x=0, y=0, width=marker_width, height=height)
        self.ping_labels = [tk.Label(panel, text="", **common) for _ in range(2)]
        for index, label in enumerate(self.ping_labels):
            label.place(x=marker_width, y=index * height, width=width-marker_width, height=height)
        return panel

    def _build_embedded_ui(self):
        """Same content/format as the docked strip, laid out with fixed,
        font-measured columns on a transparent (colour-keyed) background."""
        key = EMBED_KEY_COLOR
        fg = self.cfg["fg_color"]
        self.font = tkfont.Font(root=self.root, family="Segoe UI", size=self.cfg.getint("font_size"))
        self._line_h = self.font.metrics("linespace")
        self._calculate_embedded_columns()

        common: dict[str, Any] = dict(bg=key, font=self.font, anchor="w", bd=0, padx=0, pady=0, highlightthickness=0)
        self.lbl_up = tk.Label(self.root, text="↑ --", fg=self.cfg["accent_up"], **common)
        self.lbl_down = tk.Label(self.root, text="↓ --", fg=self.cfg["accent_down"], **common)
        if self.ping_enabled:
            self.ping_marker_label = tk.Label(self.root, text="", fg=fg, **common)
            self.ping_labels = [tk.Label(self.root, text="", fg=fg, **common) for _ in range(2)]
        self.lbl_cpu = tk.Label(self.root, text="CPU --% ", fg=fg, **common)
        self.lbl_gpu = tk.Label(self.root, text="GPU --% ", fg=fg, **common)
        self.lbl_cpu_temp = tk.Label(self.root, text="--°", fg=fg, **common)
        self.lbl_gpu_temp = tk.Label(self.root, text="--°", fg=fg, **common)
        self.lbl_mem = tk.Label(self.root, text="MEM --%", fg=fg, **common)
        self.lbl_status = tk.Label(self.root, text="", fg="#ff6b6b", **common)

    def _embedded_columns(self, level):
        measure = self.font.measure
        pad, gap = 4, 10
        split = getattr(self, '_net_available', getattr(self, '_net_active', False)) and level == 0
        w_net = net_column_width(measure, split)
        w_ping = ping_column_width(
            measure, self.ping_groups[self._ping_layout_family], self.ping_timeout_ms
        ) if self.ping_enabled else 0
        self._ping_marker_width = measure("v6·A ")
        w_hw = max(measure("CPU 100% 100°"), measure("GPU 100% 100°"))
        w_mem = measure("MEM 100%")
        w_st = measure("⚠") + 2
        x_hw = pad + w_net + gap + w_ping + (gap if self.ping_enabled else 0)
        cols = {
            "net": (pad, w_net),
            "ping": (pad + w_net + gap, w_ping),
            "hw": (x_hw, w_hw),
            "mem": (x_hw + w_hw + gap, w_mem),
        }
        x_st = cols["mem"][0] + w_mem + 2 if level < 2 else x_hw + w_hw + 2
        cols["st"] = (x_st, w_st)
        return cols, x_st + w_st + pad

    def _calculate_embedded_columns(self):
        self._cols, self.embed_width = self._embedded_columns(getattr(self, '_space_level', 0))

    def _taskbar_widths(self):
        return tuple(self._embedded_columns(level)[1] for level in range(3))

    def _apply_space_level(self, level):
        if level == self._space_level:
            return
        self._space_level = level
        # Use the metrics already measured/rendered this tick. A second collector
        # snapshot here could change ping family after widths were chosen.
        if hasattr(self, '_last_metrics'):
            self._update_labels(self._last_metrics)
        self._calculate_embedded_columns()
        self._layout_embedded(self.root.winfo_height())

    def _relayout_ping(self, family):
        """Resize existing controls on the Tk thread, never rebuild/re-embed."""
        self._ping_layout_family = family
        if self.mode == "taskbar":
            self._calculate_embedded_columns()
            if self.embedder is not None:
                self.embedder.width = self.embed_width
            self._layout_embedded(self.root.winfo_height())
            if self.embedder is not None:
                self.embedder.reposition()
        else:
            width = ping_column_width(
                self._ping_font.measure, self.ping_groups[family], self.ping_timeout_ms)
            self.ping_panel.config(width=width)
            marker_width = self._ping_font.measure("v6·A ")
            for label in self.ping_labels:
                label.place_configure(width=width - marker_width)
            if self.mode == "docked":
                self._dock_to_taskbar()
            else:
                self.root.update_idletasks()
                self.root.geometry(f"{max(150, self.root.winfo_reqwidth())}x"
                                   f"{max(130, self.root.winfo_reqheight())}")

    def _layout_embedded(self, height: int):
        ls = self._line_h
        y0 = max(0, (height - 2 * ls) // 2)
        y1 = y0 + ls
        ym = max(0, (height - ls) // 2)
        placements = (
            (self.lbl_up, "net", y0), (self.lbl_down, "net", y1),
            *((label, "ping", y0 + i * ls) for i, label in enumerate(self.ping_labels)),
            (self.lbl_cpu, "hw", y0), (self.lbl_gpu, "hw", y1),
            (self.lbl_mem, "mem", ym), (self.lbl_status, "st", ym),
        )
        for lbl, col, y in placements:
            if col == 'mem' and getattr(self, '_space_level', 0) == 2:
                lbl.place_forget()
                continue
            x, w = self._cols[col]
            if col == "ping":
                x += self._ping_marker_width
                w -= self._ping_marker_width
            lbl.place(x=x, y=y, width=w, height=ls)
        self._position_hardware_parts()
        if self.ping_enabled:
            self.ping_marker_label.place(x=self._cols["ping"][0], y=y0,
                                         width=self._ping_marker_width, height=ls)

    def _place_window(self):
        self.root.update_idletasks()
        if self.mode == "taskbar":
            self._embed_in_taskbar()
        elif self.mode == "docked":
            self._dock_to_taskbar()
        else:
            w = max(150, self.root.winfo_reqwidth())
            h = max(130, self.root.winfo_reqheight())
            cfg_x, cfg_y = self.cfg["x"], self.cfg["y"]
            if cfg_x == "auto" or cfg_y == "auto":
                sw = self.root.winfo_screenwidth()
                sh = self.root.winfo_screenheight()
                x = sw - w - 20
                y = sh - h - 60
            else:
                x, y = int(cfg_x), int(cfg_y)
            self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _embed_in_taskbar(self):
        target = getattr(self, 'taskbar_hwnd', None)
        tray = target if target is not None else find_taskbar()[0]
        tr = _win_rect(tray)
        if tr is None:
            self.embed_failed = True
            return
        height = tr.bottom - tr.top
        self._layout_embedded(height)
        # Map off-screen first so the not-yet-embedded window never flashes.
        self.root.geometry(f"{self.embed_width}x{height}+-32000+-32000")
        self.root.update_idletasks()
        self.root.update()
        wrapper = _u32.GetParent(self.root.winfo_id())  # Tk's real top-level HWND
        if not wrapper:
            self.embed_failed = True
            return
        self.click_catcher = tk.Toplevel(self.master)
        self.click_catcher.overrideredirect(True)
        self.click_catcher.configure(bg=EMBED_KEY_COLOR)
        self.click_catcher.geometry(f"{self.embed_width}x{height}+-32000+-32000")
        self.click_catcher.update_idletasks()
        catcher_hwnd = _u32.GetParent(self.click_catcher.winfo_id())
        if not catcher_hwnd:
            self.embed_failed = True
            return
        self.embedder = TaskbarEmbedder(wrapper, self.embed_width,
                                       on_height_change=self._layout_embedded,
                                       catcher_hwnd=catcher_hwnd, target_tray=target,
                                       managed_targets=getattr(self, 'session', None) is not None)
        self.embedder.space_monitor = getattr(self, 'space_monitor', None)
        self.embedder.width_provider = self._taskbar_widths
        self.embedder.on_layout_change = self._apply_space_level
        if not self.embedder.embed():
            self.embed_failed = True

    def _dock_to_taskbar(self):
        """Docked mode: a thin strip directly ABOVE the taskbar. A top-level
        window overlapping the taskbar rect loses to Shell_TrayWnd in
        composition on Win11 even when TOPMOST; the in-taskbar look is the
        "taskbar" mode, which embeds as a child window instead."""
        rect = get_taskbar_rect()
        ping_width = 0
        if self.ping_enabled:
            font = tkfont.Font(root=self.root, family="Segoe UI", size=self.cfg.getint("font_size"))
            ping_width = ping_column_width(font.measure, self.ping_groups[self._ping_layout_family], self.ping_timeout_ms) + 12
        extra_net = 0
        if getattr(self, "_net_active", False):
            measure = self._net_font.measure
            extra_net = net_column_width(measure, True) - net_column_width(measure, False)
        w = self.cfg.getint("taskbar_width") + ping_width + extra_net
        if getattr(self, "_net_active", False):
            self.root.update_idletasks()
            w = max(w, self.root.winfo_reqwidth())
        h = self.cfg.getint("docked_height", fallback=36)
        if rect is None:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.root.geometry(f"{w}x{h}+{sw - w - 160}+{sh - h - 40}")
            return
        x = rect["notify_left"] - w
        y = rect["top"] - h
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _bind_drag(self):
        if self.mode != "floating":
            return  # taskbar/docked: position derives from the taskbar

        def start(e):
            self._drag["x"], self._drag["y"] = e.x, e.y

        def move(e):
            x = self.root.winfo_pointerx() - self._drag["x"]
            y = self.root.winfo_pointery() - self._drag["y"]
            self.root.geometry(f"+{x}+{y}")

        def release(e):
            self.cfg["x"] = str(self.root.winfo_x())
            self.cfg["y"] = str(self.root.winfo_y())
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                self.full_cfg.write(f)

        self.root.bind("<ButtonPress-1>", start)
        self.root.bind("<B1-Motion>", move)
        self.root.bind("<ButtonRelease-1>", release)

    def _bind_menu(self):
        # Right-click menu, scoped to this widget incarnation.
        menu = tk.Menu(self.root, tearoff=0)
        self._net_mode_var = tk.BooleanVar(master=self.master, value=getattr(self, "net_split", False))
        menu.add_checkbutton(label="Separar IPv4/IPv6 (estimado)", variable=self._net_mode_var,
                             command=self._select_net_split)
        menu.add_separator()
        if self.ping_enabled and self.ping_monitor is not None:
            self._ping_mode_var = tk.StringVar(master=self.master, value=self.ping_monitor.mode)
            for title, value in (("Automático", "auto"), ("Só IPv4", "ipv4"), ("Só IPv6", "ipv6")):
                available = value == "auto" or bool(self.ping_monitor.groups[value])
                menu.add_radiobutton(label=title, value=value, variable=self._ping_mode_var,
                                     state="normal" if available else "disabled",
                                     command=lambda mode=value: self._select_ping_mode(mode))
            menu.add_command(label="Configurar destinos…", command=self._edit_ping_targets)
            menu.add_separator()
        menu.add_command(label="Configurar limites de uso…", command=self._edit_usage_limits)
        menu.add_command(label="Fechar", command=self.quit)

        def show_menu(e):
            if self.mode == "taskbar":
                # Tk's idea of root coords is unreliable for a child of
                # another process's window; ask Windows directly.
                pt = wintypes.POINT()
                _u32.GetCursorPos(ctypes.byref(pt))
                x, y = pt.x, pt.y
            else:
                x, y = e.x_root, e.y_root
            menu.tk_popup(x, y)

        # Bound on the Toplevel (every child widget's bindtags include it),
        # not bind_all: the "all" tag is shared by the process-wide Tk and
        # would keep pointing at this window's command after a rebuild.
        self.root.bind("<Button-3>", show_menu)
        if getattr(self, "click_catcher", None) is not None:
            self.click_catcher.bind("<Button-3>", show_menu)

    def _edit_usage_limits(self):
        from usage_limits_ui import open_limits_editor
        return open_limits_editor(self.master, self.full_cfg, CONFIG_PATH)

    def _select_net_split(self):
        selected = bool(self._net_mode_var.get())
        try:
            save_window_settings(CONFIG_PATH, net_split=str(selected).lower())
        except (OSError, configparser.Error) as exc:
            self._net_mode_var.set(self.net_split)
            _log_event(f"net split: save failed: {exc}")
            return
        self.cfg["net_split"] = str(selected).lower()
        self.net_split = selected
        if getattr(self, 'session', None) is not None:
            self.session.sync_settings()
        else:
            self._update_labels()

    def _update_net_split(self, metrics):
        self._net_available = bool(getattr(self, "net_split", False) and metrics.get("net_rates") is not None)
        active = self._net_available and (self.mode != 'taskbar' or getattr(self, '_space_level', 0) == 0)
        changed = active != getattr(self, "_net_active", False)
        self._net_active = active
        if not active and not changed:
            return
        if not hasattr(self, "_net_font"):
            self._net_font = tkfont.Font(root=self.root, font=self.lbl_up.cget("font"))
        measure = self._net_font.measure
        bg = EMBED_KEY_COLOR if self.mode == "taskbar" else self.cfg["bg_color"]
        if changed:
            for cell in self._net_cells:
                cell.destroy()
            self._net_cells = []
            for host, accent in ((self.lbl_up, "accent_up"), (self.lbl_down, "accent_down")):
                host.config(fg=bg if active else self.cfg[accent])
                if active:
                    # Reserve worst-case content, then draw independently aligned cells.
                    host.config(text="↓ v4 1000.0 Mbps v6 1000.0 Mbps")
                    for _ in range(4):
                        self._net_cells.append(tk.Label(host, bg=bg, fg=self.cfg[accent],
                            font=self._net_font, anchor="w", bd=0, padx=0, pady=0))
            if self.mode == "taskbar":
                self._relayout_ping(self._ping_layout_family)
            elif self.mode == "docked":
                self._dock_to_taskbar()
            else:
                self.root.update_idletasks()
                self.root.geometry(f"{max(150, self.root.winfo_reqwidth())}x"
                                   f"{max(130, self.root.winfo_reqheight())}")
        # Relayout can reenter this method and replace/destroy the cells.
        if active != self._net_active:
            return
        if active:
            widths = (max(measure("↑ v4 "), measure("↓ v4 ")),
                      measure("1000.0 Mbps"), measure(" v6 "), measure("1000.0 Mbps"))
            for row, arrow in enumerate(("↑", "↓")):
                host = (self.lbl_up, self.lbl_down)[row]
                host.config(text="↓ v4 1000.0 Mbps v6 1000.0 Mbps", fg=bg)
                values = metrics["net_rates"][row]
                texts = (f"{arrow} v4 ", fmt_speed(values[0]), " v6 ", fmt_speed(values[1]))
                x = 0
                for col, (text, width) in enumerate(zip(texts, widths)):
                    cell = self._net_cells[row*4+col]
                    cell.config(text=text)
                    cell.place(x=x, y=0, width=width, relheight=1)
                    x += width

    def _select_ping_mode(self, mode):
        previous = self.ping_monitor.mode
        try:
            settings = {"mode": mode}
            # Do not lose legacy destinations when removing its obsolete key.
            if "targets" in self.full_cfg["ping"]:
                settings.update(targets_v4=",".join(self.ping_monitor.groups["ipv4"]),
                                targets_v6=",".join(self.ping_monitor.groups["ipv6"]))
            save_ping_settings(CONFIG_PATH, **settings)
        except (OSError, configparser.Error) as exc:
            self._ping_mode_var.set(previous)
            _log_event(f"ping: mode save failed: {exc}")
            return
        self.full_cfg["ping"].pop("targets", None)
        self.full_cfg["ping"].update(settings)
        self.ping_monitor.set_mode(mode)
        self._ping_mode_var.set(mode)
        if getattr(self, 'session', None) is not None:
            self.session.sync_settings()
        else:
            self._update_labels()
        _log_event(f"ping: mode changed to {mode}")

    def _close_ping_editor(self):
        if getattr(self, 'session', None) is not None:
            self.session.release_editor(self)
        editor, self._ping_editor = self._ping_editor, None
        if editor is not None:
            try:
                editor.destroy()
            except tk.TclError:
                pass

    def _save_ping_targets(self, values, preferred, error_label):
        try:
            v4, v6 = parse_ping_groups(values, preferred)
            settings = dict(targets_v4=",".join(v4), targets_v6=",".join(v6), preferred=preferred)
            mode = self.ping_monitor.mode
            if mode in ("ipv4", "ipv6") and not (v4 if mode == "ipv4" else v6):
                settings["mode"] = "ipv6" if mode == "ipv4" else "ipv4"
            save_ping_settings(CONFIG_PATH, **settings)
        except (ValueError, OSError, configparser.Error) as exc:
            error_label.config(text=f"Não foi possível salvar: {exc}")
            return
        # Close before touching the monitor or rebuilding its embedded window.
        self._close_ping_editor()
        self.full_cfg["ping"].pop("targets", None)
        self.full_cfg["ping"].update(settings)
        self.ping_monitor.set_groups(v4, v6, preferred)
        _log_event(f"ping: groups changed: IPv4={','.join(v4)} IPv6={','.join(v6)} preferred={preferred}")
        if getattr(self, 'session', None) is not None:
            self.session.reconfigure()
        else:
            self.reconfigure_requested = True
            self._destroy()

    def _edit_ping_targets(self):
        if self._closing or self.ping_monitor is None:
            return
        if getattr(self, 'session', None) is not None and not self.session.claim_editor(self):
            return
        if self._ping_editor is not None and self._ping_editor.winfo_exists():
            self._ping_editor.lift()
            self._ping_editor.focus_force()
            return
        # Never parent this dialog to the widget reparented into Explorer.
        editor = tk.Toplevel(self.master)
        self._ping_editor = editor
        editor.withdraw()
        editor.title("SysMonitor · destinos de ping")
        editor.attributes("-topmost", True)
        editor.resizable(False, False)
        editor.protocol("WM_DELETE_WINDOW", self._close_ping_editor)
        frame = tk.Frame(editor, padx=16, pady=12)
        frame.pack(fill="both", expand=True)
        entries = []
        groups = self.ping_monitor.groups
        targets = [*groups["ipv4"], *([""] * (2 - len(groups["ipv4"]))),
                   *groups["ipv6"], *([""] * (2 - len(groups["ipv6"])))]
        for index, title in enumerate(("IPv4 1", "IPv4 2", "IPv6 1", "IPv6 2")):
            tk.Label(frame, text=title, anchor="w").pack(fill="x")
            entry = tk.Entry(frame, width=48)
            entry.pack(fill="x", pady=(2, 8))
            if index < len(targets):
                entry.insert(0, targets[index])
            entries.append(entry)
        tk.Label(frame, text="Preferido no automático:", anchor="w").pack(fill="x")
        preferred = tk.StringVar(master=editor, value=self.ping_monitor.preferred)
        for title, value in (("IPv4", "ipv4"), ("IPv6", "ipv6")):
            tk.Radiobutton(frame, text=title, value=value, variable=preferred).pack(anchor="w")
        error = tk.Label(frame, text="", fg="red", wraplength=420, justify="left")
        error.pack(fill="x", pady=(6, 0))
        buttons = tk.Frame(frame)
        buttons.pack(anchor="e", pady=(8, 0))
        def save(event=None):
            self._save_ping_targets([entry.get() for entry in entries], preferred.get(), error)
        tk.Button(buttons, text="Salvar", command=save).pack(side="left", padx=4)
        tk.Button(buttons, text="Cancelar", command=self._close_ping_editor).pack(side="left")
        editor.bind("<Return>", save)
        editor.bind("<Escape>", lambda event: self._close_ping_editor())
        editor.update_idletasks()
        width, height = editor.winfo_reqwidth(), editor.winfo_reqheight()
        x = (editor.winfo_screenwidth() - width) // 2
        y = (editor.winfo_screenheight() - height) // 2
        editor.geometry(f"{width}x{height}+{x}+{y}")
        editor.deiconify()
        editor.lift()
        entries[0].focus_force()

    # -- lifecycle --------------------------------------------------------
    def quit(self):
        if getattr(self, 'session', None) is not None:
            self.session.quit()
            return
        self.exit_requested = True
        self._destroy()

    def _request_rebuild(self, reason: str):
        _log_event(f"window rebuild requested: {reason}")
        self._destroy()

    def _destroy(self):
        if self._closing:
            return
        self._closing = True
        self._close_ping_editor()
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        if self.click_catcher is not None:
            try:
                self.click_catcher.destroy()
            except tk.TclError:
                pass
            self.click_catcher = None
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        # Break the MonitorWindow <-> TaskbarEmbedder cycle and drop the
        # Font now, so they're freed here on the Tk thread by refcount
        # rather than later by the GC on some other thread.
        self.embedder = None
        self.font = None
        self._ping_font = None
        self._net_font = None
        self._net_cells = []
        if hasattr(self, "_net_mode_var"):
            del self._net_mode_var
        if hasattr(self, "_ping_mode_var"):
            del self._ping_mode_var
        # Secondary disposal must never interrupt the primary mainloop.
        if getattr(self, 'taskbar_hwnd', None) is None:
            self.master.quit()

    # -- update loop ------------------------------------------------------
    def _tick(self):
        if self._closing:
            return
        try:
            self._update_labels()
            self._maintain_position()
        except Exception as exc:
            if getattr(self, 'taskbar_hwnd', None) is None:
                raise
            self._request_rebuild(f'secondary update failed: {exc}')
        finally:
            if not self._closing:
                self._after_id = self.root.after(int(self.cfg["update_interval_ms"]), self._tick)

    def _update_labels(self, metrics=None):
        m = self.metrics.snapshot() if metrics is None else metrics
        self._last_metrics = m
        cpu_t = fmt_temp(m["cpu_temp"])
        gpu_t = fmt_temp(m["gpu_temp"])
        gpu_u = f"{m['gpu_usage']:.0f}" if m["gpu_usage"] is not None else "--"

        if self.mode in ("taskbar", "docked"):
            self.lbl_up.config(text=f"↑{fmt_speed(m['up_speed'])}")
            self.lbl_down.config(text=f"↓{fmt_speed(m['down_speed'])}")
            self.lbl_cpu.config(text=f"CPU {m['cpu_percent']:.0f}% ")
            self.lbl_gpu.config(text=f"GPU {gpu_u}% ")
            self.lbl_mem.config(text=f"MEM {m['mem_percent']:.0f}%")
        else:
            self.lbl_up.config(text=f"↑ {fmt_speed(m['up_speed'])}")
            self.lbl_down.config(text=f"↓ {fmt_speed(m['down_speed'])}")
            self.lbl_cpu.config(text=f"CPU: {m['cpu_percent']:.0f}%  ")
            self.lbl_gpu.config(text=f"GPU: {gpu_u}%  ")
            self.lbl_mem.config(text=f"MEM: {m['mem_percent']:.0f}%")

        cfg = self.full_cfg if hasattr(self, 'full_cfg') else configparser.ConfigParser()
        limits = load_preferences(cfg)
        for metric, text in (('cpu', cpu_t), ('gpu', gpu_t)):
            label = getattr(self, 'lbl_' + metric + '_temp', None)
            if label is not None:
                label.config(text=text + ('°C' if self.mode == 'floating' else '°'),
                             fg=usage_color(m[metric + '_temp'], limits[metric + '_temp'], self._fg, limits['colors']))
        self._position_hardware_parts()
        for label, metric, value in ((self.lbl_cpu, 'cpu', m['cpu_percent']),
                                     (self.lbl_gpu, 'gpu', m['gpu_usage']),
                                     (self.lbl_mem, 'mem', m['mem_percent'])):
            label.config(fg=usage_color(value, limits[metric], self._fg, limits['colors']))

        self._update_net_split(m)

        if self.ping_enabled:
            if m["ping_family"] != self._ping_layout_family:
                self._relayout_ping(m["ping_family"])
            results = m["ping"] or ()
            self.ping_marker_label.config(text=ping_marker(m["ping_family"], m["ping_auto"]))
            for index, label in enumerate(self.ping_labels):
                if index < len(results):
                    ip, loss, rtt, ok = results[index]
                    label.config(text=fmt_ping_line(ip, loss, rtt, ok),
                                 fg=PING_LOSS_COLOR if ping_has_problem(loss, ok) else self._fg)
                else:
                    label.config(text="", fg=self._fg)

        self.lbl_status.config(text="⚠" if (m["cpu_temp_error"] or m["gpu_error"]) else "")

    def _maintain_position(self):
        if self.mode == "taskbar":
            emb = self.embedder
            if emb is None:
                return
            if emb.healthy():
                emb.reposition()  # tracks tray width / taskbar height changes
                return
            if (not _u32.IsWindow(emb.hwnd) or
                    (emb.catcher_hwnd and not _u32.IsWindow(emb.catcher_hwnd))):
                self._request_rebuild("window handle gone")
                return
            if getattr(self, 'taskbar_hwnd', None) is not None:
                self._request_rebuild('secondary embedding lost')
                return
            tray, notify = find_taskbar()
            if tray and notify and not emb.embed():  # Explorer restarted: re-embed
                self._request_rebuild("re-embed failed")
            return  # taskbar not back yet: retry next tick

        # docked/floating: every ~5s re-check taskbar geometry (survives
        # Explorer restarts, DPI changes, monitor changes)
        self._redock_counter += 1
        if self.mode == "docked" and self._redock_counter % 5 == 0:
            self._dock_to_taskbar()
        if self.cfg.getboolean("always_on_top"):
            hwnd = self.root.winfo_id()
            parent = _user32.GetParent(hwnd)
            _reassert_topmost(parent if parent else hwnd)

    def run(self):
        # Returns when _destroy() calls master.quit() (user "Fechar", or the
        # window was lost and must be rebuilt).
        self.master.mainloop()

    @staticmethod
    def _log_tk_callback_exception(exc_type, exc_value, exc_tb):
        _log_crash("tk-callback", exc_type, exc_value, exc_tb)


def main():
    mutex = ensure_single_instance()  # noqa: F841 (keep alive)
    cfg = load_config()
    mode = cfg["window"].get("display_mode", "taskbar")
    if mode == "taskbar":
        _enable_dpi_awareness()  # must happen before any window exists
    metrics = Metrics()
    collector = Collector(metrics, interval_s=int(cfg["window"]["update_interval_ms"]) / 1000.0)
    collector.start()
    ping = PingMonitor.from_config(cfg["ping"], metrics, on_event=_log_event)
    if ping:
        ping.start()

    # ONE Tk interpreter for the whole process, created and (never) freed on
    # this thread; each widget incarnation is a Toplevel of it. See the
    # MonitorWindow docstring for the crash this prevents.
    app_root = tk.Tk()
    app_root.withdraw()
    app_root.report_callback_exception = MonitorWindow._log_tk_callback_exception

    space_monitor = TaskbarSpaceMonitor(_log_event) if mode == 'taskbar' else None
    if space_monitor is not None:
        space_monitor.start()
    session = None
    if mode == 'taskbar':
        session = TaskbarSession(app_root, cfg, metrics, ping, space_monitor, MonitorWindow,
                                 enumerate_secondary_taskbars, lambda: find_taskbar()[0], _log_event)
        session.start()
    quick_losses = 0
    window = None
    try:
        while True:
            if session is not None and session.exit_requested:
                break
            if mode == "taskbar" and not wait_for_taskbar(
                    timeout_s=60, wait=(lambda: session.wait(1000)) if session is not None else None,
                    should_stop=lambda: session is not None and session.exit_requested):
                if session is not None and session.exit_requested:
                    break
                _log_event("taskbar not found after 60s; falling back to docked mode")
                mode = "docked"
            if mode != 'taskbar' and session is not None:
                session.close()
                session = None
            started = time.monotonic()
            window = None
            window = MonitorWindow(app_root, cfg, metrics, mode, ping_monitor=ping,
                                   space_monitor=space_monitor if mode == 'taskbar' else None,
                                   session=session)
            if session is not None:
                session.attach_primary(window)
            if window.embed_failed:
                _log_event("embedding failed; falling back to docked mode for this session")
                window._destroy()
                mode = "docked"
                continue
            window.run()
            if window.exit_requested:
                break
            if window.reconfigure_requested:
                continue
            # The window went away without the user closing it: in taskbar
            # mode that means Explorer restarted and destroyed our parent.
            lived = time.monotonic() - started
            quick_losses = quick_losses + 1 if lived < 15 else 0
            _log_event(f"window lost after {lived:.0f}s (mode={mode}); rebuilding")
            if quick_losses >= 5 and mode == "taskbar":
                _log_event("window lost 5x in a row quickly; falling back to docked mode")
                mode = "docked"
            if session is not None:
                session.wait(2000)
            else:
                time.sleep(2)
    finally:
        if session is not None:
            session.close()
        if space_monitor is not None:
            space_monitor.stop()  # Never join a potentially blocked UIA provider from Tk.
        collector.stop()
        if ping:
            ping.stop()


if __name__ == "__main__":
    main()
