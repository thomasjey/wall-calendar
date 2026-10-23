"""Builds the Function App package (DESIGN §17.5): one zip per release, with
the hash-pinned dependencies installed for Linux / Python 3.13 (binary wheels
only, every file checked against its hash) and nothing that isn't needed: no
tests, no local-only modules' data, no browser test page.

    python tools/build_package.py dist/function.zip

Prints the package's SHA-256, which the release records and the deploy checks.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON_VERSION = "3.13"
PLATFORM = "manylinux2014_x86_64"
FIXED_TIME = (2020, 1, 1, 0, 0, 0)  # reproducible: same inputs, same zip


def files_to_package() -> list[tuple[Path, str]]:
    items = [(ROOT / "azure" / "function_app.py", "function_app.py"), (ROOT / "azure" / "host.json", "host.json")]
    for path in sorted((ROOT / "fwcal").rglob("*.py")):
        items.append((path, path.relative_to(ROOT).as_posix()))
    for path in sorted((ROOT / "static").rglob("*")):
        rel = path.relative_to(ROOT).as_posix()
        if path.is_file() and not rel.startswith("static/tests/"):
            items.append((path, rel))
    return items


def install_dependencies(target: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "--require-hashes", "--no-deps", "--only-binary", ":all:",
         "--platform", PLATFORM, "--python-version", PYTHON_VERSION, "--implementation", "cp",
         "--target", str(target), "-r", str(ROOT / "azure" / "requirements.txt")],
        check=True,
    )


def build(out: Path) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        deps = Path(tmp) / "site-packages"
        install_dependencies(deps)
        entries = files_to_package()
        for path in sorted(p for p in deps.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            rel = path.relative_to(deps).as_posix()
            if rel.startswith("bin/"):
                continue  # command-line launchers: not used by the Function App, and platform-specific
            entries.append((path, ".python_packages/lib/site-packages/" + rel))
        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for path, name in sorted(entries, key=lambda e: e[1]):
                data = path.read_bytes()
                if name.endswith(".dist-info/RECORD"):  # drop the launchers' lines too
                    data = b"".join(line for line in data.splitlines(keepends=True) if b"bin/" not in line)
                info = zipfile.ZipInfo(name, FIXED_TIME)
                info.external_attr = 0o644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, data)
    return hashlib.sha256(out.read_bytes()).hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: build_package.py <output.zip>", file=sys.stderr)
        return 2
    if shutil.which("git") and subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], check=False,
                                              capture_output=True, text=True).stdout.strip():
        print("warning: the working tree has uncommitted changes", file=sys.stderr)
    print(f"sha256 {build(Path(argv[0]))}  {argv[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
