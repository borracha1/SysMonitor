"""Pure chart geometry: every number here is what the window will draw."""
import unittest

from traffic_history import FamilyPoint as P, build_chart

NOW = 1_000_000
HOUR = 3600
FOUR = 4 * 3600


def chart(points, width=800, height=360, now=NOW, period=HOUR):
    return build_chart(points, width, height, now, period, fmt_time=str)


class ChartTests(unittest.TestCase):
    def test_peak_touches_the_top_and_zero_the_base(self):
        result = chart([P(NOW - 20, 0, 0, 0), P(NOW - 10, 100, 50, 0)])
        _, y0, _, y1 = result.plot
        self.assertEqual(result.down[0][0][1], y1)
        self.assertEqual(result.down[0][1][1], y0)
        self.assertEqual(result.up[0][1][1], (y0 + y1) / 2)

    def test_time_runs_left_to_right(self):
        result = chart([P(NOW - HOUR, 1, 1, 0), P(NOW, 1, 1, 0)])
        x0, _, x1, _ = result.plot
        self.assertEqual([point[0] for segment in result.down for point in segment], [x0, x1])

    def test_short_peak_survives_when_there_are_more_points_than_pixels(self):
        points = [P(NOW - FOUR + i * 5, 100, 100, 0) for i in range(2880)]
        points[1000] = P(points[1000].epoch, 9000, 100, 0)
        result = chart(points, width=400, period=FOUR)
        _, y0, _, _ = result.plot
        self.assertIn(y0, [y for _, y in result.down[0]])

    def test_interval_above_15_s_breaks_the_line(self):
        result = chart([P(NOW - 100, 1, 1, 0), P(NOW - 95, 1, 1, 0), P(NOW - 79, 1, 1, 0)])
        self.assertEqual([len(segment) for segment in result.down], [2, 1])

    def test_interval_of_exactly_15_s_keeps_the_line(self):
        result = chart([P(NOW - 100, 1, 1, 0), P(NOW - 85, 1, 1, 0)])
        self.assertEqual([len(segment) for segment in result.down], [2])

    def test_pc_asleep_for_an_hour_shows_a_hole(self):
        result = chart([P(NOW - FOUR + 10, 1, 1, 0), P(NOW - 10, 1, 1, 0)], period=FOUR)
        self.assertEqual(len(result.down), 2)

    def test_missing_measurement_breaks_the_line_but_keeps_the_mark(self):
        result = chart([P(NOW - 100, 1, 1, 0), P(NOW - 95, None, None, 2), P(NOW - 90, 1, 1, 0)])
        self.assertEqual(len(result.down), 2)
        self.assertEqual([band[2] for band in result.bands], [2])

    def test_points_out_of_order_are_drawn_in_time_order(self):
        result = chart([P(NOW, 1, 1, 0), P(NOW - HOUR, 1, 1, 0)])
        xs = [point[0] for segment in result.down for point in segment]
        self.assertEqual(xs, sorted(xs))

    def test_family_without_traffic_stays_on_the_base_with_only_zero_on_the_axis(self):
        result = chart([P(NOW - 10, 0, 0, 0), P(NOW - 5, 0, 0, 0)])
        _, _, _, y1 = result.plot
        self.assertEqual({y for _, y in result.down[0]}, {y1})
        self.assertEqual(result.y_ticks, [(y1, 0)])

    def test_axis_shows_zero_middle_and_peak(self):
        result = chart([P(NOW - 10, 100, 0, 0)])
        _, y0, _, y1 = result.plot
        self.assertEqual(result.y_ticks, [(y1, 0), ((y0 + y1) / 2, 50), (y0, 100)])

    def test_strong_marks_are_drawn_after_light_ones_and_clean_points_have_none(self):
        result = chart([P(NOW - 100, 1, 1, 2), P(NOW - 50, 1, 1, 0), P(NOW - 10, 1, 1, 1)])
        self.assertEqual([band[2] for band in result.bands], [1, 2])

    def test_mark_band_is_at_least_one_pixel_and_stays_inside_the_plot(self):
        result = chart([P(NOW, 1, 1, 2)], period=FOUR)
        left, right, _ = result.bands[0]
        _, _, x1, _ = result.plot
        self.assertLessEqual(right, x1)
        self.assertGreaterEqual(right - left, 0)
        result = chart([P(NOW - 100, 1, 1, 2)], period=FOUR)
        self.assertGreaterEqual(result.bands[0][1] - result.bands[0][0], 1)

    def test_time_marks_every_15_min_in_one_hour_and_every_hour_in_four(self):
        now = 36000
        one = build_chart([], 800, 360, now, HOUR, fmt_time=str)
        self.assertEqual([text for _, text in one.x_ticks], [str(32400 + i * 900) for i in range(5)])
        four = build_chart([], 800, 360, now, FOUR, fmt_time=str)
        self.assertEqual([text for _, text in four.x_ticks], [str(21600 + i * 3600) for i in range(5)])

    def test_points_outside_the_period_are_ignored(self):
        result = chart([P(NOW - HOUR - 1, 9000, 9000, 2), P(NOW - 10, 100, 0, 0)])
        self.assertEqual(result.y_ticks[-1][1], 100)
        self.assertEqual(result.bands, [])

    def test_area_too_small_returns_none(self):
        for width, height in ((1, 1), (50, 200), (800, 20)):
            with self.subTest(width=width, height=height):
                self.assertIsNone(build_chart([P(NOW, 1, 1, 0)], width, height, NOW, HOUR))


if __name__ == '__main__':
    unittest.main()
