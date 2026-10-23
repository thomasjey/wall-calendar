"""Wiring for the Function App: everything is built once per instance from app
settings (set by the Bicep, none of them secret) and the platform's identity
endpoint. Plain functions: the Python runtime runs them on its own thread pool
(ADR-25), which keeps its event loop free and their log lines attached.

App settings:
    FWCAL_KEY_VAULT_URL            https://<vault>.vault.azure.net
    FWCAL_BLOB_CONTAINER_URL       https://<account>.blob.core.windows.net/<container>
    FWCAL_APP_IDENTITY_CLIENT_ID   the app identity (user-assigned): config read, blobs
    FWCAL_SYNC_CLIENT_ID           the cloud-sync app registration
    FWCAL_SYNC_IDENTITY_CLIENT_ID  the sync identity (user-assigned)
Platform: WEBSITE_HOSTNAME, IDENTITY_ENDPOINT, IDENTITY_HEADER.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from .. import sync
from ..netauth import http_session
from ..server import SECURITY_HEADERS, load_static
from .azure import BlobContainer, KeyVault, ManagedIdentity
from .consent import Consent
from .settings import SettingsCache
from .storage import BlobEventStore, ConsentStates, EventsCache
from .tokens import CloudTokens
from .web import Request, Response, Web

log = logging.getLogger("fwcal.cloud")
# Python's default threshold is WARNING, and the Functions runtime doesn't
# lower it; the sync's progress lines (which the sync alert counts) are INFO.
logging.getLogger("fwcal").setLevel(logging.INFO)

CONFIG_SECRET = "fwcal-config"
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"


@dataclass
class Services:
    web: Web
    settings: SettingsCache
    events_store: BlobEventStore
    tokens: CloudTokens
    session: object


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"app setting {name} is not set")
    return value


def build() -> Services:
    session = http_session()
    endpoint, header = _env("IDENTITY_ENDPOINT"), _env("IDENTITY_HEADER")
    app_identity = ManagedIdentity(session, endpoint, header, _env("FWCAL_APP_IDENTITY_CLIENT_ID"))
    sync_identity = ManagedIdentity(session, endpoint, header, _env("FWCAL_SYNC_IDENTITY_CLIENT_ID"))
    vault_url = _env("FWCAL_KEY_VAULT_URL")
    config_vault = KeyVault(session, vault_url, app_identity)
    token_vault = KeyVault(session, vault_url, sync_identity)
    blobs = BlobContainer(session, _env("FWCAL_BLOB_CONTAINER_URL"), app_identity)
    client_id = _env("FWCAL_SYNC_CLIENT_ID")

    settings = SettingsCache(lambda: config_vault.get(CONFIG_SECRET).value)
    consent = Consent(states=ConsentStates(blobs), vault=token_vault, sync_identity=sync_identity,
                      client_id=client_id, session=session)
    web = Web(static=load_static(STATIC_DIR, include_tests=False), settings=settings, events=EventsCache(blobs),
              hostnames=frozenset({_env("WEBSITE_HOSTNAME")}), consent=consent)
    return Services(web, settings, BlobEventStore(blobs), CloudTokens(token_vault, sync_identity, client_id), session)


_services: Services | None = None
_lock = threading.Lock()


def services() -> Services:
    global _services
    with _lock:
        if _services is None:
            _services = build()
        return _services


def _handle(req: Request) -> Response:
    try:
        web = services().web
    except Exception as exc:  # setup failed: a short answer with the usual headers, the cause only in the log
        log.exception("could not start: %s", type(exc).__name__)
        return Response(503, b"Not available right now\n", "text/plain; charset=utf-8",
                        {**SECURITY_HEADERS, "Cache-Control": "no-store"})
    return web.handle(req)


def handle(req: Request) -> Response:
    return _handle(req)



class SyncIncomplete(RuntimeError):
    """Raised so the platform records the timer run as Failed, with this short,
    content-free reason. The sync alert counts the platform's own Succeeded
    records, which don't depend on Python log forwarding."""

    REASONS: ClassVar[dict[int, str]] = {sync.PARTIAL: "a calendar could not be read; the last good data is kept",
               sync.CONFIG: "configuration problem",
               sync.REAUTH: "sign-in needed: open /manage/consent"}

    def __init__(self, code: int) -> None:
        super().__init__(f"sync incomplete: code {code} ({self.REASONS.get(code, 'unknown')})")
        self.code = code


def run_sync() -> int:
    """Returns sync.OK, or raises SyncIncomplete."""
    s = services()
    settings = s.settings.get()
    if not settings.config.calendars:
        # A deliberate state (dev before a test calendar exists), not a failure.
        log.info("sync skipped: no calendars configured")
        return sync.OK
    code = sync.run(settings.config, session=s.session, token_fn=s.tokens, events=s.events_store,
                    now=datetime.now(settings.tz))
    log.info("sync finished with code %d", code)
    if code != sync.OK:
        raise SyncIncomplete(code)
    return code
