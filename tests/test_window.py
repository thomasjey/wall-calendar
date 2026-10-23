import unittest
from datetime import date

from fwcal.window import month_grid, sync_window, utc_query_range, week_start_of


class Window(unittest.TestCase):
    def test_week_start(self):
        wed = date(2026, 10, 21)
        self.assertEqual(week_start_of(wed, "sunday"), date(2026, 10, 18))
        self.assertEqual(week_start_of(wed, "monday"), date(2026, 10, 19))
        self.assertEqual(week_start_of(date(2026, 10, 18), "sunday"), date(2026, 10, 18))

    def test_month_grid_october_2026_sunday(self):
        self.assertEqual(month_grid(2026, 10, "sunday"), (date(2026, 9, 27), date(2026, 11, 1)))

    def test_month_grid_six_rows_and_december(self):
        start, end = month_grid(2026, 8, "sunday")  # Aug 1 2026 is a Saturday
        self.assertEqual((start, end), (date(2026, 7, 26), date(2026, 9, 6)))
        self.assertEqual((end - start).days, 42)
        self.assertEqual(month_grid(2026, 12, "sunday"), (date(2026, 11, 29), date(2027, 1, 3)))

    def test_sync_window_lookahead_wins(self):
        self.assertEqual(sync_window(date(2026, 10, 21), 35, "sunday"), (date(2026, 9, 27), date(2026, 11, 26)))

    def test_sync_window_month_grid_wins(self):
        # The end is the month grid's end; the start is a week back (earlier than the grid start).
        self.assertEqual(sync_window(date(2026, 8, 1), 7, "sunday"), (date(2026, 7, 25), date(2026, 9, 6)))

    def test_sync_window_keeps_a_week_of_history(self):
        # November 2026 starts on a Sunday, so its grid starts on the 1st itself.
        self.assertEqual(month_grid(2026, 11, "sunday")[0], date(2026, 11, 1))
        self.assertEqual(sync_window(date(2026, 11, 1), 35, "sunday")[0], date(2026, 10, 25))
        self.assertEqual(sync_window(date(2026, 11, 3), 35, "sunday")[0], date(2026, 10, 27))
        # Later in the month the grid start is already earlier than a week ago.
        self.assertEqual(sync_window(date(2026, 11, 20), 35, "sunday")[0], date(2026, 11, 1))

    def test_year_rollover(self):
        start, end = sync_window(date(2026, 12, 31), 35, "sunday")
        self.assertEqual((start, end), (date(2026, 11, 29), date(2027, 2, 5)))

    def test_utc_query_range_has_slack(self):
        self.assertEqual(utc_query_range(date(2026, 9, 27), date(2026, 11, 26)),
                         ("2026-09-26T00:00:00Z", "2026-11-27T00:00:00Z"))


if __name__ == "__main__":
    unittest.main()
