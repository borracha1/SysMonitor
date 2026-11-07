"""Exact per-family loss marks for the traffic history; no real toasts."""
import unittest

import ping_monitor as pm
from metrics_collector import Metrics


class LossMarkTests(unittest.TestCase):
    def monitor(self, **kwargs):
        options = dict(targets_v4=('1.1.1.1', '8.8.8.8'), targets_v6=('::1',),
                       notifier=lambda *args: None)
        options.update(kwargs)
        return pm.PingMonitor(Metrics(), **options)

    def test_marks_none_partial_and_total_per_family(self):
        monitor = self.monitor()
        monitor.record((12, 12, 12), now=0)
        self.assertEqual(monitor.take_loss_marks(), {'ipv4': 0, 'ipv6': 0})
        monitor.record((None, 12, 12), now=1)
        self.assertEqual(monitor.take_loss_marks(), {'ipv4': 1, 'ipv6': 0})
        monitor.record((None, None, None), now=2)
        self.assertEqual(monitor.take_loss_marks(), {'ipv4': 2, 'ipv6': 2})

    def test_reading_clears_the_marks(self):
        monitor = self.monitor()
        monitor.record((None, None, 12), now=0)
        monitor.take_loss_marks()
        self.assertEqual(monitor.take_loss_marks(), {'ipv4': 0, 'ipv6': 0})

    def test_keeps_the_worst_mark_between_reads(self):
        monitor = self.monitor()
        monitor.record((None, None, 12), now=0)
        monitor.record((None, 12, 12), now=1)
        monitor.record((12, 12, 12), now=2)
        self.assertEqual(monitor.take_loss_marks(), {'ipv4': 2, 'ipv6': 0})

    def test_marks_do_not_depend_on_notification_settings(self):
        for options in ({'notify': False}, {'notify_ipv4': False, 'notify_ipv6': False}):
            with self.subTest(options=options):
                monitor = self.monitor(**options)
                monitor.record((None, 12, None), now=0)
                self.assertEqual(monitor.take_loss_marks(), {'ipv4': 1, 'ipv6': 2})

    def test_replacing_groups_clears_the_marks(self):
        monitor = self.monitor()
        monitor.record((None, None, None), now=0)
        monitor.set_groups(('9.9.9.9',), ('::2',), 'ipv4')
        self.assertEqual(monitor.take_loss_marks(), {'ipv4': 0, 'ipv6': 0})

    def test_empty_family_stays_at_zero(self):
        monitor = self.monitor(targets_v6=())
        monitor.record((None, None), now=0)
        self.assertEqual(monitor.take_loss_marks(), {'ipv4': 2, 'ipv6': 0})


if __name__ == '__main__':
    unittest.main()
