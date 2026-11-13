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

    def test_point_keeps_the_worst_rounded_ping_of_each_ip(self):
        history = self.history()
        history.add_sample(rates(), {}, {'ipv4': [12.4, 5.0], 'ipv6': [None, 3.0]})
        self.clock.now += 1
        history.add_sample(rates(), {}, {'ipv4': [30.6, None], 'ipv6': [7.0, None]})
        history.finish_bucket()
        first = history.points('ipv4', 3600)[0]
        self.assertEqual((first.ping, first.ping2, first.worst), (31, 5, None))
        second = history.points('ipv6', 3600)[0]
        self.assertEqual((second.ping, second.ping2, second.worst), (7, 3, None))

    def test_interval_without_answer_has_empty_ping(self):
        history = self.history()
        history.add_sample(rates(), {}, {'ipv4': [None, None], 'ipv6': [None, None]})
        history.finish_bucket()
        point = history.points('ipv4', 3600)[0]
        self.assertEqual((point.ping, point.ping2), (None, None))

    def test_samples_without_ping_information_still_work(self):
        history = self.history()
        history.add_sample(rates(down4=5), {})
        history.finish_bucket()
        self.assertEqual(history.points('ipv4', 3600), [th.FamilyPoint(100000, 5, 0, 0, None, None, None)])

    def test_next_point_starts_without_the_previous_ping(self):
        history = self.history()
        history.add_sample(rates(), {}, {'ipv4': [90, None]})
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

    def test_seven_column_file_is_read_and_rewritten_with_eleven(self):
        self.path.write_text(f'{self.now - 60},1,2,3,4,0,1\n', encoding='ascii')
        history = self.history()
        self.assertEqual(history.points('ipv4', 3600), [th.FamilyPoint(self.now - 60, 1, 2, 0)])
        self.assertEqual(history.points('ipv6', 3600), [th.FamilyPoint(self.now - 60, 3, 4, 1)])
        self.assertEqual(self.path.read_text(encoding='ascii'), f'{self.now - 60},1,2,3,4,0,1,,,,\n')

    def test_nine_column_ping_becomes_the_worst_of_both_and_survives_rewrite(self):
        self.path.write_text(f'{self.now - 60},1,2,3,4,0,1,5,7\n', encoding='ascii')
        history = self.history()
        self.assertEqual(history.points('ipv4', 3600), [th.FamilyPoint(self.now - 60, 1, 2, 0, None, None, 5)])
        self.assertEqual(history.points('ipv6', 3600), [th.FamilyPoint(self.now - 60, 3, 4, 1, None, None, 7)])
        self.assertEqual(self.path.read_text(encoding='ascii'), f'{self.now - 60},1,2,3,4,0,1,5,-1,7,-1\n')
        again = self.history()
        self.assertEqual(again.points('ipv4', 3600)[0].worst, 5)

    def test_nine_column_without_ping_has_no_worst(self):
        self.path.write_text(f'{self.now - 60},1,2,3,4,0,1,,7\n', encoding='ascii')
        history = self.history()
        self.assertIsNone(history.points('ipv4', 3600)[0].worst)
        self.assertEqual(history.points('ipv6', 3600)[0].worst, 7)

    def test_round_trip_with_ping_per_ip_including_zero_and_empty(self):
        first = self.history()
        first.add_sample(rates(), {}, {'ipv4': [0, 9], 'ipv6': [None, 4]})
        first.finish_bucket()
        self.assertTrue(first.flush())
        self.clock.now += th.BUCKET_S
        second = self.history()
        point4, point6 = second.points('ipv4', 3600)[0], second.points('ipv6', 3600)[0]
        self.assertEqual((point4.ping, point4.ping2), (0, 9))
        self.assertEqual((point6.ping, point6.ping2), (None, 4))
        self.assertIn(',0,9,,4\n', self.path.read_text(encoding='ascii'))

    def test_wrong_column_count_and_invalid_ping_are_ignored(self):
        self.path.write_text(f'{self.now - 60},1,2,3,4,0,1,5\n'
                             f'{self.now - 55},1,2,3,4,0,1,-5,7\n'
                             f'{self.now - 50},1,2,3,4,0,1,5,x\n'
                             f'{self.now - 45},1,2,3,4,0,1,5,7,9\n'
                             f'{self.now - 44},1,2,3,4,0,1,5,7,9,1,2\n'
                             f'{self.now - 43},1,2,3,4,0,1,-1,2,3,4\n'
                             f'{self.now - 42},1,2,3,4,0,1,1,-2,3,4\n'
                             f'{self.now - 40},1,2,3,4,0,1,5,7\n', encoding='ascii')
        history = self.history()
        self.assertEqual([p.epoch for p in history.points('ipv4', 3600)], [self.now - 40])

    def test_old_and_new_lines_can_live_in_the_same_file(self):
        self.path.write_text(f'{self.now - 60},1,2,3,4,0,1\n{self.now - 58},1,2,3,4,0,1,5,7\n'
                             f'{self.now - 55},1,2,3,4,0,1,5,6,7,8\n', encoding='ascii')
        history = self.history()
        self.assertEqual([(p.ping, p.ping2, p.worst) for p in history.points('ipv4', 3600)],
                         [(None, None, None), (None, None, 5), (5, 6, None)])


class RecorderPingTests(unittest.TestCase):
    def test_tick_feeds_the_worst_response_times(self):
        history, ping = Mock(), Mock()
        ping.take_loss_marks.return_value = {'ipv4': 1, 'ipv6': 0}
        ping.take_worst_rtts.return_value = {'ipv4': [12.0, None], 'ipv6': [None, None]}
        metrics = SimpleNamespace(lock=threading.Lock(), net_rates=rates(1, 2, 3, 4))
        th.TrafficRecorder(history, metrics, ping, Mock(), clock=lambda: 0.0).tick()
        history.add_sample.assert_called_once_with(rates(1, 2, 3, 4), {'ipv4': 1, 'ipv6': 0},
                                                   {'ipv4': [12.0, None], 'ipv6': [None, None]})


if __name__ == '__main__':
    unittest.main()
