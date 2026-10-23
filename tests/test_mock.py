import json
import subprocess
import sys
import textwrap
import unittest
from datetime import datetime

from fwcal import mock, store
from fwcal.config import Config, Display
from fwcal.paths import REPO_ROOT


def build(status="fresh", show_notes=True):
    cfg = Config(display=Display(show_notes=show_notes))
    return mock.build_payload(datetime(2026, 10, 21, 14, 47).astimezone(), cfg, status)


class Mock(unittest.TestCase):
    def test_payload_is_valid(self):
        data = build()
        self.assertEqual(store.validate(data), data)
        self.assertEqual(data["window"], {"start": "2026-09-27", "end": "2026-11-26"})

    def test_adversarial_fixtures_are_cleaned(self):
        text = json.dumps(build()["events"], ensure_ascii=False)
        for s in ("<script>alert('script')", "HIDDEN TEXT", "ALSO HIDDEN", "comment must not show",
                  "javascript:", "phish.example", "\u202e", "\u200b", "\u2066", "\x07", "\x1b"):
            self.assertNotIn(s, text, s)
        # Markup in plain-text fields stays as visible text (rendered with textContent).
        self.assertIn("<img src=x onerror=alert(1)> Title with markup", text)

    def test_cancelled_dropped_private_redacted(self):
        events = build()["events"]
        self.assertFalse([e for e in events if "Cancelled" in e["title"]])
        private = [e for e in events if e["private"]]
        self.assertEqual([(e["title"], e["notes"]) for e in private], [("Private", "")])

    def test_health_calendar_titles_only(self):
        data = build()
        health = [e for e in data["events"] if e["cal"] == "health"]
        self.assertEqual(sorted(e["title"] for e in health), ["Annual check-up", "Dentist", "Flu shots"])
        self.assertTrue(all(e["location"] == "" and e["notes"] == "" for e in health))
        text = json.dumps(data)
        for s in ("Main St Dental", "Fasting", "insurance cards", "Community clinic"):
            self.assertNotIn(s, text)

    def test_show_notes_off(self):
        self.assertTrue(all(e["notes"] == "" for e in build(show_notes=False)["events"]))

    def test_statuses(self):
        self.assertEqual(build("reauth")["auth"], "reauth_required")
        self.assertTrue(all(c["status"] == "stale" for c in build("offline")["calendars"]))

    def test_mock_mode_has_no_network_or_msal(self):
        # A fresh interpreter: generate mock data, serve one request, and check
        # nothing outbound was attempted and no Microsoft libraries were loaded.
        code = textwrap.dedent("""
            import socket, sys, threading, http.client
            from datetime import datetime
            real_connect = socket.socket.connect
            outbound = []
            def guard(self, addr):
                if addr[0] != "127.0.0.1":
                    outbound.append(addr)
                    raise OSError("blocked")
                return real_connect(self, addr)
            socket.socket.connect = guard
            from fwcal import mock, server, store, samplephotos
            from fwcal.config import Config
            from fwcal.paths import STATIC_DIR
            import tempfile, pathlib
            d = pathlib.Path(tempfile.mkdtemp())
            store.write_events(d / "e.json", mock.build_payload(datetime.now().astimezone(), Config()))
            app = server.App(config=Config(), events_path=d / "e.json",
                             static=server.load_static(STATIC_DIR, include_tests=True),
                             photos=server.PhotoIndex(None), mock=True)
            httpd = server.make_server(app, 0)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1])
            c.request("GET", "/api/events", headers={"Host": f"127.0.0.1:{httpd.server_address[1]}"})
            assert c.getresponse().status == 200
            httpd.shutdown()
            bad = [m for m in ("msal", "requests", "urllib3", "jwt", "cryptography") if m in sys.modules]
            print("OUTBOUND", outbound, "MODULES", bad)
        """)
        out = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=False,
                             timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("OUTBOUND [] MODULES []", out.stdout)


if __name__ == "__main__":
    unittest.main()
