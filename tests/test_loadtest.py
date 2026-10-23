"""The load-test tool's guards (tools/loadtest.py). No network."""

import unittest
from unittest import mock

from tools import loadtest


class Guards(unittest.TestCase):
    def test_refuses_production(self):
        with self.assertRaisesRegex(SystemExit, "production"):
            loadtest.main(["wallcal-prod-abc.azurewebsites.net", "--anonymous"])

    def test_refuses_bad_paths_and_steps(self):
        for argv in (["--paths", "api/events"], ["--steps", "0"], ["--steps", "500"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                loadtest.main(["dev.example.net", "--anonymous", *argv])

    def test_cookie_checked_and_never_echoed(self):
        good = "A" * 40
        with mock.patch("getpass.getpass", return_value=f"{loadtest.COOKIE}={good}"):
            self.assertEqual(loadtest._read_cookie(), good)
        for bad in ("short", "has space " * 5, "<script>" * 5):
            with self.subTest(bad=bad), mock.patch("getpass.getpass", return_value=bad), \
                    self.assertRaises(SystemExit) as caught:
                loadtest._read_cookie()
            self.assertNotIn(bad, str(caught.exception))

    def test_headers(self):
        self.assertNotIn("Cookie", loadtest._headers(None))
        self.assertEqual(loadtest._headers("x" * 30)["Cookie"], f"{loadtest.COOKIE}={'x' * 30}")
        self.assertEqual(loadtest._headers(None)["Sec-Fetch-Site"], "same-origin")

    def test_percentiles(self):
        times = [i / 1000 for i in range(1, 101)]
        self.assertEqual(loadtest._pct(times, 0.5), 51)
        self.assertEqual(loadtest._pct(times, 0.95), 96)
        self.assertEqual(loadtest._pct([], 0.95), 0)


if __name__ == "__main__":
    unittest.main()
