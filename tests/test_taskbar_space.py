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
    def test_side_provider_overrides_auto_without_real_taskbar(self):
        ns = namespace()
        ns['_u32'] = Mock()
        ns['_win_rect'] = {1: SimpleNamespace(left=0, top=1032, right=1920, bottom=1080)}.get
        snap = SpaceSnapshot(1, (0, 1032, 1920, 1080), (10, 658), (1000, 1600))
        embedder = ns['TaskbarEmbedder'](3, 487, catcher_hwnd=4)
        self.assertIsNone(embedder.side_provider)
        embedder.tray = 1
        embedder.widths = (487, 388, 318)
        embedder.space_monitor = SimpleNamespace(set_target=Mock(), snapshot=lambda: snap)
        for side, expected in [('auto', 1113), ('left', 10)]:
            embedder.side_provider = Mock(return_value=side)
            ns['_u32'].SetWindowPos.reset_mock()
            embedder.reposition()
            embedder.side_provider.assert_called_once_with()
            placements = [c.args for c in ns['_u32'].SetWindowPos.call_args_list if c.args[4] > 0]
            self.assertEqual([(p[0], p[2]) for p in placements], [(3, expected), (4, expected)])

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
    def test_odyssey_friend_video_2026_10_28_right_shrinks_before_left(self):
        snap = SpaceSnapshot(1, (0, 0, 1920, 48), (10, 658), (1300, 1700))
        result = choose_layout(snap, (487, 388, 318), 1700, side='right',
                               shrink=((7, 426), (6, 365)))
        self.assertEqual((result.side, result.level, result.font_size, result.x, result.width),
                         ('right', 0, 6, 1335, 365))

    def test_left_aligned_friend_video_2026_10_28_complete_first_fitting_font(self):
        els = [('StartButton', 'x', (0, 0, 48, 48), 1)] + [
            ('', 'Taskbar.TaskListButtonAutomationPeer',
             (48+i*44, 0, 92+i*44, 48), 1) for i in range(24)
        ] + [('', 'SystemTray.X', (1700, 0, 1920, 48), 1)]
        snap = build_regions(1, (0, 0, 1920, 48), els)
        self.assertEqual(snap.right, (1114, 1700))
        for side, x in [('left', 1114), ('right', 1157)]:
            with self.subTest(side=side):
                result = choose_layout(snap, (620, 500, 400), 1700, side=side,
                                       shrink=((7, 543), (6, 465)))
                self.assertEqual((result.side, result.level, result.font_size, result.x),
                                 ('right', 0, 7, x))

    def test_forced_full_normal_font_has_priority_over_shrink(self):
        snap = SpaceSnapshot(1, (0, 0, 1920, 48), (10, 658), (1000, 1700))
        for side, x in [('left', 10), ('right', 1213)]:
            result = choose_layout(snap, (487, 388, 318), 1700, side=side,
                                   shrink=((7, 426), (6, 365)))
            self.assertEqual((result.side, result.level, result.font_size, result.x),
                             (side, 0, None, x))

    def test_auto_invalid_and_missing_snapshot_ignore_shrink(self):
        snap = SpaceSnapshot(1, (0, 0, 1920, 48), (10, 658), (1300, 1700))
        for snapshot in (snap, None):
            for side in ('auto', 'invalid', None, 'left' if snapshot is None else 'auto',
                         'right' if snapshot is None else 'auto'):
                self.assertEqual(choose_layout(snapshot, (487, 388, 318), 1700, side=side,
                                               shrink=((7, 426), (6, 365))),
                                 choose_layout(snapshot, (487, 388, 318), 1700, side=side))

    def test_below_minimum_font_capacity_preserves_old_compact_and_overflow(self):
        for left, right in [((10, 350), (1400, 1700)), ((10, -10), (1400, 1700)),
                            ((10, -10), (1600, 1700))]:
            snap = SpaceSnapshot(1, (0, 0, 1920, 48), left, right)
            for side in ('left', 'right'):
                self.assertEqual(choose_layout(snap, (487, 388, 318), 1700, side=side,
                                               shrink=((7, 426), (6, 365))),
                                 choose_layout(snap, (487, 388, 318), 1700, side=side))

    def test_opposite_complete_normal_beats_requested_compact_when_minimum_fails(self):
        snap = SpaceSnapshot(1, (0, 0, 1920, 48), (10, 658), (1360, 1700))
        result = choose_layout(snap, (487, 388, 318), 1700, side='right',
                               shrink=((7, 426), (6, 365)))
        self.assertEqual((result.side, result.level, result.font_size, result.x),
                         ('left', 0, None, 171))

    def test_left_aligned_taskbar_friend_video_2026_10_27(self):
        """Barra alinhada à esquerda, vídeo do amigo 2026-10-27."""
        els = [('StartButton', 'x', (0, 0, 48, 48), 1)] + [
            ('', 'Taskbar.TaskListButtonAutomationPeer',
             (48+i*44, 0, 92+i*44, 48), 1) for i in range(24)
        ] + [('', 'SystemTray.X', (1700, 0, 1920, 48), 1)]
        snap = build_regions(1, (0, 0, 1920, 48), els)
        assert snap is not None
        self.assertEqual((snap.left, snap.right), ((10, -10), (1114, 1700)))
        for side, x in [('left', 1114), ('right', 1213), ('auto', 1213)]:
            with self.subTest(side=side):
                result = choose_layout(snap, (487, 388, 318), 1700, side=side)
                self.assertEqual((result.x, result.side, result.level, result.overflow),
                                 (x, 'right', 0, False))

    def test_right_uses_rightmost_space_in_left_region_when_right_unavailable(self):
        snap = SpaceSnapshot(1, (0, 0, 1920, 48), (10, 610), (1700, 1700))
        result = choose_layout(snap, (487, 388, 318), 1700, side='right')
        self.assertEqual((result.x, result.side, result.level, result.overflow),
                         (123, 'left', 0, False))

    def test_left_uses_begin_of_right_region_at_compact_level(self):
        snap = SpaceSnapshot(1, (0, 0, 1920, 48), (10, -10), (1300, 1700))
        result = choose_layout(snap, (487, 388, 318), 1700, side='left')
        self.assertEqual((result.x, result.side, result.level, result.overflow),
                         (1300, 'right', 1, False))

    def test_forced_sides_without_any_space_preserve_auto_overflow(self):
        snap = SpaceSnapshot(1, (0, 0, 1920, 48), (10, -10), (1500, 1700))
        automatic = choose_layout(snap, (487, 388, 318), 1700)
        self.assertTrue(automatic.overflow)
        for side in ('left', 'right'):
            with self.subTest(side=side):
                self.assertEqual(choose_layout(snap, (487, 388, 318), 1700, side=side),
                                 automatic)

    def test_forced_side_beats_other_full_side(self):
        snap = SpaceSnapshot(1, (0, 0, 2000, 48), (10, 610), (1000, 1600))
        for side, x in [('left', 10), ('right', 1113)]:
            with self.subTest(side=side):
                result = choose_layout(snap, (487, 388, 318), 1600, side=side)
                self.assertEqual((result.side, result.level, result.x), (side, 0, x))

    def test_opposite_full_before_forced_compact(self):
        # New policy prefers full content in the other region even without shrink candidates.
        for side in ('left', 'right'):
            for space in (400, 320):
                with self.subTest(side=side, space=space):
                    regions = dict(left=(10, 610), right=(1000, 1600))
                    regions[side] = (10, 10 + space)
                    snap = SpaceSnapshot(1, (0, 0, 2000, 48), **regions)
                    result = choose_layout(snap, (487, 388, 318), 1600, side=side)
                    other = 'right' if side == 'left' else 'left'
                    begin, end = regions[other]
                    self.assertEqual((result.side, result.level, result.x, result.font_size),
                                     (other, 0, begin if side == 'left' else end-487, None))

    def test_forced_unavailable_uses_other_region_then_auto_overflow(self):
        for side in ('left', 'right'):
            for other_space in (600, 0):
                with self.subTest(side=side, other_space=other_space):
                    regions = dict(left=(10, 10 + other_space), right=(1000, 1000 + other_space))
                    regions[side] = (10, 10)
                    snap = SpaceSnapshot(1, (0, 0, 2000, 48), **regions)
                    result = choose_layout(snap, (487, 388, 318), 1600, side=side)
                    if other_space:
                        other = 'right' if side == 'left' else 'left'
                        begin, end = regions[other]
                        self.assertEqual((result.side, result.level, result.x, result.overflow),
                                         (other, 0, begin if side == 'left' else end - 487, False))
                    else:
                        self.assertEqual(result, choose_layout(snap, (487, 388, 318), 1600))

    def test_explicit_auto_and_invalid_preserve_existing_policy(self):
        for left in (0, 320, 400, 600):
            for right in (0, 320, 400, 600):
                snap = SpaceSnapshot(1, (0, 0, 2000, 48), (10, 10 + left), (1000, 1000 + right))
                for side in ('auto', 'invalid', None):
                    with self.subTest(left=left, right=right, side=side):
                        self.assertEqual(choose_layout(snap, (487, 388, 318), 1600, side=side),
                                         choose_layout(snap, (487, 388, 318), 1600))
        for side in ('auto', 'left', 'right', 'invalid'):
            self.assertEqual(choose_layout(None, (487, 388, 318), 1600, side=side),
                             choose_layout(None, (487, 388, 318), 1600))

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
            logs = [call.args[0] for call in ns['_log_event'].call_args_list]
            self.assertEqual(sum(text.startswith('taskbar layout:') for text in logs), 9)
            self.assertEqual(sum('no layout fits' in text for text in logs), 1)
            self.assertEqual(sum(text.startswith('embedded into') for text in logs), 1)
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
