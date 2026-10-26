"""Space regression: exercise the real embedder with screen rectangles."""
import ctypes
from ctypes import wintypes
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import threading
import time

from taskbar_space import SpaceSnapshot, TaskbarSpaceMonitor, build_regions, choose_layout

from test_taskbar_clicks import namespace


class TaskbarSpaceRegression(unittest.TestCase):
    def test_real_1920_widget_does_not_cover_icons(self):
        ns = namespace()
        ns['_u32'] = Mock()
        rectangles = {
            1: SimpleNamespace(left=0, top=1032, right=1920, bottom=1080),
            2: SimpleNamespace(left=1574, top=1032, right=1920, bottom=1080),
        }
        ns['_win_rect'] = rectangles.get
        ns['_u32'].FindWindowExW.return_value = 2
        embedder = ns['TaskbarEmbedder'](3, 487, catcher_hwnd=4)
        embedder.tray = 1
        embedder.widths = (487, 388, 318)
        embedder.space_monitor = SimpleNamespace(set_target=Mock(), snapshot=lambda: SimpleNamespace(
            hwnd=1, bounds=(0, 1032, 1920, 1080), left=(10, 658), right=(1263, 1574)))
        embedder.reposition()
        calls = ns['_u32'].SetWindowPos.call_args_list
        placement = next(c.args for c in calls if c.args[0] == 3 and c.args[4] > 0)
        x, width = placement[2], placement[4]
        self.assertFalse(x < 1253 and x + width > 668,
                         f'widget [{x}, {x + width}] covers icons [668, 1253]')
        catcher = next(c.args for c in calls if c.args[0] == 4)
        self.assertEqual((catcher[2], catcher[4]), (x, width))


class LayoutPolicyTests(unittest.TestCase):
    def test_full_left_beats_compact_right_secondary_bar(self):
        snap = SpaceSnapshot(2, (-1920, 1032, 0, 1080),
                             (-1910, -1262), (-657, -302))
        result = choose_layout(snap, (487, 388, 318), -302)
        self.assertEqual((result.side, result.level, result.x, result.overflow),
                         ('left', 0, -1910, False))
        self.assertEqual(result.width, 487)

    def test_priority_and_alignment(self):
        widths = (487, 388, 318)
        cases = [
            ((1583, 2214), (10, 978), 'right', 0, 1727, False),
            ((1100, 1500), (10, 900), 'left', 0, 10, False),
            ((1100, 1500), (10, 410), 'right', 1, 1112, False),
            ((1263, 1574), (10, 658), 'left', 0, 10, False),
            ((1200, 1520), (10, 900), 'left', 0, 10, False),
            ((1200, 1520), (10, 330), 'right', 2, 1202, False),
            ((1300, 1500), (50, 450), 'left', 1, 50, False),
            ((1300, 1500), (50, 370), 'left', 2, 50, False),
            ((1300, 1500), (50, 250), 'right', 2, 1182, True),
        ]
        for right, left, side, level, x, overflow in cases:
            with self.subTest(right=right, left=left):
                snap = SpaceSnapshot(1, (0, 0, 2560, 48), left, right)
                result = choose_layout(snap, widths, right[1])
                self.assertEqual((result.side, result.level, result.x, result.overflow),
                                 (side, level, x, overflow))
                self.assertEqual(result.width, widths[level])

    def test_missing_snapshot_preserves_full_layout(self):
        result = choose_layout(None, (487, 388, 318), 1574)
        self.assertEqual((result.side, result.level, result.x), ('right', 0, 1087))

    def test_exact_fit_and_duplicate_levels_without_split(self):
        snap = SpaceSnapshot(2, (-1920, 0, 0, 48), (-1910, -1000), (-400, 0))
        result = choose_layout(snap, (400, 400, 318), 0)
        self.assertEqual((result.side, result.level, result.x), ('right', 0, -400))

    def test_region_builder_ignores_self_and_invalid_rectangles(self):
        elements = [
            ('StartButton', 'ToggleButton', (668, 0, 710, 48), 10),
            ('', 'Taskbar.TaskListButtonAutomationPeer', (1200, 0, 1253, 48), 10),
            ('', 'SystemTray.NotifyIconView', (1574, 0, 1920, 48), 10),
            ('Island_1', 'TextBlock', (15, 0, 161, 48), 10),
            ('', 'TkTopLevel', (0, 0, 650, 48), 99),
            ('', 'TextBlock', (0, 0, 660, 48), 99),
            ('', 'Taskbar.TaskListButtonAutomationPeer', (0, 0, float('inf'), 48), 10),
            ('', 'Image', (0, 0, 500, 0), 10),
            ('', 'Image', (0, 0, float('nan'), 48), 10),
            ('', 'Image', (0, 80, 600, 100), 10),
            ('', 'Container', (0, 0, 1920, 48), 10),
        ]
        snap = build_regions(42, (0, 0, 1920, 48), elements, own_pid=99)
        self.assertEqual(snap, SpaceSnapshot(42, (0, 0, 1920, 48), (171, 658), (1263, 1574)))
        self.assertIsNone(build_regions(42, (0, 0, 1920, 48), elements[1:]))
        self.assertIsNone(build_regions(42, (0, 0, float('inf'), 48), elements))
        self.assertIsNone(build_regions(42, (0, 0, 1920, 48), elements[:2]))

    def test_no_left_elements_and_start_only(self):
        elements = [('StartButton', '', (668, 0, 710, 48), 10),
                    ('', 'SystemTray.X', (1574, 0, 1920, 48), 10)]
        snap = build_regions(7, (0, 0, 1920, 48), elements)
        self.assertEqual((snap.left, snap.right), ((10, 658), (720, 1574)))


class TaskbarSpaceIntegrationTests(unittest.TestCase):
    def test_real_tk_levels_restore_preferences_and_move_both_windows(self):
        import ast
        import configparser
        from pathlib import Path
        import tkinter as tk
        import tkinter.font as tkfont
        import net_split as net
        import ping_monitor as pm
        from test_ping_views import load_definitions

        tree = ast.parse(Path('sys_monitor.py').read_text(encoding='utf-8'))
        defaults = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
                                        and any(isinstance(t, ast.Name) and t.id == 'DEFAULTS' for t in n.targets)))
        ns = namespace()
        load_definitions('sys_monitor.py', {'Metrics', 'fmt_temp', 'fmt_speed'}, ns)
        ns.update(threading=threading, tkfont=tkfont, APP_NAME='Space layout test',
                  ping_settings=pm.ping_settings, initial_ping_family=pm.initial_ping_family,
                  ping_column_width=pm.ping_column_width, ping_marker=pm.ping_marker,
                  fmt_ping_line=pm.fmt_ping_line, ping_has_problem=pm.ping_has_problem,
                  PING_LOSS_COLOR='red', net_column_width=net.net_column_width)
        master = tk.Tk()
        master.overrideredirect(True)  # Like the taskbar: no non-client border offset.
        master.geometry('1800x80+20+20')
        master.update()
        u32 = ns['_u32']
        parent = u32.GetParent(master.winfo_id())
        ns['find_taskbar'] = lambda: (parent, None)
        cfg = configparser.ConfigParser()
        cfg.read_dict(defaults)
        cfg['window']['net_split'] = 'true'
        metrics = ns['Metrics']()
        metrics.net_rates = ((100, 200), (300, 400))
        monitor = Mock()
        monitor.snapshot.return_value = None
        window = ns['MonitorWindow'](master, cfg, metrics, 'taskbar', space_monitor=monitor)
        window.root.after_cancel(window._after_id)
        window._after_id = None
        try:
            window._update_labels()
            master.update()
            emb = window.embedder
            original = (emb.hwnd, emb.catcher_hwnd, window.root)
            w0, w1, w2 = window._taskbar_widths()
            self.assertGreater(w0, w1)
            self.assertGreater(w1, w2)
            tr = ns['_win_rect'](parent)
            bounds = (tr.left, tr.top, tr.right, tr.bottom)
            cases = [(w0, w0, 0, 'right'), (w1, w0, 0, 'left'),
                     (w2, w0, 0, 'left'), (w1, w1, 1, 'right'),
                     (w2, w2, 2, 'right'), (0, w0, 0, 'left'),
                     (0, w1, 1, 'left'), (0, w2, 2, 'left'),
                     (0, 0, 2, 'right'), (w0, w0, 0, 'right')]
            for right_space, left_space, level, side in cases:
                with self.subTest(level=level, side=side, right_space=right_space):
                    snap = SpaceSnapshot(parent, bounds,
                                         (tr.left+10, tr.left+10+left_space),
                                         (tr.right-right_space, tr.right))
                    monitor.snapshot.return_value = snap
                    window._maintain_position()
                    master.update()
                    self.assertEqual(window._space_level, level)
                    self.assertEqual(window._net_active, level == 0)
                    self.assertTrue(window.net_split)
                    self.assertEqual(cfg['window']['net_split'], 'true')
                    self.assertEqual(window.lbl_mem.winfo_manager(), '' if level == 2 else 'place')
                    self.assertEqual(window.embed_width, (w0, w1, w2)[level])
                    a, b = ns['_win_rect'](emb.hwnd), ns['_win_rect'](emb.catcher_hwnd)
                    self.assertEqual((a.left, a.top, a.right, a.bottom),
                                     (b.left, b.top, b.right, b.bottom))
                    self.assertEqual(a.left, tr.left+10 if side == 'left' else tr.right-emb.width)
                    self.assertEqual((emb.hwnd, emb.catcher_hwnd, window.root), original)
                    with patch.object(window, '_layout_embedded', wraps=window._layout_embedded) as relayout:
                        window._maintain_position()
                        relayout.assert_not_called()
            # Stale geometry or a different HWND cannot be used after a display change.
            for snap in (None, SpaceSnapshot(parent+1, bounds, (0, 0), (0, 0)),
                         SpaceSnapshot(parent, (0, 0, 1920, 48), (0, 0), (0, 0))):
                monitor.snapshot.return_value = snap
                window._maintain_position()
                self.assertEqual(window._space_level, 0)
            self.assertEqual(ns['_log_event'].call_count, 2)  # Initial embed + one overflow.
        finally:
            window._destroy()
            master.destroy()


class SpaceWorkerTests(unittest.TestCase):
    def test_transient_scan_failure_keeps_snapshot_until_six_seconds(self):
        logs = []
        worker = TaskbarSpaceMonitor(logs.append)
        worker.set_targets({42})
        snap = SpaceSnapshot(42, (0, 0, 1920, 48), (10, 658), (1263, 1574))
        worker._scan = Mock(return_value=snap)
        with patch('taskbar_space.time.monotonic', return_value=100) as clock:
            worker._scan_targets(None)
            self.assertIs(worker.snapshot(42), snap)
            worker._scan.side_effect = TimeoutError('transient scan')
            for now in (102, 104, 105.999):
                clock.return_value = now
                worker._scan_targets(None)
                self.assertIs(worker.snapshot(42), snap)
            clock.return_value = 106
            self.assertIsNone(worker.snapshot(42))
            self.assertEqual(len(logs), 1)
            self.assertIn('keeping last layout', logs[0])
            self.assertNotIn('using fallback', logs[0])
            worker._scan.side_effect = None
            clock.return_value = 107
            worker._scan_targets(None)
            self.assertIs(worker.snapshot(42), snap)

    def test_fatal_worker_failure_still_clears_all_snapshots(self):
        logs = []
        worker = TaskbarSpaceMonitor(logs.append)
        worker.set_targets({42, 43})
        worker._scan = lambda automation, hwnd: SpaceSnapshot(
            hwnd, (0, 0, 1920, 48), (10, 658), (1263, 1574))
        with patch('taskbar_space.time.monotonic', return_value=100):
            worker._scan_targets(None)
            self.assertIsNotNone(worker.snapshot(42))
            self.assertIsNotNone(worker.snapshot(43))
            worker._failure(RuntimeError('fatal worker error'))
            self.assertIsNone(worker.snapshot(42))
            self.assertIsNone(worker.snapshot(43))
        self.assertEqual(len(logs), 1)
        self.assertIn('using fallback', logs[0])

    def test_failure_logs_once_and_snapshot_expires_or_target_changes(self):
        logs = []
        worker = TaskbarSpaceMonitor(logs.append)
        worker.set_target(42)
        snap = SpaceSnapshot(42, (0, 0, 1920, 48), (10, 658), (1263, 1574))
        stamp = time.monotonic()
        with worker._lock:
            worker._values[42] = snap, stamp
        self.assertEqual(worker.snapshot(), snap)
        with patch('taskbar_space.time.monotonic', return_value=stamp + 7):
            self.assertIsNone(worker.snapshot())
        worker.set_target(43)
        self.assertIsNone(worker.snapshot())
        worker._failure(TimeoutError('scan'))
        worker._failure(RuntimeError('scan'))
        self.assertEqual(len(logs), 1)

    def test_missing_comtypes_degrades_without_crashing(self):
        import sys
        logs = []
        worker = TaskbarSpaceMonitor(logs.append)
        with patch.dict(sys.modules, {'comtypes': None}):
            worker.start()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertIsNone(worker.snapshot())
        self.assertEqual(len(logs), 1)

    def test_worker_recovers_and_publishes_only_from_its_thread(self):
        snap = SpaceSnapshot(42, (0, 0, 1920, 48), (10, 658), (1263, 1574))
        logs, calls = [], []
        worker = TaskbarSpaceMonitor(logs.append, interval=0.01)
        def scan(automation, hwnd):
            calls.append(threading.get_ident())
            if len(calls) == 1:
                raise TimeoutError('temporary')
            return snap
        worker._scan = scan
        worker.set_target(42)
        worker.start()
        try:
            deadline = time.monotonic() + 3
            while worker.snapshot() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(worker.snapshot(), snap)
            self.assertEqual(len(logs), 1)
            self.assertTrue(all(ident == worker.ident for ident in calls))
            self.assertNotEqual(worker.ident, threading.get_ident())
        finally:
            worker.stop()
            worker.join(3)
        self.assertFalse(worker.is_alive())

    def test_blocked_scan_never_blocks_snapshot_or_stop(self):
        entered, release = threading.Event(), threading.Event()
        logs = []
        worker = TaskbarSpaceMonitor(logs.append, interval=0.01)
        def scan(automation, hwnd):
            entered.set()
            release.wait(3)
            raise TimeoutError('provider timeout')
        worker._scan = scan
        worker.set_target(42)
        worker.start()
        try:
            self.assertTrue(entered.wait(3), logs)
            # Do not use join in production: these return while UIA is stalled.
            self.assertIsNone(worker.snapshot())
            worker.stop()
            self.assertTrue(worker.is_alive())
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(logs), 1)


if __name__ == '__main__':
    unittest.main()
