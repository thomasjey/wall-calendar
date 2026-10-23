import json
import os
import stat
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fwcal import mock, store
from fwcal.config import Config


def payload():
    return mock.build_payload(datetime(2026, 10, 21, 14, 47).astimezone(), Config())


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip(self):
        p = self.dir / "data" / "events.json"
        data = payload()
        store.write_events(p, data)
        self.assertEqual(store.load_events(p), store.validate(data))
        self.assertEqual([x.name for x in p.parent.iterdir()], ["events.json"])  # no temp files left

    @unittest.skipIf(sys.platform == "win32", "POSIX modes")
    def test_modes(self):
        p = self.dir / "events.json"
        store.write_events(p, payload())
        self.assertEqual(stat.S_IMODE(os.stat(p).st_mode) & 0o777, 0o640 & ~self._umask())

    @staticmethod
    def _umask():
        m = os.umask(0)
        os.umask(m)
        return m

    def test_output_is_ascii(self):
        p = self.dir / "events.json"
        store.write_events(p, payload())
        p.read_bytes().decode("ascii")

    def test_bad_files(self):
        p = self.dir / "events.json"
        for raw in (b"", b"{", b"[]", b'{"schema": 2}', b"\xff\xfe", b"[" * 100_000):
            p.write_bytes(raw)
            with self.subTest(raw=raw[:10]), self.assertRaises(store.InvalidEventsFile):
                store.load_events(p)

    def test_too_large(self):
        p = self.dir / "events.json"
        p.write_bytes(b" " * (store.MAX_FILE_BYTES + 1))
        with self.assertRaises(store.InvalidEventsFile):
            store.load_events(p)

    def test_bad_calendar_rejects_file(self):
        for field, value in (("color", "red;}"), ("color", "#fff"), ("key", "A B"), ("status", "weird"),
                             ("name", "x" * 41), ("lastSuccessAt", "yesterday")):
            data = payload()
            data["calendars"][0][field] = value
            with self.subTest(field=field), self.assertRaises(store.InvalidEventsFile):
                store.validate(data)

    def test_bad_events_dropped(self):
        data = payload()
        good = len(data["events"])
        data["events"] += [
            {**data["events"][0], "cal": "unknown"},
            {**data["events"][0], "id": "../../etc"},
            {**data["events"][0], "title": "x" * 201},
            {**data["events"][0], "title": 5},
            {**data["events"][0], "start": "2026-10-21 10:00"},
            {**data["events"][0], "private": "no"},
            "not an object",
        ]
        self.assertEqual(len(store.validate(data)["events"]), good)

    def test_unknown_fields_not_passed_through(self):
        data = payload()
        data["extra"] = "x"
        data["events"][0]["html"] = "<b>"
        data["calendars"][0]["graphId"] = "AAMk"
        out = json.dumps(store.validate(data))
        for s in ('"extra"', '"html"', "AAMk"):
            self.assertNotIn(s, out)


if __name__ == "__main__":
    unittest.main()
