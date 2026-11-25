"""
Guardrails from the registry and per-stream credentials (plan v2, item A13).

- an item of the unconfirmed stream cannot be published by any path: autopilot
  "nothing" and owner unset refuse before any channel rule is read
- a root-stream teaser over the daily cap is refused with the rule quoted; so
  is a weekend, an hour outside the window, a Blog inside three days of the last
- the registry row parses into caps, quiet hours and drafts-only channels
- `get_secret(name, stream=...)` resolves a stream-scoped name only, and the
  root stream keeps its bare names

The registry is the fixture one (`fixture_memory.py`), installed once for the
module.
"""
import datetime as dt
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import fixture_memory  # noqa: E402
import guardrails  # noqa: E402
import memory  # noqa: E402
import secrets as sec  # noqa: E402

ROOT, OTHER = fixture_memory.ROOT, fixture_memory.OTHER

# The fixture times are wall-clock times in a +01:00 zone, and the quiet hours
# are judged in the brand's timezone (engine.json autopilot.timezone, UTC in
# the template), so the tests pin guardrails.TZ to a matching fixed zone.
TZ_PIN = mock.patch.object(guardrails, "TZ", "Etc/GMT-1")
TUE_0900 = dt.datetime(2026, 10, 27, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=1)))
SAT_0900 = dt.datetime(2026, 10, 31, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=1)))
TUE_0700 = dt.datetime(2026, 10, 27, 7, 0, tzinfo=dt.timezone(dt.timedelta(hours=1)))
TUE_1900 = dt.datetime(2026, 10, 27, 19, 0, tzinfo=dt.timezone(dt.timedelta(hours=1)))


def setUpModule():
    TZ_PIN.start()
    fixture_memory.install()


def tearDownModule():
    fixture_memory.uninstall()
    TZ_PIN.stop()


class Registry(unittest.TestCase):
    def test_root_row_parses(self):
        g = guardrails.parse_guardrails(memory.stream(ROOT))
        self.assertEqual(g["caps"], {"X": 2, "LinkedIn": 1})
        self.assertEqual(g["week_caps"], {"Blog": 2})
        self.assertEqual(g["drafts_only"], set())
        self.assertTrue(g["quiet"]["weekends"])
        self.assertEqual(g["quiet"]["before"], (8, 0))
        self.assertEqual(g["quiet"]["after"], (18, 0))
        self.assertEqual(g["quiet"]["min_days_between_blogs"], 3)

    def test_other_streams_are_drafts_only_everywhere(self):
        g = guardrails.parse_guardrails(memory.stream(OTHER))
        self.assertEqual(g["drafts_only"], set(guardrails.CHANNELS))
        self.assertTrue(g["quiet"]["all"])


class Check(unittest.TestCase):
    def test_unconfirmed_stream_cannot_publish_by_any_path(self):
        for ch in guardrails.CHANNELS:
            ok, why = guardrails.check(OTHER, ch, TUE_0900)
            self.assertFalse(ok, ch)
            self.assertIn("autopilot is 'nothing'", why)

    def test_root_inside_the_window_passes(self):
        ok, why = guardrails.check(ROOT, "X", TUE_0900, published_today=1)
        self.assertTrue(ok, why)

    def test_daily_cap_refused_with_the_rule_quoted(self):
        ok, why = guardrails.check(ROOT, "X", TUE_0900, published_today=2)
        self.assertFalse(ok)
        self.assertIn("daily cap of 2", why)
        self.assertIn("X 2; LinkedIn 1", why)

    def test_quiet_hours(self):
        self.assertFalse(guardrails.check(ROOT, "X", SAT_0900)[0])
        self.assertIn("Saturday", guardrails.check(ROOT, "X", SAT_0900)[1])
        self.assertFalse(guardrails.check(ROOT, "X", TUE_0700)[0])
        self.assertFalse(guardrails.check(ROOT, "X", TUE_1900)[0])

    def test_blog_spacing_and_weekly_cap(self):
        self.assertFalse(guardrails.check(ROOT, "Blog", TUE_0900, last_blog_days_ago=1)[0])
        self.assertTrue(guardrails.check(ROOT, "Blog", TUE_0900, last_blog_days_ago=3)[0])
        ok, why = guardrails.check(ROOT, "Blog", TUE_0900, published_this_week=2, last_blog_days_ago=4)
        self.assertFalse(ok)
        self.assertIn("weekly cap of 2", why)

    def test_cli_exit_codes(self):
        self.assertEqual(guardrails.main(["--stream", OTHER, "--channel", "X", "--at", TUE_0900.isoformat()]), 1)


class PublishUsesTheSlot(unittest.TestCase):
    def test_slot_time_not_the_clock(self):
        import publish
        import repo
        import tempfile
        saved = repo.CAL
        repo.CAL = tempfile.mkdtemp(prefix="guard-cal-")  # an empty calendar: no caps or spacing in play
        self.addCleanup(lambda: setattr(repo, "CAL", saved))
        weekday = {"id": "Q-x", "stream": fixture_memory.ROOT_NAME, "slot": {"date": "2026-10-27"}}
        saturday = {"id": "Q-y", "stream": fixture_memory.ROOT_NAME, "slot": {"date": "2026-10-31"}}
        other = {"id": "Q-z", "stream": fixture_memory.OTHER_NAME, "slot": {"date": "2026-10-27"}}
        self.assertTrue(publish.registry_check(weekday)[0], publish.registry_check(weekday)[1])
        self.assertFalse(publish.registry_check(saturday)[0])
        self.assertIn("Saturday", publish.registry_check(saturday)[1])
        self.assertFalse(publish.registry_check(other)[0])


class Secrets(unittest.TestCase):
    def test_scoped_names(self):
        self.assertEqual(sec.scoped_name("APIFY_TOKEN", None), "APIFY_TOKEN")
        self.assertEqual(sec.scoped_name("APIFY_TOKEN", ROOT), "APIFY_TOKEN")
        self.assertEqual(sec.scoped_name("APIFY_TOKEN", OTHER), f"{OTHER}/APIFY_TOKEN")

    def test_stream_secret_resolves_only_its_own_name(self):
        scoped = f"{OTHER.upper()}_APIFY_TOKEN"
        os.environ["APIFY_TOKEN"] = "root-token"
        os.environ.pop(scoped, None)
        try:
            self.assertEqual(sec.get_secret("APIFY_TOKEN"), "root-token")
            self.assertIsNone(sec.get_secret("APIFY_TOKEN", required=False, stream=OTHER))
            os.environ[scoped] = "other-token"
            self.assertEqual(sec.get_secret("APIFY_TOKEN", stream=OTHER), "other-token")
            self.assertEqual(sec.get_secret("APIFY_TOKEN", stream=ROOT), "root-token")
        finally:
            os.environ.pop("APIFY_TOKEN", None)
            os.environ.pop(scoped, None)


if __name__ == "__main__":
    unittest.main()
