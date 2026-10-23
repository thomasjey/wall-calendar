"""The private blob container: events.json (written by the sync, read by the
page) and short-lived consent state (DESIGN §15.3, §15.6)."""

from __future__ import annotations

import hashlib
import json
import logging
import threading

from .. import store
from .azure import AzureError, BlobContainer

log = logging.getLogger("fwcal.cloud.storage")

EVENTS_BLOB = "events.json"
NO_DATA = {"schema": 1, "error": "no_data", "auth": "not_configured", "calendars": [], "events": []}


class BlobEventStore:
    """The sync's load/save, like store.FileEventStore."""

    def __init__(self, blobs: BlobContainer, name: str = EVENTS_BLOB) -> None:
        self._blobs, self._name = blobs, name

    def load(self) -> dict | None:
        try:
            data, _ = self._blobs.get(self._name)
            return store.loads(data) if data is not None else None
        except (AzureError, store.InvalidEventsFile) as exc:
            log.warning("previous events unavailable: %s", type(exc).__name__)
            return None

    def save(self, payload: dict) -> None:
        self._blobs.put(self._name, store.dumps(payload))


class EventsCache:
    """The page's /api/events body and ETag. Each call asks storage whether the
    blob changed (a conditional GET); the body is re-validated only when it has."""

    def __init__(self, blobs: BlobContainer, name: str = EVENTS_BLOB) -> None:
        self._blobs, self._name = blobs, name
        self._lock = threading.Lock()
        self._blob_etag: str | None = None
        self._body: bytes | None = None
        self._etag = ""

    @staticmethod
    def _encode(payload: dict) -> tuple[bytes, str]:
        body = store.dumps(payload)
        return body, '"' + hashlib.sha256(body).hexdigest()[:32] + '"'

    def get(self) -> tuple[bytes, str]:
        with self._lock:
            try:
                data, blob_etag = self._blobs.get(self._name, self._blob_etag if self._body else None)
                if data is None and blob_etag is not None and self._body is not None:
                    return self._body, self._etag  # unchanged
                if data is None:
                    self._blob_etag, self._body = None, None
                    return self._encode(NO_DATA)
                self._body, self._etag = self._encode(store.loads(data))
                self._blob_etag = blob_etag
                return self._body, self._etag
            except (AzureError, store.InvalidEventsFile) as exc:
                log.warning("events unavailable: %s", type(exc).__name__)
                if self._body is not None:
                    return self._body, self._etag  # last good copy through a storage blip
                return self._encode(NO_DATA)


class ConsentStates:
    """One blob per pending consent, named by a hash of its `state`, deleted on
    first use. Holds the PKCE verifier and nonce for at most a few minutes."""

    PREFIX = "consent/"

    def __init__(self, blobs: BlobContainer) -> None:
        self._blobs = blobs

    def _name(self, state: str) -> str:
        return self.PREFIX + hashlib.sha256(state.encode("utf-8")).hexdigest() + ".json"

    def put(self, state: str, record: dict) -> None:
        self._blobs.put(self._name(state), json.dumps(record).encode("ascii"))

    def take(self, state: str) -> dict | None:
        """The record, removed so it can't be used twice; None if unknown or already used."""
        if not state or len(state) > 200:
            return None
        name = self._name(state)
        data, _ = self._blobs.get(name)
        if data is None or not self._blobs.delete(name):
            return None  # missing, or another request took it first
        try:
            record = json.loads(data)
        except ValueError:
            return None
        return record if isinstance(record, dict) else None
