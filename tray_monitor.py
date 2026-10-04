"""
tray_monitor.py — SysMonitor, tray-icon edition.

Replaces the floating always-on-top window (sys_monitor.py) with real
Windows notification-area icons, rendered with dynamic text via GDI +
Shell_NotifyIcon — the same technique TrafficMonitor/NetSpeedMonitor use.

Why this exists (systematic-debugging root cause, see sys_monitor.py's
_dock_to_taskbar docstring for the earlier investigation): Explorer's
Shell_TrayWnd always wins the taskbar's own screen rectangle in composition,
even against a WS_EX_TOPMOST window — so no floating window can reliably sit
"inside" the taskbar. A tray icon has no such problem: it IS part of the
taskbar, composited by Explorer itself, so there's no z-order fight.

Trade-off accepted: each icon is only 16x16px (this system's small-icon
size), so metrics are split across 3 icons instead of one wide strip:
  - Icon 1: net upload / download (compact units, K/M)
  - Icon 2: CPU usage% / temp°
  - Icon 3: GPU usage% / temp° (falls back to MEM% if no GPU reading)
Hover tooltip on each icon shows the full picture as text for anyone who
wants more precision than the tiny bitmap can render.
"""
import sys
import time
import ctypes
from ctypes import wintypes
import traceback
import threading
from pathlib import Path
from datetime import datetime

from metrics_collector import Metrics, Collector

APP_NAME = "SysMonitorTray"
CRASH_LOG_PATH = Path(__file__).with_name("crash.log")

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32


# ---------------------------------------------------------------------------
# Crash logging (same pattern as sys_monitor.py — DEBUG-9f3a lineage)
# ---------------------------------------------------------------------------
def _log_crash(kind: str, exc_type, exc_value, exc_tb):
    try:
        with open(CRASH_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n--- {kind} crash at {datetime.now().isoformat()} ---\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    except Exception:
        pass


def _install_crash_logging():
    def excepthook(exc_type, exc_value, exc_tb):
        _log_crash("main-thread", exc_type, exc_value, exc_tb)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def thread_excepthook(args):
        _log_crash(f"thread({args.thread.name})", args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook


_install_crash_logging()


def hide_console_window():
    try:
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


hide_console_window()


def ensure_single_instance():
    mutex = kernel32.CreateMutexW(None, False, f"Global\\{APP_NAME}_SingleInstance")
    if ctypes.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        print(f"{APP_NAME} already running. Exiting.")
        sys.exit(0)
    return mutex


# ---------------------------------------------------------------------------
# Win32 plumbing for Shell_NotifyIcon with correctly-typed signatures
# (PoC lesson: untyped ctypes calls silently truncate 64-bit HWNDs/HICONs
# on some APIs — always set argtypes/restype for anything handle-shaped).
# ---------------------------------------------------------------------------
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 1
WM_DESTROY = 0x0002
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205

NIF_ICON = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_TIP = 0x00000004
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

user32.DefWindowProcW.restype = ctypes.c_long
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.RegisterClassW.restype = wintypes.ATOM
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.c_void_p]
user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
user32.CreateIconIndirect.restype = wintypes.HICON
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.UINT]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.CreateFontW.restype = wintypes.HFONT
gdi32.CreateBitmap.restype = wintypes.HBITMAP
gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP),
    ]


user32.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]


def make_text_icon(lines, w, h, color=0x00FFFFFF):
    """Render `lines` (top-to-bottom strings) into a transparent 32bpp icon.

    PoC lesson kept here verbatim: GDI text drawing does not set the alpha
    channel, so drawn text is invisible unless we manually walk the pixel
    buffer afterwards and set alpha = max(R,G,B) (coverage-based AA -> alpha).
    """
    hdc_screen = user32.GetDC(None)
    hdc = gdi32.CreateCompatibleDC(hdc_screen)

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h  # top-down DIB
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0  # BI_RGB

    ppv_bits = ctypes.c_void_p()
    hbm_color = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(ppv_bits), None, 0)
    old_bmp = gdi32.SelectObject(hdc, hbm_color)

    line_h = max(6, h // max(1, len(lines)))
    font = gdi32.CreateFontW(-line_h, 0, 0, 0, 700, 0, 0, 0, 0, 0, 0, 0, 0, "Segoe UI")
    old_font = gdi32.SelectObject(hdc, font)
    gdi32.SetBkMode(hdc, 1)  # TRANSPARENT
    gdi32.SetTextColor(hdc, color)

    DT_CENTER, DT_VCENTER, DT_SINGLELINE, DT_NOCLIP = 1, 4, 32, 256
    for i, text in enumerate(lines):
        rect = wintypes.RECT(0, i * line_h, w, (i + 1) * line_h)
        user32.DrawTextW(hdc, text, -1, ctypes.byref(rect), DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOCLIP)

    gdi32.SelectObject(hdc, old_font)
    gdi32.DeleteObject(font)
    gdi32.SelectObject(hdc, old_bmp)

    buf = ctypes.cast(ppv_bits, ctypes.POINTER(ctypes.c_ubyte * (w * h * 4))).contents
    for px in range(w * h):
        off = px * 4
        b, g, r = buf[off], buf[off + 1], buf[off + 2]
        buf[off + 3] = max(b, g, r)

    hbm_mask = gdi32.CreateBitmap(w, h, 1, 1, None)
    ii = ICONINFO()
    ii.fIcon = True
    ii.hbmMask = hbm_mask
    ii.hbmColor = hbm_color
    hicon = user32.CreateIconIndirect(ctypes.byref(ii))

    gdi32.DeleteObject(hbm_mask)
    gdi32.DeleteObject(hbm_color)
    gdi32.DeleteDC(hdc)
    user32.ReleaseDC(None, hdc_screen)
    return hicon


def fmt_compact(bytes_per_sec: float) -> str:
    """Compact throughput label that fits an 8px-tall icon line, e.g. '1.2M'."""
    kbps = (bytes_per_sec * 8) / 1000
    if kbps < 1000:
        return f"{kbps:.0f}K"
    mbps = kbps / 1000
    return f"{mbps:.1f}M"


def fmt_speed_full(bytes_per_sec: float) -> str:
    mbps = (bytes_per_sec * 8) / 1_000_000
    if mbps < 1:
        kbps = (bytes_per_sec * 8) / 1_000
        return f"{kbps:.0f} Kbps"
    return f"{mbps:.1f} Mbps"


TPM_LEFTALIGN = 0x0000
TPM_RETURNCMD = 0x0100
MF_STRING = 0x0000
IDM_EXIT = 1001

user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_uint, wintypes.LPCWSTR]
user32.TrackPopupMenu.argtypes = [
    wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p,
]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.DestroyMenu.argtypes = [wintypes.HMENU]


def show_exit_menu(hwnd):
    """Right-click context menu, mirroring sys_monitor.py's single
    'Fechar' item — left-click intentionally does nothing (an accidental
    left-click must never silently kill the monitor)."""
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    menu = user32.CreatePopupMenu()
    user32.AppendMenuW(menu, MF_STRING, IDM_EXIT, "Fechar")
    # Required so the menu dismisses itself on an outside click (MSDN TrackPopupMenu note).
    user32.SetForegroundWindow(hwnd)
    cmd = user32.TrackPopupMenu(menu, TPM_LEFTALIGN | TPM_RETURNCMD, pt.x, pt.y, 0, hwnd, None)
    user32.DestroyMenu(menu)
    return cmd == IDM_EXIT


class TrayIconSlot:
    """One Shell_NotifyIcon slot: owns its NOTIFYICONDATA and current HICON,
    and knows how to refresh its bitmap+tooltip from a render callback."""

    def __init__(self, hwnd, uid, render_fn):
        self.uid = uid
        self.render_fn = render_fn
        self._current_icon = None
        self.nid = NOTIFYICONDATA()
        self.nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        self.nid.hWnd = hwnd
        self.nid.uID = uid
        self.nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP
        self.nid.uCallbackMessage = WM_TRAYICON

    def add(self, icon_w, icon_h, m):
        lines, tooltip = self.render_fn(m)
        self._current_icon = make_text_icon(lines, icon_w, icon_h)
        self.nid.hIcon = self._current_icon
        self.nid.szTip = tooltip
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self.nid))

    def update(self, icon_w, icon_h, m):
        lines, tooltip = self.render_fn(m)
        new_icon = make_text_icon(lines, icon_w, icon_h)
        old_icon = self._current_icon
        self.nid.hIcon = new_icon
        self.nid.szTip = tooltip
        self._current_icon = new_icon
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self.nid))
        if old_icon:
            user32.DestroyIcon(old_icon)

    def remove(self):
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))
        if self._current_icon:
            user32.DestroyIcon(self._current_icon)
            self._current_icon = None


def render_net(m):
    up = fmt_compact(m["up_speed"])
    down = fmt_compact(m["down_speed"])
    lines = [f"↑{up}", f"↓{down}"]
    tooltip = f"Rede: ↑ {fmt_speed_full(m['up_speed'])}  ↓ {fmt_speed_full(m['down_speed'])}"
    return lines, tooltip


def render_cpu(m):
    cpu = f"{m['cpu_percent']:.0f}%"
    temp = f"{m['cpu_temp']:.0f}°" if m["cpu_temp"] is not None else "--"
    lines = [cpu, temp]
    tooltip = f"CPU: {m['cpu_percent']:.0f}%  {temp}"
    if not m["hwinfo_ok"] and m["hwinfo_error"]:
        tooltip += "\n⚠ HWiNFO64 não está rodando (sem leitura de temperatura)"
    return lines, tooltip


def render_gpu_mem(m):
    if m["gpu_usage"] is not None:
        gpu = f"{m['gpu_usage']:.0f}%"
        gtemp = f"{m['gpu_temp']:.0f}°" if m["gpu_temp"] is not None else "--"
        lines = [gpu, gtemp]
        tooltip = f"GPU: {gpu}  {gtemp}   |   MEM: {m['mem_percent']:.0f}%"
    else:
        # No GPU reading (HWiNFO off or no dGPU exposed) — fall back to
        # showing memory, which is always available via psutil.
        lines = [f"{m['mem_percent']:.0f}%", "MEM"]
        tooltip = f"MEM: {m['mem_percent']:.0f}%"
        if not m["hwinfo_ok"] and m["hwinfo_error"]:
            tooltip += "\n⚠ HWiNFO64 não está rodando (sem leitura de GPU)"
    return lines, tooltip


_wndproc_ref = None  # keep the ctypes callback alive for the process lifetime


def run():
    mutex = ensure_single_instance()  # noqa: F841

    metrics = Metrics()
    collector = Collector(metrics, interval_s=1.0)
    collector.start()

    hInstance = kernel32.GetModuleHandleW(None)

    def wnd_proc(hwnd, msg, wparam, lparam):
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        if msg == WM_TRAYICON:
            event = lparam & 0xFFFF
            if event == WM_RBUTTONUP:
                if show_exit_menu(hwnd):
                    user32.DestroyWindow(hwnd)
                return 0
            # WM_LBUTTONUP intentionally does nothing — an accidental
            # left-click must never silently kill the monitor.
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    global _wndproc_ref
    _wndproc_ref = WNDPROC(wnd_proc)

    wc = WNDCLASS()
    wc.lpfnWndProc = _wndproc_ref
    wc.hInstance = hInstance
    wc.lpszClassName = APP_NAME + "Wnd"
    user32.RegisterClassW(ctypes.byref(wc))

    hwnd = user32.CreateWindowExW(
        0, APP_NAME + "Wnd", APP_NAME, 0, 0, 0, 0, 0, None, None, hInstance, None
    )

    SM_CXSMICON, SM_CYSMICON = 49, 50
    icon_w = user32.GetSystemMetrics(SM_CXSMICON)
    icon_h = user32.GetSystemMetrics(SM_CYSMICON)

    slots = [
        TrayIconSlot(hwnd, 1, render_net),
        TrayIconSlot(hwnd, 2, render_cpu),
        TrayIconSlot(hwnd, 3, render_gpu_mem),
    ]

    # Wait one collector tick so the first icons show real data, not zeros.
    time.sleep(1.1)
    m0 = metrics.snapshot()
    for slot in slots:
        slot.add(icon_w, icon_h, m0)

    def refresh_loop():
        while True:
            time.sleep(1.0)
            m = metrics.snapshot()
            for slot in slots:
                try:
                    slot.update(icon_w, icon_h, m)
                except Exception:
                    _log_crash("refresh_loop", *sys.exc_info())

    refresher = threading.Thread(target=refresh_loop, daemon=True)
    refresher.start()

    try:
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        for slot in slots:
            slot.remove()
        collector.stop()


if __name__ == "__main__":
    run()
