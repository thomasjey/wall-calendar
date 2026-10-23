"""The drift check (DESIGN §15.4, ADR-28). The platform allowlist (set by the
approved deploy) and the code allowlist (a Key Vault secret only the
administrator writes) have different owners, and a person must be on both.
Every hour this compares them and checks that the platform's sign-in
settings still keep everyone else out.

The platform side is read through Azure Resource Manager with the app
identity, which has Reader on its own site only; the code side is read
straight from Key Vault, not through the page's 5-minute cache. Findings
name counts and 8-character hashes (as in the request log, principal.py),
never object IDs.

It replaces the drift check's planned re-run of the "unlisted account gets
403" test: that needs a real account signed in, so a stored password.
Reading the settings that produce the 403 catches the same failures (sign-in
switched off, the list emptied or changed) with no stored credential.
"""

from __future__ import annotations

import hashlib
import re

from .oauth import CONSUMER_TENANT

AUTH_SETTINGS_API = "2024-04-01"
_SITE_ID_RE = re.compile(r"^/subscriptions/[0-9a-f-]{36}/resourceGroups/[A-Za-z0-9._()-]{1,90}"
                         r"/providers/Microsoft\.Web/sites/[A-Za-z0-9-]{1,60}$")


class DriftFound(RuntimeError):
    """Raised so the platform records the run as Failed (the drift alert counts
    those records, which don't depend on Python log forwarding)."""


def auth_settings_path(site_id: str) -> str:
    if not _SITE_ID_RE.match(site_id):
        raise ValueError("FWCAL_SITE_ID is not a Function App resource ID")
    return f"{site_id}/config/authsettingsV2"


def _short(oid: str) -> str:
    return hashlib.sha256(oid.encode()).hexdigest()[:8]


def _get(d: object, *keys: str) -> object:
    for key in keys:
        d = d.get(key) if isinstance(d, dict) else None
    return d


def problems(auth: dict, code_allowed: frozenset[str], allowed_tenants: str) -> list[str]:
    """What's wrong, in words with no IDs; empty when the two lists match and
    the sign-in settings are as the Bicep sets them (infra/app.bicep)."""
    p = auth.get("properties")
    if not isinstance(p, dict):
        return ["the platform's sign-in settings could not be read"]
    found = []
    if _get(p, "platform", "enabled") is not True:
        found.append("built-in authentication is off")
    if _get(p, "globalValidation", "requireAuthentication") is not True:
        found.append("sign-in is not required")
    if _get(p, "globalValidation", "unauthenticatedClientAction") == "AllowAnonymous":
        found.append("anonymous requests are allowed")
    aad = _get(p, "identityProviders", "azureActiveDirectory")
    if _get(aad, "enabled") is not True:
        found.append("Microsoft sign-in is off")
    issuer = str(_get(aad, "registration", "openIdIssuer") or "").rstrip("/")
    if not issuer.endswith(f"/{CONSUMER_TENANT}/v2.0"):
        found.append("the sign-in issuer is not the personal-account tenant")
    if allowed_tenants.strip().lower() != CONSUMER_TENANT:
        found.append("the allowed tenants are not just the personal-account tenant")
    if _get(p, "login", "tokenStore", "enabled") is True:
        found.append("the token store is on")

    identities = _get(aad, "validation", "defaultAuthorizationPolicy", "allowedPrincipals", "identities")
    if not isinstance(identities, list) or not identities:
        found.append("the platform allowlist is empty, so anyone who signs in gets past it (enrolment open?)")
    else:
        platform = frozenset(str(i).strip().lower() for i in identities)
        for ids, where in ((platform - code_allowed, "platform"), (code_allowed - platform, "code")):
            if ids:
                found.append(f"{len(ids)} ID(s) only on the {where} list ({', '.join(sorted(map(_short, ids)))})")
    return found
