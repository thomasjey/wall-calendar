"""Where files live (DESIGN §7). Resolved by code, never from a URL."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP = "fwcal"
REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "static"


def _win_dir(var: str) -> Path:
    base = os.environ.get(var)
    if not base:
        raise RuntimeError(f"%{var}% is not set")
    return Path(base) / APP


def default_config_path() -> Path:
    if sys.platform == "win32":
        return _win_dir("APPDATA") / "config.toml"
    return Path("/etc") / APP / "config.toml"


def state_dir(*, mock: bool) -> Path:
    """Mock data never shares a directory with real data."""
    base = _win_dir("LOCALAPPDATA") if sys.platform == "win32" else Path("/var/lib") / APP
    return base / "mock" if mock else base


def events_path(*, mock: bool) -> Path:
    return state_dir(mock=mock) / "data" / "events.json"


def auth_dir() -> Path:
    return state_dir(mock=False) / "auth"
