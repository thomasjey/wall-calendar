"""Who is asking: the principal that Azure's built-in sign-in puts in the
`x-ms-client-principal` header. The platform removes any copy a caller sends
and sets its own, so the header can be trusted while sign-in is on; if sign-in
were switched off it would be missing, and the request is refused (layer 3,
DESIGN §15.4).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass

from .settings import GUID_RE

HEADER = "x-ms-client-principal"
OID = "http://schemas.microsoft.com/identity/claims/objectidentifier"
TID = "http://schemas.microsoft.com/identity/claims/tenantid"
MAX_HEADER = 16 * 1024


@dataclass(frozen=True)
class Principal:
    oid: str
    tid: str

    def log_id(self) -> str:
        """A short hash for correlating log lines; never the ID itself (§17.7)."""
        return hashlib.sha256(self.oid.encode()).hexdigest()[:8]


def parse(value: str | None) -> Principal | None:
    """The principal, or None if missing or malformed in any way."""
    if not value or len(value) > MAX_HEADER:
        return None
    try:
        data = json.loads(base64.b64decode(value, validate=True))
    except (ValueError, binascii.Error):
        return None
    if not isinstance(data, dict) or data.get("auth_typ") != "aad" or not isinstance(data.get("claims"), list):
        return None
    claims: dict[str, str] = {}
    for c in data["claims"]:
        if isinstance(c, dict) and isinstance(c.get("typ"), str) and isinstance(c.get("val"), str):
            claims.setdefault(c["typ"], c["val"])
    oid = (claims.get(OID) or claims.get("oid") or "").lower()
    tid = (claims.get(TID) or claims.get("tid") or "").lower()
    if not GUID_RE.match(oid) or not GUID_RE.match(tid):
        return None
    return Principal(oid, tid)
