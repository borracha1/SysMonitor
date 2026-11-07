"""History window logic with a fake Tk: nothing is shown on screen."""
import unittest
from unittest.mock import Mock, patch

import traffic_history_ui as ui
from traffic_history import FamilyPoint


class WindowTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(ui, 'tk')
        self.tk = patcher.start()
        self.addCleanup(patcher.stop)
        self.tk.TclError = RuntimeError
        self.tk.Button.side_effect = lambda *args, **kwargs: Mock()
        self.master = Mock()
        self.history = Mock()
        self.history.clock.return_value = 1_000_000
        self.history.points.return_value = []
        self.top = self.tk.Toplevel.return_value
        self.top.winfo_exists.return_value = True
        self.canvas = self.tk.Canvas.return_value
        self.canvas.winfo_width.return_value = 800
        self.canvas.winfo_height.return_value = 360
        self.window = ui.TrafficHistoryWindow(self.master, self.history, lambda v: f'{v}B', '#111', '#222',
                                              work_area=lambda: (0, 0, 1920, 1040))

    def shown_family(self):
        return self.history.points.call_args.args[0]

    def test_window_is_a_child_of_the_hidden_root_so_it_survives_explorer_restart(self):
        self.window.show('ipv4')
        self.tk.Toplevel.assert_called_once_with(self.master)

    def test_opens_on_the_clicked_family(self):
        self.window.show('ipv6')
        self.assertEqual(self.shown_family(), 'ipv6')

    def test_default_family_is_ipv4_and_period_is_one_hour(self):
        self.window.show()
        self.assertEqual(self.history.points.call_args.args, ('ipv4', 3600))

    def test_second_click_reuses_the_window_and_changes_family(self):
        self.window.show('ipv4')
        self.window.show('ipv6')
        self.tk.Toplevel.assert_called_once()
        self.top.lift.assert_called()
        self.assertEqual(self.shown_family(), 'ipv6')

    def test_menu_opens_the_last_family_seen(self):
        self.window.show('ipv6')
        self.window.close()
        self.window.show()
        self.assertEqual(self.shown_family(), 'ipv6')

    def test_chosen_period_lasts_until_the_program_closes(self):
        self.window.show('ipv4')
        self.window._select_period(14400)
        self.assertEqual(self.history.points.call_args.args, ('ipv4', 14400))
        self.window.close()
        self.window.show()
        self.assertEqual(self.history.points.call_args.args[1], 14400)

    def test_selected_buttons_are_highlighted(self):
        self.window.show('ipv6')
        self.assertEqual(self.window._buttons['ipv6'].config.call_args.kwargs['relief'], 'sunken')
        self.assertEqual(self.window._buttons['ipv4'].config.call_args.kwargs['relief'], 'raised')

    def test_refreshes_every_5_s_and_close_cancels_it(self):
        self.window.show('ipv4')
        self.top.after.assert_called_with(5000, self.window._refresh)
        self.top.after.return_value = 'job'
        self.window._refresh()
        self.window.close()
        self.top.after_cancel.assert_called_with('job')
        self.top.destroy.assert_called_once()
        calls = self.history.points.call_count
        self.window.redraw()
        self.assertEqual(self.history.points.call_count, calls)

    def test_window_closed_by_the_system_is_recreated(self):
        self.window.show('ipv4')
        self.top.winfo_exists.return_value = False
        self.window.show('ipv4')
        self.assertEqual(self.tk.Toplevel.call_count, 2)

    def test_canvas_not_measured_yet_draws_nothing_and_does_not_fail(self):
        self.canvas.winfo_width.return_value = 1
        self.canvas.winfo_height.return_value = 1
        self.window.show('ipv4')
        self.canvas.create_line.assert_not_called()

    def test_no_data_shows_collecting_message(self):
        self.window.show('ipv4')
        texts = [call.kwargs.get('text') for call in self.canvas.create_text.call_args_list]
        self.assertIn('Coletando dados…', texts)

    def test_single_point_segment_is_still_drawn(self):
        self.history.points.return_value = [FamilyPoint(1_000_000 - 10, 100, None, 0)]
        self.window.show('ipv4')
        self.assertTrue(self.canvas.create_line.called)

    def test_close_without_a_window_and_after_tk_is_gone_is_harmless(self):
        self.window.close()
        self.window.show('ipv4')
        self.top.destroy.side_effect = RuntimeError('gone')
        self.window.close()

    def test_title_says_the_values_are_estimated(self):
        self.window.show('ipv4')
        self.top.title.assert_called_once_with('SysMonitor · Histórico de tráfego (estimado)')


class GeometryTests(unittest.TestCase):
    def test_centers_inside_the_work_area_of_the_clicked_screen(self):
        self.assertEqual(ui.centered_geometry((0, 0, 1920, 1040), 800, 360), '800x360+560+340')
        self.assertEqual(ui.centered_geometry((-1920, 100, 0, 1180), 800, 360), '800x360+-1360+460')

    def test_never_starts_above_or_left_of_a_small_screen(self):
        self.assertEqual(ui.centered_geometry((0, 0, 640, 300), 800, 360), '800x360+0+0')


if __name__ == '__main__':
    unittest.main()
