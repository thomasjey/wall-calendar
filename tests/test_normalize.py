import unittest

from fwcal.normalize import InvalidEvent, event_id, normalize_event


def graph(**over):
    ev = {
        "id": "AAMkGRAPHID==", "subject": "Dentist", "isAllDay": False, "isCancelled": False,
        "start": {"dateTime": "2026-10-21T17:15:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-10-21T18:00:00.0000000", "timeZone": "UTC"},
        "location": {"displayName": "Main St Dental"}, "sensitivity": "normal",
        "body": {"contentType": "text", "content": "Bring forms"},
    }
    ev.update(over)
    return ev


class Normalize(unittest.TestCase):
    def test_timed_event(self):
        out = normalize_event(graph(), "home", show_notes=True)
        self.assertEqual(out, {
            "id": event_id("home", "AAMkGRAPHID=="), "cal": "home", "title": "Dentist",
            "location": "Main St Dental", "notes": "Bring forms", "private": False,
            "allDay": False, "start": "2026-10-21T17:15:00Z", "end": "2026-10-21T18:00:00Z",
        })

    def test_graph_id_not_exposed(self):
        out = normalize_event(graph(), "home", show_notes=True)
        self.assertNotIn("AAMkGRAPHID", repr(out))
        self.assertRegex(out["id"], r"^[0-9a-f]{16}$")
        self.assertNotEqual(out["id"], event_id("work", "AAMkGRAPHID=="))

    def test_all_day_uses_dates_only(self):
        out = normalize_event(graph(
            isAllDay=True,
            start={"dateTime": "2026-10-21T00:00:00.0000000", "timeZone": "Pacific Standard Time"},
            end={"dateTime": "2026-10-24T00:00:00.0000000", "timeZone": "Pacific Standard Time"},
        ), "home", show_notes=True)
        self.assertEqual((out["allDay"], out["startDate"], out["endDate"]), (True, "2026-10-21", "2026-10-24"))
        self.assertNotIn("start", out)

    def test_all_day_end_before_start_becomes_one_day(self):
        out = normalize_event(graph(
            isAllDay=True,
            start={"dateTime": "2026-10-21T00:00:00", "timeZone": "UTC"},
            end={"dateTime": "2026-10-21T00:00:00", "timeZone": "UTC"},
        ), "home", show_notes=True)
        self.assertEqual(out["endDate"], "2026-10-22")

    def test_timed_non_utc_refused(self):
        with self.assertRaises(InvalidEvent):
            normalize_event(graph(start={"dateTime": "2026-10-21T17:15:00", "timeZone": "Pacific Standard Time"}),
                            "home", show_notes=True)

    def test_end_before_start_clamped(self):
        out = normalize_event(graph(end={"dateTime": "2026-10-21T10:00:00", "timeZone": "UTC"}),
                              "home", show_notes=True)
        self.assertEqual(out["end"], out["start"])

    def test_cancelled_dropped(self):
        self.assertIsNone(normalize_event(graph(isCancelled=True), "home", show_notes=True))

    def test_private_redacted(self):
        for level in ("private", "Confidential"):
            out = normalize_event(graph(sensitivity=level), "home", show_notes=True)
            self.assertEqual((out["title"], out["location"], out["notes"], out["private"]),
                             ("Private", "", "", True))

    def test_detail_titles_keeps_title_only(self):
        out = normalize_event(graph(), "health", show_notes=True, detail="titles")
        self.assertEqual((out["title"], out["location"], out["notes"]), ("Dentist", "", ""))
        self.assertEqual(out["start"], "2026-10-21T17:15:00Z")

    def test_detail_busy_hides_title(self):
        out = normalize_event(graph(), "health", show_notes=True, detail="busy")
        self.assertEqual((out["title"], out["location"], out["notes"]), ("Busy", "", ""))

    def test_detail_private_still_wins(self):
        out = normalize_event(graph(sensitivity="private"), "health", show_notes=True, detail="titles")
        self.assertEqual(out["title"], "Private")

    def test_unknown_detail_refused(self):
        with self.assertRaises(ValueError):
            normalize_event(graph(), "health", show_notes=True, detail="some")

    def test_show_notes_false_drops_notes(self):
        self.assertEqual(normalize_event(graph(), "home", show_notes=False)["notes"], "")

    def test_html_body_converted(self):
        out = normalize_event(graph(body={"contentType": "HTML", "content": "<p>a<script>x</script></p>"}),
                              "home", show_notes=True)
        self.assertEqual(out["notes"], "a")

    def test_text_body_is_not_parsed_as_html(self):
        out = normalize_event(graph(body={"contentType": "text", "content": "<b>bold</b>"}), "home",
                              show_notes=True)
        self.assertEqual(out["notes"], "<b>bold</b>")

    def test_missing_subject(self):
        self.assertEqual(normalize_event(graph(subject=None), "home", show_notes=True)["title"], "(No title)")

    def test_malformed_events(self):
        for bad in ([], {"subject": "x"}, graph(id=""), graph(start=None), graph(start={"dateTime": 5}),
                    graph(start={"dateTime": "2026-13-01T00:00:00", "timeZone": "UTC"}),
                    graph(end={"dateTime": "tomorrow", "timeZone": "UTC"})):
            with self.subTest(bad=bad), self.assertRaises(InvalidEvent):
                normalize_event(bad, "home", show_notes=True)


if __name__ == "__main__":
    unittest.main()
