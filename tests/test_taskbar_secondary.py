"""Multi-taskbar lifecycle/menu regressions; no real Explorer writes."""
import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from taskbar_space import SpaceSnapshot, TaskbarSpaceMonitor


def session_type():
    return importlib.import_module('taskbar_session').TaskbarSession


def fake_window(**kwargs):
    window = Mock(embed_failed=False, _closing=False, **kwargs)
    window._ping_editor = None
    window._destroy.side_effect = lambda: setattr(window, '_closing', True)
    return window


class MultiSpaceTests(unittest.TestCase):
    def test_separate_snapshots_removal_failure_and_inflight_removal(self):
        monitor = TaskbarSpaceMonitor(Mock())
        monitor.set_targets({1, 2})
        snapshots = {hwnd: SpaceSnapshot(hwnd, (0, 0, 1920, 48), (10, 658), (1263, 1574))
                     for hwnd in (1, 2)}
        monitor._scan = lambda automation, hwnd: snapshots[hwnd]
        monitor._scan_targets(None)
        self.assertEqual(monitor.snapshot(1), snapshots[1])
        self.assertEqual(monitor.snapshot(2), snapshots[2])
        monitor.set_targets({2})
        self.assertIsNone(monitor.snapshot(1))
        self.assertEqual(monitor.snapshot(2), snapshots[2])
        monitor.set_targets({1, 2})
        def fail_one(automation, hwnd):
            if hwnd == 1:
                raise TimeoutError('one bar only')
            return snapshots[hwnd]
        monitor._scan = fail_one
        monitor._scan_targets(None)
        self.assertIsNone(monitor.snapshot(1))
        self.assertEqual(monitor.snapshot(2), snapshots[2])
        def remove_during_scan(automation, hwnd):
            monitor.set_targets({2})
            return snapshots[hwnd]
        monitor._scan = remove_during_scan
        monitor._scan_targets(None)
        self.assertIsNone(monitor.snapshot(1))


class SecondarySessionTests(unittest.TestCase):
    def setUp(self):
        self.master = Mock()
        self.cfg = {'window': {'net_split': 'false'}}
        self.metrics, self.ping = Mock(), Mock(mode='auto')
        self.primary = fake_window()
        self.factory = Mock(side_effect=lambda *args, **kwargs: fake_window())
        self.handles = [2]
        self.monitor = Mock()
        self.snapshots = {2: SpaceSnapshot(2, (0, 0, 1920, 48), (10, 658), (1263, 1574))}
        self.monitor.snapshot.side_effect = self.snapshots.get
        self.session = session_type()(self.master, self.cfg, self.metrics, self.ping, self.monitor,
                                      self.factory, lambda: list(self.handles), lambda: 1, Mock())
        self.session.attach_primary(self.primary)

    def test_create_remove_recreate_no_duplicate_on_primary_rebuild(self):
        self.session.poll()
        self.assertEqual(set(self.session.secondary), {2})
        first = self.session.secondary[2]
        self.factory.assert_called_once()
        args, kwargs = self.factory.call_args
        self.assertIs(args[2], self.metrics)
        self.assertIs(kwargs['ping_monitor'], self.ping)
        self.assertEqual(kwargs['taskbar_hwnd'], 2)
        self.session.attach_primary(fake_window())
        self.session.poll()
        self.assertEqual(self.factory.call_count, 1)
        self.handles[:] = []
        self.session.poll()
        first._destroy.assert_called_once()
        self.assertEqual(self.session.secondary, {})
        self.handles[:] = [3]
        self.snapshots[3] = SpaceSnapshot(3, (0, 0, 1920, 48), (10, 658), (1263, 1574))
        self.session.poll()
        self.assertEqual(set(self.session.secondary), {3})
        self.monitor.set_targets.assert_called_with({1, 3})

    def test_manager_keeps_working_while_primary_is_being_rebuilt(self):
        self.primary._closing = True
        self.session.poll()
        self.assertEqual(set(self.session.secondary), {2})
        self.handles[:] = [3]
        self.snapshots[3] = SpaceSnapshot(3, (0, 0, 1920, 48), (10, 658), (1263, 1574))
        self.session.poll()
        self.assertEqual(set(self.session.secondary), {3})
        self.primary._destroy.assert_not_called()

    def test_no_snapshot_no_widget_and_stale_snapshot_removes_existing(self):
        self.snapshots.clear()
        self.session.poll()
        self.factory.assert_not_called()
        self.snapshots[2] = SpaceSnapshot(2, (0, 0, 1920, 48), (10, 658), (1263, 1574))
        self.session.poll()
        window = self.session.secondary[2]
        self.snapshots.clear()
        self.session.poll()
        window._destroy.assert_called_once()
        self.assertEqual(self.session.secondary, {})

    def test_secondary_failure_is_local_and_retried(self):
        bad = fake_window(embed_error=True)
        bad.embed_failed = True
        self.factory.side_effect = [bad, RuntimeError('create failed'), fake_window()]
        for expected in (set(), set(), {2}):
            self.session.poll()
            self.assertEqual(set(self.session.secondary), expected)
        self.primary._destroy.assert_not_called()
        self.assertFalse(self.session.exit_requested)
        self.primary.exit_requested = False
        self.session.secondary[2]._closing = True
        self.session.poll()
        self.assertFalse(self.primary.exit_requested)

    def test_split_and_ping_menu_state_synchronized(self):
        self.session.poll()
        self.cfg['window']['net_split'] = 'true'
        self.ping.mode = 'ipv6'
        self.session.sync_settings()
        for window in (self.primary, self.session.secondary[2]):
            self.assertTrue(window.net_split)
            window._net_mode_var.set.assert_called_with(True)
            window._ping_mode_var.set.assert_called_with('ipv6')
            window._update_labels.assert_called()

    def test_one_editor_across_widgets(self):
        self.session.poll()
        other = self.session.secondary[2]
        self.assertTrue(self.session.claim_editor(self.primary))
        editor = self.primary._ping_editor = Mock()
        editor.winfo_exists.return_value = True
        self.assertFalse(self.session.claim_editor(other))
        editor.lift.assert_called_once()
        editor.focus_force.assert_called_once()
        self.session.release_editor(self.primary)
        self.assertTrue(self.session.claim_editor(other))

    def test_close_from_secondary_closes_all_and_cancels_timer(self):
        self.session.start()
        self.session.poll()
        other = self.session.secondary[2]
        self.session.quit()
        self.assertTrue(self.session.exit_requested)
        self.assertTrue(self.primary.exit_requested)
        self.primary._destroy.assert_called_once()
        other._destroy.assert_called_once()
        self.master.after_cancel.assert_called()
        self.master.quit.assert_called()
        self.session.poll()
        self.assertEqual(self.factory.call_count, 1)

    def test_group_rebuild_clears_secondaries_but_plain_rebuild_does_not(self):
        self.session.poll()
        other = self.session.secondary[2]
        self.session.reconfigure()
        self.assertTrue(self.primary.reconfigure_requested)
        self.primary._destroy.assert_called_once()
        other._destroy.assert_called_once()
        self.assertEqual(self.session.secondary, {})
        self.session.attach_primary(fake_window())
        self.session.poll()
        self.assertEqual(self.factory.call_count, 2)


class SecondaryWidgetIntegrationTests(unittest.TestCase):
    def test_real_widgets_share_actions_editor_data_and_global_close(self):
        import ast
        import configparser
        from pathlib import Path
        import threading
        import tkinter as tk
        import tkinter.font as tkfont
        import net_split as net
        import ping_monitor as pm
        from test_ping_views import load_definitions
        from test_taskbar_clicks import namespace

        tree = ast.parse(Path('sys_monitor.py').read_text(encoding='utf-8'))
        defaults = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
                                        and any(isinstance(t, ast.Name) and t.id == 'DEFAULTS' for t in n.targets)))
        ns = namespace()
        load_definitions('sys_monitor.py', {'Metrics', 'fmt_temp', 'fmt_speed'}, ns)
        ns.update(threading=threading, tkfont=tkfont, APP_NAME='Secondary test',
                  ping_settings=pm.ping_settings, initial_ping_family=pm.initial_ping_family,
                  ping_column_width=pm.ping_column_width, ping_marker=pm.ping_marker,
                  fmt_ping_line=pm.fmt_ping_line, ping_has_problem=pm.ping_has_problem,
                  parse_ping_groups=pm.parse_ping_groups,
                  PING_LOSS_COLOR='red', net_column_width=net.net_column_width,
                  save_window_settings=Mock(), save_ping_settings=Mock(), CONFIG_PATH='never-written')
        master = tk.Tk()
        master.overrideredirect(True)
        master.geometry('1100x60+20+20')
        extra = tk.Toplevel(master)
        extra.overrideredirect(True)
        extra.geometry('1100x60+20+120')
        master.update()
        u32 = ns['_u32']
        main_hwnd, extra_hwnd = u32.GetParent(master.winfo_id()), u32.GetParent(extra.winfo_id())
        ns['find_taskbar'] = lambda: (main_hwnd, None)
        cfg = configparser.ConfigParser()
        cfg.read_dict(defaults)
        cfg['window']['net_split'] = 'true'
        metrics = ns['Metrics']()
        metrics.net_rates = ((100, 200), (300, 400))
        ping = Mock(mode='auto', preferred='ipv4', groups={'ipv4': ('8.8.8.8',), 'ipv6': ('::1',)})
        ping.set_mode.side_effect = lambda mode: setattr(ping, 'mode', mode)
        monitor = Mock()
        snapshots = {}
        for hwnd in (main_hwnd, extra_hwnd):
            r = ns['_win_rect'](hwnd)
            snapshots[hwnd] = SpaceSnapshot(hwnd, (r.left, r.top, r.right, r.bottom),
                                            (r.left+10, r.left+200), (r.right-700, r.right-100))
        monitor.snapshot.side_effect = snapshots.get
        factory = Mock(side_effect=ns['MonitorWindow'])
        session = session_type()(master, cfg, metrics, ping, monitor, factory,
                                 lambda: [extra_hwnd], lambda: main_hwnd, Mock())
        primary = ns['MonitorWindow'](master, cfg, metrics, 'taskbar', ping_monitor=ping,
                                      space_monitor=monitor, session=session)
        session.attach_primary(primary)
        try:
            session.poll()
            secondary = session.secondary[extra_hwnd]
            for window in (primary, secondary):
                window.root.after_cancel(window._after_id)
                window._after_id = None
                window._update_labels()
                window._maintain_position()
            self.assertIs(primary.metrics, secondary.metrics)
            self.assertIs(primary.ping_monitor, secondary.ping_monitor)
            self.assertEqual(primary.lbl_cpu.cget('text'), secondary.lbl_cpu.cget('text'))
            self.assertEqual(primary.lbl_up.cget('text'), secondary.lbl_up.cget('text'))
            secondary._net_mode_var.set(False)
            secondary._select_net_split()
            for window in (primary, secondary):
                self.assertFalse(window.net_split)
                self.assertFalse(window._net_mode_var.get())
                self.assertFalse(window._net_active)
            primary._net_mode_var.set(True)
            primary._select_net_split()
            secondary._select_ping_mode('ipv6')
            for window in (primary, secondary):
                self.assertTrue(window.net_split)
                self.assertEqual(window._ping_mode_var.get(), 'ipv6')
            # Levels are per bar, preferences remain global.
            old = snapshots[extra_hwnd]
            w2 = secondary._taskbar_widths()[2]
            snapshots[extra_hwnd] = SpaceSnapshot(extra_hwnd, old.bounds, (0, 0),
                                                  (old.right[1]-w2, old.right[1]))
            secondary._maintain_position()
            self.assertEqual(secondary._space_level, 2)
            self.assertEqual(primary._space_level, 0)
            self.assertFalse(secondary._net_active)
            self.assertTrue(primary._net_active)
            secondary._edit_ping_targets()
            editor = secondary._ping_editor
            self.assertIsNotNone(editor)
            primary._edit_ping_targets()
            self.assertIsNone(primary._ping_editor)
            self.assertIs(secondary._ping_editor, editor)
            # Plain primary rebuild must not recreate secondary widgets/editor.
            primary._destroy()
            primary = ns['MonitorWindow'](master, cfg, metrics, 'taskbar', ping_monitor=ping,
                                          space_monitor=monitor, session=session)
            session.attach_primary(primary)
            primary.root.after_cancel(primary._after_id)
            primary._after_id = None
            session.poll()
            self.assertIs(session.secondary[extra_hwnd], secondary)
            self.assertEqual(factory.call_count, 1)
            self.assertTrue(editor.winfo_exists())
            # A secondary update exception must not leave the primary mainloop.
            with patch.object(master, 'quit') as leave_mainloop:
                with patch.object(secondary, '_update_labels', side_effect=RuntimeError('secondary only')):
                    secondary._tick()
                leave_mainloop.assert_not_called()
            self.assertFalse(primary._closing)
            self.assertFalse(primary.reconfigure_requested)
            self.assertFalse(primary.exit_requested)
            session.poll()  # Remove the failed HWND instance.
            session.poll()  # Retry on the same taskbar, independently of primary.
            secondary = session.secondary[extra_hwnd]
            self.assertFalse(secondary._closing)
            # Saving groups from the secondary rebuilds both via the controller.
            secondary._save_ping_targets(['8.8.8.8', '', '::1', ''], 'ipv4', Mock())
            self.assertTrue(primary.reconfigure_requested)
            self.assertTrue(primary._closing)
            self.assertTrue(secondary._closing)
            self.assertEqual(session.secondary, {})
            primary = ns['MonitorWindow'](master, cfg, metrics, 'taskbar', ping_monitor=ping,
                                          space_monitor=monitor, session=session)
            session.attach_primary(primary)
            session.poll()
            secondary = session.secondary[extra_hwnd]
            secondary.quit()
            self.assertTrue(session.exit_requested)
            self.assertTrue(primary.exit_requested)
            self.assertTrue(primary._closing)
            self.assertTrue(secondary._closing)
        finally:
            session.close()
            if not primary._closing:
                primary._destroy()
            # Mock call histories contain session/root arguments and otherwise
            # keep a Tk cycle for GC on a later UIA worker (native Tcl abort).
            factory.reset_mock()
            session.window_factory = None
            extra.destroy()
            master.destroy()
            import gc
            gc.collect()


class SecondaryWin32Tests(unittest.TestCase):
    def test_explicit_parent_without_notify_uses_uia_and_hides_without_snapshot(self):
        import tkinter as tk
        from test_taskbar_clicks import namespace
        ns = namespace()
        root = tk.Tk()
        root.overrideredirect(True)
        root.geometry('900x60+80+80')
        root.attributes('-topmost', True)
        root.update()
        u32 = ns['_u32']
        parent = u32.GetParent(root.winfo_id())
        text, catcher = tk.Toplevel(root), tk.Toplevel(root)
        for window in (text, catcher):
            window.overrideredirect(True)
            window.geometry('250x60+-32000+-32000')
            window.update()
        rect = ns['_win_rect'](parent)
        bounds = (rect.left, rect.top, rect.right, rect.bottom)
        snapshot = SpaceSnapshot(parent, bounds, (rect.left+10, rect.left+400),
                                 (rect.right-400, rect.right-100))
        monitor = Mock()
        monitor.snapshot.return_value = snapshot
        ns['find_taskbar'] = Mock(side_effect=AssertionError('must not use primary bar'))
        try:
            emb = ns['TaskbarEmbedder'](u32.GetParent(text.winfo_id()), 250,
                                       catcher_hwnd=u32.GetParent(catcher.winfo_id()),
                                       target_tray=parent, managed_targets=True)
            emb.space_monitor = monitor
            emb.widths = (250, 220, 200)
            self.assertTrue(emb.embed())
            root.update()
            self.assertTrue(emb.healthy())
            self.assertEqual(u32.GetParent(emb.hwnd), parent)
            a, b = ns['_win_rect'](emb.hwnd), ns['_win_rect'](emb.catcher_hwnd)
            self.assertEqual(a.left, rect.right-350)
            self.assertEqual(a.right, rect.right-100)
            self.assertEqual((a.left, a.top, a.right, a.bottom), (b.left, b.top, b.right, b.bottom))
            monitor.snapshot.assert_called_with(parent)
            monitor.snapshot.return_value = None
            emb.reposition()
            self.assertFalse(u32.IsWindowVisible(emb.hwnd))
            self.assertFalse(u32.IsWindowVisible(emb.catcher_hwnd))
            monitor.snapshot.return_value = snapshot
            emb.reposition()
            self.assertTrue(u32.IsWindowVisible(emb.hwnd))
            self.assertTrue(u32.IsWindowVisible(emb.catcher_hwnd))
        finally:
            text.destroy()
            catcher.destroy()
            root.destroy()


if __name__ == '__main__':
    unittest.main()
