"""Falha ao entrar na barra: motivo no log, 5 tentativas, docked com volta à barra."""
import configparser
import ctypes
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from metrics_collector import Metrics
from test_ping_views import PingViewTests, load_definitions


def make_cfg(display_mode='taskbar'):
    cfg = configparser.ConfigParser()
    cfg.read_dict({'window': {'display_mode': display_mode, 'update_interval_ms': '1000',
                              'accent_up': '#111', 'accent_down': '#222'}, 'ping': {}})
    return cfg


def window_mock(**kwargs):
    base = dict(embed_failed=False, exit_requested=False, reconfigure_requested=False,
                retry_taskbar_requested=False, embed_failure=None)
    base.update(kwargs)
    return Mock(**base)


class Harness:
    def __init__(self, windows, display_mode='taskbar'):
        self.factory = Mock(side_effect=windows)
        self.clock = Mock()
        self.clock.monotonic.return_value = 0
        self.logs = Mock()
        self.sessions = []

        def new_session(*args, **kwargs):
            session = Mock(exit_requested=False)
            self.sessions.append(session)
            return session

        self.session_cls = Mock(side_effect=new_session)
        recorder, history_ui, top = Mock(), Mock(), Mock()
        self.ns = load_definitions('sys_monitor.py', {'main'}, {
            'ensure_single_instance': Mock(), 'load_config': lambda: make_cfg(display_mode),
            '_enable_dpi_awareness': Mock(), 'Metrics': Metrics, 'Collector': Mock(),
            'PingMonitor': Mock(), 'tk': Mock(), 'MonitorWindow': self.factory,
            'TaskbarSpaceMonitor': Mock(), 'TaskbarSession': self.session_cls,
            'enumerate_secondary_taskbars': Mock(return_value=[]),
            'find_taskbar': Mock(return_value=(1, 2)),
            'wait_for_taskbar': Mock(return_value=True), 'time': self.clock,
            '_log_event': self.logs, 'TrafficHistory': Mock(),
            'TrafficRecorder': Mock(return_value=recorder),
            'TrafficHistoryWindow': Mock(return_value=history_ui),
            'LatencyHistoryWindow': Mock(return_value=Mock()), 'fmt_speed': Mock(),
            'TopProcessesMonitor': Mock(return_value=top),
            'DiskMonitor': Mock(), 'DiskWindow': Mock(), 'data_dir': lambda: Path('.')})

    def run(self):
        self.ns['main']()

    @property
    def modes(self):
        return [call.args[3] for call in self.factory.call_args_list]

    @property
    def retry_flags(self):
        return [bool(call.kwargs.get('taskbar_retry')) for call in self.factory.call_args_list]

    @property
    def messages(self):
        return [call.args[0] for call in self.logs.call_args_list]


class MainRetryTests(unittest.TestCase):
    def test_one_embed_failure_then_success_stays_in_taskbar(self):
        windows = [window_mock(embed_failed=True, embed_failure='wrapper hwnd 0'),
                   window_mock(exit_requested=True)]
        h = Harness(windows)
        h.run()
        self.assertEqual(h.modes, ['taskbar', 'taskbar'])
        self.assertIn('embedding failed (wrapper hwnd 0); attempt 1/5', h.messages)
        windows[0]._destroy.assert_called_once()
        h.sessions[0].wait.assert_called_once_with(2000)

    def test_five_failures_fall_back_to_docked_with_retry(self):
        windows = [window_mock(embed_failed=True, embed_failure=f'motivo {i}') for i in range(5)]
        windows.append(window_mock(exit_requested=True))
        h = Harness(windows)
        h.run()
        self.assertEqual(h.modes, ['taskbar'] * 5 + ['docked'])
        self.assertEqual(h.retry_flags, [False] * 5 + [True])
        self.assertEqual(h.sessions[0].wait.call_args_list, [((2000,),)] * 4)
        self.assertIn('embedding failed (motivo 3); attempt 4/5', h.messages)
        self.assertIn('embedding failed 5x (motivo 4); docked mode, retrying taskbar every 60s',
                      h.messages)

    def test_docked_fallback_returns_to_taskbar_without_counting_loss(self):
        windows = [window_mock(embed_failed=True, embed_failure='x') for _ in range(5)]
        windows.append(window_mock(retry_taskbar_requested=True))   # docked fallback
        windows.append(window_mock(exit_requested=True))            # back in taskbar
        h = Harness(windows)
        h.run()
        self.assertEqual(h.modes, ['taskbar'] * 5 + ['docked', 'taskbar'])
        self.assertEqual(h.retry_flags[-2:], [True, False])
        self.assertEqual(len(h.sessions), 2)            # session recreated after docked closed it
        h.sessions[0].close.assert_called()
        h.sessions[1].start.assert_called_once()
        self.assertFalse(any('window lost' in m for m in h.messages))

    def test_return_trip_failure_goes_straight_back_to_docked(self):
        windows = [window_mock(embed_failed=True, embed_failure='x') for _ in range(5)]
        windows.append(window_mock(retry_taskbar_requested=True))   # docked
        windows.append(window_mock(embed_failed=True, embed_failure='y'))  # the single return try
        windows.append(window_mock(exit_requested=True))            # docked again
        h = Harness(windows)
        h.run()
        self.assertEqual(h.modes, ['taskbar'] * 5 + ['docked', 'taskbar', 'docked'])
        self.assertEqual(h.retry_flags[-1], True)
        self.assertEqual(sum('embedding failed 5x' in m for m in h.messages), 1)
        self.assertTrue(any('(y)' in m and 'return' in m for m in h.messages))

    def test_repeated_identical_return_failures_log_once(self):
        # Taskbar stuck broken: the 60 s return trip must not write two log lines
        # per minute (sysmon.log is discarded whole when it grows too big).
        windows = [window_mock(embed_failed=True, embed_failure='x') for _ in range(5)]
        for _ in range(3):
            windows.append(window_mock(retry_taskbar_requested=True))          # docked
            windows.append(window_mock(embed_failed=True, embed_failure='y'))  # return try
        windows.append(window_mock(exit_requested=True))
        h = Harness(windows)
        h.run()
        self.assertEqual(sum('taskbar is back' in m for m in h.messages), 1)
        self.assertEqual(sum('return' in m and '(y)' in m for m in h.messages), 1)

    def test_new_return_failure_reason_is_logged_again(self):
        windows = [window_mock(embed_failed=True, embed_failure='x') for _ in range(5)]
        for reason in ('y', 'y', 'z'):
            windows.append(window_mock(retry_taskbar_requested=True))
            windows.append(window_mock(embed_failed=True, embed_failure=reason))
        windows.append(window_mock(exit_requested=True))
        h = Harness(windows)
        h.run()
        self.assertEqual(sum('return' in m and '(y)' in m for m in h.messages), 1)
        self.assertEqual(sum('return' in m and '(z)' in m for m in h.messages), 1)

    def test_success_resets_failure_counter(self):
        windows = [window_mock(embed_failed=True, embed_failure='x') for _ in range(4)]
        windows.append(window_mock(reconfigure_requested=True))     # success resets
        windows += [window_mock(embed_failed=True, embed_failure='x') for _ in range(4)]
        windows.append(window_mock(exit_requested=True))
        h = Harness(windows)
        h.run()
        self.assertEqual(h.modes, ['taskbar'] * 10)

    def test_config_docked_never_gets_taskbar_retry(self):
        windows = [window_mock(reconfigure_requested=True), window_mock(exit_requested=True)]
        h = Harness(windows, display_mode='docked')
        h.run()
        self.assertEqual(h.modes, ['docked', 'docked'])
        self.assertEqual(h.retry_flags, [False, False])

    def test_taskbar_not_found_fallback_gets_retry(self):
        windows = [window_mock(exit_requested=True)]
        h = Harness(windows)
        h.ns['wait_for_taskbar'].return_value = False
        h.run()
        self.assertEqual(h.modes, ['docked'])
        self.assertEqual(h.retry_flags, [True])

    def test_window_lost_5x_fallback_gets_retry(self):
        windows = [window_mock() for _ in range(5)] + [window_mock(exit_requested=True)]
        h = Harness(windows)
        h.run()
        self.assertEqual(h.modes, ['taskbar'] * 5 + ['docked'])
        self.assertEqual(h.retry_flags[-1], True)


class MonitorWindowRetryTests(unittest.TestCase):
    def window(self):
        ns = PingViewTests().widget_namespace()
        ns['find_taskbar'] = Mock()
        cls = ns['MonitorWindow']
        window = cls.__new__(cls)
        window.root = Mock()
        window._closing = False
        window.retry_taskbar_requested = False
        window._retry_after_id = None
        window._destroy = Mock()
        return ns, window

    def test_taskbar_present_requests_return_and_destroys(self):
        ns, window = self.window()
        ns['find_taskbar'].return_value = (1, 2)
        window._retry_taskbar()
        self.assertTrue(window.retry_taskbar_requested)
        window._destroy.assert_called_once()
        window.root.after.assert_not_called()

    def test_taskbar_absent_reschedules(self):
        for found in [(None, None), (1, None)]:
            ns, window = self.window()
            ns['find_taskbar'].return_value = found
            window._retry_taskbar()
            self.assertFalse(window.retry_taskbar_requested)
            window._destroy.assert_not_called()
            window.root.after.assert_called_once_with(60000, window._retry_taskbar)

    def test_destroy_cancels_retry_timer(self):
        ns = PingViewTests().widget_namespace()
        ns['tk'] = Mock(TclError=Exception)
        cls = ns['MonitorWindow']
        window = cls.__new__(cls)
        window._closing = False
        window._close_hover = Mock()
        window._close_ping_editor = Mock()
        window._after_id = None
        window._retry_after_id = 'retry-id'
        window.click_catcher = None
        window.root = Mock()
        try:
            window._destroy()
        except AttributeError:
            pass  # tail of _destroy touches unrelated state; the cancel happens first
        window.root.after_cancel.assert_called_with('retry-id')


class EmbedFailureReasonTests(unittest.TestCase):
    def embed_window(self, parents, embedder_ok=True, failure=None):
        ns = PingViewTests().widget_namespace()
        u32 = Mock()
        u32.GetParent.side_effect = parents
        embedder = Mock()
        embedder.embed.return_value = embedder_ok
        embedder.failure = failure
        ns.update({'_u32': u32, '_win_rect': Mock(return_value=SimpleNamespace(top=0, bottom=40)),
                   'find_taskbar': Mock(return_value=(1, 2)), 'ctypes': ctypes,
                   'EMBED_KEY_COLOR': '#010101', 'TaskbarEmbedder': Mock(return_value=embedder)})
        ns['tk'] = Mock()
        cls = ns['MonitorWindow']
        window = cls.__new__(cls)
        window.taskbar_hwnd = 77
        window.embed_failed = False
        window.embed_failure = None
        window.embed_width = 100
        window.master, window.root = Mock(), Mock()
        window._layout_embedded = Mock()
        return window

    def test_tk_wrapper_zero_records_reason(self):
        window = self.embed_window([0])
        window._embed_in_taskbar()
        self.assertTrue(window.embed_failed)
        self.assertIn('wrapper', window.embed_failure)

    def test_taskbar_rect_unavailable_records_hwnd(self):
        window = self.embed_window([5])
        window._embed_in_taskbar.__func__.__globals__['_win_rect'].return_value = None
        window._embed_in_taskbar()
        self.assertTrue(window.embed_failed)
        self.assertIn('77', window.embed_failure)

    def test_catcher_zero_records_reason(self):
        window = self.embed_window([5, 0])
        window._embed_in_taskbar()
        self.assertTrue(window.embed_failed)
        self.assertIn('catcher', window.embed_failure)

    def test_embedder_failure_is_copied(self):
        window = self.embed_window([5, 6], embedder_ok=False,
                                   failure='catcher SetParent refused (err=5)')
        window._embed_in_taskbar()
        self.assertTrue(window.embed_failed)
        self.assertEqual(window.embed_failure, 'catcher SetParent refused (err=5)')

    def test_embedder_failure_unset_still_has_reason(self):
        window = self.embed_window([5, 6], embedder_ok=False, failure=None)
        window._embed_in_taskbar()
        self.assertTrue(window.embed_failure)

    def test_main_log_contains_the_reason(self):
        windows = [window_mock(embed_failed=True, embed_failure='catcher SetParent refused (err=5)'),
                   window_mock(exit_requested=True)]
        h = Harness(windows)
        h.run()
        self.assertTrue(any('catcher SetParent refused (err=5)' in m for m in h.messages))


class EmbedderCatcherTests(unittest.TestCase):
    def embedder(self, **u32_attrs):
        u32 = Mock(**u32_attrs)
        u32.GetWindowLongPtrW.return_value = 0
        ns = load_definitions('sys_monitor.py', {'TaskbarEmbedder'}, {
            '_u32': u32, 'ctypes': ctypes, '_log_event': Mock(), 'find_taskbar': Mock(return_value=(None, None)),
            'GWL_EXSTYLE': -20, 'GWL_STYLE': -16, 'WS_EX_LAYERED': 0x80000, 'WS_POPUP': 1 << 31,
            'WS_CHILD': 0x40000000, 'LWA_ALPHA': 2, 'EMBED_KEY_COLORREF': 0x010101,
            'LWA_COLORKEY': 1})
        return ns['TaskbarEmbedder'](10, 100, catcher_hwnd=20), u32

    def test_catcher_not_a_window(self):
        emb, u32 = self.embedder(IsWindow=Mock(return_value=False))
        self.assertFalse(emb._embed_catcher(99))
        self.assertIn('catcher', emb.failure)

    def test_catcher_setparent_refused_records_err(self):
        emb, u32 = self.embedder(IsWindow=Mock(return_value=True), GetParent=Mock(return_value=0))
        self.assertFalse(emb._embed_catcher(99))
        self.assertIn('SetParent', emb.failure)
        self.assertIn('err=', emb.failure)

    def test_catcher_layered_attributes_failed_records_err(self):
        emb, u32 = self.embedder(IsWindow=Mock(return_value=True), GetParent=Mock(return_value=99),
                                 SetLayeredWindowAttributes=Mock(return_value=0))
        self.assertFalse(emb._embed_catcher(99))
        self.assertIn('SetLayeredWindowAttributes', emb.failure)
        self.assertIn('err=', emb.failure)

    def test_embed_without_tray_records_reason(self):
        emb, u32 = self.embedder()
        emb.target_tray = None
        self.assertFalse(emb.embed())
        self.assertTrue(emb.failure)


if __name__ == '__main__':
    unittest.main()
