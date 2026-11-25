"""
The shape of the two read-only "who am I" replies (TWITTER_USER_LOOKUP_ME, LINKEDIN_GET_MY_INFO),
recorded from a live check and scrubbed to placeholders (composio_whoami_fixtures.json), and
what the engine reads out of them.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import channels  # noqa: E402
import fake_composio_http  # noqa: E402
import memory  # noqa: E402

try:
    import fixture_memory  # noqa: E402
    Base = fixture_memory.FixtureMemoryCase
except ImportError:  # a checkout without the fixture suite reads its own memory
    Base = unittest.TestCase

with open(os.path.join(HERE, "composio_whoami_fixtures.json"), encoding="utf-8") as f:
    FIXTURES = json.load(f)


class WhoAmIShape(Base):
    def setUp(self):
        super().setUp()
        self.stream = memory.DEFAULT_STREAM

    def test_the_x_reply_gives_the_username_the_handle_check_reads(self):
        fake_composio_http.install(self, reply={"TWITTER_USER_LOOKUP_ME": FIXTURES["TWITTER_USER_LOOKUP_ME"]})
        self.assertEqual("@example_account", channels.live_handle(self.stream, "x"))

    def test_the_x_reply_is_the_nested_shape(self):
        reply = FIXTURES["TWITTER_USER_LOOKUP_ME"]
        self.assertIs(reply["successful"], True)
        self.assertEqual({"id", "name", "username"}, set(reply["data"]["data"]))

    def test_the_linkedin_reply_carries_the_profile_text_the_slug_check_searches(self):
        fake_composio_http.install(self, reply={"LINKEDIN_GET_MY_INFO": FIXTURES["LINKEDIN_GET_MY_INFO"]})
        text = channels.live_handle(self.stream, "linkedin")
        self.assertIn('"vanityName": "example"', text)
        self.assertIs(FIXTURES["LINKEDIN_GET_MY_INFO"]["successful"], True)
        self.assertTrue({"id", "vanityName", "localizedFirstName", "profileUrl"} <= set(FIXTURES["LINKEDIN_GET_MY_INFO"]["data"]))

    def test_no_fixture_carries_a_token_or_an_email(self):
        text = json.dumps(FIXTURES)
        self.assertNotIn("@", text.replace("example", ""))
        self.assertNotRegex(text, r"(?i)bearer|api[_-]?key|ak_|sk-")


if __name__ == "__main__":
    unittest.main()
