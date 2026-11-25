"""
channels.send(): the one send gate, with the write driver faked.

A refusal per check (kind, driver, account, dedupe, gate, cites, stealth, hold, pair,
guardrails, kind rule), a send per kind (post, reply, comment, link-reply), the ledger
written before the driver is called, and one sends.jsonl line per attempt, sent or refused.
"""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import acts  # noqa: E402
import channels  # noqa: E402
import hermetic_channels  # noqa: E402
import gate_lint  # noqa: E402
import lifecycle  # noqa: E402
import memory  # noqa: E402

try:
    import fixture_memory  # noqa: E402
    Base = fixture_memory.FixtureMemoryCase
except ImportError:  # the checkout without the fixture suite reads its own memory
    Base = unittest.TestCase

TUE_1000 = dt.datetime(2026, 11, 10, 10, 0, tzinfo=dt.timezone.utc)
SAT_1000 = dt.datetime(2026, 11, 14, 10, 0, tzinfo=dt.timezone.utc)
CLEAN = "A relying party can check the identifier against the standard."
PASS = {"verdict": "pass", "checks": []}


class Fake:
    """A write driver that records its requests."""

    def __init__(self, result=None, fail=None):
        self.calls = []
        self.result = result or {"url": "https://x.com/own/status/1", "urn": None}
        self.fail = fail

    def __call__(self, request):
        self.calls.append(request)
        if self.fail:
            raise RuntimeError(self.fail)
        return self.result


class SendBase(Base):
    def setUp(self):
        super().setUp()
        hermetic_channels.install(self)
        channels.clear_drivers()
        self.addCleanup(channels.clear_drivers)
        self.state = tempfile.mkdtemp()
        self.root = memory.DEFAULT_STREAM
        self.other = [s for s in memory.streams() if s != self.root][0]
        self.other_name = memory.stream(self.other)["name"]
        self.cite = next(c["id"] for c in memory.current_claims(self.root)
                         if c["grade"] == "evidenced" and memory.citable(c["id"], self.root)[0])
        self.fake = Fake()
        self.acts = os.path.join(self.state, "acts.jsonl")
        self.lc = os.path.join(self.state, "lifecycle.jsonl")

    def send(self, kind="reply", text=CLEAN, ref=None, channel="X", at=TUE_1000, driver="fake", **kw):
        ref = dict(ref or {})
        if "parent_id" not in ref:
            ref.setdefault("id", "r1")
        ref.setdefault("target", "https://x.com/other/status/9")
        if driver == "fake":
            driver = self.fake
        return channels.send(self.root, channel, kind, text, ref, driver=driver, state=self.state, at=at, **kw)

    def lines(self):
        return channels.sends(self.state)

    def refused(self, check, *a, **k):
        with self.assertRaises(channels.SendRefused) as cm:
            self.send(*a, **k)
        self.assertEqual(check, cm.exception.check, cm.exception.reason)
        self.assertEqual([], self.fake.calls, "a refusal never reaches the driver")
        last = self.lines()[-1]
        self.assertEqual(("refused", check), (last["outcome"], last["check"]))
        self.assertTrue(last["reason"])
        return cm.exception

    def approve(self, target, decision="approve", base=None, stream=None):
        a = acts.record("decision", stream or self.root, target, {"decision": decision}, base=base, path=self.acts)
        acts.applied(a["id"], path=self.acts)
        return a["id"]

    def schedule_post(self, pid="p1", date="2026-11-10"):
        lifecycle.gate(pid, "h1", "v1", stream=self.root, path=self.lc)
        lifecycle.decide(pid, self.approve(pid, base="h1"), acts_path=self.acts, path=self.lc)
        lifecycle.schedule(pid, date, lambda: (True, ""), path=self.lc)


class Refusals(SendBase):
    def test_unknown_kind_and_empty_text(self):
        self.refused("kind", "tweet")
        self.refused("kind", "reply", text="  ")
        self.refused("kind", "reply", ref={"id": ""})

    def test_no_driver_configured(self):
        self.refused("driver", "reply", driver=None)

    def test_registered_driver_is_used(self):
        channels.register_driver("x", self.fake)
        self.approve("r1")
        self.send("reply", driver=None)
        self.assertEqual(1, len(self.fake.calls))

    def test_other_streams_account(self):
        self.refused("account", "reply", ref={"account": f"{self.other}-x"})

    def test_channel_not_the_streams_own(self):
        self.refused("account", "reply", channel="telegram")

    def test_gate_blocks_a_reply(self):
        self.approve("r1")
        self.refused("gate", "reply", text=f"{memory.stream(self.root)['name']} issues the credential today.")

    def test_gate_blocks_a_post_and_passes_a_clean_one(self):
        self.schedule_post()
        with mock.patch.object(gate_lint, "lint", return_value={"verdict": "block", "checks": [
                {"check": "lint: hook", "result": "block", "line": "", "fix": "no hook"}]}):
            self.refused("gate", "post", ref={"id": "p1", "item": {"title": "t"}})
        self.refused("gate", "post", ref={"id": "p1"})  # no item to read

    def test_a_team_row_post_has_no_item_so_the_text_level_gate_reads_it(self):
        self.schedule_post()
        with mock.patch.object(gate_lint, "lint_text", return_value={"verdict": "block", "checks": [
                {"check": "lint: stealth", "result": "block", "line": "", "fix": "held term"}]}):
            self.refused("gate", "post", ref={"id": "p1", "text_gate": True})
        self.send("post", text="A post about the standard.", ref={"id": "p1", "text_gate": True})
        self.assertEqual("sent", self.lines()[-1]["outcome"])

    def test_the_write_driver_setting_defaults_to_native(self):
        self.assertEqual(("native", None), channels.write_driver(self.root))
        with mock.patch("config.cfg", return_value="composio"):
            self.assertEqual(("composio", None), channels.write_driver(self.root))
        with mock.patch("config.cfg", return_value="carrier-pigeon"):
            driver, why = channels.write_driver(self.root)
        self.assertEqual("carrier-pigeon", driver)
        self.assertIn("unknown driver", why)

    def test_unknown_superseded_and_uncorroborated_cites(self):
        self.approve("r1")
        self.refused("cites", "reply", ref={"cites": ["C-nope-999"]})
        for row in memory.load_claims(self.root).values():
            if row["superseded_by"] or row["corroboration"] not in memory.CITABLE_CORROBORATION:
                self.refused("cites", "reply", ref={"cites": [row["id"]]})

    def test_stealth_term_blocks(self):
        self.approve("r1")
        term = memory.denylist(self.root)[0]
        with mock.patch.object(gate_lint, "lint_text", return_value=PASS):
            self.refused("stealth", "reply", text=f"We are talking to {term} next.")

    def test_stealth_fails_closed_without_the_companion(self):
        self.approve("r1")
        gone = {"private": {"present": False, "path": "handles.private.md"}}
        with mock.patch.object(gate_lint, "lint_text", return_value=PASS), \
                mock.patch.object(memory, "load_handles", return_value=gone), \
                mock.patch.object(memory, "private_expected", return_value=True):
            self.refused("stealth", "reply")

    def test_hold_needs_a_recorded_release(self):
        self.approve("r1")
        text = "Adoption grew 40% in a quarter."
        with mock.patch.object(gate_lint, "lint_text", return_value=PASS):
            self.refused("hold", "reply", text=text)
            self.refused("hold", "reply", text="Ask @someone_unlisted about it.")
            self.approve("r1", decision="release-hold")
            self.send("reply", text=text)
        self.assertEqual("sent", self.lines()[-1]["outcome"])

    def test_hold_cleared_by_a_cite_for_statistics_only(self):
        self.approve("r1")
        with mock.patch.object(gate_lint, "lint_text", return_value=PASS):
            self.send("reply", text="Adoption grew 40% in a quarter.", ref={"cites": [self.cite]})

    def test_pair_rule_is_required_to_name_another_stream(self):
        self.approve("r1")
        text = f"{self.other_name} runs on the same standard."
        real = memory.stream

        def no_pairs(slug, path=None):
            row = dict(real(slug, path))
            row["pair_rules"] = []
            return row
        with mock.patch.object(gate_lint, "lint_text", return_value=PASS):
            with mock.patch.object(memory, "stream", side_effect=no_pairs):
                self.refused("pair", "reply", text=text)
            self.send("reply", text=text)  # the registry's own rule covers it

    def test_guardrails_quiet_hours_and_cap(self):
        self.approve("r1")
        self.refused("guardrails", "reply", at=SAT_1000)
        self.schedule_post("p1")
        self.schedule_post("p2")
        self.schedule_post("p3")
        with mock.patch.object(gate_lint, "lint", return_value=PASS):
            for pid in ("p1", "p2"):
                self.send("post", text=f"Post {pid} about the standard.", ref={"id": pid, "item": {}})
            self.fake.calls.clear()
            self.refused("guardrails", "post", text="Post p3 about the standard.", ref={"id": "p3", "item": {}})

    def test_guardrails_refuses_a_stream_that_may_not_send(self):
        with self.assertRaises(channels.SendRefused) as cm:
            channels.send(self.other, "X", "reply", CLEAN, {"id": "r1", "target": "t"},
                          driver=self.fake, state=self.state, at=TUE_1000)
        self.assertTrue(cm.exception.check)
        self.assertEqual([], self.fake.calls)

    def test_dedupe_never_sends_the_same_text_twice(self):
        self.approve("r1")
        self.approve("r2")
        self.send("reply")
        self.refused_again = None
        with self.assertRaises(channels.SendRefused) as cm:
            self.send("reply", ref={"id": "r2"})
        self.assertEqual("dedupe", cm.exception.check)
        self.assertEqual(1, len(self.fake.calls))

    def test_unconfirmed_earlier_send_is_not_repeated(self):
        self.approve("r1")
        with open(os.path.join(self.state, "send-ledger.json"), "w") as f:
            json.dump({"sends": {"r1": {"state": "sending", "hash": "x"}}}, f)
        self.refused("dedupe", "reply")


class Kinds(SendBase):
    def test_reply_needs_approval_or_the_switch(self):
        self.refused("kind rule", "reply")
        with mock.patch.object(channels, "auto_reply_on", return_value=True):
            self.send("reply")
        self.assertEqual("sent", self.lines()[-1]["outcome"])

    def test_reply_needs_a_target_and_the_right_approval(self):
        self.approve("r1", decision="reject")
        self.refused("kind rule", "reply")
        self.approve("r1")
        with self.assertRaises(channels.SendRefused) as cm:
            self.send("reply", ref={"target": ""})
        self.assertEqual("kind rule", cm.exception.check)

    def test_approval_of_a_different_text_does_not_cover_this_one(self):
        self.approve("r1", base="somethingelse")
        self.refused("kind rule", "reply")

    def test_comment_on_linkedin_approved(self):
        self.approve("c1")
        out = self.send("comment", channel="linkedin", ref={"id": "c1", "target": "urn:li:share:1"})
        self.assertEqual("comment", out["kind"])
        self.assertEqual(f"{self.root}-linkedin", self.fake.calls[0]["account"])
        self.assertEqual("urn:li:share:1", self.fake.calls[0]["target"])

    def test_post_must_be_scheduled_and_due(self):
        with mock.patch.object(gate_lint, "lint", return_value=PASS):
            self.refused("kind rule", "post", ref={"id": "p1", "item": {}})  # draft
            self.schedule_post("p1", date="2026-11-12")
            self.refused("kind rule", "post", ref={"id": "p1", "item": {}})  # not yet due
            self.schedule_post("p2", date="2026-11-10")
            out = self.send("post", ref={"id": "p2", "item": {}})
        self.assertEqual("p2", out["id"])
        self.assertEqual("sent", lifecycle.state("p2", self.lc))
        self.assertEqual("scheduled", lifecycle.state("p1", self.lc))

    def test_post_text_must_be_the_gated_text(self):
        self.schedule_post("p1")
        with mock.patch.object(gate_lint, "lint", return_value=PASS):
            self.refused("kind rule", "post", ref={"id": "p1", "item": {}, "text_hash": "other"})

    def link_setup(self, **over):
        self.schedule_post("p1")
        with mock.patch.object(gate_lint, "lint", return_value=PASS):
            self.send("post", ref={"id": "p1", "item": {}})
        url = "https://www.example.com/insights/a-post"
        ref = {"parent_id": "p1", "target": "https://x.com/own/status/1",
               "blog_row": {"status": "Published", "url": url}}
        ref.update(over)
        return f"{channels.LINK_CAPTIONS['x']} {url}", ref

    def test_link_reply_sends_under_the_parents_approval(self):
        text, ref = self.link_setup()
        self.fake.calls.clear()
        out = self.send("link-reply", text=text, ref=ref)
        self.assertEqual("p1#link", out["id"])
        self.assertEqual("https://x.com/own/status/1", self.fake.calls[0]["target"])
        ledger = json.load(open(os.path.join(self.state, "send-ledger.json")))["sends"]
        self.assertEqual(text.split(": ")[1], ledger["p1"]["link_reply"]["link"])

    def test_link_reply_refusals(self):
        text, ref = self.link_setup()
        self.fake.calls.clear()
        self.refused("kind rule", "link-reply", text="Read this: " + ref["blog_row"]["url"], ref=ref)
        self.refused("kind rule", "link-reply", text=text, ref={**ref, "blog_row": {**ref["blog_row"], "status": "Ready"}})
        self.refused("kind rule", "link-reply", text=text, ref={**ref, "target": "https://x.com/someone/status/5"})
        self.refused("kind rule", "link-reply", text=text, ref={**ref, "parent_id": "nope"})
        self.refused("kind rule", "link-reply", text=text, ref={**ref, "blog_row": {"status": "Published", "url": "http://x.test/a"}})

    def test_link_reply_needs_the_parents_approval(self):
        text, ref = self.link_setup()
        self.fake.calls.clear()
        open(self.acts, "w").close()  # the approval record is gone
        self.refused("kind rule", "link-reply", text=text, ref=ref)


class Records(SendBase):
    def test_ledger_is_written_before_the_driver_runs(self):
        self.approve("r1")
        seen = {}

        def driver(request):
            seen.update(json.load(open(os.path.join(self.state, "send-ledger.json")))["sends"]["r1"])
            return {"url": "https://x.com/own/status/2"}
        self.send("reply", driver=driver)
        self.assertEqual("sending", seen["state"])
        done = json.load(open(os.path.join(self.state, "send-ledger.json")))["sends"]["r1"]
        self.assertEqual(("sent", "https://x.com/own/status/2"), (done["state"], done["url"]))
        for k in ("page_id", "platform", "title", "hash", "at", "stream"):
            self.assertIn(k, done)
        self.assertEqual(channels.text_hash("x", CLEAN), done["hash"])

    def test_one_line_per_attempt(self):
        self.approve("r1")
        self.refused("cites", "reply", ref={"cites": ["C-nope-999"]})
        self.send("reply")
        self.assertEqual(["refused", "sent"], [r["outcome"] for r in self.lines()])
        sent = self.lines()[1]
        for k in ("at", "stream", "channel", "kind", "id", "text_hash", "url"):
            self.assertIn(k, sent)

    def test_a_refusal_writes_no_ledger(self):
        self.refused("kind rule", "reply")
        self.assertFalse(os.path.exists(os.path.join(self.state, "send-ledger.json")))

    def test_driver_failure_is_recorded_and_raised(self):
        self.approve("r1")
        with self.assertRaises(channels.ChannelError):
            self.send("reply", driver=Fake(fail="boom"))
        self.assertEqual("failed", self.lines()[-1]["outcome"])
        ledger = json.load(open(os.path.join(self.state, "send-ledger.json")))["sends"]
        self.assertEqual("failed", ledger["r1"]["state"])


class TakeDown(SendBase):
    """The `delete` kind: a person takes down what the engine sent, in one act, even while paused."""

    URL = "https://x.com/own/status/1"

    def setUp(self):
        super().setUp()
        self.approve("r1")
        self.send("reply")
        self.fake.calls.clear()

    def takedown_act(self, target="r1", by="alpha", stream=None):
        a = acts.record("takedown", stream or self.root, target, {"channel": "x"}, by=by, path=self.acts)
        acts.applied(a["id"], path=self.acts)
        return a["id"]

    def delete(self, target="r1", channel="X", **kw):
        return channels.send(self.root, channel, "delete", "", {"target_id": target}, driver=self.fake, state=self.state,
                             at=kw.pop("at", TUE_1000), **kw)

    def refused_delete(self, check, **kw):
        with self.assertRaises(channels.SendRefused) as cm:
            self.delete(**kw)
        self.assertEqual(check, cm.exception.check, cm.exception.reason)
        self.assertEqual([], self.fake.calls, "a refusal never reaches the driver")
        return cm.exception

    def test_delete_is_a_kind_and_needs_a_persons_takedown_act(self):
        self.assertIn("delete", channels.KINDS)
        exc = self.refused_delete("kind rule")
        self.assertIn("takedown act", exc.reason)
        self.takedown_act(by="engine")
        self.refused_delete("kind rule")
        self.assertEqual(self.lines()[-1]["kind"], "delete")

    def test_a_take_down_calls_the_driver_with_the_sent_posts_url_and_marks_the_ledger(self):
        self.takedown_act()
        got = self.delete()
        self.assertEqual((got["kind"], got["id"]), ("delete", "r1#takedown"))
        (call,) = self.fake.calls
        self.assertEqual((call["kind"], call["target"], call["text"]), ("delete", self.URL, ""))
        with open(os.path.join(self.state, channels.LEDGER_FILE), encoding="utf-8") as f:
            ledger = json.load(f)["sends"]
        self.assertEqual(ledger["r1"]["state"], "sent", "the post stays on the ledger as sent")
        self.assertEqual(ledger["r1"]["taken_down"]["by"], "r1#takedown")
        self.assertEqual((ledger["r1#takedown"]["state"], ledger["r1#takedown"]["kind"]), ("sent", "delete"))
        self.assertEqual((self.lines()[-1]["outcome"], self.lines()[-1]["kind"]), ("sent", "delete"))

    def test_the_text_of_a_post_taken_down_is_never_sent_again(self):
        self.takedown_act()
        self.delete()
        self.fake.calls.clear()
        self.approve("r2")
        self.refused("dedupe", "reply", ref={"id": "r2"})

    def test_it_is_taken_down_once(self):
        self.takedown_act()
        self.delete()
        self.fake.calls.clear()
        self.refused_delete("dedupe")

    def test_only_our_own_sent_posts_on_their_own_channel(self):
        self.takedown_act("nothing-we-sent")
        exc = self.refused_delete("kind rule", target="nothing-we-sent")
        self.assertIn("our own sent post", exc.reason)
        self.takedown_act()
        exc = self.refused_delete("kind rule", channel="linkedin")
        self.assertIn("sent on X", exc.reason)
        with self.assertRaises(channels.SendRefused) as cm:
            channels.send(self.root, "x", "delete", "", {}, driver=self.fake, state=self.state, at=TUE_1000)
        self.assertEqual(cm.exception.check, "kind")

    def test_a_take_down_works_while_paused_and_outside_the_sending_hours(self):
        import switches
        switches.set_pause(self.root, True, state=self.state)
        self.takedown_act()
        self.delete(at=SAT_1000)
        self.assertEqual(len(self.fake.calls), 1)

    def test_a_failed_delete_is_recorded_and_can_be_tried_again(self):
        self.takedown_act()
        self.fake.fail = "platform said no"
        with self.assertRaises(channels.ChannelError):
            self.delete()
        self.assertEqual(self.lines()[-1]["outcome"], "failed")
        with open(os.path.join(self.state, channels.LEDGER_FILE), encoding="utf-8") as f:
            self.assertNotIn("taken_down", json.load(f)["sends"]["r1"])
        self.fake.fail = None
        self.delete()
        self.assertEqual(self.lines()[-1]["outcome"], "sent")

    def test_the_dashboards_take_down_is_one_act_then_the_delete(self):
        import control
        got = control.takedown("r1", by="Some Person", reason="a wrong figure", state_dir=self.state, driver=self.fake, at=TUE_1000)
        self.assertEqual((got["outcome"], got["url"], got["channel"]), ("taken down", self.URL, "x"))
        (act,) = [a for a in acts.list_acts(path=self.acts) if a["kind"] == "takedown"]
        self.assertEqual((act["by"], act["target"], act["outcome"], act["payload"]["reason"]), ("alpha", "r1", "applied", "a wrong figure"))
        again = control.takedown("r1", state_dir=self.state, driver=self.fake, at=TUE_1000)
        self.assertEqual((again["outcome"], again["check"]), ("refused", "dedupe"))
        with self.assertRaises(control.Refused):
            control.takedown("never-sent", state_dir=self.state, driver=self.fake)
        self.assertIn("/api/takedown", control.ACTIONS)

    def test_the_native_drivers_refuse_a_kind_they_do_not_know(self):
        import autopilot
        for driver in (autopilot.native_x_driver, autopilot.native_linkedin_driver):
            for kind in ("delete", "like", "repost", "quote"):
                with self.assertRaises(RuntimeError, msg=kind) as cm:
                    driver({"kind": kind, "text": "", "target": self.URL})
                self.assertIn(f"has no {kind}", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
