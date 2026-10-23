"""Access tokens for the cloud sync (ADR-18, ADR-27).

The viewer's refresh token lives in Key Vault; redeeming it needs an assertion
from the sync identity, which only this Function App can get. Each refresh
stores the new refresh token as a new secret version and disables the one
just used (R3), so an older copy is no longer usable from Key Vault.
"""

from __future__ import annotations

import logging

from ..config import Config
from ..netauth import AuthError, ReauthRequired
from . import oauth
from .azure import AzureError, KeyVault, ManagedIdentity

log = logging.getLogger("fwcal.cloud.tokens")

REFRESH_SECRET = "viewer-refresh-token"
CONTENT_TYPE = "refresh-token"


def store_refresh_token(vault: KeyVault, value: str, previous_version: str | None = None) -> None:
    """New version first, then disable the old one: a failure in between leaves
    a usable token rather than none."""
    vault.set(REFRESH_SECRET, value, CONTENT_TYPE)
    if previous_version:
        try:
            vault.disable(REFRESH_SECRET, previous_version)
        except AzureError as exc:
            log.warning("could not disable the previous refresh token version: %s", exc)


class CloudTokens:
    def __init__(self, vault: KeyVault, sync_identity: ManagedIdentity, client_id: str) -> None:
        self._vault, self._identity, self._client_id = vault, sync_identity, client_id

    def __call__(self, cfg: Config, session) -> str:
        """sync.run's token_fn."""
        try:
            secret = self._vault.get(REFRESH_SECRET)
        except AzureError as exc:
            if exc.status == 404:
                raise ReauthRequired("no refresh token stored; use the consent page") from exc
            raise AuthError(f"Key Vault unavailable: {exc}") from exc  # the sync keeps the last good data
        try:
            assertion = self._identity.assertion()
        except AzureError as exc:
            raise AuthError(f"sync identity unavailable: {exc}") from exc
        tokens = oauth.refresh(session, self._client_id, secret.value, assertion)
        if tokens.refresh_token and tokens.refresh_token != secret.value:
            store_refresh_token(self._vault, tokens.refresh_token, secret.version)
        return tokens.access_token
