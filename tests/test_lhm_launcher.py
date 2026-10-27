"""LHM-down warning: menu entries follow the state, launch tries tasks then runas."""
import tkinter as tk
import unittest
from pathlib import Path

import lhm_launcher as L


class SyncMenuTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label='Configurar limites de uso…')
        self.menu.add_command(label='Fechar')

    def tearDown(self):
        self.root.destroy()

    def labels(self):
        end = self.menu.index('end')
        return [self.menu.type(i) == 'separator' and '---' or self.menu.entrycget(i, 'label')
                for i in range(end + 1)]

    def test_reachable_or_unknown_adds_nothing(self):
        for state in (True, None):
            with self.subTest(state=state):
                self.assertEqual(L.sync_menu(self.menu, state, 0, lambda: None), 0)
                self.assertEqual(self.labels(), ['Configurar limites de uso…', 'Fechar'])

    def test_down_adds_disabled_warning_open_item_and_separator(self):
        shown = L.sync_menu(self.menu, False, 0, lambda: None)
        self.assertEqual(shown, 3)
        self.assertEqual(self.labels(), [L.WARNING_LABEL, L.OPEN_LABEL, '---',
                                         'Configurar limites de uso…', 'Fechar'])
        self.assertEqual(self.menu.entrycget(0, 'state'), 'disabled')
        self.assertEqual(self.menu.entrycget(1, 'state'), 'normal')

    def test_flipping_state_never_duplicates(self):
        # Foco de revisão 4.
        shown = 0
        for state in (False, False, True, False, None, False, True):
            shown = L.sync_menu(self.menu, state, shown, lambda: None)
        self.assertEqual(shown, 0)
        self.assertEqual(self.labels(), ['Configurar limites de uso…', 'Fechar'])
        shown = L.sync_menu(self.menu, False, shown, lambda: None)
        self.assertEqual(self.labels().count(L.WARNING_LABEL), 1)


class OpenLhmTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.logs = [], []
        self.exe = Path(r'C:\Program Files\SysMonitor\LibreHardwareMonitor\LibreHardwareMonitor.exe')

    def task(self, ok_names):
        def run(name):
            self.calls.append(('task', name))
            return name in ok_names
        return run

    def runas(self, ok):
        def run(exe):
            self.calls.append(('runas', exe))
            return ok
        return run

    def test_stops_at_first_task_that_works(self):
        ok = L.open_lhm(self.logs.append, run_task=self.task({'SysMonitor LHM'}),
                        runas=self.runas(True), exe=self.exe, exists=lambda p: True)
        self.assertTrue(ok)
        self.assertEqual(self.calls, [('task', 'SysMonitor LHM')])

    def test_falls_back_to_mateus_task_then_runas(self):
        ok = L.open_lhm(self.logs.append, run_task=self.task({'LibreHardwareMonitor'}),
                        runas=self.runas(True), exe=self.exe, exists=lambda p: True)
        self.assertTrue(ok)
        self.assertEqual(self.calls, [('task', 'SysMonitor LHM'), ('task', 'LibreHardwareMonitor')])
        self.calls.clear()
        ok = L.open_lhm(self.logs.append, run_task=self.task(set()),
                        runas=self.runas(True), exe=self.exe, exists=lambda p: True)
        self.assertTrue(ok)
        self.assertEqual(self.calls[-1], ('runas', self.exe))

    def test_skips_runas_when_exe_missing_and_logs_total_failure(self):
        ok = L.open_lhm(self.logs.append, run_task=self.task(set()),
                        runas=self.runas(True), exe=self.exe, exists=lambda p: False)
        self.assertFalse(ok)
        self.assertNotIn('runas', [c[0] for c in self.calls])
        self.assertEqual(len(self.logs), 1)
        self.assertIn('LibreHardwareMonitor', self.logs[0])

    def test_default_exe_path(self):
        self.assertEqual(L.default_lhm_exe().parts[-3:],
                         ('SysMonitor', 'LibreHardwareMonitor', 'LibreHardwareMonitor.exe'))
