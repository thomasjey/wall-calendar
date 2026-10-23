"""The synced date window (DESIGN §5.3, ADR-8).

Dates here are local calendar dates. The window's end is exclusive.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

WEEK_STARTS = {"sunday": 6, "monday": 0}  # date.weekday() of the first column


def week_start_of(day: date, week_start: str) -> date:
    first = WEEK_STARTS[week_start]
    return day - timedelta(days=(day.weekday() - first) % 7)


def month_grid(year: int, month: int, week_start: str) -> tuple[date, date]:
    """First day shown and the day after the last day shown in a month view."""
    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    start = week_start_of(first, week_start)
    last_shown = week_start_of(nxt - timedelta(days=1), week_start) + timedelta(days=6)
    return start, last_shown + timedelta(days=1)


HISTORY_DAYS = 7


def sync_window(today: date, lookahead_days: int, week_start: str) -> tuple[date, date]:
    """[start, end): from the earlier of the current month's grid start and a
    week ago (so the Day and Week views can always look back a week, even when
    the month starts on the first day of the grid), to the later of
    today + lookahead and the current month's grid end."""
    grid_start, grid_end = month_grid(today.year, today.month, week_start)
    start = min(grid_start, today - timedelta(days=HISTORY_DAYS))
    return start, max(today + timedelta(days=lookahead_days + 1), grid_end)


def utc_query_range(start: date, end: date) -> tuple[str, str]:
    """The Graph calendarView range, widened by a day each side so no time zone
    offset can cut off an event. The browser filters by local date."""
    lo = datetime(start.year, start.month, start.day, tzinfo=UTC) - timedelta(days=1)
    hi = datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return lo.strftime(fmt), hi.strftime(fmt)
