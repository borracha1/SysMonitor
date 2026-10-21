"""Active-family sizing and initial selection, without real Tk or Explorer."""
import configparser
import unittest
from unittest.mock import Mock

import ping_monitor as pm
import test_ping_group_views as group_views
from metrics_collector import Metrics


class PingLayoutTests(unittest.TestCase):
    def test_initial_family_manual_auto_and_empty_preferred(self):
        v4, v6 = ('8.8.8.8',), ('2606:4700:4700::1111',)
        for mode, preferred, a, b, expected in (
            ('ipv4', 'ipv6', v4, v6, 'ipv4'),
            ('ipv6', 'ipv4', v4, v6, 'ipv6'),
            ('auto', 'ipv4', v4, v6, 'ipv4'),
            ('auto', 'ipv6', v4, v6, 'ipv6'),
            ('auto', 'ipv4', (), v6, 'ipv6'),
            ('auto', 'ipv6', v4, (), 'ipv4'),
            ('ipv4', 'ipv4', (), v6, 'ipv6'),
            ('ipv6', 'ipv6', v4, (), 'ipv4'),
        ):
            with self.subTest(mode=mode, preferred=preferred, v4=a, v6=b):
                groups = {'ipv4': a, 'ipv6': b}
                self.assertEqual(pm.initial_ping_family(mode, preferred, groups), expected)
                monitor = pm.PingMonitor(Metrics(), a, b, mode=mode, preferred=preferred)
                self.assertEqual(monitor.active, expected)

    def test_widget_chooses_family_before_building_layout(self):
        for mode, preferred, v4, v6, expected in (
            ('ipv4', 'ipv6', '8.8.8.8', '::1', 'ipv4'),
            ('ipv6', 'ipv4', '8.8.8.8', '::1', 'ipv6'),
            ('auto', 'ipv6', '8.8.8.8', '::1', 'ipv6'),
            ('auto', 'ipv4', '', '::1', 'ipv6'),
            ('auto', 'ipv6', '8.8.8.8', '', 'ipv4'),
        ):
            with self.subTest(mode=mode, preferred=preferred):
                ns = group_views.GroupViewTests().namespace()
                ns.update(APP_NAME='SysMonitor', EMBED_KEY_COLOR='#010101',
                          initial_ping_family=pm.initial_ping_family)
                cls = ns['MonitorWindow']
                window = cls.__new__(cls)
                cfg = configparser.ConfigParser()
                cfg.read_dict({'window': {'fg_color': 'white'}, 'ping': {
                    'mode': mode, 'preferred': preferred, 'targets_v4': v4,
                    'targets_v6': v6, 'timeout_ms': '10000'}})
                def check_layout():
                    self.assertEqual(window._ping_layout_family, expected)
                    self.assertEqual(window.ping_timeout_ms, 10000)
                window._build_ui = Mock(side_effect=check_layout)
                for name in ('_place_window', '_bind_drag', '_bind_menu'):
                    setattr(window, name, Mock())
                window.__init__(Mock(), cfg, Metrics(), 'taskbar')
                window._build_ui.assert_called_once()

    def test_width_uses_timeout_reserve_and_active_targets_only(self):
        for targets in (('8.8.8.8', '1.1.1.1'),
                        ('2606:4700:4700::1111', '2001:4860:4860::8888')):
            for timeout in (250, 1000, 10000):
                texts = []
                def measure(text):
                    texts.append(text)
                    return len(text) * 6
                expected = 6 * (len('v6·A ') + max(
                    len(f'{ip} 100% {max(1000, timeout)}ms') for ip in targets))
                self.assertEqual(pm.ping_column_width(measure, targets, timeout), expected)
                self.assertEqual(texts, ['v6·A '] + [
                    f'{ip} 100% {max(1000, timeout)}ms' for ip in targets])

    def test_nonembedded_switch_resizes_panel_and_geometry(self):
        for mode in ('docked', 'floating'):
            with self.subTest(mode=mode):
                helper = group_views.GroupViewTests()
                ns = helper.namespace()
                font = Mock()
                font.measure.side_effect = lambda text: len(text) * 6
                font.metrics.return_value = 16
                ns.update(tkfont=Mock(Font=Mock(return_value=font)),
                          get_taskbar_rect=lambda: {'notify_left': 1800, 'top': 1040})
                window = helper.window(ns)
                window.mode = mode
                window.full_cfg['window'] = {'font_size': '9', 'taskbar_width': '220'}
                window.cfg = window.full_cfg['window']
                window._build_ping_panel(Mock(), 'black', ('Segoe UI', 9))
                window.root.winfo_reqwidth.side_effect = [280, 180]
                window.root.winfo_reqheight.return_value = 160
                window._request_rebuild = Mock()
                window._update_labels()
                window.root.geometry.assert_not_called()
                for family in ('ipv6', 'ipv4'):
                    window.metrics.ping_family = family
                    window._update_labels()
                    width = pm.ping_column_width(font.measure, window.ping_groups[family], 1000)
                    window.ping_panel.config.assert_called_with(width=width)
                    for label in window.ping_labels:
                        label.place_configure.assert_called_with(width=width - font.measure('v6·A '))
                    if mode == 'docked':
                        w = 220 + width + 12
                        window.root.geometry.assert_called_with(f'{w}x36+{1800-w}+1004')
                if mode == 'floating':
                    self.assertEqual([c.args[0] for c in window.root.geometry.call_args_list],
                                     ['280x160', '180x160'])
                self.assertEqual(window.root.geometry.call_count, 2)
                window._update_labels()
                self.assertEqual(window.root.geometry.call_count, 2)
                window._request_rebuild.assert_not_called()
                window.embedder.reposition.assert_not_called()
