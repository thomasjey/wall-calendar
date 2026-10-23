"""A fake HTTP session for Graph tests: no network, records requests."""

import json


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None, raw=None):
        self.status_code = status
        self.headers = headers or {}
        self._raw = raw if raw is not None else json.dumps(body if body is not None else {}).encode()

    def iter_content(self, size):
        for i in range(0, len(self._raw), size):
            yield self._raw[i : i + size]

    def close(self):
        pass


class FakeSession:
    """routes: list of (predicate(url) -> bool, response or callable(url) -> response)."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def get(self, url, headers=None, timeout=None, allow_redirects=True, stream=False):
        self.requests.append({"url": url, "headers": headers, "allow_redirects": allow_redirects, "timeout": timeout})
        for match, resp in self.routes:
            if match(url):
                return resp(url) if callable(resp) else resp
        return FakeResponse(404, {"error": {"code": "NotFound"}})


def graph_event(i, **over):
    ev = {"id": f"AAMk{i}", "subject": f"Event {i}", "isAllDay": False, "isCancelled": False,
          "start": {"dateTime": "2026-10-22T16:00:00.0000000", "timeZone": "UTC"},
          "end": {"dateTime": "2026-10-22T17:00:00.0000000", "timeZone": "UTC"},
          "location": {"displayName": "Somewhere"}, "sensitivity": "normal",
          "body": {"contentType": "text", "content": "Notes"}, "type": "singleInstance"}
    ev.update(over)
    return ev
