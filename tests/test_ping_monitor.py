import configparser
import threading
import unittest

import ping_monitor as pm
from metrics_collector import Metrics


class FakePinger:
    def __init__(self, responses):
        self.responses = {ip: iter(values) for ip, values in responses.items()}
        self.calls = []

    def ping(self, ip, timeout_ms):
        self.calls.append(ip)
        return next(self.responses[ip])


class PingMonitorTests(unittest.TestCase):
    def make_monitor(self, responses, **kwargs):
        metrics = Metrics()
        pinger = FakePinger(responses)
        notices = []
        monitor = pm.PingMonitor(metrics, targets_v6=(), pinger_factory=lambda: pinger,
                                 notifier=lambda *args: notices.append(args), **kwargs)
        return monitor, metrics, monitor._pinger_factory(), notices

    def test_probes_every_target_even_when_first_answers(self):
        monitor, metrics, pinger, _ = self.make_monitor(
            {'8.8.8.8': [14], '1.1.1.1': [12]})
        self.assertEqual(metrics.ping, tuple((ip, None, None, None) for ip in pm.DEFAULT_TARGETS))
        monitor.record(monitor.probe(pinger), now=0)
        self.assertEqual(pinger.calls, ['8.8.8.8', '1.1.1.1'])
        self.assertEqual(metrics.ping, (('8.8.8.8', 0.0, 14, True),
                                        ('1.1.1.1', 0.0, 12, True)))
        self.assertEqual(metrics.snapshot()['ping'], metrics.ping)
        self.assertNotIn('ping_loss', metrics.snapshot())

    def test_independent_loss_and_failed_rtt(self):
        monitor, metrics, pinger, notices = self.make_monitor(
            {'8.8.8.8': [14, 14, 14, None], '1.1.1.1': [12] * 4})
        for now in range(4):
            monitor.record(monitor.probe(pinger), now=now)
        self.assertEqual(metrics.ping, (('8.8.8.8', 25.0, None, False),
                                        ('1.1.1.1', 0.0, 12, True)))
        self.assertEqual(notices, [])

    def test_alert_and_recovery_only_for_complete_outage(self):
        monitor, metrics, pinger, notices = self.make_monitor(
            {'8.8.8.8': [None, None, 14, 14],
             '1.1.1.1': [12, None, 12, 12]}, alert_after=1, recover_after=2)
        monitor.record(monitor.probe(pinger), now=0)
        self.assertEqual(notices, [])
        monitor.record(monitor.probe(pinger), now=1)
        self.assertEqual(notices[0][0], 'Perda de pacotes detectada')
        self.assertIn('8.8.8.8 100% · 1.1.1.1 50%', notices[0][1])
        monitor.record(monitor.probe(pinger), now=2)
        self.assertEqual(len(notices), 1)
        monitor.record(monitor.probe(pinger), now=3)
        self.assertEqual(notices[1][0], 'Conexão restabelecida')

    def test_window_is_per_target_and_exact_size(self):
        monitor, metrics, pinger, _ = self.make_monitor(
            {'8.8.8.8': [None, 14, 14], '1.1.1.1': [12, 12, None]}, window=2)
        for now in range(3):
            monitor.record(monitor.probe(pinger), now=now)
        self.assertEqual(metrics.ping[0][1], 0.0)
        self.assertEqual(metrics.ping[1][1], 50.0)

    def test_defaults_config_order_and_disabled(self):
        cfg = configparser.ConfigParser()
        cfg['ping'] = {}
        monitor = pm.PingMonitor.from_config(cfg['ping'], Metrics())
        self.assertEqual(monitor.targets, pm.DEFAULT_TARGETS + pm.DEFAULT_TARGETS_V6)
        cfg['ping']['enabled'] = 'false'
        self.assertIsNone(pm.PingMonitor.from_config(cfg['ping'], Metrics()))

    def test_formatting(self):
        for args, expected in [
            (('8.8.8.8', None, None, None), '8.8.8.8 --'),
            (('8.8.8.8', 0, 14.4, True), '8.8.8.8 0% 14ms'),
            (('8.8.8.8', 25, None, False), '8.8.8.8 25% --ms'),
            (('1.1.1.1', 2.5, 12.6, True), '1.1.1.1 2.5% 13ms'),
        ]:
            with self.subTest(args=args):
                self.assertEqual(pm.fmt_ping_line(*args), expected)
        self.assertEqual(pm.fmt_loss(10), '10%')
        self.assertFalse(pm.ping_has_problem(None, None))
        self.assertFalse(pm.ping_has_problem(0, True))
        self.assertTrue(pm.ping_has_problem(0, False))
        self.assertTrue(pm.ping_has_problem(2.5, True))


if __name__ == '__main__':
    unittest.main()
