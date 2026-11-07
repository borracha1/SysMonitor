"""Family preferences through real handlers, temporary config and isolated menus."""
import ast
import configparser
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import ping_config
import ping_monitor as pm
import test_ping_group_views as views
from taskbar_session import TaskbarSession


class FamilyViewTests(unittest.TestCase):
    def window(self):
        helper = views.GroupViewTests()
        ns = helper.namespace()
        window = helper.window(ns)
        window._ping_mode_var = Mock()
        window._notify_ipv4_var = Mock()
        window._notify_ipv6_var = Mock()
        window.session = Mock()
        return ns, window

    def test_defaults(self):
        tree = ast.parse(Path('sys_monitor.py').read_text(encoding='utf-8'))
        defaults = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
                                        and any(isinstance(t, ast.Name) and t.id == 'DEFAULTS'
                                                for t in n.targets)))
        self.assertEqual(defaults['ping']['notify_ipv4'], 'true')
        self.assertEqual(defaults['ping']['notify_ipv6'], 'true')

    def test_persist_before_apply_and_preserve_legacy_for_both_handlers(self):
        for handler in ('family', 'mode'):
            with self.subTest(handler=handler), tempfile.TemporaryDirectory() as directory:
                ns, window = self.window()
                path = Path(directory) / 'test.ini'
                original = '[ping]\ntargets = 9.9.9.9,::1\nnotify_ipv6 = true\n[other]\nkeep = yes\n'
                path.write_text(original, encoding='utf-8')
                window.full_cfg.read_string(original)
                window.ping_monitor = pm.PingMonitor(window.metrics, targets_v4=('9.9.9.9',),
                                                    targets_v6=('::1',), notifier=Mock())
                ns['CONFIG_PATH'] = path
                def save(*args, **kwargs):
                    self.assertTrue(window.ping_monitor.notify_ipv4)
                    self.assertEqual(window.ping_monitor.mode, 'auto')
                    self.assertIn('targets', window.full_cfg['ping'])
                    ping_config.save_ping_settings(*args, **kwargs)
                ns['save_ping_settings'] = Mock(side_effect=save)
                window._notify_ipv4_var.get.return_value = False
                if handler == 'family':
                    window._select_ping_notify('ipv4')
                else:
                    window._select_ping_mode('ipv6')
                saved = configparser.ConfigParser()
                saved.read(path, encoding='utf-8')
                self.assertNotIn('targets', saved['ping'])
                self.assertNotIn('targets', window.full_cfg['ping'])
                for cfg in (saved, window.full_cfg):
                    self.assertEqual(cfg['ping']['targets_v4'], '9.9.9.9')
                    self.assertEqual(cfg['ping']['targets_v6'], '::1')
                self.assertEqual(saved['other']['keep'], 'yes')
                if handler == 'family':
                    self.assertFalse(saved['ping'].getboolean('notify_ipv4'))
                    self.assertTrue(saved['ping'].getboolean('notify_ipv6'))
                    self.assertFalse(window.ping_monitor.notify_ipv4)
                    self.assertEqual(window.full_cfg['ping']['notify_ipv4'], 'false')
                window.session.sync_settings.assert_called_once()
                ns['_log_event'].assert_called_once()

    def test_save_failures_restore_variable_without_apply_or_sync(self):
        for family in ('ipv4', 'ipv6'):
            for error in (OSError('denied'), configparser.Error('invalid')):
                with self.subTest(family=family, error=error):
                    ns, window = self.window()
                    before = dict(window.full_cfg['ping'])
                    variable = getattr(window, '_notify_' + family + '_var')
                    variable.get.return_value = False
                    ns['save_ping_settings'].side_effect = error
                    window._select_ping_notify(family)
                    self.assertTrue(getattr(window.ping_monitor, 'notify_' + family))
                    variable.set.assert_called_once_with(True)
                    self.assertEqual(dict(window.full_cfg['ping']), before)
                    window.session.sync_settings.assert_not_called()
                    self.assertIn('save failed', ns['_log_event'].call_args.args[0])

    def test_menu_order_states_variables_and_callbacks(self):
        ns, window = self.window()
        window.ping_monitor.set_groups(('9.9.9.9',), (), 'ipv4')
        window._bind_menu()
        menu = ns['tk'].Menu.return_value
        calls = [c for c in menu.method_calls if c[0].startswith('add_')]
        index = next(i for i, c in enumerate(calls) if c.kwargs.get('label') == 'Configurar destinos…')
        family_calls = calls[index + 1:index + 3]
        self.assertEqual([c.kwargs['label'] for c in family_calls], ['Notificar IPv4', 'Notificar IPv6'])
        self.assertEqual([c.kwargs['state'] for c in family_calls], ['normal', 'disabled'])
        self.assertEqual(calls[index + 3][0], 'add_separator')
        self.assertIs(family_calls[0].kwargs['variable'], window._notify_ipv4_var)
        self.assertIs(family_calls[1].kwargs['variable'], window._notify_ipv6_var)
        window._select_ping_notify = Mock()
        for family, call in zip(('ipv4', 'ipv6'), family_calls):
            call.kwargs['command']()
            window._select_ping_notify.assert_called_with(family)

    def test_all_bars_sync_both_preferences_and_skip_closed(self):
        monitor = pm.PingMonitor(views.Metrics(), notify_ipv4=False, notifier=Mock())
        session = TaskbarSession(Mock(), {'window': {}}, Mock(), monitor, Mock(), Mock(),
                                 Mock(), Mock(), Mock())
        windows = [Mock(_closing=False), Mock(_closing=False), Mock(_closing=True)]
        session.primary = windows[0]
        session.secondary = {2: windows[1], 3: windows[2]}
        session.sync_settings()
        for window in windows[:2]:
            window._notify_ipv4_var.set.assert_called_once_with(False)
            window._notify_ipv6_var.set.assert_called_once_with(True)
        windows[2]._notify_ipv4_var.set.assert_not_called()
        windows[2]._notify_ipv6_var.set.assert_not_called()


if __name__ == '__main__':
    unittest.main()
