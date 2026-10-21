import ast
import configparser
import ctypes
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import unittest
from unittest.mock import Mock, patch

import net_split as net
import ping_monitor as pm
from ping_config import save_window_settings
from test_taskbar_clicks import namespace
from test_ping_views import load_definitions


class SplitTests(unittest.TestCase):
    def test_proportions_separate_directions(self):
        self.assertEqual(net.split_rates(400, 800, ((10, 20), (30, 40)),
                                         ((11, 23), (33, 41))), ((300, 100), (200, 600)))

    def test_zero_wrap_reset_failure(self):
        self.assertEqual(net.split_rates(400, 800, ((1, 1), (1, 1)),
                                         ((1, 1), (1, 1))), ((0, 0), (0, 0)))
        self.assertEqual(net.packet_delta(5, 0xFFFFFFFD), 8)
        self.assertEqual(net.packet_delta(5, 100), 0)
        self.assertIsNone(net.split_rates(1, 2, None, ((1, 1), (1, 1))))
        self.assertIsNone(net.split_rates(1, 2, ((1, 1), (1, 1)), None))

    def test_failure_logs_once_and_recovers(self):
        log = Mock()
        reader = net.PacketCounters(log)
        reader.api = Mock(return_value=5)
        self.assertIsNone(reader.read())
        self.assertIsNone(reader.read())
        log.assert_called_once()
        reader.api.return_value = 0
        self.assertEqual(reader.read(), ((0, 0), (0, 0)))
        self.assertEqual(reader.api.call_args.args[1], 23)
        self.assertEqual(ctypes.sizeof(net.MIB_IPSTATS), 92)

    def test_atomic_save_keeps_other_sections_and_failure_preserves_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.ini'
            path.write_text('[window]\nx = 7\n[ping]\ntargets = 1.1.1.1\n', encoding='utf-8')
            save_window_settings(path, net_split='true')
            before = path.read_bytes()
            cfg = configparser.ConfigParser()
            cfg.read(path)
            self.assertEqual(cfg['ping']['targets'], '1.1.1.1')
            self.assertEqual(cfg['window']['x'], '7')
            self.assertEqual(cfg['window']['net_split'], 'true')
            with patch('ping_config.os.replace', side_effect=OSError('denied')):
                with self.assertRaises(OSError):
                    save_window_settings(path, net_split='false')
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_split_activation_relayout_reenters_and_disables_cells(self):
        ns = namespace()
        load_definitions('sys_monitor.py', {'fmt_speed'}, ns)
        cells = []
        def make_cell(*args, **kwargs):
            cell = Mock()
            cells.append(cell)
            return cell
        ns['tk'] = Mock()
        ns['tk'].Label.side_effect = make_cell
        window = ns['MonitorWindow'].__new__(ns['MonitorWindow'])
        window.mode = 'taskbar'
        window.net_split = True
        window._space_level = 0
        window._net_active = False
        window._net_cells = []
        window._net_font = Mock()
        window._net_font.measure.side_effect = len
        window.cfg = {'accent_up': 'green', 'accent_down': 'blue'}
        window.lbl_up, window.lbl_down = Mock(), Mock()
        window._ping_layout_family = 'ipv4'
        metrics = {'net_rates': ((100, 200), (300, 400))}
        def relayout(family):
            if window._space_level == 0:
                self.assertEqual(len(window._net_cells), 8)
                window._space_level = 1
                window._update_net_split(metrics)
        window._relayout_ping = Mock(side_effect=relayout)

        window._update_net_split(metrics)

        self.assertEqual(window._relayout_ping.call_count, 2)
        self.assertFalse(window._net_active)
        self.assertEqual(window._net_cells, [])
        self.assertTrue(window.net_split)
        self.assertEqual(len(cells), 8)
        for cell in cells:
            cell.destroy.assert_called_once()
            cell.config.assert_not_called()
            cell.place.assert_not_called()

    def test_real_tk_split_alignment_relayout_and_fallback_all_modes(self):
        tree = ast.parse(Path('sys_monitor.py').read_text(encoding='utf-8'))
        defaults = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
                                        and any(isinstance(t, ast.Name) and t.id == 'DEFAULTS' for t in n.targets)))
        for mode, ping_enabled in ((mode, enabled) for mode in ('taskbar', 'docked', 'floating')
                                   for enabled in (False, True)):
            with self.subTest(mode=mode, ping_enabled=ping_enabled):
                ns = namespace()
                load_definitions('sys_monitor.py', {'Metrics', 'fmt_temp', 'fmt_speed'}, ns)
                ns.update(threading=threading, tkfont=tkfont, APP_NAME='SysMonitor test',
                          ping_settings=pm.ping_settings, initial_ping_family=pm.initial_ping_family,
                          ping_column_width=pm.ping_column_width, ping_marker=pm.ping_marker,
                          fmt_ping_line=pm.fmt_ping_line, ping_has_problem=pm.ping_has_problem,
                          PING_LOSS_COLOR='red', net_column_width=net.net_column_width,
                          save_window_settings=Mock(), CONFIG_PATH='never-written')
                master = tk.Tk()
                master.geometry('1200x80+20+20')
                master.attributes('-topmost', True)
                master.update()
                parent = ns['_u32'].GetParent(master.winfo_id())
                ns['find_taskbar'] = lambda: (parent, None)
                ns['get_taskbar_rect'] = lambda: {'notify_left': 1200, 'top': 200}
                cfg = configparser.ConfigParser()
                cfg.read_dict(defaults)
                cfg['ping']['enabled'] = str(ping_enabled).lower()
                metrics = ns['Metrics']()
                window = ns['MonitorWindow'](master, cfg, metrics, mode)
                # This test drives updates explicitly; do not run periodic ticks.
                window.root.after_cancel(window._after_id)
                window._after_id = None
                tk_errors = []
                master.report_callback_exception = lambda *error: tk_errors.append(error)
                try:
                    window._update_labels()
                    master.update()
                    initial_width = window.embed_width if mode == 'taskbar' else window.root.winfo_width()
                    metrics.net_rates = ((100, 200), (300, 400))
                    window._net_mode_var.set(True)
                    window._select_net_split()
                    master.update()
                    self.assertTrue(window.net_split)
                    self.assertEqual(len(window._net_cells), 8)
                    for col in range(4):
                        a, b = window._net_cells[col], window._net_cells[col+4]
                        self.assertEqual(a.winfo_x(), b.winfo_x())
                        self.assertEqual(a.winfo_width(), b.winfo_width())
                    self.assertEqual(window._net_cells[0].cget('text'), '↑ v4 ')
                    self.assertEqual(window._net_cells[4].cget('text'), '↓ v4 ')
                    self.assertEqual(window._net_cells[1].cget('text'), ns['fmt_speed'](100))
                    if ping_enabled:
                        for family in ('ipv6', 'ipv4'):
                            metrics.ping_family = family
                            window._update_labels()
                            master.update()
                            self.assertEqual(window._ping_layout_family, family)
                            self.assertTrue(window._net_active)
                    if mode == 'taskbar':
                        self.assertGreater(window.embed_width, initial_width)
                        self.assertEqual(window._cols['ping'][0] - sum(window._cols['net']), 10)
                        emb = window.embedder
                        for width in (window.embed_width + 20, window.embed_width):
                            emb.width = width
                            emb.reposition()
                            master.update()
                            a, b = ns['_win_rect'](emb.hwnd), ns['_win_rect'](emb.catcher_hwnd)
                            self.assertEqual((a.left, a.top, a.right, a.bottom),
                                             (b.left, b.top, b.right, b.bottom))
                        self.assertEqual(ns['_u32'].GetWindow(emb.hwnd, 2), emb.catcher_hwnd)
                        self.assertTrue(emb.healthy())
                        self.assertTrue(emb.embed())
                        self.assertTrue(emb.healthy())
                        self.assertTrue(window.click_catcher.bind('<Button-3>'))
                    ns['save_window_settings'].side_effect = OSError('denied')
                    window._net_mode_var.set(False)
                    window._select_net_split()
                    self.assertTrue(window.net_split)
                    self.assertTrue(window._net_mode_var.get())
                    metrics.net_rates = None
                    window._update_labels()
                    master.update()
                    self.assertFalse(window._net_active)
                    self.assertEqual(window._net_cells, [])
                    self.assertIn('Kbps', window.lbl_up.cget('text'))
                    ns['save_window_settings'].side_effect = None
                    metrics.net_rates = ((100, 200), (300, 400))
                    window._update_labels()
                    self.assertTrue(window._net_active)
                    window._net_mode_var.set(False)
                    window._select_net_split()
                    master.update()
                    self.assertFalse(window.net_split)
                    self.assertFalse(window._net_active)
                    self.assertEqual(window._net_cells, [])
                    if mode == 'taskbar':
                        self.assertEqual(window.embed_width, initial_width)
                        window._request_rebuild = Mock()
                        window.click_catcher.destroy()
                        self.assertFalse(window.embedder.healthy())
                        window._maintain_position()
                        window._request_rebuild.assert_called_once_with('window handle gone')
                    self.assertEqual(tk_errors, [])
                finally:
                    handles = ([window.embedder.hwnd, window.embedder.catcher_hwnd]
                               if window.embedder else [])
                    window._destroy()
                    for hwnd in handles:
                        self.assertFalse(ns['_u32'].IsWindow(hwnd))
                    master.destroy()

    def test_collector_runs_packet_reads_in_worker_and_recovers_after_failure(self):
        import psutil
        ns = dict(threading=threading, time=time, psutil=psutil,
                  SensorReader=Mock(), PacketCounters=net.PacketCounters,
                  split_rates=net.split_rates, _log_event=Mock())
        load_definitions('sys_monitor.py', {'Metrics', 'Collector'}, ns)
        metrics = ns['Metrics']()
        collector = ns['Collector'](metrics, 0.001)
        reads = []
        samples = iter([((10, 20), (30, 40)), ((11, 23), (33, 41)), None,
                        ((100, 100), (100, 100)), ((101, 101), (101, 101))])
        snapshots = []
        def read():
            reads.append(threading.get_ident())
            return next(samples)
        collector._packets.read = read
        collector._sensors.read.return_value = {}
        def collect():
            for _ in range(5):
                collector._collect_once()
                snapshots.append(metrics.snapshot()['net_rates'])
        worker = threading.Thread(target=collect)
        worker.start()
        worker.join()
        self.assertEqual(len(reads), 5)
        self.assertTrue(all(ident != threading.get_ident() for ident in reads))
        self.assertIsNone(snapshots[0])
        self.assertIsNotNone(snapshots[1])
        self.assertIsNone(snapshots[2])
        self.assertIsNone(snapshots[3])
        self.assertIsNotNone(snapshots[4])
