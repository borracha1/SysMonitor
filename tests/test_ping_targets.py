import configparser
import ctypes
import ipaddress
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import ping_monitor as pm
from metrics_collector import Metrics
from test_ping_views import load_definitions


class TargetTests(unittest.TestCase):
    def test_parse_valid_and_canonical(self):
        for values, expected in [
            ([' 1.1.1.1 ', ''], ('1.1.1.1',)),
            (['', '8.8.8.8'], ('8.8.8.8',)),
            (['2001:4860:4860:0:0:0:0:8888'], ('2001:4860:4860::8888',)),
            (['2606:4700:4700::ABCD'], ('2606:4700:4700::abcd',)),
            (['8.8.8.8', ' 2001:4860:4860::8888 '], ('8.8.8.8', '2001:4860:4860::8888')),
        ]:
            with self.subTest(values=values):
                self.assertEqual(pm.parse_ping_targets(values), expected)

    def test_parse_invalid(self):
        for values in [[], ['', ' '], ['1.1.1.1'] * 3, ['8.8.8'], ['1'],
                       ['example.com'], ['256.1.1.1'], ['2001::db8::1'],
                       ['fe80::1%12'], ['1.1.1.1'] * 2,
                       ['2001:4860:4860:0:0:0:0:8888', '2001:4860:4860::8888']]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                pm.parse_ping_targets(values)

    def test_config_strict_and_ipv6(self):
        self.assertEqual(pm._valid_group(['8.8.8', '2001:4860:4860::8888'], 6),
                         ('2001:4860:4860::8888',))
        self.assertEqual(pm._valid_group(['1', 'fe80::1%2'], 6), ())

    def test_save_preserves_only_existing_keys(self):
        from ping_config import save_ping_settings
        for initial in ['[window]\nfont_size = 9\n',
                        '[window]\nfont_size = 9\n[ping]\ntargets = 8.8.8.8\nnotify = false\n']:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'config.ini'
                path.write_text(initial, encoding='utf-8')
                save_ping_settings(path, targets_v4='1.1.1.1', targets_v6='2001:4860:4860::8888')
                cfg = configparser.ConfigParser()
                cfg.read(path, encoding='utf-8')
                self.assertEqual(dict(cfg['window']), {'font_size': '9'})
                expected = {'targets_v4': '1.1.1.1', 'targets_v6': '2001:4860:4860::8888'}
                if 'notify' in initial:
                    expected['notify'] = 'false'
                self.assertEqual(dict(cfg['ping']), expected)
                self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_failed_replace_preserves_file_and_cleans_temp(self):
        from ping_config import save_ping_settings
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.ini'
            path.write_text('[window]\nfont_size = 9\n', encoding='utf-8')
            with patch('ping_config.os.replace', side_effect=OSError('denied')):
                with self.assertRaises(OSError):
                    save_ping_settings(path, targets_v4='1.1.1.1')
            self.assertEqual(path.read_text(encoding='utf-8'), '[window]\nfont_size = 9\n')
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_swap_resets_alert_and_windows(self):
        metrics = Metrics()
        notices = []
        monitor = pm.PingMonitor(metrics, targets_v6=(), notifier=lambda *a: notices.append(a), recover_after=1)
        monitor.record((None, None), now=0)
        self.assertTrue(monitor._alert)
        notices.clear()
        monitor.set_groups((), ('2001:4860:4860::8888',), 'ipv6')
        self.assertEqual(metrics.ping, (('2001:4860:4860::8888', None, None, None),))
        self.assertFalse(monitor._alert)
        self.assertEqual([list(s) for s in monitor._samples], [[]])
        pinger = Mock()
        pinger.ping.return_value = 38
        monitor.record(monitor.probe(pinger), now=1)
        pinger.ping.assert_called_once_with('2001:4860:4860::8888', 1000)
        self.assertEqual(notices, [])
        self.assertEqual(metrics.ping, (('2001:4860:4860::8888', 0.0, 38, True),))

    def test_inflight_old_cycle_is_discarded(self):
        metrics = Metrics()
        monitor = pm.PingMonitor(metrics, notify=False)
        old = monitor.probe(Mock(ping=Mock(return_value=None)))
        monitor.set_groups(('1.0.0.1',), (), 'ipv4')
        monitor.record(old)
        self.assertEqual(metrics.ping, (('1.0.0.1', None, None, None),))


class PingerTests(unittest.TestCase):
    def test_api_family_and_packed_ipv6(self):
        dll = Mock()
        dll.IcmpCreateFile.return_value = 11
        dll.Icmp6CreateFile.return_value = 12
        def ipv4(*args):
            reply = pm._ICMP_ECHO_REPLY.from_buffer(args[5])
            reply.Status, reply.RoundTripTime = 0, 13
            return 1
        def ipv6(*args):
            src, dst = args[4]._obj, args[5]._obj
            self.assertEqual(src.sin6_family, 23)
            self.assertEqual(bytes(src.sin6_addr), bytes(16))
            self.assertEqual(dst.sin6_family, 23)
            self.assertEqual(bytes(dst.sin6_addr), ipaddress.IPv6Address('2001:4860:4860::8888').packed)
            self.assertGreaterEqual(args[10], 256)
            reply = pm._ICMPV6_ECHO_REPLY.from_buffer(args[9])
            reply.Status, reply.RoundTripTime = 0, 38
            return 1
        dll.IcmpSendEcho.side_effect = ipv4
        dll.Icmp6SendEcho2.side_effect = ipv6
        pinger = pm.IcmpPinger(dll=dll)
        self.assertEqual(pinger.ping('1.1.1.1', 1000), 13)
        dll.Icmp6CreateFile.assert_not_called()
        self.assertEqual(pinger.ping('2001:4860:4860::8888', 1000), 38)
        dll.IcmpSendEcho.assert_called_once()
        dll.Icmp6SendEcho2.assert_called_once()
        pinger.close()
        self.assertEqual(dll.IcmpCloseHandle.call_count, 2)

    def test_ipv6_unavailable_logs_once_and_ipv4_survives(self):
        dll = Mock()
        dll.IcmpCreateFile.return_value = 11
        dll.Icmp6CreateFile.return_value = ctypes.c_void_p(-1).value
        events = []
        pinger = pm.IcmpPinger(dll=dll, on_event=events.append)
        self.assertIsNone(pinger.ping('::1', 1000))
        self.assertIsNone(pinger.ping('::1', 1000))
        self.assertEqual(len(events), 1)
        dll.Icmp6CreateFile.assert_called_once()
        dll.IcmpSendEcho.return_value = 0
        self.assertIsNone(pinger.ping('1.1.1.1', 1000))
        dll.IcmpSendEcho.assert_called_once()
        pinger.close()


class LifecycleTests(unittest.TestCase):
    def test_main_executes_reconfigurations_without_delay_or_fallback(self):
        from types import SimpleNamespace
        cfg = configparser.ConfigParser()
        cfg.read_dict({'window': {'display_mode': 'taskbar', 'update_interval_ms': '1000'}, 'ping': {}})
        windows = [Mock(embed_failed=False, exit_requested=False, reconfigure_requested=True)
                   for _ in range(6)]
        windows.append(Mock(embed_failed=False, exit_requested=True))
        factory = Mock(side_effect=windows)
        clock = Mock()
        clock.monotonic.return_value = 0
        logs = Mock()
        ns = load_definitions('sys_monitor.py', {'main'}, {
            'ensure_single_instance': Mock(), 'load_config': lambda: cfg,
            '_enable_dpi_awareness': Mock(), 'Metrics': Metrics, 'Collector': Mock(),
            'PingMonitor': Mock(), 'tk': Mock(), 'MonitorWindow': factory,
            'TaskbarSpaceMonitor': Mock(),
            'TaskbarSession': Mock(return_value=Mock(exit_requested=False)),
            'enumerate_secondary_taskbars': Mock(return_value=[]), 'find_taskbar': Mock(return_value=(1, 2)),
            'wait_for_taskbar': Mock(return_value=True), 'time': clock, '_log_event': logs})
        ns['main']()
        self.assertEqual(factory.call_count, 7)
        self.assertTrue(all(call.args[3] == 'taskbar' for call in factory.call_args_list))
        clock.sleep.assert_not_called()
        logs.assert_not_called()

    def test_save_failure_does_not_apply_and_success_closes_first(self):
        from test_ping_views import PingViewTests, FakeLabel
        ns = PingViewTests().widget_namespace()
        ns.update({'parse_ping_groups': pm.parse_ping_groups, 'CONFIG_PATH': 'unused',
                   'save_ping_settings': Mock(side_effect=OSError('denied')),
                   '_log_event': Mock(), 'configparser': configparser})
        cls = ns['MonitorWindow']
        window = cls.__new__(cls)
        cfg = configparser.ConfigParser()
        cfg['ping'] = {'targets': '8.8.8.8'}
        window.full_cfg = cfg
        window.ping_monitor = Mock()
        window._close_ping_editor = Mock()
        window._destroy = Mock()
        window.reconfigure_requested = False
        error = FakeLabel()
        window._save_ping_targets(['1.1.1.1', '', '', ''], 'ipv4', error)
        self.assertIn('denied', error['text'])
        window._close_ping_editor.assert_not_called()
        window.ping_monitor.set_groups.assert_not_called()
        self.assertEqual(cfg['ping']['targets'], '8.8.8.8')
        ns['save_ping_settings'].side_effect = None
        sequence = Mock()
        sequence.attach_mock(window._close_ping_editor, 'close')
        sequence.attach_mock(window.ping_monitor.set_groups, 'apply')
        sequence.attach_mock(window._destroy, 'destroy')
        window._save_ping_targets(['1.1.1.1', '', '', ''], 'ipv4', error)
        self.assertEqual([call[0] for call in sequence.mock_calls], ['close', 'apply', 'destroy'])
        self.assertEqual(cfg['ping']['targets_v4'], '1.1.1.1')
        self.assertNotIn('targets', cfg['ping'])
        self.assertTrue(window.reconfigure_requested)

    def test_ipv6_width_does_not_overlap_cpu(self):
        from test_ping_views import PingViewTests
        ns = PingViewTests().widget_namespace()
        ns['tk'] = Mock()
        ns['EMBED_KEY_COLOR'] = '#010101'
        font = Mock()
        font.measure.side_effect = lambda text: len(text) * 8
        font.metrics.return_value = 16
        ns['tkfont'] = Mock(Font=Mock(return_value=font))
        cls = ns['MonitorWindow']
        window = cls.__new__(cls)
        cfg = configparser.ConfigParser()
        cfg.read_dict({'window': {'font_size': '9', 'fg_color': 'white',
                                 'accent_up': 'green', 'accent_down': 'blue'}, 'ping': {}})
        window.cfg, window.full_cfg, window.root = cfg['window'], cfg, Mock()
        window.ping_enabled = True
        window.ping_groups = {'ipv4': ('1.1.1.1',), 'ipv6': ('2001:4860:4860::8888',)}
        window._ping_layout_family = 'ipv6'
        window.ping_timeout_ms = 1000
        window._build_embedded_ui()
        x, width = window._cols['ping']
        self.assertEqual(width, font.measure('v6·A ') + font.measure('2001:4860:4860::8888 100% 1000ms'))
        self.assertEqual(x + width + 10, window._cols['hw'][0])

    def test_editor_uses_hidden_root_and_is_singleton(self):
        from test_ping_views import PingViewTests
        ns = PingViewTests().widget_namespace()
        fake_tk = Mock()
        editor = fake_tk.Toplevel.return_value
        editor.winfo_reqwidth.return_value = 450
        editor.winfo_reqheight.return_value = 250
        editor.winfo_screenwidth.return_value = 1920
        editor.winfo_screenheight.return_value = 1080
        ns['tk'] = fake_tk
        cls = ns['MonitorWindow']
        window = cls.__new__(cls)
        window.master, window.root = Mock(), Mock()
        window._closing, window._ping_editor = False, None
        window.ping_monitor = Mock(groups={'ipv4': ('1.1.1.1',), 'ipv6': ()}, preferred='ipv4')
        window._edit_ping_targets()
        fake_tk.Toplevel.assert_called_once_with(window.master)
        editor.title.assert_called_once_with('SysMonitor · destinos de ping')
        editor.attributes.assert_called_once_with('-topmost', True)
        editor.resizable.assert_called_once_with(False, False)
        self.assertEqual([call.args[0] for call in editor.bind.call_args_list], ['<Return>', '<Escape>'])
        fake_tk.Entry.return_value.focus_force.assert_called_once()
        window._edit_ping_targets()
        fake_tk.Toplevel.assert_called_once()
        window._close_ping_editor()
        editor.destroy.assert_called_once()
        self.assertIsNone(window._ping_editor)

    def test_menu_only_offers_editor_when_enabled_with_monitor(self):
        from test_ping_views import PingViewTests
        ns = PingViewTests().widget_namespace()
        fake_tk = Mock()
        ns['tk'] = fake_tk
        cls = ns['MonitorWindow']
        for enabled, monitor, expected in [(True, Mock(), True), (False, Mock(), False), (True, None, False)]:
            fake_tk.reset_mock()
            window = cls.__new__(cls)
            window.mode = "floating"
            window.root, window.master, window.ping_enabled, window.ping_monitor = Mock(), Mock(), enabled, monitor
            if monitor is not None:
                monitor.groups = {'ipv4': ('1.1.1.1',), 'ipv6': ()}
            window._bind_menu()
            labels = [call.kwargs['label'] for call in fake_tk.Menu.return_value.add_command.call_args_list]
            self.assertEqual('Configurar destinos…' in labels, expected)
            self.assertEqual(labels[-1], 'Fechar')
            self.assertEqual(fake_tk.Menu.return_value.add_separator.call_count, 2 + int(expected))
            fake_tk.Menu.return_value.add_checkbutton.assert_called_once()
            self.assertEqual(fake_tk.Menu.return_value.add_checkbutton.call_args.kwargs['label'],
                             'Separar IPv4/IPv6 (estimado)')

    def test_reconfiguration_does_not_count_as_loss(self):
        import ast
        tree = ast.parse(Path('sys_monitor.py').read_text(encoding='utf-8'))
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        loop = next(n for n in ast.walk(main) if isinstance(n, ast.While))
        check = next(n for n in loop.body if isinstance(n, ast.If)
                     and 'reconfigure_requested' in ast.unparse(n.test))
        self.assertIsInstance(check.body[0], ast.Continue)
        loss = next(i for i, n in enumerate(loop.body) if 'quick_losses =' in ast.unparse(n))
        self.assertLess(loop.body.index(check), loss)
