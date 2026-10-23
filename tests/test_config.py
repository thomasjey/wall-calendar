import tempfile
import tomllib
import unittest
from pathlib import Path

from fwcal import config
from fwcal.paths import REPO_ROOT

GOOD = """
client_id = "11111111-2222-3333-4444-555555555555"
expected_account = "viewer@example.com"
port = 8765

[display]
clock = "12h"
week_start = "sunday"
show_notes = false
night_dim = []

[[calendars]]
key = "home"
name = "Home"
color = "#7FB3FF"
graph_id = "AAMk"
"""


class Config(unittest.TestCase):
    def parse(self, text):
        return config.parse(tomllib.loads(text))

    def test_good(self):
        cfg = self.parse(GOOD)
        self.assertEqual(cfg.calendars[0].key, "home")
        self.assertFalse(cfg.display.show_notes)
        self.assertEqual(cfg.display.night_dim, ())

    def test_detail_levels(self):
        for level in ("full", "titles", "busy"):
            cfg = self.parse(f'[[calendars]]\nkey = "h"\nname = "Health"\ncolor = "#AFA9EC"\ndetail = "{level}"')
            self.assertEqual(cfg.calendars[0].detail, level)
        self.assertEqual(self.parse(GOOD).calendars[0].detail, "full")
        with self.assertRaises(config.ConfigError):
            self.parse('[[calendars]]\nkey = "h"\nname = "Health"\ncolor = "#AFA9EC"\ndetail = "none"')

    def test_defaults(self):
        cfg = config.parse({})
        self.assertEqual((cfg.display.clock, cfg.display.week_start, cfg.display.show_notes), ("12h", "sunday", True))

    def test_location(self):
        self.assertIsNone(self.parse("").display.location)
        self.assertEqual(self.parse("[display]\nlocation = [51.4987, -0.1276]").display.location, (51.5, -0.1))
        self.assertEqual(self.parse("[display]\nlocation = [-34, 151]").display.location, (-34.0, 151.0))
        for bad in ("[91, 0]", "[0, 181]", '["51", "0"]', "[51.5]", "[true, false]", "[1, 2, 3]"):
            with self.subTest(bad=bad), self.assertRaises(config.ConfigError):
                self.parse(f"[display]\nlocation = {bad}")

    def test_example_file_parses(self):
        cfg = config.load(REPO_ROOT / "config.example.toml")
        self.assertTrue(cfg.calendars)

    def test_rejections(self):
        bad = [
            'unknown = 1',
            '[display]\ncolour = "x"',
            'port = 80',
            'port = true',
            'client_id = "not-a-guid"',
            'expected_account = "nobody"',
            '[display]\nclock = "13h"',
            '[display]\nweek_start = "friday"',
            '[display]\nshow_notes = "yes"',
            '[display]\nnight_dim = ["25:00", "06:00"]',
            '[[calendars]]\nkey = "Home"\nname = "F"\ncolor = "#7FB3FF"',
            '[[calendars]]\nkey = "f"\nname = "F"\ncolor = "red"',
            '[[calendars]]\nkey = "f"\nname = "F"\ncolor = "#7FB3FF;x"',
            '[[calendars]]\nkey = "f"\nname = ""\ncolor = "#7FB3FF"',
            '[[calendars]]\nkey = "f"\nname = "F"\ncolor = "#7FB3FF"\n[[calendars]]\nkey = "f"\nname = "G"\ncolor = "#7FB3FF"',
        ]
        for text in bad:
            with self.subTest(text=text), self.assertRaises(config.ConfigError):
                self.parse(text)

    def test_load_reports_toml_errors(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text("port = ", encoding="utf-8")
            with self.assertRaises(config.ConfigError):
                config.load(p)


if __name__ == "__main__":
    unittest.main()
