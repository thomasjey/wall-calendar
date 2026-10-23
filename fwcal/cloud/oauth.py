"""The cloud sync's three OAuth calls to Microsoft's personal-account endpoint
(ADR-27, ADR-30): the sign-in link, code redemption and refresh. The client
proves itself with a managed-identity assertion; there is no secret or key.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

from ..netauth import AuthError, ReauthRequired, check_granted

CONSUMER_TENANT = "9188040d-6c67-4c5b-b112-36a304b66dad"
ISSUER = f"https://login.microsoftonline.com/{CONSUMER_TENANT}/v2.0"
AUTHORIZE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
SCOPE = "Calendars.Read offline_access openid profile"
JWT_BEARER = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
TIMEOUT = (5, 20)
MAX_RESPONSE = 256 * 1024


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge)."""
    verifier = b64url(secrets.token_bytes(48))
    return verifier, b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def authorize_url(client_id: str, redirect_uri: str, *, state: str, nonce: str, challenge: str,
                  login_hint: str) -> str:
    return AUTHORIZE_URL + "?" + urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": redirect_uri,
        "response_mode": "query", "scope": SCOPE, "state": state, "nonce": nonce,
        "code_challenge": challenge, "code_challenge_method": "S256",
        "prompt": "select_account", "login_hint": login_hint,
    })


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str | None
    scope: str
    id_token: str | None = None


def _post(session, form: dict) -> dict:
    r = session.post(TOKEN_URL, data=form, timeout=TIMEOUT, allow_redirects=False, stream=True)
    try:
        chunks, size = [], 0
        for chunk in r.iter_content(64 * 1024):
            size += len(chunk)
            if size > MAX_RESPONSE:
                raise AuthError("token response too large")
            chunks.append(chunk)
        status = r.status_code
    finally:
        r.close()
    try:
        data = json.loads(b"".join(chunks))
    except ValueError as exc:
        raise AuthError(f"token endpoint: HTTP {status}, not JSON") from exc
    if not isinstance(data, dict):
        raise AuthError("token endpoint: unexpected response")
    if status != 200 or "access_token" not in data:
        error = str(data.get("error", "unknown"))[:60]
        codes = data.get("error_codes") if isinstance(data.get("error_codes"), list) else []
        # The description can echo request details; only the error code and numbers are reported.
        if error in ("invalid_grant", "interaction_required", "consent_required"):
            raise ReauthRequired(f"{error} {codes[:3]}")
        raise AuthError(f"token endpoint: HTTP {status}: {error} {codes[:3]}")
    return data


def _tokens(data: dict) -> Tokens:
    access, refresh, idt = data.get("access_token"), data.get("refresh_token"), data.get("id_token")
    if not isinstance(access, str) or not access:
        raise AuthError("token endpoint: no access token")
    return Tokens(access, refresh if isinstance(refresh, str) and refresh else None, str(data.get("scope", "")),
                  idt if isinstance(idt, str) else None)


def refresh(session, client_id: str, refresh_token: str, assertion: str) -> Tokens:
    """A new access token (and usually a new refresh token). ReauthRequired if consent is gone."""
    tokens = _tokens(_post(session, dict(
        client_id=client_id, grant_type="refresh_token", refresh_token=refresh_token,
        scope=SCOPE, client_assertion_type=JWT_BEARER, client_assertion=assertion,
    )))
    check_granted(tokens.scope)
    return tokens


def redeem_code(session, client_id: str, *, code: str, redirect_uri: str, verifier: str, assertion: str) -> Tokens:
    return _tokens(_post(session, {
        "client_id": client_id, "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
        "code_verifier": verifier, "scope": SCOPE, "client_assertion_type": JWT_BEARER,
        "client_assertion": assertion,
    }))


def id_token_claims(id_token: str) -> dict:
    """The ID token's claims. Received directly from the token endpoint over TLS,
    so its signature need not be checked (OpenID Connect Core 3.1.3.7); the
    issuer, audience, tenant, nonce and expiry still are (verify_consent)."""
    parts = id_token.split(".")
    if len(parts) != 3 or len(id_token) > 16 * 1024:
        raise AuthError("malformed ID token")
    try:
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except ValueError as exc:
        raise AuthError("malformed ID token") from exc
    if not isinstance(claims, dict):
        raise AuthError("malformed ID token")
    return claims


def verify_consent(tokens: Tokens, *, client_id: str, nonce: str, expected_account: str, now: float) -> str:
    """Accepts a consent only for the configured viewer account with exactly
    Calendars.Read plus OpenID scopes (DESIGN §15.6). Returns the account."""
    if not tokens.id_token:
        raise AuthError("no ID token")
    claims = id_token_claims(tokens.id_token)
    if claims.get("iss") != ISSUER or claims.get("tid") != CONSUMER_TENANT:
        raise AuthError("not a personal Microsoft account")
    if claims.get("aud") != client_id:
        raise AuthError("ID token is for another app")
    if not isinstance(claims.get("nonce"), str) or not secrets.compare_digest(claims["nonce"], nonce):
        raise AuthError("nonce mismatch")
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp < now:
        raise AuthError("ID token expired")
    account = str(claims.get("preferred_username", "")).lower()
    if not account or account != expected_account.lower():
        raise AuthError("signed in as an unexpected account; nothing was saved")
    check_granted(tokens.scope)
    if not tokens.refresh_token:
        raise AuthError("no refresh token returned; nothing was saved")
    return account
