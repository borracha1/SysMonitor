"""Family groups, loss display and persistence (no Tk or live network)."""
import configparser
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

import ping_monitor as pm
import ping_config
from metrics_collector import Metrics


class GroupTests(unittest.TestCase):
    def monitor(self, **kwargs):
        self.metrics = Metrics()
        self.notices, self.events = [], []
        return pm.PingMonitor(self.metrics, targets_v4=('8.8.8.8', '1.1.1.1'),
                              targets_v6=('::1', '::2'),
                              return_clean_cycles=3, notifier=lambda *a: self.notices.append(a),
                              on_event=self.events.append, **kwargs)

    def test_auto_shows_group_with_loss(self):
        self.notices, self.events = [], []
        monitor = pm.PingMonitor(
            Metrics(), notifier=lambda *args: self.notices.append(args),
            on_event=self.events.append)
        monitor.record((12, 13, 14, None))
        self.assertEqual(monitor.active, 'ipv6')
        self.assertEqual(tuple(row[0] for row in monitor.metrics.ping), pm.DEFAULT_TARGETS_V6)
        self.assertEqual(monitor.metrics.ping_family, 'ipv6')
        self.assertEqual(self.notices, [('Ping: perda no IPv6',
                         'Sem resposta de 2606:4700:4700::1111; exibindo IPv6.')])
        self.assertEqual(self.events, [f'{self.notices[0][0]}: {self.notices[0][1]}'])

    def test_config_families_legacy_empty_and_defaults(self):
        cases = [
            ({}, pm.DEFAULT_TARGETS, pm.DEFAULT_TARGETS_V6),
            ({'targets': '8.8.8.8,::1,bad'}, ('8.8.8.8',), ('::1',)),
            ({'targets_v4': '::1,bad,1.1.1.1', 'targets_v6': '8.8.8.8,::2'}, ('1.1.1.1',), ('::2',)),
            ({'targets_v4': '', 'targets_v6': '::1'}, (), ('::1',)),
            ({'targets_v4': 'bad', 'targets_v6': ''}, pm.DEFAULT_TARGETS, pm.DEFAULT_TARGETS_V6),
            ({'targets_v4': '1.1.1.1,8.8.8.8,9.9.9.9', 'targets_v6': ''}, ('1.1.1.1', '8.8.8.8'), ()),
        ]
        for values, v4, v6 in cases:
            with self.subTest(values=values):
                cfg = configparser.ConfigParser()
                cfg['ping'] = dict(values, mode='bad', preferred='bad')
                monitor = pm.PingMonitor.from_config(cfg['ping'], Metrics())
                self.assertEqual((monitor.groups['ipv4'], monitor.groups['ipv6']), (v4, v6))
                self.assertEqual((monitor.mode, monitor.preferred), ('auto', 'ipv4'))

    def test_four_fields_validation(self):
        self.assertEqual(pm.parse_ping_groups([' 1.1.1.1 ', '', '::1', ''], 'ipv4'),
                         (('1.1.1.1',), ('::1',)))
        for fields, preferred, text in [
            (['1.1.1.1', '', '', '8.8.8.8'], 'ipv4', 'IPv6 2'),
            (['::1', '', '', ''], 'ipv4', 'IPv4 1'),
            (['1.1.1.1', '1.1.1.1', '', ''], 'ipv4', 'repetidos'),
            (['', '', '::1', '0:0:0:0:0:0:0:1'], 'ipv6', 'repetidos'),
            (['', '', '', ''], 'ipv4', 'pelo menos'),
            (['1.1.1.1', '', '', ''], 'ipv6', 'preferido'),
        ]:
            with self.subTest(fields=fields), self.assertRaisesRegex(ValueError, text):
                pm.parse_ping_groups(fields, preferred)

    def test_save_new_keys_removes_legacy_preserves_rest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.ini'
            path.write_text('[window]\nx=12\n[ping]\ntargets=8.8.8.8\nnotify=false\n', encoding='utf-8')
            ping_config.save_ping_settings(path, targets_v4='1.1.1.1', targets_v6='::1', preferred='ipv6')
            cfg = configparser.ConfigParser()
            cfg.read(path, encoding='utf-8')
            self.assertEqual(dict(cfg['ping']), {'targets_v4': '1.1.1.1', 'targets_v6': '::1',
                                                'preferred': 'ipv6', 'notify': 'false'})
            self.assertEqual(dict(cfg['window']), {'x': '12'})
            ping_config.save_ping_settings(path, mode='ipv6')
            cfg.read(path, encoding='utf-8')
            self.assertEqual(cfg['ping']['mode'], 'ipv6')
            self.assertEqual(cfg['ping']['targets_v4'], '1.1.1.1')

    def test_probes_all_and_publishes_groups(self):
        monitor = self.monitor()
        pinger = Mock(ping=Mock(return_value=12))
        monitor.record(monitor.probe(pinger))
        self.assertEqual([c.args[0] for c in pinger.ping.call_args_list], list(monitor.targets))
        self.assertEqual(len(pinger.ping.call_args_list), 4)
        self.assertEqual([r[0] for r in self.metrics.ping], ['8.8.8.8', '1.1.1.1'])
        self.assertEqual([r[0] for r in self.metrics.ping_other], ['::1', '::2'])
        self.assertEqual(self.metrics.snapshot()['ping_family'], 'ipv4')
        self.assertTrue(self.metrics.snapshot()['ping_auto'])

    def test_loss_return_retains_windows_and_toasts(self):
        monitor = self.monitor()
        monitor.record((12, 13, 14, 15))
        monitor.record((12, 13, None, 15))
        self.assertEqual(self.metrics.ping_family, 'ipv6')
        self.assertEqual(self.metrics.ping[0][1], 50)
        self.assertEqual(self.notices[0], ('Ping: perda no IPv6',
                                         'Sem resposta de ::1; exibindo IPv6.'))
        for _ in range(2):
            monitor.record((12, 13, 14, 15))
            self.assertEqual(self.metrics.ping_family, 'ipv6')
        monitor.record((12, 13, 14, 15))
        self.assertEqual(self.metrics.ping_family, 'ipv4')
        self.assertEqual(self.notices[1], ('Ping: de volta ao IPv4', 'IPv6 sem perda há 3 s.'))
        self.assertEqual(len(monitor._samples[2]), 5)
        self.assertEqual(self.metrics.ping_other[0][1], 20)
        self.assertEqual(len(self.events), 2)

    def test_loss_in_both_groups_keeps_current_family(self):
        monitor = self.monitor()
        monitor.record((None, 12, None, 12))
        self.assertEqual(monitor.active, 'ipv4')
        monitor.record((12, 12, None, 12))
        self.assertEqual(monitor.active, 'ipv6')
        monitor.record((12, None, 12, None))
        self.assertEqual(monitor.active, 'ipv6')
        self.assertEqual(len(self.notices), 1)

    def test_return_requires_60_clean_cycles_of_displayed_group(self):
        monitor = pm.PingMonitor(Metrics(), notify=False)
        monitor.record((12, 12, None, 12))
        # A preferred-group failure must not substitute its clean counter for
        # the displayed group's counter (both lose, so selection stays put).
        monitor.record((None, 12, None, 12))
        for _ in range(59):
            monitor.record((12, 12, 12, 12))
            self.assertEqual(monitor.active, 'ipv6')
        monitor.record((12, 12, 12, 12))
        self.assertEqual(monitor.active, 'ipv4')

    def test_displayed_loss_resets_return_counter(self):
        monitor = self.monitor()
        monitor.record((12, 12, None, 12))
        for _ in range(2):
            monitor.record((12, 12, 12, 12))
        monitor.record((12, 12, None, 12))
        self.assertEqual(monitor._clean['ipv6'], 0)
        for _ in range(2):
            monitor.record((12, 12, 12, 12))
            self.assertEqual(monitor.active, 'ipv6')
        monitor.record((12, 12, 12, 12))
        self.assertEqual(monitor.active, 'ipv4')

    def test_preferred_loss_has_priority_over_clean_return(self):
        for clean_cycles in (0, 2):
            with self.subTest(clean_cycles=clean_cycles):
                monitor = self.monitor()
                monitor.record((12, 12, None, 12))
                for _ in range(clean_cycles):
                    monitor.record((12, 12, 12, 12))
                monitor.record((None, None, 12, 12))
                self.assertEqual(monitor.active, 'ipv4')
                self.assertEqual(self.notices[-1], ('Ping: perda no IPv4',
                                 'Sem resposta de 8.8.8.8 e 1.1.1.1; exibindo IPv4.'))

    def test_manual_never_switches_for_loss_in_other_group(self):
        for mode in ('ipv4', 'ipv6'):
            with self.subTest(mode=mode):
                monitor = self.monitor(mode=mode)
                rtts = (12, 12, None, 12) if mode == 'ipv4' else (None, 12, 12, 12)
                for _ in range(61):
                    monitor.record(rtts)
                self.assertEqual(monitor.active, mode)
                self.assertEqual(self.notices, [])

    def test_empty_group_never_selected_or_counted(self):
        for empty in ('ipv4', 'ipv6'):
            with self.subTest(empty=empty):
                monitor = pm.PingMonitor(Metrics(), **{f'targets_v{4 if empty == "ipv4" else 6}': ()},
                                         preferred=empty, notify=False)
                active = monitor._other(empty)
                for rtts in ((12, 12), (None, 12)) * 61:
                    monitor.record(rtts)
                    self.assertEqual(monitor.active, active)
                    self.assertEqual(monitor.metrics.ping_other, ())
                    self.assertEqual(monitor._clean[empty], 0)

    def test_manual_notify_false_and_global_outage(self):
        monitor = self.monitor(mode='ipv4', notify=False, recover_after=1)
        for _ in range(3):
            monitor.record((None, None, 12, 12))
        self.assertEqual(self.metrics.ping_family, 'ipv4')
        self.assertFalse(monitor._alert)
        monitor.record((None,) * 4)
        self.assertTrue(monitor._alert)
        monitor.record((None, None, 12, 12))
        self.assertFalse(monitor._alert)
        self.assertEqual(self.notices, [])
        monitor.set_mode('auto')
        monitor.record((12, 12, None, 12))
        self.assertEqual(self.metrics.ping_family, 'ipv6')
        self.assertEqual(self.notices, [])

    def test_mode_and_groups_generation_and_empty_family(self):
        monitor = self.monitor()
        old = monitor.probe(Mock(ping=Mock(return_value=99)))
        monitor.set_mode('ipv6')
        monitor.record(old)
        self.assertEqual(self.metrics.ping_family, 'ipv6')
        self.assertFalse(self.metrics.ping_auto)
        self.assertIsNone(self.metrics.ping[0][1])
        monitor.set_mode('auto')
        self.assertEqual(self.metrics.ping_family, 'ipv4')
        old = monitor.probe(Mock(ping=Mock(return_value=99)))
        monitor.set_groups((), ('::3',), 'ipv6')
        monitor.record(old)
        self.assertEqual(self.metrics.ping, (('::3', None, None, None),))
        self.assertEqual(self.metrics.ping_other, ())
        self.assertFalse(monitor._alert)
        with self.assertRaises(ValueError):
            monitor.set_mode('ipv4')

    def test_inflight_change_during_io(self):
        monitor = self.monitor()
        entered, release = threading.Event(), threading.Event()
        def ping(*args):
            entered.set()
            self.assertTrue(release.wait(3))
            return 12
        def cycle():
            monitor.record(monitor.probe(Mock(ping=ping)))
        thread = threading.Thread(target=cycle)
        thread.start()
        self.assertTrue(entered.wait(3))
        monitor.set_groups(('9.9.9.9',), (), 'ipv4')
        release.set()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.metrics.ping, (('9.9.9.9', None, None, None),))

    def test_ipv6_preferred_and_missing_preferred(self):
        metrics = Metrics()
        notices = []
        monitor = pm.PingMonitor(metrics, preferred="ipv6",
                                 return_clean_cycles=2, interval_s=30,
                                 notifier=lambda *args: notices.append(args))
        self.assertEqual(metrics.ping_family, "ipv6")
        monitor.record((12, 12, 12, 12))
        monitor.record((None, 12, 12, 12))
        self.assertEqual(metrics.ping_family, "ipv4")
        monitor.record((12, 12, 12, 12))
        monitor.record((12, 12, 12, 12))
        self.assertEqual(metrics.ping_family, "ipv6")
        self.assertEqual(notices[-1], ("Ping: de volta ao IPv6", "IPv4 sem perda há 1 min."))
        monitor = pm.PingMonitor(metrics, targets_v4=(), preferred="ipv4", notify=False)
        self.assertEqual(metrics.ping_family, "ipv6")
        self.assertEqual(metrics.ping_other, ())
        for _ in range(61):
            monitor.record((12, 12))
        self.assertEqual(metrics.ping_family, "ipv6")

    def test_set_mode_preserves_history_and_empty_mode_falls_back(self):
        monitor = self.monitor()
        monitor.record((12, 12, None, 12))
        monitor.set_mode("ipv6")
        self.assertEqual(self.metrics.ping[0][1], 100)
        monitor.set_mode("auto")
        self.assertEqual(self.metrics.ping_other[0][1], 100)
        metrics = Metrics()
        monitor = pm.PingMonitor(metrics, targets_v4=(), mode="ipv4")
        self.assertEqual(monitor.mode, "ipv6")
        self.assertEqual(metrics.ping_family, "ipv6")

    def test_clean_threshold_not_limited_by_loss_window(self):
        monitor = self.monitor(window=1)
        monitor.record((12, 12, 12, 12))
        monitor.record((12, 12, None, 12))
        self.assertEqual(self.metrics.ping_family, 'ipv6')
        for _ in range(3):
            monitor.record((12, 12, 12, 12))
        self.assertEqual(self.metrics.ping_family, 'ipv4')


if __name__ == '__main__':
    unittest.main()
