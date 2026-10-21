"""Grouped presentation and editor/menu wiring without showing a widget."""
import ast
import configparser
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

import ping_monitor as pm
from metrics_collector import Metrics
import test_ping_views as views
from test_ping_views import FakeLabel, load_definitions


class GroupViewTests(unittest.TestCase):
    def namespace(self):
        ns = views.PingViewTests().widget_namespace()
        ns.update(tk=Mock(), ping_settings=pm.ping_settings, parse_ping_groups=pm.parse_ping_groups,
                  save_ping_settings=Mock(), CONFIG_PATH='unused', _log_event=Mock(),
                  configparser=configparser)
        return ns

    def window(self, ns):
        window = ns['MonitorWindow'].__new__(ns['MonitorWindow'])
        window.metrics = Metrics()
        window.ping_monitor = pm.PingMonitor(window.metrics)
        window.ping_groups = window.ping_monitor.groups
        window._ping_layout_family = 'ipv4'
        window.ping_timeout_ms = 1000
        window.embedder = Mock()
        window.root, window.master = Mock(), Mock()
        window.root.winfo_height.return_value = 40
        window._fg, window.mode, window.ping_enabled = 'white', 'taskbar', True
        window.ping_marker_label = FakeLabel()
        window.ping_labels = [FakeLabel(), FakeLabel()]
        for name in ('up', 'down', 'cpu', 'gpu', 'mem', 'status'):
            setattr(window, 'lbl_' + name, FakeLabel())
        window.full_cfg = configparser.ConfigParser()
        window.full_cfg['ping'] = {}
        return window

    def test_markers_second_line_empty_and_no_rebuild(self):
        ns = self.namespace()
        window = self.window(ns)
        window._relayout_ping = Mock()
        for mode in ('auto', 'ipv6', 'ipv4'):
            window.ping_monitor.set_mode(mode)
            window._update_labels()
            expected = {'auto': 'v4·A', 'ipv6': 'v6', 'ipv4': 'v4'}[mode]
            self.assertEqual(window.ping_marker_label['text'], expected)
        window.ping_monitor.set_groups((), ('::1',), 'ipv6')
        window._update_labels()
        self.assertEqual(window.ping_labels[0]['text'], '::1 --')
        self.assertEqual(window.ping_labels[1]['text'], '')
        self.assertEqual(window.metrics.ping_family, 'ipv6')
        self.assertEqual(window.ping_monitor.mode, 'ipv6')

    def test_ping_column_width_follows_active_group(self):
        ns = self.namespace()
        font = Mock()
        font.measure.side_effect = lambda text: len(text) * 6
        font.metrics.return_value = 16
        ns.update(tkfont=Mock(Font=Mock(return_value=font)), EMBED_KEY_COLOR='#010101')
        window = self.window(ns)
        window.ping_monitor.set_groups(('8.8.8.8', '1.1.1.1'),
                                       ('2606:4700:4700::1111', '2001:4860:4860::8888'), 'ipv4')
        window.full_cfg['window'] = {'font_size': '9', 'fg_color': 'white',
                                     'accent_up': 'green', 'accent_down': 'blue'}
        window.cfg = window.full_cfg['window']
        window.ping_targets = window.ping_monitor.targets
        window.ping_groups = window.ping_monitor.groups
        window._ping_layout_family = 'ipv4'
        window.ping_timeout_ms = 1000
        window._build_embedded_ui()
        expected = font.measure('v6·A ') + max(
            font.measure(f'{ip} 100% 1000ms') for ip in window.ping_monitor.groups['ipv4'])
        self.assertEqual(window._cols['ping'][1], expected)
        self.assertEqual(window._cols['hw'][0], window._cols['ping'][0] + expected + 10)

    def test_embedded_switch_resizes_without_rebuild_and_aligns_lines(self):
        ns = self.namespace()
        font = Mock()
        font.measure.side_effect = lambda text: len(text) * 8
        font.metrics.return_value = 16
        ns.update(tkfont=Mock(Font=Mock(return_value=font)), EMBED_KEY_COLOR='#010101')
        window = self.window(ns)
        window.full_cfg['window'] = {'font_size': '9', 'fg_color': 'white',
                                     'accent_up': 'green', 'accent_down': 'blue'}
        window.cfg = window.full_cfg['window']
        window._build_embedded_ui()
        width_v4 = window.embed_width
        window._layout_embedded = Mock(wraps=window._layout_embedded)
        window._request_rebuild = Mock()
        window._update_labels()
        window._layout_embedded.assert_not_called()
        for family in ('ipv6', 'ipv4'):
            window.metrics.ping_family = family
            window._update_labels()
            cols = window._cols
            self.assertEqual(cols['ping'][1], pm.ping_column_width(
                font.measure, window.ping_groups[family], 1000))
            self.assertEqual(cols['hw'][0], cols['ping'][0] + cols['ping'][1] + 10)
            self.assertEqual(window.embedder.width, window.embed_width)
            window._layout_embedded.assert_called_with(40)
            x = window.ping_labels[0].place.call_args.kwargs['x']
            self.assertEqual(x, window.ping_labels[1].place.call_args.kwargs['x'])
            if family == 'ipv6':
                self.assertGreater(window.embed_width, width_v4)
            else:
                self.assertEqual(window.embed_width, width_v4)
        self.assertEqual(window.embedder.reposition.call_count, 2)
        self.assertEqual(window._layout_embedded.call_count, 2)
        window._update_labels()
        self.assertEqual(window._layout_embedded.call_count, 2)
        window._request_rebuild.assert_not_called()
        ns['_log_event'].assert_not_called()

    def test_nonembedded_panel_active_width_and_alignment(self):
        ns = self.namespace()
        font = Mock()
        font.measure.side_effect = lambda text: len(text) * 8
        font.metrics.return_value = 16
        ns['tkfont'] = Mock(Font=Mock(return_value=font))
        window = self.window(ns)
        window.ping_targets = window.ping_monitor.targets
        window._build_ping_panel(Mock(), 'black', ('Segoe UI', 9))
        frame_kwargs = ns['tk'].Frame.call_args.kwargs
        self.assertEqual(frame_kwargs['width'], pm.ping_column_width(font.measure, window.ping_groups['ipv4'], 1000))
        self.assertEqual(frame_kwargs['height'], 32)
        self.assertEqual(window.ping_labels[0].place.call_args.kwargs['x'], font.measure('v6·A '))

    def test_radio_menu_and_mode_persistence_without_rebuild(self):
        ns = self.namespace()
        window = self.window(ns)
        window.ping_monitor.set_groups(('1.1.1.1',), (), 'ipv4')
        window._bind_menu()
        menu = ns['tk'].Menu.return_value
        radios = menu.add_radiobutton.call_args_list
        self.assertEqual([c.kwargs['label'] for c in radios], ['Automático', 'Só IPv4', 'Só IPv6'])
        self.assertEqual([c.kwargs['state'] for c in radios], ['normal', 'normal', 'disabled'])
        window._destroy = Mock()
        radios[1].kwargs['command']()
        ns['save_ping_settings'].assert_called_once_with('unused', mode='ipv4')
        self.assertEqual(window.ping_monitor.mode, 'ipv4')
        window._destroy.assert_not_called()
        ns['save_ping_settings'].side_effect = OSError('denied')
        window._select_ping_mode('auto')
        self.assertEqual(window.ping_monitor.mode, 'ipv4')
        window._ping_mode_var.set.assert_called_with('ipv4')

    def test_editor_four_fields_and_preferred_radios(self):
        ns = self.namespace()
        window = self.window(ns)
        window._closing, window._ping_editor = False, None
        editor = ns['tk'].Toplevel.return_value
        for name, value in [('winfo_reqwidth', 450), ('winfo_reqheight', 400),
                            ('winfo_screenwidth', 1920), ('winfo_screenheight', 1080)]:
            getattr(editor, name).return_value = value
        window._edit_ping_targets()
        self.assertEqual(ns['tk'].Entry.call_count, 4)
        titles = [c.kwargs.get('text') for c in ns['tk'].Label.call_args_list]
        self.assertEqual(titles[:4], ['IPv4 1', 'IPv4 2', 'IPv6 1', 'IPv6 2'])
        self.assertEqual([c.kwargs['value'] for c in ns['tk'].Radiobutton.call_args_list], ['ipv4', 'ipv6'])
        self.assertEqual([c.args[1] for c in ns['tk'].Entry.return_value.insert.call_args_list],
                         list(window.ping_monitor.targets))

    def test_load_config_migrates_before_defaults_and_never_writes_existing(self):
        tree = ast.parse(Path('sys_monitor.py').read_text(encoding='utf-8'))
        defaults = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == 'DEFAULTS' for t in n.targets))
        defaults = ast.literal_eval(defaults)
        self.assertNotIn('targets', defaults['ping'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.ini'
            original = '[ping]\ntargets=1.1.1.1,::1\n'
            path.write_text(original, encoding='utf-8')
            ns = load_definitions('sys_monitor.py', {'load_config'},
                                  {'configparser': configparser, 'DEFAULTS': defaults,
                                   'CONFIG_PATH': path, 'ping_settings': pm.ping_settings})
            cfg = ns['load_config']()
            monitor = pm.PingMonitor.from_config(cfg['ping'], Metrics())
            self.assertEqual(monitor.targets, ('1.1.1.1', '::1'))
            self.assertEqual(path.read_text(encoding='utf-8'), original)

    def test_tooltip_active_first_and_inactive_truncated_first(self):
        ns = load_definitions('tray_monitor.py', {'render_net', 'fmt_compact', 'fmt_speed_full'},
                              {'ping_marker': pm.ping_marker, 'fmt_ping_line': pm.fmt_ping_line})
        metrics = Metrics()
        monitor = pm.PingMonitor(metrics)
        monitor.record((12, 13, 14, 15))
        text = ns['render_net'](metrics.snapshot())[1]
        self.assertLess(text.index('v4·A'), text.index('v6'))
        self.assertLessEqual(len(text), 127)
        monitor.set_mode('ipv6')
        text = ns['render_net'](metrics.snapshot())[1]
        self.assertIn('v6 2001:4860:4860::8888 0% 14ms / 2606:4700:4700::1111 0% 15ms', text)
        self.assertLessEqual(len(text), 127)


if __name__ == '__main__':
    unittest.main()
