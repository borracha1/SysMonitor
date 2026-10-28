"""Font shrinking regression with a real Tk/Win32 isolated taskbar parent."""
import ast
import configparser
from pathlib import Path
import threading
import tkinter as tk
import tkinter.font as tkfont
import unittest
from unittest.mock import Mock, patch

import net_split as net
import ping_monitor as pm
from taskbar_space import SpaceSnapshot, choose_layout
from test_ping_views import load_definitions
from test_taskbar_clicks import namespace


class TaskbarFontTests(unittest.TestCase):
    def setUp(self):
        self.ns = namespace()
        load_definitions('sys_monitor.py', {'Metrics', 'fmt_temp', 'fmt_speed'}, self.ns)
        self.ns.update(threading=threading, tkfont=tkfont, APP_NAME='Font layout test',
                       ping_settings=pm.ping_settings, initial_ping_family=pm.initial_ping_family,
                       ping_column_width=pm.ping_column_width, ping_marker=pm.ping_marker,
                       fmt_ping_line=pm.fmt_ping_line, ping_has_problem=pm.ping_has_problem,
                       PING_LOSS_COLOR='red', net_column_width=net.net_column_width)
        tree = ast.parse(Path('sys_monitor.py').read_text(encoding='utf-8'))
        defaults = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
                                        and any(isinstance(t, ast.Name) and t.id == 'DEFAULTS' for t in n.targets)))
        self.master = tk.Tk()
        self.master.overrideredirect(True)
        self.master.geometry('1800x80+20+20')
        self.master.update()
        self.parent = self.ns['_u32'].GetParent(self.master.winfo_id())
        self.ns['find_taskbar'] = lambda: (self.parent, None)
        self.cfg = configparser.ConfigParser()
        self.cfg.read_dict(defaults)
        self.cfg['window']['font_size'] = '8'
        self.cfg['window']['net_split'] = 'true'
        metrics = self.ns['Metrics']()
        metrics.net_rates = ((100, 200), (300, 400))
        self.monitor = Mock()
        self.monitor.snapshot.return_value = None
        self.window = self.ns['MonitorWindow'](self.master, self.cfg, metrics, 'taskbar',
                                               space_monitor=self.monitor)
        self.window.root.after_cancel(self.window._after_id)
        self.window._after_id = None
        self.window._update_labels()
        self.master.update()
        self.emb = self.window.embedder
        tr = self.ns['_win_rect'](self.parent)
        self.bounds = (tr.left, tr.top, tr.right, tr.bottom)
        self.emb.side_provider = lambda: 'right'
        self.ns['_log_event'].reset_mock()

    def tearDown(self):
        self.window._destroy()
        self.master.destroy()
        self.window = self.emb = None

    def snapshot(self, width):
        left, top, right, bottom = self.bounds
        return SpaceSnapshot(self.parent, self.bounds, (left+10, left+900), (right-width, right))

    def test_friend_video_font_shrinks_without_oscillation_and_matches_layout_width(self):
        w = self.window
        self.assertIsNotNone(self.emb.shrink_provider)
        self.assertIsNotNone(self.emb.on_font_change)
        normal = w._taskbar_widths()
        shrink = w._taskbar_shrink()
        self.assertEqual([size for size, width in shrink], [7, 6])
        for size, widths in shrink:
            width = widths[0]
            snap = self.snapshot(width)
            self.monitor.snapshot.return_value = snap
            expected = choose_layout(snap, normal, self.bounds[2], side='right', shrink=shrink)
            with patch.object(w, '_apply_taskbar_font', wraps=w._apply_taskbar_font) as apply:
                self.emb.on_font_change = apply
                self.emb.reposition()
                self.master.update()
                apply.assert_called_once_with(size)
                self.assertEqual(self.emb._layout_key, (expected.side, expected.level, size))
                self.assertEqual(w.font.cget('size'), size)
                self.assertEqual(w._net_font.cget('size'), size)
                self.assertEqual(w._line_h, w.font.metrics('linespace'))
                self.assertEqual((w.embed_width, self.emb.width), (width, expected.width))
                self.assertEqual(w.lbl_mem.winfo_manager(), 'place')
                self.assertTrue(w._net_active)
                self.assertEqual(w._taskbar_widths(), normal)
                self.assertEqual(w._taskbar_shrink(), shrink)
                marker = w._ping_marker_width
                self.assertEqual(marker, w.font.measure('v6·A '))
                before_logs = self.ns['_log_event'].call_count
                with patch.object(w.font, 'configure', wraps=w.font.configure) as configure:
                    self.emb.reposition()
                    configure.assert_not_called()
                apply.assert_called_once_with(size)
                self.assertEqual(self.emb._layout_key, (expected.side, expected.level, size))
                self.assertEqual(self.ns['_log_event'].call_count, before_logs)
                rect = self.ns['_win_rect'](self.emb.hwnd)
                catcher = self.ns['_win_rect'](self.emb.catcher_hwnd)
                self.assertEqual((rect.left, rect.right), (expected.x, expected.x+width))
                self.assertEqual((rect.left, rect.top, rect.right, rect.bottom),
                                 (catcher.left, catcher.top, catcher.right, catcher.bottom))
                for row in range(2):
                    cells = w._net_cells[row*4:row*4+4]
                    end = max(int(cell.place_info()['x']) + int(cell.place_info()['width']) for cell in cells)
                    self.assertLessEqual(end, w._cols['net'][1])
        logs = [c.args[0] for c in self.ns['_log_event'].call_args_list]
        self.assertEqual(len(logs), 2)
        for text in logs:
            for field in ('side=right', 'regions=', 'widths=', 'shrink=', 'Layout('):
                self.assertIn(field, text)
        self.monitor.snapshot.return_value = self.snapshot(normal[0])
        self.emb.on_font_change = w._apply_taskbar_font
        self.emb.reposition()
        self.assertEqual(w.font.cget('size'), 8)
        self.assertEqual(w.embed_width, normal[0])
        self.assertEqual(self.cfg['window']['font_size'], '8')

    def test_bug_2026_10_28_shrink_measures_all_levels_without_touching_live_font(self):
        w = self.window
        live = (w.font.actual(), w._net_font.actual(), w.embed_width, w._space_level)
        expected = tuple((size, tuple(w._embedded_columns(level, w._taskbar_measure_font(size).measure)[1]
                                     for level in range(3))) for size in (7, 6))
        with patch.object(w.font, 'measure', side_effect=AssertionError('live font measured')), \
                patch.object(w.font, 'configure', side_effect=AssertionError('live font changed')):
            self.assertEqual(w._taskbar_shrink(), expected)
        self.assertEqual((w.font.actual(), w._net_font.actual(), w.embed_width, w._space_level), live)

    def test_bug_2026_10_28_compact_font_six_matches_rendered_width_in_both_orders(self):
        w = self.window
        width = w._embedded_columns(2, w._taskbar_measure_font(6).measure)[1]
        for font_first in (True, False):
            with self.subTest(font_first=font_first):
                w._apply_taskbar_font(None)
                w._apply_space_level(0)
                if font_first:
                    w._apply_taskbar_font(6)
                    w._apply_space_level(2)
                else:
                    w._apply_space_level(2)
                    w._apply_taskbar_font(6)
                self.assertEqual(w.embed_width, width)
                self.assertEqual(w.lbl_mem.winfo_manager(), '')
                self.assertFalse(w._net_active)

    def test_bug_2026_10_28_compact_font_six_reposition_is_stable(self):
        w = self.window
        normal = w._taskbar_widths()
        shrink = w._taskbar_shrink()
        width = w._embedded_columns(2, w._taskbar_measure_font(6).measure)[1]
        snap = self.snapshot(width)
        self.monitor.snapshot.return_value = snap
        expected = choose_layout(snap, normal, self.bounds[2], side='right', shrink=shrink)
        self.assertEqual((expected.side, expected.level, expected.font_size, expected.width),
                         ('right', 2, 6, width))
        with patch.object(w, '_apply_taskbar_font', wraps=w._apply_taskbar_font) as apply:
            self.emb.on_font_change = apply
            self.emb.reposition()
            self.master.update()
            self.assertEqual((w.embed_width, self.emb.width), (expected.width, expected.width))
            self.assertEqual(self.emb._layout_key, ('right', 2, 6))
            for hwnd in (self.emb.hwnd, self.emb.catcher_hwnd):
                rect = self.ns['_win_rect'](hwnd)
                self.assertEqual((rect.left, rect.right), (expected.x, expected.x+expected.width))
            before_logs = self.ns['_log_event'].call_count
            with patch.object(w.font, 'configure', wraps=w.font.configure) as configure:
                self.emb.reposition()
                configure.assert_not_called()
            apply.assert_called_once_with(6)
            self.assertEqual(choose_layout(snap, w._taskbar_widths(), self.bounds[2],
                                           side='right', shrink=w._taskbar_shrink()), expected)
            self.assertEqual(self.ns['_log_event'].call_count, before_logs)
            self.assertEqual((w.embed_width, self.emb.width), (expected.width, expected.width))

    def test_measurement_fonts_cached_independent_and_minimum_respected(self):
        w = self.window
        normal = w._taskbar_widths()
        shrink = w._taskbar_shrink()
        with patch.object(w.font, 'measure', side_effect=AssertionError('live font measured')):
            self.assertEqual(w._taskbar_widths(), normal)
            self.assertEqual(w._taskbar_shrink(), shrink)
        with patch.object(tkfont, 'Font', side_effect=AssertionError('font cache missed')):
            self.assertEqual(w._taskbar_widths(), normal)
            self.assertEqual(w._taskbar_shrink(), shrink)
        for configured in (6, 5):
            self.cfg['window']['font_size'] = str(configured)
            self.assertEqual(w._taskbar_shrink(), ())

    def test_auto_invalid_or_missing_snapshot_restores_configured_font(self):
        w = self.window
        for side, missing in [('auto', False), ('invalid', False), ('right', True)]:
            with self.subTest(side=side, missing=missing):
                self.emb.side_provider = lambda: 'right'
                width = w._taskbar_shrink()[-1][1][0]
                self.monitor.snapshot.return_value = self.snapshot(width)
                self.emb.reposition()
                self.assertEqual(w.font.cget('size'), 6)
                self.emb.side_provider = lambda: side
                self.monitor.snapshot.return_value = None if missing else self.snapshot(width)
                self.emb.reposition()
                self.assertEqual(w.font.cget('size'), 8)
                self.assertEqual(w._net_font.cget('size'), 8)
                self.assertEqual(w.embed_width, w._taskbar_widths()[w._space_level])


if __name__ == '__main__':
    unittest.main()
