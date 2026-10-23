"""`fwcal check`: a self-check for the Pi (DESIGN §9.3, §11.2).

Run with sudo on the Pi so it can see the token directory. Exit code 1 if any
check fails.
"""

from __future__ import annotations

import os
import socket
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config as config_mod
from . import paths, store

OK, WARN, FAIL = "OK", "WARN", "FAIL"
SSH_PORT = 22
DHCP_CLIENT_PORTS = frozenset({68, 546})
STALE_MINUTES = 60


# ----- listening sockets (Linux /proc/net) -----

def _decode_addr(hex_addr: str) -> str:
    raw = bytes.fromhex(hex_addr)
    if len(raw) == 4:
        return socket.inet_ntop(socket.AF_INET, raw[::-1])
    # IPv6: four 32-bit words, each in host (little-endian) order.
    return socket.inet_ntop(socket.AF_INET6, b"".join(raw[i : i + 4][::-1] for i in range(0, 16, 4)))


def parse_proc_net(text: str, *, udp: bool) -> list[tuple[str, int]]:
    """(address, port) of listening sockets in /proc/net/{tcp,tcp6,udp,udp6}."""
    want = "07" if udp else "0A"  # UDP: unconnected (TCP_CLOSE); TCP: LISTEN
    out = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4 or parts[3] != want:
            continue
        addr, port = parts[1].rsplit(":", 1)
        out.append((_decode_addr(addr), int(port, 16)))
    return out


def _is_loopback(addr: str) -> bool:
    return addr.startswith("127.") or addr == "::1"


def evaluate_listeners(tcp: list[tuple[str, int]], udp: list[tuple[str, int]], web_port: int) -> list[tuple[str, str]]:
    """Only sshd and 127.0.0.1:<web_port> may listen (DESIGN §9.3)."""
    results = []
    for addr, port in sorted(set(tcp)):
        where = f"tcp {addr}:{port}"
        if port == web_port:
            results.append((OK, f"{where} (web)") if addr == "127.0.0.1" else (FAIL, f"{where}: web port not on loopback"))
        elif port == SSH_PORT:
            results.append((OK, f"{where} (ssh)"))
        elif _is_loopback(addr):
            results.append((WARN, f"{where}: unexpected loopback listener"))
        else:
            results.append((FAIL, f"{where}: unexpected network listener"))
    for addr, port in sorted(set(udp)):
        where = f"udp {addr}:{port}"
        if _is_loopback(addr):
            results.append((WARN, f"{where}: loopback listener"))
        elif port in DHCP_CLIENT_PORTS:
            results.append((OK, f"{where} (DHCP client)"))
        else:
            results.append((FAIL, f"{where}: unexpected network listener"))
    if not any(port == web_port and addr == "127.0.0.1" for addr, port in tcp):
        results.append((WARN, f"nothing listening on 127.0.0.1:{web_port}"))
    return results


def _listeners(web_port: int) -> list[tuple[str, str]]:
    if not sys.platform.startswith("linux"):
        return [(WARN, "listening-socket check runs on Linux only")]
    tcp, udp = [], []
    for name, is_udp in (("tcp", False), ("tcp6", False), ("udp", True), ("udp6", True)):
        try:
            text = Path(f"/proc/net/{name}").read_text()
        except OSError:
            continue
        (udp if is_udp else tcp).extend(parse_proc_net(text, udp=is_udp))
    return evaluate_listeners(tcp, udp, web_port)


# ----- file permissions -----

def check_mode(label: str, mode: int, *, forbidden: int) -> tuple[str, str]:
    """`forbidden`: permission bits that must not be set (e.g. 0o077)."""
    bad = stat.S_IMODE(mode) & forbidden
    perms = oct(stat.S_IMODE(mode))
    return (FAIL, f"{label}: mode {perms} grants {oct(bad)}") if bad else (OK, f"{label}: mode {perms}")


def _path_check(label: str, path: Path, forbidden: int, *, required: bool) -> list[tuple[str, str]]:
    try:
        st = path.lstat()
    except FileNotFoundError:
        return [(FAIL if required else WARN, f"{label}: {path} not found")]
    except PermissionError:
        return [(WARN, f"{label}: {path} not readable (run with sudo)")]
    if stat.S_ISLNK(st.st_mode):
        return [(FAIL, f"{label}: {path} is a symlink")]
    return [check_mode(f"{label} {path}", st.st_mode, forbidden=forbidden)]


def _files(cfg_path: Path, cfg: config_mod.Config | None) -> list[tuple[str, str]]:
    if sys.platform == "win32":
        return [(WARN, "POSIX permission checks skipped on Windows")]
    results = _path_check("config", cfg_path, 0o137, required=True)  # at most 0640
    auth = paths.auth_dir()
    results += _path_check("token dir", auth, 0o077, required=False)
    try:
        for f in auth.iterdir():
            results += _path_check("token file", f, 0o177, required=True)  # at most 0600
    except (FileNotFoundError, PermissionError):
        pass
    results += _path_check("data dir", paths.events_path(mock=False).parent, 0o027, required=True)
    if cfg is not None and cfg.photo_dir is not None:
        results += _path_check("photo dir", cfg.photo_dir, 0o022, required=True)
    return results


# ----- data freshness -----

def _data() -> list[tuple[str, str]]:
    path = paths.events_path(mock=False)
    try:
        data = store.load_events(path)
    except FileNotFoundError:
        return [(WARN, f"events: {path} not found (sync hasn't run yet?)")]
    except (OSError, store.InvalidEventsFile) as exc:
        return [(FAIL, f"events: {path} unreadable or invalid ({type(exc).__name__})")]
    results = [(OK, f"events: {len(data['events'])} events, {len(data['calendars'])} calendars")]
    if data["auth"] != "ok":
        results.append((WARN, f"events: auth is {data['auth']} (run `fwcal auth login`)"))
    now = datetime.now(timezone.utc)
    for c in data["calendars"]:
        last = c["lastSuccessAt"]
        age = (now - datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 60 if last else None
        if age is None or age > STALE_MINUTES:
            results.append((WARN, f"calendar {c['key']}: last success {last or 'never'}"))
    return results


def run(config_arg: str | None) -> int:
    cfg_path = Path(config_arg) if config_arg else paths.default_config_path()
    cfg = None
    results: list[tuple[str, str]] = []
    try:
        cfg = config_mod.load(cfg_path)
        results.append((OK, f"config: {cfg_path} ({len(cfg.calendars)} calendars)"))
    except FileNotFoundError:
        results.append((FAIL, f"config: {cfg_path} not found"))
    except (OSError, config_mod.ConfigError) as exc:
        results.append((FAIL, f"config: {exc}"))
    results += _files(cfg_path, cfg)
    results += _listeners(cfg.port if cfg else config_mod.Config().port)
    results += _data()
    for level, text in results:
        print(f"{level:<5} {text}")
    return 1 if any(level == FAIL for level, _ in results) else 0
