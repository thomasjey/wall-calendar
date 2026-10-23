# Away-from-home service on Azure: setup and operations

How to build and run the service in DESIGN.md §15 and §17. Everything is code
(`infra/`, `tools/azure/`); the portal is for reading only. Nothing in this
repository identifies the people who use it: their account IDs, the alert email
and the calendar details live only in GitHub environment secrets and in Key Vault.

## Layers (ADR-32)

| Layer | What | Deployed by |
|---|---|---|
| `infra/ops.bicep` | $10 monthly budget, email alerts, kill switch that stops both Function Apps at 100% | administrator, once |
| `infra/foundation.bicep` | identities (app, sign-in, sync, deploy), Key Vault, storage, **all role assignments** | administrator, rarely (`bootstrap.ps1`) |
| `infra/app.bicep` | Function App, built-in sign-in with the platform allowlist, monitoring, alerts | GitHub deploy workflow (Contributor on its resource group only) |
| App registrations | web sign-in and cloud sync: personal accounts only, trust in one managed identity each, **no secrets** | administrator (`bootstrap.ps1`) |

## First-time setup of an environment

Signed in with `az login` (MFA) and `gh auth login`:

1. `.\tools\azure\bootstrap.ps1 -Ops -Subscription <id>`: once, for the budget and kill switch.
2. `.\tools\azure\bootstrap.ps1 -Env dev -Subscription <id> -FirstRun`. It shows `what-if` and asks before deploying the foundation, creates the two app registrations, and sets up the GitHub `dev` environment and its secrets.
3. Set the two personal secrets (gh asks for each value; nothing is echoed):
   `gh secret set ALLOWED_OBJECT_IDS --env dev` (comma-separated object IDs) and `gh secret set ALERT_EMAIL --env dev`.
4. Write the cloud config (below): `.\tools\azure\put_config.ps1 -Env dev -File <path>`.
5. Deploy: push to `main` (dev) or push a `v*` tag and approve (prod).
6. Connect the calendar, in one browser window:
   1. Open `https://<app>/` and sign in **as yourself** (an admin). This is the website's own sign-in.
   2. In the same tab, open `https://<app>/manage/consent`. Microsoft's sign-in appears a second time: this one is the calendar consent. Choose the **viewer account** and allow calendar access. Expect "Connected as …".

   Signing in as the viewer at the *first* prompt signs the viewer in to the website, which the allowlist refuses (403). The first sync follows within 5 minutes.

7. Run step 2 again **without** `-FirstRun`, now that the Function App exists: it grants the app identity Reader on its own site, which the hourly drift check needs (DESIGN §15.4). Until then each drift check fails, which the prod alert reports.

Prod is the same with `-Env prod`. For an environment that already exists, a foundation change means running `bootstrap.ps1 -Env <env> -Subscription <id>` again; for prod, do it before the release that needs it.

## The cloud config (Key Vault secret `fwcal-config`)

Kept on the laptop only (all `*.toml` files are gitignored) and uploaded with
`put_config.ps1`, which validates it first. Only the administrator can write it;
the app can only read it. An invalid or unreadable config refuses everyone.

```toml
expected_account = "<viewer account email>"
timezone = "Area/City"          # IANA name, for the sync's day boundaries
lookahead_days = 35

[display]
clock = "12h"
week_start = "sunday"
show_notes = true
# location = [lat, lon]         # optional, rounded to 0.1 degree: the sky backdrop follows real sunrise and sunset

[[calendars]]                   # as in config.example.toml, with graph_id
key = "home"
name = "Home"
color = "#7FB3FF"
graph_id = "<from fwcal calendars>"
detail = "full"                 # full | titles | busy

[access]
allowed = ["<object ID>", "..."]   # the code allowlist (layer 3)
admins = ["<your object ID>"]      # may use /manage/consent
max_allowed = 5
# enrolment_until = "YYYY-MM-DDTHH:MM:SSZ"   # see Enrolment
```

## Enrolment (adding a person)

Both owners act on purpose (ADR-28); an empty list never opens anything.

1. Set `enrolment_until` to at most 30 minutes ahead and upload the config.
2. Set the environment secret `ENROLMENT_OPEN` to `true` and redeploy: the platform lets any personal account sign in.
3. The person signs in at `https://<app>/enrol` and sees **only their own ID**.
4. Add the ID to `ALLOWED_OBJECT_IDS` and to `allowed` in the config; set `ENROLMENT_OPEN` to `false`; remove `enrolment_until`; upload and redeploy.
5. Check: the viewer account (not on the list) still gets 403.

## Operations

- **Kill switch fired:** the budget reached $10, or prod ran more than 10,000 executions in 15 minutes (the flood brake), and both Function Apps were stopped. Find the cause (Cost analysis; request volume and who sent it in Application Insights), revoke the account if it's misuse (below), then `az functionapp start -g rg-wallcal-<env> -n <app>`.
- **Sync alert ("no successful sync for 30 minutes"):** `/api/health` shows the state. `reauth_required` means the consent was revoked or expired: run `/manage/consent` again.
- **Drift alert (prod):** the hourly check found the two allowlists differ, a sign-in setting changed, or it couldn't run (or hasn't succeeded for 3 hours). Application Insights has the reason: `traces | where message startswith "drift"`, or the failed run of `Functions.drift`. It names counts and 8-character hashes (the same hash as in request logs), never IDs. If the lists differ, compare `ALLOWED_OBJECT_IDS` (platform, via the deploy) with `allowed` in the cloud config; fix whichever is wrong, and treat a change nobody made as a suspected compromise. During enrolment the platform list is empty on purpose, so the alert fires until enrolment closes.
- **Revoking a person:** remove their ID from `allowed` (takes effect within 5 minutes) and from `ALLOWED_OBJECT_IDS`, then redeploy.
- **Revoking everything:** stop the Function Apps; remove the viewer's consent to the sync app at account.live.com/consent/Manage; delete the app registrations.
- **Credentials:** there are no keys or client secrets to rotate. The refresh token rotates on every sync; each old version is disabled.
- **Alerts:** any change to the Function App's settings (including the allowlist); a Key Vault secret used by any other identity; no successful sync for 30 minutes; more than 5 server errors in 15 minutes; the drift check (prod); more than 10,000 executions in 15 minutes (prod: stops the apps; dev: email); budget at 50%, 80%, 100% and forecast 100%.
