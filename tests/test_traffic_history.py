"""Traffic buckets and CSV storage with a fake clock and temporary folders."""
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import traffic_history as th


def rates(up4=0, up6=0, down4=0, down6=0):
    return ((up4, up6), (down4, down6))


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class BucketTests(unittest.TestCase):
    def history(self, clock):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return th.TrafficHistory(Path(directory.name) / 'h.csv', Mock(), clock=clock)

    def test_point_has_average_rates_worst_mark_and_aligned_time(self):
        clock = Clock(1001.0)
        history = self.history(clock)
        history.add_sample(rates(up4=10, down4=100), {'ipv4': 1, 'ipv6': 0})
        clock.now = 1003.0
        history.add_sample(rates(up4=30, down4=300), {'ipv4': 2, 'ipv6': 0})
        clock.now = 1005.0
        history.add_sample(rates(), {})
        self.assertEqual(history.points('ipv4', 3600), [th.FamilyPoint(1000, 200, 20, 2)])

    def test_each_family_reads_its_own_columns(self):
        clock = Clock()
        history = self.history(clock)
        history.add_sample(rates(1, 2, 3, 4), {'ipv4': 0, 'ipv6': 1})
        history.finish_bucket()
        self.assertEqual(history.points('ipv4', 3600), [th.FamilyPoint(1000, 3, 1, 0)])
        self.assertEqual(history.points('ipv6', 3600), [th.FamilyPoint(1000, 4, 2, 1)])

    def test_interval_without_measurement_keeps_empty_rates_and_the_mark(self):
        clock = Clock()
        history = self.history(clock)
        history.add_sample(None, {'ipv4': 2})
        history.finish_bucket()
        self.assertEqual(history.points('ipv4', 3600), [th.FamilyPoint(1000, None, None, 2)])

    def test_points_respect_the_period(self):
        clock = Clock()
        history = self.history(clock)
        history.add_sample(rates(), {})
        history.finish_bucket()
        clock.now = 1000.0 + 3601
        self.assertEqual(history.points('ipv4', 3600), [])
        self.assertEqual(len(history.points('ipv4', 14400)), 1)

    def test_clock_going_back_keeps_points_in_time_order(self):
        clock = Clock(2000.0)
        history = self.history(clock)
        history.add_sample(rates(down4=1), {})
        clock.now = 1000.0
        history.add_sample(rates(down4=2), {})
        history.finish_bucket()
        clock.now = 2001.0
        self.assertEqual([p.epoch for p in history.points('ipv4', 3600)], [1000, 2000])


class StorageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'h.csv'
        self.log = Mock()
        self.clock = Clock(100000.0)

    def history(self):
        return th.TrafficHistory(self.path, self.log, clock=self.clock)

    def add_point(self, history, down4=100):
        history.add_sample(rates(1, 2, down4, 4), {'ipv4': 1, 'ipv6': 2})
        history.finish_bucket()
        self.clock.now += th.BUCKET_S

    def test_round_trip_survives_a_restart(self):
        first = self.history()
        first.load()
        self.add_point(first)
        self.assertTrue(first.flush())
        second = self.history()
        second.load()
        self.assertEqual(second.points('ipv4', 3600), [th.FamilyPoint(100000, 100, 1, 1)])
        self.assertEqual(second.points('ipv6', 3600), [th.FamilyPoint(100000, 4, 2, 2)])

    def test_flush_appends_only_new_points(self):
        history = self.history()
        history.load()
        self.add_point(history)
        history.flush()
        self.add_point(history)
        history.flush()
        history.flush()
        self.assertEqual(len(self.path.read_text(encoding='ascii').splitlines()), 2)

    def test_load_ignores_bad_lines_and_times_out_of_range(self):
        now = int(self.clock.now)
        good = f'{now - 60},1,2,3,4,0,1\n'
        self.path.write_text(
            'lixo\n' + f'{now - 90},1,2\n' + f'{now - 80},1,2,3,4,0,9\n' + f'{now - 70},-1,2,3,4,0,0\n'
            + f'{now - th.KEEP_S - 5},1,2,3,4,0,0\n' + f'{now + th.FUTURE_TOLERANCE_S + 5},1,2,3,4,0,0\n'
            + good + f'{now - 50},1,2,3', encoding='ascii')
        history = self.history()
        history.load()
        self.assertEqual([p.epoch for p in history.points('ipv4', th.KEEP_S)], [now - 60])
        self.assertEqual(self.path.read_text(encoding='ascii'), good.replace('\n', ',,\n'))

    def test_cut_line_from_power_loss_does_not_damage_the_next_write(self):
        now = int(self.clock.now)
        self.path.write_text(f'{now - 60},1,2,3,4,0,1\n{now - 50},1,2', encoding='ascii')
        history = self.history()
        history.load()
        self.add_point(history)
        history.flush()
        second = self.history()
        second.load()
        self.assertEqual(len(second.points('ipv4', 3600)), 2)

    def test_rewrite_drops_points_older_than_four_hours(self):
        history = self.history()
        history.load()
        self.add_point(history)
        history.flush()
        self.clock.now += th.KEEP_S + 1
        self.add_point(history)
        self.assertTrue(history.rewrite())
        self.assertEqual(len(self.path.read_text(encoding='ascii').splitlines()), 1)

    def test_write_failure_logs_once_keeps_points_and_retries(self):
        history = self.history()
        history.load()
        self.add_point(history)
        with patch('builtins.open', side_effect=OSError('denied')), \
                patch('traffic_history.tempfile.NamedTemporaryFile', side_effect=OSError('denied')):
            self.assertFalse(history.flush())
            self.assertFalse(history.flush())
        self.assertEqual(self.log.call_count, 1)
        self.assertEqual(len(history.points('ipv4', 3600)), 1)
        self.assertTrue(history.flush())
        self.assertEqual(len(self.path.read_text(encoding='ascii').splitlines()), 1)

    def test_memory_stays_limited_to_four_hours_of_points(self):
        history = self.history()
        for _ in range(th.MAX_POINTS + 10):
            self.add_point(history)
        self.assertEqual(len(history.points('ipv4', th.KEEP_S * 2)), th.MAX_POINTS)


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.metrics = SimpleNamespace(lock=threading.Lock(), net_rates=rates(1, 2, 3, 4))
        self.history = Mock()
        self.clock = Clock(0.0)

    def recorder(self, ping=None, log=None):
        return th.TrafficRecorder(self.history, self.metrics, ping, log or Mock(),
                                  flush_s=60, rewrite_s=3600, clock=self.clock)

    def test_tick_feeds_rates_and_marks(self):
        ping = Mock()
        ping.take_loss_marks.return_value = {'ipv4': 1, 'ipv6': 0}
        ping.take_worst_rtts.return_value = {'ipv4': 12.0, 'ipv6': None}
        self.recorder(ping).tick()
        self.history.add_sample.assert_called_once_with(rates(1, 2, 3, 4), {'ipv4': 1, 'ipv6': 0},
                                                        {'ipv4': 12.0, 'ipv6': None})

    def test_tick_without_ping_has_no_marks(self):
        self.recorder().tick()
        self.history.add_sample.assert_called_once_with(rates(1, 2, 3, 4), {}, {})

    def test_flush_every_minute_and_rewrite_every_hour(self):
        recorder = self.recorder()
        self.clock.now = 59.0
        recorder.tick()
        self.history.flush.assert_not_called()
        self.clock.now = 60.0
        recorder.tick()
        self.history.flush.assert_called_once()
        self.clock.now = 3600.0
        recorder.tick()
        self.history.rewrite.assert_called_once()

    def test_stop_finishes_the_open_point_and_writes(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'h.csv'
        history = th.TrafficHistory(path, Mock())
        recorder = th.TrafficRecorder(history, self.metrics, None, Mock(), interval_s=0.01)
        recorder.start()
        while not history._bucket:
            pass
        recorder.stop()
        recorder.join(2)
        self.assertFalse(recorder.is_alive())
        self.assertTrue(path.read_text(encoding='ascii'))

    def test_failure_is_logged_once_and_never_ends_the_thread(self):
        log = Mock()
        self.history.add_sample.side_effect = ValueError('boom')
        recorder = th.TrafficRecorder(self.history, self.metrics, None, log, interval_s=0.01)
        recorder.start()
        while self.history.add_sample.call_count < 3:
            pass
        self.assertTrue(recorder.is_alive())
        recorder.stop()
        recorder.join(2)
        self.assertEqual(log.call_count, 1)


if __name__ == '__main__':
    unittest.main()
