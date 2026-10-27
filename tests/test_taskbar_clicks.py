"""Real Win32 regression on an isolated Tk parent, never Shell_TrayWnd."""
import ast
import ctypes
from ctypes import wintypes
from pathlib import Path
from typing import Any
import tkinter as tk
import unittest
from unittest.mock import Mock

from taskbar_space import choose_layout
from usage_limits import load_limits, load_preferences, usage_color, DEFAULT_LIMITS


def namespace() -> dict[str, Any]:
    tree = ast.parse(Path('sys_monitor.py').read_text(encoding='utf-8'))
    start = next(i for i, n in enumerate(tree.body)
                 if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_u32' for t in n.targets))
    end = next(i for i, n in enumerate(tree.body) if isinstance(n, ast.ClassDef) and n.name == 'TaskbarEmbedder')
    nodes = tree.body[start:end+1]
    nodes += [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MonitorWindow']
    ns = dict(ctypes=ctypes, wintypes=wintypes, tk=tk, _log_event=Mock(),
              choose_layout=choose_layout, configparser=__import__('configparser'), Metrics=object,
              load_limits=load_limits, load_preferences=load_preferences, usage_color=usage_color, DEFAULT_LIMITS=DEFAULT_LIMITS)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'sys_monitor.py', 'exec'), ns)
    return ns


class TaskbarClickTests(unittest.TestCase):
    def test_catcher_and_text_share_menu_and_win32_cursor(self):
        ns = namespace()
        ns['tk'] = Mock()
        ns['_u32'] = Mock()
        def cursor(pointer):
            point = ctypes.cast(pointer, ctypes.POINTER(wintypes.POINT)).contents
            point.x, point.y = 123, 456
            return True
        ns['_u32'].GetCursorPos.side_effect = cursor
        window = ns['MonitorWindow'].__new__(ns['MonitorWindow'])
        window.root, window.master, window.click_catcher = Mock(), Mock(), Mock()
        window.mode, window.ping_enabled, window.ping_monitor = 'taskbar', False, None
        window.metrics = Mock()
        window.metrics.snapshot.return_value = {'lhm_reachable': None}
        window._bind_menu()
        callback = window.root.bind.call_args.args[1]
        window.click_catcher.bind.assert_called_once_with('<Button-3>', callback)
        callback(Mock(x_root=-999, y_root=-999))
        ns['tk'].Menu.return_value.tk_popup.assert_called_once_with(123, 456)

    def test_background_hit_is_widget_not_parent(self):
        ns = namespace()
        root = tk.Tk()
        root.geometry('500x80+80+80')
        root.attributes('-topmost', True)
        root.lift()
        root.update()
        u32 = ns['_u32']
        parent = u32.GetParent(root.winfo_id())
        ns['find_taskbar'] = lambda: (parent, None)
        window = ns['MonitorWindow'].__new__(ns['MonitorWindow'])
        window.master = root
        window.root = tk.Toplevel(root)
        window.root.overrideredirect(True)
        window.root.configure(bg=ns['EMBED_KEY_COLOR'])
        window.embed_width = 250
        window._layout_embedded = Mock()
        window.embed_failed = False
        window.click_catcher = None
        try:
            window._embed_in_taskbar()
            root.update()
            rect = ns['_win_rect'](window.embedder.hwnd)
            u32.WindowFromPoint.argtypes = [wintypes.POINT]
            u32.WindowFromPoint.restype = wintypes.HWND
            hit = u32.WindowFromPoint(wintypes.POINT(rect.left+10, rect.top+10))
            owned = [window.embedder.hwnd, window.root.winfo_id()]
            if window.click_catcher is not None:
                owned += [window.click_catcher.winfo_id(), u32.GetParent(window.click_catcher.winfo_id())]
            if hit not in owned:
                self.assertIn(hit, (parent, root.winfo_id()), 'test parent is obscured by an unrelated window')
            self.assertIn(hit, owned, 'transparent background passed the hit to the parent instead of SysMonitor')
        finally:
            if window.click_catcher is not None:
                window.click_catcher.destroy()
            window.root.destroy()
            root.destroy()
