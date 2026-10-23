"""Microsoft sign-in for the viewer account (DESIGN §5.2, ADR-2).

Public client, `consumers` authority, `Calendars.Read` only, browser sign-in
with PKCE. A sign-in is saved only after the account and granted scopes are
checked; a failed check leaves the existing cache untouched.
"""

from __future__ import annotations

import logging
import ssl
from urllib.parse import parse_qs, urlsplit

import msal
import requests
from requests.adapters import HTTPAdapter

from . import tokencache
from .config import Config

log = logging.getLogger("fwcal.auth")
logging.getLogger("msal").setLevel(logging.WARNING)

AUTHORITY = "https://login.microsoftonline.com/consumers"
SCOPES = ["Calendars.Read"]
# Microsoft omits offline_access from the granted list for personal accounts.
ALLOWED_GRANTED = frozenset({"Calendars.Read", "openid", "profile", "offline_access"})
REDIRECT_URI = "http://localhost"


class AuthError(RuntimeError):
    pass


class ReauthRequired(AuthError):
    """No usable sign-in: run `fwcal auth login`."""


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


def granted_scopes(result: dict) -> set[str]:
    return {s.rsplit("/", 1)[-1] for s in str(result.get("scope", "")).split()}


def verify(result: dict, expected_account: str) -> str:
    """Raises AuthError unless the result is for the expected account with
    exactly the allowed scopes. Returns the account name."""
    if "access_token" not in result:
        raise AuthError(f"sign-in failed: {result.get('error')}: {str(result.get('error_description', ''))[:200]}")
    claims = result.get("id_token_claims") or {}
    account = str(claims.get("preferred_username", "")).lower()
    if not account or account != expected_account.lower():
        raise AuthError("signed in as an unexpected account; nothing was saved")
    granted = granted_scopes(result)
    if not granted <= ALLOWED_GRANTED:
        raise AuthError(f"unexpected extra permissions {sorted(granted - ALLOWED_GRANTED)}; nothing was saved")
    if "Calendars.Read" not in granted:
        raise AuthError("Calendars.Read was not granted; nothing was saved")
    return account


def _app(cfg: Config, cache: msal.SerializableTokenCache, session: requests.Session) -> msal.PublicClientApplication:
    if not cfg.client_id or not cfg.expected_account:
        raise AuthError("config needs client_id and expected_account")
    return msal.PublicClientApplication(cfg.client_id, authority=AUTHORITY, token_cache=cache, http_client=session)


def parse_redirect(pasted: str) -> dict:
    """The query of the http://localhost address the browser landed on."""
    url = urlsplit(pasted.strip())
    if url.scheme != "http" or url.hostname != "localhost":
        raise AuthError("paste the full address starting with http://localhost")
    params = {k: v[0] for k, v in parse_qs(url.query, max_num_fields=20).items()}
    if "code" not in params and "error" not in params:
        raise AuthError("that address has no sign-in result in it")
    return params


def login(cfg: Config, *, paste: bool, read_line=input, write=print) -> str:
    """Interactive sign-in. Saves the cache only after verify() succeeds."""
    cache = msal.SerializableTokenCache()  # fresh: a login replaces any earlier sign-in
    app = _app(cfg, cache, http_session())
    if paste:
        flow = app.initiate_auth_code_flow(SCOPES, redirect_uri=REDIRECT_URI, prompt="select_account",
                                           login_hint=cfg.expected_account)
        write("Open this link in a browser on another computer and sign in as the viewer account:")
        write(flow["auth_uri"])
        write("The browser then shows an http://localhost page that can't load. Copy its full address,")
        write("paste it here and press Enter:")
        result = app.acquire_token_by_auth_code_flow(flow, parse_redirect(read_line("> ")))
    else:
        result = app.acquire_token_interactive(SCOPES, prompt="select_account", login_hint=cfg.expected_account,
                                               timeout=600)
    account = verify(result, cfg.expected_account)
    tokencache.save(cache.serialize())
    return account


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    serialized = tokencache.load()
    if serialized:
        cache.deserialize(serialized)
    return cache


def access_token(cfg: Config, session: requests.Session) -> str:
    """A fresh access token for the sync job, refreshed silently if needed."""
    cache = _load_cache()
    app = _app(cfg, cache, session)
    accounts = [a for a in app.get_accounts() if str(a.get("username", "")).lower() == cfg.expected_account.lower()]
    if not accounts:
        raise ReauthRequired("no saved sign-in for the viewer account")
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if not result or "access_token" not in result:
        raise ReauthRequired(str((result or {}).get("error", "silent sign-in unavailable")))
    if cache.has_state_changed:
        tokencache.save(cache.serialize())
    return result["access_token"]


def status(cfg: Config) -> list[str]:
    cache = _load_cache()
    app = _app(cfg, cache, http_session())
    lines = [f"cache: {tokencache.describe()}"]
    accounts = app.get_accounts()
    if not accounts:
        return lines + ["signed in: no"]
    for a in accounts:
        mark = "expected" if str(a.get("username", "")).lower() == cfg.expected_account.lower() else "UNEXPECTED"
        lines.append(f"account: {a.get('username')} ({mark})")
    refresh = len(cache.find(msal.TokenCache.CredentialType.REFRESH_TOKEN))
    lines.append(f"refresh tokens: {refresh} (values never shown)")
    return lines


def logout() -> bool:
    return tokencache.delete()
