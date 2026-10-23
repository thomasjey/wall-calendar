"""HTTP and sign-in pieces shared by the laptop/Pi sign-in (auth.py, MSAL) and
the cloud (fwcal.cloud, no MSAL; ADR-30). Imports nothing from Microsoft."""

from __future__ import annotations

import ssl

import requests
from requests.adapters import HTTPAdapter

# Microsoft omits offline_access from the granted list for personal accounts.
ALLOWED_GRANTED = frozenset({"Calendars.Read", "openid", "profile", "offline_access"})


class AuthError(RuntimeError):
    pass


class ReauthRequired(AuthError):
    """No usable sign-in: sign in again (`fwcal auth login`, or the cloud consent page)."""


class TLS12Adapter(HTTPAdapter):
    """Refuses anything older than TLS 1.2 (DESIGN §5.3)."""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def http_session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", TLS12Adapter())
    s.trust_env = False  # no proxies or netrc credentials from the environment
    return s


def granted_scopes(scope: object) -> set[str]:
    """Scope names from a token response's `scope` value, without resource prefixes."""
    return {s.rsplit("/", 1)[-1] for s in str(scope or "").split()}


def check_granted(scope: object) -> None:
    """Raises AuthError unless the grant is Calendars.Read plus OpenID scopes only."""
    granted = granted_scopes(scope)
    if not granted <= ALLOWED_GRANTED:
        raise AuthError(f"unexpected extra permissions {sorted(granted - ALLOWED_GRANTED)}; nothing was saved")
    if "Calendars.Read" not in granted:
        raise AuthError("Calendars.Read was not granted; nothing was saved")
