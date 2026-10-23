"""Pre-commit check: blocks secrets, private files and personal references (DESIGN §0, §7).

Enabled with `git config core.hooksPath tools/git-hooks`. Never bypass it with
--no-verify; fix the commit instead.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unicodedata

ALLOWED_PATHS = frozenset({"config.example.toml", "pyproject.toml"})
BLOCKED_PATHS = [
    (re.compile(r"(^|/)(photos|reference|secrets)/"), "personal or third-party files"),
    (re.compile(r"\.toml$"), "a config file"),
    (re.compile(r"(cache[^/]*|events[^/]*)\.json$", re.I), "a cache file"),
    (re.compile(r"\.(pem|key|pfx|p12|cer|crt)$|(^|/)\.env(\.|$)", re.I), "key material"),
]
# Patterns are written so this file doesn't match itself.
BLOCKED_CONTENT = [
    (re.compile(rb'"(refresh|access|id)_token"\s*:'), "an OAuth token field"),
    (re.compile(rb'"(RefreshToken|AccessToken|IdToken)"\s*:'), "an MSAL token cache"),
    (re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}"), "a JWT"),
    (re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
    (re.compile(rb"(client_secret|password)\s*[=:]\s*['\"][^'\"\s]{6,}", re.I), "a secret value"),
]


# The repository is public: no references to the people who use it, even
# indirect ones (DESIGN §0). Real names can't be listed here, because this file
# is public too; they stay in gitignored files only. Bracketed letters keep the
# words from matching this file.
PERSONAL_WORDS = re.compile(
    r"\b(w[i]fe|hu[s]band|sp[o]use|d[a]ughters?|k[i]ds?|t[e]ens?|t[e]enagers?|t[o]ddlers?|"
    r"b[a]by|m[o]m|m[u]m|d[a]d|m[o]ther|f[a]ther|gr[a]ndparents?|gr[a]ndma|gr[a]ndpa|"
    r"sch[o]ols?|h[o]useholds?|f[a]mily|f[a]milies)\b",
    re.I,
)
# Technical uses of those words, removed before checking.
PERSONAL_EXEMPT = re.compile(
    r"font-f[a]mily|\.f[a]mily\b|\bf[a]mily, kind\b|socket\(f[a]mily|\bwork (and|or) sch[o]ol accounts?\b",
    re.I,
)


def personal_words(text: str) -> list[str]:
    found = []
    for lineno, line in enumerate(text.split("\n"), 1):
        for m in PERSONAL_WORDS.finditer(PERSONAL_EXEMPT.sub(" ", line)):
            found.append(f'line {lineno}: "{m.group(0)}"')
    return found


BINARY_SUFFIXES = (".woff2", ".png", ".jpg", ".jpeg", ".webp")


def invisible_chars(text: str) -> list[str]:
    """Control, format (bidi overrides, zero-width) and surrogate characters.
    Source must spell them as escapes so reviewers can see them ("Trojan Source")."""
    found = []
    for lineno, line in enumerate(text.split("\n"), 1):
        for ch in line:
            cat = unicodedata.category(ch)
            if cat in ("Cf", "Cs") or (cat == "Cc" and ch not in "\t\r"):
                found.append(f"line {lineno}: U+{ord(ch):04X}")
    return found


def problems(path: str, content: bytes) -> list[str]:
    found = []
    if path not in ALLOWED_PATHS:
        found += [f"{path}: {why}" for rx, why in BLOCKED_PATHS if rx.search(path)]
    found += [f"{path}: contains {why}" for rx, why in BLOCKED_CONTENT if rx.search(content)]
    if not path.lower().endswith(BINARY_SUFFIXES):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            found.append(f"{path}: not UTF-8 text")
        else:
            found += [f"{path}: invisible character at {where}" for where in invisible_chars(text)[:5]]
            found += [f"{path}: personal reference at {where}" for where in personal_words(text)[:5]]
    return found


def staged() -> list[str]:
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
                         check=True, capture_output=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def main() -> int:
    found = []
    for path in staged():
        content = subprocess.run(["git", "show", f":{path}"], check=True, capture_output=True).stdout
        found += problems(path, content)
    if found:
        print("pre-commit: commit blocked (see DESIGN.md section 7):", *found, sep="\n  ", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
