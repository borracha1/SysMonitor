"""LHM reachability: down only when the HTTP call fails, not when the CPU sensor is missing."""
import io
import json
import unittest
from unittest.mock import patch

import sensors
from metrics_collector import Metrics
from tests import test_ping_views as views


def fake_response(tree):
    # BytesIO is already a context manager, and json.load only needs .read().
    return io.BytesIO(json.dumps(tree).encode('utf-8'))


class LhmReachableTests(unittest.TestCase):
    def test_unknown_before_first_read(self):
        self.assertIsNone(sensors.LhmReader().reachable)

    def test_unreachable_when_urlopen_fails(self):
        reader = sensors.LhmReader()
        with patch('sensors.urllib.request.urlopen', side_effect=OSError('refused')):
            self.assertIsNone(reader.read_cpu_temp())
        self.assertIs(reader.reachable, False)

    def test_reachable_without_cpu_sensor(self):
        reader = sensors.LhmReader()
        tree = {'Text': 'Sensor', 'Children': [{'Text': 'GPU', 'SensorId': '/gpu/0/temperature/0',
                                                 'Value': '50,0 °C', 'Children': []}]}
        with patch('sensors.urllib.request.urlopen', return_value=fake_response(tree)):
            self.assertIsNone(reader.read_cpu_temp())
        self.assertIs(reader.reachable, True)
        self.assertIn('no CPU temperature sensor', reader.last_error)

    def test_sensor_reader_exposes_reachability(self):
        reader = sensors.SensorReader()
        with patch('sensors.urllib.request.urlopen', side_effect=OSError('refused')), \
                patch.object(sensors.NvmlReader, 'read', return_value=(None, None)):
            data = reader.read()
        self.assertIs(data['lhm_reachable'], False)

    def test_both_metrics_classes_carry_the_flag(self):
        widget_ns = views.PingViewTests().widget_namespace()
        for cls in (Metrics, widget_ns['Metrics']):
            with self.subTest(cls=cls.__module__):
                metrics = cls()
                self.assertIsNone(metrics.lhm_reachable)
                self.assertIn('lhm_reachable', metrics.snapshot())
