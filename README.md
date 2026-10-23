# wall-calendar

A self-hosted wall calendar: a web page shown full-screen on a Raspberry Pi in Chromium kiosk mode.
Developed and tested on a PC first.

Independent of my other projects by design: this display reads calendars with its own read-only access and never
holds or shares another project's credentials.

Design: [`DESIGN.md`](DESIGN.md) is the source of truth (v0.24, signed off 2026-10-21).

**Status:** Phases 1 and 3 done on the laptop. Phase 5 (away-from-home viewing through Azure, built to the production profile in DESIGN §17) in progress: experiments R1 and R6 done. Phase 4 (Raspberry Pi) when the hardware arrives.

## Run it with mock data (no credentials, no network)

Python 3.13 or later, standard library only.

```bash
python -m fwcal dev --mock
```

Then open http://127.0.0.1:8765/. Useful options:

- `--now 2026-12-31T23:30`: start the clock at a given local time (mock only)
- `--mock-status stale|offline|reauth`: show the status-line states
- `--config PATH`: use a config file (see [`config.example.toml`](config.example.toml))

Frontend unit tests run in the browser at http://127.0.0.1:8765/tests/index.html (mock mode only).
Keyboard shortcuts for the laptop: `1` `2` `3` switch views (Day, Week, Month), arrow keys move back and forward, `Esc` closes details.

## Dependencies

Mock mode and the web server need nothing beyond Python. The Microsoft sign-in library used by the sync job
is pinned with hashes; install it into a virtual environment:

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install --require-hashes --only-binary :all: --no-deps -r requirements.txt
```

(On the Pi the path is `.venv/bin/python`.)

## Run it with real calendars

Needs the private config (`%APPDATA%\fwcal\config.toml` on Windows, `/etc/fwcal/config.toml` on the Pi; see
[`config.example.toml`](config.example.toml)), the app registration and the viewer account described in DESIGN §5.

```bash
.venv/Scripts/python -m fwcal auth login
```

```bash
.venv/Scripts/python -m fwcal calendars --add
```

```bash
.venv/Scripts/python -m fwcal dev
```

`auth login` opens the browser to sign in as the viewer account (`--paste` on a headless Pi). `calendars --add`
appends the shared calendars to the config and asks how much detail to show for each. `dev` serves the page and
syncs every 5 minutes. `auth status`, `auth logout`, `sync` and `check` are also available.

## Tests

```bash
python -m unittest discover -s tests -t .
```

## Repository safety

Enable the pre-commit check once per clone. It blocks tokens, keys, config files, caches, photos and the
`reference/` screenshots:

```bash
git config core.hooksPath tools/git-hooks
```

Never bypass it with `--no-verify`.

## Layout
- `fwcal/`: Python backend (stdlib HTTP server, text cleaning, normalisation, mock data)
- `static/`: the page (vanilla HTML, CSS and ES modules; no build step, no CDN); `static/tests/` is served in mock mode only
- `tests/`: Python unit tests (`unittest`)
- `tools/`: pre-commit check
- `deploy/`: Raspberry Pi files and the setup checklist ([`deploy/SETUP.md`](deploy/SETUP.md))
