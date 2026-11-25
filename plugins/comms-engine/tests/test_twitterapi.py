"""
X through twitterapi.io (owner decision 2026-10-26).

- search pages through `next_cursor`, stops at `max_items` or the last page,
  sends the key in `X-API-Key` and adds `since_time:` to the query
- lookup batches ids by 50 and matches results by id, dropping strays
- an error status raises, never reads as an empty result
- the listening pass's X path calls twitterapi.io, and its tweets normalise
  through `norm_item` unchanged
- x_metrics writes one summed read per item, counts only, marked
  `source: twitterapi.io`, and score.py labels it "public counts", partial
No network: every call goes through a fake opener.
"""
import datetime as dt
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import fixture_memory  # noqa: E402
import listen  # noqa: E402
import score  # noqa: E402
import twitterapi  # noqa: E402
import x_metrics  # noqa: E402


def tweet(i, **counts):
    return {"type": "tweet", "id": str(i), "url": f"https://x.com/someone/status/{i}", "text": f"text {i} credential root",
            "createdAt": "Mon Oct 26 09:00:00 +0000 2026", "lang": "en",
            "author": {"userName": "someone", "name": "Some One", "followers": 100},
            "likeCount": counts.get("likes", 1), "retweetCount": counts.get("reposts", 0), "replyCount": counts.get("replies", 0),
            "quoteCount": counts.get("quotes", 0), "viewCount": counts.get("views", 10), "bookmarkCount": counts.get("saves", 0)}


class FakeOpener:
    """Answers twitterapi.io paths from a script and records each request."""

    def __init__(self, pages=None, lookup=None, error=None):
        self.pages, self.lookup_db, self.error, self.calls = list(pages or []), lookup or {}, error, []

    def __call__(self, req, timeout=None):
        url = urllib.parse.urlparse(req.full_url)
        q = dict(urllib.parse.parse_qsl(url.query, keep_blank_values=True))
        self.calls.append((url.path, q, req.get_header("X-api-key")))
        if self.error:
            body = {"status": "error", "msg": self.error}
        elif url.path.endswith("advanced_search"):
            body = self.pages.pop(0)
        else:
            ids = q["tweet_ids"].split(",")
            body = {"status": "success", "msg": "", "code": 0,
                    "tweets": [self.lookup_db[i] for i in ids if i in self.lookup_db] + [{"id": ""}]}
        return io.BytesIO(json.dumps(body).encode())


class Client(unittest.TestCase):
    def test_search_pages_and_stops_at_max(self):
        op = FakeOpener(pages=[
            {"tweets": [tweet(i) for i in range(20)], "has_next_page": True, "next_cursor": "c1"},
            {"tweets": [tweet(i) for i in range(20, 40)], "has_next_page": True, "next_cursor": "c2"},
        ])
        got = twitterapi.search("k", '"credential root" lang:en', 25, since_ts=1761000000, opener=op)
        self.assertEqual(len(got), 25)
        self.assertEqual(len(op.calls), 2)
        path, q, key = op.calls[0]
        self.assertEqual(path, "/twitter/tweet/advanced_search")
        self.assertEqual(key, "k")
        self.assertEqual(q["query"], '"credential root" lang:en since_time:1761000000')
        self.assertEqual((q["queryType"], q["cursor"]), ("Latest", ""))
        self.assertEqual(op.calls[1][1]["cursor"], "c1")

    def test_search_stops_on_the_last_page(self):
        op = FakeOpener(pages=[{"tweets": [tweet(1), tweet(2)], "has_next_page": False, "next_cursor": ""}])
        self.assertEqual(len(twitterapi.search("k", "q", 12, opener=op)), 2)
        self.assertEqual(len(op.calls), 1)

    def test_lookup_batches_and_matches_by_id(self):
        db = {str(i): tweet(i) for i in range(60)}
        op = FakeOpener(lookup=db)
        got = twitterapi.lookup("k", [str(i) for i in range(60)] + ["999", "3"], opener=op)
        self.assertEqual(len(op.calls), 2)
        self.assertEqual(len(op.calls[0][1]["tweet_ids"].split(",")), 50)
        self.assertEqual(set(got), {str(i) for i in range(60)})

    def test_error_status_raises(self):
        with self.assertRaises(twitterapi.TwitterAPIError):
            twitterapi.search("k", "q", 5, opener=FakeOpener(error="bad key"))


class Profiles(unittest.TestCase):
    """user/info answers HTTP 200 either way; `status` says which."""

    def opener(self, body):
        calls = []

        def op(req, timeout=None):
            calls.append(urllib.parse.urlparse(req.full_url))
            return io.BytesIO(json.dumps(body).encode())
        op.calls = calls
        return op

    def test_found_not_found_and_suspended(self):
        op = self.opener({"status": "success", "msg": "", "data": {"userName": "examplestandards", "followers": 9}})
        self.assertEqual(twitterapi.user_info("k", "@examplestandards", opener=op), ("found", {"userName": "examplestandards", "followers": 9}))
        self.assertEqual(dict(urllib.parse.parse_qsl(op.calls[0].query)), {"userName": "examplestandards"})
        self.assertEqual(twitterapi.user_info("k", "nobody", opener=self.opener({"status": "error", "msg": "user not found"})),
                         ("not found", "user not found"))
        self.assertEqual(twitterapi.user_info("k", "gone", opener=self.opener(
            {"status": "success", "data": {"unavailable": True, "unavailableReason": "Suspended"}})), ("unavailable", "Suspended"))
        with self.assertRaises(twitterapi.TwitterAPIError):
            twitterapi.user_info("k", "x", opener=self.opener({"status": "error", "msg": "invalid api key"}))

    def test_inventory_reads_the_answer(self):
        import inventory
        self.assertEqual(inventory.check_x_handle("@examplestandards", call=lambda n: ("found", {"userName": "examplestandards"})), ("confirmed", "@examplestandards"))
        self.assertEqual(inventory.check_x_handle("@old", call=lambda n: ("found", {"userName": "new"}))[0], "inconclusive")
        self.assertEqual(inventory.check_x_handle("@gone", call=lambda n: ("unavailable", "Suspended")),
                         ("inconclusive", "twitterapi.io: account Suspended"))
        self.assertEqual(inventory.check_x_handle("@x", call=lambda n: ("not found", "user not found")),
                         ("inconclusive", "twitterapi.io: no such handle"))

        def boom(n):
            raise twitterapi.TwitterAPIError("HTTP 401")
        self.assertEqual(inventory.check_x_handle("@x", call=boom)[0], "error")


class ListeningPath(unittest.TestCase):
    def test_x_path_uses_twitterapi_and_normalises(self):
        op = FakeOpener(pages=[{"tweets": [tweet(7, likes=4, reposts=2, replies=1, views=300)], "has_next_page": False}])
        items = listen.run_x("k", '"credential root"', 12, 1761000000, opener=op)
        n = listen.norm_item(items[0])
        self.assertEqual((n["id"], n["likes"], n["retweets"], n["replies"], n["views"], n["author"]),
                         ("7", 4, 2, 1, 300, "someone"))
        self.assertEqual(n["source"], "x")
        self.assertEqual(listen.X_SOURCE, "twitterapi.io advanced_search")
        # Most-engaged first: newest first at 12 a term covers hours, not the week.
        self.assertEqual(op.calls[0][1]["queryType"], "Top")


class OneStreamOnly(fixture_memory.FixtureMemoryCase):
    """A stream's listening drops posts naming another stream (themes.json `ignore`, 2026-10-26).

    The terms come from the fixture `themes.json`, whose `ignore` names the
    second fixture stream; the checkout's own search file is not read.
    """

    def setUp(self):
        super().setUp()
        patch = mock.patch.object(listen, "terms_file", lambda stream=None: fixture_memory.THEMES_JSON)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_post_naming_another_stream_is_ignored(self):
        cfg = listen.load_themes()
        self.assertIn("betalabs", cfg["ignore"])
        for text in ("The Acme validator has been down. Something happened between Beta Labs and Acme.",
                     "@betalabs shipped a release", "gm betalabs fam"):
            self.assertTrue(listen.ignored(text, cfg["ignore"]), text)
        for text in ("Acme is a trust infrastructure", "A central bank on stablecoins", ""):
            self.assertFalse(listen.ignored(text, cfg["ignore"]), text)

    def test_the_mentions_term_is_the_fixture_one(self):
        q = listen.load_themes()["mentions"]["x_search"]
        self.assertIn('"Acme"', q)


class PublicCounts(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        self.state = tempfile.mkdtemp(prefix="x-metrics-")

    def tearDown(self):
        shutil.rmtree(self.state, ignore_errors=True)

    def test_one_summed_read_per_item_counts_only(self):
        now = dt.datetime(2026, 10, 27, 21, 0, tzinfo=dt.timezone.utc)
        items = [
            {"id": "P1", "published_at": "2026-10-23T08:00:00+00:00",
             "urls": ["https://x.com/acme_hq/status/11", "https://x.com/i/web/status/12", "https://www.example.com/insights/p1"]},
            {"id": "P2", "published_at": "2026-09-01T08:00:00+00:00", "urls": ["https://x.com/acme_hq/status/21"]},
            {"id": "P3", "published_at": "2026-10-26T08:00:00+00:00", "urls": ["https://www.linkedin.com/feed/update/x"]},
            {"id": "P4", "published_at": "2026-10-25T08:00:00+00:00", "urls": ["https://x.com/acme_hq/status/41"]},
        ]
        op = FakeOpener(lookup={"11": tweet(11, likes=5, views=400, saves=1), "12": tweet(12, likes=2, views=100, quotes=1)})
        out = x_metrics.run("acme", self.state, now=now, items=items, key="k", opener=op)
        self.assertEqual([d[0] for d in out["due"]], ["P1", "P4"])
        self.assertEqual(out["written"], ["P1"])
        self.assertEqual(out["missing"], ["P4"])
        with open(os.path.join(self.state, "metrics-input", "P1.json"), encoding="utf-8") as f:
            read = json.load(f)["reads"][0]
        self.assertEqual((read["likes"], read["impressions"], read["quotes"], read["saves"], read["posts"]), (7, 500, 1, 1, 2))
        self.assertEqual(read["source"], "twitterapi.io")
        self.assertNotIn("someone", json.dumps(read))

    def test_dry_run_calls_nothing(self):
        op = FakeOpener()
        items = [{"id": "P1", "published_at": "2026-10-26T08:00:00+00:00", "urls": ["https://x.com/a/status/1"]}]
        out = x_metrics.run("acme", self.state, now=dt.datetime(2026, 10, 27, tzinfo=dt.timezone.utc),
                            items=items, opener=op, dry_run=True)
        self.assertEqual(len(out["due"]), 1)
        self.assertEqual(op.calls, [])

    def test_score_labels_public_counts_partial(self):
        pub = dt.datetime(2026, 10, 1, 8, tzinfo=dt.timezone.utc)
        x_metrics.append_read(self.state, "Q-1", {"at": (pub + dt.timedelta(days=6)).isoformat(), "platform": "X",
                                                  "source": "twitterapi.io", "likes": 9, "impressions": 900})
        item = {"id": "Q-1", "stream": "Acme", "theme": "#ExampleTheme", "title": "t", "format": "", "slot": {"platform": "X"},
                "published_at": pub.isoformat(), "cta": "https://x.com/acme_hq/status/5"}
        records, _ = score.score_all("acme", self.state, now=pub + dt.timedelta(days=8), items=[item],
                                     publish_log={"entries": []}, ledger={"sends": {}}, queue=[])
        w = records[0]["at_7d"]
        self.assertEqual(w["likes"], 9)
        self.assertEqual(w["source"], ["public counts"])
        self.assertTrue(w["partial"])


if __name__ == "__main__":
    unittest.main()
