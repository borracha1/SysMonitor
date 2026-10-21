"""Per-IP toast throttling with controlled monotonic time; no real toasts/I/O."""
import ast
import configparser
from pathlib import Path
import unittest

import ping_monitor as pm
from metrics_collector import Metrics


class PingMuteTests(unittest.TestCase):
    def monitor(self, **kwargs):
        self.notices, self.events = [], []
        options = dict(targets_v4=('1.1.1.1',), targets_v6=('::1', '::2'),
                       return_clean_cycles=1, recover_after=1, cooldown_s=0,
                       notifier=lambda *args: self.notices.append(args), on_event=self.events.append)
        options.update(kwargs)
        return pm.PingMonitor(Metrics(), **options)

    def switch_cycle(self, monitor, now, failed=('::1',)):
        monitor.record(tuple(None if ip in failed else 12 for ip in monitor.targets), now=now)
        monitor.record((12,) * len(monitor.targets), now=now + 0.5)

    def mute_ipv6(self, monitor):
        for now in (0, 10, 20, 30, 40):
            self.switch_cycle(monitor, now)

    def losses(self):
        return [notice for notice in self.notices if notice[0].startswith('Ping: perda')
                or notice[0] == 'Perda de pacotes detectada']

    def info(self):
        return [notice for notice in self.notices if notice[0] == 'Alertas silenciados']

    def test_fifth_alert_mutes_once_omitted_alerts_count_and_logs_continue(self):
        monitor = self.monitor()
        for now in (0, 10, 20, 30):
            self.switch_cycle(monitor, now)
        self.assertEqual(len(self.losses()), 4)
        self.assertEqual(self.info(), [])
        self.switch_cycle(monitor, 40)
        self.assertEqual(self.info(), [('Alertas silenciados',
            '::1 instável: 5 alertas em 2 min. Avisos dele voltam após 30 min sem queda.')])
        self.assertEqual(len(self.losses()), 4)
        self.assertEqual(monitor._muted, {'::1'})
        for now in (50, 60):
            self.switch_cycle(monitor, now)
        self.assertEqual(len(self.losses()), 4)
        self.assertEqual(len(self.info()), 1)
        self.assertEqual(monitor._alert_times['::1'][-1], 60)
        self.assertEqual(sum('Ping: perda' in event for event in self.events), 7)
        self.assertEqual(sum('Ping: de volta' in event for event in self.events), 7)
        self.assertEqual(monitor.active, 'ipv4')

    def test_mixed_subject_still_notifies_and_muted_previous_family_hides_return(self):
        monitor = self.monitor()
        self.mute_ipv6(monitor)
        before = len(self.losses())
        returns = sum(title.startswith('Ping: de volta') for title, _ in self.notices)
        self.switch_cycle(monitor, 50, failed=('::1', '::2'))
        self.assertEqual(len(self.losses()), before + 1)
        self.assertIn('::1 e ::2', self.losses()[-1][1])
        self.assertEqual(monitor._muted, {'::1'})
        self.assertEqual(sum(title.startswith('Ping: de volta') for title, _ in self.notices), returns)
        self.assertEqual(monitor.active, 'ipv4')

    def test_sliding_window_excludes_old_alerts_and_includes_exact_boundary(self):
        for times, muted in [((0, 121, 242, 363, 484, 605), False),
                             ((0, 30, 60, 90, 120), True),
                             ((0, 30, 60, 90, 120.001), False)]:
            with self.subTest(times=times):
                monitor = self.monitor()
                for now in times:
                    self.switch_cycle(monitor, now)
                self.assertEqual(bool(self.info()), muted)
                self.assertEqual('::1' in monitor._muted, muted)

    def test_unmute_after_1800_clean_seconds_resets_history_and_only_logs(self):
        monitor = self.monitor()
        self.mute_ipv6(monitor)
        notices = len(self.notices)
        monitor.record((12, 12, 12), now=1839.999)
        self.assertIn('::1', monitor._muted)
        monitor.record((12, 12, 12), now=1840)
        self.assertNotIn('::1', monitor._muted)
        self.assertFalse(monitor._alert_times.get('::1'))
        self.assertEqual(len(self.notices), notices)
        self.assertTrue(any('::1' in event and 'reativados' in event for event in self.events))
        self.switch_cycle(monitor, 1841)
        self.assertEqual(len(self.losses()), 5)
        self.assertEqual(len(self.info()), 1)

    def test_failure_at_29_minutes_restarts_unmute_even_in_inactive_group(self):
        monitor = self.monitor()
        self.mute_ipv6(monitor)
        monitor.set_mode('ipv4')
        monitor.record((12, None, 12), now=1780)
        monitor.record((12, 12, 12), now=1840)
        self.assertIn('::1', monitor._muted)
        monitor.record((12, 12, 12), now=3579.999)
        self.assertIn('::1', monitor._muted)
        monitor.record((12, 12, 12), now=3580)
        self.assertNotIn('::1', monitor._muted)

    def test_global_loss_omission_also_omits_recovery_but_keeps_logs(self):
        monitor = self.monitor(targets_v6=(), mode='ipv4')
        for now in (0, 10, 20, 30, 40, 50):
            monitor.record((None,), now=now)
            monitor.record((12,), now=now + 1)
        self.assertEqual(len(self.losses()), 4)
        self.assertEqual(sum(title == 'Conexão restabelecida' for title, _ in self.notices), 4)
        self.assertEqual(len(self.info()), 1)
        self.assertFalse(monitor._alert_notified)
        self.assertEqual(sum('packet loss detected' in event for event in self.events), 6)
        self.assertEqual(sum('connection recovered' in event for event in self.events), 6)

    def test_switch_and_global_loss_share_per_ip_alert_count(self):
        monitor = self.monitor()
        for now in (0, 10, 20, 30):
            self.switch_cycle(monitor, now)
        monitor.record((None, None, None), now=40)
        self.assertEqual(monitor._muted, {'::1'})
        self.assertEqual(self.losses()[-1][0], 'Perda de pacotes detectada')
        self.assertTrue(monitor._alert_notified)
        monitor.record((12, 12, 12), now=41)
        self.assertEqual(self.notices[-1][0], 'Conexão restabelecida')

    def test_zero_disables_mute_and_notify_false_never_sends_info(self):
        monitor = self.monitor(mute_after_alerts=0)
        for now in range(8):
            self.switch_cycle(monitor, now)
        self.assertEqual(len(self.losses()), 8)
        self.assertEqual(self.info(), [])
        self.assertEqual(monitor._muted, set())
        monitor = self.monitor(notify=False, mute_after_alerts=1)
        self.mute_ipv6(monitor)
        self.assertEqual(self.notices, [])
        self.assertEqual(sum('Ping: perda' in event for event in self.events), 5)

    def test_set_groups_clears_silence_even_for_same_ips_and_restart_is_clean(self):
        monitor = self.monitor()
        self.mute_ipv6(monitor)
        monitor.set_groups(('1.1.1.1',), ('::1', '::2'), 'ipv4')
        self.assertEqual(monitor._muted, set())
        self.assertEqual(monitor._alert_times, {})
        self.assertEqual(monitor._last_failure, {})
        self.switch_cycle(monitor, 50)
        self.assertEqual(len(self.losses()), 5)
        self.assertEqual(self.monitor()._muted, set())

    def test_multiple_ips_mute_and_reactivate_independently(self):
        monitor = self.monitor()
        for now in (0, 10, 20, 30, 40):
            monitor.record((None, None, None), now=now)
            monitor.record((12, 12, 12), now=now + 1)
        self.assertEqual(monitor._muted, set(monitor.targets))
        self.assertEqual(len(self.info()), 3)
        monitor.record((12, None, 12), now=1780)
        monitor.record((12, 12, 12), now=1840)
        self.assertEqual(monitor._muted, {'::1'})
        self.assertEqual(len(self.info()), 3)
        self.assertEqual(sum('reativados' in event for event in self.events), 2)

    def test_custom_threshold_window_and_unmute_period_affect_behavior(self):
        monitor = self.monitor(mute_after_alerts=2, mute_window_s=10, unmute_after_s=20)
        self.switch_cycle(monitor, 0)
        self.assertEqual(self.info(), [])
        self.switch_cycle(monitor, 10)
        self.assertEqual(monitor._muted, {'::1'})
        self.assertEqual(len(self.losses()), 1)
        monitor.record((12, 12, 12), now=29.999)
        self.assertIn('::1', monitor._muted)
        monitor.record((12, 12, 12), now=30)
        self.assertNotIn('::1', monitor._muted)

    def test_config_defaults_overrides_and_disabled_option(self):
        cfg = configparser.ConfigParser()
        cfg['ping'] = {}
        monitor = pm.PingMonitor.from_config(cfg['ping'], Metrics())
        self.assertEqual((monitor.mute_after_alerts, monitor.mute_window_s, monitor.unmute_after_s),
                         (5, 120, 1800))
        cfg['ping'].update(mute_after_alerts='0', mute_window_s='60', unmute_after_s='900')
        monitor = pm.PingMonitor.from_config(cfg['ping'], Metrics())
        self.assertEqual((monitor.mute_after_alerts, monitor.mute_window_s, monitor.unmute_after_s),
                         (0, 60, 900))
        tree = ast.parse(Path('sys_monitor.py').read_text(encoding='utf-8'))
        defaults = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
                                        and any(isinstance(t, ast.Name) and t.id == 'DEFAULTS' for t in n.targets)))
        self.assertEqual({key: defaults['ping'][key] for key in
                          ('mute_after_alerts', 'mute_window_s', 'unmute_after_s')},
                         {'mute_after_alerts': '5', 'mute_window_s': '120', 'unmute_after_s': '1800'})


if __name__ == '__main__':
    unittest.main()
