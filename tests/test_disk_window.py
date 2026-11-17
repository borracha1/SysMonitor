"""DiskWindow in a real, hidden Tk root (never the widget or the Explorer)."""
import tkinter as tk
import unittest

import disk_monitor as dm
from disk_ui import DiskWindow

GB = 1024 ** 3
PREFS = {'disk': (50, 75, 90), 'disk_space': (80, 90), 'colors': ('#5fb0ff', '#ff9d5f', '#ff6b6b')}


def snap(*letters_per_disk, active=87.0):
    return tuple(dm.Disk(i, f'Model {i}', active, 1024.0, 0.0,
                         tuple(dm.Volume(l, 'Dados', 100 * GB, 50 * GB, 50 * GB) for l in letters))
                 for i, letters in enumerate(letters_per_disk))


class Monitor:
    def __init__(self, value):
        self.value = value

    def snapshot(self):
        return self.value


class DiskWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.opened = []
        self.monitor = Monitor(snap(('C',), ('D', 'F')))
        self.ui = DiskWindow(self.root, self.monitor, lambda: PREFS, open_volume=self.opened.append,
                             work_area=lambda: (0, 0, 1920, 1040))

    def tearDown(self):
        self.ui.close()
        self.root.destroy()

    def texts(self):
        return [[block['title'].cget('text'), block['activity'].cget('text'), block['rates'].cget('text'),
                 [row['name'].cget('text') for row in block['volumes']]] for block in self.ui.blocks]

    def test_show_builds_one_block_per_disk(self):
        self.ui.show()
        self.assertEqual(self.ui.window.title(), 'SysMonitor · Discos')
        self.assertEqual(self.texts(), [['Disco 0 · Model 0', 'atividade 87%', 'leitura 1,0 KB/s   escrita 0 B/s',
                                         ['C:  Dados']],
                                        ['Disco 1 · Model 1', 'atividade 87%', 'leitura 1,0 KB/s   escrita 0 B/s',
                                         ['D:  Dados', 'F:  Dados']]])
        self.assertEqual(self.ui.blocks[0]['activity'].cget('fg'), '#ff9d5f')

    def test_show_twice_reuses_the_window(self):
        self.ui.show()
        first = self.ui.window
        self.ui.show()
        self.assertIs(self.ui.window, first)

    def test_refresh_updates_text_without_rebuilding(self):
        self.ui.show()
        label = self.ui.blocks[0]['activity']
        self.monitor.value = snap(('C',), ('D', 'F'), active=10.0)
        self.ui.refresh()
        self.assertIs(self.ui.blocks[0]['activity'], label)
        self.assertEqual(label.cget('text'), 'atividade 10%')

    def test_volume_disappearing_rebuilds_and_does_not_break(self):
        self.ui.show()
        self.monitor.value = snap(('C',), ('D',))
        self.ui.refresh()
        self.assertEqual(self.texts()[1][3], ['D:  Dados'])
        self.monitor.value = ()
        self.ui.refresh()
        self.assertEqual(self.ui.blocks, [])
        self.assertEqual(self.ui.empty.cget('text'), 'Nenhum disco encontrado')
        self.monitor.value = None
        self.ui.refresh()

    def test_double_click_opens_the_volume(self):
        self.ui.show()
        self.ui.window.update()
        name = self.ui.blocks[1]['volumes'][1]['name']
        for sequence in ('<ButtonPress-1>', '<ButtonRelease-1>', '<ButtonPress-1>'):  # Tk cannot synthesize Double
            name.event_generate(sequence, x=2, y=2)
        self.assertEqual(self.opened, ['F'])

    def test_close_cancels_the_timer_and_escape_closes(self):
        self.ui.show()
        self.ui.window.update()
        self.ui.window.focus_force()
        self.ui.window.update()
        self.ui.window.event_generate('<Escape>')
        self.assertIsNone(self.ui.window)
        self.ui.close()  # idempotent
