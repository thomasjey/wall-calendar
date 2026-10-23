"""Source checks on the frontend (DESIGN §8.2) and vendored files."""

import hashlib
import re
import unittest

from fwcal.paths import STATIC_DIR

# Built from parts so this file doesn't trip itself or the pre-commit hook.
BANNED = [
    r"\.innerHTML\b", r"\.outerHTML\b", r"insertAdjacentHTML", r"document\.write", r"\beval\s*\(",
    r"new\s+Function\b", r"set(Timeout|Interval)\s*\(\s*['\"`]", r"\.href\s*=", r"<a[\s>]",
    r"window\.open\b", r"location\.(assign|replace)\b", r"\.srcdoc\b", r"createContextualFragment",
    r"DOMParser", r"document\.domain", r"postMessage", r"\bimport\s*\(", r"\.src\s*=",
]
ALLOWED_SRC_ASSIGN = {"js/dom.js"}  # setPhoto() validates the URL first


def frontend_files(*, include_tests=False):
    """The app's source. static/tests/ deliberately exercises blocked sinks and is
    served only in mock mode (server.load_static)."""
    return [p for p in STATIC_DIR.rglob("*")
            if p.suffix in (".js", ".html", ".css") and p.is_file()
            and (include_tests or not p.relative_to(STATIC_DIR).as_posix().startswith("tests/"))]


class FrontendSource(unittest.TestCase):
    def test_no_banned_sinks(self):
        for path in frontend_files():
            rel = path.relative_to(STATIC_DIR).as_posix()
            text = path.read_text(encoding="utf-8")
            for pattern in BANNED:
                if pattern == r"\.src\s*=" and rel in ALLOWED_SRC_ASSIGN:
                    continue
                with self.subTest(file=rel, pattern=pattern):
                    self.assertIsNone(re.search(pattern, text))

    def test_no_external_urls(self):
        for path in frontend_files(include_tests=True):
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertIsNone(re.search(r"(https?:)?//[a-z0-9.-]+\.[a-z]{2,}", text, re.IGNORECASE))

    def test_no_inline_script_or_style(self):
        for path in STATIC_DIR.rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertIsNone(re.search(r"<script(?![^>]*\bsrc=)[^>]*>", text))
                self.assertIsNone(re.search(r"<style\b|\sstyle=|\son[a-z]+=", text, re.IGNORECASE))

    def test_only_expected_file_types(self):
        allowed = {".html", ".css", ".js", ".woff2", ".txt", ".md"}
        for path in STATIC_DIR.rglob("*"):
            if path.is_file():
                self.assertIn(path.suffix, allowed, path)


class VendoredFonts(unittest.TestCase):
    def test_hashes_match_sources(self):
        sources = (STATIC_DIR / "fonts" / "SOURCES.md").read_text(encoding="utf-8")
        rows = re.findall(r"^\| `([^`]+)` \|.*\| `([0-9a-f]{64})` \|$", sources, re.MULTILINE)
        self.assertEqual({name for name, _ in rows}, {"InterVariable.woff2", "LICENSE.txt"})
        for name, digest in rows:
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((STATIC_DIR / "fonts" / name).read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
