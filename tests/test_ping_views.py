"""Exercise view logic without importing the Windows entry points or opening Tk."""
import ast
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest

from metrics_collector import Metrics
from ping_monitor import fmt_ping_line, ping_has_problem, ping_marker, ping_column_width


ROOT = Path(__file__).resolve().parents[1]


def load_definitions(filename, names, namespace):
    tree = ast.parse((ROOT / filename).read_text(encoding='utf-8'))
    tree.body = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                 and node.name in names]
    exec(compile(tree, filename, 'exec'), namespace)
    return namespace


class FakeLabel(dict):
    def config(self, **kwargs):
        self.update(kwargs)


class PingViewTests(unittest.TestCase):
    def widget_namespace(self):
        return load_definitions('sys_monitor.py', {'Metrics', 'MonitorWindow', 'fmt_temp', 'fmt_speed'},
                                {'threading': threading, 'tk': SimpleNamespace(Tk=object),
                                 'configparser': SimpleNamespace(ConfigParser=object),
                                 'fmt_ping_line': fmt_ping_line, 'ping_has_problem': ping_has_problem,
                                 'PING_LOSS_COLOR': 'red', 'ping_marker': ping_marker, 'ping_column_width': ping_column_width})

    def test_both_metrics_contracts(self):
        for cls in (Metrics, self.widget_namespace()['Metrics']):
            metrics = cls()
            self.assertIsNone(metrics.ping)
            self.assertIsNone(metrics.snapshot()['ping'])
            for old in ('ping_loss', 'ping_rtt', 'ping_ok'):
                self.assertFalse(hasattr(metrics, old))
                self.assertNotIn(old, metrics.snapshot())

    def test_widget_lines_stay_visible_and_colors_recover(self):
        ns = self.widget_namespace()
        for mode in ('taskbar', 'docked', 'floating'):
            with self.subTest(mode=mode):
                window = ns['MonitorWindow'].__new__(ns['MonitorWindow'])
                window.mode = mode
                window.metrics = Metrics()
                window.ping_enabled = True
                window._ping_layout_family = 'ipv4'
                window.ping_targets = ('8.8.8.8', '1.1.1.1')
                window.ping_labels = [FakeLabel(), FakeLabel()]
                window.ping_marker_label = FakeLabel()
                window.metrics.ping = (('8.8.8.8', None, None, None), ('1.1.1.1', None, None, None))
                window._fg = 'normal'
                for name in ('up', 'down', 'cpu', 'gpu', 'mem', 'status'):
                    setattr(window, 'lbl_' + name, FakeLabel())
                window._update_labels()
                self.assertEqual(window.ping_labels[0]['text'], '8.8.8.8 --')
                window.metrics.ping = (('8.8.8.8', 25, None, False), ('1.1.1.1', 0, 12, True))
                window._update_labels()
                self.assertEqual(window.ping_labels[0], {'text': '8.8.8.8 25% --ms', 'fg': 'red'})
                self.assertEqual(window.ping_labels[1], {'text': '1.1.1.1 0% 12ms', 'fg': 'normal'})
                window.metrics.ping = (('8.8.8.8', 0, 14, True), ('1.1.1.1', 0, 12, True))
                window._update_labels()
                self.assertEqual(window.ping_labels[0], {'text': '8.8.8.8 0% 14ms', 'fg': 'normal'})
                window.ping_enabled = False
                window.ping_labels = []
                window._update_labels()

    def test_network_tooltip_per_target_and_limit(self):
        ns = load_definitions('tray_monitor.py', {'render_net', 'fmt_compact', 'fmt_speed_full'},
                              {'ping_marker': ping_marker, 'fmt_ping_line': fmt_ping_line})
        m = Metrics().snapshot()
        m['ping'] = (('8.8.8.8', 0, 14, True), ('1.1.1.1', 25, None, False))
        _, tooltip = ns['render_net'](m)
        self.assertIn('v4·A 8.8.8.8 0% 14ms', tooltip)
        self.assertIn('1.1.1.1 25% --ms', tooltip)
        m['ping'] *= 10
        self.assertEqual(len(ns['render_net'](m)[1]), 127)
        m['ping'] = None
        self.assertNotIn('Perda', ns['render_net'](m)[1])
