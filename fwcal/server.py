"""The loopback web server (DESIGN §8.1, ADR-6).

Serves a fixed set of static files read at startup, the validated events
file, display settings and the photo folder. It never holds a token.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import store
from .config import Config

log = logging.getLogger("fwcal.web")

BIND = "127.0.0.1"
MAX_REQUEST_HEAD = 8192
MAX_PHOTO_BYTES = 25 * 1024 * 1024
PHOTO_RESCAN_SECONDS = 600

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'; require-trusted-types-for 'script'; trusted-types 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), "
        "microphone=(), payment=(), usb=(), serial=(), hid=(), bluetooth=(), "
        "midi=(), display-capture=(), clipboard-read=(), clipboard-write=()"
    ),
}
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".woff2": "font/woff2",
}
PHOTO_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
_PHOTO_MAGIC = {
    "image/jpeg": lambda b: b[:3] == b"\xff\xd8\xff",
    "image/png": lambda b: b[:8] == b"\x89PNG\r\n\x1a\n",
    "image/webp": lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP",
}
NO_DATA = {"schema": 1, "error": "no_data", "auth": "not_configured", "calendars": [], "events": []}


def load_static(static_dir: Path, *, include_tests: bool) -> dict[str, tuple[bytes, str]]:
    """URL path -> (bytes, content type), read once. Request paths are only ever
    looked up in this table, never joined to a filesystem path."""
    table: dict[str, tuple[bytes, str]] = {}
    for path in sorted(static_dir.rglob("*")):
        rel = path.relative_to(static_dir).as_posix()
        ctype = STATIC_TYPES.get(path.suffix.lower())
        if ctype is None or path.is_symlink() or not path.is_file():
            continue
        if rel.startswith("tests/") and not include_tests:
            continue
        table["/" + rel] = (path.read_bytes(), ctype)
    if "/index.html" in table:
        table["/"] = table.pop("/index.html")
    return table


class PhotoIndex:
    """Opaque photo IDs for the files directly inside one folder."""

    def __init__(self, folder: Path | None) -> None:
        self._folder = folder
        self._lock = threading.Lock()
        self._items: dict[str, tuple[Path, str]] = {}
        self._scanned = 0.0

    def _scan(self) -> None:
        items: dict[str, tuple[Path, str]] = {}
        if self._folder is not None:
            try:
                entries = list(os.scandir(self._folder))
            except OSError:
                entries = []
            for entry in entries:
                ctype = PHOTO_TYPES.get(os.path.splitext(entry.name)[1].lower())
                try:
                    if ctype is None or entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                        continue
                    if entry.stat(follow_symlinks=False).st_size > MAX_PHOTO_BYTES:
                        continue
                except OSError:
                    continue
                pid = hashlib.sha256(entry.name.encode("utf-8", "surrogatepass")).hexdigest()[:16]
                items[pid] = (Path(entry.path), ctype)
        self._items, self._scanned = items, time.monotonic()

    def ids(self) -> list[str]:
        with self._lock:
            if not self._scanned or time.monotonic() - self._scanned > PHOTO_RESCAN_SECONDS:
                self._scan()
            return sorted(self._items)

    def read(self, pid: str) -> tuple[bytes, str] | None:
        with self._lock:
            item = self._items.get(pid)
        if item is None:
            return None
        path, ctype = item
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb") as f:
                data = f.read(MAX_PHOTO_BYTES + 1)
        except OSError:
            return None
        if len(data) > MAX_PHOTO_BYTES or not _PHOTO_MAGIC[ctype](data):
            return None
        return data, ctype


@dataclass
class App:
    config: Config
    events_path: Path
    static: dict[str, tuple[bytes, str]]
    photos: PhotoIndex
    mock: bool = False
    debug_now: Callable[[], datetime] | None = None
    allowed_hosts: frozenset[str] = field(default_factory=frozenset)
    _events_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _events_cache: tuple | None = field(default=None, repr=False)

    def events_json(self) -> tuple[bytes, str]:
        """The validated events as JSON and its ETag. Re-read and re-validated
        only when the file changes (the sync replaces it atomically)."""
        try:
            st = os.stat(self.events_path)
            key = (st.st_mtime_ns, st.st_size, st.st_ino)
        except OSError:
            key = None
        with self._events_lock:
            if key is not None and self._events_cache and self._events_cache[0] == key:
                return self._events_cache[1], self._events_cache[2]
            try:
                payload = store.load_events(self.events_path)
            except (OSError, store.InvalidEventsFile) as exc:
                log.warning("events file unavailable: %s", type(exc).__name__)
                payload, key = NO_DATA, None
            body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
            etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
            self._events_cache = (key, body, etag) if key is not None else None
            return body, etag

    def settings_json(self) -> bytes:
        d = self.config.display
        now = self.debug_now() if self.debug_now else None
        body = {
            "clock": d.clock, "weekStart": d.week_start, "showNotes": d.show_notes,
            "idleSeconds": d.idle_seconds, "photoIntervalSeconds": d.photo_interval_seconds,
            "nightDim": list(d.night_dim), "location": list(d.location) if d.location else None, "mock": self.mock,
            "debugNow": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if now else None,
        }
        return json.dumps(body, separators=(",", ":")).encode("ascii")

    def photos_json(self) -> bytes:
        return json.dumps({"photos": [f"/photos/{p}" for p in self.photos.ids()]}).encode("ascii")


class Handler(BaseHTTPRequestHandler):
    server_version = "fwcal"
    timeout = 5  # seconds per socket operation; slow clients are dropped
    app: App  # set on the subclass made by make_server

    def version_string(self) -> str:
        return self.server_version  # no Python version in the Server header

    def do_GET(self) -> None:
        self._dispatch(head=False)

    def do_HEAD(self) -> None:
        self._dispatch(head=True)

    def _not_allowed(self) -> None:
        self._send(405, b"Method not allowed\n", "text/plain; charset=utf-8", extra={"Allow": "GET, HEAD"})

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _not_allowed

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        # Replaces the stdlib HTML error page with a fixed short text.
        self.close_connection = True
        self._send(code, f"Error {code}\n".encode(), "text/plain; charset=utf-8")

    def _dispatch(self, head: bool) -> None:
        head_size = len(self.requestline) + sum(len(k) + len(v) + 4 for k, v in self.headers.items())
        if head_size > MAX_REQUEST_HEAD:
            return self.send_error(431)
        if self.headers.get("Host", "") not in self.app.allowed_hosts:
            return self.send_error(421)
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None and site not in ("same-origin", "none"):
            return self.send_error(403)
        path = self.path
        if not path.startswith("/") or "?" in path or "#" in path:
            return self.send_error(400)

        app = self.app
        if path in app.static:
            body, ctype = app.static[path]
            return self._send(200, body, ctype, cache="no-cache", head=head)
        if path == "/api/events":
            body, etag = app.events_json()
            if self.headers.get("If-None-Match") == etag:
                return self._send(304, b"", "application/json", head=True, extra={"ETag": etag})
            return self._send(200, body, "application/json", head=head, extra={"ETag": etag})
        if path == "/api/settings":
            return self._send(200, app.settings_json(), "application/json", head=head)
        if path == "/api/photos":
            return self._send(200, app.photos_json(), "application/json", head=head)
        if path.startswith("/photos/"):
            photo = app.photos.read(path[len("/photos/"):])
            if photo is not None:
                return self._send(200, photo[0], photo[1], cache="private, max-age=3600", head=head)
        return self.send_error(404)

    def _send(self, code: int, body: bytes, ctype: str, *, cache: str = "no-store",
              head: bool | None = None, extra: dict[str, str] | None = None) -> None:
        if head is None:
            head = self.command == "HEAD"
        self.send_response(code)
        if code != 304:  # a 304 carries no body and no length
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        for k, v in {**SECURITY_HEADERS, **(extra or {})}.items():
            self.send_header(k, v)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        msg = (format % args).encode("ascii", "backslashreplace").decode("ascii")
        log.info("%s", msg.replace("\n", "\\n")[:300])


class LoopbackServer(ThreadingHTTPServer):
    daemon_threads = True
    # SO_REUSEADDR on Windows would let another process bind the same port.
    allow_reuse_address = False

    def server_bind(self) -> None:
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


SYSTEMD_FIRST_FD = 3


def systemd_socket_fd() -> int | None:
    """The listening socket passed by systemd socket activation, if any (the
    one environment input this program reads; DESIGN §9.1). The variables are
    removed so child processes don't inherit them."""
    pid, fds = os.environ.pop("LISTEN_PID", None), os.environ.pop("LISTEN_FDS", None)
    os.environ.pop("LISTEN_FDNAMES", None)
    if pid is None and fds is None:
        return None
    if pid != str(os.getpid()) or fds != "1":
        raise RuntimeError("socket activation: expected exactly one socket for this process")
    return SYSTEMD_FIRST_FD


def adopt_socket(fd: int) -> socket.socket:
    """Wraps an inherited listening socket, refusing anything but TCP on 127.0.0.1."""
    sock = socket.socket(fileno=fd)
    if sock.family != socket.AF_INET or sock.type != socket.SOCK_STREAM or sock.getsockname()[0] != BIND:
        sock.close()
        raise RuntimeError("socket activation: socket must be TCP on 127.0.0.1")
    return sock


def make_server(app: App, port: int, *, inherited: socket.socket | None = None) -> LoopbackServer:
    handler = type("BoundHandler", (Handler,), {"app": app})
    if inherited is None:
        server = LoopbackServer((BIND, port), handler)
    else:
        server = LoopbackServer((BIND, 0), handler, bind_and_activate=False)
        server.socket.close()
        server.socket = inherited
        server.server_address = inherited.getsockname()
    bound = server.server_address[1]
    app.allowed_hosts = frozenset({f"127.0.0.1:{bound}", f"localhost:{bound}"})
    return server
