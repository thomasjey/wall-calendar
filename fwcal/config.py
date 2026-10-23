"""Configuration (DESIGN §7). Strict: unknown keys and bad values are errors."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
KEY_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
# How much of each event reaches the wall (DESIGN §5.4 rule 7a). Applied by the
# sync job, so hidden fields are never written to disk.
DETAIL_LEVELS = ("full", "titles", "busy")
HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Calendar:
    key: str
    name: str
    color: str
    graph_id: str = ""
    detail: str = "full"


@dataclass(frozen=True)
class Display:
    clock: str = "12h"
    week_start: str = "sunday"
    show_notes: bool = True
    idle_seconds: int = 120
    photo_interval_seconds: int = 600
    night_dim: tuple[str, ...] = ("22:00", "06:30")
    # Rough position (one decimal, about 10 km) for sunrise and sunset in the
    # page's sky; None uses fixed hours. Private config only, never the repo.
    location: tuple[float, float] | None = None


@dataclass(frozen=True)
class Config:
    client_id: str = ""
    expected_account: str = ""
    lookahead_days: int = 35
    port: int = 8765
    photo_dir: Path | None = None
    display: Display = field(default_factory=Display)
    calendars: tuple[Calendar, ...] = ()


def _check_keys(table: dict, allowed: set[str], where: str) -> None:
    unknown = set(table) - allowed
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {sorted(unknown)}")


def _get(table: dict, key: str, typ: type | tuple[type, ...], default):
    value = table.get(key, default)
    # bool is an int subclass; never accept it where a number is expected.
    if isinstance(value, bool) and typ is not bool:
        raise ConfigError(f"{key}: wrong type")
    if not isinstance(value, typ):
        raise ConfigError(f"{key}: wrong type")
    return value


def _int_in(table: dict, key: str, default: int, lo: int, hi: int) -> int:
    value = _get(table, key, int, default)
    if not lo <= value <= hi:
        raise ConfigError(f"{key}: must be {lo}..{hi}")
    return value


def parse(data: dict) -> Config:
    _check_keys(
        data,
        {"client_id", "expected_account", "lookahead_days", "port", "photo_dir", "display", "calendars"},
        "config",
    )
    client_id = _get(data, "client_id", str, "")
    if client_id and not _GUID_RE.match(client_id):
        raise ConfigError("client_id: must be a GUID")
    expected = _get(data, "expected_account", str, "")
    if expected and ("@" not in expected or len(expected) > 254):
        raise ConfigError("expected_account: must be an email address")
    photo_dir = _get(data, "photo_dir", str, "")

    d = _get(data, "display", dict, {})
    _check_keys(d, {f for f in Display.__dataclass_fields__}, "display")
    clock = _get(d, "clock", str, "12h")
    week_start = _get(d, "week_start", str, "sunday")
    if clock not in ("12h", "24h"):
        raise ConfigError("display.clock: 12h or 24h")
    if week_start not in ("sunday", "monday"):
        raise ConfigError("display.week_start: sunday or monday")
    night = _get(d, "night_dim", list, ["22:00", "06:30"])
    if night and (len(night) != 2 or not all(isinstance(t, str) and HHMM_RE.match(t) for t in night)):
        raise ConfigError('display.night_dim: ["HH:MM", "HH:MM"] or []')
    location = _get(d, "location", list, [])
    if location and (len(location) != 2
                     or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in location)
                     or not (-90 <= location[0] <= 90 and -180 <= location[1] <= 180)):
        raise ConfigError("display.location: [latitude, longitude] in degrees, or leave it out")
    display = Display(
        clock=clock,
        week_start=week_start,
        show_notes=_get(d, "show_notes", bool, True),
        idle_seconds=_int_in(d, "idle_seconds", 120, 15, 3600),
        photo_interval_seconds=_int_in(d, "photo_interval_seconds", 600, 10, 86400),
        night_dim=tuple(night),
        location=(round(float(location[0]), 1), round(float(location[1]), 1)) if location else None,
    )

    calendars = []
    seen: set[str] = set()
    for i, c in enumerate(_get(data, "calendars", list, [])):
        if not isinstance(c, dict):
            raise ConfigError(f"calendars[{i}]: must be a table")
        _check_keys(c, {"key", "name", "color", "graph_id", "detail"}, f"calendars[{i}]")
        key = _get(c, "key", str, "")
        name = _get(c, "name", str, "")
        color = _get(c, "color", str, "")
        graph_id = _get(c, "graph_id", str, "")
        detail = _get(c, "detail", str, "full")
        if not KEY_RE.match(key) or key in seen:
            raise ConfigError(f"calendars[{i}].key: [a-z0-9_-]{{1,32}}, unique")
        if not 1 <= len(name) <= 40:
            raise ConfigError(f"calendars[{i}].name: 1..40 characters")
        if not COLOR_RE.match(color):
            raise ConfigError(f"calendars[{i}].color: #RRGGBB")
        if len(graph_id) > 512:
            raise ConfigError(f"calendars[{i}].graph_id: too long")
        if detail not in DETAIL_LEVELS:
            raise ConfigError(f"calendars[{i}].detail: one of {', '.join(DETAIL_LEVELS)}")
        seen.add(key)
        calendars.append(Calendar(key, name, color, graph_id, detail))

    return Config(
        client_id=client_id,
        expected_account=expected,
        lookahead_days=_int_in(data, "lookahead_days", 35, 7, 120),
        port=_int_in(data, "port", 8765, 1024, 65535),
        photo_dir=Path(photo_dir) if photo_dir else None,
        display=display,
        calendars=tuple(calendars),
    )


def load(path: Path) -> Config:
    try:
        with path.open("rb") as f:
            return parse(tomllib.load(f))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
