"""Cell HWND refusal on an isolated Win32 parent; never use Explorer."""
import ast
import configparser
import ctypes
from ctypes import wintypes
from pathlib import Path
import threading
import tkinter as tk
import tkinter.font as tkfont
import unittest
from unittest.mock import Mock

import net_split as net
import ping_monitor as pm
from taskbar_space import SpaceSnapshot
from test_taskbar_clicks import namespace
from test_ping_views import load_definitions


class NetCellWindowTests(unittest.TestCase):
    def setUp(self):
        self.ns = ns = namespace()
        load_definitions('sys_monitor.py', {'Metrics', 'fmt_temp', 'fmt_speed'}, ns)
        ns.update(threading=threading, tkfont=tkfont, APP_NAME='Cell HWND test',
                  ping_settings=pm.ping_settings, initial_ping_family=pm.initial_ping_family,
                  net_column_width=net.net_column_width)
        self.master = tk.Tk()
        self.master.withdraw()
        self.addCleanup(self.master.destroy)
        self.errors = []
        self.master.report_callback_exception = lambda *error: self.errors.append(error)
        self.u32 = u32 = ns['_u32']
        u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
            wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        u32.CreateWindowExW.restype = wintypes.HWND
        self.parent = u32.CreateWindowExW(0, 'STATIC', 'Isolated cells', 0x90000000,
                                         80, 100, 1600, 80, None, None, None, None)
        self.assertTrue(self.parent)
        self.addCleanup(u32.DestroyWindow, self.parent)
        # No real taskbar lookup, UIA worker, session or configuration writes.
        ns['find_taskbar'] = lambda: (self.parent, None)
        monitor = Mock()
        r = ns['_win_rect'](self.parent)
        monitor.snapshot.return_value = SpaceSnapshot(self.parent,
            (r.left, r.top, r.right, r.bottom), (r.left+10, r.left+20), (r.left+30, r.right-10))
        tree = ast.parse(Path('sys_monitor.py').read_text(encoding='utf-8'))
        defaults = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == 'DEFAULTS' for t in n.targets)))
        cfg = configparser.ConfigParser()
        cfg.read_dict(defaults)
        cfg['window']['net_split'] = 'true'
        cfg['ping']['enabled'] = 'false'
        self.metrics = ns['Metrics']()
        self.metrics.up_speed, self.metrics.down_speed = 125000, 250000
        self.metrics.net_rates = ((50000, 75000), (100000, 150000))
        self.window = ns['MonitorWindow'](self.master, cfg, self.metrics, 'taskbar',
            taskbar_hwnd=self.parent, session=Mock(), space_monitor=monitor)
        self.addCleanup(self.window._destroy)
        self.window.root.after_cancel(self.window._after_id)
        self.window._after_id = None
        self.window._apply_space_level(1)
        self.tick()
        self.assertFalse(self.window._net_active)
        self.ns['_log_event'].reset_mock()
        self.refusals = 0
        self.hook = None
        self.addCleanup(self.remove_hook)

    def tick(self):
        self.window._update_labels()
        self.master.update()
        self.assertEqual(self.errors, [])

    def refuse_cells(self):
        u32 = self.u32
        hookproc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                     wintypes.WPARAM, wintypes.LPARAM)
        u32.SetWindowsHookExW.argtypes = [ctypes.c_int, hookproc, wintypes.HINSTANCE, wintypes.DWORD]
        u32.SetWindowsHookExW.restype = wintypes.HHOOK
        u32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        u32.CallNextHookEx.restype = ctypes.c_ssize_t
        u32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        u32.UnhookWindowsHookEx.restype = wintypes.BOOL
        u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u32.GetClassNameW.restype = ctypes.c_int
        kernel = ctypes.WinDLL('kernel32')
        kernel.GetCurrentThreadId.argtypes = []
        kernel.GetCurrentThreadId.restype = wintypes.DWORD
        def proc(code, wp, lp):
            if code == 3:
                name = ctypes.create_unicode_buffer(256)
                u32.GetClassNameW(wp, name, len(name))
                if name.value.lower() == 'static':
                    self.refusals += 1
                    return 1
            return u32.CallNextHookEx(None, code, wp, lp)
        self.proc = hookproc(proc)  # Keep alive until unhooked.
        self.hook = u32.SetWindowsHookExW(5, self.proc, None, kernel.GetCurrentThreadId())
        self.assertTrue(self.hook)

    def remove_hook(self):
        if self.hook:
            self.assertTrue(self.u32.UnhookWindowsHookEx(self.hook))
            self.hook = None

    def activate(self):
        self.window._apply_space_level(0)
        self.tick()

    def assert_totals(self):
        self.assertGreater(self.refusals, 0, 'CBT hook must actually refuse a Static HWND')
        self.assertEqual(self.window._space_level, 0)
        self.assertEqual(self.window._net_cells, [])
        self.assertFalse(self.window._net_active)
        for host, accent, speed, arrow in ((self.window.lbl_up, 'accent_up', 125000, '↑'),
                                          (self.window.lbl_down, 'accent_down', 250000, '↓')):
            self.assertEqual(host.cget('text'), arrow + self.ns['fmt_speed'](speed))
            self.assertNotIn('1000.0', host.cget('text'))
            self.assertEqual(host.cget('fg'), self.window.cfg[accent])
            self.assertNotEqual(host.cget('fg'), '#010101')

    def test_taskbar_host_never_draws_placeholder_text(self):
        self.activate()
        self.assertTrue(self.window._net_active)
        for host in (self.window.lbl_up, self.window.lbl_down):
            self.assertNotIn('1000.0', host.cget('text'))
            self.assertEqual(host.cget('text'), '')

    def test_refused_cell_window_shows_totals_instead_of_placeholder(self):
        self.refuse_cells()
        self.activate()
        self.assert_totals()
        # Activation and the explicit next tick each stop at the first refusal.
        self.assertEqual(self.refusals, 2)
        for host in (self.window.lbl_up, self.window.lbl_down):
            self.assertEqual(host.winfo_children(), [])

    def test_cells_recover_on_next_tick_after_refusal(self):
        self.refuse_cells()
        self.activate()
        self.assertGreater(self.refusals, 0)
        self.remove_hook()
        self.tick()
        self.assertEqual(len(self.window._net_cells), 8)
        self.assertTrue(self.window._net_active)
        for cell in self.window._net_cells:
            self.assertNotEqual(cell.winfo_id(), 0)
            self.assertTrue(self.u32.IsWindow(cell.winfo_id()))

    def test_refusal_logged_once_until_recovery(self):
        self.refuse_cells()
        self.activate()
        for _ in range(3):
            self.tick()
        log = self.ns['_log_event']
        refusal_logs = lambda: [call for call in log.call_args_list
                               if 'net split:' in call.args[0] and 'refused' in call.args[0]]
        self.assertEqual(len(refusal_logs()), 1)
        self.remove_hook()
        self.tick()
        self.assertTrue(self.window._net_active)
        self.window._apply_space_level(1)
        self.refuse_cells()
        self.activate()
        self.assertEqual(len(refusal_logs()), 2)
        self.assert_totals()
