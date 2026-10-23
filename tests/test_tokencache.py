import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fwcal import tokencache


class TokenCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.auth = Path(self.tmp.name) / "state" / "auth"
        patcher = mock.patch("fwcal.paths.auth_dir", return_value=self.auth)
        patcher.start()
        self.addCleanup(patcher.stop)
        win = mock.patch("fwcal.tokencache._protect_windows")
        self.protect = win.start()
        self.addCleanup(win.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_and_delete(self):
        self.assertIsNone(tokencache.load())
        tokencache.save('{"secret": "value"}')
        self.assertEqual(tokencache.load(), '{"secret": "value"}')
        self.assertTrue(tokencache.delete())
        self.assertIsNone(tokencache.load())
        self.assertFalse(tokencache.delete())

    def test_describe_never_shows_contents(self):
        tokencache.save('{"secret": "value"}')
        self.assertNotIn("value", tokencache.describe())

    @unittest.skipIf(sys.platform == "win32", "POSIX modes")
    def test_posix_modes_and_refusals(self):
        tokencache.save("{}")
        self.assertEqual(stat.S_IMODE(os.stat(self.auth).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(self.auth / tokencache.CACHE_NAME).st_mode), 0o600)
        os.chmod(self.auth / tokencache.CACHE_NAME, 0o644)
        with self.assertRaises(tokencache.InsecureCache):
            tokencache.load()
        os.chmod(self.auth / tokencache.CACHE_NAME, 0o600)
        os.chmod(self.auth, 0o755)
        with self.assertRaises(tokencache.InsecureCache):
            tokencache.load()

    @unittest.skipIf(sys.platform == "win32", "POSIX symlinks")
    def test_symlinked_cache_refused(self):
        tokencache.ensure_dir()
        target = Path(self.tmp.name) / "elsewhere.json"
        target.write_text("{}")
        os.symlink(target, self.auth / tokencache.CACHE_NAME)
        with self.assertRaises(OSError):
            tokencache.load()

    @unittest.skipUnless(sys.platform == "win32", "Windows ACL")
    def test_windows_acl_applied_on_save(self):
        tokencache.save("{}")
        self.protect.assert_called()

    def test_windows_acl_command(self):
        cmd = tokencache.windows_acl_command(Path("C:/x/auth"), "S-1-5-21-1-2-3-1001")
        self.assertEqual(cmd[:3], ["icacls", str(Path("C:/x/auth")), "/inheritance:r"])
        self.assertIn("*S-1-5-21-1-2-3-1001:(OI)(CI)F", cmd)
        self.assertIn("*S-1-5-18:(OI)(CI)F", cmd)  # SYSTEM
        self.assertEqual(sum(1 for a in cmd if a.startswith("*")), 2)  # nobody else

    def test_oversized_cache_refused(self):
        tokencache.save("x" * (tokencache.MAX_CACHE_BYTES + 1))
        with self.assertRaises(tokencache.InsecureCache):
            tokencache.load()


if __name__ == "__main__":
    unittest.main()
