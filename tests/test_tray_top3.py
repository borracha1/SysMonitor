"""Tray tooltips of the CPU and memory icons with the top 3 programs (127-character limit)."""
import unittest

import top_processes as tp
from test_ping_views import load_definitions

GB = 1024 ** 3


def namespace():
    ns = {'tray_tooltip': tp.tray_tooltip}
    return load_definitions('tray_monitor.py', {'render_cpu', 'render_gpu_mem'}, ns)


def metrics(**changes):
    values = dict(cpu_percent=12.0, cpu_temp=45.0, cpu_temp_error=False, gpu_usage=10.0, gpu_temp=50.0,
                  gpu_error=False, mem_percent=40.0)
    values.update(changes)
    return values


TOP = tp.TopLists([tp.Entry('chrome.exe', 12.0, 12.0), tp.Entry('code.exe', 3.0, 3.0)],
                  [tp.Entry('vivaldi.exe', 8.6 * GB, 27.0), tp.Entry('claude.exe', 1.1 * GB, 3.5)])


class TrayTop3Tests(unittest.TestCase):
    def test_without_top_the_tooltips_are_the_old_ones(self):
        ns = namespace()
        self.assertEqual(ns['render_cpu'](metrics())[1], 'CPU: 12%  45°')
        self.assertEqual(ns['render_gpu_mem'](metrics())[1], 'GPU: 10%  50°   |   MEM: 40%')
        self.assertEqual(ns['render_gpu_mem'](metrics(gpu_usage=None, gpu_error=True))[1],
                         'MEM: 40%\n⚠ Sem leitura da GPU (NVML)')

    def test_cpu_icon_lists_the_top_cpu_programs(self):
        lines, tooltip = namespace()['render_cpu'](metrics(), TOP)
        self.assertEqual(lines, ['12%', '45°'])
        self.assertEqual(tooltip, 'CPU: 12%  45°\nchrome.exe 12%\ncode.exe 3,0%')

    def test_memory_shows_in_the_gpu_icon_or_in_the_fallback(self):
        ns = namespace()
        self.assertEqual(ns['render_gpu_mem'](metrics(), TOP)[1],
                         'GPU: 10%  50°   |   MEM: 40%\nvivaldi.exe 8,6 GB\nclaude.exe 1,1 GB')
        lines, tooltip = ns['render_gpu_mem'](metrics(gpu_usage=None), TOP)
        self.assertEqual(lines, ['40%', 'MEM'])
        self.assertEqual(tooltip, 'MEM: 40%\nvivaldi.exe 8,6 GB\nclaude.exe 1,1 GB')

    def test_warning_only_stays_when_it_fits(self):
        ns = namespace()
        full = tp.TopLists([tp.Entry(f'program-number-{i}-with-a-long-name.exe', 10.0, 10.0) for i in range(3)], [])
        tooltip = ns['render_cpu'](metrics(cpu_temp=None, cpu_temp_error=True), full)[1]
        self.assertLessEqual(len(tooltip), 127)
        self.assertNotIn('LibreHardwareMonitor', tooltip)
        self.assertEqual(len(tooltip.splitlines()), 4)
        self.assertIn('LibreHardwareMonitor', ns['render_cpu'](metrics(cpu_temp=None, cpu_temp_error=True))[1])


if __name__ == '__main__':
    unittest.main()
