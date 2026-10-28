"""Taskbar side menu and per-HWND cache, isolated from Explorer and config.ini."""
import configparser
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import screen_side
from test_taskbar_clicks import namespace


class TaskbarSideMenuTests(unittest.TestCase):
    def setUp(self):
        self.ns = namespace()
        self.ns.update(screen_key=screen_side.screen_key, load_side=screen_side.load_side,
                       monitor_device=Mock(return_value=r'\\.\DISPLAY1'),
                       save_side=Mock(), CONFIG_PATH='test-settings.ini')
        self.ns['tk'] = Mock()
        self.ns['_u32'] = Mock()
        self.window = self.make_window(101)

    def make_window(self, tray):
        window = self.ns['MonitorWindow'].__new__(self.ns['MonitorWindow'])
        window.root, window.master, window.click_catcher = Mock(), Mock(), Mock()
        window.mode, window.ping_enabled, window.ping_monitor = 'taskbar', False, None
        window.embedder = SimpleNamespace(tray=tray, reposition=Mock())
        window.full_cfg = configparser.ConfigParser()
        window.full_cfg.read_dict({'taskbar_side': {'display1': 'left', 'display2': 'right'}})
        window.metrics = Mock()
        window.metrics.snapshot.return_value = {'lhm_reachable': None}
        window.session = Mock()
        return window

    def test_separator_immediately_before_close_in_every_mode(self):
        for mode in ('taskbar', 'floating', 'docked'):
            for ping_enabled in (False, True):
                with self.subTest(mode=mode, ping_enabled=ping_enabled):
                    self.ns['tk'].reset_mock()
                    self.window.mode = mode
                    self.window.ping_enabled = ping_enabled
                    self.window.ping_monitor = SimpleNamespace(
                        mode='auto', groups={'ipv4': ['1.1.1.1'], 'ipv6': []})
                    self.window._bind_menu()
                    menu = self.ns['tk'].Menu.return_value
                    entries = [c for c in menu.method_calls if c[0].startswith('add_')]
                    self.assertEqual(entries[-1][0], 'add_command')
                    self.assertEqual(entries[-1].kwargs['label'], 'Fechar')
                    self.assertEqual(entries[-2][0], 'add_separator')
                    self.assertEqual(entries[-3].kwargs['label'], 'Configurar limites de uso…')

    def test_menu_options_and_selection_save_only_this_widget(self):
        other = self.make_window(202)
        self.window._bind_menu()
        menu = self.ns['tk'].Menu.return_value
        calls = menu.add_radiobutton.call_args_list
        self.assertEqual([(c.kwargs['label'], c.kwargs['value']) for c in calls],
                         [('Lado: Automático', 'auto'), ('Lado: Esquerda', 'left'),
                          ('Lado: Direita', 'right')])
        calls[2].kwargs['command']()
        self.ns['save_side'].assert_called_once_with('test-settings.ini', self.window.full_cfg,
                                                     'display1', 'right')
        self.window.embedder.reposition.assert_called_once_with()
        other.embedder.reposition.assert_not_called()
        self.window.session.sync_settings.assert_not_called()
        self.ns['tk'].StringVar.return_value.set.assert_called_with('right')

    def test_popup_refreshes_current_value_and_enables_options(self):
        self.window._bind_menu()
        self.window.full_cfg['taskbar_side']['display1'] = 'right'
        callback = self.window.root.bind.call_args.args[1]
        callback(Mock())
        self.ns['tk'].StringVar.return_value.set.assert_called_with('right')
        menu = self.ns['tk'].Menu.return_value
        for label in ('Lado: Automático', 'Lado: Esquerda', 'Lado: Direita'):
            self.assertIn(((label,), {'state': 'normal'}), menu.entryconfigure.call_args_list)
        menu.tk_popup.assert_called_once()

    def test_unknown_monitor_disables_options_and_does_not_save(self):
        self.ns['monitor_device'].return_value = None
        self.window._bind_menu()
        self.window.root.bind.call_args.args[1](Mock())
        menu = self.ns['tk'].Menu.return_value
        for label in ('Lado: Automático', 'Lado: Esquerda', 'Lado: Direita'):
            self.assertIn(((label,), {'state': 'disabled'}), menu.entryconfigure.call_args_list)
        self.window._select_taskbar_side('left')
        self.ns['save_side'].assert_not_called()
        self.window.embedder.reposition.assert_not_called()

    def test_save_failure_restores_variable_and_never_repositions(self):
        self.window._bind_menu()
        for error in (OSError('disk full'), configparser.Error('invalid file')):
            with self.subTest(error=type(error).__name__):
                self.ns['save_side'].side_effect = error
                self.window._select_taskbar_side('right')
                self.ns['tk'].StringVar.return_value.set.assert_called_with('left')
                self.assertEqual(self.window.full_cfg['taskbar_side']['display1'], 'left')
                self.window.embedder.reposition.assert_not_called()
                self.assertIn('save failed', self.ns['_log_event'].call_args.args[0])

    def test_screen_cache_recalculates_only_when_tray_changes(self):
        self.assertEqual(self.window._taskbar_side(), 'left')
        self.assertEqual(self.window._taskbar_side(), 'left')
        self.ns['monitor_device'].assert_called_once_with(101)
        self.window.full_cfg['taskbar_side']['display1'] = 'right'
        self.assertEqual(self.window._taskbar_side(), 'right')
        self.ns['monitor_device'].return_value = r'\\.\DISPLAY2'
        self.window.embedder.tray = 202
        self.assertEqual(self.window._taskbar_side(), 'right')
        self.assertEqual(self.ns['monitor_device'].call_count, 2)
        self.ns['monitor_device'].assert_called_with(202)

    def test_unknown_device_is_cached_until_hwnd_changes(self):
        self.ns['monitor_device'].return_value = None
        self.assertEqual(self.window._taskbar_side(), 'auto')
        self.assertEqual(self.window._taskbar_side(), 'auto')
        self.ns['monitor_device'].assert_called_once_with(101)

    def test_no_side_menu_outside_taskbar(self):
        self.window._bind_menu()
        self.assertEqual(self.ns['tk'].Menu.return_value.add_radiobutton.call_count, 3)
        for mode in ('floating', 'docked'):
            with self.subTest(mode=mode):
                self.ns['tk'].reset_mock()
                self.window.mode = mode
                self.window._bind_menu()
                self.ns['tk'].Menu.return_value.add_radiobutton.assert_not_called()
