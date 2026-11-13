"""Hover tooltip with a fake Tk and a fake monitor: nothing on screen, no real sampling."""
import unittest
from unittest.mock import Mock, patch

import hover_tooltip as ht
import top_processes as tp

CPU_RECT = (1000, 1040, 1100, 1080)
MEM_RECT = (1200, 1040, 1300, 1080)
TOP = tp.TopLists([tp.Entry('chrome.exe', 12.0, 12.0)], [tp.Entry('vivaldi.exe', 2 * 1024 ** 3, 12.0)])


class FakeMonitor:
    def __init__(self):
        self.active = set()
        self.data = None
        self.calls = []

    def set_active(self, owner, active):
        self.calls.append((owner, active))
        (self.active.add if active else self.active.discard)(owner)

    def snapshot(self):
        return self.data


class TooltipCase(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(ht, 'tk')
        self.tk = patcher.start()
        self.addCleanup(patcher.stop)
        self.tk.TclError = RuntimeError
        self.windows = []
        self.labels = []

        def toplevel(*args, **kwargs):
            window = Mock()
            window.winfo_reqwidth.return_value = 200
            window.winfo_reqheight.return_value = 60
            self.windows.append(window)
            return window

        def label(*args, **kwargs):
            item = Mock()
            self.labels.append(item)
            return item

        self.tk.Toplevel.side_effect = toplevel
        self.tk.Label.side_effect = label
        self.master = Mock()
        self.master.after.side_effect = lambda ms, callback: f'after-{ms}'
        self.monitor = FakeMonitor()
        self.hit = None
        self.tip = ht.HoverTooltip(self.master, self.monitor, 'w1', lambda: self.hit, '#111', '#eee',
                                   ('Segoe UI', 9), screen=lambda: (0, 0, 1920, 1080))

    def text(self):
        return self.labels[-1].config.call_args.kwargs['text']


class ShowHideTests(TooltipCase):
    def test_nothing_happens_while_the_cursor_is_elsewhere(self):
        self.tip.pointer_moved()
        self.assertFalse(self.tip.visible)
        self.assertEqual(self.monitor.calls, [])
        self.tk.Toplevel.assert_not_called()

    def test_hover_shows_the_window_and_turns_sampling_on(self):
        self.hit = ('cpu', CPU_RECT)
        self.tip.pointer_moved()
        self.assertTrue(self.tip.visible)
        self.assertEqual(self.monitor.active, {'w1'})
        self.assertEqual(self.text(), 'Maiores em CPU\ncoletando…')
        self.windows[0].overrideredirect.assert_called_with(True)
        self.windows[0].attributes.assert_called_with('-topmost', True)
        self.assertEqual(self.windows[0].configure.call_args.kwargs['bg'], '#111')
        self.assertEqual(self.tk.Toplevel.call_args.args[0], self.master)  # Never a child of the Explorer widget.

    def test_leaving_hides_it_and_stops_the_sampling(self):
        self.hit = ('cpu', CPU_RECT)
        self.tip.pointer_moved()
        self.hit = None
        self.tip.pointer_moved()
        self.assertFalse(self.tip.visible)
        self.windows[0].destroy.assert_called_once()
        self.assertEqual(self.monitor.active, set())
        self.master.after_cancel.assert_called_once_with('after-250')

    def test_placed_above_the_label_inside_the_screen(self):
        self.hit = ('cpu', CPU_RECT)
        self.tip.pointer_moved()
        self.windows[0].geometry.assert_called_with('+1000+976')

    def test_close_is_safe_when_nothing_is_shown_and_after_destroy_errors(self):
        self.tip.close()
        self.hit = ('mem', MEM_RECT)
        self.tip.pointer_moved()
        self.windows[0].destroy.side_effect = RuntimeError('gone')
        self.tip.close()
        self.assertFalse(self.tip.visible)

    def test_hit_test_failure_counts_as_not_hovering(self):
        self.tip.hit_test = Mock(side_effect=OSError('win32'))
        self.tip.pointer_moved()
        self.assertFalse(self.tip.visible)


class ContentTests(TooltipCase):
    def test_cpu_and_memory_show_their_own_lists(self):
        self.monitor.data = TOP
        self.hit = ('cpu', CPU_RECT)
        self.tip.pointer_moved()
        self.assertEqual(self.text(), 'Maiores em CPU\nchrome.exe  12%')
        self.hit = ('mem', MEM_RECT)
        self.tip.pointer_moved()
        self.assertEqual(self.text(), 'Maiores em memória\nvivaldi.exe  2,0 GB (12%)')
        self.windows[0].destroy.assert_called_once()  # One window at a time.
        self.assertEqual(len(self.windows), 2)

    def test_new_samples_are_picked_up_while_the_mouse_stays(self):
        self.hit = ('cpu', CPU_RECT)
        self.tip.pointer_moved()
        self.monitor.data = TOP
        self.tip._poll()
        self.assertEqual(self.text(), 'Maiores em CPU\nchrome.exe  12%')
        self.assertEqual(len(self.windows), 1)

    def test_unchanged_text_is_not_rewritten(self):
        self.monitor.data = TOP
        self.hit = ('cpu', CPU_RECT)
        self.tip.pointer_moved()
        self.tip._poll()
        self.assertEqual(self.labels[0].config.call_count, 1)

    def test_poll_hides_it_when_the_cursor_left_without_events(self):
        self.hit = ('cpu', CPU_RECT)
        self.tip.pointer_moved()
        self.hit = None
        self.tip._poll()
        self.assertFalse(self.tip.visible)
        self.assertEqual(self.monitor.active, set())

    def test_only_one_poll_is_scheduled_however_many_events_arrive(self):
        self.hit = ('cpu', CPU_RECT)
        for _ in range(5):
            self.tip.pointer_moved()
        self.assertEqual(self.master.after.call_count, 1)
        self.tip._poll()
        self.assertEqual(self.master.after.call_count, 2)


class VirtualScreenTests(unittest.TestCase):
    def test_virtual_screen_has_a_size(self):
        left, top, right, bottom = ht.virtual_screen()
        self.assertGreater(right - left, 0)
        self.assertGreater(bottom - top, 0)


if __name__ == '__main__':
    unittest.main()
