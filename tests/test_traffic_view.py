"""Pure view logic: filter, ping axis, zoom, selection and summary."""
import unittest

from traffic_history import (ALL_SERIES, FamilyPoint as P, build_chart, selection_view, summarize,
                             x_to_time, zoom_view)

NOW = 1_000_000
HOUR = 3600
FOUR = 4 * 3600


def chart(points, series=ALL_SERIES, now=NOW, span=HOUR):
    return build_chart(points, 800, 360, now, span, series, fmt_time=str)


class FilterTests(unittest.TestCase):
    POINTS = [P(NOW - 20, 100, 50, 1, 10), P(NOW - 10, 200, 40, 2, 20)]

    def test_continuous_failure_has_no_gaps_at_any_zoom(self):
        for span in (60, 300, 900, 2932, 3600, 14400):
            with self.subTest(span=span):
                points = [P(NOW - span + 5 * i, 1, 1, 2) for i in range(span // 5)]
                bands = chart(points, span=span).bands
                self.assertTrue(all(left[1] >= right[0] for left, right in zip(bands, bands[1:])))

    def test_everything_is_visible_by_default(self):
        result = chart(self.POINTS)
        self.assertTrue(result.down and result.up and result.ping and result.bands)

    def test_only_download(self):
        result = chart(self.POINTS, {'down'})
        self.assertTrue(result.down)
        self.assertEqual((result.up, result.ping, result.bands, result.ping_ticks), ([], [], [], []))

    def test_scale_follows_only_what_is_visible(self):
        points = [P(NOW - 10, 1000, 50, 0)]
        _, y0, _, _ = chart(points).plot
        result = chart(points, {'up'})
        self.assertEqual(result.up[0][0][1], y0)
        self.assertEqual(result.y_ticks[-1], (y0, 50))

    def test_only_ping_hides_the_left_axis(self):
        result = chart(self.POINTS, {'ping'})
        self.assertTrue(result.ping)
        self.assertEqual(result.y_ticks, [])
        self.assertEqual((result.down, result.up, result.bands), ([], [], []))

    def test_only_loss_hides_both_value_axes_and_keeps_time(self):
        result = chart(self.POINTS, {'loss'})
        self.assertEqual([band[2] for band in result.bands], [1, 2])
        self.assertEqual((result.y_ticks, result.ping_ticks, result.down, result.ping), ([], [], [], []))
        self.assertTrue(result.x_ticks)


class PingAxisTests(unittest.TestCase):
    def test_ping_has_its_own_scale(self):
        result = chart([P(NOW - 10, 1000, 1000, 0, 100)])
        _, y0, _, y1 = result.plot
        self.assertEqual(result.ping[0][0][1], y0)
        self.assertEqual(result.ping_ticks, [(y1, 0), ((y0 + y1) / 2, 50), (y0, 100)])
        self.assertEqual(result.y_ticks[-1], (y0, 1000))

    def test_ping_of_zero_ms_stays_on_the_base(self):
        result = chart([P(NOW - 10, 1, 1, 0, 0)])
        _, _, _, y1 = result.plot
        self.assertEqual(result.ping[0][0][1], y1)
        self.assertEqual(result.ping_ticks, [(y1, 0)])

    def test_old_points_have_no_ping_line_and_no_axis(self):
        result = chart([P(NOW - 10, 1, 1, 0)])
        self.assertEqual((result.ping, result.ping_ticks), ([], []))

    def test_missing_ping_breaks_the_line(self):
        result = chart([P(NOW - 100, 1, 1, 0, 5), P(NOW - 95, 1, 1, 0, None), P(NOW - 90, 1, 1, 0, 5)])
        self.assertEqual(len(result.ping), 2)

    def test_short_ping_peak_survives_reduction(self):
        points = [P(NOW - FOUR + i * 5, 1, 1, 0, 10) for i in range(2880)]
        points[1000] = points[1000]._replace(ping=900)
        result = chart(points, span=FOUR)
        self.assertEqual(result.ping_ticks[-1][1], 900)


class TimeAxisTests(unittest.TestCase):
    def ticks(self, span, now=36000, fmt_time=str):
        return [text for _, text in build_chart([], 800, 360, now, span, ALL_SERIES, fmt_time).x_ticks]

    def test_steps_of_each_period(self):
        self.assertEqual(self.ticks(300), [str(35700 + i * 60) for i in range(6)])
        self.assertEqual(self.ticks(900), [str(35100 + i * 300) for i in range(4)])
        self.assertEqual(self.ticks(3600), [str(32400 + i * 900) for i in range(5)])
        self.assertEqual(self.ticks(14400), [str(21600 + i * 3600) for i in range(5)])
        self.assertEqual(self.ticks(60), [str(35940 + i * 15) for i in range(5)])

    def test_labels_include_seconds_only_with_steps_under_one_minute(self):
        self.assertEqual(self.ticks(60, fmt_time=None)[0].count(':'), 2)
        self.assertEqual(self.ticks(300, fmt_time=None)[0].count(':'), 1)


class ZoomTests(unittest.TestCase):
    def test_zoom_in_cuts_25_percent_keeping_the_anchor_in_place(self):
        self.assertEqual(zoom_view(NOW - 3600, NOW, 0.75, NOW - 1800, NOW), (NOW - 3150, NOW - 450))
        start, end = zoom_view(NOW - 3600, NOW, 0.75, NOW - 2700, NOW)
        self.assertAlmostEqual((NOW - 2700 - start) / (end - start), 0.25)

    def test_never_shorter_than_one_minute(self):
        self.assertEqual(zoom_view(NOW - 60, NOW, 0.75, NOW - 30, NOW), (NOW - 60, NOW))
        start, end = zoom_view(NOW - 70, NOW - 10, 0.75, NOW - 40, NOW)
        self.assertEqual(end - start, 60)

    def test_never_longer_than_four_hours(self):
        self.assertEqual(zoom_view(NOW - FOUR, NOW, 1 / 0.75, NOW - 1000, NOW), (NOW - FOUR, NOW))

    def test_slides_back_when_passing_the_present(self):
        self.assertEqual(zoom_view(NOW - 3600, NOW, 1 / 0.75, NOW - 1800, NOW), (NOW - 4800, NOW))

    def test_slides_forward_when_passing_what_is_stored(self):
        start, end = zoom_view(NOW - FOUR, NOW - 12000, 1 / 0.75, NOW - 12000, NOW)
        self.assertEqual(start, NOW - FOUR)
        self.assertAlmostEqual(end - start, 3200)

    def test_view_that_aged_beyond_four_hours_comes_back(self):
        start, end = zoom_view(NOW - 20000, NOW - 19000, 0.75, NOW - 19500, NOW)
        self.assertEqual(start, NOW - FOUR)
        self.assertEqual(end - start, 750)


class SelectionTests(unittest.TestCase):
    def test_either_direction_gives_the_same_range(self):
        self.assertEqual(selection_view(NOW - 500, NOW - 100, NOW), (NOW - 500, NOW - 100))
        self.assertEqual(selection_view(NOW - 100, NOW - 500, NOW), (NOW - 500, NOW - 100))

    def test_short_selection_becomes_one_minute_around_its_center(self):
        self.assertEqual(selection_view(NOW - 100, NOW - 90, NOW), (NOW - 125, NOW - 65))

    def test_short_selection_at_the_present_slides_back(self):
        self.assertEqual(selection_view(NOW - 10, NOW, NOW), (NOW - 60, NOW))


class XToTimeTests(unittest.TestCase):
    PLOT = (100, 0, 300, 50)

    def test_converts_inside_the_plot(self):
        self.assertEqual(x_to_time(200, self.PLOT, 0, 200), 100)

    def test_limits_to_the_edges(self):
        self.assertEqual(x_to_time(50, self.PLOT, 0, 200), 0)
        self.assertEqual(x_to_time(999, self.PLOT, 0, 200), 200)


class SummaryTests(unittest.TestCase):
    POINTS = [P(1, 100, 10, 0, 20), P(2, 300, None, 1, None), P(3, None, 30, 2, 40)]

    def text(self, points=None, series=ALL_SERIES):
        return summarize(self.POINTS if points is None else points, 1, 3, series,
                         lambda v: f'{v}B', fmt_time=str)

    def test_peaks_averages_and_failures_skip_empty_values(self):
        self.assertEqual(self.text(), '1 – 3 · ↓ pico 300B, média 200.0B · ↑ pico 30B, média 20.0B'
                                      ' · ping pico 40 ms, média 30 ms · 2 intervalos com falha')

    def test_only_the_visible_measure_enters(self):
        self.assertEqual(self.text(series={'up'}), '1 – 3 · ↑ pico 30B, média 20.0B')
        self.assertEqual(self.text(series={'loss'}), '1 – 3 · 2 intervalos com falha')

    def test_measure_without_data_says_so(self):
        points = [P(1, None, None, 0, None)]
        self.assertEqual(self.text(points), '1 – 3 · ↓ sem dados · ↑ sem dados · ping sem dados · 0 intervalos com falha')

    def test_singular_failure(self):
        self.assertTrue(self.text([P(1, 1, 1, 2, 1)]).endswith('· 1 intervalo com falha'))

    def test_zero_ms_counts_as_data(self):
        self.assertIn('ping pico 0 ms, média 0 ms', self.text([P(1, 1, 1, 0, 0)]))


if __name__ == '__main__':
    unittest.main()
