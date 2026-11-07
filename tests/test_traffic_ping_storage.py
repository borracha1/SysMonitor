"""Ping in points and CSV, including files written by the first 1.1.0 build."""
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import traffic_history as th


def rates(up4=0, up6=0, down4=0, down6=0):
    return ((up4, up6), (down4, down6))


class Clock:
    def __init__(self, now=100000.0):
        self.now = now

    def __call__(self):
        return self.now


class PingPointTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'h.csv'
        self.clock = Clock()

    def history(self):
        return th.TrafficHistory(self.path, Mock(), clock=self.clock)

    def test_point_keeps_the_worst_rounded_ping_of_each_family(self):
        history = self.history()
        history.add_sample(rates(), {}, {'ipv4': 12.4, 'ipv6': None})
        self.clock.now += 1
        history.add_sample(rates(), {}, {'ipv4': 30.6, 'ipv6': 7.0})
        history.finish_bucket()
        self.assertEqual(history.points('ipv4', 3600)[0].ping, 31)
        self.assertEqual(history.points('ipv6', 3600)[0].ping, 7)

    def test_interval_without_answer_has_empty_ping(self):
        history = self.history()
        history.add_sample(rates(), {}, {'ipv4': None, 'ipv6': None})
        history.finish_bucket()
        self.assertIsNone(history.points('ipv4', 3600)[0].ping)

    def test_samples_without_ping_information_still_work(self):
        history = self.history()
        history.add_sample(rates(down4=5), {})
        history.finish_bucket()
        self.assertEqual(history.points('ipv4', 3600), [th.FamilyPoint(100000, 5, 0, 0, None)])

    def test_next_point_starts_without_the_previous_ping(self):
        history = self.history()
        history.add_sample(rates(), {}, {'ipv4': 90})
        self.clock.now += th.BUCKET_S
        history.add_sample(rates(), {}, {})
        history.finish_bucket()
        self.assertEqual([p.ping for p in history.points('ipv4', 3600)], [90, None])

    def test_points_between_uses_the_given_range_in_time_order(self):
        history = self.history()
        for epoch in (100010.0, 100000.0, 100005.0):
            self.clock.now = epoch
            history.add_sample(rates(), {})
            history.finish_bucket()
        self.clock.now = 100100.0
        self.assertEqual([p.epoch for p in history.points_between('ipv4', 100000, 100005)], [100000, 100005])


class PingFileTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'h.csv'
        self.clock = Clock()
        self.now = int(self.clock.now)

    def history(self):
        history = th.TrafficHistory(self.path, Mock(), clock=self.clock)
        history.load()
        return history

    def test_file_from_the_first_build_is_read_and_converted(self):
        self.path.write_text(f'{self.now - 60},1,2,3,4,0,1\n', encoding='ascii')
        history = self.history()
        self.assertEqual(history.points('ipv4', 3600), [th.FamilyPoint(self.now - 60, 1, 2, 0, None)])
        self.assertEqual(history.points('ipv6', 3600), [th.FamilyPoint(self.now - 60, 3, 4, 1, None)])
        self.assertEqual(self.path.read_text(encoding='ascii'), f'{self.now - 60},1,2,3,4,0,1,,\n')

    def test_round_trip_with_ping_including_zero_and_empty(self):
        first = self.history()
        first.add_sample(rates(), {}, {'ipv4': 0, 'ipv6': None})
        first.finish_bucket()
        self.assertTrue(first.flush())
        self.clock.now += th.BUCKET_S
        second = self.history()
        self.assertEqual(second.points('ipv4', 3600)[0].ping, 0)
        self.assertIsNone(second.points('ipv6', 3600)[0].ping)

    def test_wrong_column_count_and_negative_ping_are_ignored(self):
        self.path.write_text(f'{self.now - 60},1,2,3,4,0,1,5\n'
                             f'{self.now - 55},1,2,3,4,0,1,-5,7\n'
                             f'{self.now - 50},1,2,3,4,0,1,5,x\n'
                             f'{self.now - 45},1,2,3,4,0,1,5,7,9\n'
                             f'{self.now - 40},1,2,3,4,0,1,5,7\n', encoding='ascii')
        history = self.history()
        self.assertEqual([p.epoch for p in history.points('ipv4', 3600)], [self.now - 40])

    def test_old_and_new_lines_can_live_in_the_same_file(self):
        self.path.write_text(f'{self.now - 60},1,2,3,4,0,1\n{self.now - 55},1,2,3,4,0,1,5,7\n', encoding='ascii')
        history = self.history()
        self.assertEqual([p.ping for p in history.points('ipv4', 3600)], [None, 5])


class RecorderPingTests(unittest.TestCase):
    def test_tick_feeds_the_worst_response_times(self):
        history, ping = Mock(), Mock()
        ping.take_loss_marks.return_value = {'ipv4': 1, 'ipv6': 0}
        ping.take_worst_rtts.return_value = {'ipv4': 12.0, 'ipv6': None}
        metrics = SimpleNamespace(lock=threading.Lock(), net_rates=rates(1, 2, 3, 4))
        th.TrafficRecorder(history, metrics, ping, Mock(), clock=lambda: 0.0).tick()
        history.add_sample.assert_called_once_with(rates(1, 2, 3, 4), {'ipv4': 1, 'ipv6': 0},
                                                   {'ipv4': 12.0, 'ipv6': None})


if __name__ == '__main__':
    unittest.main()
