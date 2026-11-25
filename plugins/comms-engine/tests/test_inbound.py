"""
The inbound poll (channels.inbound, inbound.py, engage.merge_inbound), on fixtures only.

channels.search, the proxy GET and the Composio CLI are all faked; nothing is called.
Covers the gates (price hold, LinkedIn account), the planned queries, the persisted
cursor, patterns-only output (no handle, no third party's text), the dry run and the
doctor line.
"""
import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import channels  # noqa: E402
import hermetic_channels  # noqa: E402
import config  # noqa: E402
import engage  # noqa: E402
import fixture_memory  # noqa: E402
import memory  # noqa: E402

import inbound as inbound_cli  # noqa: E402

NOW = dt.datetime(2026, 11, 10, 12, 0, tzinfo=dt.timezone.utc)
SECRET_TEXT = "private words of a third party"


def sent_row(name, platform, at, url="", urn=None, kind="post"):
    return {"page_id": "p", "platform": platform, "title": "t", "hash": "h", "state": "sent", "at": at,
            "stream": name, "kind": kind, "url": url, "urn": urn}


class InboundCase(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        hermetic_channels.install(self)
        self.stream = memory.DEFAULT_STREAM
        self.own = "acme_hq"
        self.state = tempfile.mkdtemp()
        self.settings = {}
        real = config.cfg

        def fake(path, default=None, **kw):
            return self.settings[path] if path in self.settings else real(path, default, **kw)
        p = mock.patch.object(config, "cfg", fake)
        p.start()
        self.addCleanup(p.stop)
        channels._composio_calls["n"] = 0
        import x_stream
        with open(fixture_memory.THEMES_JSON) as fh:
            themes = json.load(fh)
        real_rules = x_stream.desired_rules
        q = mock.patch.object(x_stream, "desired_rules", lambda cfg=None: real_rules(cfg or themes))
        q.start()
        self.addCleanup(q.stop)
        name = memory.stream(self.stream)["name"]
        ledger = {"sends": {
            "a": sent_row(name, "X", "2026-11-10T09:00:00Z", url="https://x.com/i/web/status/5001"),
            "b": sent_row(name, "X", "2026-11-10T10:00:00Z", url="https://x.com/i/web/status/5002"),
            "old": sent_row(name, "X", "2026-10-01T10:00:00Z", url="https://x.com/i/web/status/4000"),
            "reply": sent_row(name, "X", "2026-11-10T10:30:00Z", url="https://x.com/i/web/status/5003", kind="reply"),
            "li": sent_row(name, "LinkedIn", "2026-11-10T09:00:00Z", urn="urn:li:share:77"),
        }}
        channels._save_ledger(self.state, ledger)

    def go_x(self):
        self.settings["listen.x_own_price_signoff"] = "2026-11-11"
        self.settings["channels.x_own." + self.stream] = "composio"


def x_item(tid, text, author, conv=""):
    return {"id": tid, "text": text, "author": {"userName": author}, "conversationId": conv}


class Gates(InboundCase):
    def test_x_is_held_without_the_signoff(self):
        self.settings["channels.x_own." + self.stream] = "composio"
        self.assertEqual(channels.inbound_status(self.stream, "x"), ("held", channels.HELD_OWN_REASON))
        search = mock.Mock()
        got = channels.inbound(self.stream, "x", state=self.state, now=NOW, search=search)
        self.assertEqual(got["state"], "held")
        search.assert_not_called()
        self.assertFalse(os.path.exists(os.path.join(self.state, "inbound.json")))

    def test_x_needs_the_composio_driver_even_with_the_signoff(self):
        self.settings["listen.x_own_price_signoff"] = "2026-11-11"
        self.assertEqual(channels.inbound_status(self.stream, "x")[0], "off")

    def test_linkedin_needs_a_linked_account(self):
        self.assertEqual(channels.inbound_status(self.stream, "linkedin", {})[0], "off")
        self.assertIn("no linkedin composio account", channels.inbound_status(self.stream, "linkedin", {})[1])
        with mock.patch.object(channels, "linkedin_linked", return_value=True):
            self.assertEqual(channels.inbound_status(self.stream, "linkedin")[0], "on")

    def test_a_stream_without_the_channel_is_off(self):
        self.assertEqual(channels.inbound_status("beta", "linkedin")[0], "off")


class XInbound(InboundCase):
    def test_dry_run_plans_the_queries_and_calls_nothing(self):
        self.go_x()
        search = mock.Mock()
        got = channels.inbound(self.stream, "x", dry_run=True, state=self.state, now=NOW, search=search)
        search.assert_not_called()
        kinds = [k for k, _ in got["plan"]["queries"]]
        self.assertEqual(kinds, ["mention", "reply"])
        mention, reply = (q for _, q in got["plan"]["queries"])
        self.assertIn("-from:acme_hq", mention)
        self.assertIn("conversation_id:5001", reply)
        self.assertIn("conversation_id:5002", reply)
        self.assertNotIn("4000", reply, "an old post is not watched")
        self.assertNotIn("5003", reply, "a reply of ours is not a post to watch")
        self.assertFalse(os.path.exists(os.path.join(self.state, "inbound.json")))

    def test_patterns_only_and_a_persisted_cursor(self):
        self.go_x()
        calls = []

        def search(query, since, n, stream=None, query_type=None):
            calls.append((query, since))
            if "conversation_id" in query:
                return [x_item("6002", f"{SECRET_TEXT} ?", "someone", "5001"), x_item("6001", "ok", "zed_user", "5002"),
                        x_item("6009", "mine", "acme_hq", "5001")]
            return [x_item("6003", f"about {SECRET_TEXT}", "somebody")]
        got = channels.inbound(self.stream, "x", state=self.state, now=NOW, search=search)
        self.assertEqual(got["state"], "on")
        flat = json.dumps(got["patterns"])
        for leak in (SECRET_TEXT, "someone", "somebody", "zed_user", "@", "acme_hq"):
            self.assertNotIn(leak, flat)
        self.assertEqual(sum(p["count"] for p in got["patterns"]), 3)
        shapes = {p["shape"] for p in got["patterns"]}
        self.assertEqual(shapes, {"question", "reply", "mention"})
        self.assertEqual({p["target_post"] for p in got["patterns"]}, {"", "5001", "5002"})
        with open(os.path.join(self.state, "inbound.json")) as f:
            saved = json.load(f)
        self.assertEqual(saved[self.stream]["x"]["since_id"], "6003")
        self.assertNotIn(SECRET_TEXT + "x", json.dumps(saved))
        # the next poll starts from the cursor and drops what it already counted
        again = channels.inbound(self.stream, "x", state=self.state, now=NOW, search=search)
        self.assertEqual(again["patterns"], [])
        self.assertEqual(calls[-1][1], saved[self.stream]["x"]["since_ts"])

    def test_a_failed_read_leaves_the_cursor(self):
        self.go_x()

        def search(*a, **k):
            raise channels.ChannelError("boom")
        with self.assertRaises(channels.ChannelError):
            channels.inbound(self.stream, "x", state=self.state, now=NOW, search=search)
        self.assertFalse(os.path.exists(os.path.join(self.state, "inbound.json")))


class LinkedInInbound(InboundCase):
    def test_comments_through_a_get_proxy_as_patterns(self):
        seen = []
        ms = int(NOW.timestamp() * 1000)

        def proxy(stream, channel, url, headers=None):
            seen.append((url, headers))
            return {"elements": [{"actor": "urn:li:person:abc", "message": {"text": f"{SECRET_TEXT}?"}, "created": {"time": ms}},
                                 {"actor": "urn:li:person:abd", "message": {"text": "fine"}, "created": {"time": ms - 10 ** 9}}]}
        with mock.patch.object(channels, "linkedin_linked", return_value=True):
            got = channels.inbound(self.stream, "linkedin", state=self.state, now=NOW, proxy=proxy)
        self.assertEqual(len(seen), 1)
        self.assertIn("socialActions/urn%3Ali%3Ashare%3A77/comments", seen[0][0])
        self.assertEqual(got["patterns"], [{"channel": "LinkedIn", "tier": "other", "shape": "question", "theme": "",
                                            "target_post": "urn:li:share:77", "count": 1}])
        self.assertNotIn("urn:li:person", json.dumps(got))
        self.assertEqual(channels.load_inbound_cursors(self.state)[self.stream]["linkedin"]["since_id"], str(ms))

    def test_the_proxy_call_is_a_get(self):
        import fake_composio_http
        fake = fake_composio_http.install(self, reply={})
        channels._proxy_get(self.stream, "linkedin", "https://api.linkedin.com/rest/socialActions/x/comments", {"A": "b"})
        call = fake.calls[-1]
        self.assertEqual(call["path"], "/api/v3.1/tools/execute/proxy")
        self.assertEqual(call["body"]["method"], "GET")
        self.assertEqual(call["body"]["connected_account_id"], f"ca_{self.stream}-linkedin")
        self.assertNotIn("binary_body", call["body"])

    def test_dry_run_calls_nothing(self):
        proxy = mock.Mock()
        with mock.patch.object(channels, "linkedin_linked", return_value=True):
            got = channels.inbound(self.stream, "linkedin", dry_run=True, state=self.state, now=NOW, proxy=proxy)
        proxy.assert_not_called()
        self.assertEqual(len(got["plan"]["queries"]), 1)
        self.assertTrue(got["plan"]["queries"][0][1].startswith("GET "))


class Engage(InboundCase):
    def test_merge_adds_counts_and_keeps_the_rest(self):
        engage.save({"inbound": {"posts_in_last_three_days": 2, "summary": "s"}}, self.state)
        p = {"channel": "X", "tier": "other", "shape": "reply", "theme": "", "target_post": "5001", "count": 2}
        engage.merge_inbound([p], state=self.state, now=NOW)
        sec = engage.merge_inbound([dict(p, count=1)], state=self.state, now=NOW)
        self.assertEqual(sec["posts_in_last_three_days"], 2)
        self.assertEqual(sec["counts"]["total"], 3)
        self.assertEqual(len(sec["patterns"]), 1)
        self.assertEqual(sec["counts"]["by_tier"], {"other": 3})

    def test_a_handle_or_extra_key_is_refused_before_writing(self):
        good = {"channel": "X", "tier": "other", "shape": "reply", "theme": "", "target_post": "1", "count": 1}
        for bad in (dict(good, target_post="@someone"), dict(good, author="x"), dict(good, tier="friend")):
            with self.assertRaises(ValueError):
                engage.merge_inbound([good, bad], state=self.state, now=NOW)
        self.assertFalse(os.path.exists(engage.path(self.state)))


class Cli(InboundCase):
    def test_poll_dry_run_and_status(self):
        self.go_x()
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(channels, "linkedin_linked", return_value=False):
            rc = inbound_cli.main(["poll", "--dry-run", "--stream", self.stream])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("would run", text)
        self.assertIn("nothing called, nothing written", text)
        self.assertIn("linkedin: off", text)

    def test_doctor_line_says_on_held_or_missing(self):
        self.settings["channels.x_own." + self.stream] = "composio"
        with mock.patch.object(channels, "linkedin_linked", return_value=False):
            lines = {l["check"]: l for l in channels._inbound_doctor(self.stream, {})}
        self.assertTrue(lines[f"composio {self.stream} inbound x"]["tail"].startswith("held:"))
        self.assertIn("no linkedin composio account", lines[f"composio {self.stream} inbound linkedin"]["tail"])

    def test_engine_knows_the_inbound_dry_form(self):
        import engine
        self.assertEqual(engine.DRY_FORMS["inbound"][0][-2:], ["poll", "--dry-run"])
        self.assertIn("inbound", engine.LIVE_REFUSED)


if __name__ == "__main__":
    unittest.main()
