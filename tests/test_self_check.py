"""--verificar: imports what the entry point needs, prints version/paths, exits 0, opens nothing."""
import ast
import subprocess
import sys
import unittest
from pathlib import Path

import self_check

ROOT = Path(__file__).resolve().parents[1]


class RunSelfCheckTests(unittest.TestCase):
    def test_ok_prints_version_data_dir_and_frozen(self):
        lines = []
        rc = self_check.run_self_check('widget', ('json',), uia=False, out=lines.append)
        self.assertEqual(rc, 0)
        text = '\n'.join(lines)
        self.assertIn('SysMonitor 1.0.1 (widget)', text)
        self.assertIn('dados: ', text)
        self.assertIn('congelado: False', text)

    def test_missing_module_returns_nonzero(self):
        lines = []
        rc = self_check.run_self_check('widget', ('modulo_que_nao_existe_123',), uia=False,
                                       out=lines.append)
        self.assertNotEqual(rc, 0)
        self.assertTrue(lines[-1].startswith('ERRO'), lines)

    def test_flag_detection(self):
        self.assertTrue(self_check.is_self_check(['--verificar']))
        self.assertFalse(self_check.is_self_check([]))


class EntryPointTests(unittest.TestCase):
    def run_entry(self, script):
        return subprocess.run([sys.executable, script, '--verificar'], cwd=ROOT,
                              capture_output=True, text=True, timeout=120)

    def test_widget_entry(self):
        result = self.run_entry('sys_monitor.py')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SysMonitor 1.0.1 (widget)', result.stdout)

    def test_tray_entry(self):
        result = self.run_entry('tray_monitor.py')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SysMonitor 1.0.1 (bandeja)', result.stdout)

    def test_console_is_not_hidden_when_self_checking(self):
        # Foco de revisão 2: hiding the console on import would hide the
        # terminal that ran --verificar. The module-level call must be guarded.
        for filename in ('sys_monitor.py', 'tray_monitor.py'):
            tree = ast.parse((ROOT / filename).read_text(encoding='utf-8'))
            bare = [n for n in tree.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                    and getattr(n.value.func, 'id', None) == 'hide_console_window']
            guarded = [n for n in tree.body if isinstance(n, ast.If)
                       and 'is_self_check' in ast.unparse(n.test)
                       and 'hide_console_window()' in ast.unparse(n)]
            with self.subTest(filename=filename):
                self.assertEqual(bare, [])
                self.assertEqual(len(guarded), 1)
