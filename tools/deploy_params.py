"""Builds the app.bicep parameter file in the deploy workflow from the
environment's GitHub secrets, refusing anything malformed (DESIGN ADR-28).

The values are secrets in a public repository's workflow, so they are written
to a file only and never printed; GitHub also masks them in the logs.

    python tools/deploy_params.py <env> <output.json>

Reads: ALLOWED_OBJECT_IDS (comma-separated object IDs), SIGNIN_CLIENT_ID,
SYNC_CLIENT_ID, ADMIN_PRINCIPAL_ID, ALERT_EMAIL, and optionally
ENROLMENT_OPEN ("true" to lift the platform allowlist for enrolment).
"""

from __future__ import annotations

import json
import os
import re
import sys

GUID = re.compile(r"^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[a-z]{2,}$", re.IGNORECASE)
MAX_ALLOWED = 10
SETTINGS = {"dev": {"alwaysReady": 0}, "prod": {"alwaysReady": 1}}


class ParamError(ValueError):
    pass


def _guid(name: str, value: str) -> str:
    value = value.strip()
    if not GUID.match(value):
        raise ParamError(f"{name} must be a lower-case GUID")
    return value


def build(env: str, environ: dict[str, str]) -> dict:
    if env not in SETTINGS:
        raise ParamError("env must be dev or prod")

    def get(name: str) -> str:
        value = environ.get(name, "")
        if not value.strip():
            raise ParamError(f"{name} is not set")
        return value

    ids = [s.strip() for s in get("ALLOWED_OBJECT_IDS").split(",") if s.strip()]
    if not 1 <= len(ids) <= MAX_ALLOWED or len(set(ids)) != len(ids):
        raise ParamError(f"ALLOWED_OBJECT_IDS: 1..{MAX_ALLOWED} distinct object IDs (never empty: empty means everyone)")
    for i in ids:
        _guid("ALLOWED_OBJECT_IDS entry", i)
    email = get("ALERT_EMAIL").strip()
    if not EMAIL.match(email):
        raise ParamError("ALERT_EMAIL must be an email address")
    enrolment = environ.get("ENROLMENT_OPEN", "").strip().lower()
    if enrolment not in ("", "false", "true"):
        raise ParamError('ENROLMENT_OPEN must be "true" or "false"')

    values = {
        "env": env,
        "allowedObjectIds": ids,
        "enrolmentOpen": enrolment == "true",
        "signinClientId": _guid("SIGNIN_CLIENT_ID", get("SIGNIN_CLIENT_ID")),
        "syncClientId": _guid("SYNC_CLIENT_ID", get("SYNC_CLIENT_ID")),
        "adminPrincipalId": _guid("ADMIN_PRINCIPAL_ID", get("ADMIN_PRINCIPAL_ID")),
        "alertEmail": email,
        **SETTINGS[env],
    }
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {k: {"value": v} for k, v in values.items()},
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: deploy_params.py <dev|prod> <output.json>", file=sys.stderr)
        return 2
    try:
        params = build(argv[0], dict(os.environ))
    except ParamError as exc:
        print(f"refusing to deploy: {exc}", file=sys.stderr)
        return 1
    fd = os.open(argv[1], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(params, f)
    p = params["parameters"]
    print(f"parameters ok: {len(p['allowedObjectIds']['value'])} allowed, "
          f"enrolment {'OPEN' if p['enrolmentOpen']['value'] else 'off'}, always-ready {p['alwaysReady']['value']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
