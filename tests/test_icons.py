"""The app icons and manifest (static/icons, static/manifest.webmanifest)."""

import json
import struct
import unittest
import zlib

from fwcal.paths import STATIC_DIR
from tools import make_icons


def _pixels(png: bytes) -> bytes:
    """The decompressed image data. The compressed bytes depend on the zlib
    build (Python 3.14 on Windows ships zlib-ng), the pixels don't."""
    data, pos = b"", 8
    while pos < len(png):
        length, kind = struct.unpack(">I4s", png[pos:pos + 8])
        if kind == b"IDAT":
            data += png[pos + 8:pos + 8 + length]
        pos += 12 + length
    return zlib.decompress(data)


class Icons(unittest.TestCase):
    def test_committed_icons_match_the_generator(self):
        for name, size in make_icons.SIZES.items():
            with self.subTest(icon=name):
                committed = _pixels((STATIC_DIR / "icons" / name).read_bytes())
                expected = _pixels(make_icons._png(size, make_icons._render(size)))
                self.assertEqual(committed, expected, "run tools/make_icons.py and commit the result")

    def test_icons_are_opaque_pngs_of_the_right_size(self):
        for name, size in make_icons.SIZES.items():
            with self.subTest(icon=name):
                data = (STATIC_DIR / "icons" / name).read_bytes()
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                width, height, depth, colour_type = struct.unpack(">IIBB", data[16:26])
                self.assertEqual((width, height, depth, colour_type), (size, size, 8, 2))  # RGB, no alpha

    def test_manifest_fetched_with_the_session(self):
        # Browsers fetch a manifest without cookies unless told otherwise; behind
        # the sign-in layer that fetch is redirected to Microsoft and blocked by CSP.
        page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn('<link rel="manifest" href="/manifest.webmanifest" crossorigin="use-credentials">', page)

    def test_manifest(self):
        manifest = json.loads((STATIC_DIR / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["start_url"], "/")
        for icon in manifest["icons"]:
            self.assertTrue((STATIC_DIR / icon["src"].lstrip("/")).is_file(), icon["src"])


if __name__ == "__main__":
    unittest.main()
