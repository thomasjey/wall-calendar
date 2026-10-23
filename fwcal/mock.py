"""Mock data (DESIGN §10.5): Graph-shaped events relative to "now", passed
through the same normalisation as real data. Never imports MSAL or opens a
network connection."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .config import Calendar, Config
from .normalize import InvalidEvent, normalize_event
from .window import sync_window

CALENDARS = (
    Calendar("home", "Home", "#7FB3FF"),
    Calendar("activities", "Activities", "#5DCAA5"),
    Calendar("events", "Events", "#ED93B1"),
    Calendar("work", "Work", "#EF9F27"),
    Calendar("health", "Health", "#AFA9EC", detail="titles"),
    Calendar("test", "Test", "#B4B2A9"),
)
STATUSES = ("fresh", "stale", "offline", "reauth")

_TEAMS_BLOCK = (
    "Agenda: budget review.\n\n"
    "________________________________________________________________________________\n"
    "Microsoft Teams meeting\n"
    "Join on your computer, mobile app or room device\n"
    "Click here to join the meeting <https://teams.microsoft.com/l/meetup-join/19%3ameeting_ZmFrZQ%40thread.v2/0?context=%7b%22Tid%22%3a%22fake%22%7d>\n"
    "Meeting ID: 000 000 000 000\nPasscode: fake00\n"
    "________________________________________________________________________________"
)

_HTML_ATTACK = (
    '<html><head><title>t</title><style>p{color:red}</style></head><body>'
    "<div>Agenda for the visit<script>alert('script')</script></div>"
    '<img src="x" onerror="alert(\'img\')">'
    '<p><a href="javascript:alert(\'link\')">Click me</a> and '
    '<a href="https://phish.example/login">sign in here</a></p>'
    '<p style="display:none">HIDDEN TEXT MUST NOT SHOW</p><span hidden>ALSO HIDDEN</span>'
    "<!-- comment must not show -->"
    "<ul><li>Bring snacks</li><li>Bring water</li></ul>"
    "<p>&lt;b&gt;escaped markup shows literally&lt;/b&gt; &amp; entities decode once: &amp;lt;</p>"
    "</body></html>"
)


class _Builder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self._n = 0

    def _id(self) -> str:
        self._n += 1
        return f"AAMkMOCK{self._n:06d}="

    @staticmethod
    def _utc(day: date, hhmm: str, extra_min: int = 0) -> dict:
        h, m = (int(x) for x in hhmm.split(":"))
        local = datetime(day.year, day.month, day.day, h, m) + timedelta(minutes=extra_min)
        utc = local.astimezone().astimezone(timezone.utc)
        return {"dateTime": utc.strftime("%Y-%m-%dT%H:%M:%S.0000000"), "timeZone": "UTC"}

    def timed(self, cal: str, title: str, day: date, start: str, minutes: int,
              location: str = "", notes: str = "", **extra) -> None:
        ev = {
            "id": self._id(), "subject": title, "isAllDay": False, "isCancelled": False,
            "start": self._utc(day, start), "end": self._utc(day, start, minutes),
            "location": {"displayName": location}, "sensitivity": "normal", "showAs": "busy",
            "body": {"contentType": "text", "content": notes}, "type": "singleInstance",
        }
        ev.update(extra)
        self.events.append((cal, ev))

    def all_day(self, cal: str, title: str, day: date, days: int = 1, notes: str = "") -> None:
        end = day + timedelta(days=days)
        self.events.append((cal, {
            "id": self._id(), "subject": title, "isAllDay": True, "isCancelled": False,
            "start": {"dateTime": f"{day.isoformat()}T00:00:00.0000000", "timeZone": "UTC"},
            "end": {"dateTime": f"{end.isoformat()}T00:00:00.0000000", "timeZone": "UTC"},
            "location": {"displayName": ""}, "sensitivity": "normal", "showAs": "free",
            "body": {"contentType": "text", "content": notes}, "type": "singleInstance",
        }))


def _graph_events(today: date, start: date, end: date) -> list[tuple[str, dict]]:
    b = _Builder()
    quiet = today + timedelta(days=6)  # an empty day
    d = start
    while d < end:
        wd = d.weekday()  # Mon=0
        if d != quiet:
            if wd < 5:
                b.timed("activities", "Gym", d, "07:00", 45)
            if wd in (0, 2):
                b.timed("activities", "Tennis practice", d, "18:00", 60, "Riverside Park, court 2",
                        "Bring a racket and a water bottle.")
            if wd == 3:
                b.timed("activities", "Guitar lesson", d, "18:30", 45, "Music studio")
            if wd == 1:
                b.timed("work", "Team planning", d, "09:00", 60, "Video call", _TEAMS_BLOCK)
            if wd == 5:
                b.timed("activities", "Tennis match", d, "10:00", 90, "Lincoln Courts")
            if wd == 6:
                b.timed("home", "Pancake breakfast", d, "09:00", 60)
            if wd == 2 and d.isocalendar().week % 2 == 0:
                b.timed("home", "Book club", d, "19:00", 90, "Library, room B")
        d += timedelta(days=1)

    t = today
    day = lambda n: t + timedelta(days=n)  # noqa: E731
    b.all_day("home", "Guests visiting", t, 3, "Guest room is ready.")
    # Health uses detail="titles": location and notes are dropped by normalisation.
    b.timed("health", "Dentist", t, "17:15", 45, "Main St Dental",
            "Routine check-up.\nBring the forms from the front desk.")
    b.timed("events", "Neighbourhood meeting", day(-1), "16:00", 30, "Room 12")
    b.timed("work", "Lunch with Sam", day(1), "12:30", 60, "Corner Cafe")
    b.timed("home", "Dinner out", day(1), "18:00", 90)
    b.timed("home", "Movie night", day(2), "19:00", 120)
    b.timed("activities", "Overnight hike", day(3), "19:00", 14 * 60, "Trailhead", "Overnight; back by 9.")
    b.timed("events", "Friend's birthday party", day(4), "14:00", 120, "Riverside Hall")
    b.all_day("events", "Street fair", day(5))
    for i, (hhmm, title) in enumerate(
        [("08:00", "Bake sale setup"), ("09:30", "Street fair: music"), ("10:15", "Street fair: food trucks"),
         ("11:00", "Picnic lunch"), ("12:30", "Photo booth"), ("13:15", "Awards"),
         ("15:00", "Clean-up crew"), ("17:00", "Pizza night"), ("20:00", "Wind down")]
    ):
        b.timed(("events", "home", "activities")[i % 3], title, day(5), hhmm, 40)
    b.timed("work", "Doctor appointment", day(7), "10:00", 60, "Clinic", "Private details",
            sensitivity="private")
    b.timed("home", "Cancelled: yard sale", day(8), "09:00", 120, isCancelled=True)
    b.timed("events", "Fall festival", day(-10), "11:00", 180, "Town square")
    b.timed("activities", "Haircut", day(-5), "16:00", 45)
    b.all_day("events", "Public holiday", day(12))
    b.timed("health", "Flu shots", day(14), "17:00", 30, "Pharmacy", "Bring insurance cards.")
    b.timed("health", "Annual check-up", day(2), "08:30", 60, "Community clinic", "Fasting from midnight.")
    b.timed("events", "Choir recital", day(16), "18:30", 90, "Town hall")
    b.all_day("home", "Camping trip", day(18), 4, "Pack the tent.")

    # Adversarial fixtures (DESIGN §10.5): shown on the Test calendar.
    a, a2 = day(9), day(10)
    b.timed("test", "HTML body", a, "09:00", 30, "", _HTML_ATTACK)
    b.events[-1][1]["body"]["contentType"] = "html"
    b.timed("test", "<img src=x onerror=alert(1)> Title with markup", a, "10:00", 30,
            "<b>Room 5</b>", "<script>alert('notes')</script> shows as text")
    b.timed("test", "Invoice \u202egnp.exe and zero\u200bwidth\u2060 text", a, "11:00", 30,
            "Office\u202e evil", "Bidi \u2066isolate\u2069 and \u200bzero-width removed.")
    b.timed("test", "Long " * 2000, a, "12:00", 30, "x" * 1000, "word " * 3000)
    b.timed("test", "Party \U0001f389 \U0001f9d1\u200d\U0001f373 מסיבה حفلة", a2, "09:00", 60,
            "Café Zoë", "RTL: שלום עולם\nEmoji: \U0001f9c1")
    b.timed("test", "Control\x07chars\x00 and \ud800 lone surrogate", a2, "10:00", 30, "",
            "Line one\r\nLine two Line three\x1b[31m")
    b.timed("test", "Link-only notes", a2, "11:00", 30, "",
            "Details: https://example.com/a/very/long/path/that/goes/on/and/on?with=query&and=more&tracking=abcdef123456\n"
            "Short: https://example.com/x")
    return b.events


def build_payload(now_local: datetime, cfg: Config, status: str = "fresh") -> dict:
    """now_local: an aware local datetime."""
    today = now_local.date()
    start, end = sync_window(today, cfg.lookahead_days, cfg.display.week_start)
    now_utc = now_local.astimezone(timezone.utc)
    last = now_utc - {"fresh": timedelta(0), "stale": timedelta(minutes=25),
                      "offline": timedelta(minutes=75), "reauth": timedelta(minutes=40)}[status]
    detail = {c.key: c.detail for c in CALENDARS}
    events = []
    for cal, ev in _graph_events(today, start, end):
        try:
            out = normalize_event(ev, cal, show_notes=cfg.display.show_notes, detail=detail[cal])
        except InvalidEvent:
            continue
        if out is not None:
            events.append(out)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return {
        "schema": 1,
        "source": "mock",
        "generatedAt": now_utc.strftime(fmt),
        "auth": "reauth_required" if status == "reauth" else "ok",
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "calendars": [
            {"key": c.key, "name": c.name, "color": c.color,
             "status": "ok" if status == "fresh" else "stale",
             "lastSuccessAt": last.strftime(fmt), "truncated": False}
            for c in CALENDARS
        ],
        "events": events,
    }
