"""Command line: `python -m fwcal <command>`.

The Microsoft modules (auth, graph, sync) are imported only by the commands
that need them, so mock mode and the web server never load MSAL.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import threading
import time
import tomllib
from datetime import datetime, timedelta
from pathlib import Path

from . import config as config_mod
from . import paths, store, textclean
from .server import App, PhotoIndex, adopt_socket, load_static, make_server, systemd_socket_fd

log = logging.getLogger("fwcal")
MOCK_REFRESH_SECONDS = 300
SYNC_SECONDS = 300
SUGGESTED_COLORS = ("#7FB3FF", "#5DCAA5", "#ED93B1", "#EF9F27", "#AFA9EC", "#F0997B", "#97C459")


def _load_config(arg: str | None, *, mock: bool) -> config_mod.Config:
    path = Path(arg) if arg else paths.default_config_path()
    if path.exists():
        return config_mod.load(path)
    if arg or not mock:
        raise config_mod.ConfigError(f"config file not found: {path}")
    log.info("no config file; mock mode uses defaults")
    return config_mod.Config()


def _clock(now_arg: str | None):
    """Real local time, or a fixed starting point that then runs forward
    (mock testing only)."""
    if not now_arg:
        return lambda: datetime.now().astimezone()
    start = datetime.fromisoformat(now_arg)
    start = start.astimezone() if start.tzinfo is None else start
    t0 = time.monotonic()
    return lambda: start + timedelta(seconds=time.monotonic() - t0)


def _mock_loop(cfg: config_mod.Config, now, status: str, stop: threading.Event) -> None:
    from . import mock  # imported only in mock mode

    while True:
        try:
            store.write_events(paths.events_path(mock=True), mock.build_payload(now(), cfg, status))
        except OSError as exc:
            # On Windows the replace fails if the server is reading the file at
            # that moment; keep the previous file and try again next cycle.
            log.warning("mock refresh failed: %s", type(exc).__name__)
        if stop.wait(MOCK_REFRESH_SECONDS):
            return


def _sync_loop(cfg: config_mod.Config, stop: threading.Event) -> None:
    from . import sync  # needs MSAL; laptop development only (the Pi uses a systemd timer)

    while True:
        try:
            sync.run(cfg)
        except Exception:  # keep the loop alive; the next cycle retries
            log.exception("sync failed")
        if stop.wait(SYNC_SECONDS):
            return


def cmd_serve(args: argparse.Namespace) -> int:
    mock = args.mock
    if args.now and not mock:
        raise SystemExit("--now is only allowed with --mock")
    cfg = _load_config(args.config, mock=mock)
    now = _clock(args.now) if mock else None
    photo_dir = cfg.photo_dir
    stop = threading.Event()
    if mock:
        if photo_dir is None:
            from . import samplephotos
            photo_dir = samplephotos.ensure(paths.state_dir(mock=True) / "photos")
        threading.Thread(target=_mock_loop, args=(cfg, now, args.mock_status, stop), daemon=True).start()
        time.sleep(0.2)  # first events file
    elif args.command == "dev":
        threading.Thread(target=_sync_loop, args=(cfg, stop), daemon=True).start()

    app = App(
        config=cfg,
        events_path=paths.events_path(mock=mock),
        static=load_static(paths.STATIC_DIR, include_tests=mock),
        photos=PhotoIndex(photo_dir),
        mock=mock,
        debug_now=now if args.now else None,
    )
    port = args.port if args.port is not None else cfg.port
    fd = systemd_socket_fd()
    server = make_server(app, port, inherited=adopt_socket(fd) if fd is not None else None)
    if fd is not None and server.server_address[1] != cfg.port:
        log.warning("systemd socket port %d differs from configured port %d", server.server_address[1], cfg.port)
    host, bound = server.server_address[:2]
    log.info("serving on http://%s:%d/%s", host, bound, " (mock data)" if mock else "")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from . import check

    return check.run(args.config)


def cmd_auth(args: argparse.Namespace) -> int:
    from . import auth, tokencache

    cfg = _load_config(args.config, mock=False)
    try:
        return _auth(args, cfg, auth)
    except tokencache.InsecureCache as exc:
        print(f"refusing to use the token cache: {exc}")
        return 1


def _auth(args: argparse.Namespace, cfg: config_mod.Config, auth) -> int:
    if args.action == "status":
        print("\n".join(auth.status(cfg)))
        return 0
    if args.action == "logout":
        print("sign-in removed" if auth.logout() else "no saved sign-in")
        return 0
    paste = args.paste or (sys.platform.startswith("linux") and not _has_display())
    try:
        account = auth.login(cfg, paste=paste)
    except auth.AuthError as exc:
        print(f"sign-in refused: {exc}")
        return 1
    print(f"signed in as {account}; sign-in saved")
    return 0


def _has_display() -> bool:
    import os

    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "calendar"


def cmd_calendars(args: argparse.Namespace) -> int:
    from . import auth
    from .graph import Graph, GraphError

    cfg = _load_config(args.config, mock=False)
    session = auth.http_session()
    try:
        cals = Graph(session, auth.access_token(cfg, session)).calendars()
    except auth.ReauthRequired as exc:
        print(f"sign-in needed ({exc}): run `fwcal auth login`")
        return 3
    except GraphError as exc:
        print(f"could not list calendars: {exc}")
        return 1
    configured = {c.graph_id: c.key for c in cfg.calendars}
    shared = []
    print(f"{len(cals)} calendar(s) visible to the viewer account:")
    for c in cals:
        owner = (c.get("owner") or {}).get("address", "")
        own = owner.lower() == cfg.expected_account.lower()
        flags = [f"configured as '{configured[c['id']]}'"] if c["id"] in configured else []
        if c.get("canEdit") and not own:
            flags.append("WARNING: shared with edit rights; share it as 'Can view'")
        # Names come from the calendar owner: cleaned so they can't carry terminal escape codes.
        print(f"  - {textclean.clean_line(c.get('name'), 80)!r} "
              f"owner={'viewer (own)' if own else textclean.clean_line(owner, 120)} canEdit={c.get('canEdit')}"
              + (f"  [{'; '.join(flags)}]" if flags else ""))
        if not own:
            shared.append(c)
    new = [c for c in shared if c["id"] not in configured]
    if not new:
        return 0
    if not args.add:
        print(f"\n{len(new)} shared calendar(s) not in the config yet; `fwcal calendars --add` adds them.")
        return 0
    path = Path(args.config) if args.config else paths.default_config_path()
    used = {c.key for c in cfg.calendars}
    blocks = []
    for i, c in enumerate(new, len(cfg.calendars)):
        name = textclean.clean_line(c.get("name"), 40) or "Calendar"
        key = _slug(name)
        while key in used:
            key = f"{key[:28]}-{i}"
        used.add(key)
        blocks.append(calendar_block(key, name, SUGGESTED_COLORS[i % len(SUGGESTED_COLORS)], c["id"],
                                     _ask_detail(name)))
    text = path.read_text(encoding="utf-8")
    config_mod.parse(tomllib.loads(text + "".join(blocks)))  # validate before writing
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write("".join(blocks))
    print(f"added {len(blocks)} calendar(s) to {path}")
    return 0


def calendar_block(key: str, name: str, color: str, graph_id: str, detail: str) -> str:
    """A [[calendars]] TOML table. Values are written as quoted, escaped strings
    (json.dumps without ASCII escaping; inputs already cleaned of control,
    format and surrogate characters), so a name can't break out of its string."""
    def q(v: str) -> str:
        return json.dumps(textclean.clean_line(v, 512), ensure_ascii=False)

    lines = ["", "[[calendars]]", f"key = {q(key)}", f"name = {q(name)}", f"color = {q(color)}",
             f"graph_id = {q(graph_id)}", f"detail = {q(detail)}"]
    return "\n".join(lines) + "\n"


def _ask_detail(name: str, read_line=input) -> str:
    """How much of each event to show. Defaults to the private choice."""
    while True:
        answer = read_line(f"Detail for {name!r}: full / titles / busy [titles]: ").strip().lower() or "titles"
        if answer in config_mod.DETAIL_LEVELS:
            return answer
        print("  please answer full, titles or busy")


def cmd_sync(args: argparse.Namespace) -> int:
    from . import sync

    cfg = _load_config(args.config, mock=False)
    if not args.loop:
        return sync.run(cfg)
    stop = threading.Event()
    try:
        _sync_loop(cfg, stop)
    except KeyboardInterrupt:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="fwcal", description="Wall calendar (see DESIGN.md)")
    sub = p.add_subparsers(dest="command", required=True)
    for name, help_text in (("serve", "run the web server"),
                            ("dev", "laptop development: web server plus the sync loop (or mock data)")):
        s = sub.add_parser(name, help=help_text)
        s.add_argument("--mock", action="store_true", help="use generated mock data; no credentials or network")
        s.add_argument("--config", help="config file (default: platform location)")
        s.add_argument("--port", type=int, help="override the configured port")
        s.add_argument("--now", help="mock only: start the clock at this local time, e.g. 2026-12-31T23:30")
        s.add_argument("--mock-status", choices=("fresh", "stale", "offline", "reauth"), default="fresh",
                       help="mock only: simulate a sync state")
        s.set_defaults(func=cmd_serve)
    a = sub.add_parser("auth", help="sign in, check or remove the viewer account's sign-in")
    a.add_argument("action", choices=("login", "status", "logout"))
    a.add_argument("--paste", action="store_true",
                   help="sign in from another computer's browser and paste the result back (default on a headless Pi)")
    a.add_argument("--config", help="config file (default: platform location)")
    a.set_defaults(func=cmd_auth)
    cl = sub.add_parser("calendars", help="list the calendars the viewer account can see")
    cl.add_argument("--add", action="store_true",
                    help="append shared calendars missing from the config (asks the detail level for each)")
    cl.add_argument("--config", help="config file (default: platform location)")
    cl.set_defaults(func=cmd_calendars)
    sy = sub.add_parser("sync", help="fetch calendars once and write events.json (the Pi runs this from a timer)")
    sy.add_argument("--loop", action="store_true", help="repeat every 5 minutes (development)")
    sy.add_argument("--config", help="config file (default: platform location)")
    sy.set_defaults(func=cmd_sync)
    c = sub.add_parser("check", help="verify file permissions, listening ports and data freshness")
    c.add_argument("--config", help="config file (default: platform location)")
    c.set_defaults(func=cmd_check)
    args = p.parse_args(argv)
    try:
        return args.func(args)
    except config_mod.ConfigError as exc:
        log.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
