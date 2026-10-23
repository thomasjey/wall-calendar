"""Load test for the away-from-home service (DESIGN §17.6), run against dev.

    python tools/loadtest.py <host> [--paths /api/events,...] [--steps 4,8,16,32,64] [--seconds 60]

Signed in: asks for the value of the AppServiceAuthSession cookie at a hidden
prompt (copy it from the browser's developer tools after signing in to dev).
It stays in memory only: never printed, logged, stored or put on the command
line. Sign out of dev afterwards so the session ends. --anonymous sends no
cookie (only the sign-in layer answers).

Each step holds N keep-alive connections busy for --seconds and prints
requests per second, latency percentiles and the status codes seen. Response
bodies are read and discarded, never printed. Standard library only.
"""

from __future__ import annotations

import argparse
import getpass
import http.client
import re
import sys
import threading
import time
from collections import Counter

COOKIE = "AppServiceAuthSession"
USER_AGENT = "fwcal-loadtest"
# A browser's fetch from the page itself (the app checks Fetch Metadata).
FETCH_HEADERS = {"Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}


def _headers(cookie: str | None) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT, **FETCH_HEADERS}
    if cookie:
        headers["Cookie"] = f"{COOKIE}={cookie}"
    return headers


def _one(host: str, path: str, headers: dict[str, str]) -> int:
    conn = http.client.HTTPSConnection(host, timeout=30)
    try:
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        resp.read()
        return resp.status
    finally:
        conn.close()


def _worker(host: str, paths: list[str], headers: dict[str, str], deadline: float,
            codes: Counter, times: list[float], lock: threading.Lock) -> None:
    mine_codes, mine_times = Counter(), []
    conn, i = None, 0
    while time.monotonic() < deadline:
        path = paths[i % len(paths)]
        i += 1
        t0 = time.monotonic()
        try:
            if conn is None:
                conn = http.client.HTTPSConnection(host, timeout=30)
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            resp.read()
            mine_codes[resp.status] += 1
            if resp.getheader("Connection", "").lower() == "close":
                conn.close()
                conn = None
        except (OSError, http.client.HTTPException) as exc:  # count it and reconnect; print no details
            mine_codes[type(exc).__name__] += 1
            if conn is not None:
                conn.close()
            conn = None
        mine_times.append(time.monotonic() - t0)
    if conn is not None:
        conn.close()
    with lock:
        codes.update(mine_codes)
        times.extend(mine_times)


def _pct(sorted_times: list[float], p: float) -> float:
    if not sorted_times:
        return 0.0
    return sorted_times[min(len(sorted_times) - 1, int(len(sorted_times) * p))] * 1000


def run_step(host: str, paths: list[str], headers: dict[str, str], workers: int, seconds: float) -> dict:
    codes, times, lock = Counter(), [], threading.Lock()
    start = time.monotonic()
    deadline = start + seconds
    threads = [threading.Thread(target=_worker, args=(host, paths, headers, deadline, codes, times, lock))
               for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - start
    times.sort()
    return {"workers": workers, "requests": len(times), "rps": len(times) / elapsed,
            "p50": _pct(times, 0.50), "p95": _pct(times, 0.95), "p99": _pct(times, 0.99),
            "max": times[-1] * 1000 if times else 0.0, "codes": dict(codes)}


def _read_cookie() -> str:
    value = getpass.getpass(f"{COOKIE} cookie value (hidden): ").strip()
    if value.startswith(COOKIE + "="):
        value = value[len(COOKIE) + 1:]
    if not re.fullmatch(r"[A-Za-z0-9+/=_.%-]{20,8192}", value):
        raise SystemExit("that doesn't look like a session cookie value; nothing was sent")
    return value


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("host", help="the dev host name, e.g. <app>.azurewebsites.net")
    ap.add_argument("--paths", default="/api/events", help="comma-separated paths, used in turn")
    ap.add_argument("--steps", default="4,8,16,32,64", help="comma-separated connection counts")
    ap.add_argument("--seconds", type=float, default=60, help="length of each step")
    ap.add_argument("--anonymous", action="store_true", help="send no cookie")
    args = ap.parse_args(argv)

    if "prod" in args.host.lower():
        raise SystemExit("refusing to load-test a production host; use dev")
    paths = [p.strip() for p in args.paths.split(",") if p.strip()]
    if not paths or any(not p.startswith("/") for p in paths):
        raise SystemExit("--paths must be paths starting with /")
    steps = [int(s) for s in args.steps.split(",")]
    if any(not 1 <= s <= 128 for s in steps):
        raise SystemExit("--steps must be between 1 and 128 connections")

    headers = _headers(None if args.anonymous else _read_cookie())
    if not args.anonymous:
        status = _one(args.host, "/api/health", headers)
        if status != 200:
            raise SystemExit(f"/api/health answered {status}: the cookie wasn't accepted (signed in to dev?)")

    print(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {args.host} "
          f"{'anonymous' if args.anonymous else 'signed in'}, paths {','.join(paths)}, {args.seconds:.0f} s per step")
    print(f"{'conns':>5} {'requests':>8} {'req/s':>7} {'p50 ms':>7} {'p95 ms':>7} {'p99 ms':>7} {'max ms':>7}  codes")
    for workers in steps:
        r = run_step(args.host, paths, headers, workers, args.seconds)
        print(f"{r['workers']:>5} {r['requests']:>8} {r['rps']:>7.0f} {r['p50']:>7.0f} {r['p95']:>7.0f} "
              f"{r['p99']:>7.0f} {r['max']:>7.0f}  {r['codes']}", flush=True)
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} done. Sign out of dev to end the session.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
