"""
The X read driver (channels.search / channels.counts), on recorded fixtures only.

No live call is made: the Composio HTTP layer is faked with a recorded reply and
twitterapi.io is faked through its opener. Covers each driver's item shape (the one
listen.norm_item reads), the price hold, the logged fallback, the query limit and
`listen.py --dry-run`.
"""
import json
import os
import urllib.error
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import channels  # noqa: E402
import hermetic_channels  # noqa: E402
import config  # noqa: E402
import fake_composio_http  # noqa: E402
import fake_composio_key  # noqa: E402
import fixture_memory  # noqa: E402
import listen  # noqa: E402
import memory  # noqa: E402
from test_twitterapi import FakeOpener, tweet  # noqa: E402

# A recorded TWITTER_RECENT_SEARCH reply (the tool's JSON).
RECENT_SEARCH = {"successful": True, "error": None, "data": {
    "data": [{"id": "1001", "text": "a credential root, checked", "author_id": "7", "lang": "en",
              "created_at": "2026-11-09T09:00:00.000Z",
              "public_metrics": {"like_count": 4, "retweet_count": 2, "reply_count": 1, "impression_count": 90}}],
    "includes": {"users": [{"id": "7", "username": "someone", "name": "Some One",
                            "public_metrics": {"followers_count": 120}}]},
    "meta": {"result_count": 1}}}
# A recorded TWITTER_SEARCH_RECENT_COUNTS reply.
RECENT_COUNTS = {"successful": True, "error": None, "data": {
    "data": [{"start": "2026-11-08T00:00:00.000Z", "end": "2026-11-09T00:00:00.000Z", "tweet_count": 5},
             {"start": "2026-11-09T00:00:00.000Z", "end": "2026-11-10T00:00:00.000Z", "tweet_count": 7}],
    "meta": {"total_tweet_count": 12}}}


THEMES = {"themes": [{"tag": "#One", "x_search": '"one"', "keywords": ["one"]}],
          "mentions": {"x_search": "mentions", "keywords": ["acme"]}, "ignore": []}


def cli(obj=None, code=0, err=""):
    """A recorded reply for the fake HTTP layer; a failing call becomes the transport error."""
    return urllib.error.URLError(err) if code else obj


class ReadCase(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        hermetic_channels.install(self)
        fake_composio_key.install(self)
        self.stream = memory.DEFAULT_STREAM
        self.settings = {}
        real = config.cfg

        def fake(path, default=None, **kw):
            if path in self.settings:
                return self.settings[path]
            return real(path, default, **kw)
        p = mock.patch.object(config, "cfg", fake)
        p.start()
        self.addCleanup(p.stop)
        channels._composio_calls["n"] = 0
        self.runs = os.path.join(tempfile.mkdtemp(), "runs.json")

    def read_runs(self):
        with open(self.runs) as f:
            return json.load(f)

    def composio(self, signoff=True):
        self.settings["channels.x_read." + self.stream] = "composio"
        self.settings["listen.x_price_signoff"] = "2026-11-11" if signoff else ""


SCOPED_NOTE = "2026-11-11 owner: official X API accepted for own-post numbers and inbound only; listening and monitors stay on twitterapi.io"


class SplitClasses(ReadCase):
    """Two read classes, two drivers, two holds: listening/monitors (x_read) and our own accounts (x_own)."""

    def test_defaults_are_twitterapi_for_both(self):
        self.assertEqual(channels.x_own_driver(self.stream), ("twitterapi", None))
        self.assertEqual(channels.effective_x_own(self.stream), ("twitterapi", None))
        self.assertFalse(channels.own_price_signoff())

    def test_unknown_own_driver_is_named(self):
        self.settings["channels.x_own." + self.stream] = "scraper"
        driver, why = channels.x_own_driver(self.stream)
        self.assertEqual(driver, "scraper")
        self.assertIn("unknown driver", why)
        with self.assertRaises(channels.ChannelError):
            channels.effective_x_own(self.stream)

    def test_own_composio_without_its_signoff_is_held(self):
        self.settings["channels.x_own." + self.stream] = "composio"
        self.assertEqual(channels.effective_x_own(self.stream), ("twitterapi", channels.HELD_OWN_REASON))

    def test_the_listening_signoff_does_not_release_own_reads(self):
        self.settings["channels.x_own." + self.stream] = "composio"
        self.settings["listen.x_price_signoff"] = "2026-11-11"
        self.assertEqual(channels.effective_x_own(self.stream), ("twitterapi", channels.HELD_OWN_REASON))

    def test_own_signoff_releases_own_reads(self):
        self.settings["channels.x_own." + self.stream] = "composio"
        self.settings["listen.x_own_price_signoff"] = SCOPED_NOTE
        self.assertTrue(channels.own_price_signoff())
        self.assertEqual(channels.effective_x_own(self.stream), ("composio", None))

    def test_the_scoped_signoff_is_not_accepted_for_listening(self):
        self.settings["channels.x_read." + self.stream] = "composio"
        self.settings["channels.x_own." + self.stream] = "composio"
        self.settings["listen.x_own_price_signoff"] = SCOPED_NOTE
        self.assertFalse(channels.price_signoff())
        self.assertEqual(channels.effective_x_read(self.stream), ("twitterapi", channels.HELD_REASON))
        self.assertEqual(channels.effective_x_own(self.stream), ("composio", None))

    def test_listening_search_stays_on_twitterapi_while_own_search_uses_composio(self):
        self.settings["channels.x_own." + self.stream] = "composio"
        self.settings["listen.x_own_price_signoff"] = SCOPED_NOTE
        op = FakeOpener(pages=[{"tweets": [tweet(1)], "has_next_page": False}])
        fake = fake_composio_http.install(self, reply=cli(RECENT_SEARCH))
        got = channels.search("q", 1761000000, 12, stream=self.stream, key="k", opener=op, runs_path=self.runs)
        self.assertEqual(fake.executes, [], "listening is on twitterapi.io")
        self.assertEqual([t["id"] for t in got], ["1"])
        own = channels.search("q", 1761000000, 12, stream=self.stream, runs_path=self.runs, own=True)
        self.assertEqual([t["id"] for t in own], ["1001"])
        self.assertEqual(fake.executes[0][0], "TWITTER_RECENT_SEARCH")

    def test_a_composio_own_class_marks_the_stream_set_up(self):
        for k in ("channels.x_read." + self.stream, "channels.write_driver." + self.stream):
            self.settings[k] = "twitterapi" if "x_read" in k else "native"
        self.settings["channels.x_own." + self.stream] = "composio"
        self.settings["channels.composio_org." + self.stream] = ""
        with mock.patch.object(channels, "composio_key", side_effect=channels.MissingComposioKey("none")):
            self.assertTrue(channels.composio_setup(self.stream)[0])


class Held(ReadCase):
    def test_default_is_twitterapi(self):
        self.assertEqual(channels.effective_x_read(self.stream), ("twitterapi", None))
        self.assertFalse(channels.price_signoff())

    def test_composio_without_signoff_is_held(self):
        self.composio(signoff=False)
        self.assertEqual(channels.effective_x_read(self.stream), ("twitterapi", "held: price sign-off not recorded"))

    def test_held_search_never_calls_composio(self):
        self.composio(signoff=False)
        op = FakeOpener(pages=[{"tweets": [tweet(1)], "has_next_page": False}])
        fake = fake_composio_http.install(self)
        got = channels.search("q", 1761000000, 12, stream=self.stream, key="k", opener=op, runs_path=self.runs)
        self.assertEqual(fake.calls, [])
        self.assertEqual([t["id"] for t in got], ["1"])
        self.assertFalse(os.path.exists(self.runs), "a hold is not a fallback")

    def test_signoff_with_composio_is_effective(self):
        self.composio()
        self.assertEqual(channels.effective_x_read(self.stream), ("composio", None))

    def test_doctor_line_says_held(self):
        self.composio(signoff=False)
        lines = [l for l in channels.doctor_report() if l["check"] == f"composio {self.stream} x read driver"]
        if lines:  # the fixture stream carries a channels cell
            self.assertIn("held: price sign-off not recorded", lines[0]["tail"])


class ComposioDriver(ReadCase):
    def test_search_shape_and_call(self):
        self.composio()
        fake = fake_composio_http.install(self, reply=cli(RECENT_SEARCH))
        got = channels.search('"credential root"', 1762000000, 12, stream=self.stream, runs_path=self.runs)
        slug, body = fake.executes[0]
        self.assertEqual(slug, "TWITTER_RECENT_SEARCH")
        self.assertEqual(body["connected_account_id"], f"ca_{self.stream}-x")
        args = body["arguments"]
        self.assertEqual(args["query"], '"credential root"')
        self.assertEqual(args["start_time"], "2025-11-01T12:26:40Z")
        self.assertTrue(args["start_time"].endswith("Z"))
        self.assertEqual(args["sort_order"], "relevancy")
        n = listen.norm_item(got[0])
        self.assertEqual((n["id"], n["author"], n["likes"], n["retweets"], n["replies"], n["views"], n["followers"]),
                         ("1001", "someone", 4, 2, 1, 90, 120))
        self.assertEqual(n["url"], "https://x.com/someone/status/1001")
        self.assertEqual(n["created_at"], "2026-11-09T09:00:00.000Z")
        self.assertIsNotNone(listen.parse_when(n["created_at"]))

    def test_same_shape_as_twitterapi(self):
        self.composio()
        fake_composio_http.install(self, reply=cli(RECENT_SEARCH))
        official = listen.norm_item(channels.search("q", None, 12, stream=self.stream)[0])
        op = FakeOpener(pages=[{"tweets": [tweet(1001)], "has_next_page": False}])
        self.settings["listen.x_price_signoff"] = ""
        held = listen.norm_item(channels.search("q", None, 12, stream=self.stream, key="k", opener=op)[0])
        self.assertEqual(set(official), set(held))

    def test_dry_run_checks_the_account_executes_nothing_and_returns_nothing(self):
        self.composio()
        fake = fake_composio_http.install(self)
        self.assertEqual(channels.search("q", None, 12, stream=self.stream, dry_run=True), [])
        self.assertEqual(fake.executes, [])
        self.assertTrue(any(c["path"] == "/api/v3.1/connected_accounts" for c in fake.calls))

    def test_counts_shape(self):
        self.composio()
        fake = fake_composio_http.install(self, reply=cli(RECENT_COUNTS))
        got = channels.counts("q", stream=self.stream)
        self.assertEqual(fake.executes[0][0], "TWITTER_SEARCH_RECENT_COUNTS")
        self.assertEqual(got, {"total": 12, "buckets": [{"start": "2026-11-08", "count": 5},
                                                         {"start": "2026-11-09", "count": 7}],
                               "driver": "composio", "approximate": False})


class Twitterapi(ReadCase):
    def test_counts_by_day(self):
        op = FakeOpener(pages=[{"tweets": [tweet(1), tweet(2)], "has_next_page": False}])
        got = channels.counts("q", stream=self.stream, key="k", opener=op)
        self.assertEqual(got["driver"], "twitterapi")
        self.assertTrue(got["approximate"])
        self.assertEqual(got["total"], 2)
        self.assertEqual(got["buckets"], [{"start": "2026-10-26", "count": 2}])
        self.assertEqual(set(got), {"total", "buckets", "driver", "approximate"})


class Fallback(ReadCase):
    def check(self, side_effect, needle):
        self.composio()
        op = FakeOpener(pages=[{"tweets": [tweet(5)], "has_next_page": False}])
        fake_composio_http.install(self, reply=side_effect)
        got = channels.search("q", None, 12, stream=self.stream, key="k", opener=op, runs_path=self.runs)
        self.assertEqual([t["id"] for t in got], ["5"], "twitterapi answered")
        rows = self.read_runs()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["step"], "listen-fallback")
        self.assertEqual(rows[0]["fallback_from"], "composio")
        self.assertIn(needle, rows[0]["detail"])
        return rows[0]

    def test_api_error_falls_back_and_is_logged(self):
        self.check(cli(None, code=1, err="no connected account for alias"), "no connected account")

    def test_unsuccessful_result_falls_back(self):
        self.check({"successful": False, "error": "rate limited"}, "rate limited")

    def test_unreachable_api_falls_back(self):
        self.check(OSError("no network"), "did not run")

    def test_exhausted_cap_falls_back(self):
        self.settings["listen.composio_call_cap"] = 1
        self.composio()
        ops = [FakeOpener(pages=[{"tweets": [tweet(n)], "has_next_page": False}]) for n in (8, 9)]
        run = fake_composio_http.install(self, reply=cli(RECENT_SEARCH))
        first = channels.search("q", None, 12, stream=self.stream, key="k", opener=ops[0], runs_path=self.runs)
        second = channels.search("q", None, 12, stream=self.stream, key="k", opener=ops[1], runs_path=self.runs)
        self.assertEqual(len(run.executes), 1)
        self.assertEqual(first[0]["id"], "1001")
        self.assertEqual(second[0]["id"], "9")
        self.assertIn("cap", self.read_runs()[0]["detail"])

    def test_fallback_is_on_the_run_log_for_the_stream(self):
        row = self.check(cli(None, code=1, err="boom"), "boom")
        self.assertEqual(row["stream"], memory.stream(self.stream)["name"])


class QueryLimit(ReadCase):
    def handles(self, n=40):
        path = os.path.join(tempfile.mkdtemp(), "watchlist.json")
        with open(path, "w") as f:
            json.dump({"watched": [{"handle": f"@account_{i:02d}"} for i in range(n)]}, f)
        return path

    def test_defaults_per_driver(self):
        self.assertEqual(channels.query_limit("twitterapi"), 255)
        self.assertEqual(channels.query_limit("composio"), 512)

    def test_watched_packing_reads_the_effective_driver_limit(self):
        path = self.handles()
        held = listen.watched_passes(path)
        self.assertTrue(all(len(p["query"]) <= 255 for p in held))
        self.composio()
        wide = listen.watched_passes(path)
        self.assertTrue(all(len(p["query"]) <= 512 for p in wide))
        self.assertTrue(any(len(p["query"]) > 255 for p in wide))
        self.assertLess(len(wide), len(held))

    def test_limit_comes_from_config(self):
        self.settings["listen.query_limit.twitterapi"] = 120
        self.assertTrue(all(len(p["query"]) <= 120 for p in listen.watched_passes(self.handles())))

    def test_max_per_term_is_bounded(self):
        op = FakeOpener(pages=[{"tweets": [tweet(n) for n in range(20)], "has_next_page": False}])
        self.assertLessEqual(len(listen.run_x("k", "q", 50, 1761000000, opener=op)), 12)


class ListenDryRun(ReadCase):
    def run_main(self, *argv):
        out = []
        with mock.patch.object(sys, "argv", ["listen.py", "--dry-run", "--stream", self.stream, *argv]), \
                mock.patch("builtins.print", lambda *a, **k: out.append(" ".join(str(x) for x in a))), \
                mock.patch.object(listen, "load_themes", return_value=THEMES), \
                mock.patch.object(listen.twitterapi, "load_key", side_effect=AssertionError("no key in a dry run")):
            listen.main()
        return "\n".join(out)

    def test_dry_run_says_held(self):
        self.composio(signoff=False)
        text = self.run_main()
        self.assertIn("held: price sign-off not recorded", text)
        self.assertIn("x read driver twitterapi", text)

    def test_dry_run_with_signoff_checks_the_account_and_executes_nothing(self):
        self.composio()
        fake = fake_composio_http.install(self)
        text = self.run_main()
        self.assertIn("x read driver composio", text)
        self.assertEqual(fake.executes, [])
        self.assertTrue(fake.calls)


if __name__ == "__main__":
    unittest.main()
