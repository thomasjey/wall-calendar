"""The app icons and manifest (static/icons, static/manifest.webmanifest)."""

import json
import struct
import unittest

from fwcal.paths import STATIC_DIR
from tools import make_icons


class Icons(unittest.TestCase):
    def test_committed_icons_match_the_generator(self):
        for name, size in make_icons.SIZES.items():
            with self.subTest(icon=name):
                committed = (STATIC_DIR / "icons" / name).read_bytes()
                self.assertEqual(committed, make_icons._png(size, make_icons._render(size)),
                                 "run tools/make_icons.py and commit the result")

    def test_icons_are_opaque_pngs_of_the_right_size(self):
        for name, size in make_icons.SIZES.items():
            with self.subTest(icon=name):
                data = (STATIC_DIR / "icons" / name).read_bytes()
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                width, height, depth, colour_type = struct.unpack(">IIBB", data[16:26])
                self.assertEqual((width, height, depth, colour_type), (size, size, 8, 2))  # RGB, no alpha

    def test_manifest(self):
        manifest = json.loads((STATIC_DIR / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["start_url"], "/")
        for icon in manifest["icons"]:
            self.assertTrue((STATIC_DIR / icon["src"].lstrip("/")).is_file(), icon["src"])


if __name__ == "__main__":
    unittest.main()
