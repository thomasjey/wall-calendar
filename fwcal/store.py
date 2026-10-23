"""events.json: atomic writes (sync side) and strict validation (web side).
DESIGN §5.3, §6."""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
from pathlib import Path

from . import textclean
from .config import COLOR_RE, KEY_RE

SCHEMA = 1
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_EVENTS = 20_000

_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_AUTH = frozenset({"ok", "reauth_required", "not_configured"})
_CAL_STATUS = frozenset({"ok", "stale", "error"})
_SOURCES = frozenset({"graph", "mock"})


class InvalidEventsFile(ValueError):
    pass


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    """Writes via a temp file in the same directory, created with `mode` from the
    start (no chmod window), then fsync and os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, mode)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    if sys.platform != "win32":
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)


def write_events(path: Path, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    atomic_write(path, data, 0o640)


def _s(obj: dict, key: str, limit: int) -> str:
    value = obj.get(key, "")
    if not isinstance(value, str) or len(value) > limit:
        raise InvalidEventsFile(f"{key}: bad string")
    return value


def validate(payload: object) -> dict:
    """Rebuilds the payload from known fields only. Anything unexpected in a
    calendar is an error; a bad event is dropped."""
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise InvalidEventsFile("schema")
    if payload.get("source") not in _SOURCES or payload.get("auth") not in _AUTH:
        raise InvalidEventsFile("source/auth")
    window = payload.get("window")
    if not isinstance(window, dict) or not all(
        isinstance(window.get(k), str) and _DATE_RE.match(window[k]) for k in ("start", "end")
    ):
        raise InvalidEventsFile("window")
    generated = payload.get("generatedAt")
    if not isinstance(generated, str) or not _UTC_RE.match(generated):
        raise InvalidEventsFile("generatedAt")

    cals = payload.get("calendars")
    if not isinstance(cals, list) or len(cals) > 50:
        raise InvalidEventsFile("calendars")
    calendars = []
    for c in cals:
        if not isinstance(c, dict):
            raise InvalidEventsFile("calendar")
        key, color = c.get("key"), c.get("color")
        last = c.get("lastSuccessAt")
        if not (isinstance(key, str) and KEY_RE.match(key)):
            raise InvalidEventsFile("calendar key")
        if not (isinstance(color, str) and COLOR_RE.match(color)):
            raise InvalidEventsFile("calendar color")
        if c.get("status") not in _CAL_STATUS or not isinstance(c.get("truncated"), bool):
            raise InvalidEventsFile("calendar status")
        if last is not None and not (isinstance(last, str) and _UTC_RE.match(last)):
            raise InvalidEventsFile("calendar lastSuccessAt")
        calendars.append(
            {"key": key, "name": _s(c, "name", 40), "color": color, "status": c["status"],
             "lastSuccessAt": last, "truncated": c["truncated"]}
        )
    keys = {c["key"] for c in calendars}

    evs = payload.get("events")
    if not isinstance(evs, list) or len(evs) > MAX_EVENTS:
        raise InvalidEventsFile("events")
    events = []
    for e in evs:
        try:
            events.append(_validate_event(e, keys))
        except InvalidEventsFile:
            continue
    return {
        "schema": SCHEMA, "source": payload["source"], "generatedAt": generated,
        "auth": payload["auth"], "window": {"start": window["start"], "end": window["end"]},
        "calendars": calendars, "events": events,
    }


def _validate_event(e: object, keys: set[str]) -> dict:
    if not isinstance(e, dict):
        raise InvalidEventsFile("event")
    if not (isinstance(e.get("id"), str) and _ID_RE.match(e["id"])) or e.get("cal") not in keys:
        raise InvalidEventsFile("event id/cal")
    if not isinstance(e.get("private"), bool) or not isinstance(e.get("allDay"), bool):
        raise InvalidEventsFile("event flags")
    out = {
        "id": e["id"], "cal": e["cal"],
        "title": _s(e, "title", textclean.TITLE_MAX),
        "location": _s(e, "location", textclean.LOCATION_MAX),
        "notes": _s(e, "notes", textclean.NOTES_MAX),
        "private": e["private"], "allDay": e["allDay"],
    }
    if e["allDay"]:
        for k in ("startDate", "endDate"):
            if not (isinstance(e.get(k), str) and _DATE_RE.match(e[k])):
                raise InvalidEventsFile("event date")
            out[k] = e[k]
    else:
        for k in ("start", "end"):
            if not (isinstance(e.get(k), str) and _UTC_RE.match(e[k])):
                raise InvalidEventsFile("event time")
            out[k] = e[k]
    return out


def load_events(path: Path) -> dict:
    """Validated payload. Raises InvalidEventsFile or OSError."""
    with path.open("rb") as f:
        raw = f.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise InvalidEventsFile("too large")
    try:
        payload = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise InvalidEventsFile("not JSON") from exc
    return validate(payload)
