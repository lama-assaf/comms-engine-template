"""
channels.py write drivers for X and LinkedIn, with the Composio HTTP layer faked.

Each test builds the Composio call for an input and compares its fields to what the
native path (autopilot's post_x, post_x_reply, post_linkedin, post_linkedin_comment)
sends for the same input: the same text, the same account, the same reply target.
"""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import fake_composio_http  # noqa: E402
import fixture_memory  # noqa: E402
import channels  # noqa: E402
import linkedin_api  # noqa: E402
import memory  # noqa: E402

CONFIG = {"LINKEDIN_ORG_ID": "555"}
AUTHOR = "urn:li:organization:555"
POST_URN = "urn:li:share:7123"


class DriverTest(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        self.stream = memory.DEFAULT_STREAM

    def call(self, driver, channel, kind, text, target=None, reply=None):
        request = {"stream": self.stream, "channel": channel, "kind": kind, "text": text, "target": target,
                   "account": channels.account_for(self.stream, channel), "ref": {}}
        fake = fake_composio_http.install(self, reply=reply)
        with mock.patch.object(linkedin_api, "settings", return_value=CONFIG):
            out = driver(request)
        slug, body = fake.executes[-1]
        alias = next(a["alias"] for a in fake.default_accounts() if a["id"] == body["connected_account_id"])
        return out, slug, alias, body["arguments"]

    def test_defaults_are_registered(self):
        channels.clear_drivers()
        channels.register_defaults()
        self.assertIs(channels._DRIVERS["x"], channels.x_driver)
        self.assertIs(channels._DRIVERS["linkedin"], channels.linkedin_driver)

    def test_x_post_matches_xurl_post(self):
        out, slug, account, args = self.call(channels.x_driver, "x", "post", "A claim, plainly.",
                                             reply={"data": {"data": {"id": "999"}}, "successful": True})
        self.assertEqual("TWITTER_CREATION_OF_A_POST", slug)
        self.assertEqual(f"{self.stream}-x", account)
        self.assertEqual({"text": "A claim, plainly."}, args)  # xurl post <text>
        self.assertEqual("https://x.com/i/web/status/999", out["url"])

    def test_x_reply_matches_xurl_reply(self):
        url = "https://x.com/someone/status/12345"
        for kind in ("reply", "comment", "link-reply"):
            out, _, account, args = self.call(channels.x_driver, "x", kind, "Reply text.", target=url,
                                              reply={"data": {"id": "77"}})
            # xurl reply <id of post_url.rsplit('/', 1)[-1]> <text>
            self.assertEqual({"text": "Reply text.", "reply_in_reply_to_tweet_id": url.rsplit("/", 1)[-1]}, args)
            self.assertEqual(f"{self.stream}-x", account)
            self.assertEqual("https://x.com/i/web/status/77", out["url"])

    def test_x_reply_without_target_or_id_fails(self):
        with self.assertRaises(channels.ChannelError):
            self.call(channels.x_driver, "x", "reply", "t", target=None, reply={"data": {"id": "1"}})

    def test_x_post_success_without_a_readable_id_is_not_an_error(self):
        out, _, _, _ = self.call(channels.x_driver, "x", "post", "t", reply={"data": {"note": "no id"}, "successful": True})
        self.assertEqual("", out["url"])
        self.assertIn("no readable post id", out["warning"])

    def test_linkedin_post_matches_linkedin_api(self):
        out, slug, account, args = self.call(channels.linkedin_driver, "linkedin", "post", "  The post.  ",
                                             reply={"data": {"id": POST_URN}, "successful": True})
        native = linkedin_api.build_post_payload(author=linkedin_api.author_urn(CONFIG), text="  The post.  ")
        self.assertEqual("LINKEDIN_CREATE_LINKED_IN_POST", slug)
        self.assertEqual(f"{self.stream}-linkedin", account)
        self.assertEqual({k: native[k] for k in ("author", "commentary", "visibility")}, args)
        self.assertEqual(AUTHOR, args["author"])
        self.assertEqual({"url": linkedin_api.post_url(POST_URN), "urn": POST_URN}, out)

    def test_linkedin_comment_matches_linkedin_api(self):
        for kind in ("comment", "reply", "link-reply"):
            out, slug, account, args = self.call(channels.linkedin_driver, "linkedin", kind, "A comment.",
                                                 target=POST_URN, reply={"data": {"$URN": "urn:li:comment:(x,1)"}})
            native = linkedin_api.build_comment_payload(actor=AUTHOR, text="A comment.")
            self.assertEqual("LINKEDIN_CREATE_COMMENT_ON_POST", slug)
            self.assertEqual(f"{self.stream}-linkedin", account)
            self.assertEqual(native["actor"], args["actor"])
            self.assertEqual(native["message"], args["message"])
            self.assertEqual(POST_URN, args["target_urn"])
            self.assertEqual(POST_URN, args["object"])
            self.assertEqual("urn:li:comment:(x,1)", out["urn"])

    def test_linkedin_comment_needs_a_urn_target(self):
        with self.assertRaises(channels.ChannelError):
            self.call(channels.linkedin_driver, "linkedin", "comment", "t", target="https://x.com/a/1", reply={})

    def test_x_take_down_deletes_the_post_by_its_id(self):
        url = "https://x.com/i/web/status/12345"
        out, slug, account, args = self.call(channels.x_driver, "x", "delete", "", target=url, reply={"successful": True})
        self.assertEqual("TWITTER_POST_DELETE_BY_POST_ID", slug)
        self.assertEqual(f"{self.stream}-x", account)
        self.assertEqual({"id": "12345"}, args)
        self.assertEqual(url, out["url"])
        with self.assertRaises(channels.ChannelError):
            self.call(channels.x_driver, "x", "delete", "", target="not a post url")

    def test_linkedin_take_down_deletes_a_post_or_a_comment_by_its_urn(self):
        out, slug, _, args = self.call(channels.linkedin_driver, "linkedin", "delete", "", target=POST_URN,
                                       reply={"successful": True})
        self.assertEqual(("LINKEDIN_DELETE_POST", {"post_urn": POST_URN}), (slug, args))
        self.assertEqual(POST_URN, out["urn"])
        comment = f"urn:li:comment:({POST_URN},6789)"
        _, slug, _, args = self.call(channels.linkedin_driver, "linkedin", "delete", "", target=comment,
                                     reply={"successful": True})
        self.assertEqual("LINKEDIN_DELETE_COMMENT", slug)
        self.assertEqual({"entity_urn": POST_URN, "comment_id": "6789", "actor": AUTHOR}, args)
        with self.assertRaises(channels.ChannelError):
            self.call(channels.linkedin_driver, "linkedin", "delete", "", target="https://www.linkedin.com/feed/update/x")

    def test_a_kind_a_driver_does_not_know_is_refused_not_sent_as_a_post(self):
        for driver, channel in ((channels.x_driver, "x"), (channels.linkedin_driver, "linkedin")):
            with self.assertRaises(channels.ChannelError):
                self.call(driver, channel, "telegram-blast", "text")

    def test_drivers_use_the_streams_own_account(self):
        other = [s for s in memory.streams() if s != self.stream][0]
        request = {"stream": self.stream, "channel": "x", "kind": "post", "text": "t", "target": None,
                   "account": f"{other}-x", "ref": {}}
        fake = fake_composio_http.install(self)
        with self.assertRaises(channels.CrossStreamAccount):
            channels.x_driver(request)
        self.assertEqual(fake.executes, [])


if __name__ == "__main__":
    unittest.main()
