"""Cleaning of untrusted event text (DESIGN §5.4).

Every string that came from Graph passes through here before it is written to
events.json. The output is plain text: the browser renders it with
textContent only, so this module's job is legibility and anti-spoofing, not
HTML escaping.
"""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser
from itertools import pairwise

TITLE_MAX = 200
LOCATION_MAX = 200
NOTES_MAX = 2000
# Input beyond limit * factor can't survive whitespace collapsing and truncation
# in any useful form, so it is cut before the per-character work.
_INPUT_FACTOR = 10
_HTML_INPUT_MAX = 500_000
_MAX_COMBINING = 4

# Elements whose content is never shown.
_SKIP_TAGS = frozenset(
    {"script", "style", "head", "title", "template", "noscript", "svg", "math",
     "iframe", "object", "embed", "canvas", "select", "textarea", "button"}
)
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
     "source", "track", "wbr"}
)
_BLOCK_TAGS = frozenset(
    {"p", "div", "section", "article", "header", "footer", "blockquote", "pre",
     "table", "tr", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "dl",
     "dt", "dd", "address", "figure", "figcaption", "main", "nav", "aside"}
)
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.IGNORECASE)

# Format characters kept: ZWNJ and ZWJ (emoji sequences, some scripts).
_KEEP_FORMAT = frozenset({"\u200c", "\u200d"})

_LINE_SEP = re.compile(r"[  \r\x0b\x0c\x85]")
_HSPACE = re.compile(r"[^\S\n]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_SEPARATOR_LINE = re.compile(r"^[_\-=~*]{10,}$")
_URL = re.compile(r"\bhttps?://[^\s<>\"']+", re.IGNORECASE)
_URL_DISPLAY_MAX = 60
_MEETING_MARKERS = re.compile(
    r"microsoft teams|join the meeting|join on your computer|meeting id:|"
    r"skype meeting|teams\.microsoft\.com",
    re.IGNORECASE,
)


class _TextExtractor(HTMLParser):
    """Reduces HTML to text. Fails closed: unclosed hidden or script elements hide
    everything after them rather than leaking it."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip_tag: str | None = None
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_tag is not None:
            if tag == self._skip_tag and tag not in _VOID_TAGS:
                self._skip_depth += 1
            return
        attr = dict(attrs)
        hidden = (
            "hidden" in attr
            or (attr.get("aria-hidden") or "").lower() == "true"
            or _HIDDEN_STYLE.search(attr.get("style") or "") is not None
        )
        if (tag in _SKIP_TAGS or hidden) and tag not in _VOID_TAGS:
            self._skip_tag, self._skip_depth = tag, 1
            return
        if tag == "br":
            self._out.append("\n")
        elif tag == "li":
            self._out.append("\n• ")
        elif tag in ("td", "th"):
            self._out.append(" ")
        elif tag in _BLOCK_TAGS:
            self._out.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # <br/>, <div/>: never opens a skip region.
        if self._skip_tag is None and (tag == "br" or tag in _BLOCK_TAGS):
            self._out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._skip_tag is not None:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if self._skip_depth == 0:
                    self._skip_tag = None
            return
        if tag in _BLOCK_TAGS:
            self._out.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_tag is None:
            self._out.append(data)

    def text(self) -> str:
        return "".join(self._out)


def html_to_text(html: str) -> str:
    """Plain text from an HTML fragment. Entities are decoded exactly once."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text()


def _strip_invisible(s: str) -> str:
    out = []
    marks = 0
    for ch in s:
        if ch in "\n\t":
            out.append(ch)
            marks = 0
            continue
        cat = unicodedata.category(ch)
        # Cc control, Cs lone surrogates, Cf format (bidi overrides and isolates,
        # zero-width spaces, BOM, tag characters, soft hyphen): removed.
        if cat in ("Cc", "Cs") or (cat == "Cf" and ch not in _KEEP_FORMAT):
            continue
        # Stacked combining marks ("Zalgo" text) can draw over other parts of the
        # screen; real scripts need only a few per letter.
        if cat in ("Mn", "Me"):
            marks += 1
            if marks > _MAX_COMBINING:
                continue
        else:
            marks = 0
        out.append(ch)
    return "".join(out)


def _remove_meeting_boilerplate(s: str) -> str:
    """Drops online-meeting join blocks and separator lines (cosmetic)."""
    lines = s.split("\n")
    seps = [i for i, line in enumerate(lines) if _SEPARATOR_LINE.match(line.strip())]
    drop: set[int] = set(seps)
    # A meeting block sits between two separator lines.
    for a, b in pairwise(seps):
        if _MEETING_MARKERS.search("\n".join(lines[a + 1 : b])):
            drop.update(range(a, b + 1))
    # A trailing block after the last separator (Teams often omits the closing one).
    if seps and _MEETING_MARKERS.search("\n".join(lines[seps[-1] + 1 :])):
        drop.update(range(seps[-1], len(lines)))
    return "\n".join(line for i, line in enumerate(lines) if i not in drop)


def _shorten_url(match: re.Match[str]) -> str:
    url = match.group(0)
    if len(url) <= _URL_DISPLAY_MAX:
        return url
    host = re.sub(r"^https?://", "", url, flags=re.IGNORECASE).split("/", 1)[0]
    return host[:_URL_DISPLAY_MAX] + "/…"


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + "…"


def clean_line(value: object, limit: int) -> str:
    """A single-line field (title, location)."""
    if not isinstance(value, str):
        return ""
    s = unicodedata.normalize("NFC", value[: limit * _INPUT_FACTOR])
    s = _LINE_SEP.sub(" ", s)
    s = _strip_invisible(s)
    s = " ".join(s.split())
    s = _URL.sub(_shorten_url, s)
    return _truncate(s, limit)


def clean_notes(value: object, *, is_html: bool = False, limit: int = NOTES_MAX) -> str:
    """A multi-line field (event body)."""
    if not isinstance(value, str):
        return ""
    # Bound the work on hostile input before parsing; markup is verbose, so HTML
    # gets more room. Cutting HTML mid-tag fails closed (the tail is dropped).
    s = html_to_text(value[: _HTML_INPUT_MAX]) if is_html else value[: limit * _INPUT_FACTOR]
    s = unicodedata.normalize("NFC", s[: limit * _INPUT_FACTOR])
    s = _LINE_SEP.sub("\n", s.replace("\r\n", "\n"))
    s = _strip_invisible(s)
    s = s.replace("\t", " ")
    s = _remove_meeting_boilerplate(s)
    s = "\n".join(_HSPACE.sub(" ", line).strip() for line in s.split("\n"))
    s = _BLANK_LINES.sub("\n\n", s).strip()
    s = _URL.sub(_shorten_url, s)
    return _truncate(s, limit)
