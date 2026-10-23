"""The cloud configuration: one TOML document kept as a Key Vault secret that
only I can write (ADR-28, ADR-31). It is the local config (calendars, display,
viewer account), a time zone, and an [access] table:

    timezone = "Area/City"           # IANA name: the day boundaries for the sync window

    [access]
    allowed = ["<object ID>", ...]   # the code allowlist (layer 3, DESIGN §15.4)
    admins = ["<object ID>"]         # may use /admin/consent; must also be allowed
    max_allowed = 5                  # a malformed or oversized list is refused
    enrolment_until = "2026-10-23T02:00:00Z"   # optional (see enrolment_active)

Nothing in it is a secret, but changing it changes who sees what, so it is
validated strictly and an invalid document denies everyone.
"""

from __future__ import annotations

import re
import threading
import time
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..config import Config, ConfigError, parse

GUID_RE = re.compile(r"^[0-9a-f]{8}-([0-9a-f]{4}-){3}[0-9a-f]{12}$")
MAX_ALLOWED_CAP = 10
ENROLMENT_MAX_SECONDS = 30 * 60


@dataclass(frozen=True)
class Access:
    allowed: frozenset[str]
    admins: frozenset[str]
    enrolment_until: datetime | None = None

    def enrolment_active(self, now: datetime) -> bool:
        """Enrolment shows a signed-in person only their own ID. It is on only
        while the end time is less than 30 minutes away, so a far-future value
        can't hold it open."""
        if self.enrolment_until is None:
            return False
        remaining = (self.enrolment_until - now).total_seconds()
        return 0 < remaining <= ENROLMENT_MAX_SECONDS


@dataclass(frozen=True)
class CloudSettings:
    config: Config
    access: Access
    tz: ZoneInfo


def _ids(value: object, what: str) -> frozenset[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) and GUID_RE.match(v) for v in value):
        raise ConfigError(f"access.{what}: a list of lower-case object IDs")
    return frozenset(value)


def parse_settings(text: str) -> CloudSettings:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"cloud config: {exc}") from exc
    tz_name = data.pop("timezone", None)
    if not isinstance(tz_name, str) or not re.fullmatch(r"[A-Za-z_]+(/[A-Za-z0-9_+-]+){0,2}", tz_name):
        raise ConfigError('cloud config: timezone = "Area/City" is required')
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"cloud config: unknown timezone {tz_name!r}") from exc
    access = data.pop("access", None)
    if not isinstance(access, dict):
        raise ConfigError("cloud config: [access] is required")
    unknown = set(access) - {"allowed", "admins", "max_allowed", "enrolment_until"}
    if unknown:
        raise ConfigError(f"access: unknown key(s) {sorted(unknown)}")
    cfg = parse(data)
    if not cfg.expected_account:
        raise ConfigError("cloud config: expected_account (the viewer account) is required")
    allowed = _ids(access.get("allowed"), "allowed")
    admins = _ids(access.get("admins", []), "admins")
    max_allowed = access.get("max_allowed")
    if isinstance(max_allowed, bool) or not isinstance(max_allowed, int) or not 1 <= max_allowed <= MAX_ALLOWED_CAP:
        raise ConfigError(f"access.max_allowed: 1..{MAX_ALLOWED_CAP}")
    if not allowed or len(allowed) > max_allowed:
        raise ConfigError("access.allowed: between 1 and max_allowed entries")
    if not admins <= allowed:
        raise ConfigError("access.admins: every admin must also be allowed")
    until = access.get("enrolment_until")
    if until is not None:
        if not isinstance(until, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", until):
            raise ConfigError('access.enrolment_until: "YYYY-MM-DDTHH:MM:SSZ"')
        until = datetime.strptime(until, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return CloudSettings(cfg, Access(allowed, admins, until), tz)


class SettingsCache:
    """Re-reads the secret every `ttl` seconds. If a re-read fails, the last
    good settings are used for at most `grace` seconds, then everyone is denied
    (SettingsUnavailable). A removal from the allowlist takes effect within `ttl`."""

    def __init__(self, load_text, *, ttl: float = 300, grace: float = 1800, clock=time.monotonic) -> None:
        self._load_text = load_text
        self._ttl, self._grace, self._clock = ttl, grace, clock
        self._value: CloudSettings | None = None
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def get(self) -> CloudSettings:
        with self._lock:
            now = self._clock()
            if self._value is not None and now - self._loaded_at < self._ttl:
                return self._value
            try:
                self._value, self._loaded_at = parse_settings(self._load_text()), now
            except Exception as exc:  # any failure: keep the last good value briefly, then fail closed
                if self._value is not None and now - self._loaded_at < self._grace:
                    return self._value
                self._value = None
                raise SettingsUnavailable(type(exc).__name__) from exc
            return self._value


class SettingsUnavailable(RuntimeError):
    pass


def main(argv: list[str]) -> int:
    """`python -m fwcal.cloud.settings <file>`: validates a cloud config before
    it is uploaded (tools/azure/put_config.ps1). Prints counts, never IDs."""
    import sys

    if len(argv) != 1:
        print("usage: python -m fwcal.cloud.settings <config.toml>", file=sys.stderr)
        return 2
    try:
        with open(argv[0], encoding="utf-8") as f:
            st = parse_settings(f.read())
    except (OSError, ConfigError) as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    a = st.access
    print(f"valid: {len(st.config.calendars)} calendars, {len(a.allowed)} allowed, {len(a.admins)} admin(s), "
          f"time zone {st.tz.key}, enrolment {'set' if a.enrolment_until else 'off'}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
