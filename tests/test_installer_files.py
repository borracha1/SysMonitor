"""Installer data files: LHM task XML, LHM config, PowerShell helper."""
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / 'installer'
NS = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}


def run_helper(*args):
    return subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                           str(INSTALLER / 'util-instalador.ps1'), *args],
                          capture_output=True, text=True, errors='replace', timeout=60)


class TaskXmlTests(unittest.TestCase):
    def generate(self, lhm_dir, user='S-1-5-21-1-2-3-1001'):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'tarefa.xml'
            result = run_helper('-Acao', 'CriarTarefa', '-LhmDir', lhm_dir, '-UserId', user,
                                '-SomenteGerar', str(out))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return ET.fromstring(out.read_text(encoding='utf-8'))

    def test_values_from_spec(self):
        task = self.generate(r'C:\Program Files\SysMonitor\LibreHardwareMonitor')
        get = lambda path: task.find(path, NS).text
        self.assertEqual(get('t:Principals/t:Principal/t:UserId'), 'S-1-5-21-1-2-3-1001')
        self.assertEqual(get('t:Principals/t:Principal/t:LogonType'), 'InteractiveToken')
        self.assertEqual(get('t:Principals/t:Principal/t:RunLevel'), 'HighestAvailable')
        self.assertIsNotNone(task.find('t:Triggers/t:LogonTrigger', NS))
        self.assertEqual(get('t:Settings/t:DisallowStartIfOnBatteries'), 'false')
        self.assertEqual(get('t:Settings/t:StopIfGoingOnBatteries'), 'false')
        self.assertEqual(get('t:Settings/t:ExecutionTimeLimit'), 'PT0S')
        self.assertEqual(get('t:Settings/t:MultipleInstancesPolicy'), 'IgnoreNew')
        self.assertEqual(get('t:Actions/t:Exec/t:Command'),
                         r'C:\Program Files\SysMonitor\LibreHardwareMonitor\LibreHardwareMonitor.exe')
        self.assertEqual(get('t:Actions/t:Exec/t:WorkingDirectory'),
                         r'C:\Program Files\SysMonitor\LibreHardwareMonitor')

    def test_path_with_ampersand_and_accents(self):
        # Foco de revisão 5.
        folder = r'C:\Program Files\Sys & Mon\Ação'
        task = self.generate(folder)
        self.assertEqual(task.find('t:Actions/t:Exec/t:Command', NS).text,
                         folder + r'\LibreHardwareMonitor.exe')

    def test_stop_lhm_without_process_is_noop(self):
        result = run_helper('-Acao', 'PararLhm', '-LhmDir', r'C:\nao\existe')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_powershell_files_are_ascii(self):
        for name in ('util-instalador.ps1',):
            with self.subTest(name=name):
                (INSTALLER / name).read_bytes().decode('ascii')


class LhmConfigTests(unittest.TestCase):
    def test_web_server_settings(self):
        tree = ET.parse(INSTALLER / 'LibreHardwareMonitor.config')
        values = {node.get('key'): node.get('value') for node in tree.iter('add')}
        self.assertEqual(values['runWebServerMenuItem'], 'true')
        self.assertEqual(values['listenerIp'], '127.0.0.1')
        self.assertEqual(values['listenerPort'], '8085')
        self.assertEqual(values['authenticationEnabled'], 'false')
        for key in ('startMinMenuItem', 'minTrayMenuItem', 'minCloseMenuItem'):
            self.assertEqual(values[key], 'true', key)
        self.assertNotIn('startupMenuItem', values)  # LHM's own autostart stays off
