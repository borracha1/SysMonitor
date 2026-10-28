"""data_dir(): source mode keeps the project root; frozen mode uses %APPDATA%\\SysMonitor."""
import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_paths

ROOT = Path(__file__).resolve().parents[1]


class DataDirTests(unittest.TestCase):
    def test_source_mode_is_project_root(self):
        self.assertFalse(getattr(sys, 'frozen', False))
        self.assertEqual(app_paths.data_dir().resolve(), ROOT)

    def test_frozen_mode_creates_appdata_folder(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(sys, 'frozen', True, create=True), \
                patch.dict(os.environ, {'APPDATA': tmp}):
            folder = app_paths.data_dir()
            self.assertEqual(folder, Path(tmp) / 'SysMonitor')
            self.assertTrue(folder.is_dir())

    def test_frozen_mode_without_appdata_falls_back_to_roaming(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(sys, 'frozen', True, create=True), \
                patch.dict(os.environ, {}, clear=True), \
                patch.object(Path, 'home', return_value=Path(tmp)):
            folder = app_paths.data_dir()
            self.assertEqual(folder, Path(tmp) / 'AppData' / 'Roaming' / 'SysMonitor')
            self.assertTrue(folder.is_dir())


class EntryPointPathsTests(unittest.TestCase):
    def assignments(self, filename):
        tree = ast.parse((ROOT / filename).read_text(encoding='utf-8'))
        return {node.targets[0].id: ast.unparse(node.value) for node in tree.body
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}

    def test_widget_paths_come_from_data_dir(self):
        values = self.assignments('sys_monitor.py')
        self.assertEqual(values['CONFIG_PATH'], "data_dir() / 'config.ini'")
        self.assertEqual(values['CRASH_LOG_PATH'], "data_dir() / 'crash.log'")
        self.assertEqual(values['EVENT_LOG_PATH'], "data_dir() / 'sysmon.log'")

    def test_tray_paths_come_from_data_dir(self):
        values = self.assignments('tray_monitor.py')
        self.assertEqual(values['CONFIG_PATH'], "data_dir() / 'config.ini'")
        self.assertEqual(values['CRASH_LOG_PATH'], "data_dir() / 'crash.log'")

    def test_entry_points_no_longer_use_dunder_file(self):
        for filename in ('sys_monitor.py', 'tray_monitor.py'):
            with self.subTest(filename=filename):
                self.assertNotIn('__file__', (ROOT / filename).read_text(encoding='utf-8'))

    def test_version(self):
        import version
        self.assertEqual(version.__version__, '1.0.1')
