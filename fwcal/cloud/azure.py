"""Managed-identity tokens, Key Vault secrets and blobs over REST (ADR-30).

Every URL is checked against the service's own domain before a token is sent,
responses are size-capped, and secret values are never logged.
"""

from __future__ import annotations

import ipaddress
import json
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import quote, urlencode, urlsplit

TIMEOUT = (5, 15)
MAX_BODY = 11 * 1024 * 1024  # events.json is capped at 10 MB (store.MAX_FILE_BYTES)
KEY_VAULT = "https://vault.azure.net"
STORAGE = "https://storage.azure.com/"
TOKEN_EXCHANGE = "api://AzureADTokenExchange"
KV_API = "7.4"
BLOB_API = "2023-11-03"
_NAME_RE = re.compile(r"^[A-Za-z0-9-]{1,127}$")
_BLOB_RE = re.compile(r"^[a-z0-9][a-z0-9/._-]{0,250}$")
_GUID_RE = re.compile(r"^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$")


class AzureError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def https_url(url: str, suffix: str) -> str:
    """`url` without a trailing slash, if it is https on a host ending in `suffix`."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if (parts.scheme != "https" or not host.endswith(suffix) or parts.port not in (None, 443)
            or parts.username or parts.query or parts.fragment):
        raise AzureError(f"refusing a URL outside *{suffix}")
    return url.rstrip("/")


def _read(r, limit: int = MAX_BODY) -> bytes:
    chunks, size = [], 0
    for chunk in r.iter_content(64 * 1024):
        size += len(chunk)
        if size > limit:
            raise AzureError("response larger than the cap")
        chunks.append(chunk)
    return b"".join(chunks)


def _json(r, what: str) -> dict:
    try:
        data = json.loads(_read(r, 1024 * 1024))
    except ValueError as exc:
        raise AzureError(f"{what}: response is not JSON") from exc
    if not isinstance(data, dict):
        raise AzureError(f"{what}: unexpected response shape")
    return data


def _platform_local(host: str | None) -> bool:
    """Loopback or link-local (169.254.0.0/16, fe80::/10): addresses the
    platform uses for its own endpoints and that are never routed to the
    internet. Flex Consumption serves identity tokens on a link-local address."""
    if host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    return ip.is_loopback or ip.is_link_local


class ManagedIdentity:
    """Tokens from the Functions host's identity endpoint for the user-assigned
    identity `client_id` (None would be a system-assigned identity, unused here)."""

    def __init__(self, session, endpoint: str, header: str, client_id: str | None = None,
                 clock=time.time) -> None:
        parts = urlsplit(endpoint)
        if parts.scheme not in ("http", "https") or not _platform_local(parts.hostname):
            # The identity header must never go to a routable host; the host itself is not secret.
            raise AzureError(f"the identity endpoint must be loopback or link-local, not {parts.hostname!r}")
        if client_id is not None and not _GUID_RE.match(client_id):
            raise AzureError("identity client ID must be a GUID")
        self._session, self._endpoint, self._header = session, endpoint, header
        self.client_id = client_id
        self._clock = clock
        self._cache: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def token(self, resource: str) -> str:
        with self._lock:
            cached = self._cache.get(resource)
            if cached and cached[1] - self._clock() > 300:
                return cached[0]
        params = {"resource": resource, "api-version": "2019-08-01"}
        if self.client_id:
            params["client_id"] = self.client_id
        r = self._session.get(f"{self._endpoint}?{urlencode(params)}", headers={"X-IDENTITY-HEADER": self._header},
                              timeout=TIMEOUT, allow_redirects=False, stream=True)
        try:
            if r.status_code != 200:
                raise AzureError(f"managed identity: HTTP {r.status_code}", r.status_code)
            data = _json(r, "managed identity")
        finally:
            r.close()
        token = data.get("access_token")
        try:
            expires = float(data.get("expires_on", 0))
        except (TypeError, ValueError):
            expires = 0.0
        if not isinstance(token, str) or not token:
            raise AzureError("managed identity: no token")
        with self._lock:
            self._cache[resource] = (token, expires)
        return token

    def assertion(self) -> str:
        """A client assertion for a federated credential (ADR-26, ADR-27). Not cached beyond its lifetime."""
        return self.token(TOKEN_EXCHANGE)


@dataclass(frozen=True)
class Secret:
    value: str
    version: str


class KeyVault:
    def __init__(self, session, vault_url: str, identity: ManagedIdentity) -> None:
        self._session = session
        self._url = https_url(vault_url, ".vault.azure.net")
        self._identity = identity

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        r = self._session.request(method, f"{self._url}/{path}?api-version={KV_API}", json=body, timeout=TIMEOUT,
                                  allow_redirects=False, stream=True,
                                  headers={"Authorization": f"Bearer {self._identity.token(KEY_VAULT)}"})
        try:
            if r.status_code >= 400:
                raise AzureError(f"Key Vault {method}: HTTP {r.status_code}", r.status_code)
            return _json(r, "Key Vault")
        finally:
            r.close()

    @staticmethod
    def _name(name: str) -> str:
        if not _NAME_RE.match(name):
            raise AzureError("bad secret name")
        return name

    def get(self, name: str) -> Secret:
        data = self._request("GET", f"secrets/{self._name(name)}")
        value, sid = data.get("value"), data.get("id")
        if not isinstance(value, str) or not isinstance(sid, str):
            raise AzureError("Key Vault: unexpected secret shape")
        return Secret(value, sid.rsplit("/", 1)[-1])

    def set(self, name: str, value: str, content_type: str) -> str:
        """Stores a new version; returns its version ID."""
        data = self._request("PUT", f"secrets/{self._name(name)}", {"value": value, "contentType": content_type})
        sid = data.get("id")
        if not isinstance(sid, str):
            raise AzureError("Key Vault: unexpected response")
        return sid.rsplit("/", 1)[-1]

    def disable(self, name: str, version: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{32}", version):
            raise AzureError("bad secret version")
        self._request("PATCH", f"secrets/{self._name(name)}/{version}", {"attributes": {"enabled": False}})


class BlobContainer:
    """One private container, reached with the app's identity (shared keys are off)."""

    def __init__(self, session, container_url: str, identity: ManagedIdentity) -> None:
        self._session = session
        self._url = https_url(container_url, ".blob.core.windows.net")
        if urlsplit(self._url).path.count("/") != 1:
            raise AzureError("the blob URL must name exactly one container")
        self._identity = identity

    def _headers(self, extra: dict | None = None) -> dict:
        return {"Authorization": f"Bearer {self._identity.token(STORAGE)}", "x-ms-version": BLOB_API, **(extra or {})}

    def _blob_url(self, name: str) -> str:
        if not _BLOB_RE.match(name) or ".." in name:
            raise AzureError("bad blob name")
        return f"{self._url}/{quote(name)}"

    def get(self, name: str, etag: str | None = None) -> tuple[bytes | None, str | None]:
        """(data, etag). (None, etag) if unchanged since `etag`; (None, None) if missing."""
        headers = self._headers({"If-None-Match": etag} if etag else None)
        r = self._session.get(self._blob_url(name), headers=headers, timeout=TIMEOUT, allow_redirects=False,
                              stream=True)
        try:
            if r.status_code == 304:
                return None, etag
            if r.status_code == 404:
                return None, None
            if r.status_code != 200:
                raise AzureError(f"blob get: HTTP {r.status_code}", r.status_code)
            return _read(r), r.headers.get("ETag")
        finally:
            r.close()

    def put(self, name: str, data: bytes, content_type: str = "application/json") -> None:
        headers = self._headers({"x-ms-blob-type": "BlockBlob", "Content-Type": content_type})
        r = self._session.put(self._blob_url(name), data=data, headers=headers, timeout=TIMEOUT,
                              allow_redirects=False)
        try:
            if r.status_code != 201:
                raise AzureError(f"blob put: HTTP {r.status_code}", r.status_code)
        finally:
            r.close()

    def delete(self, name: str) -> bool:
        """True if it existed and was deleted."""
        r = self._session.delete(self._blob_url(name), headers=self._headers(), timeout=TIMEOUT,
                                 allow_redirects=False)
        try:
            if r.status_code == 404:
                return False
            if r.status_code != 202:
                raise AzureError(f"blob delete: HTTP {r.status_code}", r.status_code)
            return True
        finally:
            r.close()
