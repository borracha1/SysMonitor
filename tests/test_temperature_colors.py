"""Temperature/color regression, isolated from Explorer and the user's config."""
import configparser
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import usage_limits as u
import test_ping_views as views
from test_ping_views import FakeLabel, load_definitions


class TemperatureColorsTests(unittest.TestCase):
    def test_color_text_color_uses_luminance(self):
        for background, foreground in (('#202080', '#ffffff'), ('#ffff80', '#101010'),
                                       ('#000000', '#ffffff'), ('#FFFFFF', '#101010'),
                                       ('#5fb0ff', '#101010'), ('#ff9d5f', '#101010'),
                                       ('#ff6b6b', '#101010')):
            with self.subTest(background=background):
                self.assertEqual(u.color_text_color(background), foreground)

    def test_real_editor_color_text_contrast_and_restore(self):
        from usage_limits_ui import open_limits_editor
        cfg = configparser.ConfigParser()
        cfg.read_dict({'usage_limits': {'low_color': '#202080'}})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.ini'
            root = tk.Tk()
            root.withdraw()
            try:
                editor = open_limits_editor(root, cfg, path)
                root.update()
                with self.subTest(action='initial dark background'):
                    self.assertEqual(editor.color_boxes['low'].cget('fg'), '#ffffff')
                for level in u.LEVELS:
                    for background, foreground in (('#202080', '#ffffff'), ('#ffff80', '#101010'),
                                                   ('#202080', '#ffffff')):
                        with self.subTest(level=level, background=background), patch(
                                'usage_limits_ui.colorchooser.askcolor', return_value=(None, background)) as choose:
                            editor.color_boxes[level].event_generate('<Button-1>')
                            root.update()
                            self.assertEqual(choose.call_args.kwargs['parent'], editor.window)
                            self.assertEqual(editor.color_boxes[level].cget('bg'), background)
                            self.assertEqual(editor.color_boxes[level].cget('fg'), foreground)
                editor.restore_colors()
                for level, background in zip(u.LEVELS, ('#5fb0ff', '#ff9d5f', '#ff6b6b')):
                    with self.subTest(action='restore', level=level):
                        self.assertEqual(editor.color_boxes[level].cget('bg'), background)
                        self.assertEqual(editor.color_boxes[level].cget('fg'), '#101010')
                self.assertFalse(path.exists(), 'color preview must not write config')
                self.assertEqual(cfg['usage_limits']['low_color'], '#202080')
            finally:
                root.destroy()

    def test_validation_and_boundaries(self):
        for metric in ('cpu_temp', 'gpu_temp'):
            self.assertEqual(u.validate_preferences({metric: (0, 60, 120)})[metric], (0, 60, 120))
            for bad in [(-1, 60, 85), (0, 60, 121), (60, 60, 85), (85, 75, 60), ('nan', 75, 85), (60, 'inf', 85), ('', 75, 85)]:
                with self.subTest(metric=metric, bad=bad), self.assertRaisesRegex(ValueError, 'Temperatura'):
                    u.validate_preferences({metric: bad})
        for color in ('#aAbBcC', '#000000', '#ffffff'):
            self.assertEqual(u.validate_preferences({'colors': (color, color, color)})['colors'], (color,)*3)
        for color in ('red', '#fff', '', '#gg0000', '#1234567'):
            with self.subTest(color=color), self.assertRaises(ValueError):
                u.validate_preferences({'colors': (color, '#000000', '#ffffff')})

    def test_load_fallback_and_selective_atomic_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.ini'
            original = '[window]\nx=7\n[usage_limits]\ncpu_low=12\ncpu_temp_low=nan\ngpu_temp_low=42\nlow_color=red\nwarning_color=#ABCDEF\nother=keep\n'
            path.write_text(original, encoding='utf-8')
            cfg = configparser.ConfigParser()
            cfg.read(path)
            values = u.load_preferences(cfg)
            self.assertEqual(values['cpu_temp'], (60, 75, 85))
            self.assertEqual(values['gpu_temp'], (42, 75, 85))
            self.assertEqual(values['colors'], ('#5fb0ff', '#ABCDEF', '#ff6b6b'))
            self.assertEqual(path.read_text(encoding='utf-8'), original)
            u.save_limits(path, {'cpu_temp': (0, 70, 120), 'colors': ('#123456', '#234567', '#345678')})
            cfg.read(path)
            self.assertEqual(cfg['usage_limits']['cpu_low'], '12')
            self.assertEqual(cfg['usage_limits']['other'], 'keep')
            self.assertEqual(cfg['window']['x'], '7')
            self.assertEqual(u.load_preferences(cfg)['cpu_temp'], (0, 70, 120))
            before = path.read_bytes()
            with patch('ping_config.os.replace', side_effect=OSError('denied')):
                with self.assertRaises(OSError):
                    u.save_limits(path, {'gpu_temp': (1, 2, 3)})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_widget_independent_parts_all_modes(self):
        ns = views.PingViewTests().widget_namespace()
        cfg = configparser.ConfigParser()
        cfg.read_dict({'usage_limits': {'low_color': '#112233', 'warning_color': '#445566', 'high_color': '#778899'}})
        for mode in ('taskbar', 'docked', 'floating'):
            w = ns['MonitorWindow'].__new__(ns['MonitorWindow'])
            w.mode, w.full_cfg, w._fg, w.cfg, w.ping_enabled = mode, cfg, 'normal', {}, False
            w._update_net_split = lambda m: None
            w._position_hardware_parts = Mock()
            for name in ('up', 'down', 'cpu', 'gpu', 'cpu_temp', 'gpu_temp', 'mem', 'status'):
                setattr(w, 'lbl_' + name, FakeLabel())
            m = ns['Metrics']().snapshot()
            m.update(cpu_percent=50, cpu_temp=85, gpu_usage=90, gpu_temp=75, mem_percent=75)
            w._update_labels(m)
            self.assertEqual(w.lbl_cpu['fg'], '#112233')
            self.assertEqual(w.lbl_cpu_temp['fg'], '#778899')
            self.assertEqual(w.lbl_gpu['fg'], '#778899')
            self.assertEqual(w.lbl_gpu_temp['fg'], '#445566')
            self.assertEqual(w.lbl_mem['fg'], '#445566')
            expected = 'CPU: 50%  85°C' if mode == 'floating' else 'CPU 50% 85°'
            self.assertEqual(w.lbl_cpu['text'] + w.lbl_cpu_temp['text'], expected)
            m.update(cpu_temp=None, gpu_temp=None)
            w._update_labels(m)
            self.assertEqual(w.lbl_cpu_temp['fg'], 'normal')
            self.assertEqual(w.lbl_gpu_temp['fg'], 'normal')

    def test_tray_temperature_custom_colors_and_mem(self):
        ns = load_definitions('tray_monitor.py', {'usage_line_colors'}, {})
        values = u.validate_preferences({'colors': ('#112233', '#445566', '#778899')})
        m = dict(cpu_percent=50, cpu_temp=85, gpu_usage=90, gpu_temp=75, mem_percent=75)
        self.assertEqual(ns['usage_line_colors'](m, 'cpu', values), [0x332211, 0x998877])
        self.assertEqual(ns['usage_line_colors'](m, 'gpu', values), [0x998877, 0x665544])
        m['gpu_usage'] = None
        self.assertEqual(ns['usage_line_colors'](m, 'gpu', values), [0x665544, 0xffffff])
        m['cpu_temp'] = None
        self.assertEqual(ns['usage_line_colors'](m, 'cpu', values)[1], 0xffffff)

    def test_real_tk_parts_geometry_space_levels_and_menus(self):
        import ast
        import tkinter.font as tkfont
        from test_taskbar_clicks import namespace
        import net_split
        tree = ast.parse(Path('sys_monitor.py').read_text(encoding='utf-8'))
        defaults = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
                                        and any(isinstance(t, ast.Name) and t.id == 'DEFAULTS' for t in n.targets)))
        for mode in ('taskbar', 'docked', 'floating'):
            ns = namespace()
            ns.update(tkfont=tkfont, threading=__import__('threading'), net_column_width=net_split.net_column_width)
            load_definitions('sys_monitor.py', {'Metrics', 'fmt_temp', 'fmt_speed'}, ns)
            root = tk.Tk()
            root.withdraw()
            w = ns['MonitorWindow'].__new__(ns['MonitorWindow'])
            w.master, w.root = root, tk.Toplevel(root)
            cfg = configparser.ConfigParser()
            cfg.read_dict(defaults)
            w.cfg, w.full_cfg, w.mode = cfg['window'], cfg, mode
            w._fg, w.ping_enabled, w.ping_monitor = '#e6e6e6', False, None
            w.ping_labels, w._space_level = [], 0
            w._net_cells, w._net_active, w.net_split = [], False, False
            w.click_catcher = tk.Toplevel(root) if mode == 'taskbar' else None
            try:
                w._build_ui()
                if mode == 'taskbar':
                    w.root.geometry(f'{w.embed_width}x48+40+40')
                    w._layout_embedded(48)
                w._bind_menu()
                root.update()
                m = ns['Metrics']().snapshot()
                m.update(cpu_percent=45, cpu_temp=60, gpu_usage=90, gpu_temp=85)
                w._update_labels(m)
                root.update()
                if mode == 'taskbar':
                    original_cols, original_width = w._embedded_columns(0)
                    measure = w.font.measure
                    expected_hw = max(measure('CPU 100% 100°'), measure('GPU 100% 100°'))
                    self.assertEqual(original_cols['hw'][1], expected_hw)
                    for level in (0, 1, 2, 0):
                        w._space_level = level
                        w._calculate_embedded_columns()
                        w._layout_embedded(48)
                        root.update()
                        x, width = w._cols['hw']
                        for metric in ('cpu', 'gpu'):
                            usage, temp = getattr(w, 'lbl_' + metric), getattr(w, 'lbl_' + metric + '_temp')
                            self.assertEqual(temp.winfo_x(), x + measure(usage.cget('text')))
                            self.assertEqual(usage.winfo_width() + temp.winfo_width(), width)
                            self.assertEqual(usage.winfo_y(), temp.winfo_y())
                            self.assertEqual(temp.winfo_manager(), 'place')
                        self.assertEqual(w.lbl_mem.winfo_manager(), '' if level == 2 else 'place')
                    self.assertEqual(w.embed_width, original_width)
                    self.assertEqual(w._cols['mem'], original_cols['mem'])
                else:
                    for metric in ('cpu', 'gpu'):
                        usage, temp = getattr(w, 'lbl_' + metric), getattr(w, 'lbl_' + metric + '_temp')
                        self.assertIs(usage.master, temp.master)
                        self.assertEqual(temp.winfo_x(), usage.winfo_x() + usage.winfo_width())
                menu = next(c for c in w.root.winfo_children() if isinstance(c, tk.Menu))
                parts = [w.lbl_cpu, w.lbl_cpu_temp, w.lbl_gpu, w.lbl_gpu_temp, w.lbl_mem]
                if w.click_catcher is not None:
                    parts.append(w.click_catcher)
                with patch.object(menu, 'tk_popup') as popup:
                    # Secondary bars use the exact same class/menu and child bindtags.
                    for hwnd in (None, 999):
                        w.taskbar_hwnd = hwnd
                        for part in parts:
                            self.assertTrue(str(w.root) in part.bindtags() or part is w.click_catcher)
                            part.event_generate('<Button-3>', x=1, y=1)
                            root.update()
                    self.assertEqual(popup.call_count, 2 * len(parts))
                # Shared configuration is reloaded on the next tick, no rebuild.
                cfg['usage_limits'] = {'low_color': '#112233'}
                w._update_labels(m)
                self.assertEqual(w.lbl_cpu_temp.cget('fg'), '#112233')
            finally:
                root.destroy()

    def test_real_editor_colors_restore_cancel_error_and_publish(self):
        from usage_limits_ui import open_limits_editor, TrayLimitsPreferences
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.ini'
            path.write_text('[window]\nx=7\n', encoding='utf-8')
            cfg = configparser.ConfigParser()
            cfg.read(path)
            root = tk.Tk()
            root.withdraw()
            prefs = TrayLimitsPreferences(cfg, path)
            try:
                e = open_limits_editor(root, cfg, path, prefs._saved)
                before = path.read_bytes()
                root.update()
                with patch('usage_limits_ui.colorchooser.askcolor', return_value=((17, 34, 51), '#112233')) as choose:
                    e.color_boxes['low'].event_generate('<Button-1>')
                    root.update()
                    choose.assert_called_once_with(color='#5fb0ff', parent=e.window)
                self.assertEqual(e.color_boxes['low'].cget('background'), '#112233')
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(u.load_preferences(cfg)['colors'][0], '#5fb0ff')
                e.restore_colors()
                self.assertEqual(tuple(e.color_boxes[level].cget('background') for level in u.LEVELS),
                                 ('#5fb0ff', '#ff9d5f', '#ff6b6b'))
                with patch('usage_limits_ui.colorchooser.askcolor', return_value=(None, None)):
                    e.choose_color('low')
                self.assertEqual(e.colors['low'], '#5fb0ff')
                e.entries['cpu_temp'][0].delete(0, 'end')
                e.entries['cpu_temp'][0].insert(0, 'nan')
                e.save()
                self.assertIn('Temperatura CPU', e.error.cget('text'))
                self.assertEqual(path.read_bytes(), before)
                e.close()
                self.assertEqual(path.read_bytes(), before)
                e = open_limits_editor(root, cfg, path, prefs._saved)
                with patch('usage_limits_ui.colorchooser.askcolor', return_value=((17, 34, 51), '#112233')):
                    e.choose_color('low')
                e.save()
                self.assertEqual(prefs.limits['colors'][0], '#112233')
                self.assertEqual(prefs.limits['gpu_temp'], (60, 75, 85))
                reloaded = configparser.ConfigParser()
                reloaded.read(path)
                self.assertEqual(u.load_preferences(reloaded), prefs.limits)
            finally:
                root.destroy()
