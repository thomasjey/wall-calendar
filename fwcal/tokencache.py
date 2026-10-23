"""The MSAL token cache on disk (DESIGN §5.2, ADR-5).

POSIX: the directory is 0700 and the file 0600, both owned by the running user;
anything looser or owned by someone else is refused, as ssh does. The file is
created with its mode from the start and replaced atomically.
Windows (development only): the directory gets an explicit ACL with
inheritance removed (current user and SYSTEM only).

Token values are never logged or printed.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

from . import paths
from .store import atomic_write

CACHE_NAME = "msal_cache.json"
MAX_CACHE_BYTES = 1024 * 1024


class InsecureCache(RuntimeError):
    """The cache location has the wrong owner or permissions; nothing is read."""


def cache_path() -> Path:
    return paths.auth_dir() / CACHE_NAME


# ----- Windows ACL -----

def _current_user_sid() -> str:
    out = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], check=True, capture_output=True, text=True).stdout
    sid = out.strip().split(",")[-1].strip('"')
    if not sid.startswith("S-1-"):
        raise InsecureCache("could not determine the current user's SID")
    return sid


def windows_acl_command(directory: Path, user_sid: str) -> list[str]:
    """icacls arguments: remove inherited entries; full control for the user and SYSTEM only."""
    return ["icacls", str(directory), "/inheritance:r",
            "/grant:r", f"*{user_sid}:(OI)(CI)F", "/grant:r", "*S-1-5-18:(OI)(CI)F"]


def _protect_windows(directory: Path) -> None:
    subprocess.run(windows_acl_command(directory, _current_user_sid()), check=True, capture_output=True)


# ----- POSIX checks -----

def check_posix_dir(st: os.stat_result) -> None:
    if not stat.S_ISDIR(st.st_mode):
        raise InsecureCache("token location is not a directory")
    if st.st_uid != os.getuid():
        raise InsecureCache("token directory is owned by another user")
    if stat.S_IMODE(st.st_mode) & 0o077:
        raise InsecureCache(f"token directory mode {oct(stat.S_IMODE(st.st_mode))} is too open (want 0700)")


def check_posix_file(st: os.stat_result) -> None:
    if not stat.S_ISREG(st.st_mode):
        raise InsecureCache("token cache is not a regular file")
    if st.st_uid != os.getuid():
        raise InsecureCache("token cache is owned by another user")
    if stat.S_IMODE(st.st_mode) & 0o077:
        raise InsecureCache(f"token cache mode {oct(stat.S_IMODE(st.st_mode))} is too open (want 0600)")


def ensure_dir(*, protect: bool = False) -> Path:
    """Creates the directory if needed and checks it (POSIX). On Windows the ACL
    is applied when the directory is created and whenever `protect` is set."""
    directory = paths.auth_dir()
    if sys.platform == "win32":
        new = not directory.exists()
        directory.mkdir(parents=True, exist_ok=True)
        if new or protect:
            _protect_windows(directory)
        return directory
    if not directory.exists():
        directory.parent.mkdir(parents=True, exist_ok=True)
        os.mkdir(directory, 0o700)
    check_posix_dir(os.lstat(directory))
    return directory


def load() -> str | None:
    """The serialized cache, or None if there is none yet."""
    directory = ensure_dir()
    path = directory / CACHE_NAME
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as f:
        if sys.platform != "win32":
            check_posix_file(os.fstat(f.fileno()))
        data = f.read(MAX_CACHE_BYTES + 1)
    if len(data) > MAX_CACHE_BYTES:
        raise InsecureCache("token cache is unexpectedly large")
    return data.decode("utf-8")


def save(serialized: str) -> None:
    directory = ensure_dir(protect=True)
    atomic_write(directory / CACHE_NAME, serialized.encode("utf-8"), 0o600)


def delete() -> bool:
    """Overwrites, then removes the cache. True if there was one."""
    path = cache_path()
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return False
    with open(path, "r+b") as f:
        f.write(b"\0" * size)
        f.flush()
        os.fsync(f.fileno())
    path.unlink()
    return True


def describe() -> str:
    """Location and permissions, for `fwcal auth status` (never contents)."""
    path = cache_path()
    if not path.exists():
        return f"{path} (none)"
    if sys.platform == "win32":
        return f"{path} (Windows ACL on {path.parent})"
    st = os.lstat(path)
    return f"{path} mode {oct(stat.S_IMODE(st.st_mode))} uid {st.st_uid}"
