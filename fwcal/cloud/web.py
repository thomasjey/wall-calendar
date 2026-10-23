"""Request handling for the away-from-home page (DESIGN §15.3–15.6).

Framework-free: function_app.py turns an Azure request into a Request and the
Response back. Every request is denied unless it passes, in order: GET/HEAD
only; the app's own Host; Fetch Metadata (only top-level navigations may come
from another site); a principal set by the platform's sign-in; the personal-
account tenant; and the code allowlist (layer 3). The static files, the events
and the settings are the same as on the wall.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..server import SECURITY_HEADERS
from . import principal as principals
from .consent import Consent, ConsentError
from .oauth import CONSUMER_TENANT
from .settings import SettingsCache, SettingsUnavailable
from .storage import EventsCache

log = logging.getLogger("fwcal.cloud.web")

PAGES = frozenset({"/", "/enrol", "/admin/consent", "/admin/consent/callback"})
TEXT = "text/plain; charset=utf-8"
JSON = "application/json"


@dataclass
class Request:
    method: str
    path: str
    headers: dict[str, str]  # lower-case names
    query: dict[str, str] = field(default_factory=dict)


@dataclass
class Response:
    status: int
    body: bytes = b""
    content_type: str | None = TEXT
    headers: dict[str, str] = field(default_factory=dict)


def _text(status: int, message: str) -> Response:
    return Response(status, (message + "\n").encode("utf-8"))


class Web:
    def __init__(self, *, static: dict[str, tuple[bytes, str]], settings: SettingsCache, events: EventsCache,
                 hostnames: frozenset[str], consent: Consent | None,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._static, self._settings, self._events = static, settings, events
        self._hosts = frozenset(h.lower() for h in hostnames)
        self._consent, self._now = consent, now

    def handle(self, req: Request) -> Response:
        try:
            resp = self._route(req)
        except Exception as exc:  # never a stack trace or detail in a response
            log.exception("request failed: %s", type(exc).__name__)
            resp = _text(500, "Error 500")
        return self._finish(req, resp)

    @staticmethod
    def _finish(req: Request, resp: Response) -> Response:
        headers = {**SECURITY_HEADERS, "Cache-Control": "no-store", **resp.headers}
        if resp.status == 304:
            return Response(304, b"", None, headers)
        if req.method == "HEAD":
            headers["Content-Length"] = str(len(resp.body))
            return Response(resp.status, b"", resp.content_type, headers)
        return Response(resp.status, resp.body, resp.content_type, headers)

    def _route(self, req: Request) -> Response:
        if req.method not in ("GET", "HEAD"):
            return Response(405, b"Method not allowed\n", TEXT, {"Allow": "GET, HEAD"})
        if req.headers.get("host", "").lower() not in self._hosts:
            return _text(421, "Error 421")
        path = req.path
        if not path.startswith("/") or "#" in path or len(path) > 200:
            return _text(400, "Error 400")
        if not self._fetch_allowed(req.headers, path):
            return _text(403, "Error 403")

        who = principals.parse(req.headers.get(principals.HEADER))
        if who is None or who.tid != CONSUMER_TENANT:
            log.warning("refused: %s principal", "no" if who is None else "wrong-tenant")
            return _text(403, "Error 403")
        try:
            settings = self._settings.get()
        except SettingsUnavailable as exc:
            log.error("settings unavailable (%s): everyone is refused", exc)
            return _text(503, "Not available right now")
        access = settings.access
        allowed = who.oid in access.allowed

        if path == "/enrol":
            if allowed or access.enrolment_active(self._now()):
                return _text(200, f"Your account ID: {who.oid}\nSend it to the administrator.")
            return _text(403, "Error 403")
        if not allowed:
            log.warning("refused: %s not on the allowlist", who.log_id())
            return _text(403, "Error 403")

        if path in ("/admin/consent", "/admin/consent/callback"):
            return self._consent_route(req, who, access.admins, settings.config.expected_account)
        if path in self._static:
            body, ctype = self._static[path]
            return Response(200, body, ctype, {"Cache-Control": "no-cache"})
        if path == "/api/events":
            body, etag = self._events.get()
            if req.headers.get("if-none-match") == etag:
                return Response(304, headers={"ETag": etag})
            return Response(200, body, JSON, {"ETag": etag})
        if path == "/api/settings":
            return Response(200, self._settings_json(settings.config), JSON)
        if path == "/api/photos":
            return Response(200, b'{"photos":[]}', JSON)  # photos stay on the wall
        if path == "/api/health":
            return Response(200, self._health(), JSON)
        return _text(404, "Error 404")

    @staticmethod
    def _fetch_allowed(headers: dict[str, str], path: str) -> bool:
        """Fetch Metadata resource isolation: requests from other sites are
        allowed only as top-level page navigations (for example the return
        from Microsoft sign-in); never for /api/*. Old browsers send nothing."""
        site = headers.get("sec-fetch-site")
        if site in (None, "same-origin", "none"):
            return True
        return (path in PAGES and headers.get("sec-fetch-mode") == "navigate"
                and headers.get("sec-fetch-dest") == "document")

    def _consent_route(self, req: Request, who, admins: frozenset[str], viewer: str) -> Response:
        if who.oid not in admins or self._consent is None:
            log.warning("refused: %s is not an admin", who.log_id())
            return _text(403, "Error 403")
        host = req.headers["host"].lower()
        if req.path == "/admin/consent":
            return Response(302, b"", TEXT, {"Location": self._consent.start(who, host, viewer)})
        try:
            account = self._consent.finish(who, host, req.query, viewer)
        except ConsentError as exc:
            return _text(400, str(exc))
        return _text(200, f"Connected as {account}. The calendar refreshes within 5 minutes.")

    @staticmethod
    def _settings_json(cfg) -> bytes:
        d = cfg.display
        return json.dumps({
            "clock": d.clock, "weekStart": d.week_start, "showNotes": d.show_notes,
            "idleSeconds": d.idle_seconds, "photoIntervalSeconds": d.photo_interval_seconds,
            "nightDim": [], "mock": False, "debugNow": None,
        }, separators=(",", ":")).encode("ascii")

    def _health(self) -> bytes:
        """Sync freshness and status, without event content (§17.3)."""
        body, _ = self._events.get()
        data = json.loads(body)
        generated = data.get("generatedAt")
        age = None
        if isinstance(generated, str):
            age = int((self._now() - datetime.strptime(generated, "%Y-%m-%dT%H:%M:%SZ")
                       .replace(tzinfo=timezone.utc)).total_seconds())
        cals = [{"key": c["key"], "status": c["status"]} for c in data.get("calendars", [])]
        if data.get("error") or age is None:
            status = "no_data"
        elif data.get("auth") != "ok" or any(c["status"] == "error" for c in cals):
            status = "degraded"
        else:
            status = "ok" if age <= 600 and all(c["status"] == "ok" for c in cals) else "stale"
        return json.dumps({"status": status, "syncAgeSeconds": age, "auth": data.get("auth"), "calendars": cals},
                          separators=(",", ":")).encode("ascii")
