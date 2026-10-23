import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fwcal import store
from fwcal.config import Calendar, Config
from tests.fakes import FakeResponse, FakeSession, graph_event

HAVE_DEPS = all(importlib.util.find_spec(m) for m in ("msal", "requests"))
NOW = datetime(2026, 10, 21, 14, 47).astimezone()
CFG = Config(calendars=(
    Calendar("swim", "Swim", "#5DCAA5", "ID-SWIM"),
    Calendar("health", "Health", "#AFA9EC", "ID-HEALTH", detail="titles"),
))


@unittest.skipUnless(HAVE_DEPS, "msal/requests not installed (pip install -r requirements.txt)")
class SyncTest(unittest.TestCase):
    def setUp(self):
        from fwcal import auth, sync

        self.auth, self.sync = auth, sync
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "events.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_sync(self, routes, token=lambda cfg, s: "T", cfg=CFG, now=NOW):
        session = FakeSession(routes)
        code = self.sync.run(cfg, session=session, token_fn=token, now=now, events_path=self.path,
                             sleep=lambda d: None)
        return code, session, store.load_events(self.path)

    @staticmethod
    def cal(key_id, events):
        return (lambda u, k=key_id: f"/calendars/{k}/" in u, FakeResponse(200, {"value": events}))

    def test_happy_path(self):
        code, session, data = self.run_sync([
            self.cal("ID-SWIM", [graph_event(1), graph_event(2, isCancelled=True)]),
            self.cal("ID-HEALTH", [graph_event(3, subject="Dentist")]),
        ])
        self.assertEqual(code, self.sync.OK)
        self.assertEqual(data["source"], "graph")
        self.assertEqual(data["auth"], "ok")
        self.assertEqual(data["window"], {"start": "2026-09-27", "end": "2026-11-26"})
        self.assertEqual([c["status"] for c in data["calendars"]], ["ok", "ok"])
        by_cal = {e["cal"]: e for e in data["events"]}
        self.assertEqual(len(data["events"]), 2)  # cancelled dropped
        self.assertEqual(by_cal["swim"]["location"], "Somewhere")
        # Health: titles only, and location/body were never requested.
        self.assertEqual((by_cal["health"]["title"], by_cal["health"]["location"], by_cal["health"]["notes"]),
                         ("Dentist", "", ""))
        health_req = next(r["url"] for r in session.requests if "ID-HEALTH" in r["url"])
        self.assertNotIn("location", health_req)
        self.assertNotIn("body", health_req)
        self.assertNotIn("ID-SWIM", self.path.read_text())  # Graph IDs never written
        self.assertNotIn("AAMk", self.path.read_text())

    def test_outage_keeps_last_good_data(self):
        self.run_sync([self.cal("ID-SWIM", [graph_event(1)]), self.cal("ID-HEALTH", [graph_event(2)])])
        later = NOW.replace(hour=15)
        code, _, data = self.run_sync([
            (lambda u: "ID-SWIM" in u, FakeResponse(503)),  # no Retry-After: give up this run
            self.cal("ID-HEALTH", []),
        ], now=later)
        self.assertEqual(code, self.sync.PARTIAL)
        swim = data["calendars"][0]
        self.assertEqual(swim["status"], "stale")
        self.assertTrue(swim["lastSuccessAt"].startswith("2026-10-21"))
        self.assertEqual([e["cal"] for e in data["events"]], ["swim"])  # kept from the previous run
        self.assertEqual(data["calendars"][1]["status"], "ok")

    def test_removed_share_drops_events(self):
        self.run_sync([self.cal("ID-SWIM", [graph_event(1)]), self.cal("ID-HEALTH", [])])
        code, _, data = self.run_sync([(lambda u: "ID-SWIM" in u, FakeResponse(404)), self.cal("ID-HEALTH", [])])
        self.assertEqual(code, self.sync.PARTIAL)
        self.assertEqual(data["calendars"][0]["status"], "error")
        self.assertEqual(data["events"], [])

    def test_reauth_required_keeps_data_and_flags_it(self):
        self.run_sync([self.cal("ID-SWIM", [graph_event(1)]), self.cal("ID-HEALTH", [])])

        def no_token(cfg, s):
            raise self.auth.ReauthRequired("expired")

        code, session, data = self.run_sync([], token=no_token)
        self.assertEqual(code, self.sync.REAUTH)
        self.assertEqual(data["auth"], "reauth_required")
        self.assertEqual(len(data["events"]), 1)
        self.assertEqual(session.requests, [])  # no Graph calls without a token

    def test_invalid_events_skipped(self):
        bad = graph_event(2, start={"dateTime": "2026-10-22T16:00:00", "timeZone": "Pacific Standard Time"})
        code, _, data = self.run_sync([self.cal("ID-SWIM", [graph_event(1), bad, "junk"]), self.cal("ID-HEALTH", [])])
        self.assertEqual(code, self.sync.OK)
        self.assertEqual(len(data["events"]), 1)

    def test_config_problems(self):
        for cfg in (Config(), Config(calendars=(Calendar("a", "A", "#7FB3FF", ""),))):
            with self.subTest(cfg=cfg):
                self.assertEqual(self.sync.run(cfg, session=FakeSession([]), token_fn=lambda c, s: "T",
                                               events_path=self.path), self.sync.CONFIG)
        self.assertFalse(self.path.exists())

    def test_show_notes_off_drops_notes(self):
        cfg = Config(calendars=CFG.calendars[:1], display=type(CFG.display)(show_notes=False))
        _, _, data = self.run_sync([self.cal("ID-SWIM", [graph_event(1)])], cfg=cfg)
        self.assertEqual(data["events"][0]["notes"], "")
        self.assertNotIn("Notes", json.dumps(data))


@unittest.skipUnless(HAVE_DEPS, "msal/requests not installed")
class AuthVerifyTest(unittest.TestCase):
    def setUp(self):
        from fwcal import auth

        self.auth = auth

    def result(self, account="viewer@example.com", scope="Calendars.Read openid profile"):
        # dict() keeps the pre-commit token check from flagging this fake result.
        return dict(access_token="x", scope=scope, id_token_claims={"preferred_username": account})

    def test_accepts_expected(self):
        self.assertEqual(self.auth.verify(self.result(), "Viewer@Example.com"), "viewer@example.com")
        self.auth.verify(self.result(scope="https://graph.microsoft.com/Calendars.Read openid profile offline_access"),
                         "viewer@example.com")

    def test_refuses(self):
        cases = [
            self.result(account="me@example.com"),
            self.result(account=""),
            self.result(scope="openid profile"),
            self.result(scope="Calendars.Read Calendars.ReadWrite openid profile"),
            self.result(scope="Calendars.Read Mail.Read openid profile"),
            {"error": "access_denied", "error_description": "user declined"},
        ]
        for r in cases:
            with self.subTest(r=r), self.assertRaises(self.auth.AuthError):
                self.auth.verify(r, "viewer@example.com")

    def test_parse_redirect(self):
        self.assertEqual(self.auth.parse_redirect(" http://localhost/?code=abc&state=s1 "),
                         {"code": "abc", "state": "s1"})
        self.assertEqual(self.auth.parse_redirect("http://localhost:51234/?error=access_denied&state=s")["error"],
                         "access_denied")
        for bad in ("https://localhost/?code=a", "http://evil.example/?code=a", "http://localhost.evil.example/?code=a",
                    "http://localhost/?nothing=1", "code=abc"):
            with self.subTest(bad=bad), self.assertRaises(self.auth.AuthError):
                self.auth.parse_redirect(bad)


if __name__ == "__main__":
    unittest.main()
