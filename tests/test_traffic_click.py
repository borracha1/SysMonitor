"""Left click on the network column; Win32 and Tk are replaced by fakes."""
import ast
from pathlib import Path
import unittest
from unittest.mock import Mock
from ctypes import wintypes

from net_split import is_click, net_family_at
import test_ping_group_views as views


class PureClickTests(unittest.TestCase):
    WIDTHS = (30, 70, 25, 75)  # v4 half: 100 px; v6 half: 100 px.

    def test_each_half_opens_its_family_including_the_boundaries(self):
        self.assertEqual(net_family_at(500, 500, self.WIDTHS), 'ipv4')
        self.assertEqual(net_family_at(599, 500, self.WIDTHS), 'ipv4')
        self.assertEqual(net_family_at(600, 500, self.WIDTHS), 'ipv6')
        self.assertEqual(net_family_at(699, 500, self.WIDTHS), 'ipv6')

    def test_outside_the_column_is_nothing(self):
        self.assertIsNone(net_family_at(499, 500, self.WIDTHS))
        self.assertIsNone(net_family_at(700, 500, self.WIDTHS))

    def test_release_without_moving_is_a_click_and_a_drag_is_not(self):
        self.assertTrue(is_click((10, 10), (10, 10)))
        self.assertTrue(is_click((10, 10), (13, 7)))
        self.assertFalse(is_click((10, 10), (14, 10)))
        self.assertFalse(is_click((10, 10), (10, 6)))
        self.assertFalse(is_click(None, (10, 10)))


def rect(left, top, right, bottom):
    return wintypes.RECT(left, top, right, bottom)


class WindowClickTests(unittest.TestCase):
    def window(self, cursor, active=True):
        helper = views.GroupViewTests()
        ns = helper.namespace()
        window = helper.window(ns)
        ui = Mock()
        rects = {1: rect(500, 0, 700, 20), 2: rect(500, 20, 700, 40)}
        ns.update(TRAFFIC_HISTORY_UI=ui, net_family_at=net_family_at, is_click=is_click,
                  _cursor_pos=Mock(return_value=cursor), _win_rect=lambda hwnd: rects.get(hwnd))
        window.lbl_up = Mock(winfo_id=Mock(return_value=1))
        window.lbl_down = Mock(winfo_id=Mock(return_value=2))
        window._closing = False
        window._net_active = active
        window._net_font = Mock(measure=Mock(side_effect=lambda text: {
            '↑ v4 ': 30, '↓ v4 ': 30, '1000.0 Mbps': 70, ' v6 ': 60}[text]))
        return ns, window, ui

    def test_click_on_each_half_opens_that_family(self):
        for cursor, family in (((510, 10), 'ipv4'), ((510, 30), 'ipv4'),
                               ((690, 10), 'ipv6'), ((690, 30), 'ipv6')):
            with self.subTest(cursor=cursor):
                _, window, ui = self.window(cursor)
                window._on_net_click()
                ui.show.assert_called_once_with(family)

    def test_click_outside_the_network_column_does_nothing(self):
        for cursor in ((499, 10), (700, 10), (510, 40), (510, -1)):
            with self.subTest(cursor=cursor):
                _, window, ui = self.window(cursor)
                window._on_net_click()
                ui.show.assert_not_called()

    def test_without_split_on_screen_opens_the_last_family_seen(self):
        _, window, ui = self.window((510, 10), active=False)
        window._on_net_click()
        ui.show.assert_called_once_with(None)

    def test_refused_window_handle_or_closing_widget_does_nothing(self):
        ns, window, ui = self.window((510, 10))
        ns['_win_rect'] = lambda hwnd: None
        window._on_net_click()
        ui.show.assert_not_called()
        ns, window, ui = self.window((510, 10))
        window._closing = True
        window._on_net_click()
        ui.show.assert_not_called()

    def test_program_without_history_window_ignores_the_click(self):
        ns, window, _ = self.window((510, 10))
        ns['TRAFFIC_HISTORY_UI'] = None
        window._on_net_click()

    def test_taskbar_binds_left_click_on_text_and_catcher(self):
        _, window, _ = self.window((510, 10))
        window.mode, window.click_catcher = 'taskbar', Mock()
        window._bind_traffic_click()
        window.root.bind.assert_called_once()
        self.assertEqual(window.root.bind.call_args.args[0], '<Button-1>')
        window.click_catcher.bind.assert_called_once()
        self.assertEqual(window.click_catcher.bind.call_args.args[0], '<Button-1>')

    def test_rebuilt_widget_binds_the_click_again_after_explorer_restart(self):
        source = Path('sys_monitor.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MonitorWindow')
        init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
        self.assertIn('self._bind_traffic_click()', ast.get_source_segment(source, init))

    def test_floating_mode_leaves_left_button_to_drag(self):
        _, window, _ = self.window((510, 10))
        window.mode, window.click_catcher = 'floating', None
        window._bind_traffic_click()
        window.root.bind.assert_not_called()

    def test_menu_item_comes_before_limits_and_opens_last_family(self):
        ns, window, ui = self.window((510, 10))
        window._bind_menu()
        calls = [c for c in ns['tk'].Menu.return_value.method_calls if c[0] == 'add_command']
        labels = [c.kwargs['label'] for c in calls]
        index = labels.index('Histórico de tráfego…')
        self.assertEqual(labels[index + 1], 'Configurar limites de uso…')
        calls[index].kwargs['command']()
        ui.show.assert_called_once_with(None)


if __name__ == '__main__':
    unittest.main()
