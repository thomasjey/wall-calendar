"""The private blob container: events.json (written by the sync, read by the
page) and short-lived consent state (DESIGN §15.3, §15.6)."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, replace

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


@dataclass(frozen=True)
class _Snapshot:
    body: bytes
    etag: str
    blob_etag: str | None  # None: no blob seen (the page shows "no data")
    checked: float  # when storage was last asked, on the cache's clock


class EventsCache:
    """The page's /api/events body and ETag, held as one immutable snapshot that
    requests read without a lock. Storage is asked whether the blob changed (a
    conditional GET) at most every `recheck` seconds per instance: until then
    the snapshot is served as is, and when it's due one request checks while
    the others keep serving the current snapshot (stale-while-revalidate).
    Only the first request on a fresh instance waits for storage. A storage
    failure keeps the last good snapshot and is retried after `recheck`.

    Earlier this held a lock across every storage call, so under load each
    request queued behind the slowest one ahead of it (load test, §17.6)."""

    def __init__(self, blobs: BlobContainer, name: str = EVENTS_BLOB, *, recheck: float = 10.0,
                 clock=time.monotonic) -> None:
        self._blobs, self._name = blobs, name
        self._recheck, self._clock = recheck, clock
        self._snap: _Snapshot | None = None
        self._first_load = threading.Lock()  # a fresh instance loads once; the others wait for it
        self._claim = threading.Lock()  # guards only the flag below, never storage I/O
        self._refreshing = False

    @staticmethod
    def _encode(payload: dict, blob_etag: str | None, checked: float) -> _Snapshot:
        body = store.dumps(payload)
        return _Snapshot(body, '"' + hashlib.sha256(body).hexdigest()[:32] + '"', blob_etag, checked)

    def get(self) -> tuple[bytes, str]:
        snap = self._snap
        if snap is None:
            with self._first_load:
                if self._snap is None:
                    self._snap = self._load(None)
                snap = self._snap
        elif self._clock() - snap.checked >= self._recheck:
            with self._claim:
                mine = not self._refreshing
                self._refreshing = True
            if mine:  # anyone else meanwhile serves the snapshot they already have
                try:
                    self._snap = snap = self._load(snap)
                finally:
                    self._refreshing = False
        return snap.body, snap.etag

    def _load(self, prev: _Snapshot | None) -> _Snapshot:
        now = self._clock()
        try:
            data, blob_etag = self._blobs.get(self._name, prev.blob_etag if prev else None)
            if data is None and blob_etag is not None and prev is not None:
                return replace(prev, checked=now)  # unchanged
            if data is None:
                return self._encode(NO_DATA, None, now)  # no blob
            return self._encode(store.loads(data), blob_etag, now)
        except (AzureError, store.InvalidEventsFile) as exc:
            log.warning("events unavailable: %s", type(exc).__name__)
            if prev is not None:
                return replace(prev, checked=now)  # last good copy through a storage blip
            return self._encode(NO_DATA, None, now)


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
