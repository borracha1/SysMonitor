"""MonitorWindow hover wiring: which label is under the Windows cursor and where the events go."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_ping_views import load_definitions


def rect(left, top, right, bottom):
    return SimpleNamespace(left=left, top=top, right=right, bottom=bottom)


class Cfg(dict):
    def getint(self, key):
        return int(self[key])


def make_label(hwnd, mapped=True):
    label = Mock()
    label.winfo_id.return_value = hwnd
    label.winfo_ismapped.return_value = mapped
    return label


class HoverCase(unittest.TestCase):
    RECTS = {1: rect(1000, 1040, 1060, 1080), 2: rect(1060, 1040, 1100, 1080), 3: rect(1200, 1040, 1300, 1080)}

    def setUp(self):
        self.cursor = (0, 0)
        self.tooltips = []

        def make_tooltip(*args, **kwargs):
            tip = Mock()
            tip.args = args
            self.tooltips.append(tip)
            return tip

        self.ns = {'_cursor_pos': lambda: self.cursor, '_win_rect': lambda hwnd: self.RECTS.get(hwnd),
                   'HoverTooltip': make_tooltip, 'TOP_PROCESSES': Mock(),
                   'tk': SimpleNamespace(Tk=object, TclError=RuntimeError), 'configparser': Mock(), 'Metrics': object}
        load_definitions('sys_monitor.py', {'MonitorWindow'}, self.ns)
        cls = self.ns['MonitorWindow']
        self.window = cls.__new__(cls)
        w = self.window
        w.lbl_cpu, w.lbl_cpu_temp, w.lbl_mem = make_label(1), make_label(2), make_label(3)
        w._closing = False
        w.master, w.root, w.click_catcher = Mock(), Mock(), Mock()
        w.cfg = Cfg(bg_color='#000000', fg_color='#ffffff', font_size='9')
        w.mode = 'taskbar'
        w._hover = None


class HitTests(HoverCase):
    def hit(self, x, y):
        self.cursor = (x, y)
        return self.window._hover_hit()

    def test_cpu_covers_the_usage_and_the_temperature_parts(self):
        self.assertEqual(self.hit(1010, 1050), ('cpu', (1000, 1040, 1100, 1080)))
        self.assertEqual(self.hit(1099, 1079), ('cpu', (1000, 1040, 1100, 1080)))

    def test_memory_label(self):
        self.assertEqual(self.hit(1250, 1060), ('mem', (1200, 1040, 1300, 1080)))

    def test_outside_any_label_or_on_the_edge_is_none(self):
        self.assertIsNone(self.hit(1100, 1060))
        self.assertIsNone(self.hit(1150, 1060))
        self.assertIsNone(self.hit(1010, 1039))
        self.assertIsNone(self.hit(1300, 1060))

    def test_hidden_memory_label_is_not_a_target(self):
        self.window.lbl_mem.winfo_ismapped.return_value = False
        self.assertIsNone(self.hit(1250, 1060))

    def test_label_without_a_window_rect_is_skipped(self):
        self.RECTS = {}
        self.ns['_win_rect'] = lambda hwnd: None
        self.assertIsNone(self.hit(1010, 1050))

    def test_closing_window_has_no_target(self):
        self.window._closing = True
        self.assertIsNone(self.hit(1010, 1050))


class BindingTests(HoverCase):
    def test_events_reach_the_toplevel_and_the_taskbar_click_catcher(self):
        self.window._bind_hover()
        for target in (self.window.root, self.window.click_catcher):
            bound = {call.args[0]: call for call in target.bind.call_args_list}
            self.assertEqual(set(bound), {'<Motion>', '<Enter>', '<Leave>'})
            self.assertTrue(all(call.kwargs.get('add') == '+' or call.args[2:] == ('+',) for call in bound.values()))
        tip = self.tooltips[0]
        self.window.root.bind.call_args_list[0].args[1](None)
        tip.pointer_moved.assert_called_once()

    def test_tooltip_is_a_toplevel_of_the_hidden_root_with_the_widget_colors(self):
        self.window._bind_hover()
        args = self.tooltips[0].args
        self.assertEqual(args[0], self.window.master)
        self.assertIs(args[1], self.ns['TOP_PROCESSES'])
        self.assertEqual(args[3], self.window._hover_hit)
        self.assertEqual(args[4:6], ('#000000', '#ffffff'))

    def test_without_the_process_monitor_nothing_is_bound(self):
        self.ns['TOP_PROCESSES'] = None
        self.window._bind_hover()
        self.assertIsNone(self.window._hover)
        self.window.root.bind.assert_not_called()

    def test_no_click_catcher_outside_taskbar_mode(self):
        self.window.click_catcher = None
        self.window._bind_hover()
        self.assertEqual(self.window.root.bind.call_count, 3)

    def test_events_are_ignored_once_closing(self):
        self.window._bind_hover()
        self.window._closing = True
        self.window._hover_event(None)
        self.tooltips[0].pointer_moved.assert_not_called()

    def test_close_hover_hides_and_forgets_the_tooltip(self):
        self.window._bind_hover()
        self.window._close_hover()
        self.tooltips[0].close.assert_called_once()
        self.assertIsNone(self.window._hover)
        self.window._close_hover()


if __name__ == '__main__':
    unittest.main()
