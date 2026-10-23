# wall-calendar — Design

**Version:** 0.26 — **signed off 2026-10-21** (v0.3; §15 signed off with v0.17; §17 production profile with v0.22). Phases 1 and 3 done on the laptop; S1 passed, S2 mostly answered; Phase 5 spikes R1, R2, R3, R4, R6, R7 passed (§15.13); next: R5 (the iPad), then the Phase 5 build; Phase 4 (Raspberry Pi) when the hardware arrives.
**Date:** 2026-10-04
**Conventions:** decisions are ADRs (§13), unknowns are spikes (§12.3), and nothing personal goes in this repository.

## 0. Independence from other projects (ADR-11)
This project is **fully independent** of my other projects. The only possible relationship is that calendars another tool uses may be shared to this project's viewer account through Microsoft's own calendar sharing, which the calendar owner can remove at any time.
- **No shared credentials or identities:** a separate Microsoft account, a separate Entra app registration and client ID, and a separate token cache with its own paths (`fwcal`). This project never holds, reads or copies another project's passwords, tokens, certificates, keys or cloud access, and no other project holds this one's.
- **No shared code, config or tooling:** no imports, symlinks, git submodules, shared virtualenvs, shared config files, or scripts that read another project's folder. Tools such as the pre-commit hook are written fresh here, not copied or referenced.
- **No runtime coupling:** nothing here reads another project's state, storage, cloud resources or output files. It sees only the calendar events Microsoft returns for the viewer account.
- **No personal details carried over:** this repository doesn't name any calendars, activities or people. Calendar names live only in the private config on the device.
- **Development practice:** work on this project does not open other projects' folders. (During the v0.1 draft, one other project's design document, README, `pyproject.toml` and `.gitignore` were read for conventions; no secrets, config or data.)

---

## 1. Problem
A wall display that shows shared calendars at a glance: today's agenda, the week and the month. It should look like DAKboard: a full-screen photo, a large clock and calm type. It must run unattended on a Raspberry Pi in a hallway, keep working through internet outages, and must not become a weak point for the Microsoft accounts involved or for any other system that owns those calendars.

## 2. Goals and non-goals

### Goals
- **G1. Glanceable:** clock, date and today's events readable from about 3 m on a portrait 1080×1920 screen.
- **G2. Three views, switchable by touch:** Today (agenda), Week, Month. Tapping an event shows its details.
- **G3. Survives outages:** the last good data stays on screen, with a clear note of how old it is.
- **G4. Read-only and least privilege:** the device can read only the calendars chosen for it, and can change nothing.
- **G5. Untrusted content is harmless:** event text comes from arbitrary senders (invitations, and events that other tools created from email). Nothing in an event can run code, navigate the kiosk or produce a clickable link.
- **G6. Small attack surface:** one loopback-only HTTP listener, no inbound network access, minimal pinned dependencies, no CDN and no build step.
- **G7. Developed on the laptop:** a mock-data mode builds and tests the whole UI without credentials or network access.

### Non-goals (v1)
- Creating or editing events from the wall (it stays read-only).
- Weather, to-do lists, chores or other widgets. Each adds a new outbound dependency, and possibly an API key; they can be revisited later.
- Remote management or a web admin page. Administration is over SSH.
- Calendars outside Microsoft (Google, iCloud, ICS feeds).
- Multiple screens or multiple locations.

## 3. Critique of the suggested architecture
The suggested architecture is sound, and most of it is kept. These changes come from the review:

| # | Suggested | Change | Why |
|---|---|---|---|
| C1 | Sign in "against consumers" (the account isn't named) | **A dedicated viewer Microsoft account** that only holds *view-only shares* of the chosen calendars (ADR-1) | `Calendars.Read` on my primary account would expose **every** calendar I own to a device that sits in a hallway. With a viewer account, a stolen Pi or SD card exposes only what I shared to it, and I can revoke it from my side by removing the shares. It also keeps the README promise that the display never holds any other system's credentials (§0). |
| C2 | Scopes `Calendars.Read` + `offline_access` | Request **`Calendars.Read` only** (confirmed by S1, 2026-10-21; ADR-2). MSAL adds `openid profile offline_access` itself (MSAL Python refuses reserved scopes passed explicitly). The app registration lists only `Calendars.Read`; the default `User.Read` is removed. | `Calendars.Read` reaches the calendars shared to the viewer account: S1 found they appear in `/me/calendars` and can be read. `Calendars.Read.Shared` was tried first (it is the documented permission for shared calendars) but Microsoft's consumer sign-in silently dropped it, in short and full form. `openid profile` gives the ID token we use to check that the right account signed in (§5.2). |
| C3 | One Python backend | **Two processes under two service users:** `fwcal-sync` holds the token and writes the events file; `fwcal-web` serves the page and the events file, with **no access to the token** (ADR-3). One command runs both on the laptop. | The web process is the one exposed to the browser, which renders untrusted content. Separating it means a bug in HTTP handling can't reach the token. It costs one more systemd unit and nothing else. |
| C4 | Fetch "the next 5 weeks" | Window = **start of the current month's grid** → **the later of today + 35 days and the end of the month grid** (§5.3) | The month view shows the earlier days of the month and the trailing days of the grid. A pure "next 5 weeks" window would leave them blank. |
| C5 | "Strict sanitizer" for HTML bodies | **Ask Graph for plain text** (`Prefer: outlook.body-content-type="text"`), then clean it in Python and render with `textContent` only. **No HTML sanitizer library.** If HTML still arrives, a stdlib `html.parser` extractor reduces it to text (ADR-4). | A sanitizer is a dependency, and its correctness becomes our security boundary. Plain text has no boundary to get wrong. A Trusted Types CSP makes any accidental `innerHTML` throw (§8.2). |
| C6 | Serve on 127.0.0.1 only | Also **reject unexpected `Host` headers and cross-site requests**, serve files from a fixed allowlist (never a path from the URL), and accept GET/HEAD only (§8.3) | Loopback binding alone doesn't stop **DNS rebinding**: on the laptop, any website I visit could otherwise read the calendar from `127.0.0.1`. |
| C7 | Kiosk mode (unspecified) | **Chromium enterprise policies** lock the kiosk to `http://127.0.0.1:<port>` and turn off dev tools, downloads, sign-in, autofill, printing and translation. **No remote-debugging port** (§9.2). | This is a second barrier behind G5: even if something tried to navigate, the browser refuses. |
| C8 | Token cache "mode 600" | Created **with** mode 0600 (`os.open(..., 0o600)`, never chmod afterwards), in a 0700 directory owned by the sync user, written atomically. **Startup refuses** a looser mode or a different owner, as ssh does. On Windows (dev only) it lives under `%LOCALAPPDATA%`, protected by the profile's user-only ACL (ADR-5). | It closes the window between create and chmod, and a misconfiguration fails loudly instead of quietly. |
| C9 | Device-code flow | **Replaced by the browser sign-in** (authorization code with PKCE, `http://localhost` redirect), started only from the CLI (`fwcal auth login`). The web UI never starts or shows a sign-in. Login **refuses to save** the cache unless the account is the configured viewer account and the granted scopes are exactly as expected. | S1 found that Microsoft's consumer code-entry page (`microsoft.com/link`) rejects every device code as "expired" at entry, even for Microsoft's own client, on two devices and networks (2026-10-21). The browser sign-in is Microsoft's recommended flow for desktop apps. On the Pi it runs in paste-back form (§5.2). |
| C10 | Public client | Kept: a **public client**, no secret, no certificate (ADR-2) | On a Pi there's nowhere safer than the token's own disk to keep a secret (no TPM, no Key Vault), so a confidential client would add complexity without protection. The limit on a stolen token is the viewer account's view-only shares (C1). |

## 4. Architecture

```
  Owners' Microsoft accounts                              Raspberry Pi (Raspberry Pi OS, Wayland/labwc)
  ┌──────────────────────────────┐                        ┌────────────────────────────────────────────────────┐
  │ My primary Outlook            │                        │  user fwcal-sync (no login shell)                  │
  │  shared calendars             │  view-only shares      │  ┌──────────────────────────────────────────────┐  │
  │ Other owners' calendars       │ ─────────────────┐     │  │ fwcal sync  (systemd timer, every 5 min)     │  │
  │  (chosen by each owner;       │                  │     │  │  MSAL (public client, consumers authority)   │  │
  │   private config only)        │                  │     │  │  token cache 0600 ── /var/lib/fwcal/auth/    │  │
  └──────────────────────────────┘                  │     │  │  Graph calendarView per configured calendar  │  │
                                                     ▼     │  │  normalise → clean text → events.json (atomic)│  │
                              ┌───────────────────────────┐│  └───────────────┬──────────────────────────────┘  │
                              │ Dedicated viewer account  ││    HTTPS out only │ writes  /var/lib/fwcal/data/    │
                              │ (outlook.com, MFA)        │◄──────────────────┘   events.json (0640, group web) │
                              │ accepted shares only      ││                                                    │
                              └───────────────────────────┘│  user fwcal-web (no login shell)                   │
                                   ▲ Graph: Cal.Read.Shared │  ┌──────────────────────────────────────────────┐  │
                                   │ (delegated, read-only) │  │ fwcal serve  127.0.0.1:8765 only             │  │
                                                            │  │  static page · /api/events · /api/photos     │  │
                                                            │  │  reads events.json and photo folder; no token │  │
                                                            │  └───────────────▲──────────────────────────────┘  │
                                                            │                  │ loopback                         │
                                                            │  desktop user: Chromium --kiosk, policy-locked to   │
                                                            │  http://127.0.0.1:8765, touch screen                │
                                                            └────────────────────────────────────────────────────┘
```

**Data flow:** the sync job fetches → normalises and cleans → writes `events.json`. The web server serves that file as is. The browser renders it with DOM text APIs only. Nothing ever flows back from the browser to Microsoft.

## 5. Calendar sources and sync

### 5.1 Which calendars (ADR-1)
- A **dedicated viewer account** (e.g. `<non-identifying>-wall@outlook.com`; **decided 2026-10-04: I'm creating it**). It is made by hand (off VPN, ideally on a phone), with a unique password in my password manager and MFA. It is used for nothing else, holds no other consented apps, and is aged 1–2 weeks before the Pi connects.
- Owners share each chosen calendar to it **view-only ("can view all details")**, and it accepts them. Which calendars are chosen is recorded only in the private config. **Never share a calendar that holds proposals, digests or other working data** of another tool; share only calendars meant to be read by people.
- **Detail level per calendar (ADR-15, decided 2026-10-21; amended after S1).** Outlook now offers only *"Can view"* and *"Can edit"* when sharing, so details can't be withheld at the share. Every calendar is shared as **"Can view"**, and the config's `detail` setting does the limiting twice: the sync job **doesn't request** the hidden fields from Graph (`$select` per calendar, §5.3), and normalisation removes them again (§5.4 rule 7a). The **Health** calendar uses `detail = "titles"`: title and time only, never location or notes. `detail = "busy"` (time only) is available for anything more sensitive.
- **Currently shared (2026-10-21):** four calendars from one owner account, Health among them. One more calendar is deliberately **not** shared for now; sharing it later as "Can view" makes it visible with no code change (it then needs a `[[calendars]]` entry).
- `fwcal calendars` lists what the viewer account can see (name, owner, whether it can edit, ID). I copy the chosen IDs into the config. **The sync reads only configured IDs**; other calendars are never fetched, even if shared later.
- If `fwcal calendars` shows `canEdit: true` on any configured calendar, sync logs a warning and the wall shows a small notice. The share should be view-only, even though our token can't write anyway.

### 5.2 Microsoft identity
- **A new Entra app registration used only by this project** (never reuse another project's; §0):
  - supported account types: *personal Microsoft accounts only*;
  - platform *Mobile and desktop* with the redirect URI **`http://localhost`** only (any port is accepted for localhost); no `nativeclient` URI, no web or SPA platforms;
  - no secrets, no certificates;
  - API permissions: Microsoft Graph delegated **`Calendars.Read`** only. Remove the default `User.Read`.
  - Authentication settings (the portal's Authentication page was redesigned in 2026; these are on its Settings tab): **Allow public client flows: on** and **Live SDK support: on**, as used in S1. Both were changed while chasing the device-code failure, which turned out to be unrelated; **Phase 3 tests turning each off** and keeps them off if sign-in still works (least privilege).
- Authority `https://login.microsoftonline.com/consumers`. The client ID comes from the config file.
- `fwcal auth login`: the browser sign-in (authorization code + PKCE). On the laptop, MSAL opens the browser and listens on `http://localhost:<random port>` for the answer. **On the Pi (paste-back form, to verify in Phase 3):** the command prints the sign-in link; I open it in my laptop's browser and sign in as the viewer account; the browser then lands on an `http://localhost/...` page that fails to load, and I paste that page's address into the SSH session. The PKCE verifier never leaves the Pi, so the pasted code is useless anywhere else; it is single-use and expires within minutes. The token is created on the Pi and never exists anywhere else. Before writing the cache, it checks:
  1. `preferred_username` in the ID token equals `expected_account` in the config;
  2. the granted scopes are exactly `Calendars.Read` plus `openid profile` (Microsoft omits `offline_access` from the granted list for personal accounts but still issues a refresh token). Anything broader is refused (e.g. a re-used app registration);
  3. if either check fails, nothing is written, and the in-memory tokens are dropped.
- `fwcal auth status` shows the account, scopes, token expiry and the cache file's mode and owner, never token values. `fwcal auth logout` deletes the cache (overwrite, then unlink).
- Refresh is silent (`acquire_token_silent`). If it needs interaction, sync records `auth: reauth_required` and the wall shows "Calendar sign-in needed". **The wall never shows a sign-in link or code.**

### 5.3 Fetch
- **Schedule:** a systemd timer every 5 minutes with ±30 s jitter, plus a run at boot. On the laptop, `fwcal dev` runs the same loop in-process.
- **Window** (computed in local time, with one day of slack each side; no tz database needed):
  `start = min(first day of the week that contains the 1st of this month, today - 7 days)`
  `end = max(today + lookahead_days (default 35), last day of the current month's grid)`
  The UI can move forward and back only within the window. Past it, it shows "Not synced this far ahead" (or "back"). *The week of history was added 2026-10-21: when a month starts on the first day of the grid (November 2026 starts on a Sunday), the window used to begin today and the Day view couldn't show yesterday.*
- **Request**, per configured calendar:
  `GET /me/calendars/{id}/calendarView?startDateTime=…&endDateTime=…&$select=…&$top=100`
  with headers `Prefer: outlook.timezone="UTC"` and `Prefer: outlook.body-content-type="text"`.
  `$select`: `id, subject, start, end, isAllDay, isCancelled, location, body, sensitivity, showAs, type`. Nothing else: no attendees, organizer, online-meeting data or attachments (**data minimisation**). Per calendar, `detail = "titles"` drops `location` and `body` from the `$select`, and `detail = "busy"` also drops `subject`, so Microsoft never sends those fields (ADR-15).
- **Paging:** follow `@odata.nextLink` **only if** it is `https://graph.microsoft.com/` (scheme and host checked), so a tampered response can't send the bearer token elsewhere. Cap at 20 pages and 2,000 events per calendar; past the cap, the calendar is marked `truncated`.
- **HTTP hygiene:** `requests` with TLS verification always on (no config switch to disable it), a minimum of **TLS 1.2** set explicitly in our code rather than left to library defaults (decided 2026-10-21), 10 s connect / 30 s read timeouts, 2 MB response cap per page, no redirects followed for Graph calls. 429/503 honour `Retry-After` up to 2 minutes, else the run ends and the next one retries.
- **Partial failure:** each calendar succeeds or fails on its own. After a network or service failure, a calendar keeps its **previous** events and is marked `stale` with its last success time; a run where every calendar fails changes nothing except the status. **A removed share is different:** if Graph answers 403 or 404 for a calendar, its events are **dropped** and it is marked `error`, so removing a share (revocation step 1, §11.3) also clears it from the wall within one sync.
- **Atomic write:** a temp file in the same directory, fsync, `os.replace`. The web server never reads a half-written file.

### 5.4 Normalisation and cleaning (the content boundary)
Every string from Graph is untrusted. `normalize.py` turns a Graph event into the display schema (§6), and `textclean.py` applies these rules to every text field:
1. If `body.contentType` is `html` despite the Prefer header, extract text with a stdlib `html.parser` subclass: drop `<script>`, `<style>`, `<head>`, comments and hidden elements; keep line breaks for block elements; decode entities once.
2. Unicode NFC. Remove control characters except `\n` and `\t`. Remove **bidi overrides and isolates** (U+202A–U+202E, U+2066–U+2069) and zero-width characters, which can spoof text.
3. Collapse runs of whitespace and blank lines.
4. **Remove Microsoft boilerplate:** the Teams/Skype join block and long lines of underscores, recognised by fixed patterns. It's cosmetic, and a fallback leaves the text unchanged.
5. **Length caps:** title 200, location 200, notes 2,000 characters (ending with "…").
6. URLs stay as plain text. They are never turned into links (G5). Very long URLs are shortened for display to `host/…` (cosmetic).
7. **Private events:** if `sensitivity` is `private` or `confidential`, title becomes "Private", and location and notes are dropped **in the sync job**, so they never reach the disk.
7a. **Detail level** (`detail` per calendar, ADR-15): `full` keeps everything; `titles` keeps the title and time and drops location and notes; `busy` shows "Busy" and the time only. Applied in the sync job, so hidden fields never reach the disk or the browser. Private events stay "Private" at every level.
8. `isCancelled` events are dropped. `showAs: free` events are kept (people often mark activities free).
9. **IDs:** Graph IDs never leave the sync job. Events get `sha256(calendarKey + graphId)[:16]`, and calendars get the config key (e.g. `home`).

### 5.5 Time handling
- **Timed events:** Graph returns UTC (header above). They are stored as ISO-8601 instants with `Z`, and the browser converts them to local time with `Intl`. The Pi's system time zone must be set (deployment checklist), and NTP keeps the clock right.
- **All-day events:** stored as **dates only** (`startDate`, exclusive `endDate`), taken from the date part and never converted between zones. A converted all-day event can slip a day, so these never go through time-zone conversion. **Spike S2** confirms how Graph returns all-day events under `Prefer: outlook.timezone="UTC"`.
- **Multi-day and overnight events** appear on every day they touch. Timed events show "continues" or "until 10:00" on later days.
- **Python needs no `tzdata` package.** Window maths uses the local UTC offset with a day of slack, and all display conversion happens in the browser.

## 6. Data contract: `events.json` (also `GET /api/events`)
```jsonc
{
  "schema": 1,
  "source": "graph",                       // "graph" | "mock"
  "generatedAt": "2026-10-04T21:05:12Z",
  "auth": "ok",                            // "ok" | "reauth_required" | "not_configured"
  "window": { "start": "2026-09-28", "end": "2026-11-09" },
  "calendars": [
    { "key": "home", "name": "Home", "color": "#7FB3FF",
      "status": "ok", "lastSuccessAt": "2026-10-04T21:05:11Z", "truncated": false }
  ],
  "events": [
    { "id": "3f9c0a1b2c3d4e5f", "cal": "home", "title": "Dentist",
      "allDay": false, "start": "2026-10-06T16:30:00Z", "end": "2026-10-06T17:15:00Z",
      "location": "Main St Dental", "notes": "Bring forms", "private": false },
    { "id": "…", "cal": "home", "title": "Guests visiting",
      "allDay": true, "startDate": "2026-10-10", "endDate": "2026-10-13",
      "location": "", "notes": "", "private": false }
  ]
}
```
- The web server **validates** the file on read (parse, schema version, types, color regex `^#[0-9A-Fa-f]{6}$`, `cal` refers to a known calendar). It drops invalid events and never passes through a file it can't parse; it serves `{"auth": …, "events": [], "error": "no_data"}` instead.
- Display settings come from `GET /api/settings`, built from the non-secret part of the config. **Defaults (decided 2026-10-04):** `clock = "12h"`, `week_start = "sunday"`, `show_notes = true`. The other settings are the idle timeout, photo interval and night-dim hours.
- **`show_notes`** is a config option. When it is `false`, the **sync job drops notes before writing** `events.json`, so they never reach the disk or the browser; the details panel then shows the time, location and calendar only. Hiding notes in the browser alone would not be enough.
- Calendar colors come from the config, not from Outlook. Owners' Outlook colors don't carry over through shares, and colors chosen for the wall can be picked for contrast on dark photos.

## 7. Configuration, files and paths

| What | Pi | Laptop (dev) | Mode / owner | In repo? |
|---|---|---|---|---|
| Config (`config.toml`) | `/etc/fwcal/config.toml` | `%APPDATA%\fwcal\config.toml` | 0640 root:fwcal | No. `config.example.toml` is |
| Token cache | `/var/lib/fwcal/auth/msal_cache.json` | `%LOCALAPPDATA%\fwcal\auth\msal_cache.json` | file 0600, dir 0700, fwcal-sync | **Never** |
| Events cache | `/var/lib/fwcal/data/events.json` | `%LOCALAPPDATA%\fwcal\data\events.json` | 0640 fwcal-sync:fwcal-web | Never |
| Photos | `/var/lib/fwcal/photos/` | configurable folder | 0750, readable by fwcal-web | Never |
| Logs | journald | console | — | — |

- **Config** (TOML, read with stdlib `tomllib`): `client_id`, `expected_account`, `[[calendars]]` (key, Graph ID, display name, color, detail level), `lookahead_days`, `port`, `photo_dir`, display settings. It holds **no secrets** (a public client ID is not one), but it does hold personal details (the account name and calendar names), so it stays out of git.
- **Paths are resolved by code, not taken from the URL or the environment.** The config path can be overridden only with an explicit `--config` argument; nothing is read from environment variables.
- **Logs** hold counts, status codes, Graph `request-id`, durations and calendar keys, but never titles, notes, locations, tokens or account names. MSAL's own logger is set to WARNING, and it is checked that it never logs token values.
- **Repository safety:** `.gitignore` adds `*.toml` except `config.example.toml`, `*cache*.json`, `events*.json`, `photos/`, `reference/` and `secrets/`. A small pre-commit hook (`tools/git-hooks/pre-commit`, written for this repo) blocks token-like strings (`"refresh_token"`, `eyJ…` JWTs), `.toml` files other than the example, and anything under `photos/` or `reference/`.
- **`reference/` screenshots** stay local and gitignored. They are third-party product screenshots, and may show personal calendars.
- **Mock data is generic** ("Tennis practice", "Dentist", "Book club"). There are no real names, places, activities or schedules in the repo, and nothing about who uses it.

## 8. Web server and frontend security

### 8.1 Server (`fwcal serve`)
- Python stdlib `http.server.ThreadingHTTPServer`. **No web framework.**
- Binds `127.0.0.1` only. A port is configurable; a non-loopback bind address is **not** configurable.
- **Routes are a fixed table** built at startup:
  - `/`, `/app.css`, `/js/*.js`, `/fonts/*.woff2` map to files enumerated from `static/` once at startup. The request path is a dictionary key, never joined to a filesystem path;
  - `/api/events`, `/api/settings`, `/api/photos` (a list of opaque names);
  - `/photos/<name>`, served only if `<name>` is in the current listing (rescanned every 10 minutes): `.jpg`, `.jpeg`, `.png` and `.webp` only, at most 25 MB each. Symlinks are not followed. **SVG is not allowed** (it can carry script).
- **Request checks:** method GET or HEAD (else 405); `Host` must be exactly `127.0.0.1:<port>` or `localhost:<port>` (else 421); if `Sec-Fetch-Site` is present it must be `same-origin` or `none` (else 403); no query strings except a cache-buster; request line and headers capped at 8 KB; one-second header timeout.
- **Response headers on everything:**
  - `Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; require-trusted-types-for 'script'; trusted-types 'none'`
  - `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Resource-Policy: same-origin`, `Permissions-Policy` denying camera, microphone, geolocation, USB, payment and similar, `Cache-Control: no-store` on the API.
  - **No CORS headers**, ever.
- Errors are short fixed strings, with no stack traces or paths.

### 8.2 Frontend rules
- **Vanilla ES modules, no build step, no third-party JS, no CDN.** Fonts are served locally (§10.4).
- **One DOM helper** (`dom.js`: `el(tag, {class}, ...children)`) creates elements with `createElement` and sets text with `textContent`. **These are banned in `static/`** and the ban is enforced by a test that scans the source: `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, `new Function`, string `setTimeout`/`setInterval`, `.href =`, `<a`, `window.open` and `location.assign`.
- **Trusted Types with `trusted-types 'none'`:** Chromium throws on any HTML-string sink, so even a missed `innerHTML` fails safely instead of injecting.
- **No links anywhere.** URLs in notes are plain text. Text selection, the long-press callout and the context menu are disabled (CSS `user-select: none`, `-webkit-touch-callout: none`, and `contextmenu` prevented). Kiosk policy also blocks navigation (§9.2).
- **Colors** are applied through `element.style.setProperty('--cal', value)` only after the regex check, so no inline style attributes are needed (CSP blocks them).
- The page fetches only `/api/*` and `/photos/*` from its own origin. `connect-src 'self'` enforces that.

## 9. Raspberry Pi deployment

**Files:** `deploy/` holds the systemd units, service users and directories (sysusers.d, tmpfiles.d), Chromium policy, kiosk autostart, firewall and SSH settings; `deploy/SETUP.md` is the step-by-step checklist. `tests/test_deploy.py` keeps them consistent with the code (port, paths, sandbox settings). `fwcal check` verifies permissions, listeners and data freshness on the Pi.

**Deviations found while writing them (2026-10-21):**
- The web service runs with `PrivateNetwork=yes`: it has no network at all beyond the socket systemd passes in. `PrivateUsers=` is not used, because it would hide the `fwcal` group needed to read the config.
- The sync service uses `UMask=0027` (not 0077), so `events.json` stays readable by the web service's group; the token file gets an explicit 0600. `MemoryDenyWriteExecute=` waits for S3 on the sync service (the cryptography library).
- The checklist uses the standard Raspberry Pi OS (64-bit) image with its labwc desktop and removes listening services, instead of Lite plus a hand-built Wayland session: it is the documented kiosk route and fewer moving parts. Revisit after S3 if the image is too heavy.

### 9.0 Hardware (recommendation; not bought yet)
- **Raspberry Pi 5, 4 GB.** Chromium is noticeably smoother than on a Pi 4 (faster CPU and GPU), and 4 GB leaves headroom for full-screen photos. 8 GB isn't needed. A Pi 4 (4 GB) would work, but with slower crossfades.
- **Official 27 W USB-C power supply.** A Pi 5 on a weaker supply limits USB current, and the touch screen is a USB device. Add the **official Active Cooler**, since the Pi runs 24/7 inside a mount.
- **Storage:** an **NVMe SSD on the official M.2 HAT+** is preferred for years of unattended running. A good A2 microSD card is acceptable, since the app writes only a small file every 5 minutes.
- **Screen:** a **plain 21.5–24" 1080p IPS monitor with USB touch**:
  - multi-touch over USB HID, so it works on Linux without drivers;
  - matte finish; VESA mount; can be used in portrait;
  - sleeps when there's no signal (for night-time screen off).
  **Avoid "smart" or Android all-in-one displays** (another networked computer on the wall), and models with a built-in camera or microphone.
- **Mounting and network:** the Pi goes on a VESA bracket behind the screen, so one outlet and short cables are enough (Pi 5 needs a micro-HDMI → HDMI cable). Use wired Ethernet if there's a port nearby; otherwise Wi-Fi is fine, since the display survives outages.
- **Portrait setup:** rotate in the compositor (labwc/kanshi), and **map touch input to the rotated output**, or taps land in the wrong place. This is part of S3.

### 9.1 Services (systemd)
- `fwcal-sync.service` (oneshot) + `fwcal-sync.timer`; `fwcal-web.service` (simple, restart on failure), started by **`fwcal-web.socket`**: systemd holds 127.0.0.1:8765 at all times, so no other process can take the port while the web service restarts (§12.6).
- **Sandboxing on both:** `NoNewPrivileges`, `ProtectSystem=strict` (with `ReadWritePaths` set to the unit's own state directory), `ProtectHome`, `PrivateTmp`, `PrivateDevices`, `ProtectKernel*`, `RestrictSUIDSGID`, `LockPersonality`, `MemoryDenyWriteExecute` (verified to work with `cryptography`), `SystemCallFilter=@system-service`, `CapabilityBoundingSet=` (empty), `UMask=0077` for sync and `0027` for web.
- **Network:** `fwcal-web` gets `RestrictAddressFamilies=AF_INET AF_UNIX`, `IPAddressDeny=any`, `IPAddressAllow=localhost`. `fwcal-sync` gets `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX` and has no listening socket.
- The code runs from a root-owned virtualenv at `/opt/fwcal` (not writable by either service user).

### 9.2 Kiosk browser
- The desktop user auto-logs in and starts `chromium --kiosk --app=http://127.0.0.1:8765 --noerrdialogs --disable-session-crashed-bubble --no-first-run --overscroll-history-navigation=0 --disable-pinch`. **Never `--remote-debugging-port`.** Screen rotation is set in the compositor (labwc/kanshi).
- **Managed policies** in `/etc/chromium/policies/managed/fwcal.json`: `URLBlocklist ["*"]` and `URLAllowlist ["http://127.0.0.1:8765"]`; `DeveloperToolsAvailability 2`; `DownloadRestrictions 3`; `PrintingEnabled false`; `BrowserSignin 0`; `SyncDisabled true`; `PasswordManagerEnabled false`; `AutofillAddressEnabled false`; `AutofillCreditCardEnabled false`; `TranslateEnabled false`; `SearchSuggestEnabled false`; `MetricsReportingEnabled false`; `ExtensionInstallBlocklist ["*"]`; `DefaultGeolocationSetting 2`; `DefaultNotificationsSetting 2`; `DefaultPopupsSetting 2`; `IncognitoModeAvailability 1`.
- The page reloads itself daily at 03:00 to pick up updates and release memory.

### 9.3 Host hardening checklist
- Raspberry Pi OS Lite + a minimal Wayland session; automatic security updates (`unattended-upgrades`).
- **SSH: keys only, no password login, no root login.** Optionally reachable from the LAN only.
- nftables: default deny inbound, allow established and SSH from the LAN.
- Disable services that listen and aren't needed (`avahi-daemon`, `cups`, Bluetooth).
- **Verified with `ss -tulpn`:** only sshd and `127.0.0.1:8765` listen. This check is part of `fwcal check`.
- Time zone set; NTP (`systemd-timesyncd`) on.
- **Physical:** the SD card is the weak point; the revocation runbook (§11.3) covers theft. Full-disk encryption isn't worth it here: an unattended Pi would have to keep the key on the same device.

## 10. Frontend design

### 10.1 Look (DAKboard-inspired, original code)
- **Full-screen photo**, crossfading (opacity, 2 s) every N minutes (default 10). Photos come from the local folder in shuffled order, with `object-fit: cover`.
- **Dark overlay:** a vertical gradient (darker at top and bottom where text sits), plus a subtle text shadow. **No `backdrop-filter` blur**: it's expensive on the Pi GPU. Cards use a flat translucent dark fill instead.
- **Type:** a light sans-serif (weights 200–400) in white and soft greys. Clock about 180 px at weight 200; date about 48 px.
- **Calendar colors:** a 6 px left bar on each event, plus a matching dot in the month view. A legend with calendar names sits at the bottom.
- **Status line** (small, bottom corner): nothing while fresh; amber "Updated 25 min ago" after 15 minutes; red "Offline since 14:05" after 60 minutes; "Calendar sign-in needed" when re-authentication is required.
- **Night dimming:** a darker overlay between configurable hours (default 22:00–06:30). Turning the screen off on a schedule (`wlr-randr`) is an operations option, not app code.
- **Visual baseline approved 2026-10-21** from an interactive mockup: photo background with flat dark overlay, Inter at light weights, a 12-hour clock with a small AM/PM, pill-shaped view switch, colored left bars for events, Week as stacked day rows, a Sunday-first Month grid, a bottom-sheet details panel, and a legend with the status note in the bottom row. Phase 1 builds to this look.
- **The approved mockup is the visual reference (decided 2026-10-21).** DAKboard screenshots are no longer needed. `reference/` stays gitignored in case any are added later.

### 10.2 Layout (portrait 1080×1920, responsive)
```
┌──────────────────────────────┐
│  9:41                        │  clock + date block  (~22% height)
│  Sunday, October 4           │
├──────────────────────────────┤
│ [ Today ]  [ Week ]  [ Month ]│  view switch: 3 large pills (≥ 96 px tall)
├──────────────────────────────┤
│  ALL DAY  ▌Guests visiting   │
│  8:00 AM  ▌Tennis practice   │  active view (scrolls inside if long)
│  3:30 PM  ▌Dentist  · Main St│
│  ...                         │
│  TOMORROW                    │  Today view adds a short "Tomorrow" preview
├──────────────────────────────┤
│ ● Home ● Events ● Work    ⓘ │  legend + status
└──────────────────────────────┘
```
- **Day** (the tab was called Today until 2026-10-21): all-day events as banners, then timed events in order. Under each start time, a smaller, dimmer line gives the end ("to 4:30 PM", or "to Sun 9:00 AM" across midnight; none for all-day events or events continuing from an earlier day, which already say "Until ..."). Events in progress are highlighted, and past events are dimmed. A "Tomorrow" preview shows up to 4 events. Swipe left/right changes the day. The heading says "Today" for today; for any other day it shows the date with a dimmer relative hint ("Thursday, October 22 · Tomorrow", "In 5 days", "Yesterday"). Tapping the Day tab always returns to today.
- **Truncated text:** titles, locations and chips that don't fit end with an ellipsis; on a laptop, hovering shows the full text as a native tooltip (plain text, set only when the text is actually cut off). On the touch kiosk, tapping opens the details panel instead.
- **Week:** in portrait, 7 **stacked day rows** (not 7 narrow columns), each with its events as compact chips. Today is highlighted. Swipe changes the week.
- **Month:** a 7-column grid with 5–6 rows. Each day shows **one dot per event in its calendar colour** (a short pill for all-day events), up to 8, then "+N": a busy-ness pattern readable from across the room, with no truncated text. Tapping a day opens it in the Today view; on a laptop, hovering over a day lists its events with times. *(Changed 2026-10-21 from up to 3 text chips per day, which clipped and cut titles to a few characters with real data.)* Swipe changes the month (within the synced window).
- **Landscape and other sizes:** a CSS grid reflow (clock column on the left, view on the right). Sizes use `clamp()` and viewport units, so 1920×1080 and the laptop window both work.
- **Idle behaviour:** after 2 minutes without a touch, the details panel closes and the display returns to Today for the current day.
- **Timers and power (2026-10-21):** the page wakes **once a minute, just after the minute boundary** (not every second) to update the clock, past/now highlighting, night dimming and the day; it checks `/api/events` every 60 s with **`If-None-Match`**, and the server answers **304 with no body** until a sync changes the file (the server also caches the validated file by modification time, size and inode, so it isn't re-read). While the page is **hidden** (a laptop background tab) the clock, polling and photo changes stop, and everything catches up the moment it is visible. Verified: event end and midnight transitions happen unattended. The screen itself is the largest power draw; a scheduled screen-off is planned for Phase 4 (§9).

### 10.3 Event details panel
- A bottom sheet over a dimmed backdrop. It shows the title, calendar name with its color, the time ("Tue 6 Oct · 4:30–5:15 PM", or "All day · Sat 10 – Mon 12 Oct"), the location and the notes (plain text, `white-space: pre-wrap`, scrolls inside the sheet).
- It closes with a large ✕, a tap on the backdrop, a swipe down, or after 60 s. Every target is at least 64 px.
- Private events show only "Private" and the time.

### 10.4 Fonts and assets
- **Inter** (SIL Open Font License 1.1), the upright variable `woff2` (weights 100–900, 352 KB; italics not used), vendored into `static/fonts/` with `LICENSE.txt`. The upstream release, download URL and SHA-256 of each file are recorded in `static/fonts/SOURCES.md`, and a test checks the hashes. Fallback stack: `system-ui, sans-serif`.
- Icons are inline SVG built with DOM APIs, or plain CSS. There are no icon fonts or third-party sprites.

### 10.5 Mock-data mode
- `fwcal dev --mock` (laptop) or `fwcal serve --mock`. **Mock mode never imports MSAL, never reads the token cache and makes no network calls**; a test enforces this.
- It generates events relative to "now" across 4 calendars: overlapping events, all-day and multi-day events, overnight events, a day with 9 events (overflow), an empty day, and a private event.
- **Adversarial fixtures double as security tests:** a body with `<script>`, `<img onerror>`, `javascript:` URLs, `<a href>`, a Teams join block, bidi-override characters, zero-width characters, a 10,000-character title, emoji and RTL text, and an HTML body that arrives despite the text preference. They go through **the same `normalize.py` as Graph data**, so the UI shows exactly what production would.
- `--now 2026-12-31T23:30` fixes the clock to test month and year rollover. A built-in sample photo set (flat landscapes drawn by the standard library at first start) keeps it free of personal photos and downloads. `--mock-status stale|offline|reauth` shows each status-line state.

## 11. Threat model and operations

### 11.1 Threats

| # | Threat | Mitigation | Residual |
|---|---|---|---|
| T1 | Script or HTML in event title, location or body (from any inviter, or from events other tools created from email) | Graph returns text; stdlib extraction fallback; cleaning; `textContent` only; banned-sink test; Trusted Types CSP; strict CSP | Very low |
| T2 | Phishing link or URL in an event | Never clickable; no selection or context menu; kiosk URL allowlist | Very low |
| T3 | Text spoofing (bidi overrides, zero-width, giant strings) | Stripped and capped (§5.4) | Low |
| T4 | Pi or SD card stolen; token cache taken | Viewer account has only view-only shares; revoke (§11.3) | Read access to shared calendars until revoked |
| T5 | Website in another browser reads `127.0.0.1` (dev laptop): DNS rebinding or cross-site requests | Host allowlist, `Sec-Fetch-Site` check, no CORS, GET only | Low |
| T6 | Bug in the web server exploited locally | Separate user with no token access; systemd sandbox; stdlib server; fixed routes | Low (calendar data only) |
| T7 | Path traversal or arbitrary file read via static or photo routes | Startup allowlist; listed names only; no symlinks; no SVG | Very low |
| T8 | Guest escapes the kiosk via the touch screen | Kiosk mode, policies (no dev tools, downloads, navigation), no keyboard, gestures disabled | Low |
| T9 | LAN attacker | No inbound ports except key-only SSH; firewall; automatic updates | Low |
| T10 | Supply-chain compromise | Few dependencies; exact versions with hashes; `--require-hashes --only-binary :all:`; no frontend dependencies or CDN; Dependabot alerts | Med (industry-wide), small surface |
| T11 | Signing in the wrong (primary) account, or over-broad consent | Expected-account and exact-scope checks before saving (both proven in S1: the dropped-scope runs were refused before any Graph call); app registration has only `Calendars.Read` | Very low |
| T12 | Token redirected to another host via a tampered `nextLink` | Host and scheme check before following | Very low |
| T12b | Authorization code intercepted during the paste-back sign-in (§5.2) | PKCE: the verifier never leaves the Pi, so a code alone can't be redeemed; single-use, minutes-long code; only the viewer account consents | Very low |
| T13 | Tokens or personal data in logs or the repo | No-content logging; MSAL logger level; `.gitignore`; pre-commit hook; generic mock data | Low |
| T14 | Viewer account taken over | Unique password + MFA; it owns nothing and only holds view-only shares | Low |
| T15 | Private event details shown in a shared hallway | Private/confidential redacted in the sync job; owners choose what to share | Low (the wall is meant to show the schedule) |
| T16 | Availability: outage, Microsoft locks the account, expired consent | Cached display + staleness banner; "sign-in needed" banner; CLI re-auth over SSH | Inconvenience only |

### 11.2 Operations
- `fwcal check` runs the self-check: file modes and owners, config validity, listening sockets, that the configured calendars are visible and view-only, the token's account and scopes, and the age of the cache.
- Updates: `git pull` on the Pi (read-only deploy key or HTTPS), then `pip install --require-hashes`, then restart the services. Deployment is manual; GitHub has no access to the Pi.
- Backups: none needed. Config is re-creatable, the cache is disposable, and photos live wherever they came from.

### 11.3 Revocation runbook (fastest first)
1. **Remove the shares** from the owners' accounts (works even if the Pi is gone; a running Pi also drops those calendars from the wall at its next sync, §5.3).
2. **Revoke the app's consent** for the viewer account at account.live.com/consent/Manage.
3. **Change the viewer account's password** ("sign out everywhere").
4. **Delete the Entra app registration.**
5. On the Pi, if it's still yours: `fwcal auth logout`, then re-image.

## 12. Dependencies, testing and delivery

### 12.1 Dependencies
- **Runtime:** `msal` only directly. It brings `requests` (also used for Graph), `PyJWT`, `cryptography` and their dependencies (`cffi`, `pycparser`, `urllib3`, `idna`, `charset-normalizer`, `certifi`). There is **no** HTML sanitizer, web framework, `tzdata` or `msal-extensions`.
- **Pinning:** `requirements.in` → `requirements.txt` generated with `pip-compile --generate-hashes` (pip-tools, a dev tool only). Hashes cover both the Windows (cp314) and Raspberry Pi aarch64 (cp313) wheels. Installation is `pip install --require-hashes --only-binary :all: --no-deps -r requirements.txt`. Dev tools (`pip-tools`, and `ruff` if adopted) are pinned the same way in `requirements-dev.txt`. **Phase 1 uses the standard library only.** The files were created on 2026-10-21 for spike S1: `msal` 1.39.0, `requests` 2.34.2, `cryptography` 50.0.2, `PyJWT` 2.15.1 and their dependencies (10 packages, 345 hashes); every platform wheel for Raspberry Pi aarch64 (cp313) and Windows (cp314) is covered. `pip-tools` is in `requirements-dev.txt` only.
- **Python:** 3.13 or later (Raspberry Pi OS Trixie has 3.13; the laptop has 3.14). No 3.14-only features.
- **Frontend:** none.

### 12.2 Tests
- **Unit tests (stdlib `unittest`, so no test dependency):**
  - text cleaning and HTML-to-text conversion against the adversarial fixtures;
  - normalisation of recurring, all-day, multi-day, cancelled and private events;
  - window calculation, including month and year edges and DST weeks;
  - atomic writes, and the file-mode refusal (POSIX);
  - config validation;
  - `nextLink` host check; paging caps;
  - partial-failure merge.
- **Server tests:** spin up on an ephemeral port and check the Host and `Sec-Fetch-Site` rejections, 405s, traversal attempts (`/../`, encoded and double-encoded, backslashes), photo allowlist and SVG refusal, every security header, and handling of a malformed `events.json`.
- **Static source scan:** the banned-sink list (§8.2), plus no `http(s)://` URLs in `static/` (no CDNs).
- **Mock-mode isolation:** mock mode imports no `msal` and opens no sockets except the listener.
- **Frontend:** the pure JS functions (day bucketing, multi-day spans, month grid, overflow) are tested by a small in-browser test page (`/tests/index.html`) served only in mock mode; it also checks that Trusted Types blocks `innerHTML`. Visual checks at 1080×1920, 1920×1080 and the laptop size in the browser, with screenshots for review.
- **Graph tests** use recorded, scrubbed responses (`tests/fixtures/graph/`, synthetic content only), never live calls.

### 12.3 Spikes (before the fetcher is built)

| Spike | Question | Method | Pass |
|---|---|---|---|
| **S1** Auth and shared calendars | Can a public-client token with only a calendar-read permission on the viewer account read view-only shared calendars via `/me/calendars/{id}/calendarView`? Do the shares appear in `/me/calendars`? | New app registration; sign-in; list calendars; read each share. **Negative tests:** create an event (expect 403); read `/me/messages` (expect 403); log in with a different account (refused by our check) | **PASS 2026-10-21** (§12.7) |
| **S2** Event shapes | How do all-day, multi-day, recurring, cancelled-occurrence, private and Teams-invite events come back with UTC + text preferences? Does a per-calendar `$select` without `location` and `body` work for `detail = "titles"` calendars? | Make each kind on a test calendar, share it, record the responses (scrubbed into fixtures) | Normalisation handles all of them; fixtures committed. *Partly answered by S1: UTC times, text bodies, all-day as midnight UTC.* |
| **S3** Pi performance | Does Chromium on the target Pi render 1080×1920 with photo crossfades smoothly? Does Trusted Types work in its Chromium version? | Run mock mode on the Pi; watch CPU, memory and frame rate; try a deliberate `innerHTML` (expect a TypeError) | Smooth crossfade; under 50% CPU when idle; memory steady over 24 h |

### 12.4 Delivery plan
1. **Phase 1: mock-data UI (laptop). Done 2026-10-21** (§12.5). Server (`serve`, `dev --mock`), normalisation and cleaning with the adversarial fixtures, all three views, the details panel, photos and status line, security headers, and the tests above. **Design review with you on screenshots at 1080×1920.** *Meanwhile, you create the viewer account so it ages.*
2. **Phase 2: spikes S1 and S2** on the laptop, with the real viewer account. Then update this design. *S1 passed 2026-10-21 (§12.7); S2 is partly answered and finishes in Phase 3 with recorded fixtures.*
3. **Phase 3: Graph fetcher.** `auth login/status/logout`, `calendars`, `sync`, the partial-failure merge, `check`. A live run on the laptop. **Done 2026-10-21 (§12.8).**
4. **Phase 4: Raspberry Pi.** S3, systemd units, kiosk policies, host hardening, the `ss` check, and a 72-hour soak test with a simulated outage (network unplugged).

### 12.5 Phase 1 result (2026-10-21)
- **Built:** `fwcal serve` / `fwcal dev --mock`; text cleaning and normalisation with the adversarial fixtures; Today, Week and Month views; details panel; photo crossfade; status line; night dimming; idle return; swipe navigation; portrait and landscape layouts; pre-commit check.
- **Tests:** 80 Python tests (1 POSIX-only test skipped on Windows) and 13 in-browser tests, all passing. Verified in the browser at 1080×1920 and 1600×900. Trusted Types blocks `innerHTML` in practice; markup in event text renders as literal text; the HTML-body fixture shows no hidden text, scripts or links.
- **Additions made while building** (no change to signed-off decisions):
  - the server sets `SO_EXCLUSIVEADDRUSE` on Windows and never `SO_REUSEADDR`, so another local process can't take over the port;
  - the `Server` header carries no Python version; responses also send `X-Frame-Options: DENY`;
  - photos are served only if their first bytes match their type (a `.jpg` that is really HTML is refused);
  - static files are read once at startup, so the server must be restarted to pick up frontend changes;
  - the package lives at `fwcal/` in the repo root (no `src/` layout), run with `python -m fwcal`.

### 12.6 Security review of Phase 1 (2026-10-21)
A manual adversarial pass over the server, text cleaning, store, CLI and frontend. No critical findings. Fixed:
- **Stacked combining marks** ("Zalgo" text) could draw over other parts of the screen: at most 4 combining marks per letter (§5.4).
- **Hostile body sizes:** input is cut before the per-character work (10× the output limit; 500,000 characters for HTML), so one event can't stall a sync.
- **Settings in the browser** are copied key by key with type checks (`static/js/settings.js`) instead of `Object.assign`, which would honour a `__proto__` key.
- **Mock refresh** survives a failed file replace on Windows instead of stopping silently.
- **Invisible characters in source code:** the editing tools had turned escapes in test data into real bidi-override and zero-width characters. They're escapes again, and the pre-commit check and a test now reject control, format and surrogate characters in any text file ("Trojan Source").

Accepted (no change): hidden-text tricks beyond `display:none`, `visibility:hidden` and `hidden` (e.g. zero font size) can still show text on the wall; this is display-only, since nothing is executable or clickable. Homoglyphs are shown as written.

Carried to Phase 4: **port squatting.** If `fwcal-web` is down, another local process could bind 127.0.0.1:8765 and serve a fake page to the kiosk. On the Pi, systemd will own the socket (socket activation) so the port is never free for another process (§9.1).

### 12.7 Spike S1 result (2026-10-21): PASS
Run from the laptop with `spikes/s1_auth.py` (not committed): token in memory only, never printed; account and scopes checked before any Graph call; only counts and field shapes printed.
- **Sign-in:** the device-code flow failed: Microsoft's consumer code-entry page rejected every code as "expired" at entry while the token endpoint still reported it as pending (`AADSTS70016`). This happened with our app and with Microsoft's own Graph command-line client, on a laptop and on a phone on mobile data. The browser sign-in (authorization code + PKCE, `http://localhost`) worked first time. ADR-2 changed accordingly.
- **Permission:** `Calendars.Read.Shared` was silently dropped by the consumer sign-in (no calendar line on the consent screen; granted scopes `openid profile`); the account and scope checks refused to continue, as designed. `Calendars.Read` was granted (consent screen: "Read your calendars") and is sufficient.
- **Calendars:** `/me/calendars` listed the viewer account's own empty calendar plus **4 shared calendars from one owner, all `canEdit = false`**. `calendarView` worked on every calendar.
- **Event shapes (partial S2):** times in UTC as requested; bodies as text; one all-day event returned as midnight UTC (confirms date-only handling); no recurring or private events in the 14-day window.
- **Negative tests:** create an event in the viewer's own calendar **403**; mail **403**; contacts **403**; OneDrive **401**; `/me` **403** (no `User.Read`).
- **Mistakes corrected on the way:** the original advice to leave redirect URIs empty was wrong for this flow (it needs `http://localhost`); the `nativeclient` URI and the Live SDK toggle were tried and were not the cause.

### 12.8 Phase 3 result (2026-10-21): fetcher working on the laptop
- **Built:** `fwcal auth login | status | logout` (browser sign-in with PKCE; `--paste` for a headless Pi); `fwcal calendars [--add]`; `fwcal sync [--loop]`; `fwcal dev` now runs the web server and the sync loop together. Modules: `tokencache.py`, `auth.py`, `graph.py`, `sync.py`. MSAL is imported only by these commands, never by the web server or mock mode (tested).
- **Token cache on Windows:** saved in `%LOCALAPPDATA%\fwcal\auth`; the folder's ACL lists **only the user and SYSTEM** (inheritance removed, so not even Administrators). `fwcal auth status` shows the account and the number of refresh tokens, never their values.
- **Live sync:** 64 events from the 4 shared calendars in under 2 s, none rejected. **Health** (`detail = "titles"`): 3 events, **0 locations and 0 notes**, because `location` and `body` were never requested. No Graph IDs in `events.json`. `fwcal check` reports the config and events as good.
- **`fwcal calendars --add`** appends the shared calendars to the private config and **asks the detail level for each, defaulting to `titles`** (the private choice). Calendar names come from the calendar's owner, so they are cleaned before being printed (no terminal escape codes) and written as quoted, escaped TOML strings.
- **Changes from the plan:** a calendar shared with edit rights is reported by `fwcal calendars` (with a warning) instead of as a notice on the wall; removed shares drop their events (§5.3); the page's timers and the 304 answers above.
- **Tests:** 138 Python tests (Graph client, sync, token cache, sign-in checks and CLI use fakes; no network) and 16 in-browser tests, all passing.
- **Still to verify on the Pi (Phase 4):** the paste-back sign-in; turning **Allow public client flows** and **Live SDK support** off in the app registration (keep them off if sign-in still works); `MemoryDenyWriteExecute=` on the sync service; the rest of S2 (recurring series, cancelled occurrences, private events) as they appear in real data.

## 13. Decisions

| ADR | Decision | Status |
|---|---|---|
| ADR-1 | A dedicated viewer Microsoft account with view-only shares; never my primary account; never a calendar holding another tool's working data | **Accepted 2026-10-04** |
| ADR-2 | Public client; **browser sign-in (authorization code + PKCE, `http://localhost` redirect)** instead of device code; `consumers`; **`Calendars.Read`** only; MSAL adds `openid profile offline_access`; separate app registration. *History: device code was refused at Microsoft's consumer code-entry page; `Calendars.Read.Shared` was silently dropped (both found in S1, 2026-10-21).* | **Accepted; verified by S1** |
| ADR-3 | Two processes, two service users: sync holds the token, web never sees it | Proposed |
| ADR-4 | Plain-text bodies from Graph + stdlib fallback + `textContent` + Trusted Types; no sanitizer library | Proposed |
| ADR-5 | Token cache: plain file, created 0600 in a 0700 directory, refuse otherwise; Windows dev: the token directory still gets an explicit ACL with inheritance removed (current user and SYSTEM only) as cheap defence in depth. *Correction 2026-10-21: the extra AppContainer entry first seen on AppData was an artifact of the development sandbox's view; the real profile grants only the user, SYSTEM and Administrators.* No `msal-extensions` (libsecret needs a desktop keyring on a headless Pi) | Proposed |
| ADR-6 | Stdlib HTTP server on 127.0.0.1, fixed routes, Host and Sec-Fetch checks, strict CSP | Proposed |
| ADR-7 | Chromium kiosk locked by managed policies; no remote debugging | Proposed |
| ADR-8 | Fetch window = earlier of the current month grid start and 7 days ago → later of +35 days and month grid end | Accepted (history amended 2026-10-21) |
| ADR-9 | Calendar colors and names from config; Graph IDs never reach the browser | Proposed |
| ADR-10 | No ICS/public calendar links: anyone holding the link could read where people will be | Proposed |
| ADR-11 | Full independence from other projects: no shared accounts, app registrations, credentials, code, config, tooling or runtime data (§0) | **Accepted 2026-10-04** |
| ADR-12 | Display defaults: 12-hour clock, week starts Sunday, `show_notes` option (default on; off removes notes in the sync job) | **Accepted 2026-10-04** |
| ADR-13 | Hardware: Raspberry Pi 5 (4 GB) + a plain 21.5–24" 1080p IPS USB-touch monitor in portrait (§9.0) | Proposed: recommendation |
| ADR-14 | Font: Inter v4.1 (OFL 1.1), upright variable woff2, vendored with licence and SHA-256 (§10.4) | **Accepted 2026-10-04** |
| ADR-15 | Per-calendar detail level (`full` / `titles` / `busy`). Outlook offers only "Can view" / "Can edit", so it is enforced by requesting only the allowed fields (`$select`) and by normalisation; Health = titles and times only (§5.1, §5.3, §5.4) | **Accepted 2026-10-21; amended after S1** |

## 14. Open questions
**Resolved 2026-10-21:** reference screenshots not needed; the approved mockup is the visual reference (§10.1).

**Resolved 2026-10-04:** viewer account (ADR-1, I'm creating it); 12-hour clock, Sunday week start, notes optional (ADR-12); font (ADR-14); independence from other projects (ADR-11).

**Still open:**
1. **One more calendar:** not shared to the viewer account for now (decided 2026-10-21); share as "Can view" when wanted.
2. **Hardware:** not bought yet; §9.0 recommends a setup. S3 runs once it arrives, and nothing in Phases 1–3 depends on it.
3. **Paging to other months (possible later feature, not in scope).** The page shows only what the synced copy holds (ADR-8: the month grid or the past week, through `lookahead_days` ahead, 35 by default, at most 120). Fetching from Graph when someone pages would give up what the separation of sync and display buys: a fast page that works through outages, a Pi web service with no network at all, and no Graph token on Azure's request path. If paging is wanted:
   - **Step 1, a wider copy refreshed in tiers:** the current and next month every 5 minutes as now; a far range (for example 3 months back to 12 ahead) hourly. Paging inside it is instant and works offline. Watch daily recurring series, which multiply over a year; the existing page and event caps (§5) bound them.
   - **Step 2, further out on request, still through the sync:** paging past the far range shows "loading…" and leaves a small request (a month); the sync fetches it within seconds and adds it to the copy. The page never calls Graph. On the Pi the request is a local file that wakes the sync service (systemd path activation), so the web service keeps no network access.

## 15. Viewing away from home through Azure (Phase 5)

**Status: signed off 2026-10-21** (questions answered in §15.12). Next: the spikes R1–R5 (short throwaway experiments), then the build.

### 15.1 Goal and scope
- **G12. The same calendar page from a phone, iPad or browser anywhere** (for example from work or while travelling), because the Outlook app's calendar view is hard to use. Read-only, exactly as on the wall.
- **Only a few named people,** each signing in with their own personal Microsoft account. **Everyone else is refused, including people who sign in successfully.**
- **Personal devices only.** Not devices managed by an employer or other organisation, and not shared computers.
- **The Raspberry Pi kiosk is unchanged:** home-only, loopback-only, with its own sync.
- **Not in scope:** editing, notifications, any calendar beyond those already shared to the viewer account.

### 15.2 Options considered

| Option | Verdict |
|---|---|
| **Azure web app behind Microsoft sign-in, with an allowlist** | **Proposed.** No app or certificate to install; works on any network; Microsoft sign-in with MFA; the data already lives with Microsoft. Cost: a public sign-in page and an Azure environment to secure. |
| Tailscale private network + identity check | Strong (nothing public), but needs a VPN app per device, some networks block VPNs, and it adds a third party. Kept as the fallback. |
| Router port-forwarding to the Pi | **Rejected:** puts the home network on the internet. |
| Mutual TLS on the home network only | Doesn't meet the "from anywhere" need. |
| Outlook app | Already possible, but its interface is the reason this project exists. |

### 15.3 Architecture

```
 Phone / iPad / browser                             Microsoft sign-in (personal accounts)
        |  HTTPS                                            ^
        v                                                   | redirect, MFA
 +--------------------------------------------------------------------------------+
 | Azure subscription for this project only (separate from any other project)     |
 |                                                                                |
 |  Function App (Flex Consumption, Python, max 1 instance)                       |
 |   built-in authentication: "Require authentication", personal accounts only   |
 |   platform allowlist: 3 account object IDs  -> anyone else: 403, code never runs|
 |   +------------------------------+     +------------------------------------+ |
 |   | HTTP: page, /api/* (our code |     | Timer: sync every 5 min            | |
 |   | re-checks the allowlist)     |     | Graph Calendars.Read as the viewer | |
 |   +---------------+--------------+     +-------------------+----------------+ |
 |                   | read                                   | write             |
 |                   v                                        v                   |
 |        Storage: events.json (private; managed identity only; no shared keys)  |
 |        Key Vault: viewer refresh token only (no keys, no client secrets)      |
 |        Application Insights / Log Analytics (no event content)                |
 +--------------------------------------------------------------------------------+
```

- **One Function App** runs both parts: the **timer** (the existing sync code: normalisation, cleaning, `$select` per detail level, Health titles only) and the **HTTP** side (the existing page and `/api/*` contract). The timer function exposes no HTTP endpoint.
- **Same page, same rules:** the frontend is unchanged (CSP with Trusted Types, text-only rendering, no links). Server-side checks adapted for Azure: the Host check accepts only the app's own hostname, and `Sec-Fetch-Site` and GET-only stay as they are.
- **Same calendars and the same detail levels as the wall** (decided 2026-10-21): Health shows titles and times only, everywhere.
- **Data at rest:** `events.json` in a private blob container, readable and writable only by the Function App's managed identity; storage shared-key access disabled. No Graph IDs; Health has no location or notes; nothing else is stored.

### 15.4 Who can see it: three independent checks (deny by default)
1. **Sign-in is required for every request.** Built-in authentication is set to *Require authentication*: a browser without a session is redirected to Microsoft sign-in, and API calls get 401. Anonymous requests never reach our code. The app registration is **personal Microsoft accounts only**, so work and school accounts can't sign in at all.
2. **The platform allowlist.** The built-in authorization policy (`allowedPrincipals.identities`) lists the **object IDs of the allowed accounts**, and `WEBSITE_AUTH_AAD_ALLOWED_TENANTS` allows only the personal-account tenant. A signed-in account that isn't listed gets **403 from the platform**; our code never runs for it.
3. **Our code checks again, against its own copy of the list.** Every request reads the platform's `x-ms-client-principal` header, and our code serves data only if the object ID and tenant match **the code allowlist, a Key Vault secret** (ADR-28). If the header is missing (for example built-in authentication was switched off by mistake), the answer is 403. The header can't be supplied by a caller; the platform removes and replaces it. Unit tests cover listed, unlisted, wrong-tenant, missing and malformed principals.
- **Allowlist by object ID, not email:** the ID is fixed for the account, while an email alias can change.
- **Enrolment:** to learn the IDs, an explicit, time-limited *enrolment setting* (never implied by an empty list) shows a signed-in user **only their own ID** and no calendar data, and turns itself off after 30 minutes. Used in R1 for every account.
- **Verified after every deploy:** a check signs in with an account that is *not* on the list (the viewer account itself is a good choice) and confirms a 403.

**Guarding the allowlists (ADR-28).** The IDs aren't secret (knowing one doesn't let anyone sign in); the risk is **tampering**: someone adding an ID, or emptying a list. R1 showed that **an empty platform list means "everyone"**, not "no one".
- **Two lists, two owners; a person must be on both.** The platform list (layer 2) is set only by the prod deploy (Bicep, after my approval in GitHub); its IDs live as variables on GitHub's protected prod environment, not in the repository. The code list (layer 3) is a Key Vault secret written **only by me**, with a small script and MFA; the deploy identity (Contributor on the resource group) has no data access to Key Vault, and the Function App's own identity can only *read* that one secret. Tampering through one path can't let anyone in.
- **Fail closed:** the Bicep refuses an empty list, a malformed ID or more entries than the configured maximum. Our code caches the secret for a few minutes and **denies everyone** if it is unreadable, empty or malformed.
- **Every change is seen:** a free Activity Log alert emails me on any write to the Function App's sign-in or app settings; Key Vault's access log alerts on any write to the secret (and on reads by any identity but the Function App's). Key Vault keeps every version, so a bad change can be rolled back.
- **Drift check:** a scheduled job compares the two lists, repeats the unlisted-account 403 check and alerts on any difference.
- **Code that skips the check:** branch protection (pull requests I review), tests that fail if the check is weakened or removed, and the drift check's 403 test.
- **Not covered:** a fully compromised administrator (my Azure or GitHub account) could change both lists or anything else. Defences: MFA, the change alerts, Microsoft's account alerts. The blast radius is limited: Azure holds no irreplaceable data (everything rebuilds from Bicep plus one consent), the wall at home doesn't depend on Azure, and revoking the cloud sync's consent cuts off calendar access (§15.8).

### 15.5 Sessions and devices
- Session cookie lifetime **12 hours** (decided 2026-10-21), then sign in again. *Later iteration, if wanted: a shorter session when signing in from abroad. The platform's session length is one setting for the whole app, so this would be our own check (for example on the sign-in's country), with its own privacy review; Microsoft's location-based Conditional Access isn't available for personal accounts.* The token store is **off**, because the page needs no Microsoft tokens; the sign-in only establishes who is asking.
- **MFA on every allowed account** (Microsoft account security settings).
- **Personal devices only.** On a shared computer, sign out (`/.auth/logout`); a sign-out link is added to the page.
- iPhone and iPad: works in Safari and as an "Add to Home Screen" app; **needs iPadOS/iOS 15.4 or later** (§10). Older Safari lacks Trusted Types; the text-only rendering still applies. *The iPad to be used is under two years old (2026-10-21), so it runs a current iPadOS and meets this; spike R5 still confirms on the device.*

### 15.6 Graph access in the cloud
- A **new app registration for cloud sync**, separate from the Pi's: personal accounts only, `Calendars.Read`, and a **confidential client** whose only credential is a **federated credential that trusts a dedicated user-assigned managed identity** (the *sync identity*; ADR-27, decided 2026-10-22, replacing the Key Vault signing key that R3 proved). Every token request carries a fresh assertion from that identity, which only the Function App can obtain. So **a stolen refresh token alone is useless**, and there is no key or certificate to protect, expire or rotate.
- **Two identities, one job each:** the *sign-in identity* (ADR-26) is trusted only by the web sign-in registration; the *sync identity* only by the cloud-sync registration. Neither is assigned to anything else.
- **The refresh token is stored in Key Vault, not in storage.** Only the sync identity can read or replace it; access to that one secret, nothing else. Each refresh stores the new token as a new version and disables the previous one (R3).
- **One-time consent through an admin-only page** (ADR-27): `/admin/consent` sits behind the same sign-in **and** a separate admin allowlist in our code (my object ID only; anyone else, including the other allowed people, gets 403). It sends the browser to Microsoft to sign in as the viewer account, with PKCE and a single-use `state` bound to my session. The callback accepts only a top-level GET with that unused `state` (so the GET-only rule of §8 holds), redeems the code with the sync identity, **accepts the result only if the account is the configured viewer and the scopes are exactly `Calendars.Read` plus OpenID**, writes the refresh token straight to Key Vault, and shows only "connected as <viewer>". The PKCE verifier and `state` are kept server-side in the private container for 10 minutes at most, so no encryption key is needed. The token is never shown, logged or written elsewhere. Used at setup, and again only if consent is revoked or the token lapses. *(The paste-back tool R3 used from the laptop can't work here: a laptop can't obtain the Function App's identity token.)*
- The Pi keeps its own public-client sign-in (ADR-2). The two are independent: revoking one doesn't affect the other.
- **A third app registration** is used only for the web sign-in: personal accounts only, `openid profile email`, **no Graph permissions at all**, redirect `https://<app>/.auth/login/aad/callback`. Its credential: **a federated credential that trusts a user-assigned managed identity used for nothing else; no client secret exists** (spike R2 passed, §15.13, ADR-26).

### 15.7 Azure hardening
- **A dedicated subscription** for this project (decided 2026-10-21), with no shared identities, credentials or role assignments (ADR-11).
- Admin access with MFA; no standing data-plane roles for my own account; deployment manual from the laptop, as with code today. Infrastructure as Bicep in the repo; **no secrets in it**.
- Key Vault: RBAC, soft delete, purge protection, all access logged; alert on any access by an identity other than the Function App.
- Function App: HTTPS only; **minimum inbound TLS 1.3** for the site and its deployment (SCM) endpoint (decided 2026-10-22; every current browser and iOS 12.2+ supports it); **HTTP/2 on**; FTP and basic-auth publishing off; remote debugging off; **maximum instance count 1** (caps cost even under a flood of requests). HTTP/3 (QUIC) isn't offered by App Service or Functions (only by edge services such as Front Door, about $35/month) and isn't needed. Outbound calls (Graph, Key Vault) refuse anything below TLS 1.2 and use 1.3 where the server offers it.
- **Budget alert at $5/month** and an alert on unusual request volume or repeated 403s.
- **Cost kill switch (decided 2026-10-22):** the budget alert triggers an action that **stops the Function App**. Runaway cost becomes an outage of the away-from-home page only; the wall at home is unaffected, and I restart the app once the cause is understood.
- **Request floods (DDoS):** anonymous requests are answered by the platform's sign-in redirect and strangers who sign in get the platform's 403, so **our functions don't run for them** and no executions are billed; the instance cap bounds any execution-time cost (worst case about $31/month if one instance were busy all month); Azure's built-in network DDoS protection applies at no cost; a web application firewall (Front Door, about $35/month) is out of proportion. Spike R6 measures what a flood actually costs.
- **Network:** baseline (public endpoints, Entra-only access to Key Vault and storage, no keys). Private endpoints would add about $30/month (mainly 3–4 private endpoints at about $7.30 each) and are not proposed for this data.

### 15.8 New threats

| # | Threat | Mitigation | Residual |
|---|---|---|---|
| T20 | Anyone on the internet finds the URL | Only Microsoft's sign-in page is reachable; personal accounts only | Low |
| T21 | A stranger signs in with their own Microsoft account | Platform allowlist (403) + our code's allowlist (403) + post-deploy check with an unlisted account | Very low |
| T22 | Built-in authentication misconfigured or turned off | Our code denies any request without a valid allowlisted principal; Bicep keeps the setting in code | Low |
| T23 | An allowed person's account is taken over | MFA; remove the ID from the allowlist; read-only data | Low |
| T24 | Session left open on a shared device | Personal devices only; 12-hour session; sign-out link | Low–Med (behavioural) |
| T25 | Function code compromised | Identities limited to one secret and one container; no outbound except Graph and Key Vault by design | Low, contained |
| T26 | Azure account compromise | MFA; separate subscription; Key Vault logs and alerts; budget alert | Med (same as any cloud account) |
| T27 | Cost abuse (request flood) | Platform rejects anonymous and unlisted requests before our code; max 1 instance; free grant; request-volume alert; budget alert that stops the app (kill switch); measured in R6 | Low |
| T28 | Refresh token stolen from Key Vault | Useless outside the Function App: Microsoft also requires an assertion from the sync identity (ADR-27; R3 proved the same property with a key, R10 repeats it); revoke consent | Low |
| T29 | Someone else completes the consent page (a stranger, another allowed person, or a forged callback) | Admin allowlist in code; single-use `state` bound to my session; only the configured viewer account with exactly `Calendars.Read` is accepted; tested in R10 | Low |
| T30 | An allowlist is tampered with or emptied (a bad deploy, a mistaken edit) | Two lists with different owners, a person must be on both; fail closed on empty or malformed lists; change alerts; drift check (§15.4, ADR-28) | Low |

**Revocation, fastest first:** remove the person's object ID from both allowlists; stop the Function App; remove the calendar shares from the viewer account; revoke the cloud-sync app's consent; delete the app registrations.

### 15.9 Cost estimate (USD per month)
*Corrected 2026-10-22: the first estimate (about $0.20) left out the alert rules; their cost was observed on this account's existing subscription.* Assumptions: sync every 5 minutes (8,640 runs a month, about 3 s each at 0.5 GB); a few people opening the page for a few minutes a day, polling once a minute while open. Prices from Azure's pricing pages and third-party summaries, October 2026; the official page shows the Flex free grant but not per-unit prices, so those are to be confirmed in the Azure pricing calculator for the chosen region.

| Item | Basis | Estimate |
|---|---|---|
| Function App, Flex Consumption | ~13,000 GB-s and ~15,000 executions; **free grant 100,000 GB-s and 250,000 executions per subscription** | **$0** (if it ever exceeded the grant: about $0.000026/GB-s and $0.40 per million executions) |
| Storage (events file + Functions host storage) | < 1 GB, a few thousand operations | < $0.10 |
| Key Vault (Standard) | ~10,000–20,000 operations (get, set; no signing since ADR-27) at about $0.03 per 10,000; no keys or certificates | ~$0.05 |
| Application Insights / Log Analytics (data) | well under the free monthly allowance | $0 |
| **Alert rules** (Key Vault access by an unexpected identity; repeated 403s or unusual volume) | log-search alert rules are billed per rule per month; **observed on this account: about $0.31–0.33 per rule for three weeks**, so roughly $0.45–0.50 per rule per month | **about $1.00** |
| Outbound data | well under the free monthly allowance | $0 |
| **Total** | | **about $1.20 a month; budget alert at $5** |

Alternatives priced for comparison: Azure Static Web Apps Standard (needed there for custom sign-in) about **$9/month** plus the Function App; App Service B1 about **$13/month**; private endpoints about **+$30/month**. **A custom domain is optional:** the app works on its `*.azurewebsites.net` address with Microsoft's certificate; a domain of our own is about $10–15 a year.

A dedicated subscription gets its own free grant, so this cost doesn't depend on any other project's usage.

### 15.10 Spikes before building

| Spike | Question | Pass |
|---|---|---|
| R1 | Built-in authentication with *personal accounts only*: does sign-in work for every allowed account, and does the platform allowlist (`allowedPrincipals.identities` with personal-account object IDs) return 403 for an unlisted personal account? | Every allowed account gets in; the viewer account gets 403 from the platform |
| R2 | Can the web sign-in app use a managed-identity federated credential instead of a client secret in this configuration? | Yes, or the secret-in-Key-Vault fallback is chosen |
| R3 | Confidential-client sync for the viewer account with a Key Vault signing key, from Flex Consumption | Token refresh works only with the Key Vault signature |
| R4 | Cold start: how long does the first page load take after an idle hour, on a phone on mobile data? | Under about 5 seconds, or decide whether an always-ready instance is worth its cost |
| R5 | The actual phones and iPad: Safari versions and "Add to Home Screen" behaviour with the sign-in redirect | Works on the actual devices |
| R6 | Does a flood of anonymous requests cost anything? Send 10,000 unauthenticated requests to the test app and read the billing metrics (execution count and execution units) | No executions billed for rejected requests, or a measured rate the kill switch is sized for |

### 15.11 Decisions (accepted 2026-10-21)

| ADR | Decision |
|---|---|
| ADR-16 | Remote viewing through an Azure Function App behind built-in Microsoft sign-in; the Pi kiosk stays home-only |
| ADR-17 | Three-layer authorization: require sign-in; platform allowlist of object IDs and tenant; the same allowlist re-checked in code; deny by default |
| ADR-18 | Cloud sync as a confidential client with a non-exportable Key Vault key; refresh token in Key Vault only *(credential amended by ADR-27: a managed identity instead of the key)* |
| ADR-19 | Three separate app registrations: Pi sync (public), cloud sync (confidential), web sign-in (no Graph permissions) |
| ADR-20 | **Dedicated Azure subscription** (decided) with no shared identities or credentials; baseline network; max 1 instance; $5 budget alert |
| ADR-21 | Tailscale with identity check remains the documented fallback if Azure is rejected |

### 15.12 Review answers (2026-10-21)
1. **Subscription:** a dedicated Azure subscription.
2. **Session length:** 12 hours on every device. Location-aware session length (for example abroad) is a possible later iteration (§15.5).
3. **Detail away from home:** the same calendars and detail levels as the wall.
4. **Devices:** the iPad is under two years old (model and iPadOS version to be confirmed); the phones are still to be confirmed. Both are checked in spike R5.

**Signed off 2026-10-21.** Next: the spikes R1–R5. The Azure subscription and the two new app registrations are created by hand (by me, not by a script), as with the existing ones. *(Superseded for the app registrations by §17.1 and R1's finding: they are created and corrected by script, never through the portal's quick path.)*

### 15.13 Spike results (2026-10-22)
All run in a throwaway resource group in the project's subscription, with test app registrations; deleted after the build (§17.2 environments replace them).

| Spike | Result | What it changes |
|---|---|---|
| R1 sign-in and allowlist | **Pass.** Every allowed account signed in (a laptop browser and Safari on iOS/iPadOS); their object IDs were collected through the enrolment window, which was then closed. With the platform allowlist holding exactly those IDs, each still gets in, and the viewer account (a real personal account that signs in successfully) gets the **platform's 403**; our code never runs for it. | The portal's quick path set **four things wrong** for personal accounts (below); the build creates the registration and settings by script/Bicep only |
| R2 web sign-in without a secret | **Pass.** Built-in authentication redeems the personal-account sign-in with a client assertion from a **user-assigned managed identity** (federated identity credential), using the documented `OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID` setting. Microsoft's documentation doesn't say whether this works for personal accounts; it does | No client secret anywhere, nothing to rotate or leak (ADR-26). **Proven:** after the secret was deleted from the app settings and the registration (0 secrets, 0 certificates, 1 federated credential), a fresh sign-in still worked |
| R3 cloud sync with a Key Vault key | **Pass.** Refresh token alone: refused (`invalid_client`, 70002). Refresh token + an assertion signed by a different key: refused (700027). Refresh token + an assertion signed inside Key Vault: token issued, Graph read works. The refresh token rotates (new secret version, previous one disabled). The one-time consent used the paste-back sign-in and wrote the token straight to Key Vault | T28 confirmed with a key. **Superseded by ADR-27** (a managed identity instead of the key); R10 repeats these tests with it |
| R4 first load from cold | **Pass.** With no instance running (app stopped and started, confirmed in the instance metrics), a signed-in reload on an iPhone took **2.6 s over mobile data** and 1.9 s over Wi-Fi, each starting a new instance; the next reloads took 0.5–0.6 s. Two samples, on the tiny test page; the real app loads more code at start-up | Well under the 5 s pass mark. Prod keeps its always-ready instance (ADR-23) for the stricter 2 s objective (§17.9); dev measures the real app's cold start |
| R6 flood cost | **Pass.** 2,200 anonymous requests: answered by the platform (401), **0 billed executions**. With one instance, ~56 requests/s and a few timeouts | Floods cost nothing; with 1 instance they hurt availability |
| R7 concurrency and scale | With up to 4 instances and per-instance concurrency 8: 4–32 parallel connections ran at 84–346 requests/s, p95 67–119 ms, **0 timeouts, 0 billed executions**. Scale-out follows sustained load, not seconds-long bursts | The R6 timeouts came from the cap of 1 instance; §17.3's max 4 confirmed. Signed-in load (our code running) still to measure in dev |

**Settings proven for personal accounts (the build sets all of them in code):**
- App registration: `signInAudience` **PersonalMicrosoftAccount**, which needs `api.requestedAccessTokenVersion` **2** set first. *(Quick path: AzureADMyOrg.)*
- Issuer: `https://login.microsoftonline.com/9188040d-6c67-4c5b-b112-36a304b66dad/v2.0`, the personal-account tenant. *(Quick path: the directory's legacy `sts.windows.net` issuer.)*
- `WEBSITE_AUTH_AAD_ALLOWED_TENANTS` = the personal-account tenant. *(Quick path: the directory tenant, which blocked every sign-in.)*
- Session cookie 12 hours *(quick path: 8)*; token store off; `defaultAuthorizationPolicy.allowedApplications` = the app's own client ID; `allowedPrincipals.identities` = the allowed object IDs.
- Personal-account principals arrive as claim `objectidentifier` in the form `00000000-0000-0000-xxxx-xxxxxxxxxxxx`, tenant = the personal-account tenant, provider `aad`. Our code's allowlist check (§15.4 layer 3) uses these.
- Per-instance HTTP concurrency must be set explicitly: Python's default of 1 stalled a capped app for 5–40 s.
- TLS 1.3 minimum works (a TLS 1.2-only client is refused at the handshake); deployment works with basic-auth publishing off.

**Build notes from R3:**
- MSAL gets the client assertion as a **callable**, so every token request carries a freshly signed, short-lived JWT, not one long-lived string.
- MSAL recommends `response_mode=form_post` for the sign-in. The Pi's paste-back sign-in can't use it, because the code is copied from the address bar. Accepted: the code is single-use, expires in minutes, and is useless without the PKCE verifier (held only in the running process). The cloud consent page (§15.6) also uses a query response, so its callback stays a plain top-level GET under the existing GET-only and cookie rules; the code goes only to our own HTTPS callback and is useless without the PKCE verifier and the sync identity.

**Decided 2026-10-22: cloud sync with a managed identity instead of a Key Vault key (ADR-27).** R2 shows the personal-account token endpoint accepts a managed-identity assertion. The cloud-sync registration trusts a second, dedicated user-assigned identity instead of a certificate. The property R3 proved still holds (a stolen refresh token is useless outside the Function App), and the signing key, the certificate's yearly expiry and its manual re-upload to the registration all go away. Key Vault still holds the refresh token. Because a laptop can't obtain the identity's token, consent moves from the laptop tool into an admin-only page (§15.6). **Pending R10:** if the refresh-token request with the identity's assertion fails, the design falls back to ADR-18's Key Vault key and the laptop consent tool, both already proven.

| ADR | Decision |
|---|---|
| ADR-26 | The web sign-in has **no client secret**: built-in authentication uses a federated credential that trusts a user-assigned managed identity, which is assigned only to that environment's Function App (accepted 2026-10-22, R2) |
| ADR-27 | Cloud sync's credential is a federated credential that trusts a **second, dedicated** user-assigned managed identity, not a Key Vault key; consent through an admin-only page in the Function App (accepted 2026-10-22, pending R10; fallback ADR-18) |
| ADR-28 | Two allowlists with different owners: the platform list set only by the approved deploy, the code list a Key Vault secret only I can write; both fail closed; change alerts and a drift check (accepted 2026-10-22, §15.4) |

## 16. Ownership and handover

What exists, who controls it, and how to hand it to someone else (for example if I step back). Do it in this order, and remove my own access last.

| # | Piece | How it's handed over | Notes |
|---|---|---|---|
| 1 | **Password manager** | Name the successor for **emergency access** now, so step 2 onward is possible even if I can't help | Holds the admin, viewer-account and GitHub credentials |
| 2 | **GitHub repository** (`thomasjey/wall-calendar`, public) | Add the successor as a collaborator, or **Settings → Transfer ownership** to their account | The calendar keeps running without it; it's needed only to change or rebuild things |
| 3 | **Microsoft Entra directory** (admin, app registrations) | Make the successor a **Global Administrator**; add them as **owner** of each app registration | Registrations can't move to another directory; to use the successor's own directory, re-create them there (about 5 minutes each) and sign in again |
| 4 | **Azure subscription** (Phase 5) | Add the successor as **Owner**, then **Transfer billing ownership** to their account and payment method; change the budget alert's email | Resources keep running during the transfer |
| 5 | **Viewer account** (personal Microsoft account) | Either hand over its password and move its MFA and recovery details to the successor, or (cleaner) the successor creates a new viewer account, the calendars are re-shared to it, and `fwcal auth login` is run again (Pi and laptop; plus the cloud sync's admin consent page in Phase 5, §15.6) | Remove the old viewer account's shares afterwards |
| 6 | **Calendar shares** | Owned by the calendars' owners, not by this project; they re-share to a new viewer account if one is created | §5.1 |
| 7 | **Allowlists** (Phase 5) | The successor edits the allowed account object IDs in the code allowlist and the platform allowlist (§15.4) | Remove anyone who should no longer see the calendar |
| 8 | **Raspberry Pi** (Phase 4) | Physical hand-over; add the successor's SSH public key, remove mine | `fwcal check` afterwards |
| 9 | **This design and the setup checklist** | Travel with the repository | DESIGN.md, deploy/SETUP.md, README.md |

**Last:** remove my own access in reverse order (Pi key, allowlist entry, Azure roles, directory roles, GitHub collaborator), then run the revocation runbook's checks (§11.3, §15.8) to confirm nothing still depends on my accounts.

## 17. Production profile

**Status: signed off 2026-10-22.** Goal (decided 2026-10-22): build and run the away-from-home service (§15) **as a real production workload would be**, emulating production security and systems design, while staying **under $10 a month** for dev and prod together. Where §15 and this section differ, this section wins once signed off.

### 17.1 Principles
- **Everything as code:** infrastructure in Bicep, previewed with `what-if` before every change; the portal is read-only. (R1 showed why: the portal's quick path got three sign-in settings wrong.)
- **No stored deployment secrets:** GitHub Actions deploys through OpenID Connect federation to Azure; no publish profiles, no keys.
- **Production practices cost time, not money:** expensive components are **switches** in the Bicep (parameters), default off, so they can be turned on to learn and off to save money.
- **Measure, don't guess:** concurrency, instance limits and SLOs are set from load tests.

### 17.2 Environments
| Environment | Where | Purpose | Always-ready | Cost |
|---|---|---|---|---|
| **dev** | resource group `rg-wallcal-dev` in the `wall-calendar` subscription | every merge to `main` deploys here automatically | no (scale to zero) | ~$0 |
| **prod** | resource group `rg-wallcal-prod` | deploys only from a tagged release, after a manual approval in GitHub | **yes, 1 instance** | ~$6.50 |

Each environment has its **own** Function App, storage, Key Vault, managed identity, app registrations (web sign-in and cloud sync) and allowlist. Dev's allowlist holds only my account; dev syncs a test calendar, not real ones (§17.6).

### 17.3 Compute and scaling
- **Scale-out: up to 4 instances** (was 1). A flood or a busy moment no longer takes the page down; cost stays bounded by the kill switch (§17.8).
- **Per-instance HTTP concurrency: set from load tests** (start at 8; R1 showed the Python default of 1 stalls a capped app). R7: with 8 and up to 4 instances, the sign-in layer answered up to ~350 anonymous requests/s with no timeouts (§15.13).
- **One always-ready instance in prod** (no cold start for anyone). 512 MB.
- **Async handlers** for all HTTP functions; no blocking I/O on the request path.
- **Timeouts:** `host.json` `functionTimeout` 30 s for HTTP-serving functions, 5 minutes for the sync; explicit connect/read timeouts on every outbound call (Graph, Key Vault, storage); the platform's front end ends any HTTP request after about 230 s.
- **Health endpoint** (`/api/health`, behind sign-in like everything else) reporting sync age and dependency status, without event content.
- **Zone redundancy: off** (switch). It needs at least two always-ready instances, beyond this budget.

### 17.4 Edge and network (switches, default off)
| Switch | When on | Cost |
|---|---|---|
| `edgeProtection` | Azure Front Door Standard + WAF: managed rules, rate limiting per client, bot and geo filtering; the Function App accepts traffic **only** from this Front Door (access restriction on its service tag plus the `X-Azure-FDID` header) | ~$35/month |
| `privateNetworking` | VNet integration; Key Vault and storage through private endpoints only, public access disabled | ~$30/month |

With both off (the default), protection comes from the sign-in and allowlist layers, the instance cap, the kill switch and Azure's built-in network DDoS protection (§15.7, R6).

### 17.5 CI/CD and supply chain
- **Pull request checks (GitHub Actions):** unit, server and adversarial tests; Ruff lint; Bicep build and lint; `pip-audit` on `requirements.txt`; GitHub dependency review; CodeQL code scanning; secret scanning with push protection where the plan allows; the repository's own pre-commit checks re-run in CI.
- **Build:** one artifact per release, from hash-pinned dependencies (`--require-hashes`), with an **SBOM** (CycloneDX) and a build provenance attestation stored with the release.
- **Deploy:** OIDC federation from GitHub to a deploy identity that has **Contributor on the environment's resource group only** (never the subscription); dev on merge, prod on a tagged release after manual approval; `what-if` output attached to the approval.
- **Branch protection on `main`:** pull requests only, required checks, no force pushes.
- **Why the repository is public (decided 2026-10-22, ADR-29):** on a free plan, branch protection, deploy environments with required reviewers, CodeQL, secret-scanning push protection, dependency review and artifact attestations are available only for public repositories. Security doesn't depend on the code being secret. The repository holds no secrets, no IDs and **no references to the people who use it**; the pre-commit check blocks such words (§0), and real names, IDs and calendar details live only in gitignored files and in Key Vault. Publishing started a new repository from one fresh commit, so earlier wording isn't in its history; the earlier private repository is kept as an archive.

### 17.6 Testing beyond unit tests
- **Load tests** (in dev): find the per-instance concurrency and instance count that meet the SLOs; record the results here.
- **Failure tests:** Graph unavailable or throttling; token expired or revoked; Key Vault unreachable; storage unreachable; a request flood. Each must degrade as designed (stale data with a status, a clear error, no secrets in errors).
- **Post-deploy checks:** an unlisted account gets 403; anonymous requests get 302/401; TLS 1.2 is refused; security headers present.
- **Dev data:** a separate test calendar with synthetic events, shared to a separate dev viewer account, so dev never holds real data.

### 17.7 Observability
- **Application Insights** (workspace-based) with the OpenTelemetry distro; sampling on; daily data cap set so logging can't exceed the budget.
- **Privacy-safe telemetry:** request paths, status codes, durations, dependency calls, sync counts; **never** event content, names or account IDs in logs (a hashed principal for correlation at most).
- **Dashboards:** availability, p95 latency, error rate, sync freshness, instance count, cost.
- **Alerts** (email): failed syncs for 30 minutes; error rate above 5%; p95 latency above target for 15 minutes; Key Vault access by an unexpected identity; request volume far above normal; budget thresholds.

### 17.8 Cost controls
- **Budget $10/month** on the `wall-calendar` subscription (both environments); email alerts at 50%, 80% and 100% of actual and 100% of forecast.
- **Kill switch at 100% of actual ($10):** the budget's action group runs an automation that stops the **prod and dev** Function Apps. The wall at home is unaffected; restarting is a documented manual step.
- **Application Insights daily cap** so telemetry can't run away.

| Item | Monthly |
|---|---|
| Always-ready instance (prod, 512 MB, Flex baseline rate about $0.000004/GB-s; to confirm, R8) | ~$5.20 |
| Alert rules (2, observed rate) | ~$1.00 |
| Key Vault, storage, Application Insights (under free allowances) | ~$0.30 |
| On-demand executions (within the free grant) | $0 |
| Dev environment (scale to zero) | ~$0 |
| **Total** | **~$6.50**, budget and kill switch at $10 |

### 17.9 Service level objectives
| SLO | Target |
|---|---|
| Availability of the away-from-home page (successful responses to allowed users, monthly) | 99.5% |
| Latency, warm (p95, server side) | under 300 ms |
| First load after idle | under 2 s (always-ready instance) |
| Data freshness | events no older than 10 minutes, 99% of the time |
| Security | zero requests served to principals outside the allowlist (verified by the post-deploy and periodic checks) |

The wall at home keeps its own objectives: it works without the internet, from cached data.

### 17.10 Operations
Runbooks in the repository: incident response (page down, sync failing, suspected compromise); credential review (there are no keys or client secrets to rotate; the refresh token rotates itself; re-consent through the admin page); revocation (§15.8); disaster recovery (rebuild an environment from Bicep and re-consent); restoring after the kill switch. A short post-incident note for anything that triggers an alert.

### 17.11 New experiments
| Experiment | Question | Pass |
|---|---|---|
| R7 | Concurrency and scale: at 4, 8, 16 and 32 parallel connections, with up to 4 instances, what latency, throughput and timeouts do anonymous and signed-in requests see? | Settings that meet the SLOs are chosen and recorded |
| R8 | Always-ready cost: one 512 MB always-ready instance for a few days | Measured cost within the estimate |
| R9 | GitHub Actions deploy through OIDC to the dev resource group, with no stored secret | Deploy works; the identity can't touch prod or anything outside dev |
| R10 | Cloud sync with its managed identity (ADR-27), in dev: consent through the admin page; refresh-token redemption with the sync identity's assertion; token rotation. Negatives: refresh token with no assertion; assertion from the *sign-in* identity; consent completed with a different account; consent page opened by a non-admin; a reused or forged `state` | The positive path works and every negative is refused; otherwise fall back to ADR-18 |

### 17.12 Decisions (accepted 2026-10-22)
| ADR | Decision |
|---|---|
| ADR-22 | Build and run the away-from-home service with production practices: Bicep, dev and prod, OIDC CI/CD with approvals, observability, SLOs, load and failure tests, runbooks |
| ADR-23 | Paid components are Bicep switches: scale-out to 4 **on**; one always-ready instance in prod **on**; Front Door + WAF **off**; private networking **off**; zone redundancy **off** |
| ADR-24 | Budget $10/month with a kill switch that stops both Function Apps at 100% |
| ADR-25 | Python with async handlers stays the implementation language; per-instance concurrency and instance limits come from load tests |
| ADR-29 | The repository is **public**, started fresh with no references to the people who use it; enforced by the pre-commit check (§17.5) |
| ADR-30 | **No MSAL in the cloud:** the cloud code makes three plain OAuth calls (refresh, consent code redemption, managed-identity assertion). Its runtime dependencies are `azure-functions` and `requests` only, pinned with hashes. The Pi and laptop keep MSAL |
| ADR-31 | **Cloud config in Key Vault, written only by me:** calendars (Graph IDs, names, colours, detail levels), display settings, the code allowlist and the admin ID, as one TOML secret. Changing a detail level is as sensitive as changing the allowlist, so it gets the same protection (ADR-28). Nothing personal is in the repository |
| ADR-32 | **Two layers of infrastructure:** *foundation* (identities, Key Vault, storage, role assignments), deployed rarely by me; *app* (Function App, its settings, sign-in settings with the platform allowlist, code), deployed by the pipeline with Contributor on the resource group. The app registrations and their federated credentials are made by a one-time bootstrap script I run; the pipeline has no directory permissions |
| ADR-33 | **Dev uses its own viewer account** with a test calendar of synthetic events (§17.6); until it exists, dev runs on mock data |

| ADR-34 | **Built as (2026-10-22):** four user-assigned identities per environment (app: storage and reading the config; sign-in; sync; deploy), all created with their role assignments in the foundation. Role assignments on the two Key Vault secrets are per secret. **Enrolment** needs both the deploy switch `ENROLMENT_OPEN` (lifts the platform allowlist) and `enrolment_until` in the config (at most 30 minutes ahead); a newcomer sees only their own ID. **Workflow logs are public**, so every environment value (allowed IDs, client IDs, subscription, alert email) is a GitHub environment *secret*, masked in logs; parameters go to a file, never to the output. The cloud config also holds the **time zone** for the sync's day boundaries (Azure runs on UTC). The page and `/api/*` share one catch-all function; other sites may only *navigate* to pages (Fetch Metadata), never call `/api/*` |

*Note on the two identities (ADR-26, ADR-27):* both are assigned to the same Function App, so any of its code can use either. Keeping them apart limits **which app registration trusts which identity**; it is not isolation between pieces of code.

## Appendix: Design history

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-10-04 | First draft: critique of the suggested architecture (§3), full design for review |
| 0.2 | 2026-10-04 | Open questions answered: ADR-1 accepted; ADR-11 independence (§0) and personal details removed from this repo; ADR-12 display defaults and `show_notes`; §9.0 hardware recommendation; ADR-14 Inter font |
| 0.3 | 2026-10-21 | Visual baseline approved from the interactive mockup (§10.1) |
| 0.4 | 2026-10-21 | Phase 1 done (§12.5): stdlib-only, `unittest` instead of pytest, `--config` instead of an environment override, server hardening additions |
| 0.26 | 2026-10-22 | ADR-34: how Phase 5 was built (identities, per-secret roles, two-switch enrolment, secrets-only workflow values, time zone, Fetch Metadata) |
| 0.25 | 2026-10-22 | ADR-29 public repository with no personal references (pre-commit check); Phase 5 build choices ADR-30 to ADR-33 |
| 0.24 | 2026-10-22 | ADR-28: two allowlists with different owners (platform list by the approved deploy, code list in Key Vault written only by me); fail closed; change alerts; drift check (§15.4, T30); §14 paging to other months recorded as a possible later feature; R4 passed (§15.13) |
| 0.23 | 2026-10-22 | §15.13 spike results R1, R2, R3, R6, R7; ADR-26 web sign-in without a client secret; ADR-27 cloud sync with a managed identity instead of a Key Vault key, consent through an admin-only page (§15.6, T29, R10) |
| 0.22 | 2026-10-22 | **§17 signed off** (ADR-22 to ADR-25 accepted) |
| 0.21 | 2026-10-22 | **Proposed** §17 production profile: dev and prod, Bicep, OIDC CI/CD, observability, SLOs, scale-out to 4, always-ready instance, $10 budget with kill switch; experiments R7–R9 (for review) |
| 0.20 | 2026-10-22 | §15.7: TLS 1.3 minimum, HTTP/2, cost kill switch, request-flood analysis; spike R6 |
| 0.19 | 2026-10-22 | §15.9 cost corrected to about $1.20/month (alert rules were missing) |
| 0.18 | 2026-10-21 | §16 ownership and handover checklist; code now in a private GitHub repository |
| 0.17 | 2026-10-21 | **§15 signed off**: remote viewing through Azure (ADR-16 to ADR-21 accepted) |
| 0.16 | 2026-10-21 | §15 review answers: dedicated subscription, 12-hour sessions (location-aware later), same detail as the wall, recent iPad |
| 0.15 | 2026-10-21 | **Proposed** §15: viewing away from home through Azure behind Microsoft sign-in with a three-layer allowlist; cost estimate; spikes R1–R5 (for review, not signed off) |
| 0.14 | 2026-10-21 | ADR-8: the sync window always includes the past week; the clock change on 1 Nov 2026 simulated and correct |
| 0.13 | 2026-10-21 | The Today tab is now Day; other days show a relative hint in the heading (§10.2) |
| 0.12 | 2026-10-21 | Month view: coloured dots instead of text chips (§10.2) |
| 0.11 | 2026-10-21 | **Phase 3 done on the laptop** (§12.8): fetcher, token cache, `calendars --add`; removed shares drop their events; minute-aligned timers, hidden-page pause and 304 answers; end times and hover tooltips |
| 0.10 | 2026-10-21 | **S1 passed** (§12.7): browser sign-in with PKCE replaces device code; `Calendars.Read`; paste-back sign-in on the Pi; ADR-15 enforced by `$select`; ADR-5 correction; one calendar not shared yet |
| 0.9 | 2026-10-21 | Pinned dependencies created for S1; ADR-5: explicit Windows ACL for the token directory |
| 0.8 | 2026-10-21 | ADR-2 amended: `Calendars.Read.Shared`; app registration settings for the redesigned portal; explicit TLS 1.2 minimum |
| 0.7 | 2026-10-21 | Pi deployment files, setup checklist and `fwcal check` (§9); socket activation in the server |
| 0.6 | 2026-10-21 | Phase 1 security review and fixes (§12.6); web socket held by systemd |
| 0.5 | 2026-10-21 | Health calendar: per-calendar detail level (ADR-15); Health shows titles and times only; S2 checks reduced-permission shares; mockup is the visual reference |
