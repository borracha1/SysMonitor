"""DiskSource/DiskMonitor with fakes, plus a smoke test against this very PC."""
import sys
import unittest

import disk_monitor as dm

GB = 1024 ** 3


class FakeCounters:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def read(self, letters=None):
        self.calls += 1
        result = self.results.pop(0) if self.results else {}
        if isinstance(result, Exception):
            raise result
        return result


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.volume_calls = 0
        self.model_calls = []

    def volumes(self):
        self.volume_calls += 1
        return {'C': dm.Volume('C', '', 100 * GB, 10 * GB, 90 * GB)}

    def model(self, index):
        self.model_calls.append(index)
        return 'SSD'

    def source(self, counters, fallback=None):
        return dm.DiskSource(counters=counters, fallback=fallback, volumes=self.volumes, model=self.model,
                             space_every=5, log=self.logs.append)

    def test_space_is_reread_every_fifth_cycle_and_model_once(self):
        source = self.source(FakeCounters([{'0 C:': {'idle': 90.0, 'read': 1.0, 'write': 2.0}}] * 6))
        for _ in range(6):
            snap = source.read()
        self.assertEqual(self.volume_calls, 2)
        self.assertEqual(self.model_calls, [0])
        self.assertEqual(snap[0].active, 10.0)

    def test_pdh_failure_logs_once_and_switches_to_fallback(self):
        fallback = FakeCounters([{'0 C:': {'idle': None, 'read': 5.0, 'write': 0.0}}] * 3)
        source = self.source(FakeCounters([OSError('pdh broke')]), fallback)
        first = source.read()
        source.read()
        self.assertEqual(first[0].read, 5.0)
        self.assertIsNone(first[0].active)
        self.assertEqual(len([m for m in self.logs if 'pdh' in m.lower()]), 1)

    def test_new_instance_set_rereads_models(self):
        counters = FakeCounters([{'0 C:': {'idle': 90.0, 'read': 0.0, 'write': 0.0}},
                                 {'1 C:': {'idle': 90.0, 'read': 0.0, 'write': 0.0}}])
        source = self.source(counters)
        source.read()
        source.read()
        self.assertEqual(self.model_calls, [0, 1])


class PsutilCountersTests(unittest.TestCase):
    def test_rates_from_deltas_grouped_by_disk(self):
        now = [10.0]
        samples = [{'PhysicalDrive1': type('C', (), {'read_bytes': 1000, 'write_bytes': 0})()},
                   {'PhysicalDrive1': type('C', (), {'read_bytes': 3000, 'write_bytes': 500})()}]
        counters = dm.PsutilCounters(volume_disk=lambda letter: 1, io=lambda: samples.pop(0),
                                     clock=lambda: now[0])
        self.assertEqual(counters.read(('D', 'F')), {'1 D: F:': {'idle': None, 'read': None, 'write': None}})
        now[0] = 12.0
        self.assertEqual(counters.read(('D', 'F')), {'1 D: F:': {'idle': None, 'read': 1000.0, 'write': 250.0}})

    def test_unmapped_volume_is_skipped(self):
        counters = dm.PsutilCounters(volume_disk=lambda letter: None, io=lambda: {}, clock=lambda: 0.0)
        self.assertEqual(counters.read(('C',)), {})


class MonitorTests(unittest.TestCase):
    def test_cycle_publishes_and_a_failure_logs_once_and_keeps_running(self):
        logs = []

        class Source:
            def __init__(self):
                self.results = [(), RuntimeError('boom'), RuntimeError('boom'), ('ok',)]

            def read(self):
                result = self.results.pop(0)
                if isinstance(result, Exception):
                    raise result
                return result

        monitor = dm.DiskMonitor(source=Source(), log=logs.append)
        self.assertIsNone(monitor.snapshot())
        monitor.cycle()
        self.assertEqual(monitor.snapshot(), ())
        monitor.cycle()
        monitor.cycle()
        self.assertEqual(len(logs), 1)
        monitor.cycle()
        self.assertEqual(monitor.snapshot(), ('ok',))
        self.assertEqual(logs[-1], 'disks: collection recovered')


@unittest.skipUnless(sys.platform == 'win32', 'Windows only')
class RealPcSmokeTests(unittest.TestCase):
    def test_fixed_volumes_include_the_system_drive(self):
        import os
        volumes = dm.fixed_volumes()
        system = os.environ.get('SystemDrive', 'C:')[0].upper()
        self.assertIn(system, volumes)
        self.assertGreater(volumes[system].total, volumes[system].free)

    def test_pdh_gives_an_instance_per_disk_with_the_system_drive(self):
        import os, time
        reader = dm.PdhReader()
        try:
            time.sleep(0.3)
            counters = reader.read()
        finally:
            reader.close()
        system = os.environ.get('SystemDrive', 'C:')[0].upper()
        parsed = [dm.parse_instance(name) for name in counters]
        self.assertTrue(any(p and system in p[1] for p in parsed), counters)
        for values in counters.values():
            self.assertEqual(set(values), {'idle', 'read', 'write'})

    def test_volume_disk_number_and_model_need_no_admin(self):
        import os
        system = os.environ.get('SystemDrive', 'C:')[0].upper()
        number = dm.volume_disk_number(system)
        self.assertIsInstance(number, int)
        model = dm.read_model(number)
        self.assertTrue(model is None or isinstance(model, str))

    def test_disk_source_with_real_pdh_gives_a_snapshot(self):
        import os, time
        source = dm.DiskSource()
        try:
            source.read()
            time.sleep(0.3)
            snapshot = source.read()
        finally:
            source._counters.close()
        system = os.environ.get('SystemDrive', 'C:')[0].upper()
        self.assertTrue(any(system in [v.letter for v in disk.volumes] for disk in snapshot), snapshot)
