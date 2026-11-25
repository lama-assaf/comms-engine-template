"""
channels.metrics: the official own-post numbers, mapped to the metrics-input shape x_metrics.py
writes from twitterapi.io, with the Composio CLI faked. Nothing here makes a live call.
"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import channels  # noqa: E402
import linkedin_api  # noqa: E402
import memory  # noqa: E402
import score  # noqa: E402
import x_metrics  # noqa: E402

try:
    import fixture_memory  # noqa: E402
    Base = fixture_memory.FixtureMemoryCase
except ImportError:
    Base = unittest.TestCase

NOW = dt.datetime(2026, 10, 27, 21, 0, tzinfo=dt.timezone.utc)
SHAPE = {"at", "platform", "source", "impressions", "likes", "reposts", "quotes", "replies", "saves", "posts"}
URN = "urn:li:share:7123"

X_ANALYTICS = {"successful": True, "data": {"data": [
    {"id": "11", "public_metrics": {"impression_count": 400, "like_count": 5, "retweet_count": 1,
                                    "quote_count": 0, "reply_count": 2, "bookmark_count": 1},
     "organic_metrics": {"impression_count": 400, "like_count": 5}},
    {"id": "12", "timestamped_metrics": [{"metrics": {"impression_count": 60, "like_count": 1}},
                                         {"metrics": {"impression_count": 40, "like_count": 1, "quote_count": 1}}]},
    {"id": "99", "public_metrics": {"impression_count": 9999}},
]}}
LI_STATS = {"successful": True, "data": {"elements": [
    {"totalShareStatistics": {"impressionCount": 300, "likeCount": 7, "shareCount": 2, "commentCount": 3, "clickCount": 50}}]}}


def item(iid, urls, days=3):
    return {"id": iid, "published_at": (NOW - dt.timedelta(days=days)).isoformat(), "urls": urls}


class MetricsTest(Base):
    def setUp(self):
        super().setUp()
        self.stream = memory.DEFAULT_STREAM
        self.state = tempfile.mkdtemp()
        channels._composio_calls["n"] = 0
        self.addCleanup(shutil.rmtree, self.state, ignore_errors=True)

    def test_x_analytics_maps_to_the_metrics_input_shape(self):
        with mock.patch.object(channels, "_execute", return_value=X_ANALYTICS) as ex:
            read = channels.metrics(self.stream, "x", ["11", "12"], now=NOW)
        self.assertEqual(ex.call_args[0][2], "TWITTER_GET_POST_ANALYTICS")
        self.assertEqual(set(read), SHAPE)
        self.assertEqual(read["source"], "composio")
        self.assertEqual((read["impressions"], read["likes"], read["reposts"], read["quotes"], read["replies"],
                          read["saves"], read["posts"]), (500, 7, 1, 1, 2, 1, 2))

    def test_linkedin_stats_map_to_the_same_shape(self):
        with mock.patch.object(channels, "_execute", return_value=LI_STATS) as ex, \
                mock.patch.object(linkedin_api, "settings", return_value={"LINKEDIN_ORG_ID": "5"}):
            read = channels.metrics(self.stream, "linkedin", URN, now=NOW)
        self.assertEqual(ex.call_args[0][2], "LINKEDIN_GET_SHARE_STATS")
        self.assertEqual(set(read), SHAPE)
        self.assertEqual((read["platform"], read["impressions"], read["likes"], read["reposts"], read["replies"]),
                         ("LinkedIn", 300, 7, 2, 3))

    def test_no_author_text_or_handle_is_kept(self):
        rows = json.loads(json.dumps(X_ANALYTICS))
        rows["data"]["data"][0].update({"text": "some words", "author_id": "7", "username": "someone"})
        with mock.patch.object(channels, "_execute", return_value=rows):
            read = channels.metrics(self.stream, "x", "11", now=NOW)
        self.assertNotIn("someone", json.dumps(read))
        self.assertNotIn("words", json.dumps(read))

    def test_both_sources_write_the_same_keys(self):
        it = [item("P1", ["https://x.com/a/status/11"])]
        with mock.patch.object(channels, "_execute", return_value=X_ANALYTICS):
            x_metrics.run(self.stream, self.state, now=NOW, items=it, driver="composio")
        tw = x_metrics.read_from([{"viewCount": 1}], NOW)
        with open(os.path.join(self.state, "metrics-input", "P1.json"), encoding="utf-8") as f:
            official = json.load(f)["reads"][0]
        self.assertEqual(set(official), set(tw))
        self.assertEqual((official["source"], tw["source"]), ("composio", "twitterapi.io"))

    def test_held_sign_off_keeps_twitterapi(self):
        it = [item("P1", ["https://x.com/a/status/11"])]
        with mock.patch.object(channels, "_execute") as ex, \
                mock.patch.object(channels, "effective_x_own", return_value=("twitterapi", "held")), \
                mock.patch.object(x_metrics.twitterapi, "lookup", return_value={"11": {"viewCount": 5, "likeCount": 2}}) as lk:
            out = x_metrics.run(self.stream, self.state, now=NOW, items=it, key="k")
        ex.assert_not_called()
        lk.assert_called_once()
        self.assertEqual(out["driver"], "twitterapi")

    def test_composio_failure_falls_back_and_is_logged(self):
        it = [item("P1", ["https://x.com/a/status/11"])]
        with mock.patch.object(channels, "_execute", side_effect=channels.ChannelError("boom")), \
                mock.patch.object(channels, "_log_fallback") as log, \
                mock.patch.object(x_metrics.twitterapi, "lookup", return_value={"11": {"viewCount": 5}}):
            out = x_metrics.run(self.stream, self.state, now=NOW, items=it, key="k", driver="composio")
        log.assert_called_once()
        self.assertEqual(out["written"], ["P1"])
        with open(os.path.join(self.state, "metrics-input", "P1.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["reads"][0]["source"], "twitterapi.io")

    def test_dry_run_calls_nothing(self):
        it = [item("P1", ["https://x.com/a/status/11", "https://www.linkedin.com/feed/update/" + URN])]
        with mock.patch.object(channels, "_execute") as ex, mock.patch.object(channels, "_http") as cli, \
                mock.patch.object(x_metrics.twitterapi, "lookup") as lk:
            out = x_metrics.run(self.stream, self.state, now=NOW, items=it, driver="composio", dry_run=True)
        for m in (ex, cli, lk):
            m.assert_not_called()
        self.assertEqual(len(out["due"]), 1)
        self.assertFalse(os.path.exists(os.path.join(self.state, "metrics-input")))

    def test_linkedin_unlinked_is_skipped_and_x_unchanged(self):
        it = [item("P1", ["https://www.linkedin.com/feed/update/" + URN])]
        with mock.patch.object(channels, "_execute") as ex:
            out = x_metrics.run(self.stream, self.state, now=NOW, items=it, driver="twitterapi", linked=False)
        ex.assert_not_called()
        self.assertEqual(out["linkedin_written"], [])
        self.assertTrue(out["linkedin_skipped"])
        self.assertFalse(os.path.exists(os.path.join(self.state, "metrics-input")))

    def test_linkedin_linked_writes_a_read(self):
        it = [item("P1", ["https://www.linkedin.com/feed/update/" + URN])]
        with mock.patch.object(channels, "_execute", return_value=LI_STATS), \
                mock.patch.object(linkedin_api, "settings", return_value={"LINKEDIN_ORG_ID": "5"}):
            out = x_metrics.run(self.stream, self.state, now=NOW, items=it, driver="twitterapi", linked=True)
        self.assertEqual(out["linkedin_written"], ["P1"])

    def test_score_labels_official_analytics_apart(self):
        pub = dt.datetime(2026, 10, 1, 8, tzinfo=dt.timezone.utc)
        x_metrics.append_read(self.state, "Q-1", {"at": (pub + dt.timedelta(days=6)).isoformat(), "platform": "X",
                                                  "source": "composio", "likes": 9, "impressions": 900})
        it = {"id": "Q-1", "stream": memory.stream(self.stream)["name"], "theme": "#T", "title": "t", "format": "",
              "slot": {"platform": "X"}, "published_at": pub.isoformat(), "cta": "https://x.com/a/status/5"}
        records, _ = score.score_all(self.stream, self.state, now=pub + dt.timedelta(days=8), items=[it],
                                     publish_log={"entries": []}, ledger={"sends": {}}, queue=[])
        w = records[0]["at_7d"]
        self.assertEqual(w["source"], ["official analytics"])
        self.assertFalse(w["partial"])

    def test_mixed_sources_are_flagged(self):
        pub = dt.datetime(2026, 10, 1, 8, tzinfo=dt.timezone.utc)
        at = (pub + dt.timedelta(days=6)).isoformat()
        x_metrics.append_read(self.state, "Q-2", {"at": at, "platform": "X", "source": "composio", "likes": 1})
        x_metrics.append_read(self.state, "Q-2", {"at": at, "platform": "LinkedIn", "source": "twitterapi.io", "likes": 1})
        it = {"id": "Q-2", "stream": memory.stream(self.stream)["name"], "theme": "#T", "title": "t", "format": "",
              "slot": {"platform": "X"}, "published_at": pub.isoformat(), "cta": "https://x.com/a/status/5"}
        records, _ = score.score_all(self.stream, self.state, now=pub + dt.timedelta(days=8), items=[it],
                                     publish_log={"entries": []}, ledger={"sends": {}}, queue=[])
        self.assertIn("impressions_measure", records[0]["at_7d"])


if __name__ == "__main__":
    unittest.main()
