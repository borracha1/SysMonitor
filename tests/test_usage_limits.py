import configparser
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class UsageLimitsTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('usage_limits'), 'usage_limits module missing')
        import usage_limits
        return usage_limits

    def test_tray_run_wires_config_menu_and_color_callbacks(self):
        import usage_limits_ui as ui
        from unittest.mock import Mock
        self.assertTrue(hasattr(ui, 'TrayLimitsPreferences'), 'tray editor lifecycle missing')
        ns = self.tray_namespace()
        with tempfile.TemporaryDirectory() as directory:
            ns['__file__'] = str(Path(directory) / 'tray_monitor.py')
            ns['ensure_single_instance'] = Mock()
            ns['Collector'] = Mock()
            ns['PingMonitor'] = Mock()
            ns['PingMonitor'].from_config.return_value = None
            ns['threading'] = Mock()
            ns['time'] = Mock()
            ns['TrayIconSlot'] = Mock()
            ns['user32'] = Mock()
            ns['user32'].GetMessageW.return_value = 0
            ns['user32'].CreateWindowExW.return_value = 123
            ns['kernel32'] = Mock()
            ns['kernel32'].GetModuleHandleW.return_value = 1
            with patch.object(ui, 'TrayLimitsPreferences') as factory:
                prefs = factory.return_value
                prefs.limits = self.module().DEFAULT_LIMITS
                ns['run']()
                slots = ns['TrayIconSlot'].call_args_list
                self.assertEqual(len(slots), 3)
                m = {'cpu_percent': 90, 'gpu_usage': None, 'mem_percent': 75}
                self.assertEqual(slots[1].kwargs['color_fn'](m)[0], 0x006b6bff)
                self.assertEqual(slots[2].kwargs['color_fn'](m)[0], 0x005f9dff)
                ns['show_exit_menu'] = Mock(return_value=False)
                ns['_wndproc_ref'](123, ns['WM_TRAYICON'], 0, ns['WM_RBUTTONUP'])
                self.assertIs(ns['show_exit_menu'].call_args.args[1], prefs.show)
                prefs.close.assert_called_once()
                close_counts_at_quit = []
                ns['user32'].PostQuitMessage.side_effect = lambda code: close_counts_at_quit.append(prefs.close.call_count)
                ns['_wndproc_ref'](123, ns['WM_DESTROY'], 0, 0)
                ns['user32'].PostQuitMessage.assert_called_once_with(0)
                self.assertEqual(close_counts_at_quit, [2], 'editor must close before posting quit')
                self.assertEqual(prefs.close.call_count, 2, 'exit must release a modal editor before posting quit')

    def test_real_tray_editor_lifecycle(self):
        import usage_limits_ui as ui
        self.assertTrue(hasattr(ui, 'TrayLimitsPreferences'), 'tray editor lifecycle missing')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.ini'
            cfg = configparser.ConfigParser()
            prefs = ui.TrayLimitsPreferences(cfg, path)
            try:
                # Drive the modal Tk loop with a real scheduled Save.
                import tkinter as tk
                prefs.root = tk.Tk()
                prefs.root.withdraw()
                def save():
                    editor = prefs.root._usage_limits_editor
                    entry = editor.entries['mem'][2]
                    entry.delete(0, 'end')
                    entry.insert(0, '99')
                    editor.save()
                prefs.root.after(50, save)
                prefs.show()
                self.assertEqual(prefs.limits['mem'], (50, 75, 99))
                prefs.root.after(50, lambda: prefs.root._usage_limits_editor.close())
                prefs.show()
            finally:
                prefs.close()

    def tray_namespace(self):
        import ast
        tree = ast.parse(Path('tray_monitor.py').read_text(encoding='utf-8'))
        tree.body = [n for n in tree.body if not isinstance(n, (ast.Expr, ast.If))]
        ns = {'__file__': str(Path('tray_monitor.py').resolve())}
        exec(compile(tree, 'tray_monitor.py', 'exec'), ns)
        return ns

    def test_real_gdi_icon_supports_independent_line_colors(self):
        ns = self.tray_namespace()
        from unittest.mock import Mock
        colors = []
        gdi = ns['gdi32']
        original = gdi.SetTextColor
        def record(hdc, color):
            colors.append(color)
            return original(hdc, color)
        with patch.object(gdi, 'SetTextColor', side_effect=record):
            try:
                icon = ns['make_text_icon'](['90%', '60°'], 32, 32, color=[0x006b6bff, 0xffffff])
            except (TypeError, ns['ctypes'].ArgumentError):
                self.fail('GDI does not accept independent usage/temperature colors')
        self.assertTrue(icon)
        ns['user32'].DestroyIcon(icon)
        self.assertEqual(colors, [0x006b6bff, 0xffffff])

    def test_tray_slot_passes_colors_to_gdi(self):
        from test_ping_views import load_definitions
        from unittest.mock import Mock
        import ctypes
        class NID(ctypes.Structure):
            _fields_ = [('hIcon', ctypes.c_void_p), ('szTip', ctypes.c_wchar * 128)]
        ns = {'ctypes': ctypes, 'make_text_icon': Mock(return_value=123),
              'shell32': Mock(), 'user32': Mock(), 'NIM_ADD': 0, 'NIM_MODIFY': 1}
        load_definitions('tray_monitor.py', {'TrayIconSlot'}, ns)
        slot = ns['TrayIconSlot'].__new__(ns['TrayIconSlot'])
        slot.render_fn = lambda m: (['90%', '60°'], 'CPU')
        slot.color_fn = lambda m: [0x006b6bff, 0xffffff]
        slot.nid, slot._current_icon = NID(), None
        for action in (slot.add, slot.update):
            action(16, 16, {})
            self.assertEqual(ns['make_text_icon'].call_args.kwargs.get('color'), [0x006b6bff, 0xffffff])

    def test_tray_colors_and_menu_dispatch(self):
        from test_ping_views import load_definitions
        from unittest.mock import Mock
        import ctypes
        from ctypes import wintypes
        ns = {'user32': Mock(), 'ctypes': ctypes, 'wintypes': wintypes,
              'IDM_EXIT': 1001, 'IDM_LIMITS': 1002, 'MF_STRING': 0,
              'TPM_LEFTALIGN': 0, 'TPM_RETURNCMD': 256}
        load_definitions('tray_monitor.py', {'usage_line_colors', 'show_exit_menu'}, ns)
        self.assertIn('usage_line_colors', ns, 'tray color routing missing')
        u = self.module()
        m = {'cpu_percent': 90, 'gpu_usage': 75, 'mem_percent': 50}
        self.assertEqual(ns['usage_line_colors'](m, 'cpu', u.DEFAULT_LIMITS), [0x006b6bff, 0x00ffffff])
        self.assertEqual(ns['usage_line_colors'](m, 'gpu', u.DEFAULT_LIMITS), [0x005f9dff, 0x00ffffff])
        m['gpu_usage'] = None
        self.assertEqual(ns['usage_line_colors'](m, 'gpu', u.DEFAULT_LIMITS), [0x00ffb05f, 0x00ffffff])
        callback = Mock()
        ns['user32'].TrackPopupMenu.return_value = 1002
        self.assertFalse(ns['show_exit_menu'](1, callback))
        callback.assert_called_once()
        ns['user32'].TrackPopupMenu.return_value = 1001
        self.assertTrue(ns['show_exit_menu'](1, callback))
        ns['user32'].TrackPopupMenu.return_value = 0
        self.assertFalse(ns['show_exit_menu'](1, callback))

    def test_real_tk_editor_save_error_cancel_singleton_and_menu(self):
        import tkinter as tk
        from test_taskbar_clicks import namespace
        self.assertIsNotNone(importlib.util.find_spec('usage_limits_ui'), 'GUI editor missing')
        from usage_limits_ui import open_limits_editor
        from usage_limits import load_limits
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.ini'
            path.write_text('[window]\nx=7\n', encoding='utf-8')
            cfg = configparser.ConfigParser()
            cfg.read(path)
            root = tk.Tk()
            root.withdraw()
            try:
                ns = namespace()
                ns['CONFIG_PATH'] = path
                w = ns['MonitorWindow'].__new__(ns['MonitorWindow'])
                w.master, w.root, w.full_cfg = root, tk.Toplevel(root), cfg
                w.mode = "floating"
                w.ping_enabled, w.ping_monitor = False, None
                w._bind_menu()
                menu = next(c for c in w.root.winfo_children() if isinstance(c, tk.Menu))
                index = next(i for i in range(menu.index('end')+1)
                             if menu.type(i) == 'command' and menu.entrycget(i, 'label') == 'Configurar limites de uso…')
                menu.invoke(index)
                editor = open_limits_editor(root, cfg, path)
                self.assertIs(editor, open_limits_editor(root, cfg, path))
                self.assertIs(editor.window.master, root)
                root.update()
                before = path.read_bytes()
                editor.entries['cpu'][0].delete(0, 'end')
                editor.entries['cpu'][0].insert(0, '99')
                editor.save()
                self.assertTrue(editor.error.cget('text'))
                self.assertEqual(path.read_bytes(), before)
                editor.entries['cpu'][0].delete(0, 'end')
                editor.entries['cpu'][0].insert(0, '10')
                with patch('ping_config.os.replace', side_effect=OSError('denied')):
                    editor.save()
                self.assertEqual(load_limits(cfg)['cpu'], (50, 75, 90))
                self.assertTrue(editor.window.winfo_exists())
                editor.save()
                self.assertEqual(load_limits(cfg)['cpu'], (10, 75, 90))
                reloaded = configparser.ConfigParser()
                reloaded.read(path)
                self.assertEqual(load_limits(reloaded), load_limits(cfg))
                editor = open_limits_editor(root, cfg, path)
                before = path.read_bytes()
                editor.close()
                self.assertEqual(path.read_bytes(), before)
            finally:
                root.destroy()

    def test_widget_colors_all_modes(self):
        from test_ping_views import PingViewTests, FakeLabel
        ns = PingViewTests().widget_namespace()
        cfg = configparser.ConfigParser()
        cfg.read_dict({'usage_limits': {'cpu_low': '10', 'cpu_warning': '20', 'cpu_high': '30'}})
        for mode in ('floating', 'docked', 'taskbar'):
            window = ns['MonitorWindow'].__new__(ns['MonitorWindow'])
            window.mode, window.ping_enabled = mode, False
            window.full_cfg, window._fg = cfg, '#e6e6e6'
            window.cfg = {}
            window._update_net_split = lambda m: None
            for name in ('up', 'down', 'cpu', 'gpu', 'mem', 'status'):
                setattr(window, 'lbl_' + name, FakeLabel())
            m = ns['Metrics']().snapshot()
            m.update(cpu_percent=30, gpu_usage=75, mem_percent=50)
            window._update_labels(m)
            self.assertEqual(window.lbl_cpu.get('fg'), '#ff6b6b')
            self.assertEqual(window.lbl_gpu.get('fg'), '#ff9d5f')
            self.assertEqual(window.lbl_mem.get('fg'), '#5fb0ff')
            m.update(cpu_percent=0, gpu_usage=None, mem_percent=0)
            window._update_labels(m)
            for name in ('cpu', 'gpu', 'mem'):
                self.assertEqual(getattr(window, 'lbl_' + name)['fg'], '#e6e6e6')

    def test_validation_load_and_atomic_persistence(self):
        u = self.module()
        self.assertTrue(hasattr(u, 'save_limits'), 'validated persistence missing')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.ini'
            original = '[window]\nx=7\n[ping]\ntargets=1.1.1.1\n[custom]\nkeep=yes\n'
            path.write_text(original, encoding='utf-8')
            cfg = configparser.ConfigParser()
            cfg.read(path)
            self.assertEqual(u.load_limits(cfg), u.DEFAULT_LIMITS)
            limits = {'cpu': ('0', '20.5', '100'), 'gpu': (10, 40, 80), 'mem': (20, 60, 95)}
            expected = u.validate_limits(limits)
            u.save_limits(path, limits)
            cfg.read(path)
            self.assertEqual(u.load_limits(cfg), expected)
            self.assertEqual(cfg['window']['x'], '7')
            self.assertEqual(cfg['ping']['targets'], '1.1.1.1')
            self.assertEqual(cfg['custom']['keep'], 'yes')
            before = path.read_bytes()
            for bad in [(-1, 50, 90), (20, 20, 90), (90, 50, 20), (10, 50, 101), ('', 50, 90), ('nan', 50, 90), (10, 50, 'inf')]:
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    u.save_limits(path, dict(limits, cpu=bad))
                self.assertEqual(path.read_bytes(), before)
            with patch('ping_config.os.replace', side_effect=OSError('denied')):
                with self.assertRaises(OSError):
                    u.save_limits(path, u.DEFAULT_LIMITS)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(directory).iterdir()), [path])
            cfg['usage_limits']['cpu_low'] = 'nan'
            self.assertEqual(u.load_limits(cfg)['cpu'], u.DEFAULT_LIMITS['cpu'])
            self.assertEqual(u.load_limits(cfg)['gpu'], expected['gpu'])

    def test_boundaries_defaults_and_missing_sensor(self):
        u = self.module()
        self.assertEqual(u.DEFAULT_LIMITS, {'cpu': (50, 75, 90), 'gpu': (50, 75, 90), 'mem': (50, 75, 90)})
        for value, color in [(None, 'normal'), (0, 'normal'), (49.99, 'normal'),
                             (50, u.LOW_COLOR), (74.99, u.LOW_COLOR),
                             (75, u.WARNING_COLOR), (89.99, u.WARNING_COLOR),
                             (90, u.HIGH_COLOR), (100, u.HIGH_COLOR)]:
            self.assertEqual(u.usage_color(value, (50, 75, 90), 'normal'), color)
        self.assertEqual(u.usage_color(30, (10, 20, 30), 'normal'), u.HIGH_COLOR)
