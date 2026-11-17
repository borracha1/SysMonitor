"""Pure part of disk_monitor: snapshot, alert, formatting and the window's view."""
import struct
import unittest

import disk_monitor as dm

GB = 1024 ** 3
PREFS = {'disk': (50, 75, 90), 'disk_space': (80, 90), 'colors': ('#low', '#warn', '#high')}


def vol(letter, total=100 * GB, used=40 * GB, label=''):
    return dm.Volume(letter, label, total, used, None if total is None else total - used)


class ParseInstanceTests(unittest.TestCase):
    def test_index_and_letters(self):
        self.assertEqual(dm.parse_instance('0 C:'), (0, ('C',)))
        self.assertEqual(dm.parse_instance('1 D: F:'), (1, ('D', 'F')))
        self.assertEqual(dm.parse_instance('3'), (3, ()))

    def test_total_and_garbage(self):
        self.assertIsNone(dm.parse_instance('_Total'))
        self.assertIsNone(dm.parse_instance('abc'))
        self.assertIsNone(dm.parse_instance(''))


class BuildSnapshotTests(unittest.TestCase):
    def test_groups_volumes_under_their_disk_sorted(self):
        counters = {'1 F: D:': {'idle': 13.0, 'read': 10.0, 'write': 2.0},
                    '0 C:': {'idle': 100.0, 'read': 0.0, 'write': 0.0},
                    '_Total': {'idle': 50.0, 'read': 10.0, 'write': 2.0}}
        snap = dm.build_snapshot(counters, {'C': vol('C'), 'D': vol('D'), 'F': vol('F')}, {1: 'ST2000'})
        self.assertEqual([d.index for d in snap], [0, 1])
        self.assertEqual([v.letter for v in snap[1].volumes], ['D', 'F'])
        self.assertEqual(snap[1].active, 87.0)
        self.assertEqual(snap[1].model, 'ST2000')
        self.assertIsNone(snap[0].model)

    def test_activity_is_clamped_and_missing_idle_is_none(self):
        counters = {'0 C:': {'idle': 130.0, 'read': 1.0, 'write': 1.0},
                    '1 D:': {'idle': -5.0, 'read': None, 'write': None},
                    '2 E:': {'idle': None, 'read': 1.0, 'write': 1.0}}
        snap = dm.build_snapshot(counters, {'C': vol('C'), 'D': vol('D'), 'E': vol('E')}, {})
        self.assertEqual([d.active for d in snap], [0.0, 100.0, None])
        self.assertIsNone(snap[1].read)

    def test_disk_without_a_fixed_lettered_volume_is_left_out(self):
        counters = {'0 C:': {'idle': 90.0, 'read': 0.0, 'write': 0.0},
                    '1': {'idle': 0.0, 'read': 0.0, 'write': 0.0},
                    '2 E:': {'idle': 0.0, 'read': 0.0, 'write': 0.0}}  # E: is not a fixed volume
        snap = dm.build_snapshot(counters, {'C': vol('C')}, {})
        self.assertEqual([d.index for d in snap], [0])


class AlertTests(unittest.TestCase):
    def disk(self, index, active, letters=('C',)):
        return dm.Disk(index, None, active, 0.0, 0.0, tuple(vol(l) for l in letters))

    def test_below_low_or_unknown_is_no_alert(self):
        self.assertIsNone(dm.alert_disk((self.disk(0, 49.9), self.disk(1, None, ('D',))), (50, 75, 90)))
        self.assertIsNone(dm.alert_disk((), (50, 75, 90)))
        self.assertIsNone(dm.alert_disk(None, (50, 75, 90)))

    def test_busiest_disk_wins_with_its_first_letter(self):
        snap = (self.disk(0, 60.0, ('C',)), self.disk(1, 87.0, ('D', 'F')))
        self.assertEqual(dm.alert_disk(snap, (50, 75, 90)), ('D', 87.0))

    def test_tie_goes_to_the_lowest_index(self):
        snap = (self.disk(0, 80.0, ('J',)), self.disk(1, 80.0, ('D',)))
        self.assertEqual(dm.alert_disk(snap, (50, 75, 90)), ('J', 80.0))

    def test_exactly_low_alerts(self):
        self.assertEqual(dm.alert_disk((self.disk(0, 50.0),), (50, 75, 90)), ('C', 50.0))


class FormatTests(unittest.TestCase):
    def test_rate(self):
        self.assertEqual(dm.fmt_rate(None), '--')
        self.assertEqual(dm.fmt_rate(0), '0 B/s')
        self.assertEqual(dm.fmt_rate(512), '512 B/s')
        self.assertEqual(dm.fmt_rate(1536), '1,5 KB/s')
        self.assertEqual(dm.fmt_rate(45.2 * 1024 ** 2), '45,2 MB/s')
        self.assertEqual(dm.fmt_rate(120 * 1024 ** 2), '120 MB/s')
        self.assertEqual(dm.fmt_rate(2 * 1024 ** 3), '2,0 GB/s')

    def test_size(self):
        self.assertEqual(dm.fmt_size(None), '--')
        self.assertEqual(dm.fmt_size(412 * GB), '412,0 GB')
        self.assertEqual(dm.fmt_size(int(0.5 * GB)), '0,5 GB')
        self.assertEqual(dm.fmt_size(999 * GB), '999,0 GB')
        self.assertEqual(dm.fmt_size(1000 * GB), '1,0 TB')
        self.assertEqual(dm.fmt_size(int(1.6 * 1024 * GB)), '1,6 TB')


class ViewTests(unittest.TestCase):
    def test_view_of_one_disk(self):
        snap = (dm.Disk(1, 'ST2000DM008', 87.0, 120 * 1024 ** 2, 0.0,
                        (vol('D', 1000 * GB, 900 * GB, 'Dados'),)),)
        view = dm.disk_view(snap, PREFS, '#fff')
        self.assertEqual(view, [{
            'key': (1, ('D',)),
            'title': 'Disco 1 · ST2000DM008',
            'activity': 'atividade 87%', 'activity_color': '#warn',
            'rates': 'leitura 120 MB/s   escrita 0 B/s',
            'volumes': [{'letter': 'D', 'name': 'D:  Dados', 'fraction': 0.9, 'bar_color': '#high',
                         'space': '900,0 GB / 1,0 TB', 'free': '100,0 GB livre'}]}])

    def test_unknown_values_show_dashes(self):
        snap = (dm.Disk(0, None, None, None, None, (dm.Volume('C', '', None, None, None),)),)
        view = dm.disk_view(snap, PREFS, '#fff')[0]
        self.assertEqual(view['title'], 'Disco 0')
        self.assertEqual(view['activity'], 'atividade --')
        self.assertEqual(view['activity_color'], '#fff')
        self.assertEqual(view['rates'], 'leitura --   escrita --')
        self.assertEqual(view['volumes'][0], {'letter': 'C', 'name': 'C:', 'fraction': None, 'bar_color': '#fff',
                                              'space': '-- / --', 'free': '-- livre'})


class SpaceColorTests(unittest.TestCase):
    def test_bands_low_warning_high(self):
        for percent, expected in [(46, '#low'), (79.9, '#low'), (80, '#warn'), (88, '#warn'),
                                  (89.9, '#warn'), (90, '#high'), (99, '#high')]:
            with self.subTest(percent=percent):
                self.assertEqual(dm.space_color(percent, (80, 90), '#fff', PREFS['colors']), expected)

    def test_no_reading_keeps_normal(self):
        self.assertEqual(dm.space_color(None, (80, 90), '#fff', PREFS['colors']), '#fff')

    def test_view_bar_color_by_used_percent(self):
        for used, expected in [(46, '#low'), (79.9, '#low'), (80, '#warn'), (88, '#warn'), (90, '#high'), (99, '#high')]:
            with self.subTest(used=used):
                snap = (dm.Disk(0, None, 0.0, 0.0, 0.0, (vol('C', 1000 * GB, round(used * 10) * GB),)),)
                self.assertEqual(dm.disk_view(snap, PREFS, '#fff')[0]['volumes'][0]['bar_color'], expected)

    def test_view_without_total_or_used_is_normal(self):
        for volume in (vol('C', 0, 0), dm.Volume('C', '', 100 * GB, None, None)):
            snap = (dm.Disk(0, None, 0.0, 0.0, 0.0, (volume,)),)
            self.assertEqual(dm.disk_view(snap, PREFS, '#fff')[0]['volumes'][0]['bar_color'], '#fff')


class DescriptorTests(unittest.TestCase):
    def descriptor(self, vendor, product):
        buf = bytearray(256)
        struct.pack_into('<II', buf, 0, 1, 256)
        at = 64
        offsets = []
        for text in (vendor, product):
            if text is None:
                offsets.append(0)
                continue
            data = text.encode('ascii') + b'\0'
            buf[at:at + len(data)] = data
            offsets.append(at)
            at += len(data)
        struct.pack_into('<II', buf, 12, *offsets)
        return bytes(buf)

    def test_vendor_and_product_trimmed(self):
        self.assertEqual(dm.parse_device_descriptor(self.descriptor('ATA     ', 'ST2000DM008-2FR102  ')),
                         'ATA ST2000DM008-2FR102')
        self.assertEqual(dm.parse_device_descriptor(self.descriptor(None, 'Samsung SSD 980 1TB')),
                         'Samsung SSD 980 1TB')

    def test_empty_or_short_is_none(self):
        self.assertIsNone(dm.parse_device_descriptor(self.descriptor(None, None)))
        self.assertIsNone(dm.parse_device_descriptor(b'\0' * 10))

    def test_disk_extents_first_disk_number(self):
        buf = struct.pack('<I4xI4xqq', 1, 3, 0, 100)
        self.assertEqual(dm.parse_disk_extents(buf), 3)
        self.assertIsNone(dm.parse_disk_extents(struct.pack('<I4x', 0)))
        self.assertIsNone(dm.parse_disk_extents(b''))
