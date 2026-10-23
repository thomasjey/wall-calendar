import unittest

from fwcal import textclean as tc


class HtmlToText(unittest.TestCase):
    def test_script_style_head_and_comments_dropped(self):
        html = ("<head><title>T</title><style>p{}</style></head><p>Hello<script>alert(1)</script></p>"
                "<!-- secret --><noscript>ns</noscript>")
        self.assertEqual(tc.clean_notes(html, is_html=True), "Hello")

    def test_hidden_elements_dropped(self):
        html = ('<p>Shown</p><p style="display: none">a</p><div hidden>b</div>'
                '<span aria-hidden="true">c</span><div style="visibility:hidden"><div>d</div></div><p>End</p>')
        self.assertEqual(tc.clean_notes(html, is_html=True), "Shown\n\nEnd")

    def test_nested_skip_of_same_tag(self):
        html = '<div hidden><div>x</div><div>y</div></div><div>z</div>'
        self.assertEqual(tc.clean_notes(html, is_html=True), "z")

    def test_unclosed_hidden_element_fails_closed(self):
        self.assertEqual(tc.clean_notes("<p>a</p><div hidden>secret <p>more", is_html=True), "a")

    def test_entities_decoded_once(self):
        self.assertEqual(tc.clean_notes("&amp;lt;b&amp;gt; &lt;i&gt;", is_html=True), "&lt;b&gt; <i>")

    def test_links_become_plain_text(self):
        out = tc.clean_notes('<a href="javascript:alert(1)">Click</a> <a href="https://x.example/">here</a>',
                             is_html=True)
        self.assertEqual(out, "Click here")

    def test_lists_and_breaks(self):
        self.assertEqual(tc.clean_notes("<ul><li>a</li><li>b</li></ul>x<br>y", is_html=True),
                         "• a\n• b\nx\ny")

    def test_void_tag_with_hidden_attribute_hides_nothing_else(self):
        self.assertEqual(tc.clean_notes('<img hidden src=x>after', is_html=True), "after")


class CleanText(unittest.TestCase):
    def test_bidi_and_zero_width_removed(self):
        s = "a\u202eb\u202dc\u2066d\u2069e\u200bf\u2060g\ufeffh\u200ei\u00adj"
        self.assertEqual(tc.clean_line(s, 100), "abcdefghij")

    def test_zwj_emoji_kept(self):
        zwj = "\U0001f9d1\u200d\U0001f373"
        self.assertEqual(tc.clean_line(f"Hi {zwj}", 100), f"Hi {zwj}")

    def test_control_chars_and_lone_surrogates_removed(self):
        self.assertEqual(tc.clean_line("a\x00b\x07c\x1b[31m\ud800d", 100), "abc[31md")

    def test_line_field_collapses_whitespace_and_newlines(self):
        self.assertEqual(tc.clean_line("  a\n\tb c  d  ", 100), "a b c d")

    def test_notes_crlf_and_separators(self):
        self.assertEqual(tc.clean_notes("one\r\ntwo three\n\n\n\nfour"), "one\ntwo\nthree\n\nfour")

    def test_length_caps(self):
        self.assertEqual(len(tc.clean_line("x" * 10_000, tc.TITLE_MAX)), tc.TITLE_MAX)
        self.assertTrue(tc.clean_line("x" * 300, 200).endswith("…"))
        self.assertEqual(len(tc.clean_notes("word " * 3000)), tc.NOTES_MAX)

    def test_stacked_combining_marks_limited(self):
        marks = "".join(chr(c) for c in range(0x301, 0x307))  # six combining accents
        zalgo = "q" + marks * 50 + "ap"
        self.assertEqual(tc.clean_line(zalgo, 200), "q" + marks[:4] + "ap")
        # Ordinary accents and scripts with vowel signs are untouched.
        devanagari = "".join(chr(c) for c in (0x928, 0x92E, 0x938, 0x94D, 0x924, 0x947))
        self.assertEqual(tc.clean_line("Zoe" + chr(0x308) + " " + devanagari, 100), "Zo" + chr(0xEB) + " " + devanagari)

    def test_huge_input_bounded(self):
        import time

        t0 = time.monotonic()
        tc.clean_notes("<p>" + "x́ " * 5_000_000, is_html=True)
        tc.clean_notes("y " * 5_000_000)
        tc.clean_line("z" * 5_000_000, tc.TITLE_MAX)
        self.assertLess(time.monotonic() - t0, 5)

    def test_non_string_input(self):
        self.assertEqual(tc.clean_line(None, 10), "")
        self.assertEqual(tc.clean_notes({"x": 1}), "")

    def test_teams_block_removed(self):
        sep = "_" * 40
        s = f"Agenda\n{sep}\nMicrosoft Teams meeting\nJoin on your computer\nMeeting ID: 1\n{sep}\nAfter"
        self.assertEqual(tc.clean_notes(s), "Agenda\nAfter")

    def test_trailing_teams_block_without_closing_separator(self):
        self.assertEqual(tc.clean_notes("Agenda\n" + "_" * 30 + "\nJoin the meeting now\nhttps://teams.microsoft.com/l/x"),
                         "Agenda")

    def test_separator_without_meeting_text_only_drops_line(self):
        self.assertEqual(tc.clean_notes("a\n" + "-" * 20 + "\nb"), "a\nb")

    def test_long_url_shortened_short_url_kept(self):
        long = "https://example.com/" + "p" * 80
        self.assertEqual(tc.clean_notes(f"see {long} and https://ex.com/x"), "see example.com/… and https://ex.com/x")


if __name__ == "__main__":
    unittest.main()
