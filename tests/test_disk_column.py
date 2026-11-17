"""Disk column of the widget: width, levels, alert text, click, hover target and menu."""
import ast
import configparser
from pathlib import Path
import threading
import tkinter as tk
import tkinter.font as tkfont
import unittest
from unittest.mock import Mock

import disk_monitor as dm
import net_split as net
import ping_monitor as pm
from test_ping_views import load_definitions
from test_taskbar_clicks import namespace

GB = 1024 ** 3
ICON_FALLBACK = ('Segoe UI Symbol', '\U0001F5B4')


def snapshot(active, letter='D'):
    return (dm.Disk(1, 'Model', active, 0.0, 0.0, (dm.Volume(letter, '', 100 * GB, 50 * GB, 50 * GB),)),)


class Monitor:
    def __init__(self, value=None):
        self.value = value

    def snapshot(self):
        return self.value


class IconChoiceTests(unittest.TestCase):
    def test_fluent_when_installed_else_symbol(self):
        ns = load_definitions('sys_monitor.py', {'disk_icon_choice'}, {'DISK_ICON_FALLBACK': ICON_FALLBACK})
        self.assertEqual(ns['disk_icon_choice']({'Segoe Fluent Icons', 'Arial'}), ('Segoe Fluent Icons', '\uEDA2'))
        self.assertEqual(ns['disk_icon_choice']({'Arial'}), ICON_FALLBACK)


class DiskColumnBase(unittest.TestCase):
    with_disk = True

    def setUp(self):
        self.ns = namespace()
        load_definitions('sys_monitor.py', {'Metrics', 'fmt_temp', 'fmt_speed', 'disk_icon_choice'}, self.ns)
        self.disk_monitor = Monitor(snapshot(87.0))
        self.disk_ui = Mock()
        self.ns.update(threading=threading, tkfont=tkfont, APP_NAME='Disk column test',
                       ping_settings=pm.ping_settings, initial_ping_family=pm.initial_ping_family,
                       ping_column_width=pm.ping_column_width, ping_marker=pm.ping_marker,
                       fmt_ping_line=pm.fmt_ping_line, ping_has_problem=pm.ping_has_problem,
                       PING_LOSS_COLOR='red', net_column_width=net.net_column_width,
                       DISK_ICON_FALLBACK=ICON_FALLBACK, DiskMonitor=object, DiskWindow=object,
                       alert_disk=dm.alert_disk, DISK_UI=self.disk_ui,
                       _cursor_pos=lambda: self.cursor)
        if self.with_disk:
            self.ns['DISK_MONITOR'] = self.disk_monitor
        self.cursor = (-1, -1)
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
        metrics = self.ns['Metrics']()
        metrics.net_rates = ((100, 200), (300, 400))
        self.space = Mock()
        self.space.snapshot.return_value = None
        self.window = self.ns['MonitorWindow'](self.master, self.cfg, metrics, 'taskbar',
                                               space_monitor=self.space)
        self.window.root.after_cancel(self.window._after_id)
        self.window._after_id = None
        self.window._update_labels()
        self.master.update()

    def tearDown(self):
        self.window._destroy()
        self.master.destroy()
        self.window = None

    def rect_of(self, *labels):
        return self.window._union_rect(labels)

    def point_in(self, *labels):
        left, top, right, bottom = self.rect_of(*labels)
        return (left + right) // 2, (top + bottom) // 2


class WithoutDiskTests(DiskColumnBase):
    with_disk = False

    def test_without_disk_monitor_widths_are_unchanged(self):
        w = self.window
        self.assertFalse(w.disk_enabled)
        self.assertNotIn('disk', w._cols)
        self.assertFalse(hasattr(w, 'lbl_disk'))
        cols, width = w._embedded_columns(0)
        self.assertEqual((w._cols, w.embed_width), (cols, width))
        x_mem, w_mem = cols['mem']
        self.assertEqual(cols['st'][0], x_mem + w_mem + 2)
        self.assertEqual(width, cols['st'][0] + cols['st'][1] + 4)
        self.assertEqual(w._taskbar_widths(), tuple(w._embedded_columns(level, w._taskbar_measure_font(8).measure)[1]
                                                    for level in range(3)))


class DiskColumnTests(DiskColumnBase):
    def test_disk_column_follows_mem_with_a_10px_gap(self):
        cols = self.window._cols
        self.assertEqual(cols['disk'][0], cols['mem'][0] + cols['mem'][1] + 10)
        self.assertEqual(cols['st'][0], cols['disk'][0] + cols['disk'][1] + 2)

    def test_width_is_the_same_at_rest_and_in_alert(self):
        w = self.window
        self.disk_monitor.value = snapshot(10.0)
        w._update_labels()
        rest = (w.embed_width, w._taskbar_widths(), w._taskbar_shrink())
        self.assertEqual(w.lbl_disk['text'], '')
        self.disk_monitor.value = snapshot(87.0)
        w._update_labels()
        self.master.update()
        self.assertEqual((w.embed_width, w._taskbar_widths(), w._taskbar_shrink()), rest)
        self.assertEqual(w.lbl_disk['text'], ' D: 87%')
        self.assertEqual(w.lbl_disk_icon['fg'], '#ff9d5f')
        self.assertEqual(w.lbl_disk['fg'], '#ff9d5f')
        x, width = w._cols['disk']
        self.assertLessEqual(int(w.lbl_disk.place_info()['x']) + int(w.lbl_disk.place_info()['width']), x + width)

    def test_at_rest_only_the_icon(self):
        w = self.window
        self.disk_monitor.value = snapshot(10.0)
        w._update_labels()
        self.assertEqual(w.lbl_disk['text'], '')
        self.assertEqual(w.lbl_disk_icon['fg'], w._fg)
        self.assertTrue(w.lbl_disk_icon['text'])

    def test_level_two_hides_disk_with_mem(self):
        w = self.window
        w._apply_space_level(2)
        self.master.update()
        self.assertFalse(w.lbl_disk_icon.winfo_ismapped())
        self.assertFalse(w.lbl_disk.winfo_ismapped())
        self.assertEqual(w.lbl_mem.winfo_manager(), '')
        self.assertIn('disk', w._cols)
        hw_x, hw_w = w._cols['hw']
        self.assertEqual(w._cols['st'][0], hw_x + hw_w + 2)
        w._apply_space_level(0)
        self.master.update()
        self.assertTrue(w.lbl_disk_icon.winfo_ismapped())

    def test_click_on_disk_opens_the_window(self):
        w = self.window
        self.cursor = self.point_in(w.lbl_disk_icon, w.lbl_disk)
        w._on_net_click()
        self.disk_ui.show.assert_called_once_with()
        self.disk_ui.show.reset_mock()
        self.cursor = self.point_in(w.lbl_cpu)
        w._on_net_click()
        self.disk_ui.show.assert_not_called()

    def test_hover_targets_include_disk(self):
        w = self.window
        self.cursor = self.point_in(w.lbl_disk)
        kind, rect = w._hover_hit()
        self.assertEqual(kind, 'disk')
        self.assertEqual(rect, self.rect_of(w.lbl_disk_icon, w.lbl_disk))
        self.cursor = self.point_in(w.lbl_mem)
        self.assertEqual(w._hover_hit()[0], 'mem')

    def test_menu_has_discos_entry(self):
        menu = self.window._menu
        self.assertIsNotNone(menu.index('Discos…'))
        menu.invoke('Discos…')
        self.disk_ui.show.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
