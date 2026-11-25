"""
channels.py: the Composio REST client, with the HTTP layer faked (an injected urllib opener).

- a tool runs as `POST /api/v3.1/tools/execute/<SLUG>` with `connected_account_id`, `arguments`
  and (where the account has one) `user_id`; the project key is sent as `x-api-key` only
- the account is the `<stream>-<channel>` alias in the stream's own project, else the id
  recorded in engine.json
- `dry_run` plans the call and checks the account, and makes no execute call
- another stream's account is refused before any request
- an unknown stream, an unknown channel or another toolkit's slug is refused
- an HTTP error, a non-JSON reply and `successful: false` raise ChannelError, and the key
  appears in no URL, no error message and no call log
"""
import os
import sys
import unittest
import urllib.error
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import fake_composio_http  # noqa: E402
import fixture_memory  # noqa: E402
import channels  # noqa: E402
import memory  # noqa: E402

KEY = fake_composio_http.KEY


class ChannelsTest(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        self.fake = fake_composio_http.install(self, reply={"data": {"id": "1"}, "successful": True})
        self.root = memory.DEFAULT_STREAM
        self.other = [s for s in memory.streams() if s != self.root][0]

    def test_request_shape_and_parsed_result(self):
        result = channels._execute(self.root, "X", "TWITTER_CREATION_OF_A_POST", {"text": "hi"})
        self.assertEqual(result["data"]["id"], "1")
        lists = [c for c in self.fake.calls if c["path"] == "/api/v3.1/connected_accounts"]
        self.assertEqual(lists[0]["method"], "GET")
        self.assertEqual(lists[0]["query"]["limit"], ["100"])
        slug, body = self.fake.executes[0]
        self.assertEqual(slug, "TWITTER_CREATION_OF_A_POST")
        self.assertEqual(body, {"connected_account_id": f"ca_{self.root}-x", "arguments": {"text": "hi"}, "user_id": "u_1"})
        post = [c for c in self.fake.calls if c["method"] == "POST"][0]
        self.assertEqual(post["path"], "/api/v3.1/tools/execute/TWITTER_CREATION_OF_A_POST")
        self.assertTrue(post["url"].startswith("https://backend.composio.dev/"))

    def test_key_is_sent_as_a_header_and_nowhere_else(self):
        channels._execute(self.root, "X", "TWITTER_RECENT_SEARCH", {"query": "q"})
        for call in self.fake.calls:
            self.assertEqual(call["headers"]["x-api-key"], KEY)
            self.assertNotIn(KEY, call["url"])
            self.assertNotIn(KEY, repr(call["body"]))
            self.assertNotIn(KEY, repr(call["query"]))

    def test_dry_run_checks_the_account_and_executes_nothing(self):
        out = channels._execute(self.root, "linkedin", "LINKEDIN_CREATE_LINKED_IN_POST", {"a": 1}, dry_run=True)
        self.assertTrue(out["dry_run"])
        self.assertEqual(out["account"], f"ca_{self.root}-linkedin")
        self.assertEqual(self.fake.executes, [])
        self.assertTrue(all(c["method"] == "GET" for c in self.fake.calls))

    def test_dry_run_without_the_account_fails(self):
        self.enterContext(mock.patch.object(channels, "recorded_account_id", lambda stream, channel: ""))
        self.fake.accounts = []
        with self.assertRaisesRegex(channels.ChannelError, "no x account"):
            channels._execute(self.root, "X", "TWITTER_RECENT_SEARCH", dry_run=True)

    def test_refuses_another_streams_account(self):
        with self.assertRaises(channels.CrossStreamAccount):
            channels._execute(self.root, "X", "TWITTER_CREATION_OF_A_POST", {}, account=f"{self.other}-x")
        with self.assertRaises(channels.CrossStreamAccount):
            channels._execute(self.root, "X", "TWITTER_CREATION_OF_A_POST", {}, account="ca_abc123")
        self.assertEqual(self.fake.calls, [])

    def test_an_account_of_another_projects_alias_is_not_found(self):
        self.enterContext(mock.patch.object(channels, "recorded_account_id", lambda stream, channel: ""))
        # the project holds only the other stream's alias: this stream has no account, nothing crosses over
        self.fake.accounts = [fake_composio_http.account(f"{self.other}-x", "twitter")]
        with self.assertRaisesRegex(channels.ChannelError, "no x account"):
            channels._execute(self.root, "X", "TWITTER_RECENT_SEARCH")
        self.assertEqual(self.fake.executes, [])

    def test_own_alias_explicit_is_accepted(self):
        channels._execute(self.other, "X", "TWITTER_RECENT_SEARCH", account=f"{self.other}-x")
        self.assertEqual(self.fake.executes[0][1]["connected_account_id"], f"ca_{self.other}-x")

    def test_recorded_account_id_is_used_without_an_alias(self):
        self.fake.accounts = [fake_composio_http.account(None, "twitter", ident="ca_dash")]
        with mock.patch("config.cfg", lambda path, default=None, **kw: "ca_dash" if path == f"channels.account_id.{self.root}.x" else default):
            channels._execute(self.root, "X", "TWITTER_RECENT_SEARCH")
        self.assertEqual(self.fake.executes[0][1]["connected_account_id"], "ca_dash")

    def test_a_recorded_id_outside_the_project_fails(self):
        self.fake.accounts = []
        with mock.patch("config.cfg", lambda path, default=None, **kw: "ca_gone" if path == f"channels.account_id.{self.root}.x" else default):
            with self.assertRaisesRegex(channels.ChannelError, "not in its Composio project"):
                channels._execute(self.root, "X", "TWITTER_RECENT_SEARCH")

    def test_each_stream_gets_its_own_alias(self):
        self.assertNotEqual(channels.account_for(self.root, "X"), channels.account_for(self.other, "X"))

    def test_unknown_stream_channel_and_slug(self):
        with self.assertRaises(memory.SharedMemoryError):
            channels._execute("nobody", "X", "TWITTER_RECENT_SEARCH")
        with self.assertRaises(channels.ChannelError):
            channels._execute(self.root, "myspace", "TWITTER_RECENT_SEARCH")
        with self.assertRaises(channels.ChannelError):
            channels._execute(self.root, "X", "LINKEDIN_GET_SHARE_STATS")
        self.assertEqual(self.fake.calls, [])

    def test_failures_raise_and_never_carry_the_key(self):
        self.fake.reply = {"successful": False, "error": "nope"}
        with self.assertRaisesRegex(channels.ChannelError, "not successful"):
            channels._execute(self.root, "X", "TWITTER_RECENT_SEARCH")
        self.fake.reply = urllib.error.URLError("down " + KEY)
        with self.assertRaises(channels.ChannelError) as ctx:
            channels._execute(self.root, "X", "TWITTER_RECENT_SEARCH")
        self.assertNotIn(KEY, str(ctx.exception))
        self.fake.status, self.fake.error_body = 401, "bad key " + KEY
        channels.clear_cache()
        with self.assertRaisesRegex(channels.ChannelError, "HTTP 401") as ctx:
            channels.connections(self.root)
        self.assertNotIn(KEY, str(ctx.exception))

    def test_non_json_reply_raises(self):
        class Raw(fake_composio_http.FakeComposio):
            def open(self, request, timeout=None):
                if "tools/execute" in request.full_url:
                    return fake_composio_http.Response(None, raw=b"<html>gateway</html>")
                return super().open(request, timeout)
        with mock.patch.object(channels, "_OPENER", Raw()):
            with self.assertRaisesRegex(channels.ChannelError, "no JSON"):
                channels._execute(self.root, "X", "TWITTER_RECENT_SEARCH")

    def test_no_key_is_refused_before_any_request(self):
        import fake_composio_key
        fake_composio_key.install(self, {})
        channels.clear_cache()
        with self.assertRaises(channels.MissingComposioKey):
            channels._execute(self.root, "X", "TWITTER_RECENT_SEARCH")
        self.assertEqual(self.fake.calls, [])

    def test_connections_groups_by_toolkit_and_pages(self):
        pages = [{"items": [fake_composio_http.account("a-x", "twitter")], "next_cursor": "c2"},
                 {"items": [fake_composio_http.account("a-linkedin", "linkedin", status="EXPIRED")], "next_cursor": None}]
        seen = []

        class Paged(fake_composio_http.FakeComposio):
            def open(self, request, timeout=None):
                seen.append(request.full_url)
                return fake_composio_http.Response(pages[len(seen) - 1])
        channels.clear_cache()
        conns = channels.connections(self.root, opener=Paged())
        self.assertEqual(sorted(conns), ["linkedin", "twitter"])
        self.assertEqual(conns["linkedin"][0]["status"], "EXPIRED")
        self.assertEqual(conns["twitter"][0]["auth_config_id"], "ac_x")
        self.assertIn("cursor=c2", seen[1])

    def test_auth_configs_listing(self):
        self.fake.auth_configs = ["ac_one", "ac_two"]
        got = channels.auth_configs(self.root)
        self.assertEqual([c["id"] for c in got], ["ac_one", "ac_two"])
        self.assertEqual(self.fake.calls[-1]["path"], "/api/v3.1/auth_configs")

    def test_proxy_get_body(self):
        self.fake.reply = {"data": {"elements": []}}
        out = channels._proxy_get(self.root, "linkedin", "https://api.linkedin.com/rest/socialActions/x/comments", {"A": "b"})
        self.assertEqual(out, {"data": {"elements": []}})
        call = self.fake.calls[-1]
        self.assertEqual(call["path"], "/api/v3.1/tools/execute/proxy")
        self.assertEqual(call["body"]["method"], "GET")
        self.assertEqual(call["body"]["endpoint"], "https://api.linkedin.com/rest/socialActions/x/comments")
        self.assertEqual(call["body"]["parameters"], [{"name": "A", "value": "b", "type": "header"}])
        self.assertEqual(call["body"]["connected_account_id"], f"ca_{self.root}-linkedin")


if __name__ == "__main__":
    unittest.main()
