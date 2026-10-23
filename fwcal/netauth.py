"""HTTP and sign-in pieces shared by the laptop/Pi sign-in (auth.py, MSAL) and
the cloud (fwcal.cloud, no MSAL; ADR-30). Imports nothing from Microsoft."""

from __future__ import annotations

import ssl

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

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


# One immediate retry when a connection fails: connecting (nothing was sent, so
# safe for any method), or for a GET, a reply that never came. A kept-alive
# connection can be dropped silently while idle (Azure's outbound connections
# after about 4 minutes); the retry opens a fresh one. Status codes are never
# retried here (Graph handles 429 and 503 itself).
RETRY = Retry(total=1, connect=1, read=1, redirect=0, status=0, other=0, allowed_methods=frozenset({"GET"}),
              backoff_factor=0, raise_on_status=False, respect_retry_after_header=False)


def http_session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", TLS12Adapter(max_retries=RETRY))
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
