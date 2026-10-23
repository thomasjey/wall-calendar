"""The sync job (DESIGN §5.3): fetch each configured calendar, normalise, merge
with the last good data, and write events.json atomically.

Exit codes: 0 all calendars fresh; 1 at least one calendar failed; 2 config
problem; 3 sign-in needed. Logs carry counts and codes, never event content.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

from . import netauth, paths, store
from .config import Config, ConfigError
from .graph import Graph, GraphError
from .normalize import InvalidEvent, normalize_event
from .window import sync_window, utc_query_range

log = logging.getLogger("fwcal.sync")

OK, PARTIAL, CONFIG, REAUTH = 0, 1, 2, 3
_FMT = "%Y-%m-%dT%H:%M:%SZ"


def local_token(cfg: Config, session) -> str:
    """The Pi and laptop sign-in (MSAL). Imported here so the cloud never loads MSAL (ADR-30)."""
    from . import auth

    return auth.access_token(cfg, session)


def check_config(cfg: Config) -> None:
    if not cfg.calendars:
        raise ConfigError("no [[calendars]] configured (run `fwcal calendars`)")
    missing = [c.key for c in cfg.calendars if not c.graph_id]
    if missing:
        raise ConfigError(f"calendars without graph_id: {missing}")


def run(cfg: Config, *, session=None, token_fn=local_token, now: datetime | None = None,
        events_path: Path | None = None, events=None, sleep=time.sleep) -> int:
    """events: where the payload is kept (load/save); by default the local file."""
    try:
        check_config(cfg)
    except ConfigError as exc:
        log.error("%s", exc)
        return CONFIG
    events_store = events or store.FileEventStore(events_path or paths.events_path(mock=False))
    now = now or datetime.now().astimezone()
    now_utc = now.astimezone(UTC)
    start, end = sync_window(now.date(), cfg.lookahead_days, cfg.display.week_start)
    q_start, q_end = utc_query_range(start, end)

    previous = events_store.load()
    prev_cals = {c["key"]: c for c in (previous or {}).get("calendars", [])}
    prev_events: dict[str, list[dict]] = {}
    for e in (previous or {}).get("events", []):
        prev_events.setdefault(e["cal"], []).append(e)

    session = session or netauth.http_session()
    auth_state = "ok"
    graph = None
    try:
        graph = Graph(session, token_fn(cfg, session), sleep=sleep)
    except netauth.ReauthRequired as exc:
        log.warning("sign-in needed: %s", exc)
        auth_state = "reauth_required"
    except (netauth.AuthError, requests.RequestException) as exc:
        log.warning("could not get a token: %s", type(exc).__name__)
        auth_state = (previous or {}).get("auth", "ok")

    calendars, events, failed = [], [], 0
    for cal in cfg.calendars:
        prev = prev_cals.get(cal.key, {})
        entry = {"key": cal.key, "name": cal.name, "color": cal.color, "status": "ok",
                 "lastSuccessAt": now_utc.strftime(_FMT), "truncated": False}
        try:
            if graph is None:
                raise GraphError("no token")
            t0 = time.monotonic()
            raw, truncated = graph.calendar_view(cal.graph_id, q_start, q_end, cal.detail)
            kept, invalid = [], 0
            for ev in raw:
                try:
                    out = normalize_event(ev, cal.key, show_notes=cfg.display.show_notes, detail=cal.detail)
                except InvalidEvent:
                    invalid += 1
                    continue
                if out is not None:
                    kept.append(out)
            events += kept
            entry["truncated"] = truncated
            log.info("calendar %s: %d events (%d skipped as invalid)%s in %.1fs", cal.key, len(kept), invalid,
                     ", truncated" if truncated else "", time.monotonic() - t0)
        except (GraphError, requests.RequestException) as exc:
            failed += 1
            lost = isinstance(exc, GraphError) and exc.access_lost
            log.warning("calendar %s: %s%s", cal.key, exc if isinstance(exc, GraphError) else type(exc).__name__,
                        " (share removed? its events are dropped)" if lost else "")
            entry["lastSuccessAt"] = prev.get("lastSuccessAt")
            entry["status"] = "error" if lost or not entry["lastSuccessAt"] else "stale"
            if not lost:
                events += prev_events.get(cal.key, [])  # keep the last good data through outages
        calendars.append(entry)

    payload = {"schema": store.SCHEMA, "source": "graph", "generatedAt": now_utc.strftime(_FMT),
               "auth": auth_state, "window": {"start": start.isoformat(), "end": end.isoformat()},
               "calendars": calendars, "events": events}
    events_store.save(store.validate(payload))
    if auth_state == "reauth_required":
        return REAUTH
    return PARTIAL if failed else OK
