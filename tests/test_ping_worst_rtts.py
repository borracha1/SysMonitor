"""Worst response time per family for the traffic history; no real toasts."""
import unittest

import ping_monitor as pm
from metrics_collector import Metrics


class WorstRttTests(unittest.TestCase):
    def monitor(self, **kwargs):
        options = dict(targets_v4=('1.1.1.1', '8.8.8.8'), targets_v6=('::1',),
                       notifier=lambda *args: None)
        options.update(kwargs)
        return pm.PingMonitor(Metrics(), **options)

    def test_worst_answer_of_each_family(self):
        monitor = self.monitor()
        monitor.record((12, 30, 7), now=0)
        self.assertEqual(monitor.take_worst_rtts(), {'ipv4': 30, 'ipv6': 7})

    def test_keeps_the_worst_between_reads_and_clears_on_read(self):
        monitor = self.monitor()
        monitor.record((50, 12, 7), now=0)
        monitor.record((12, 12, 90), now=1)
        self.assertEqual(monitor.take_worst_rtts(), {'ipv4': 50, 'ipv6': 90})
        self.assertEqual(monitor.take_worst_rtts(), {'ipv4': None, 'ipv6': None})

    def test_ignores_who_did_not_answer(self):
        monitor = self.monitor()
        monitor.record((None, 12, None), now=0)
        self.assertEqual(monitor.take_worst_rtts(), {'ipv4': 12, 'ipv6': None})

    def test_zero_ms_is_a_valid_answer(self):
        monitor = self.monitor()
        monitor.record((0, 0, 0), now=0)
        self.assertEqual(monitor.take_worst_rtts(), {'ipv4': 0, 'ipv6': 0})

    def test_does_not_depend_on_notification_settings(self):
        monitor = self.monitor(notify=False, notify_ipv4=False, notify_ipv6=False)
        monitor.record((12, 30, 7), now=0)
        self.assertEqual(monitor.take_worst_rtts(), {'ipv4': 30, 'ipv6': 7})

    def test_replacing_groups_clears_the_values(self):
        monitor = self.monitor()
        monitor.record((12, 30, 7), now=0)
        monitor.set_groups(('9.9.9.9',), ('::2',), 'ipv4')
        self.assertEqual(monitor.take_worst_rtts(), {'ipv4': None, 'ipv6': None})

    def test_empty_family_stays_empty(self):
        monitor = self.monitor(targets_v6=())
        monitor.record((12, 30), now=0)
        self.assertEqual(monitor.take_worst_rtts(), {'ipv4': 30, 'ipv6': None})


if __name__ == '__main__':
    unittest.main()
