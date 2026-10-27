"""Per-monitor taskbar-side preferences, independent of Tk."""
import ctypes
from ctypes import wintypes
import re

import ping_config


SIDES = ('auto', 'left', 'right')


def screen_key(device):
    if not device:
        return None
    key = re.sub(r'[^a-z0-9]', '', device.removeprefix('\\\\.\\').lower())
    return key or None


def load_side(cfg, key):
    if key is None or not cfg.has_section('taskbar_side'):
        return 'auto'
    side = cfg.get('taskbar_side', key, fallback='auto')
    return side if side in SIDES else 'auto'


def save_side(path, cfg, key, side):
    if key is None:
        return
    if side not in SIDES:
        side = 'auto'
    if side == 'auto':
        ping_config.save_settings(path, 'taskbar_side', {}, remove=(key,))
    else:
        ping_config.save_settings(path, 'taskbar_side', {key: side})
    if not cfg.has_section('taskbar_side'):
        cfg.add_section('taskbar_side')
    if side == 'auto':
        cfg.remove_option('taskbar_side', key)
    else:
        cfg['taskbar_side'][key] = side


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT),
                ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD),
                ('szDevice', wintypes.WCHAR * 32)]


def monitor_device(hwnd):
    """Return the nearest monitor's device name; never require elevation."""
    try:
        u32 = ctypes.WinDLL('user32', use_last_error=True)
        u32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        u32.MonitorFromWindow.restype = wintypes.HANDLE
        u32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFOEXW)]
        u32.GetMonitorInfoW.restype = wintypes.BOOL
        monitor = u32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        if not monitor:
            return None
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if not u32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        return info.szDevice or None
    except Exception:
        return None
