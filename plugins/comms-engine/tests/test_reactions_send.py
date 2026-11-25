"""
Likes, reposts and quote posts through channels.send(): the kinds, their checks and their drivers.

A like or a repost has no text of ours, so the gate has nothing to read; what is asked instead:

- the stream's own account, and one reaction per target ever (the ledger id is `like:<post id>`)
- the target is one we may touch: its author is on a verified cleared row of handles.md, on the
  watchlist, or the post replies to one of ours; and its text passes the stealth list, the
  status words and the pair rules
- the day's cap (`reactions_per_day` in brand.json; a kind with no number has no allowance), the
  quiet hours and the pause
- a person's click, or the kind's mode on `auto`; a like on X goes out on a click only, because
  X requires a like to be initiated by the account's user, and the sign-off key ships empty
- a like on LinkedIn is refused by name: no tool creates one

A quote is a post of ours on someone else's: the whole text gate, and the target's checks too.
No handle reaches a record. Every driver is a fake; the Composio calls are checked on the fake
HTTP layer.
"""
import json
import os
import sys
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import acts  # noqa: E402
import brandfile  # noqa: E402
import channels  # noqa: E402
import config  # noqa: E402
import fake_composio_http  # noqa: E402
import guardrails  # noqa: E402
import linkedin_api  # noqa: E402
import memory  # noqa: E402
import switches  # noqa: E402
from test_channels_send import CLEAN, SAT_1000, TUE_1000  # noqa: E402
from test_switches import SwitchBase  # noqa: E402

POST = "1900000000000000001"
TEXT = "A relying party should be able to check the root for itself."


class Base(SwitchBase):
    CAPS = {"x": {"like": 2, "repost": 1, "quote": 1}, "linkedin": {"repost": 1}}

    def setUp(self):
        super().setUp()
        with open(memory.STREAMS_MD, encoding="utf-8") as f:
            bdoc = brandfile.from_streams_md(f.read(), config.brand())
        bdoc["streams"][self.root]["reactions_per_day"] = self.CAPS
        brandfile.write(bdoc)
        self.partner = next(row["x"] for row in memory.taggable_handles(self.root).values() if row.get("x"))

    def ref(self, kind="like", post=POST, **kw):
        ref = {"id": f"{kind}:{post}", "target_id": post, "author": self.partner, "target_text": TEXT}
        ref.update(kw)
        return ref

    def react(self, kind="like", channel="x", text="", at=TUE_1000, **kw):
        return channels.send(self.root, channel, kind, text, self.ref(kind, **kw), driver=self.fake, state=self.state, at=at)

    def no(self, check, kind="like", **kw):
        with self.assertRaises(channels.SendRefused) as cm:
            self.react(kind, **kw)
        self.assertEqual(check, cm.exception.check, cm.exception.reason)
        self.assertEqual([], self.fake.calls, "a refusal never reaches the driver")
        return cm.exception.reason

    def click(self, kind="like", post=POST, channel="x"):
        """A person's one click on the dashboard: an applied approval for this reaction on this target."""
        a = acts.record("decision", self.root, f"{kind}:{post}", {"decision": "approve", "item_kind": kind},
                        base=channels.reaction_hash(channel, kind, post), path=self.acts)
        acts.applied(a["id"], path=self.acts)


class Kinds(Base):
    def test_the_three_kinds_exist_and_a_like_needs_a_click_or_the_mode(self):
        for kind in ("like", "repost", "quote"):
            self.assertIn(kind, channels.KINDS)
        self.assertIn("a person's click", self.no("kind rule"))
        self.click()
        got = self.react()
        self.assertEqual((got["kind"], got["id"]), ("like", f"like:{POST}"))
        (call,) = self.fake.calls
        self.assertEqual((call["kind"], call["text"], call["ref"]["target_id"]), ("like", "", POST))

    def test_the_caps_come_from_the_setup_file(self):
        self.assertEqual(guardrails.reaction_cap(self.root, "x", "like"), 2)
        self.assertEqual(guardrails.reaction_cap(self.root, "linkedin", "like"), 0, "a kind with no number has no allowance")
        self.assertEqual(guardrails.reaction_cap(self.other, "x", "like"), 0)
        self.assertEqual(guardrails.parse_guardrails(memory.stream(self.root))["reactions"], self.CAPS)

    def test_one_reaction_per_target_ever(self):
        self.click()
        self.react()
        self.fake.calls.clear()
        self.assertIn("one per target", self.no("dedupe"))
        self.click("repost")
        self.react("repost")
        self.assertEqual(len(self.fake.calls), 1, "a repost of a post we liked is another reaction, and its own one")

    def test_the_id_names_the_target_and_nothing_else_will_do(self):
        self.no("kind", id="like:another-post")
        self.no("kind", target_id="")

    def test_a_like_on_linkedin_is_done_by_hand(self):
        self.assertIn("by hand", self.no("kind", channel="linkedin"))


class Target(Base):
    def test_the_author_must_be_cleared_watched_or_answering_us(self):
        self.click()
        self.assertIn("not on a verified cleared row", self.no("target", author="@a_stranger"))
        self.assertIn("not on a verified cleared row", self.no("target", author=""))
        with open(os.path.join(self.state, "watchlist.json"), "w", encoding="utf-8") as f:
            json.dump({"watched": [{"handle": "@A_Stranger"}], "dismissed": []}, f)
        self.react(author="@a_stranger")
        self.assertEqual(len(self.fake.calls), 1)

    def test_a_reply_to_one_of_our_own_posts_is_eligible_whoever_wrote_it(self):
        self.approve("r1")
        self.send("reply")
        self.fake.calls.clear()
        self.click()
        self.react(author="@a_stranger", in_reply_to="r1")
        self.assertEqual(len(self.fake.calls), 1)
        self.fake.calls.clear()
        self.click("like", "1900000000000000002")
        self.no("target", post="1900000000000000002", author="@a_stranger", in_reply_to="never-sent")

    def test_the_targets_text_is_checked_too(self):
        self.click()
        self.assertIn("not known", self.no("target", target_text=""))
        stealth = memory.denylist(self.root)[0]
        why = self.no("target", target_text=f"{stealth} joins the round.")
        self.assertIn("stealth", why)
        self.assertNotIn(stealth.lower(), why.lower(), "a refusal that is recorded never repeats the term")
        self.assertNotIn(stealth.lower(), json.dumps(self.lines()).lower())
        other = memory.stream(self.other)["name"]
        with open(memory.STREAMS_MD, encoding="utf-8") as f:
            text = f.read()
        self.assertIn(f"| {self.root} | {self.other} |", text, "the fixture has a pair rule for the other stream")
        self.react(target_text=f"{other} runs on the platform.")
        self.assertEqual(len(self.fake.calls), 1, "a stream named under a pair rule is not a reason to refuse")

    def test_a_status_word_in_the_target_refuses_it(self):
        with open(self.fixture.path("gate-rules.json"), "w", encoding="utf-8") as f:
            json.dump({"status_words": [{"pattern": r"\bcertified\b", "fix": "never certified"}]}, f)
        self.click()
        self.assertIn("status words", self.no("target", target_text="They are certified already."))


class Limits(Base):
    def test_the_days_cap_the_hours_and_the_pause(self):
        for i in range(2):
            post = f"19000000000000001{i}"
            self.click("like", post)
            self.react(post=post)
        self.fake.calls.clear()
        self.click("like", "1900000000000000019")
        self.assertIn("daily cap of 2", self.no("guardrails", post="1900000000000000019"))
        self.click("repost")
        self.assertIn("quiet hours", self.no("guardrails", kind="repost", at=SAT_1000))
        switches.set_pause(self.root, True, state=self.state)
        self.assertIn("paused", self.no("pause", kind="repost"))

    def test_a_kind_with_no_cap_is_never_sent(self):
        self.click("repost", POST, "linkedin")
        urn = "urn:li:share:7123"
        with mock.patch.object(guardrails, "reaction_cap", return_value=0):
            with self.assertRaises(channels.SendRefused) as cm:
                channels.send(self.root, "linkedin", "repost", "", {"id": f"repost:{urn}", "target_id": urn, "author": self.partner,
                                                                    "target_text": TEXT}, driver=self.fake, state=self.state, at=TUE_1000)
        self.assertEqual(cm.exception.check, "guardrails")
        self.assertIn("sets none", cm.exception.reason)


class Modes(Base):
    def setUp(self):
        super().setUp()
        self.autopilot()

    def test_a_repost_on_auto_goes_with_no_click_and_review_stops_the_next_one(self):
        self.set("repost")
        self.react("repost")
        self.assertEqual(len(self.fake.calls), 1)
        self.set("repost", "review", confirm=False)
        self.fake.calls.clear()
        with mock.patch.object(guardrails, "reaction_cap", return_value=5):  # room under the cap: the mode is what refuses
            self.no("kind rule", kind="repost", post="1900000000000000002")

    def test_a_like_on_x_never_goes_on_the_mode_alone(self):
        self.set("like")
        self.assertEqual(channels.mode(self.root, "x", "like", self.state), "auto")
        self.assertEqual(channels.reactions_signoff(self.root), "", "the sign-off ships empty")
        why = self.no("kind rule")
        self.assertIn("directly initiated", why)
        self.click()
        self.react()
        self.assertEqual(len(self.fake.calls), 1, "a person's click is the case X allows")

    def test_only_a_recorded_sign_off_lets_the_mode_send_a_like_on_x(self):
        self.set("like")
        real = config.cfg
        key = f"channels.reactions_signoff.{self.root}"
        with mock.patch.object(config, "cfg", lambda k, d=None, **kw: "2026-11-20: owner, likes on X" if k == key else real(k, d, **kw)):
            self.react()
        self.assertEqual(len(self.fake.calls), 1)

    def test_auto_does_not_skip_the_target_the_cap_or_the_dedupe(self):
        self.set("repost")
        self.no("target", kind="repost", author="@a_stranger")
        self.react("repost")
        self.fake.calls.clear()
        self.no("dedupe", kind="repost")
        self.assertIn("daily cap of 1", self.no("guardrails", kind="repost", post="1900000000000000002"))


class Quote(Base):
    def test_a_quote_takes_the_whole_text_gate_and_the_targets_checks(self):
        self.assertIn("empty", self.no("kind", kind="quote"))
        self.assertIn("approval", self.no("kind rule", kind="quote", text=CLEAN))
        a = acts.record("decision", self.root, f"quote:{POST}", {"decision": "approve"}, base=channels.text_hash("x", CLEAN), path=self.acts)
        acts.applied(a["id"], path=self.acts)
        name = memory.stream(self.root)["name"]
        self.no("gate", kind="quote", text=f"{name} issues the credential today.")
        self.no("target", kind="quote", text=CLEAN, author="@a_stranger")
        got = self.react("quote", text=CLEAN)
        self.assertEqual(got["kind"], "quote")
        self.assertEqual(self.fake.calls[0]["text"], CLEAN)
        self.fake.calls.clear()
        self.no("dedupe", kind="quote", text=CLEAN)


class Records(Base):
    def test_no_handle_reaches_a_record_and_the_target_is_kept_as_an_id(self):
        self.click()
        self.react()
        with open(os.path.join(self.state, channels.LEDGER_FILE), encoding="utf-8") as f:
            ledger = f.read()
        with open(os.path.join(self.state, channels.SENDS_LOG), encoding="utf-8") as f:
            log = f.read()
        handle = self.partner.lstrip("@").lower()
        for blob in (ledger, log):
            self.assertNotIn(handle, blob.lower())
            self.assertNotIn(TEXT, blob, "nor the words of someone else's post")
        entry = json.loads(ledger)["sends"][f"like:{POST}"]
        self.assertEqual((entry["kind"], entry["target_id"], entry["state"]), ("like", POST, "sent"))
        self.assertEqual(self.lines()[-1]["target_id"], POST)

    def test_a_like_is_undone_through_the_take_down(self):
        self.click()
        self.react()
        self.fake.calls.clear()
        a = acts.record("takedown", self.root, f"like:{POST}", {"channel": "x"}, by="alpha", path=self.acts)
        acts.applied(a["id"], path=self.acts)
        channels.send(self.root, "x", "delete", "", {"target_id": f"like:{POST}"}, driver=self.fake, state=self.state, at=TUE_1000)
        (call,) = self.fake.calls
        self.assertEqual((call["kind"], call["target_kind"], call["target_post"]), ("delete", "like", POST))


class Drivers(Base):
    def call(self, driver, channel, kind, text="", ref=None, replies=None, **extra):
        request = {"stream": self.root, "channel": channel, "kind": kind, "text": text, "target": None,
                   "account": channels.account_for(self.root, channel), "ref": ref or {}}
        request.update(extra)
        fake = fake_composio_http.install(self, reply={"data": {"id": "42"}, "successful": True})
        with mock.patch.object(linkedin_api, "settings", return_value={"LINKEDIN_ORG_ID": "555"}):
            out = driver(request)
        return out, [(slug, body["arguments"]) for slug, body in fake.executes]

    def test_x_like_asks_who_the_account_is_then_likes_as_that_account(self):
        out, calls = self.call(channels.x_driver, "x", "like", ref={"target_id": POST})
        self.assertEqual(calls, [("TWITTER_USER_LOOKUP_ME", {}), ("TWITTER_USER_LIKE_POST", {"id": "42", "tweet_id": POST})])
        self.assertEqual(out, {"url": ""})

    def test_x_repost_and_quote(self):
        _, calls = self.call(channels.x_driver, "x", "repost", ref={"target_id": POST})
        self.assertEqual(calls, [("TWITTER_RETWEET_POST", {"tweet_id": POST})])
        out, calls = self.call(channels.x_driver, "x", "quote", text="Our reading.", ref={"target_id": POST})
        self.assertEqual(calls, [("TWITTER_CREATION_OF_A_POST", {"text": "Our reading.", "quote_tweet_id": POST})])
        self.assertEqual(out["url"], "https://x.com/i/web/status/42")
        with self.assertRaises(channels.ChannelError):
            self.call(channels.x_driver, "x", "repost", ref={"target_id": "not-a-post"})

    def test_x_undo(self):
        _, calls = self.call(channels.x_driver, "x", "delete", target_kind="like", target_post=POST)
        self.assertEqual(calls, [("TWITTER_USER_LOOKUP_ME", {}), ("TWITTER_UNLIKE_POST", {"id": "42", "tweet_id": POST})])
        _, calls = self.call(channels.x_driver, "x", "delete", target_kind="repost", target_post=POST)
        self.assertEqual(calls, [("TWITTER_UNRETWEET_POST", {"source_tweet_id": POST})])

    def test_linkedin_reshare_and_quote_are_posts_with_a_reshare_context(self):
        urn = "urn:li:share:7123"
        _, calls = self.call(channels.linkedin_driver, "linkedin", "repost", ref={"target_id": urn})
        slug, args = calls[0]
        self.assertEqual(slug, "LINKEDIN_CREATE_LINKED_IN_POST")
        self.assertEqual((args["reshareContext"], args["commentary"], args["author"]), ({"parent": urn}, "", "urn:li:organization:555"))
        _, calls = self.call(channels.linkedin_driver, "linkedin", "quote", text="Our reading.", ref={"target_id": urn})
        self.assertEqual((calls[0][1]["reshareContext"], calls[0][1]["commentary"]), ({"parent": urn}, "Our reading."))
        with self.assertRaises(channels.ChannelError):
            self.call(channels.linkedin_driver, "linkedin", "repost", ref={"target_id": "https://www.linkedin.com/feed/update/x"})
        with self.assertRaises(channels.ChannelError):
            self.call(channels.linkedin_driver, "linkedin", "like", ref={"target_id": urn})

    def test_the_slugs_are_the_ones_composios_tool_list_names(self):
        self.assertEqual((channels.X_LIKE_SLUG, channels.X_UNLIKE_SLUG, channels.X_REPOST_SLUG, channels.X_UNREPOST_SLUG),
                         ("TWITTER_USER_LIKE_POST", "TWITTER_UNLIKE_POST", "TWITTER_RETWEET_POST", "TWITTER_UNRETWEET_POST"))
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), ".atelier", "memory", "decisions",
                               "2026-11-13-reactions-platform-rules.md"), encoding="utf-8") as f:
            decision = f.read()
        for slug in (channels.X_LIKE_SLUG, channels.X_UNLIKE_SLUG, channels.X_REPOST_SLUG, channels.X_UNREPOST_SLUG,
                     channels.X_DELETE_SLUG, channels.LINKEDIN_DELETE_SLUG, channels.LINKEDIN_DELETE_COMMENT_SLUG):
            self.assertIn(slug, decision, f"{slug} is not in the recorded tool list: a slug is looked up, never guessed")


if __name__ == "__main__":
    import unittest
    unittest.main()
