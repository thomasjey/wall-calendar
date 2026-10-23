import importlib.util
import unittest
from urllib.parse import parse_qs, urlsplit

from tests.fakes import FakeResponse, FakeSession, graph_event

HAVE_DEPS = importlib.util.find_spec("requests") is not None


@unittest.skipUnless(HAVE_DEPS, "requests not installed (pip install -r requirements.txt)")
class GraphTest(unittest.TestCase):
    def setUp(self):
        from fwcal import graph

        self.graph = graph

    def view_url(self, session):
        return session.requests[0]["url"]

    def test_select_per_detail_level(self):
        g = self.graph
        self.assertIn("location", g.select_for("full").split(","))
        self.assertIn("body", g.select_for("full").split(","))
        titles = g.select_for("titles").split(",")
        self.assertIn("subject", titles)
        self.assertNotIn("location", titles)
        self.assertNotIn("body", titles)
        busy = g.select_for("busy").split(",")
        for f in ("subject", "location", "body"):
            self.assertNotIn(f, busy)

    def test_calendar_view_request(self):
        s = FakeSession([(lambda u: "calendarView" in u, FakeResponse(200, {"value": [graph_event(1)]}))])
        events, truncated = self.graph.Graph(s, "TOKEN").calendar_view("AQMk/abc+=", "2026-10-01T00:00:00Z",
                                                                       "2026-11-01T00:00:00Z", "titles")
        self.assertEqual((len(events), truncated), (1, False))
        req = s.requests[0]
        url = urlsplit(req["url"])
        self.assertEqual((url.scheme, url.hostname), ("https", "graph.microsoft.com"))
        self.assertIn("/me/calendars/AQMk%2Fabc%2B%3D/calendarView", url.path)  # id fully escaped
        q = parse_qs(url.query)
        self.assertEqual(q["$select"][0], self.graph.select_for("titles"))
        self.assertEqual(q["startDateTime"][0], "2026-10-01T00:00:00Z")
        self.assertIn('outlook.timezone="UTC"', req["headers"]["Prefer"])
        self.assertIn('outlook.body-content-type="text"', req["headers"]["Prefer"])
        self.assertFalse(req["allow_redirects"])
        self.assertEqual(req["headers"]["Authorization"], "Bearer TOKEN")

    def test_paging_follows_only_graph_links(self):
        page2 = "https://graph.microsoft.com/v1.0/me/calendars/x/calendarView?$skip=1"
        s = FakeSession([
            (lambda u: "skip" in u, FakeResponse(200, {"value": [graph_event(2)]})),
            (lambda u: True, FakeResponse(200, {"value": [graph_event(1)], "@odata.nextLink": page2})),
        ])
        events, _ = self.graph.Graph(s, "T").calendar_view("x", "a", "b", "full")
        self.assertEqual([e["id"] for e in events], ["AAMk1", "AAMk2"])

    def test_foreign_next_link_refused_before_sending_token(self):
        for evil in ("https://evil.example/steal", "http://graph.microsoft.com/v1.0/x",
                     "https://graph.microsoft.com.evil.example/x", "https://user@graph.microsoft.com/x",
                     "https://graph.microsoft.com:8443/x"):
            s = FakeSession([(lambda u: True, FakeResponse(200, {"value": [], "@odata.nextLink": evil}))])
            with self.subTest(evil=evil), self.assertRaises(self.graph.GraphError):
                self.graph.Graph(s, "T").calendar_view("x", "a", "b", "full")
            self.assertEqual(len(s.requests), 1)

    def test_page_and_event_caps(self):
        g = self.graph
        many = {"value": [graph_event(i) for i in range(50)]}
        s = FakeSession([(lambda u: True, lambda u: FakeResponse(200, {
            **many, "@odata.nextLink": "https://graph.microsoft.com/v1.0/next"}))])
        events, truncated = g.Graph(s, "T").calendar_view("x", "a", "b", "full")
        self.assertTrue(truncated)
        self.assertEqual(len(events), min(g.MAX_EVENTS, g.MAX_PAGES * 50))
        self.assertLessEqual(len(s.requests), g.MAX_PAGES)

    def test_response_size_cap(self):
        s = FakeSession([(lambda u: True, FakeResponse(200, raw=b" " * (self.graph.MAX_RESPONSE_BYTES + 1)))])
        with self.assertRaises(self.graph.GraphError):
            self.graph.Graph(s, "T").calendar_view("x", "a", "b", "full")

    def test_errors_and_access_lost(self):
        for status, lost in ((401, False), (403, True), (404, True), (500, False)):
            s = FakeSession([(lambda u: True, FakeResponse(status, {"error": {}}, {"request-id": "r1"}))])
            with self.subTest(status=status):
                with self.assertRaises(self.graph.GraphError) as cm:
                    self.graph.Graph(s, "T").calendar_view("x", "a", "b", "full")
                self.assertEqual((cm.exception.status, cm.exception.access_lost), (status, lost))
                self.assertNotIn("T", str(cm.exception).replace("HTTP", ""))

    def test_throttling_within_budget(self):
        calls = iter([FakeResponse(429, headers={"Retry-After": "3"}), FakeResponse(200, {"value": []})])
        slept = []
        s = FakeSession([(lambda u: True, lambda u: next(calls))])
        self.graph.Graph(s, "T", sleep=slept.append).calendar_view("x", "a", "b", "full")
        self.assertEqual(slept, [3])

    def test_throttling_beyond_budget_or_unparseable(self):
        for value in ("600", "soon", None):
            headers = {"Retry-After": value} if value else {}
            s = FakeSession([(lambda u: True, FakeResponse(503, headers=headers))])
            with self.subTest(value=value), self.assertRaises(self.graph.GraphError):
                self.graph.Graph(s, "T", sleep=lambda d: None).calendar_view("x", "a", "b", "full")

    def test_non_json_and_wrong_shapes(self):
        for resp in (FakeResponse(200, raw=b"<html>"), FakeResponse(200, raw=b"[]"), FakeResponse(200, {"value": 5})):
            s = FakeSession([(lambda u: True, resp)])
            with self.assertRaises(self.graph.GraphError):
                self.graph.Graph(s, "T").calendar_view("x", "a", "b", "full")


if __name__ == "__main__":
    unittest.main()
