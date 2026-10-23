"""Microsoft Graph calendar reads (DESIGN §5.3).

HTTPS to graph.microsoft.com only: `@odata.nextLink` is followed only if it
points there, so a tampered response can't send the token elsewhere. Responses
are size-capped, paging is capped, redirects are not followed, and 429/503 are
retried only within the Retry-After budget.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from urllib.parse import quote, urlencode, urlsplit

log = logging.getLogger("fwcal.graph")

GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_HOST = "graph.microsoft.com"
TIMEOUT = (10, 30)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PAGES = 20
MAX_EVENTS = 2000
MAX_RETRY_AFTER = 120
PREFER = 'outlook.timezone="UTC", outlook.body-content-type="text"'

SELECT_FULL = ("id", "subject", "start", "end", "isAllDay", "isCancelled", "location", "body",
               "sensitivity", "showAs", "type")
_HIDDEN = {"full": set(), "titles": {"location", "body"}, "busy": {"subject", "location", "body"}}


class GraphError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def access_lost(self) -> bool:
        """The calendar is gone or no longer shared (as opposed to a network or service problem)."""
        return self.status in (403, 404)


def select_for(detail: str) -> str:
    """The $select for a calendar's detail level (ADR-15): hidden fields are never requested."""
    return ",".join(f for f in SELECT_FULL if f not in _HIDDEN[detail])


def check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != GRAPH_HOST or parts.port not in (None, 443) or parts.username:
        raise GraphError("refusing a URL outside https://graph.microsoft.com")


class Graph:
    def __init__(self, session, token: str, sleep: Callable[[float], None] = time.sleep) -> None:
        self._session = session
        self._token = token
        self._sleep = sleep

    def get(self, url: str, *, prefer: str | None = None) -> dict:
        check_url(url)
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        waited = 0.0
        while True:
            r = self._session.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=False, stream=True)
            try:
                if r.status_code in (429, 503):
                    delay = _retry_after(r.headers.get("Retry-After"))
                    if delay is None or waited + delay > MAX_RETRY_AFTER:
                        raise GraphError(f"HTTP {r.status_code}: throttled beyond the retry budget")
                    waited += delay
                    log.info("throttled (HTTP %d); waiting %ds", r.status_code, delay)
                    self._sleep(delay)
                    continue
                body = _read_capped(r)
            finally:
                r.close()
            if r.status_code != 200:
                raise GraphError(f"HTTP {r.status_code} (request-id {r.headers.get('request-id', '?')})", r.status_code)
            try:
                data = json.loads(body)
            except ValueError as exc:
                raise GraphError("response is not JSON") from exc
            if not isinstance(data, dict):
                raise GraphError("unexpected response shape")
            return data

    def pages(self, url: str, *, prefer: str | None = None, max_items: int = MAX_EVENTS):
        """Yields items across pages. Returns (via StopIteration value) True if truncated."""
        count = 0
        for _ in range(MAX_PAGES):
            data = self.get(url, prefer=prefer)
            items = data.get("value")
            if not isinstance(items, list):
                raise GraphError("response has no value list")
            for item in items:
                if count >= max_items:
                    return True
                count += 1
                yield item
            nxt = data.get("@odata.nextLink")
            if not nxt:
                return False
            if not isinstance(nxt, str):
                raise GraphError("bad nextLink")
            check_url(nxt)
            url = nxt
        return True

    def calendars(self) -> list[dict]:
        url = f"{GRAPH}/me/calendars?" + urlencode(
            {"$select": "id,name,canEdit,owner,isDefaultCalendar", "$top": "50"}, safe="$,")
        return list(self.pages(url, max_items=200))

    def calendar_view(self, calendar_id: str, start: str, end: str, detail: str) -> tuple[list[dict], bool]:
        url = f"{GRAPH}/me/calendars/{quote(calendar_id, safe='')}/calendarView?" + urlencode(
            {"startDateTime": start, "endDateTime": end, "$select": select_for(detail), "$top": "100"}, safe="$,:")
        gen = self.pages(url, prefer=PREFER)
        events = []
        try:
            while True:
                events.append(next(gen))
        except StopIteration as stop:
            truncated = bool(stop.value)
        return events, truncated


def _retry_after(value: str | None) -> int | None:
    try:
        seconds = int(value) if value is not None else None
    except ValueError:
        return None
    return seconds if seconds is not None and 0 <= seconds <= MAX_RETRY_AFTER else None


def _read_capped(r) -> bytes:
    chunks, size = [], 0
    for chunk in r.iter_content(64 * 1024):
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise GraphError("response larger than the cap")
        chunks.append(chunk)
    return b"".join(chunks)
