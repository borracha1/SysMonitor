"""
sys_monitor.py — Lightweight system monitor widget (TrafficMonitor replacement).

Shows, embedded in the Windows taskbar just left of the tray (default mode):
  - Network upload/download speed (psutil, no driver needed)
  - CPU usage % (psutil)
  - CPU temperature (HWiNFO64 shared memory — needs HWiNFO64 running)
  - GPU usage % and temperature (HWiNFO64 shared memory, via NVIDIA's
    signed driver under the hood — works with Memory Integrity/HVCI ON)
  - Memory usage %

Display modes (config.ini -> [window] display_mode):
  - "taskbar"  : embedded INSIDE the taskbar, left of the tray chevron,
                 TrafficMonitor-style (child window of Shell_TrayWnd).
                 Falls back to "docked" for the session if embedding fails.
  - "docked"   : thin strip just ABOVE the taskbar.
  - "floating" : draggable box.

Design choices:
  - Pure stdlib GUI (tkinter) + psutil: no heavy GUI framework to install.
  - HWiNFO reading is best-effort: if HWiNFO64 isn't running, CPU/GPU temps
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
from pathlib import Path
from datetime import datetime

import psutil
import tkinter as tk
import tkinter.font as tkfont

from hwinfo_reader import HWiNFOReader, READING_TYPE_TEMP, READING_TYPE_USAGE

APP_NAME = "SysMonitor"
CONFIG_PATH = Path(__file__).with_name("config.ini")
CRASH_LOG_PATH = Path(__file__).with_name("crash.log")
EVENT_LOG_PATH = Path(__file__).with_name("sysmon.log")


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
    }
}


def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read_dict(DEFAULTS)
    if CONFIG_PATH.exists():
        cfg.read(CONFIG_PATH, encoding="utf-8")
    else:
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
# Trade-off (same as TrafficMonitor): colour-keyed pixels are click-through,
# so the right-click menu opens only when clicking on the text itself.
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

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
LWA_COLORKEY = 0x1
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


def wait_for_taskbar(timeout_s: float) -> bool:
    """At logon (or right after an Explorer restart) the taskbar may not
    exist yet; wait for it instead of falling back immediately."""
    deadline = time.monotonic() + timeout_s
    while True:
        tray, notify = find_taskbar()
        if tray and notify:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(1)


class TaskbarEmbedder:
    """Keeps one top-level HWND embedded in Shell_TrayWnd, docked just left
    of TrayNotifyWnd, and re-docks it when the tray width / taskbar height
    changes or Explorer is restarted."""

    def __init__(self, hwnd: int, width: int, on_height_change=None):
        self.hwnd = hwnd
        self.width = width
        self.on_height_change = on_height_change
        self.tray = None
        self._height = None

    def embed(self) -> bool:
        tray, _ = find_taskbar()
        if not tray:
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

    def healthy(self) -> bool:
        if not self.tray or not _u32.IsWindow(self.hwnd):
            return False
        tray, _ = find_taskbar()
        return tray == self.tray and _u32.GetParent(self.hwnd) == self.tray

    def reposition(self):
        tray = self.tray
        tr = _win_rect(tray)
        if tr is None:
            return
        nr = _win_rect(_u32.FindWindowExW(tray, None, "TrayNotifyWnd", None))
        right = nr.left if (nr and nr.right > nr.left) else tr.right
        height = tr.bottom - tr.top
        x = right - tr.left - self.width  # relative to the taskbar
        if height != self._height:
            self._height = height
            if self.on_height_change:
                self.on_height_change(height)
        cur = _win_rect(self.hwnd)
        want = (tr.left + x, tr.top, tr.left + x + self.width, tr.top + height)
        if cur is None or (cur.left, cur.top, cur.right, cur.bottom) != want:
            _u32.SetWindowPos(self.hwnd, None, x, 0, self.width, height,
                              SWP_NOZORDER | SWP_NOACTIVATE)
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
        self.cpu_percent = 0.0
        self.mem_percent = 0.0
        self.cpu_temp = None
        self.gpu_temp = None
        self.gpu_usage = None
        self.hwinfo_ok = False
        self.hwinfo_error = None

    def snapshot(self):
        with self.lock:
            return dict(
                up_speed=self.up_speed,
                down_speed=self.down_speed,
                cpu_percent=self.cpu_percent,
                mem_percent=self.mem_percent,
                cpu_temp=self.cpu_temp,
                gpu_temp=self.gpu_temp,
                gpu_usage=self.gpu_usage,
                hwinfo_ok=self.hwinfo_ok,
                hwinfo_error=self.hwinfo_error,
            )


class Collector(threading.Thread):
    def __init__(self, metrics: Metrics, interval_s: float = 1.0):
        super().__init__(daemon=True)
        self.metrics = metrics
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._hwinfo = HWiNFOReader()
        self._last_net = psutil.net_io_counters()
        self._last_net_time = time.time()

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

        cpu_temp = gpu_temp = gpu_usage = None
        hwinfo_ok = False
        hwinfo_error = None
        try:
            readings = self._hwinfo.read()
            if self._hwinfo.last_error:
                hwinfo_error = self._hwinfo.last_error
            elif readings:
                hwinfo_ok = True
                r_cpu = (
                    self._hwinfo.find(readings, "tctl", reading_type=READING_TYPE_TEMP)
                    or self._hwinfo.find(readings, "cpu package", reading_type=READING_TYPE_TEMP)
                    or self._hwinfo.find(readings, "cpu (", reading_type=READING_TYPE_TEMP)
                )
                r_gpu_t = self._hwinfo.find(readings, "gpu", reading_type=READING_TYPE_TEMP)
                r_gpu_u = (
                    self._hwinfo.find(readings, "núcleo da gpu", reading_type=READING_TYPE_USAGE)
                    or self._hwinfo.find(readings, "gpu", "core", reading_type=READING_TYPE_USAGE)
                    or self._hwinfo.find(readings, "gpu", "utilization", reading_type=READING_TYPE_USAGE)
                    or self._hwinfo.find(readings, "gpu", "utilização", reading_type=READING_TYPE_USAGE)
                )
                cpu_temp = r_cpu.value if r_cpu else None
                gpu_temp = r_gpu_t.value if r_gpu_t else None
                gpu_usage = r_gpu_u.value if r_gpu_u else None
        except Exception as e:  # never let a sensor hiccup kill the collector thread
            hwinfo_error = f"unexpected error: {e}"

        with self.metrics.lock:
            self.metrics.up_speed = up
            self.metrics.down_speed = down
            self.metrics.cpu_percent = cpu_percent
            self.metrics.mem_percent = mem_percent
            self.metrics.cpu_temp = cpu_temp
            self.metrics.gpu_temp = gpu_temp
            self.metrics.gpu_usage = gpu_usage
            self.metrics.hwinfo_ok = hwinfo_ok
            self.metrics.hwinfo_error = hwinfo_error


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

    def __init__(self, master: tk.Tk, cfg: configparser.ConfigParser, metrics: Metrics, mode: str):
        self.master = master
        self.full_cfg = cfg
        self.cfg = cfg["window"]
        self.metrics = metrics
        self.mode = mode
        self.exit_requested = False  # True only when the user chose "Fechar"
        self.embed_failed = False
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
        self._build_ui()
        self._place_window()
        self._bind_drag()
        self._bind_menu()

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

            self.lbl_cpu = tk.Label(col2, text="CPU --%", fg=fg, bg=bg, font=font, anchor="w")
            self.lbl_gpu = tk.Label(col2, text="GPU --%", fg=fg, bg=bg, font=font, anchor="w")
            self.lbl_cpu.pack(anchor="w")
            self.lbl_gpu.pack(anchor="w")

            self.lbl_mem = tk.Label(frame, text="MEM --%", fg=fg, bg=bg, font=font, anchor="w")
            self.lbl_mem.pack(side="left", padx=(0, 8))
            self.lbl_status = tk.Label(frame, text="", fg="#ff6b6b", bg=bg, font=("Segoe UI", 7))
            self.lbl_status.pack(side="left")
        else:
            pad = dict(padx=6, pady=1)
            self.lbl_up = tk.Label(frame, text="↑ -- KB/s", fg=self.cfg["accent_up"], bg=bg, font=font, anchor="w")
            self.lbl_down = tk.Label(frame, text="↓ -- KB/s", fg=self.cfg["accent_down"], bg=bg, font=font, anchor="w")
            self.lbl_cpu = tk.Label(frame, text="CPU: --%  --°C", fg=fg, bg=bg, font=font, anchor="w")
            self.lbl_gpu = tk.Label(frame, text="GPU: --%  --°C", fg=fg, bg=bg, font=font, anchor="w")
            self.lbl_mem = tk.Label(frame, text="MEM: --%", fg=fg, bg=bg, font=font, anchor="w")
            self.lbl_status = tk.Label(frame, text="", fg="#ff6b6b", bg=bg, font=("Segoe UI", 7), anchor="w")

            for w in (self.lbl_up, self.lbl_down, self.lbl_cpu, self.lbl_gpu, self.lbl_mem):
                w.pack(fill="x", **pad)
            self.lbl_status.pack(fill="x", padx=6)

            close_btn = tk.Label(frame, text="✕", fg=fg, bg=bg, font=("Segoe UI", 8), cursor="hand2")
            close_btn.place(relx=1.0, y=2, anchor="ne")
            close_btn.bind("<Button-1>", lambda e: self.quit())

    def _build_embedded_ui(self):
        """Same content/format as the docked strip, laid out with fixed,
        font-measured columns on a transparent (colour-keyed) background."""
        key = EMBED_KEY_COLOR
        fg = self.cfg["fg_color"]
        self.font = tkfont.Font(root=self.root, family="Segoe UI", size=self.cfg.getint("font_size"))
        measure = self.font.measure
        self._line_h = self.font.metrics("linespace")
        pad, gap = 4, 10
        w_net = measure("↓1000.0 Mbps")
        w_hw = max(measure("CPU 100% 100°"), measure("GPU 100% 100°"))
        w_mem = measure("MEM 100%")
        w_st = measure("⚠") + 2
        self._cols = {
            "net": (pad, w_net),
            "hw": (pad + w_net + gap, w_hw),
            "mem": (pad + w_net + gap + w_hw + gap, w_mem),
        }
        x_st = self._cols["mem"][0] + w_mem + 2
        self._cols["st"] = (x_st, w_st)
        self.embed_width = x_st + w_st + pad

        common = dict(bg=key, font=self.font, anchor="w", bd=0, padx=0, pady=0, highlightthickness=0)
        self.lbl_up = tk.Label(self.root, text="↑ --", fg=self.cfg["accent_up"], **common)
        self.lbl_down = tk.Label(self.root, text="↓ --", fg=self.cfg["accent_down"], **common)
        self.lbl_cpu = tk.Label(self.root, text="CPU --%", fg=fg, **common)
        self.lbl_gpu = tk.Label(self.root, text="GPU --%", fg=fg, **common)
        self.lbl_mem = tk.Label(self.root, text="MEM --%", fg=fg, **common)
        self.lbl_status = tk.Label(self.root, text="", fg="#ff6b6b", **common)

    def _layout_embedded(self, height: int):
        ls = self._line_h
        y0 = max(0, (height - 2 * ls) // 2)
        y1 = y0 + ls
        ym = max(0, (height - ls) // 2)
        placements = (
            (self.lbl_up, "net", y0), (self.lbl_down, "net", y1),
            (self.lbl_cpu, "hw", y0), (self.lbl_gpu, "hw", y1),
            (self.lbl_mem, "mem", ym), (self.lbl_status, "st", ym),
        )
        for lbl, col, y in placements:
            x, w = self._cols[col]
            lbl.place(x=x, y=y, width=w, height=ls)

    def _place_window(self):
        self.root.update_idletasks()
        if self.mode == "taskbar":
            self._embed_in_taskbar()
        elif self.mode == "docked":
            self._dock_to_taskbar()
        else:
            w, h = 150, 130
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
        tray, _ = find_taskbar()
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
        self.embedder = TaskbarEmbedder(wrapper, self.embed_width, on_height_change=self._layout_embedded)
        if not self.embedder.embed():
            self.embed_failed = True

    def _dock_to_taskbar(self):
        """Docked mode: a thin strip directly ABOVE the taskbar. A top-level
        window overlapping the taskbar rect loses to Shell_TrayWnd in
        composition on Win11 even when TOPMOST; the in-taskbar look is the
        "taskbar" mode, which embeds as a child window instead."""
        rect = get_taskbar_rect()
        w = self.cfg.getint("taskbar_width")
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
        # Right-click context menu (minimal: quit)
        menu = tk.Menu(self.root, tearoff=0)
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

    # -- lifecycle --------------------------------------------------------
    def quit(self):
        self.exit_requested = True
        self._destroy()

    def _request_rebuild(self, reason: str):
        _log_event(f"window rebuild requested: {reason}")
        self._destroy()

    def _destroy(self):
        if self._closing:
            return
        self._closing = True
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        # Break the MonitorWindow <-> TaskbarEmbedder cycle and drop the
        # Font now, so they're freed here on the Tk thread by refcount
        # rather than later by the GC on some other thread.
        self.embedder = None
        self.font = None
        # The hidden process-wide root keeps mainloop alive; leave it.
        self.master.quit()

    # -- update loop ------------------------------------------------------
    def _tick(self):
        if self._closing:
            return
        try:
            self._update_labels()
            self._maintain_position()
        finally:
            if not self._closing:
                self._after_id = self.root.after(int(self.cfg["update_interval_ms"]), self._tick)

    def _update_labels(self):
        m = self.metrics.snapshot()
        cpu_t = fmt_temp(m["cpu_temp"])
        gpu_t = fmt_temp(m["gpu_temp"])
        gpu_u = f"{m['gpu_usage']:.0f}" if m["gpu_usage"] is not None else "--"

        if self.mode in ("taskbar", "docked"):
            self.lbl_up.config(text=f"↑{fmt_speed(m['up_speed'])}")
            self.lbl_down.config(text=f"↓{fmt_speed(m['down_speed'])}")
            self.lbl_cpu.config(text=f"CPU {m['cpu_percent']:.0f}% {cpu_t}°")
            self.lbl_gpu.config(text=f"GPU {gpu_u}% {gpu_t}°")
            self.lbl_mem.config(text=f"MEM {m['mem_percent']:.0f}%")
        else:
            self.lbl_up.config(text=f"↑ {fmt_speed(m['up_speed'])}")
            self.lbl_down.config(text=f"↓ {fmt_speed(m['down_speed'])}")
            self.lbl_cpu.config(text=f"CPU: {m['cpu_percent']:.0f}%  {cpu_t}°C")
            self.lbl_gpu.config(text=f"GPU: {gpu_u}%  {gpu_t}°C")
            self.lbl_mem.config(text=f"MEM: {m['mem_percent']:.0f}%")

        self.lbl_status.config(text="⚠" if (not m["hwinfo_ok"] and m["hwinfo_error"]) else "")

    def _maintain_position(self):
        if self.mode == "taskbar":
            emb = self.embedder
            if emb is None:
                return
            if emb.healthy():
                emb.reposition()  # tracks tray width / taskbar height changes
                return
            if not _u32.IsWindow(emb.hwnd):
                self._request_rebuild("window handle gone")
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

    # ONE Tk interpreter for the whole process, created and (never) freed on
    # this thread; each widget incarnation is a Toplevel of it. See the
    # MonitorWindow docstring for the crash this prevents.
    app_root = tk.Tk()
    app_root.withdraw()
    app_root.report_callback_exception = MonitorWindow._log_tk_callback_exception

    quick_losses = 0
    window = None
    try:
        while True:
            if mode == "taskbar" and not wait_for_taskbar(timeout_s=60):
                _log_event("taskbar not found after 60s; falling back to docked mode")
                mode = "docked"
            started = time.monotonic()
            window = None
            window = MonitorWindow(app_root, cfg, metrics, mode)
            if window.embed_failed:
                _log_event("embedding failed; falling back to docked mode for this session")
                window._destroy()
                mode = "docked"
                continue
            window.run()
            if window.exit_requested:
                break
            # The window went away without the user closing it: in taskbar
            # mode that means Explorer restarted and destroyed our parent.
            lived = time.monotonic() - started
            quick_losses = quick_losses + 1 if lived < 15 else 0
            _log_event(f"window lost after {lived:.0f}s (mode={mode}); rebuilding")
            if quick_losses >= 5 and mode == "taskbar":
                _log_event("window lost 5x in a row quickly; falling back to docked mode")
                mode = "docked"
            time.sleep(2)
    finally:
        collector.stop()


if __name__ == "__main__":
    main()
