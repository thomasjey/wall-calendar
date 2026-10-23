"""Wiring for the Function App: everything is built once per instance from app
settings (set by the Bicep, none of them secret) and the platform's identity
endpoint. Blocking calls run in worker threads so the event loop stays free
(ADR-25).

App settings:
    FWCAL_KEY_VAULT_URL            https://<vault>.vault.azure.net
    FWCAL_BLOB_CONTAINER_URL       https://<account>.blob.core.windows.net/<container>
    FWCAL_APP_IDENTITY_CLIENT_ID   the app identity (user-assigned): config read, blobs
    FWCAL_SYNC_CLIENT_ID           the cloud-sync app registration
    FWCAL_SYNC_IDENTITY_CLIENT_ID  the sync identity (user-assigned)
Platform: WEBSITE_HOSTNAME, IDENTITY_ENDPOINT, IDENTITY_HEADER.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .. import sync
from ..netauth import http_session
from ..server import load_static
from .azure import BlobContainer, KeyVault, ManagedIdentity
from .consent import Consent
from .settings import SettingsCache
from .storage import BlobEventStore, ConsentStates, EventsCache
from .tokens import CloudTokens
from .web import Request, Response, Web

log = logging.getLogger("fwcal.cloud")

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


async def handle(req: Request) -> Response:
    return await asyncio.to_thread(lambda: services().web.handle(req))


def run_sync() -> int:
    s = services()
    settings = s.settings.get()
    code = sync.run(settings.config, session=s.session, token_fn=s.tokens, events=s.events_store,
                    now=datetime.now(settings.tz))
    log.info("sync finished with code %d", code)
    return code


async def sync_now() -> int:
    return await asyncio.to_thread(run_sync)
