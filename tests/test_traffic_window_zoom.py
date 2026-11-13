"""Live and frozen views, drag, zoom and filter with a fake Tk: nothing on screen."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import traffic_history as th
import traffic_history_ui as ui
from traffic_history import FamilyPoint as P

NOW = 1_000_000


def event(x=400, y=100, delta=0):
    return SimpleNamespace(x=x, y=y, delta=delta)


class WindowCase(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(ui, 'tk')
        self.tk = patcher.start()
        self.addCleanup(patcher.stop)
        self.tk.TclError = RuntimeError
        self.tk.Button.side_effect = lambda *args, **kwargs: Mock()
        self.tk.Label.side_effect = lambda *args, **kwargs: Mock()
        self.master = Mock()
        self.history = Mock()
        self.history.clock.return_value = NOW
        self.history.points_between.return_value = []
        self.top = self.tk.Toplevel.return_value
        self.top.winfo_exists.return_value = True
        self.canvas = self.tk.Canvas.return_value
        self.canvas.winfo_width.return_value = 800
        self.canvas.winfo_height.return_value = 360
        self.window = ui.TrafficHistoryWindow(self.master, self.history, lambda v: f'{v}B', '#111', '#222',
                                              work_area=lambda: (0, 0, 1920, 1040))
        self.window.show('ipv4')
        self.plot = self.window._chart.plot

    def range_shown(self):
        return self.history.points_between.call_args.args[1:]

    def selected(self, key):
        return self.window._buttons[key].config.call_args.kwargs['relief'] == 'sunken'


class PeriodTests(WindowCase):
    def test_four_period_buttons(self):
        self.assertEqual([key for key in self.window._buttons if key not in ('ipv4', 'ipv6')],
                         [300, 900, 3600, 14400])

    def test_each_period_is_live_and_highlighted(self):
        for period in (300, 900, 3600, 14400):
            with self.subTest(period=period):
                self.window._select_period(period)
                self.assertEqual(self.range_shown(), (NOW - period, NOW))
                self.assertTrue(self.selected(period))

    def test_live_view_follows_the_clock_and_a_frozen_one_does_not(self):
        self.history.clock.return_value = NOW + 5
        self.window._refresh()
        self.assertEqual(self.range_shown(), (NOW + 5 - 3600, NOW + 5))
        self.window._zoom(th.ZOOM_STEP)
        frozen = self.range_shown()
        self.history.clock.return_value = NOW + 10
        self.window._refresh()
        self.assertEqual(self.range_shown(), frozen)


class ZoomTests(WindowCase):
    def test_wheel_up_zooms_in_keeping_the_time_under_the_mouse(self):
        x = 244
        before = th.x_to_time(x, self.plot, NOW - 3600, NOW)
        self.window._on_wheel(event(x=x, delta=120))
        start, end = self.range_shown()
        self.assertAlmostEqual(end - start, 2700)
        self.assertAlmostEqual(th.x_to_time(x, self.plot, start, end), before)

    def test_wheel_down_zooms_out(self):
        self.window._on_wheel(event(delta=-120))
        start, end = self.range_shown()
        self.assertAlmostEqual(end - start, 4800)
        self.assertEqual(end, NOW)

    def test_wheel_outside_the_plot_uses_the_center(self):
        self.window._on_wheel(event(x=10, delta=120))
        self.assertEqual(self.range_shown(), (NOW - 3150, NOW - 450))

    def test_plus_and_minus_buttons_use_the_center(self):
        commands = {call.kwargs['text']: call.kwargs['command'] for call in self.tk.Button.call_args_list}
        commands['+']()
        self.assertEqual(self.range_shown(), (NOW - 3150, NOW - 450))
        commands['−']()
        start, end = self.range_shown()
        self.assertAlmostEqual(end - start, 3600)

    def test_keyboard(self):
        handlers = {call.args[0]: call.args[1] for call in self.top.bind.call_args_list}
        for key in ('<plus>', '<equal>', '<KP_Add>'):
            with self.subTest(key=key):
                self.window._select_period(3600)
                handlers[key](None)
                self.assertAlmostEqual(self.range_shown()[1] - self.range_shown()[0], 2700)
        for key in ('<minus>', '<KP_Subtract>'):
            with self.subTest(key=key):
                self.window._select_period(3600)
                handlers[key](None)
                self.assertAlmostEqual(self.range_shown()[1] - self.range_shown()[0], 4800)

    def test_frozen_view_turns_off_the_period_highlight_and_a_period_goes_back_to_live(self):
        self.window._zoom(th.ZOOM_STEP)
        self.assertFalse(self.selected(3600))
        self.window._select_period(900)
        self.assertTrue(self.selected(900))
        self.assertEqual(self.range_shown(), (NOW - 900, NOW))

    def test_changing_family_keeps_the_frozen_range(self):
        self.window._zoom(th.ZOOM_STEP)
        frozen = self.range_shown()
        self.window._select_family('ipv6')
        self.assertEqual(self.history.points_between.call_args.args, ('ipv6', *frozen))
        self.window.show('ipv4')
        self.assertEqual(self.history.points_between.call_args.args, ('ipv4', *frozen))

    def test_closing_drops_the_frozen_range_and_keeps_the_last_period(self):
        self.window._select_period(900)
        self.window._zoom(th.ZOOM_STEP)
        self.window.close()
        self.window.show()
        self.assertEqual(self.range_shown(), (NOW - 900, NOW))
        self.assertTrue(self.selected(900))

    def test_zoom_on_a_range_older_than_four_hours_comes_back(self):
        self.window.view = (NOW - 20000, NOW - 19000)
        self.window._zoom(th.ZOOM_STEP)
        self.assertEqual(self.range_shown()[0], NOW - th.KEEP_S)


class DragTests(WindowCase):
    def test_band_is_translucent_blue_so_the_lines_stay_visible(self):
        self.window._drag_start(event(x=176))
        options = self.canvas.create_rectangle.call_args.kwargs
        self.assertEqual((options['fill'], options['stipple'], options['outline']),
                         ('#2f6fb0', 'gray25', '#7fb3e6'))

    def drag(self, first, last):
        self.window._drag_start(event(x=first))
        self.window._drag_move(event(x=last))
        self.window._drag_end(event(x=last))

    def expected(self, first, last):
        return th.selection_view(th.x_to_time(first, self.plot, NOW - 3600, NOW),
                                 th.x_to_time(last, self.plot, NOW - 3600, NOW), NOW)

    def test_dragging_freezes_the_selected_range(self):
        self.drag(176, 576)
        self.assertEqual(self.range_shown(), self.expected(176, 576))

    def test_either_direction_gives_the_same_range(self):
        self.drag(576, 176)
        self.assertEqual(self.range_shown(), self.expected(176, 576))

    def test_band_follows_the_mouse_inside_the_plot(self):
        self.window._drag_start(event(x=176))
        self.window._drag_move(event(x=5000))
        item = self.canvas.create_rectangle.return_value
        self.canvas.coords.assert_called_with(item, 176, self.plot[1], self.plot[2], self.plot[3])

    def test_releasing_outside_the_window_stops_at_the_edge(self):
        self.drag(176, 5000)
        self.assertEqual(self.range_shown(), self.expected(176, self.plot[2]))
        self.assertAlmostEqual(self.range_shown()[1], NOW)

    def test_movement_under_4_px_is_not_a_selection(self):
        self.drag(176, 179)
        self.assertIsNone(self.window.view)
        self.assertTrue(self.selected(3600))

    def test_movement_of_4_px_selects_at_least_one_minute(self):
        self.drag(176, 180)
        start, end = self.range_shown()
        self.assertEqual(end - start, 60)

    def test_press_outside_the_plot_is_ignored(self):
        self.drag(10, 400)
        self.assertIsNone(self.window.view)
        self.window._drag_start(event(x=176, y=self.plot[3] + 5))
        self.assertIsNone(self.window._drag)

    def test_refresh_during_the_drag_keeps_the_band(self):
        self.window._drag_start(event(x=176))
        deletes = self.canvas.delete.call_count
        self.window._refresh()
        self.assertEqual(self.canvas.delete.call_count, deletes)
        self.assertIsNotNone(self.window._drag)

    def test_range_comes_from_what_was_on_screen_when_the_drag_started(self):
        expected = self.expected(176, 576)
        self.window._drag_start(event(x=176))
        self.history.clock.return_value = NOW + 30
        self.window._drag_end(event(x=576))
        self.assertEqual(self.window.view, expected)

    def test_escape_cancels_the_drag_and_keeps_the_window(self):
        handlers = {call.args[0]: call.args[1] for call in self.top.bind.call_args_list}
        self.window._drag_start(event(x=176))
        handlers['<Escape>'](None)
        self.assertIsNone(self.window._drag)
        self.assertIsNone(self.window.view)
        self.top.destroy.assert_not_called()
        self.window._drag_end(event(x=576))
        self.assertIsNone(self.window.view)

    def test_escape_without_a_drag_closes(self):
        handlers = {call.args[0]: call.args[1] for call in self.top.bind.call_args_list}
        handlers['<Escape>'](None)
        self.top.destroy.assert_called_once()

    def test_canvas_binds_drag_and_wheel(self):
        events = {call.args[0] for call in self.canvas.bind.call_args_list}
        self.assertLessEqual({'<ButtonPress-1>', '<B1-Motion>', '<ButtonRelease-1>', '<MouseWheel>'}, events)


class SummaryLineTests(WindowCase):
    def test_hidden_when_live_and_shown_when_frozen(self):
        self.window._summary.pack.assert_not_called()
        self.history.points_between.return_value = [P(NOW - 100, 100, 10, 2, 30)]
        self.window._zoom(th.ZOOM_STEP)
        self.window._summary.pack.assert_called_once()
        text = self.window._summary.config.call_args.kwargs['text']
        self.assertIn('↓ pico 100B', text)
        self.assertIn('ping pico 30 ms', text)
        self.assertIn('1 intervalo com falha', text)
        self.window._select_period(300)
        self.window._summary.pack_forget.assert_called_once()

    def test_summary_follows_the_filter(self):
        self.history.points_between.return_value = [P(NOW - 100, 100, 10, 2, 30)]
        self.window._zoom(th.ZOOM_STEP)
        self.window._select_series('up')
        text = self.window._summary.config.call_args.kwargs['text']
        self.assertIn('↑ pico 10B', text)
        self.assertNotIn('↓', text)

    def test_frozen_range_without_data_says_so(self):
        self.window._zoom(th.ZOOM_STEP)
        texts = [call.kwargs.get('text') for call in self.canvas.create_text.call_args_list]
        self.assertIn('Sem dados neste trecho', texts)


class FilterTests(WindowCase):
    def series(self):
        with patch.object(ui, 'build_chart', wraps=ui.build_chart) as spy:
            self.window.redraw()
        return spy.call_args.args[5]

    def test_click_shows_only_that_item_another_swaps_and_again_shows_all(self):
        self.assertEqual(self.series(), th.ALL_SERIES)
        self.window._select_series('down')
        self.assertEqual(self.series(), {'down'})
        self.window._select_series('ping')
        self.assertEqual(self.series(), {'ping'})
        self.window._select_series('ping')
        self.assertEqual(self.series(), th.ALL_SERIES)

    def test_every_label_of_an_item_is_clickable(self):
        for name in ('down', 'up', 'ping', 'loss'):
            for label in self.window._legend[name]:
                with self.subTest(name=name):
                    self.window.series_filter = None
                    handler = label.bind.call_args.args[1]
                    self.assertEqual(label.bind.call_args.args[0], '<Button-1>')
                    handler(None)
                    self.assertEqual(self.window.series_filter, name)

    def test_active_item_is_highlighted(self):
        self.window._select_series('ping')
        self.assertEqual(self.window._legend['ping'][0].config.call_args.kwargs['bg'], ui.LEGEND_ACTIVE_BG)
        self.assertEqual(self.window._legend['down'][0].config.call_args.kwargs['bg'], ui.BG)

    def test_filter_survives_closing_the_window(self):
        self.window._select_series('up')
        self.window.close()
        self.window.show()
        self.assertEqual(self.series(), {'up'})

    def test_ping_draws_its_line_and_axis_in_ms(self):
        self.history.points_between.return_value = [P(NOW - 100, 100, 10, 0, 30)]
        self.window.redraw()
        texts = [call.kwargs.get('text') for call in self.canvas.create_text.call_args_list]
        self.assertIn('30 ms', texts)
        colors = [call.kwargs.get('fill') for call in self.canvas.create_line.call_args_list]
        self.assertIn(ui.PING_COLOR, colors)

    def test_only_ping_on_old_data_is_empty_without_failing(self):
        self.history.points_between.return_value = [P(NOW - 100, 100, 10, 0)]
        self.canvas.create_text.reset_mock()
        self.window._select_series('ping')
        texts = [call.kwargs.get('text') for call in self.canvas.create_text.call_args_list]
        self.assertFalse([text for text in texts if text and text.endswith(' ms')])


class TwoPingWindowTests(WindowCase):
    GROUPS = {'ipv4': ('8.8.8.8', '1.1.1.1'), 'ipv6': ('2001:db8::1',)}

    def setUp(self):
        super().setUp()
        self.window.ping_targets = lambda: self.GROUPS
        self.window.redraw()

    def legend_text(self, name):
        return self.window._legend[name][0].config.call_args.kwargs['text']

    def test_legend_names_the_current_ip_of_each_position(self):
        self.assertEqual(self.legend_text('ping'), 'ping 8.8.8.8')
        self.assertEqual(self.legend_text('ping2'), 'ping 1.1.1.1')

    def test_position_without_ip_is_not_shown_and_follows_the_family(self):
        self.window._select_family('ipv6')
        self.assertEqual(self.legend_text('ping'), 'ping 2001:db8::1')
        self.assertEqual(self.legend_text('ping2'), '')
        self.window._select_family('ipv4')
        self.assertEqual(self.legend_text('ping2'), 'ping 1.1.1.1')

    def test_old_data_without_a_configured_ip_still_gets_a_label(self):
        self.window._select_family('ipv6')
        self.history.points_between.return_value = [P(NOW - 100, 1, 1, 0, 5, 6)]
        self.window.redraw()
        self.assertEqual(self.legend_text('ping2'), 'ping 2')

    def test_worst_of_both_legend_only_when_old_points_are_in_view(self):
        self.assertEqual(self.legend_text('pingw'), '')
        self.history.points_between.return_value = [P(NOW - 100, 1, 1, 0, None, None, 9)]
        self.window.redraw()
        self.assertEqual(self.legend_text('pingw'), 'ping (pior dos dois)')

    def test_two_lines_with_their_own_colors(self):
        self.history.points_between.return_value = [P(NOW - 100, 1, 1, 0, 30, 60)]
        self.canvas.create_line.reset_mock()
        self.window.redraw()
        colors = [call.kwargs.get('fill') for call in self.canvas.create_line.call_args_list]
        self.assertIn(ui.PING_COLOR, colors)
        self.assertIn(ui.PING2_COLOR, colors)
        self.assertNotEqual(ui.PING_COLOR, ui.PING2_COLOR)
        texts = [call.kwargs.get('text') for call in self.canvas.create_text.call_args_list]
        self.assertIn('60 ms', texts)

    def test_each_ping_legend_filters_its_own_line(self):
        for name in ('ping', 'ping2', 'pingw'):
            with self.subTest(name=name):
                self.window.series_filter = None
                for label in self.window._legend[name]:
                    label.bind.call_args.args[1](None)
                self.assertEqual(self.window.series_filter, name)

    def test_summary_names_each_ip(self):
        self.history.points_between.return_value = [P(NOW - 100, 1, 1, 0, 30, 60)]
        self.window._zoom(th.ZOOM_STEP)
        text = self.window._summary.config.call_args.kwargs['text']
        self.assertIn('ping 8.8.8.8 pico 30 ms', text)
        self.assertIn('ping 1.1.1.1 pico 60 ms', text)


if __name__ == '__main__':
    unittest.main()
