"""Graph event -> display event (DESIGN §5.4, §5.5, §6).

Input is an untrusted Graph `event` resource fetched with
`Prefer: outlook.timezone="UTC"` and `Prefer: outlook.body-content-type="text"`.
Output follows the events.json contract. Graph IDs never leave this module.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta

from . import textclean

_GRAPH_DT = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?$")
_PRIVATE = frozenset({"private", "confidential"})


class InvalidEvent(ValueError):
    """The Graph event can't be shown safely; it is skipped and counted."""


def event_id(cal_key: str, graph_id: str) -> str:
    return hashlib.sha256(f"{cal_key}\0{graph_id}".encode()).hexdigest()[:16]


def _parse_utc(value: object) -> datetime:
    """A timed event's start or end. Must be UTC (we asked Graph for UTC); any
    other zone is refused rather than guessed."""
    if not isinstance(value, dict) or not isinstance(value.get("dateTime"), str):
        raise InvalidEvent("start/end missing")
    if value.get("timeZone") != "UTC":
        raise InvalidEvent("time zone not UTC")
    m = _GRAPH_DT.match(value["dateTime"])
    if m is None:
        raise InvalidEvent("bad dateTime")
    try:
        return datetime(*(int(g) for g in m.groups()))
    except ValueError as exc:
        raise InvalidEvent("bad dateTime") from exc


def _date_part(value: object) -> date:
    if not isinstance(value, dict) or not isinstance(value.get("dateTime"), str):
        raise InvalidEvent("start/end missing")
    m = _GRAPH_DT.match(value["dateTime"])
    if m is None:
        raise InvalidEvent("bad dateTime")
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError as exc:
        raise InvalidEvent("bad date") from exc


def normalize_event(ev: object, cal_key: str, *, show_notes: bool, detail: str = "full") -> dict | None:
    """Returns the display event, or None for events that are not shown
    (cancelled). Raises InvalidEvent for malformed input.

    detail: "full", "titles" (title and time only) or "busy" (time only)."""
    if detail not in ("full", "titles", "busy"):
        raise ValueError(f"unknown detail level: {detail!r}")
    if not isinstance(ev, dict):
        raise InvalidEvent("not an object")
    graph_id = ev.get("id")
    if not isinstance(graph_id, str) or not graph_id:
        raise InvalidEvent("missing id")
    if ev.get("isCancelled") is True:
        return None

    private = str(ev.get("sensitivity") or "").lower() in _PRIVATE
    out: dict = {"id": event_id(cal_key, graph_id), "cal": cal_key}

    if private:
        out["title"], out["location"], out["notes"] = "Private", "", ""
    elif detail == "busy":
        out["title"], out["location"], out["notes"] = "Busy", "", ""
    elif detail == "titles":
        title = textclean.clean_line(ev.get("subject"), textclean.TITLE_MAX)
        out["title"], out["location"], out["notes"] = title or "(No title)", "", ""
    else:
        title = textclean.clean_line(ev.get("subject"), textclean.TITLE_MAX)
        loc = ev.get("location")
        out["title"] = title or "(No title)"
        out["location"] = textclean.clean_line(
            loc.get("displayName") if isinstance(loc, dict) else None, textclean.LOCATION_MAX
        )
        notes = ""
        body = ev.get("body")
        if show_notes and isinstance(body, dict):
            is_html = str(body.get("contentType") or "").lower() == "html"
            notes = textclean.clean_notes(body.get("content"), is_html=is_html)
        out["notes"] = notes
    out["private"] = private

    if ev.get("isAllDay") is True:
        start, end = _date_part(ev.get("start")), _date_part(ev.get("end"))
        if end <= start:
            end = start + timedelta(days=1)
        out.update(allDay=True, startDate=start.isoformat(), endDate=end.isoformat())
    else:
        start_dt, end_dt = _parse_utc(ev.get("start")), _parse_utc(ev.get("end"))
        end_dt = max(end_dt, start_dt)
        out.update(
            allDay=False,
            start=start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end=end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    return out
