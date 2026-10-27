"""Per-screen preference persistence and safe, read-only monitor discovery."""
import configparser
import ctypes
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


class ScreenSideTests(unittest.TestCase):
    def setUp(self):
        import screen_side
        self.api = screen_side

    def test_sides_and_device_key(self):
        self.assertEqual(self.api.SIDES, ('auto', 'left', 'right'))
        for device, key in [(r'\\.\DISPLAY1', 'display1'), (r'\\.\DISPLAY12', 'display12'),
                            ('DiS-PLAY_2!', 'display2'), ('', None), (None, None), ('!!!', None)]:
            with self.subTest(device=device):
                self.assertEqual(self.api.screen_key(device), key)

    def test_load_missing_invalid_and_valid(self):
        cfg = configparser.ConfigParser()
        self.assertEqual(self.api.load_side(cfg, None), 'auto')
        self.assertEqual(self.api.load_side(cfg, 'display1'), 'auto')
        cfg.read_dict({'taskbar_side': {'display1': 'left', 'display2': 'right',
                                      'display3': 'bad', 'display4': 'auto'}})
        for key, expected in [('display1', 'left'), ('display2', 'right'), ('display3', 'auto'),
                              ('display4', 'auto'), (None, 'auto'), ('missing', 'auto')]:
            with self.subTest(key=key):
                self.assertEqual(self.api.load_side(cfg, key), expected)

    def test_save_round_trip_preserves_other_settings_and_removes_auto(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.ini'
            path.write_text('[window]\nnet_split=true\n[ping]\nmode=ipv4\n'
                            '[taskbar_side]\ndisplay2=right\n', encoding='utf-8')
            cfg = configparser.ConfigParser()
            cfg.read(path, encoding='utf-8')
            for side in ('left', 'auto'):
                self.api.save_side(path, cfg, 'display1', side)
                loaded = configparser.ConfigParser()
                loaded.read(path, encoding='utf-8')
                self.assertEqual(self.api.load_side(loaded, 'display1'), side)
                self.assertEqual(self.api.load_side(cfg, 'display1'), side)
                self.assertEqual(loaded['window']['net_split'], 'true')
                self.assertEqual(loaded['ping']['mode'], 'ipv4')
                self.assertEqual(loaded['taskbar_side']['display2'], 'right')
                self.assertEqual('display1' in loaded['taskbar_side'], side != 'auto')
                self.assertEqual('display1' in cfg['taskbar_side'], side != 'auto')

    def test_save_uses_selective_writer_and_publishes_only_after_success(self):
        cfg = configparser.ConfigParser()
        cfg.read_dict({'taskbar_side': {'display1': 'right'}})
        with patch.object(self.api.ping_config, 'save_settings') as save:
            self.api.save_side('unused.ini', cfg, 'display1', 'left')
            save.assert_called_once_with('unused.ini', 'taskbar_side', {'display1': 'left'})
            save.reset_mock()
            self.api.save_side('unused.ini', cfg, 'display1', 'auto')
            save.assert_called_once_with('unused.ini', 'taskbar_side', {}, remove=('display1',))
            save.side_effect = OSError('disk full')
            with self.assertRaises(OSError):
                self.api.save_side('unused.ini', cfg, 'display1', 'right')
            self.assertNotIn('display1', cfg['taskbar_side'])
            save.reset_mock()
            self.api.save_side('unused.ini', cfg, None, 'left')
            save.assert_not_called()

    def test_monitor_device_desktop_and_zero_do_not_raise(self):
        u32 = ctypes.WinDLL('user32', use_last_error=True)
        u32.GetDesktopWindow.restype = ctypes.c_void_p
        self.assertTrue(self.api.monitor_device(u32.GetDesktopWindow()).startswith('\\\\.\\DISPLAY'))
        result = self.api.monitor_device(0)
        self.assertTrue(result is None or result.startswith('\\\\.\\DISPLAY'))

    def test_monitor_device_api_failures_and_structure_size(self):
        u32 = Mock()
        u32.MonitorFromWindow.return_value = 123
        def info(handle, pointer):
            value = pointer._obj
            self.assertEqual(value.cbSize, ctypes.sizeof(value))
            value.szDevice = r'\\.\DISPLAY9'
            return True
        u32.GetMonitorInfoW.side_effect = info
        with patch.object(self.api.ctypes, 'WinDLL', return_value=u32):
            self.assertEqual(self.api.monitor_device(42), r'\\.\DISPLAY9')
            u32.MonitorFromWindow.assert_called_once_with(42, 2)
            u32.GetMonitorInfoW.side_effect = None
            u32.GetMonitorInfoW.return_value = False
            self.assertIsNone(self.api.monitor_device(42))
            u32.MonitorFromWindow.return_value = 0
            self.assertIsNone(self.api.monitor_device(42))
            u32.MonitorFromWindow.side_effect = OSError('unavailable')
            self.assertIsNone(self.api.monitor_device(42))
