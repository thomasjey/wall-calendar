"""The admin-only consent page (DESIGN §15.6, ADR-27, T29).

/manage/consent sends the admin's browser to Microsoft to sign in as the viewer
account. The callback accepts the result only with an unused `state` that was
issued to the same admin less than 10 minutes ago, redeems the code with the
sync identity's assertion and the PKCE verifier, and stores the refresh token
only if it is for the configured viewer with exactly Calendars.Read.
"""

from __future__ import annotations

import logging
import secrets
import time

from ..netauth import AuthError
from . import oauth
from .azure import AzureError, KeyVault, ManagedIdentity
from .principal import Principal
from .storage import ConsentStates
from .tokens import REFRESH_SECRET, store_refresh_token

log = logging.getLogger("fwcal.cloud.consent")

STATE_SECONDS = 600
# Not under /admin/ or /runtime/: the Functions host keeps those for itself.
START = "/manage/consent"
CALLBACK = START + "/callback"


class ConsentError(RuntimeError):
    """Shown to the admin as a short message."""


class Consent:
    def __init__(self, *, states: ConsentStates, vault: KeyVault, sync_identity: ManagedIdentity, client_id: str,
                 session, clock=time.time) -> None:
        self._states, self._vault, self._identity = states, vault, sync_identity
        self._client_id, self._session, self._clock = client_id, session, clock

    def start(self, admin: Principal, host: str, viewer_account: str) -> str:
        """Records a pending consent and returns Microsoft's sign-in URL."""
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        verifier, challenge = oauth.pkce_pair()
        self._states.put(state, {"oid": admin.oid, "nonce": nonce, "verifier": verifier,
                                 "expires": self._clock() + STATE_SECONDS})
        log.info("consent started by %s", admin.log_id())
        return oauth.authorize_url(self._client_id, f"https://{host}{CALLBACK}", state=state, nonce=nonce,
                                   challenge=challenge, login_hint=viewer_account)

    def finish(self, admin: Principal, host: str, query: dict[str, str], viewer_account: str) -> str:
        """Completes a consent; returns the connected account. Raises ConsentError."""
        record = self._states.take(query.get("state", ""))
        if (record is None or record.get("oid") != admin.oid or not isinstance(record.get("expires"), (int, float))
                or record["expires"] < self._clock()):
            raise ConsentError("This sign-in link is invalid, already used or expired. Start again.")
        if "error" in query:
            raise ConsentError("Microsoft sign-in did not complete. Start again.")
        code = query.get("code", "")
        if not code or len(code) > 4096:
            raise ConsentError("No sign-in result. Start again.")
        try:
            tokens = oauth.redeem_code(self._session, self._client_id, code=code,
                                       redirect_uri=f"https://{host}{CALLBACK}", verifier=record.get("verifier", ""),
                                       assertion=self._identity.assertion())
            account = oauth.verify_consent(tokens, client_id=self._client_id, nonce=str(record.get("nonce", "")),
                                           expected_account=viewer_account, now=self._clock())
        except AuthError as exc:
            log.warning("consent refused for %s: %s", admin.log_id(), exc)
            raise ConsentError("Not connected: sign in as the viewer account and allow calendar access only.") from exc
        try:
            previous = self._vault.get(REFRESH_SECRET).version
        except AzureError as exc:
            if exc.status != 404:
                raise
            previous = None
        store_refresh_token(self._vault, tokens.refresh_token, previous)
        log.info("consent completed by %s", admin.log_id())
        return account
