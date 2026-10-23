import subprocess
import unittest

from fwcal.paths import REPO_ROOT
from tools.precommit_check import problems


class PreCommit(unittest.TestCase):
    def test_blocked_paths(self):
        for path in ("config.toml", "deploy/fwcal.toml", "photos/a.jpg", "reference/dakboard.png",
                     "msal_cache.json", "data/events.json", "secrets/x", "id.pem", ".env", "a/.env.local"):
            with self.subTest(path=path):
                self.assertTrue(problems(path, b""))

    def test_allowed_paths(self):
        for path in ("config.example.toml", "pyproject.toml", "fwcal/server.py", "static/js/app.js",
                     "tests/test_mock.py"):
            with self.subTest(path=path):
                self.assertEqual(problems(path, b""), [])

    def test_blocked_content(self):
        jwt = b"ey" + b"J" + b"a" * 12 + b".ey" + b"J" + b"b" * 12
        samples = [
            b'{"refresh' + b'_token": "x"}',
            b'{"Refresh' + b'Token": {}}',
            jwt,
            b"-----BEGIN RSA " + b"PRIVATE KEY-----",
            b"client_" + b'secret = "abcdefgh"',
        ]
        for content in samples:
            with self.subTest(content=content[:20]):
                self.assertTrue(problems("notes.md", content))

    def test_invisible_characters_blocked(self):
        for code in (0x202E, 0x2066, 0x200B, 0xFEFF, 0x00AD, 0x0007, 0x001B):
            content = ('x = "a' + chr(code) + 'b"\n').encode("utf-8")
            with self.subTest(code=hex(code)):
                self.assertTrue(problems("fwcal/x.py", content))
        self.assertTrue(problems("fwcal/x.py", b"\xff\xfe"))
        # Visible non-ASCII text, tabs and CRLF are fine; binary files are skipped.
        self.assertEqual(problems("a.md", "Café, Zoë\tx\r\n".encode("utf-8")), [])
        self.assertEqual(problems("static/fonts/x.woff2", bytes(range(256))), [])

    def test_repository_files_pass(self):
        # Every file git would commit (tracked, or untracked and not ignored).
        result = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=REPO_ROOT,
                                capture_output=True)
        if result.returncode != 0:  # e.g. a root-owned deployment checkout ("dubious ownership")
            self.skipTest("git ls-files unavailable")
        out = result.stdout
        for rel in filter(None, out.decode("utf-8").split("\0")):
            with self.subTest(path=rel):
                self.assertEqual(problems(rel, (REPO_ROOT / rel).read_bytes()), [])


if __name__ == "__main__":
    unittest.main()
