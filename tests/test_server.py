import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path

from fwcal import mock, server, store
from fwcal.config import Config
from fwcal.paths import STATIC_DIR

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.events = root / "events.json"
        store.write_events(cls.events, mock.build_payload(datetime.now().astimezone(), Config()))
        photos = root / "photos"
        photos.mkdir()
        (photos / "beach.png").write_bytes(PNG)
        (photos / "evil.svg").write_bytes(b"<svg onload='alert(1)'/>")
        (photos / "fake.jpg").write_bytes(b"<html>not a jpeg</html>")
        (photos / "notes.txt").write_bytes(b"x")
        (photos / "sub").mkdir()
        (photos / "sub" / "deep.png").write_bytes(PNG)
        if sys.platform != "win32":
            os.symlink(cls.events, photos / "link.png")
        cls.app = server.App(
            config=Config(), events_path=cls.events,
            static=server.load_static(STATIC_DIR, include_tests=False),
            photos=server.PhotoIndex(photos),
        )
        cls.httpd = server.make_server(cls.app, 0)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def request(self, path, method="GET", host=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", host if host is not None else f"127.0.0.1:{self.port}")
        for k, v in (headers or {}).items():
            conn.putheader(k, v)
        conn.endheaders()
        r = conn.getresponse()
        body = r.read()
        conn.close()
        return r, body

    def test_bound_to_loopback_only(self):
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")
        self.assertEqual(self.httpd.socket.family, socket.AF_INET)

    def test_index_and_headers(self):
        r, body = self.request("/")
        self.assertEqual(r.status, 200)
        self.assertIn(b"/js/app.js", body)
        self.assertEqual(r.getheader("Content-Type"), "text/html; charset=utf-8")
        for k, v in server.SECURITY_HEADERS.items():
            self.assertEqual(r.getheader(k), v)
        self.assertIn("require-trusted-types-for 'script'", r.getheader("Content-Security-Policy"))
        self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))
        self.assertEqual(r.getheader("Server"), "fwcal")

    def test_static_files(self):
        for path, ctype in (("/app.css", "text/css"), ("/js/app.js", "text/javascript"),
                            ("/fonts/InterVariable.woff2", "font/woff2"), ("/icons/icon-32.png", "image/png"),
                            ("/icons/apple-touch-icon.png", "image/png"),
                            ("/manifest.webmanifest", "application/manifest+json")):
            r, _ = self.request(path)
            self.assertEqual(r.status, 200, path)
            self.assertTrue(r.getheader("Content-Type").startswith(ctype))

    def test_not_served(self):
        for path in ("/index.html", "/fonts/LICENSE.txt", "/fonts/SOURCES.md", "/tests/index.html",
                     "/../DESIGN.md", "/js/../../fwcal/server.py", "/%2e%2e/DESIGN.md", "/js/%2e%2e/app.css",
                     "/..%5cDESIGN.md", "/js\\app.js", "//etc/passwd", "/photos/", "/photos/../events.json",
                     "/api", "/api/events/", "/favicon.ico"):
            r, _ = self.request(path)
            self.assertEqual(r.status, 404, path)

    def test_bad_host_rejected(self):
        for host in ("evil.example", f"evil.example:{self.port}", "127.0.0.1", "127.0.0.1:1",
                     f"localhost.evil.example:{self.port}", ""):
            r, body = self.request("/api/events", host=host)
            self.assertEqual(r.status, 421, host)
            self.assertNotIn(b"events", body)
        r, _ = self.request("/", host=f"localhost:{self.port}")
        self.assertEqual(r.status, 200)

    def test_cross_site_rejected(self):
        for site in ("cross-site", "same-site"):
            r, _ = self.request("/api/events", headers={"Sec-Fetch-Site": site})
            self.assertEqual(r.status, 403, site)
        for site in ("same-origin", "none"):
            r, _ = self.request("/api/events", headers={"Sec-Fetch-Site": site})
            self.assertEqual(r.status, 200, site)

    def test_methods(self):
        for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS", "TRACE"):
            r, _ = self.request("/api/events", method=method)
            self.assertEqual(r.status, 405, method)
            self.assertEqual(r.getheader("Allow"), "GET, HEAD")
        r, body = self.request("/api/events", method="HEAD")
        self.assertEqual((r.status, body), (200, b""))
        r, _ = self.request("/", method="FOO")
        self.assertEqual(r.status, 501)
        self.assertEqual(r.getheader("Content-Type"), "text/plain; charset=utf-8")

    def test_query_and_absolute_form_rejected(self):
        for path in ("/api/events?x=1", "/?", "http://evil.example/api/events"):
            r, _ = self.request(path)
            self.assertEqual(r.status, 400, path)

    def test_oversized_headers(self):
        r, _ = self.request("/", headers={"X-Big": "a" * 9000})
        self.assertEqual(r.status, 431)

    def test_events_api(self):
        r, body = self.request("/api/events")
        self.assertEqual(r.getheader("Cache-Control"), "no-store")
        self.assertEqual(r.getheader("Content-Type"), "application/json")
        data = json.loads(body)
        self.assertEqual(data["source"], "mock")
        self.assertEqual(store.validate(data), data)

    def test_events_not_modified(self):
        r, body = self.request("/api/events")
        etag = r.getheader("ETag")
        self.assertRegex(etag, r'^"[0-9a-f]{32}"$')
        r2, body2 = self.request("/api/events", headers={"If-None-Match": etag})
        self.assertEqual((r2.status, body2), (304, b""))
        self.assertEqual(r2.getheader("ETag"), etag)
        self.assertIsNone(r2.getheader("Content-Length"))
        self.assertEqual(r2.getheader("Content-Security-Policy"), server.CSP)
        r3, body3 = self.request("/api/events", headers={"If-None-Match": '"stale"'})
        self.assertEqual((r3.status, body3), (200, body))

    def test_events_reread_only_when_file_changes(self):
        from unittest import mock

        self.request("/api/events")  # prime the cache
        with mock.patch("fwcal.store.load_events", wraps=store.load_events) as load:
            for _ in range(3):
                self.request("/api/events")
            self.assertEqual(load.call_count, 0)
            good = self.events.read_bytes()
            try:
                data = json.loads(good)
                data["generatedAt"] = "2030-01-01T00:00:00Z"
                store.write_events(self.events, data)
                _, body = self.request("/api/events")
                self.assertEqual(load.call_count, 1)
                self.assertEqual(json.loads(body)["generatedAt"], "2030-01-01T00:00:00Z")
            finally:
                self.events.write_bytes(good)

    def test_events_api_malformed_file(self):
        good = self.events.read_bytes()
        try:
            self.events.write_bytes(b'{"schema":1,"events":"<script>"}')
            r, body = self.request("/api/events")
            self.assertEqual(r.status, 200)
            self.assertEqual(json.loads(body), server.NO_DATA)
        finally:
            self.events.write_bytes(good)

    def test_settings_api(self):
        _, body = self.request("/api/settings")
        s = json.loads(body)
        self.assertEqual((s["clock"], s["weekStart"], s["showNotes"], s["debugNow"]), ("12h", "sunday", True, None))
        self.assertIsNone(s["location"])  # not configured: the page uses fixed hours for its sky

    def test_photos(self):
        _, body = self.request("/api/photos")
        urls = json.loads(body)["photos"]
        # Only top-level .png/.jpg/... files that are not symlinks; names are opaque.
        self.assertEqual(len(urls), 2)
        for u in urls:
            self.assertRegex(u, r"^/photos/[0-9a-f]{16}$")
            self.assertNotIn("beach", u)
        statuses = sorted(self.request(u)[0].status for u in urls)
        self.assertEqual(statuses, [200, 404])  # fake.jpg fails the magic-number check
        r, body = self.request(next(u for u in urls if self.request(u)[0].status == 200))
        self.assertEqual((r.getheader("Content-Type"), body), ("image/png", PNG))


if __name__ == "__main__":
    unittest.main()
