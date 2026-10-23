import tomllib
import unittest

from fwcal import cli, config


class CalendarBlock(unittest.TestCase):
    def parse(self, block):
        return config.parse(tomllib.loads(block)).calendars[0]

    def test_round_trip(self):
        cal = self.parse(cli.calendar_block("swim", "Swim", "#5DCAA5", "AQMkADAw-_=", "titles"))
        self.assertEqual((cal.key, cal.name, cal.color, cal.graph_id, cal.detail),
                         ("swim", "Swim", "#5DCAA5", "AQMkADAw-_=", "titles"))

    def test_hostile_names_stay_inside_their_string(self):
        esc, bell, bidi = chr(27), chr(7), chr(0x202E)
        for name in ('Evil"\ndetail = "full', "Back\\slash", f"Esc{esc}[31m red{bell}", f"Bidi{bidi}txet",
                     "Party " + chr(0x1F389), "x" * 40):
            with self.subTest(name=name):
                cal = self.parse(cli.calendar_block("k", name, "#5DCAA5", "id", "titles"))
                self.assertEqual(cal.detail, "titles")
                for ch in (esc, bell, bidi, "\n"):
                    self.assertNotIn(ch, cal.name)

    def test_ask_detail_defaults_to_titles(self):
        self.assertEqual(cli._ask_detail("Health", read_line=lambda prompt: ""), "titles")
        answers = iter(["everything", "FULL"])
        self.assertEqual(cli._ask_detail("Swim", read_line=lambda prompt: next(answers)), "full")

    def test_slug(self):
        self.assertEqual(cli._slug("Book Club & Swim!"), "book-club-swim")
        self.assertEqual(cli._slug("!!!"), "calendar")
        self.assertLessEqual(len(cli._slug("a" * 100)), 32)


if __name__ == "__main__":
    unittest.main()
