"""
The review switch: a mode per stream, channel and kind (`review` by default, `auto` by a
person's confirmed act), tighter than the stream's setup, recorded as a `switch` act, kept in
`state/switches.json` by the act applier and read live by `channels.send()`; the auto-reply
switch is the reply and comment modes; a pause per stream stops every send at once; and
`engage.py send-due` sends through `channels.send()` only while the reply mode is `auto`.

Every write driver is faked and the state directory is a temp one: no platform is called.
"""
import http.server
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import acts  # noqa: E402
import channels  # noqa: E402
import config  # noqa: E402
import control  # noqa: E402
import desk_sync  # noqa: E402
import engage  # noqa: E402
import memory  # noqa: E402
import switches  # noqa: E402
import views  # noqa: E402
from test_channels_send import CLEAN, SAT_1000, TUE_1000, Fake, SendBase  # noqa: E402

WHY = "Replies to peers on this theme are low risk and the checks still apply."


OLD_RULE = ("themes: Blog row created Published after audit and gate pass; LinkedIn and X teasers created Ready "
            "and posted on their date; facts: manual")


class SwitchBase(SendBase):
    def turn(self, value=True, stream=None, channel="X", reason=WHY, confirm=True, by="alpha"):
        return switches.change(stream or self.root, channel, value, by=by, reason=reason, confirm=confirm, state=self.state)

    def set(self, kind, mode="auto", stream=None, channel="X", confirm=True, **kw):
        return switches.set_mode(stream or self.root, channel, kind, mode, confirm=confirm, state=self.state, **kw)

    def autopilot(self, value="by switch"):
        """Rewrite the root stream's autopilot cell in the fixture registry, as `engine.py apply` would."""
        with open(memory.STREAMS_MD, encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(text.count(OLD_RULE), 1)
        with open(memory.STREAMS_MD, "w", encoding="utf-8") as f:
            f.write(text.replace(OLD_RULE, value))

    def switch_acts(self):
        return [a for a in acts.list_acts(path=self.acts) if a["kind"] == "switch"]


class Default(SwitchBase):
    def test_off_by_default_and_an_unapproved_reply_is_refused(self):
        self.assertFalse(channels.auto_reply_on(self.root, "x", self.state))
        self.assertFalse(os.path.exists(os.path.join(self.state, switches.FILE)))
        self.refused("kind rule", "reply")

    def test_switch_is_a_known_act_kind(self):
        self.assertIn("switch", acts.KINDS)

    def test_the_engine_json_default_counts_only_until_the_switch_is_changed(self):
        real = config.cfg
        key = f"channels.auto_reply.{self.root}.x"
        with mock.patch.object(config, "cfg", lambda k, d=None: True if k == key else real(k, d)):
            self.assertTrue(channels.auto_reply_on(self.root, "x", self.state))
            self.turn(False)
            self.assertFalse(channels.auto_reply_on(self.root, "x", self.state))


class Turning(SwitchBase):
    def test_on_needs_a_confirmation_and_records_no_act_without_it(self):
        got = self.turn(confirm=False)
        self.assertTrue(got["outcome"].startswith("refused: "))
        self.assertIn("confirmation", got["outcome"])
        self.assertEqual(self.switch_acts(), [])
        self.assertFalse(channels.auto_reply_on(self.root, "x", self.state))

    def test_a_written_reason_is_optional_as_it_is_for_an_approval(self):
        got = self.turn(reason=None)
        self.assertEqual((got["outcome"], got["reason"]), ("applied", ""))
        self.assertTrue(channels.auto_reply_on(self.root, "x", self.state))

    def test_on_is_a_switch_act_with_role_time_and_reason_and_lands_in_switches_json(self):
        got = self.turn(by="Some Person")
        self.assertEqual((got["outcome"], got["value"], got["by"]), ("applied", True, "alpha"))
        (act,) = self.switch_acts()
        self.assertEqual((act["outcome"], act["by"], act["target"]), ("applied", "alpha", f"{self.root}/x"))
        self.assertEqual(act["payload"], {"channel": "x", "value": True, "reason": WHY})
        self.assertTrue(act["at"])
        rec = switches.get(self.root, "X", self.state)
        self.assertEqual((rec["value"], rec["by"], rec["reason"], rec["act"], rec["at"]), (True, "alpha", WHY, act["id"], act["at"]))
        self.assertTrue(channels.auto_reply_on(self.root, "x", self.state))

    def test_off_needs_no_reason_and_a_change_takes_effect_on_the_next_send(self):
        self.turn()
        self.send("reply")                       # on: the unapproved reply goes out through the gate
        self.assertEqual(len(self.fake.calls), 1)
        got = self.turn(False, reason=None, confirm=False)
        self.assertEqual((got["outcome"], got["value"]), ("applied", False))
        self.fake.calls.clear()
        self.refused("kind rule", "reply", text=CLEAN + " Next.", ref={"id": "r2"})   # off: the very next send is refused
        self.assertEqual(len(self.switch_acts()), 2)
        self.assertFalse(switches.get(self.root, "x", self.state)["value"])

    def test_the_switch_is_per_channel(self):
        self.turn()
        self.assertTrue(channels.auto_reply_on(self.root, "x", self.state))
        self.assertFalse(channels.auto_reply_on(self.root, "linkedin", self.state))

    def test_on_does_not_skip_the_other_checks(self):
        self.turn()
        self.refused("guardrails", "reply", at=SAT_1000)
        self.refused("gate", "reply", text=f"{memory.stream(self.root)['name']} issues the credential today.", ref={"id": "r3"})

    def test_a_bad_value_stream_or_channel_is_an_error_not_a_guess(self):
        for args in ((self.root, "X", "yes"), ("nowhere", "X", True), (self.root, "fax", True)):
            with self.assertRaises(switches.SwitchError):
                switches.change(*args, reason=WHY, confirm=True, state=self.state)
        self.assertEqual(self.switch_acts(), [])


class Tightening(SwitchBase):
    def test_a_stream_streams_md_does_not_allow_cannot_be_turned_on(self):
        got = self.turn(stream=self.other)       # autopilot is `nothing` for the second stream
        self.assertTrue(got["outcome"].startswith("refused: "), got)
        (act,) = [a for a in acts.list_acts(path=self.acts) if a["kind"] == "switch"]
        self.assertTrue(act["outcome"].startswith("refused: "))
        self.assertIsNone(switches.get(self.other, "x", self.state))
        self.assertFalse(channels.auto_reply_on(self.other, "x", self.state))

    def test_a_stored_on_stops_counting_when_streams_md_stops_allowing_it(self):
        self.turn()
        with mock.patch.object(switches, "streams_allow", return_value=(False, "tightened")):
            self.assertFalse(channels.auto_reply_on(self.root, "x", self.state))
            self.refused("kind rule", "reply")
        self.assertTrue(channels.auto_reply_on(self.root, "x", self.state))

    def test_a_default_in_engine_json_cannot_loosen_it_either(self):
        real = config.cfg
        with mock.patch.object(config, "cfg", lambda k, d=None: True if k.startswith("channels.auto_reply.") else real(k, d)):
            self.assertTrue(channels.auto_reply_on(self.root, "x", self.state))
            self.assertFalse(channels.auto_reply_on(self.other, "x", self.state))

    def test_streams_md_can_keep_replies_manual_in_the_autopilot_cell(self):
        row = dict(memory.stream(self.root))
        row["autopilot"] += "; replies: manual"
        with mock.patch.object(memory, "stream", return_value=row):
            ok, why = switches.streams_allow(self.root, "x")
        self.assertFalse(ok)
        self.assertIn("manual", why)
        self.assertTrue(switches.streams_allow(self.root, "x")[0])

    def test_only_the_applier_writes_switches_json_and_a_refused_act_leaves_it_alone(self):
        self.turn(stream=self.other)
        self.assertFalse(os.path.exists(os.path.join(self.state, switches.FILE)))
        act = acts.record("switch", self.root, f"{self.root}/x", {"channel": "x", "value": "yes", "reason": ""},
                          by="alpha", path=self.acts)
        self.assertEqual(switches.apply_act(act, self.state, self.acts), "refused: not a switch act with a true or false value")
        self.assertFalse(os.path.exists(os.path.join(self.state, switches.FILE)))


class Modes(SwitchBase):
    """A mode per stream, channel and kind: review by default, auto by a confirmed act where the
    stream's setup allows it."""

    def test_every_kind_is_review_by_default(self):
        self.assertEqual(switches.KINDS, ("post", "reply", "comment", "like", "repost", "quote", "hold"))
        for kind in switches.KINDS:
            self.assertEqual(switches.mode(self.root, "x", kind, self.state), "review", kind)
            self.assertEqual(channels.mode(self.root, "X", kind, self.state), "review", kind)
        with self.assertRaises(switches.SwitchError):
            switches.mode(self.root, "x", "telegram-blast", self.state)

    def test_a_kind_other_than_a_reply_needs_the_autopilot_to_say_by_switch(self):
        got = self.set("post")
        self.assertTrue(got["outcome"].startswith("refused: "), got)
        self.assertIn("by switch", got["outcome"])
        (act,) = self.switch_acts()
        self.assertTrue(act["outcome"].startswith("refused: "), "the refusal is on the record")
        self.assertEqual(switches.mode(self.root, "x", "post", self.state), "review")
        self.assertEqual(self.set("reply")["outcome"], "applied", "a reply could always be switched under a rule")
        self.autopilot()
        got = self.set("post", by="Some Person")
        self.assertEqual((got["outcome"], got["mode"], got["by"]), ("applied", "auto", "alpha"))
        self.assertEqual(switches.mode(self.root, "x", "post", self.state), "auto")
        act = self.switch_acts()[-1]
        self.assertEqual((act["target"], act["payload"]), (f"{self.root}/x/post", {"channel": "x", "kind": "post", "mode": "auto", "reason": ""}))
        rec = switches.stored(self.root, "x", "post", self.state)
        self.assertEqual((rec["mode"], rec["by"], rec["act"], rec["at"]), ("auto", "alpha", act["id"], act["at"]))

    def test_auto_takes_one_confirmation_and_no_reason_and_review_takes_neither(self):
        self.autopilot()
        got = self.set("like", confirm=False)
        self.assertTrue(got["outcome"].startswith("refused: "))
        self.assertIn("confirmation", got["outcome"])
        self.assertEqual(self.switch_acts(), [])
        self.assertEqual(self.set("like")["outcome"], "applied")
        self.assertEqual(self.set("like", "review", confirm=False)["outcome"], "applied")
        self.assertEqual(switches.mode(self.root, "x", "like", self.state), "review")

    def test_a_mode_is_per_stream_channel_and_kind(self):
        self.autopilot()
        self.set("like")
        self.assertEqual(switches.mode(self.root, "x", "like", self.state), "auto")
        for channel, kind in (("x", "repost"), ("x", "post"), ("linkedin", "like")):
            self.assertEqual(switches.mode(self.root, channel, kind, self.state), "review", (channel, kind))

    def test_nothing_and_an_unset_owner_stay_the_hard_off(self):
        got = self.set("post", stream=self.other)
        self.assertTrue(got["outcome"].startswith("refused: "), got)
        self.autopilot("nothing")
        self.assertTrue(self.set("reply")["outcome"].startswith("refused: "))
        for kind in switches.KINDS:
            self.assertEqual(switches.mode(self.root, "x", kind, self.state), "review")

    def test_a_stored_auto_stops_counting_when_the_setup_stops_allowing_it(self):
        self.autopilot()
        self.set("post")
        self.assertEqual(switches.mode(self.root, "x", "post", self.state), "auto")
        with open(memory.STREAMS_MD, encoding="utf-8") as f:
            text = f.read()
        with open(memory.STREAMS_MD, "w", encoding="utf-8") as f:
            f.write(text.replace("| by switch |", "| nothing |"))
        self.assertEqual(switches.mode(self.root, "x", "post", self.state), "review")

    def test_the_setup_files_default_counts_until_a_person_changes_it(self):
        self.autopilot()
        real = config.cfg
        default = {"like": "auto", "repost": {"x": "auto", "linkedin": "review"}, "post": "sometimes"}
        with mock.patch.object(config, "cfg", lambda k, d=None: default if k == f"streams.{self.root}.review" else real(k, d)):
            self.assertEqual(switches.mode(self.root, "x", "like", self.state), "auto")
            self.assertEqual(switches.mode(self.root, "x", "repost", self.state), "auto")
            self.assertEqual(switches.mode(self.root, "linkedin", "repost", self.state), "review")
            self.assertEqual(switches.mode(self.root, "x", "post", self.state), "review", "a value that is not a mode is review")
            self.set("like", "review", confirm=False)
            self.assertEqual(switches.mode(self.root, "x", "like", self.state), "review")

    def test_the_auto_reply_switch_is_the_reply_and_comment_modes(self):
        self.turn()
        self.assertEqual(switches.mode(self.root, "x", "reply", self.state), "auto")
        self.assertEqual(switches.mode(self.root, "x", "comment", self.state), "auto")
        self.set("comment", "review", confirm=False)
        self.assertEqual(switches.mode(self.root, "x", "comment", self.state), "review")
        self.assertTrue(channels.auto_reply_on(self.root, "x", self.state), "the reply mode is what auto_reply_on reads")
        # a record written before modes existed still counts
        with open(os.path.join(self.state, switches.FILE), "w", encoding="utf-8") as f:
            json.dump({"switches": {f"{self.root}/x": {"stream": self.root, "channel": "x", "value": True}}}, f)
        self.assertEqual(switches.mode(self.root, "x", "comment", self.state), "auto")

    def test_presets_set_every_kind_on_every_channel(self):
        self.autopilot()
        self.assertTrue(switches.preset(self.root, "fully-automatic", state=self.state)[0]["outcome"].startswith("refused: "))
        done = switches.preset(self.root, "review-posts-only", confirm=True, state=self.state)
        self.assertTrue(done and all(r["outcome"] == "applied" for r in done), done)
        for channel in ("x", "linkedin"):
            self.assertEqual(switches.mode(self.root, channel, "post", self.state), "review")
            self.assertEqual(switches.mode(self.root, channel, "reply", self.state), "auto")
            self.assertEqual(switches.mode(self.root, channel, "like", self.state), "auto")
            self.assertEqual(switches.mode(self.root, channel, "hold", self.state), "review")
        entry = next(e for e in switches.policy(self.state) if e["stream"] == self.root)
        self.assertEqual(entry["preset"], "review-posts-only")
        back = switches.preset(self.root, "review-everything", state=self.state)
        self.assertTrue(all(r["outcome"] == "applied" for r in back), "tightening needs no confirmation")
        self.assertEqual(switches.preset(self.root, "review-everything", state=self.state), [], "nothing left to change")
        with self.assertRaises(switches.SwitchError):
            switches.preset(self.root, "yolo", confirm=True, state=self.state)

    def test_policy_rows_say_what_is_asked_what_is_in_force_and_why(self):
        self.set("post")
        entry = next(e for e in switches.policy(self.state) if e["stream"] == self.root)
        self.assertFalse(entry["by_switch"])
        x = next(c for c in entry["channels"] if c["channel"] == "x")
        post = next(k for k in x["kinds"] if k["kind"] == "post")
        self.assertEqual((post["mode"], post["allowed"]), ("review", False))
        self.assertIn("by switch", post["why"])
        other = next(e for e in switches.policy(self.state) if e["stream"] == self.other)
        self.assertEqual({k["mode"] for c in other["channels"] for k in c["kinds"]}, {"review"})


class Pause(SwitchBase):
    """A pause per stream stops every send at once, whatever was approved or switched."""

    def test_pause_takedown_and_setup_are_known_act_kinds(self):
        for kind in ("pause", "takedown", "setup"):
            self.assertIn(kind, acts.KINDS)

    def test_a_paused_stream_sends_nothing_and_resuming_needs_a_confirmation(self):
        self.approve("r1")
        got = switches.set_pause(self.root, True, by="Some Person", reason="a wrong claim went out", state=self.state)
        self.assertEqual((got["outcome"], got["by"]), ("applied", "alpha"))
        self.assertTrue(channels.paused(self.root, self.state))
        self.assertFalse(channels.paused(self.other, self.state), "a pause is per stream")
        exc = self.refused("pause", "reply")
        self.assertIn("paused", exc.reason)
        (act,) = [a for a in acts.list_acts(path=self.acts) if a["kind"] == "pause"]
        self.assertEqual((act["outcome"], act["payload"]["paused"], act["by"]), ("applied", True, "alpha"))
        self.assertTrue(switches.set_pause(self.root, False, state=self.state)["outcome"].startswith("refused: "))
        self.assertTrue(channels.paused(self.root, self.state))
        self.assertEqual(switches.set_pause(self.root, False, confirm=True, state=self.state)["outcome"], "applied")
        self.send("reply")
        self.assertEqual(len(self.fake.calls), 1)

    def test_a_pause_outranks_every_mode(self):
        self.turn()
        self.send("reply")
        switches.set_pause(self.root, True, state=self.state)
        self.fake.calls.clear()
        self.refused("pause", "reply", text=CLEAN + " Next.", ref={"id": "r2"})
        entry = next(e for e in switches.policy(self.state) if e["stream"] == self.root)
        self.assertTrue(entry["paused"])
        self.assertEqual(channels.CHECK_ORDER[0], "pause", "the pause is read before any other check")

    def test_a_bad_pause_is_an_error_and_an_odd_act_is_refused(self):
        with self.assertRaises(switches.SwitchError):
            switches.set_pause(self.root, "yes", state=self.state)
        with self.assertRaises(switches.SwitchError):
            switches.set_pause("nowhere", True, state=self.state)
        act = acts.record("pause", self.root, self.root, {"paused": "yes"}, by="alpha", path=self.acts)
        self.assertTrue(switches.apply_act(act, self.state, self.acts).startswith("refused: "))
        self.assertFalse(channels.paused(self.root, self.state))


class View(SwitchBase):
    def test_rows_show_value_who_when_and_why_and_what_streams_md_allows(self):
        rows = {(r["stream"], r["channel"]): r for r in switches.rows(self.state)}
        self.assertFalse(rows[(self.root, "x")]["on"])
        self.assertTrue(rows[(self.root, "x")]["allowed"])
        self.assertFalse(rows[(self.other, "x")]["allowed"])
        self.assertTrue(rows[(self.other, "x")]["why"])
        self.turn()
        row = {(r["stream"], r["channel"]): r for r in switches.rows(self.state)}[(self.root, "x")]
        self.assertEqual((row["on"], row["by"], row["reason"]), (True, "alpha", WHY))
        self.assertTrue(row["at"])


TARGET = "https://x.com/other/status/9"


class SendDue(SwitchBase):
    def setUp(self):
        super().setUp()
        self.name = memory.stream(self.root)["name"]
        self.p1 = {"finding_id": "F1", "theme": "#T", "platform": "X", "target_url": TARGET, "target_post": "9", "tier": "peer",
                   "draft_comment": CLEAN, "stream": self.name, "shape": "sharper question"}
        self.p2 = dict(self.p1, finding_id="F2", draft_comment="A relying party can check the issuer against the register.")
        self.write([self.p1, self.p2])

    def write(self, proposals):
        with open(os.path.join(self.state, "engagement.json"), "w", encoding="utf-8") as f:
            json.dump({"proposals": proposals}, f)

    def run_due(self, **kw):
        kw.setdefault("at", TUE_1000)
        return engage.send_due(self.state, **kw)

    def test_with_the_switch_off_nothing_is_sent_and_nothing_is_tried(self):
        rows = self.run_due(live=True, driver=self.fake)
        self.assertEqual([r["outcome"] for r in rows], ["skipped", "skipped"])
        self.assertIn("switch is off", rows[0]["reason"])
        self.assertEqual((self.fake.calls, self.lines()), ([], []))

    def test_dry_runs_every_check_with_a_fake_driver_and_writes_nothing(self):
        self.turn()
        rows = self.run_due()
        self.assertEqual([r["outcome"] for r in rows], ["sent", "sent"])
        self.assertTrue(rows[0]["url"].startswith("dry-run://"))
        self.assertEqual(self.lines(), [])
        self.assertFalse(os.path.exists(os.path.join(self.state, channels.LEDGER_FILE)))
        with open(os.path.join(self.state, "engagement.json"), encoding="utf-8") as f:
            self.assertNotIn("acts", json.load(f))
        self.assertEqual(self.fake.calls, [])

    def test_dry_still_refuses_what_the_gate_or_the_hours_refuse(self):
        self.turn()
        self.write([dict(self.p1, draft_comment=f"{self.name} issues the credential today.")])
        self.assertEqual([(r["outcome"], r["check"]) for r in self.run_due()], [("refused", "gate")])
        self.write([self.p1])
        self.assertEqual([(r["outcome"], r["check"]) for r in self.run_due(at=SAT_1000)], [("refused", "guardrails")])

    def test_live_goes_through_channels_send_with_the_driver_and_records_the_engagement(self):
        self.turn()
        rows = self.run_due(live=True, driver=self.fake)
        self.assertEqual([r["outcome"] for r in rows], ["sent", "sent"])
        self.assertEqual([c["kind"] for c in self.fake.calls], ["reply", "reply"])
        self.assertEqual([l["outcome"] for l in self.lines()], ["sent", "sent"])
        recorded = engage.load(self.state)["acts"]
        self.assertEqual([(a["tier"], a["shape"], a["target_post"]) for a in recorded][0], ("peer", "sharper question", "9"))

    def test_a_second_run_does_not_send_the_same_text_again(self):
        self.turn()
        self.run_due(live=True, driver=self.fake)
        rows = self.run_due(live=True, driver=self.fake)
        self.assertEqual([(r["outcome"], r["check"]) for r in rows], [("refused", "dedupe")] * 2)
        self.assertEqual(len(self.fake.calls), 2)

    def test_the_per_run_limit_and_the_desks_decisions_are_honoured(self):
        self.turn()
        rows = self.run_due(live=True, driver=self.fake, limit=1)
        self.assertEqual([r["outcome"] for r in rows], ["sent", "skipped"])
        self.assertIn("limit", rows[1]["reason"])
        with open(os.path.join(self.state, "decisions.json"), "w") as f:
            json.dump({desk_sync.proposal_id(self.p2): {"status": "rejected"}}, f)
        rows = self.run_due(live=True, driver=Fake())
        self.assertEqual(rows[1]["outcome"], "skipped")
        self.assertIn("desk", rows[1]["reason"])

    def test_turning_it_off_stops_the_next_run(self):
        self.turn()
        self.assertEqual(self.run_due(live=True, driver=self.fake, limit=1)[0]["outcome"], "sent")
        self.turn(False, reason=None, confirm=False)
        self.assertEqual({r["outcome"] for r in self.run_due(live=True, driver=self.fake)}, {"skipped"})
        self.assertEqual(len(self.fake.calls), 1)

    def test_it_is_in_no_scheduled_job(self):
        """`engage.py send-due`, the reply sender, is run by a person or not at all. (The reactions
        sender, `reactions.py send-due --scheduled`, is in the engagement chain and dry unless
        `reactions.live` is set: tests/test_reactions.py.)"""
        with open(os.path.join(os.path.dirname(HERE), "engine.json"), encoding="utf-8") as f:
            doc = json.load(f)

        def argvs(node):
            if isinstance(node, list) and node and all(isinstance(x, str) for x in node):
                yield node
            elif isinstance(node, (list, dict)):
                for child in (node.values() if isinstance(node, dict) else node):
                    yield from argvs(child)

        for argv in argvs({"jobs": doc["jobs"], "workflows": doc["params"]["workflows"]}):
            joined = " ".join(argv)
            self.assertFalse("engage.py" in joined and "send-due" in joined, joined)
        for name in os.listdir(os.path.join(os.path.dirname(HERE), "schedule")):
            path = os.path.join(os.path.dirname(HERE), "schedule", name)
            if os.path.isfile(path):
                with open(path, encoding="utf-8", errors="ignore") as f:
                    self.assertNotIn("send-due", f.read(), name)


class Endpoint(SwitchBase):
    token = "tok"

    def setUp(self):
        super().setUp()
        for target, name in ((control, "STATE"), (views, "STATE")):
            p = mock.patch.object(target, name, self.state)
            p.start()
            self.addCleanup(p.stop)
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), control.make_handler(0, self.token))
        self.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = control.make_handler(self.port, self.token)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def call(self, body, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/switch", data=json.dumps(body).encode(),
                                     headers=headers or {}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_needs_the_token_and_the_origin(self):
        body = {"stream": self.root, "channel": "x", "value": True, "reason": WHY, "confirm": True}
        self.assertEqual(self.call(body)[0], 403)
        self.assertEqual(self.call(body, {"X-Control-Token": self.token, "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.switch_acts(), [])

    def test_on_off_and_the_refusals_over_http(self):
        h = {"X-Control-Token": self.token}
        code, got = self.call({"stream": self.root, "channel": "x", "value": True, "reason": WHY}, h)
        self.assertEqual(code, 200)
        self.assertTrue(got["switch"]["outcome"].startswith("refused: "))       # no confirmation
        code, got = self.call({"stream": self.root, "channel": "x", "value": True, "reason": WHY, "confirm": True, "by": "alpha"}, h)
        self.assertEqual((code, got["switch"]["outcome"], got["switch"]["by"]), (200, "applied", "alpha"))
        snap = {(r["stream"], r["channel"]): r for r in views.accounts()["switches"]}
        self.assertTrue(snap[(self.root, "x")]["on"])
        code, got = self.call({"stream": self.root, "channel": "x", "value": False}, h)
        self.assertEqual(got["switch"]["outcome"], "applied")
        self.assertFalse({(r["stream"], r["channel"]): r for r in views.accounts()["switches"]}[(self.root, "x")]["on"])
        self.assertEqual(self.call({"stream": self.root, "channel": "x", "value": "on"}, h)[0], 400)
        self.assertEqual(self.call({"stream": "nowhere", "channel": "x", "value": False}, h)[0], 400)


if __name__ == "__main__":
    unittest.main()
