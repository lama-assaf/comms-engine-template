"""
Read parity: the Composio read drivers hand listen.py, x_metrics.py and the inbound path the
same item shape twitterapi.io does, on recorded fixtures only.

Each test records one logical set of posts twice, once as twitterapi.io returns it and once as the
official API returns it through Composio (the HTTP layer is faked with the recorded
reply, twitterapi.io with a fake opener or `twitterapi.search`), runs the consumer unchanged, and
compares what the consumer ends up with. No live call is made. The twitterapi.io path's own tests
(test_twitterapi, test_x_read) stay as they are and are run with this one.
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
import fake_composio_http  # noqa: E402
import listen  # noqa: E402
import memory  # noqa: E402
import score  # noqa: E402
import test_inbound  # noqa: E402
import test_x_read  # noqa: E402
import x_metrics  # noqa: E402
from test_twitterapi import FakeOpener  # noqa: E402

NOW = dt.datetime(2026, 11, 10, 12, 0, tzinfo=dt.timezone.utc)

#: the same two posts, as the official API (through Composio) records them ...
OFFICIAL = {"successful": True, "error": None, "data": {
    "data": [
        {"id": "7001", "text": "What does a valid signature tell you? Who was allowed to sign it.", "author_id": "11",
         "lang": "en", "created_at": "2026-11-09T09:30:00.000Z", "conversation_id": "5001",
         "public_metrics": {"like_count": 6, "retweet_count": 2, "reply_count": 3, "impression_count": 410}},
        {"id": "7002", "text": "A plain remark, no question.", "author_id": "12", "lang": "en",
         "created_at": "2026-11-08T18:00:00.000Z", "conversation_id": "7002",
         "public_metrics": {"like_count": 0, "retweet_count": 0, "reply_count": 0, "impression_count": 12}}],
    "includes": {"users": [{"id": "11", "username": "reader_one", "name": "Reader One", "public_metrics": {"followers_count": 340}},
                           {"id": "12", "username": "reader_two", "name": "Reader Two", "public_metrics": {"followers_count": 15}}]},
    "meta": {"result_count": 2}}}
#: ... and as twitterapi.io records them
TWITTERAPI = [
    {"type": "tweet", "id": "7001", "url": "https://x.com/reader_one/status/7001",
     "text": "What does a valid signature tell you? Who was allowed to sign it.",
     "createdAt": "Mon Nov 09 09:30:00 +0000 2026", "lang": "en", "conversationId": "5001",
     "author": {"userName": "reader_one", "name": "Reader One", "followers": 340},
     "likeCount": 6, "retweetCount": 2, "replyCount": 3, "viewCount": 410},
    {"type": "tweet", "id": "7002", "url": "https://x.com/reader_two/status/7002", "text": "A plain remark, no question.",
     "createdAt": "Sun Nov 08 18:00:00 +0000 2026", "lang": "en", "conversationId": "7002",
     "author": {"userName": "reader_two", "name": "Reader Two", "followers": 15},
     "likeCount": 0, "retweetCount": 0, "replyCount": 0, "viewCount": 12}]
OFFICIAL_COUNTS = {"successful": True, "error": None, "data": {
    "data": [{"start": "2026-11-08T00:00:00.000Z", "end": "2026-11-09T00:00:00.000Z", "tweet_count": 1},
             {"start": "2026-11-09T00:00:00.000Z", "end": "2026-11-10T00:00:00.000Z", "tweet_count": 1}],
    "meta": {"total_tweet_count": 2}}}


def cli(obj):
    return obj


class SearchParity(test_x_read.ReadCase):
    def official(self, **kw):
        self.composio()
        fake_composio_http.install(self, reply=cli(OFFICIAL))
        return channels.search("q", 1762000000, 12, stream=self.stream, **kw)

    def twitterapi(self, **kw):
        self.settings["listen.x_price_signoff"] = ""  # held: twitterapi.io reads
        op = FakeOpener(pages=[{"tweets": TWITTERAPI, "has_next_page": False}])
        return channels.search("q", 1762000000, 12, stream=self.stream, key="k", opener=op, **kw)

    def test_the_raw_items_carry_the_same_keys(self):
        official, tw = self.official(), self.twitterapi()
        self.assertEqual(len(official), len(tw))
        for a, b in zip(official, tw):
            self.assertEqual(set(a) - {"quoteCount", "bookmarkCount"}, set(b) - {"quoteCount", "bookmarkCount"})
            self.assertEqual(set(a["author"]), set(b["author"]))

    def test_norm_item_reads_both_to_the_same_item(self):
        official = [listen.norm_item(t) for t in self.official()]
        tw = [listen.norm_item(t) for t in self.twitterapi()]
        self.assertEqual(set(official[0]), set(tw[0]))
        for a, b in zip(official, tw):
            a_when, b_when = listen.parse_when(a.pop("created_at")), listen.parse_when(b.pop("created_at"))
            self.assertIsNotNone(a_when)
            self.assertEqual(a_when, b_when, "both timestamp spellings place the post at the same moment")
            self.assertEqual(a, b)

    def test_listen_run_x_and_prescore_are_blind_to_the_driver(self):
        theme = {"keywords": ["signature", "sign"]}
        self.composio()
        fake_composio_http.install(self, reply=cli(OFFICIAL))
        official = [listen.prescore(listen.norm_item(t), theme)
                    for t in listen.run_x("k", "q", 12, 1762000000, stream=self.stream)]
        self.settings["listen.x_price_signoff"] = ""
        op = FakeOpener(pages=[{"tweets": TWITTERAPI, "has_next_page": False}])
        tw = [listen.prescore(listen.norm_item(t), theme)
              for t in listen.run_x("k", "q", 12, 1762000000, opener=op, stream=self.stream)]
        self.assertEqual(len(official), 2)
        for a, b in zip(official, tw):
            self.assertEqual({k: v for k, v in a.items() if k != "created_at"},
                             {k: v for k, v in b.items() if k != "created_at"})

    def test_counts_carry_the_same_keys_and_numbers(self):
        self.composio()
        fake_composio_http.install(self, reply=cli(OFFICIAL_COUNTS))
        official = channels.counts("q", stream=self.stream)
        self.settings["listen.x_price_signoff"] = ""
        op = FakeOpener(pages=[{"tweets": TWITTERAPI, "has_next_page": False}])
        tw = channels.counts("q", stream=self.stream, key="k", opener=op)
        self.assertEqual(set(official), set(tw))
        self.assertEqual((official["total"], official["buckets"]), (tw["total"], tw["buckets"]))
        self.assertEqual((official["driver"], official["approximate"]), ("composio", False))
        self.assertEqual((tw["driver"], tw["approximate"]), ("twitterapi", True))


class MetricsParity(test_x_read.ReadCase):
    """x_metrics.py writes the same read, and score.py reads it the same, whichever source supplied it."""

    ANALYTICS = {"successful": True, "data": {"data": [
        {"id": "7001", "public_metrics": {"impression_count": 410, "like_count": 6, "retweet_count": 2, "quote_count": 1,
                                          "reply_count": 3, "bookmark_count": 4}}]}}
    LOOKUP = {"7001": {"id": "7001", "viewCount": 410, "likeCount": 6, "retweetCount": 2, "quoteCount": 1,
                       "replyCount": 3, "bookmarkCount": 4}}

    def written(self, driver):
        state = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, state, ignore_errors=True)
        pub = NOW - dt.timedelta(days=6)
        item = {"id": "P1", "published_at": pub.isoformat(), "urls": ["https://x.com/a/status/7001"]}
        if driver == "composio":
            with mock.patch.object(channels, "_execute", return_value=self.ANALYTICS):
                x_metrics.run(self.stream, state, now=NOW, items=[item], driver="composio")
        else:
            with mock.patch.object(x_metrics.twitterapi, "lookup", return_value=self.LOOKUP):
                x_metrics.run(self.stream, state, now=NOW, items=[item], key="k", driver="twitterapi")
        with open(os.path.join(state, "metrics-input", "P1.json"), encoding="utf-8") as f:
            return state, json.load(f), pub

    def test_both_write_the_same_envelope_and_numbers(self):
        (_, official, _), (_, tw, _) = self.written("composio"), self.written("twitterapi")
        a, b = official["reads"][0], tw["reads"][0]
        self.assertEqual(set(a), set(b))
        self.assertEqual({k: v for k, v in a.items() if k != "source"}, {k: v for k, v in b.items() if k != "source"})
        self.assertEqual((a["source"], b["source"]), ("composio", "twitterapi.io"))
        self.assertEqual(set(official), set(tw))

    def test_score_reads_both_to_the_same_window_numbers(self):
        windows = {}
        for driver in ("composio", "twitterapi"):
            state, _, pub = self.written(driver)
            it = {"id": "P1", "stream": memory.stream(self.stream)["name"], "theme": "#T", "title": "t", "format": "",
                  "slot": {"platform": "X"}, "published_at": pub.isoformat(), "cta": "https://x.com/a/status/7001"}
            records, _ = score.score_all(self.stream, state, now=NOW + dt.timedelta(days=2), items=[it],
                                         publish_log={"entries": []}, ledger={"sends": {}}, queue=[])
            windows[driver] = records[0]["at_7d"]
        official, tw = windows["composio"], windows["twitterapi"]
        self.assertEqual(set(official), set(tw))
        numbers = lambda w: {k: v for k, v in w.items() if k not in ("source", "partial", "impressions_measure")}  # noqa: E731
        self.assertEqual(numbers(official), numbers(tw))
        self.assertEqual(official["source"], ["official analytics"])


class InboundParity(test_inbound.InboundCase):
    """channels.inbound turns the posts a driver returns into the same patterns whichever driver read them."""

    def patterns(self, search):
        out = channels.inbound(self.stream, "x", state=tempfile.mkdtemp(), now=NOW, search=search)
        self.assertEqual(out["state"], "on")
        return out["patterns"], out["cursor"]["since_id"]

    def test_composio_and_twitterapi_items_give_the_same_patterns(self):
        self.go_x()
        official = json.loads(json.dumps(OFFICIAL))
        official["data"]["data"].append({"id": "7003", "text": "mine", "author_id": "13", "conversation_id": "5001",
                                         "created_at": "2026-11-09T10:00:00.000Z"})
        official["data"]["includes"]["users"].append({"id": "13", "username": self.own, "name": "Us"})
        tw = [dict(t) for t in TWITTERAPI] + [{"type": "tweet", "id": "7003", "text": "mine", "conversationId": "5001",
                                              "createdAt": "Mon Nov 09 10:00:00 +0000 2026",
                                              "author": {"userName": self.own, "name": "Us"}}]
        run = fake_composio_http.install(self, reply=cli(official))
        via_composio = self.patterns(None)  # channels.search through the faked HTTP layer
        self.assertTrue(run.executes)
        self.assertEqual(run.executes[0][0], "TWITTER_RECENT_SEARCH")
        via_twitterapi = self.patterns(lambda q, since, n, stream=None, query_type=None: [dict(t) for t in tw])
        self.assertEqual(via_composio, via_twitterapi)
        patterns, newest = via_composio
        self.assertEqual(newest, "7002", "our own post never moves the cursor")
        self.assertEqual(sum(p["count"] for p in patterns), 2, "our own post is not counted")
        self.assertNotIn("reader_one", json.dumps(patterns))


if __name__ == "__main__":
    unittest.main()
