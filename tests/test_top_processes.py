"""Top 3 programs by CPU and memory: pure aggregation, formatting and sampling with fakes."""
import os
import struct
import sys
import time
import unittest

import top_processes as tp

GB = 1024 ** 3
MB = 1024 ** 2


def row(pid, name, cpu, rss):
    return tp.ProcRow(pid, name, cpu, rss)


class AggregateTests(unittest.TestCase):
    def test_same_name_is_summed_and_cpu_is_divided_by_logical_cpus(self):
        rows = [row(10, 'chrome.exe', 100.0, GB), row(11, 'chrome.exe', 60.0, GB // 2),
                row(12, 'code.exe', 40.0, MB)]
        top = tp.top_lists(rows, cpu_count=8, total_ram=16 * GB)
        self.assertEqual([(e.name, e.value) for e in top.cpu], [('chrome.exe', 20.0), ('code.exe', 5.0)])
        self.assertEqual(top.mem[0].name, 'chrome.exe')
        self.assertEqual(top.mem[0].value, GB + GB // 2)
        self.assertAlmostEqual(top.mem[0].percent, 9.375)

    def test_name_match_ignores_case(self):
        top = tp.top_lists([row(1, 'Chrome.exe', 10, 5), row(2, 'chrome.EXE', 10, 5)], 1, 100)
        self.assertEqual([(e.name, e.value) for e in top.cpu], [('Chrome.exe', 20.0)])

    def test_only_three_largest_ordered_and_ties_by_name(self):
        rows = [row(i, f'p{i}.exe', i * 10, i * MB) for i in range(1, 7)]
        rows.append(row(99, 'a.exe', 30, 3 * MB))
        top = tp.top_lists(rows, 1, GB)
        self.assertEqual([e.name for e in top.cpu], ['p6.exe', 'p5.exe', 'p4.exe'])
        self.assertEqual([e.name for e in top.mem], ['p6.exe', 'p5.exe', 'p4.exe'])
        tie = tp.top_lists([row(1, 'b.exe', 10, 1), row(2, 'a.exe', 10, 1)], 1, GB)
        self.assertEqual([e.name for e in tie.cpu], ['a.exe', 'b.exe'])

    def test_idle_and_pid_zero_are_ignored(self):
        rows = [row(0, 'System Idle Process', 700.0, 0), row(0, 'x', 500.0, 10 * GB),
                row(4, 'System Idle Process', 90.0, 0), row(5, 'real.exe', 10.0, MB)]
        top = tp.top_lists(rows, 8, 16 * GB)
        self.assertEqual([e.name for e in top.cpu], ['real.exe'])
        self.assertEqual([e.name for e in top.mem], ['real.exe'])

    def test_idle_processes_stay_out_of_the_cpu_list_but_keep_memory(self):
        top = tp.top_lists([row(1, 'a.exe', 0.0, 5 * MB)], 4, GB)
        self.assertEqual(top.cpu, [])
        self.assertEqual([e.name for e in top.mem], ['a.exe'])

    def test_empty_and_zero_division_are_safe(self):
        self.assertEqual(tp.top_lists([], 4, GB), tp.TopLists([], []))
        top = tp.top_lists([row(1, 'a.exe', 10, 5)], 0, 0)
        self.assertEqual(top.cpu[0].value, 10.0)
        self.assertEqual(top.mem[0].percent, 0.0)


class FormatTests(unittest.TestCase):
    def test_cpu_line(self):
        self.assertEqual(tp.format_cpu(tp.Entry('chrome.exe', 12.4, 12.4)), 'chrome.exe  12%')
        self.assertEqual(tp.format_cpu(tp.Entry('a.exe', 3.34, 3.34)), 'a.exe  3,3%')
        self.assertEqual(tp.format_cpu(tp.Entry('a.exe', 0.04, 0.04)), 'a.exe  0,0%')

    def test_memory_line_in_gb_or_mb_with_decimal_comma(self):
        self.assertEqual(tp.format_mem(tp.Entry('chrome.exe', int(1.8 * GB), 11.2)), 'chrome.exe  1,8 GB (11%)')
        self.assertEqual(tp.format_mem(tp.Entry('a.exe', 512 * MB, 3.1)), 'a.exe  512 MB (3,1%)')
        self.assertEqual(tp.format_mem(tp.Entry('a.exe', 0, 0.0)), 'a.exe  0 MB (0,0%)')

    def test_tooltip_text_has_a_title_and_one_line_per_program(self):
        top = tp.top_lists([row(1, 'a.exe', 50, GB)], 1, 8 * GB)
        self.assertEqual(tp.widget_text('cpu', top), 'Maiores em CPU\na.exe  50%')
        self.assertEqual(tp.widget_text('mem', top), 'Maiores em memória\na.exe  1,0 GB (13%)')

    def test_tooltip_text_without_data(self):
        self.assertEqual(tp.widget_text('cpu', None), 'Maiores em CPU\ncoletando…')
        self.assertEqual(tp.widget_text('cpu', tp.TopLists([], [])), 'Maiores em CPU\nsem uso relevante')


class TrayTooltipTests(unittest.TestCase):
    def entries(self, *names):
        return [tp.Entry(name, 12.0, 12.0) for name in names]

    def test_short_text_is_kept_whole(self):
        text = tp.tray_tooltip('CPU: 12%  45°', 'cpu', tp.TopLists(self.entries('a.exe', 'b.exe'), []))
        self.assertEqual(text, 'CPU: 12%  45°\na.exe 12%\nb.exe 12%')

    def test_never_exceeds_127_and_shortens_names_first(self):
        names = ['a-very-long-program-name-number-one.exe', 'another-extremely-long-program-name.exe',
                 'third-long-name-that-goes-on-and-on.exe']
        mem = [tp.Entry(name, 2 * GB, 12.0) for name in names]
        text = tp.tray_tooltip('GPU: 10%  50°   |   MEM: 40%', 'mem', tp.TopLists([], mem))
        self.assertLessEqual(len(text), 127)
        self.assertEqual(len(text.splitlines()), 4)  # all three programs survive
        self.assertIn('…', text)
        self.assertIn('2,0 GB', text)

    def test_head_and_unfit_extra_lines(self):
        top = tp.TopLists(self.entries('a.exe', 'b.exe', 'c.exe'), [])
        extra = '⚠ LibreHardwareMonitor não está rodando (sem leitura de temperatura)'
        text = tp.tray_tooltip('CPU: 12%  --', 'cpu', top, extra)
        self.assertLessEqual(len(text), 127)
        self.assertIn('c.exe', text)
        tight = tp.tray_tooltip('CPU: 12%  --', 'cpu', tp.TopLists(self.entries('a.exe'), []), '⚠ x')
        self.assertTrue(tight.endswith('\n⚠ x'))

    def test_without_data_the_head_is_unchanged(self):
        self.assertEqual(tp.tray_tooltip('CPU: 1%', 'cpu', None), 'CPU: 1%')
        self.assertEqual(tp.tray_tooltip('CPU: 1%', 'cpu', tp.TopLists([], [])), 'CPU: 1%')

    def test_truncate_name(self):
        self.assertEqual(tp.shorten('abcdef.exe', 20), 'abcdef.exe')
        self.assertEqual(tp.shorten('abcdef.exe', 6), 'abcde…')
        self.assertEqual(tp.shorten('abc', 0), '…')


def raw(pid, name, cpu_s=0.0, rss=0, created=1):
    return tp.RawProc(pid, created, name, cpu_s, rss)


class SamplerTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.records = []
        self.sampler = tp.ProcessSampler(lambda: list(self.records), cpu_count=4, total_ram=8 * GB,
                                         clock=lambda: self.now)

    def test_first_reading_is_zero_and_the_next_has_the_delta(self):
        self.records = [raw(10, 'a.exe', cpu_s=5.0, rss=GB)]
        first = self.sampler.sample()
        self.assertEqual(first.cpu, [])
        self.assertEqual(first.mem[0].value, GB)
        self.now += 2.0
        self.records = [raw(10, 'a.exe', cpu_s=7.0, rss=GB)]  # 2 s of CPU in 2 s: one full core
        self.assertEqual(self.sampler.sample().cpu[0].value, 25.0)  # of 4 logical CPUs

    def test_new_process_and_reused_pid_start_at_zero(self):
        self.records = [raw(10, 'a.exe', cpu_s=5.0)]
        self.sampler.sample()
        self.now += 1.0
        self.records = [raw(10, 'b.exe', cpu_s=9.0, created=2), raw(11, 'c.exe', cpu_s=9.0)]
        self.assertEqual(self.sampler.sample().cpu, [])

    def test_counter_going_backwards_is_not_negative_cpu(self):
        self.records = [raw(10, 'a.exe', cpu_s=9.0)]
        self.sampler.sample()
        self.now += 1.0
        self.records = [raw(10, 'a.exe', cpu_s=1.0)]
        self.assertEqual(self.sampler.sample().cpu, [])

    def test_pid_zero_is_skipped_and_gone_processes_are_forgotten(self):
        self.records = [raw(0, 'System Idle Process', cpu_s=900.0, rss=1), raw(10, 'a.exe', cpu_s=1.0)]
        self.sampler.sample()
        self.assertEqual(list(self.sampler._previous), [(10, 1)])
        self.records = []
        self.sampler.sample()
        self.assertEqual(self.sampler._previous, {})


class FakeError(Exception):
    pass


class FakeProcess:
    def __init__(self, pid, name, cpu_s=0.0, rss=0, fail=None):
        self.pid, self._name, self._cpu, self._rss, self.fail = pid, name, cpu_s, rss, fail or {}

    def _maybe(self, key):
        if key in self.fail:
            raise self.fail[key]

    def name(self):
        self._maybe('name')
        return self._name

    def create_time(self):
        return 7.0

    def cpu_times(self):
        self._maybe('cpu')
        return type('Times', (), {'user': self._cpu, 'system': 1.0})()

    def memory_info(self):
        self._maybe('mem')
        return type('MemInfo', (), {'rss': self._rss})()


class PsutilReaderTests(unittest.TestCase):
    def test_denied_or_vanished_processes_do_not_raise(self):
        processes = [FakeProcess(1, 'gone.exe', fail={'name': FakeError()}),
                     FakeProcess(2, 'denied.exe', rss=MB, fail={'cpu': FakeError()}),
                     FakeProcess(3, 'nomem.exe', cpu_s=4.0, fail={'mem': FakeError()}),
                     FakeProcess(4, 'ok.exe', cpu_s=2.0, rss=2 * MB)]
        read = tp.psutil_reader(lambda: iter(processes), errors=(FakeError,))
        self.assertEqual(list(read()), [raw(2, 'denied.exe', 0.0, MB, 7.0), raw(3, 'nomem.exe', 5.0, 0, 7.0),
                                        raw(4, 'ok.exe', 3.0, 2 * MB, 7.0)])

    def test_pid_zero_is_skipped_before_asking_anything(self):
        process = FakeProcess(0, 'System Idle Process', fail={'name': AssertionError()})
        self.assertEqual(list(tp.psutil_reader(lambda: iter([process]), errors=(FakeError,))()), [])


class BufferParserTests(unittest.TestCase):
    BASE = 0x10000

    def build(self, records):
        """Synthetic SystemProcessInformation buffer: 64-bit layout, names after the entries."""
        size = 256
        records = [tuple(r) + (0, 0)[len(r) - 6:] if len(r) < 8 else tuple(r) for r in records]
        names = b''.join(r[1].encode('utf-16-le') for r in records)
        buffer = bytearray(size * len(records) + len(names))
        name_at = size * len(records)
        for index, (pid, name, user, kernel, wset, created, io_read, io_write) in enumerate(records):
            offset = index * size
            encoded = name.encode('utf-16-le')
            struct.pack_into('<I', buffer, offset, 0 if index == len(records) - 1 else size)
            struct.pack_into('<qqq', buffer, offset + 32, created, user, kernel)
            struct.pack_into('<HHxxxxQ', buffer, offset + 56, len(encoded), len(encoded), self.BASE + name_at)
            struct.pack_into('<Q', buffer, offset + 80, pid)
            struct.pack_into('<Q', buffer, offset + 144, wset)
            struct.pack_into('<QQ', buffer, offset + 232, io_read, io_write)
            buffer[name_at:name_at + len(encoded)] = encoded
            name_at += len(encoded)
        return bytes(buffer)

    def test_fields_are_read_from_the_documented_offsets(self):
        data = self.build([(0, '', 0, 0, 8192, 0), (4, 'System', 10_000_000, 20_000_000, 123456, 5),
                           (900, 'Chrome é.exe', 5_000_000, 5_000_000, 999, 6)])
        self.assertEqual(list(tp.parse_process_buffer(data, self.BASE)),
                         [tp.RawProc(0, 0, '', 0.0, 8192), tp.RawProc(4, 5, 'System', 3.0, 123456),
                          tp.RawProc(900, 6, 'Chrome é.exe', 1.0, 999)])

    def test_garbage_name_pointer_does_not_break_the_parser(self):
        data = bytearray(self.build([(4, 'System', 0, 0, 1, 1)]))
        struct.pack_into('<Q', data, 64, 0xFFFFFFFFFFFF)
        self.assertEqual(list(tp.parse_process_buffer(bytes(data), self.BASE))[0].name, '')

    def test_truncated_buffer_stops_quietly(self):
        self.assertEqual(list(tp.parse_process_buffer(bytes(40), self.BASE)), [])


@unittest.skipUnless(sys.platform == 'win32', 'Windows only')
class RealReaderTests(unittest.TestCase):
    def test_bulk_reader_agrees_with_psutil_about_this_process(self):
        import psutil
        mine = [proc for proc in tp.ctypes_reader()() if proc.pid == os.getpid()][0]
        me = psutil.Process()
        self.assertIn('python', mine.name.lower())
        self.assertLess(abs(mine.rss - me.memory_info().rss), 50 * MB)
        self.assertLess(abs(mine.cpu_s - sum(me.cpu_times()[:2])), 2.0)

    def test_default_reader_returns_processes_quickly(self):
        started = time.perf_counter()
        records = tp.default_reader()()
        records = list(records)
        self.assertGreater(len(records), 10)
        self.assertLess(time.perf_counter() - started, 1.5)


class IoTests(unittest.TestCase):
    def test_buffer_reads_the_transfer_counters(self):
        data = BufferParserTests().build([(900, 'a.exe', 0, 0, 1, 6, 5000, 700)])
        proc = list(tp.parse_process_buffer(data, BufferParserTests.BASE))[0]
        self.assertEqual((proc.io_read, proc.io_write), (5000, 700))

    def test_sampler_io_rate_from_the_delta_summed_by_name(self):
        now = [100.0]
        records = [[tp.RawProc(10, 1, 'a.exe', 0.0, 0, 1000, 0), tp.RawProc(11, 1, 'A.exe', 0.0, 0, 0, 0),
                    tp.RawProc(12, 1, 'b.exe', 0.0, 0, 50, 50)]]
        sampler = tp.ProcessSampler(lambda: list(records[0]), cpu_count=1, total_ram=GB, clock=lambda: now[0])
        self.assertEqual(sampler.sample().io, [])
        now[0] = 102.0
        records[0] = [tp.RawProc(10, 1, 'a.exe', 0.0, 0, 5000, 2000), tp.RawProc(11, 1, 'A.exe', 0.0, 0, 1000, 0),
                      tp.RawProc(12, 1, 'b.exe', 0.0, 0, 50, 50)]
        io = sampler.sample().io
        self.assertEqual([(e.name, e.value) for e in io], [('a.exe', 3500.0)])  # (4000+2000+1000)/2 s

    def test_counter_going_back_is_zero(self):
        now = [0.0]
        records = [[tp.RawProc(10, 1, 'a.exe', 0.0, 0, 9000, 9000)]]
        sampler = tp.ProcessSampler(lambda: list(records[0]), cpu_count=1, total_ram=GB, clock=lambda: now[0])
        sampler.sample()
        now[0] = 1.0
        records[0] = [tp.RawProc(10, 1, 'a.exe', 0.0, 0, 1, 1)]
        self.assertEqual(sampler.sample().io, [])

    def test_widget_text_for_disk(self):
        top = tp.TopLists([], [], [tp.Entry('chrome.exe', 12.4 * 1024 ** 2, 0.0)])
        self.assertEqual(tp.widget_text('disk', top), 'Maiores em E/S (aprox.)\nchrome.exe  12,4 MB/s')
        self.assertEqual(tp.widget_text('disk', tp.TopLists([], [])), 'Maiores em E/S (aprox.)\nsem E/S')
        self.assertEqual(tp.widget_text('disk', None), 'Maiores em E/S (aprox.)\ncoletando…')

    def test_psutil_reader_without_io_access_reports_zero(self):
        processes = [FakeProcess(4, 'ok.exe', cpu_s=2.0, rss=2 * MB)]  # FakeProcess has no io_counters
        self.assertEqual(list(tp.psutil_reader(lambda: iter(processes), errors=(FakeError,))()),
                         [tp.RawProc(4, 7.0, 'ok.exe', 3.0, 2 * MB, 0, 0)])


@unittest.skipUnless(sys.platform == 'win32', 'Windows only')
class RealIoTests(unittest.TestCase):
    def test_own_process_read_counter_grows_after_reading_a_file(self):
        import os
        read = tp.ctypes_reader()
        before = next(p for p in read() if p.pid == os.getpid()).io_read
        with open(__file__, 'rb') as handle:
            handle.read()
        after = next(p for p in read() if p.pid == os.getpid()).io_read
        self.assertGreater(after, before)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FakeSampler:
    def __init__(self):
        self.calls = 0

    def sample(self):
        self.calls += 1
        return tp.TopLists([tp.Entry(f'n{self.calls}', 1.0, 1.0)], [])


class MonitorTests(unittest.TestCase):
    def monitor(self, **kwargs):
        self.sampler, self.clock = FakeSampler(), Clock()
        return tp.TopProcessesMonitor(self.sampler, clock=self.clock, **kwargs)

    def test_no_snapshot_before_the_first_cycle(self):
        self.assertIsNone(self.monitor().snapshot())

    def test_first_cycle_primes_the_counters_then_publishes_a_second_reading(self):
        monitor = self.monitor()
        waits = []
        monitor.cycle(wait=waits.append)
        self.assertEqual(self.sampler.calls, 2)
        self.assertEqual(waits, [tp.PRIME_WAIT_S])
        self.assertEqual(monitor.snapshot().cpu[0].name, 'n2')

    def test_recent_data_needs_no_priming(self):
        monitor = self.monitor()
        monitor.cycle(wait=lambda s: None)
        self.clock.now += 2.0
        monitor.cycle(wait=lambda s: self.fail('should not wait'))
        self.assertEqual(self.sampler.calls, 3)

    def test_stale_data_is_primed_again(self):
        monitor = self.monitor()
        monitor.cycle(wait=lambda s: None)
        self.clock.now += 60
        monitor.cycle(wait=lambda s: None)
        self.assertEqual(self.sampler.calls, 4)

    def test_active_flag_follows_the_owners(self):
        monitor = self.monitor()
        self.assertFalse(monitor.active)
        monitor.set_active('a', True)
        monitor.set_active('b', True)
        monitor.set_active('a', False)
        self.assertTrue(monitor.active)
        monitor.set_active('b', False)
        self.assertFalse(monitor.active)
        monitor.set_active('c', False)
        self.assertFalse(monitor.active)

    def test_sampler_failure_is_swallowed_and_keeps_the_last_snapshot(self):
        monitor = self.monitor()
        monitor.cycle(wait=lambda s: None)
        before = monitor.snapshot()
        self.sampler.sample = lambda: (_ for _ in ()).throw(RuntimeError('boom'))
        self.clock.now += 2.0
        monitor.cycle(wait=lambda s: None)
        self.assertEqual(monitor.snapshot(), before)


class TooltipOriginTests(unittest.TestCase):
    SCREEN = (0, 0, 1920, 1080)

    def test_above_a_label_on_a_bottom_taskbar(self):
        self.assertEqual(tp.tooltip_origin((1000, 1040, 1100, 1080), (200, 60), self.SCREEN), (1000, 976))

    def test_below_when_there_is_no_room_above(self):
        self.assertEqual(tp.tooltip_origin((1000, 0, 1100, 40), (200, 60), self.SCREEN), (1000, 44))

    def test_kept_inside_the_screen_horizontally(self):
        self.assertEqual(tp.tooltip_origin((1850, 1040, 1900, 1080), (200, 60), self.SCREEN)[0], 1720)
        self.assertEqual(tp.tooltip_origin((-30, 1040, 20, 1080), (200, 60), self.SCREEN)[0], 0)


if __name__ == '__main__':
    unittest.main()
