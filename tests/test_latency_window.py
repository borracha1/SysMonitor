"""Latency and loss window with a fake Tk: nothing on screen."""
import unittest
from unittest.mock import patch

import traffic_history as th
import traffic_history_ui as ui
from traffic_history import FamilyPoint as P
import test_traffic_window_zoom as base

NOW = base.NOW
event = base.event


class LatencyCase(base.WindowCase):
    KIND = 'latency'

    def setUp(self):
        patcher = patch.object(ui, 'tk')
        self.tk = patcher.start()
        self.addCleanup(patcher.stop)
        self.tk.TclError = RuntimeError
        self.tk.Button.side_effect = lambda *args, **kwargs: base.Mock()
        self.tk.Label.side_effect = lambda *args, **kwargs: base.Mock()
        self.tk.Frame.side_effect = lambda *args, **kwargs: base.Mock()
        self.master = base.Mock()
        self.history = base.Mock()
        self.history.clock.return_value = NOW
        self.history.points_between.return_value = []
        self.top = self.tk.Toplevel.return_value
        self.top.winfo_exists.return_value = True
        self.canvas = self.tk.Canvas.return_value
        self.canvas.winfo_width.return_value = 800
        self.canvas.winfo_height.return_value = 360
        self.window = ui.LatencyHistoryWindow(self.master, self.history, lambda v: f'{v}B', '#111', '#222',
                                              work_area=lambda: (0, 0, 1920, 1040))
        self.window.show('ipv4')
        self.plot = self.window._chart.plot

    def texts(self):
        return [call.kwargs.get('text') for call in self.canvas.create_text.call_args_list]


class LegendAndFilterTests(LatencyCase):
    GROUPS = {'ipv4': ('8.8.8.8', '1.1.1.1'), 'ipv6': ('2001:db8::1',)}

    def setUp(self):
        super().setUp()
        self.window.ping_targets = lambda: self.GROUPS
        self.window.redraw()

    def series(self):
        with patch.object(ui, 'build_chart', wraps=ui.build_chart) as spy:
            self.window.redraw()
        return spy.call_args.args[5], spy.call_args.kwargs['kind']

    def legend_text(self, name):
        return self.window._legend[name][0].config.call_args.kwargs['text']

    def test_has_only_the_latency_series_and_the_loss_legend(self):
        self.assertEqual(set(self.window._legend), {'ping', 'ping2', 'pingw', 'loss'})
        self.assertEqual(set(self.window._legend_frames), {'latency', 'loss'})
        self.assertEqual(self.series(), (th.KIND_SERIES['latency'], 'latency'))

    def test_legend_names_the_current_ip_of_each_position(self):
        self.assertEqual(self.legend_text('ping'), '8.8.8.8')
        self.assertEqual(self.legend_text('ping2'), '1.1.1.1')

    def test_position_without_ip_is_not_shown_and_follows_the_family(self):
        self.window._select_family('ipv6')
        self.assertEqual(self.legend_text('ping'), '2001:db8::1')
        self.assertEqual(self.legend_text('ping2'), '')
        self.window._select_family('ipv4')
        self.assertEqual(self.legend_text('ping2'), '1.1.1.1')

    def test_old_data_without_a_configured_ip_still_gets_a_label(self):
        self.window._select_family('ipv6')
        self.history.points_between.return_value = [P(NOW - 100, 1, 1, 0, 5, 6)]
        self.window.redraw()
        self.assertEqual(self.legend_text('ping2'), 'ping 2')

    def test_worst_of_both_legend_only_when_old_points_are_in_view(self):
        self.assertEqual(self.legend_text('pingw'), '')
        self.history.points_between.return_value = [P(NOW - 100, 1, 1, 0, None, None, 9)]
        self.window.redraw()
        self.assertEqual(self.legend_text('pingw'), 'pior dos dois')

    def test_loss_legend_explains_both_colours(self):
        created = [call.kwargs for call in self.tk.Label.call_args_list]
        self.assertIn('perda:', [kwargs.get('text') for kwargs in created])
        self.assertIn('um IP sem resposta', [kwargs.get('text') for kwargs in created])
        self.assertIn('todos sem resposta', [kwargs.get('text') for kwargs in created])
        self.assertTrue({ui.MARK_COLORS[1], ui.MARK_COLORS[2]} <= {kwargs.get('fg') for kwargs in created})
        self.assertEqual(len(self.window._legend['loss']), 5)

    def test_every_legend_item_filters_its_own_series(self):
        for name in ('ping', 'ping2', 'pingw', 'loss'):
            for label in self.window._legend[name]:
                with self.subTest(name=name):
                    self.window.series_filter = None
                    self.assertEqual(label.bind.call_args.args[0], '<Button-1>')
                    label.bind.call_args.args[1](None)
                    self.assertEqual(self.window.series_filter, name)

    def test_click_filters_again_shows_all(self):
        self.window._select_series('ping2')
        self.assertEqual(self.series()[0], {'ping2'})
        self.window._select_series('ping2')
        self.assertEqual(self.series()[0], th.KIND_SERIES['latency'])

    def test_active_item_is_highlighted(self):
        self.window._select_series('ping')
        self.assertEqual(self.window._legend['ping'][0].config.call_args.kwargs['bg'], ui.LEGEND_ACTIVE_BG)
        self.assertEqual(self.window._legend['loss'][0].config.call_args.kwargs['bg'], ui.BG)

    def test_two_lines_with_their_own_colours_and_the_ms_scale(self):
        self.history.points_between.return_value = [P(NOW - 100, 1, 1, 0, 30, 60)]
        self.canvas.create_line.reset_mock()
        self.canvas.create_text.reset_mock()
        self.window.redraw()
        colors = [call.kwargs.get('fill') for call in self.canvas.create_line.call_args_list]
        self.assertIn(ui.PING_COLOR, colors)
        self.assertIn(ui.PING2_COLOR, colors)
        self.assertEqual((ui.PING_COLOR, ui.PING2_COLOR, ui.PING_WORST_COLOR), ('#c9a0ff', '#5fd7c0', '#9aa0a6'))
        calls = [c for c in self.canvas.create_text.call_args_list if c.kwargs.get('text') == '60 ms']
        self.assertEqual((len(calls), calls[0].args[0]), (1, self.window._chart.plot[0] - 6))

    def test_worst_of_both_is_dashed_gray(self):
        self.history.points_between.return_value = [P(NOW - 100, 1, 1, 0, None, None, 9),
                                                    P(NOW - 95, 1, 1, 0, None, None, 9)]
        self.window.redraw()
        dashed = [call.kwargs for call in self.canvas.create_line.call_args_list if call.kwargs.get('dash')]
        self.assertEqual([(kwargs['fill'], kwargs['dash']) for kwargs in dashed],
                         [(ui.PING_WORST_COLOR, ui.PING_WORST_DASH)])

    def test_no_speed_lines_are_drawn(self):
        self.history.points_between.return_value = [P(NOW - 100, 1000, 500, 0, 30, 60)]
        self.canvas.create_line.reset_mock()
        self.window.redraw()
        colors = {call.kwargs.get('fill') for call in self.canvas.create_line.call_args_list}
        self.assertFalse(colors & {'#111', '#222'})

    def test_loss_bands_are_drawn_once_over_the_whole_panel(self):
        self.history.points_between.return_value = [P(NOW - 100, 1, 1, 2, 5)]
        self.canvas.create_rectangle.reset_mock()
        self.window.redraw()
        chart = self.window._chart
        spans = [(call.args[1], call.args[3], call.kwargs['fill']) for call in self.canvas.create_rectangle.call_args_list]
        self.assertEqual(spans, [(chart.plot[1], chart.plot[3], ui.MARK_COLORS[2])])

    def test_loss_legend_sits_under_the_chart_and_ip_legend_above_it(self):
        self.window.redraw()
        chart = self.window._chart
        placed = {call.kwargs['window']: call for call in self.canvas.create_window.call_args_list}
        frames = self.window._legend_frames
        self.assertEqual(placed[frames['latency']].args[1], chart.plot[1] - 4)
        self.assertGreater(placed[frames['loss']].args[1], chart.plot[3])

    def test_no_ping_at_all_says_so_discreetly_but_the_bands_stay(self):
        self.history.points_between.return_value = [P(NOW - 100, 100, 10, 2)]
        self.canvas.create_text.reset_mock()
        self.canvas.create_rectangle.reset_mock()
        self.window.redraw()
        self.assertIn('sem dados de ping', self.texts())
        self.canvas.create_rectangle.assert_called_once()

    def test_ping_present_has_no_such_message(self):
        self.history.points_between.return_value = [P(NOW - 100, 100, 10, 0, 30)]
        self.canvas.create_text.reset_mock()
        self.window.redraw()
        self.assertNotIn('sem dados de ping', self.texts())

    def test_filter_on_loss_only_hides_lines_without_complaining(self):
        self.history.points_between.return_value = [P(NOW - 100, 100, 10, 2, 30)]
        self.canvas.create_text.reset_mock()
        self.window._select_series('loss')
        self.assertNotIn('sem dados de ping', self.texts())
        self.assertNotIn('30 ms', self.texts())


class SummaryTests(LatencyCase):
    def test_summary_names_each_ip_and_counts_the_failures_and_has_no_speed(self):
        self.window.ping_targets = lambda: {'ipv4': ('8.8.8.8', '1.1.1.1')}
        self.history.points_between.return_value = [P(NOW - 100, 500, 400, 2, 30, 60)]
        self.window._zoom(th.ZOOM_STEP)
        text = self.window._summary.config.call_args.kwargs['text']
        self.assertIn('ping 8.8.8.8 pico 30 ms', text)
        self.assertIn('ping 1.1.1.1 pico 60 ms', text)
        self.assertIn('1 intervalo com falha', text)
        self.assertNotIn('↓', text)
        self.assertNotIn('↑', text)

    def test_summary_is_hidden_while_live(self):
        self.window._summary.pack.assert_not_called()

    def test_range_without_data_says_so(self):
        self.window._zoom(th.ZOOM_STEP)
        self.assertIn('Sem dados neste trecho', self.texts())


class WindowTests(LatencyCase):
    def test_title_and_shared_controls(self):
        self.top.title.assert_called_once_with('SysMonitor · Latência e perda')
        self.assertEqual(list(self.window._buttons), ['ipv4', 'ipv6', 300, 900, 3600, 14400])
        self.assertEqual(self.window.period_s, 3600)

    def test_zoom_and_selection_use_the_single_panel(self):
        self.window._on_wheel(event(x=244, delta=120))
        self.assertAlmostEqual(self.history.points_between.call_args.args[2] - self.history.points_between.call_args.args[1], 2700)
        self.window._drag_start(event(x=176, y=(self.plot[1] + self.plot[3]) // 2))
        self.assertIsNotNone(self.window._drag)

    def test_chosen_family_is_kept_when_reopened_from_the_menu(self):
        self.window.show('ipv6')
        self.window.close()
        self.window.show()
        self.assertEqual(self.history.points_between.call_args.args[0], 'ipv6')


if __name__ == '__main__':
    unittest.main()
