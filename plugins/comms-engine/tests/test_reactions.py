"""
reactions.py: the plan of likes and reposts, and the sender that makes them.

- the plan reads what the engine already read (the listening files, the `@watched` pass, the
  standing monitors' replies to our own account) and keeps a candidate as a post id, a tier and
  a theme: never a handle, never the post's words; a stranger's post is not a candidate at all
- a cleared partner's post earns a like and a repost, a watched account's a like, a reply to us
  a like; a post that fails the target checks is kept as refused, with the reason
- candidates are ranked by tier, then by the themes the last assessment found warm; a plan run
  twice queues nothing twice and forgets nothing that was done
- send-due is dry by default: every check, a driver that sends nothing, nothing written; live,
  it goes through channels.send(), waits between sends, stops at the per-run limit, marks each
  candidate and records each reaction in the engagement ledger
- a like on X ends `waiting` whatever the mode, and one click sends it; an undone like is shown
- the engagement chain plans and then runs the scheduled sender, which is dry unless
  `reactions.live` is set
"""
import datetime as dt
import json
import os
import sys
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import acts  # noqa: E402
import brandfile  # noqa: E402
import channels  # noqa: E402
import config  # noqa: E402
import control  # noqa: E402
import engage  # noqa: E402
import memory  # noqa: E402
import reactions  # noqa: E402
import state_check  # noqa: E402
from test_channels_send import TUE_1000  # noqa: E402
from test_switches import SwitchBase  # noqa: E402

NOW = TUE_1000
P1, P2, P3, P4, P5 = (f"190000000000000000{i}" for i in range(1, 6))


class Base(SwitchBase):
    def setUp(self):
        super().setUp()
        with open(memory.STREAMS_MD, encoding="utf-8") as f:
            bdoc = brandfile.from_streams_md(f.read(), config.brand())
        bdoc["streams"][self.root]["reactions_per_day"] = {"x": {"like": 5, "repost": 2}}
        brandfile.write(bdoc)
        self.partner = next(row["x"] for row in memory.taggable_handles(self.root).values() if row.get("x")).lstrip("@")
        self.own = channels._handle(dict(channels.stream_channels(self.root))["x"])
        self.name = memory.stream(self.root)["name"]
        self.stealth = memory.denylist(self.root)[0]
        with open(os.path.join(self.state, "watchlist.json"), "w", encoding="utf-8") as f:
            json.dump({"watched": [{"handle": "@watched_one"}], "dismissed": []}, f)
        created = (NOW - dt.timedelta(hours=5)).isoformat()
        items = [
            {"id": P1, "source": "x", "author": self.partner, "text": "The standard is the public part.", "created_at": created,
             "_matched_term": "#SecondTheme", "url": f"https://x.com/{self.partner}/status/{P1}"},
            {"id": P2, "source": "x", "author": "watched_one", "text": "A register is not a root.", "created_at": created,
             "_matched_term": "@watched"},
            {"id": P3, "source": "x", "author": "a_stranger", "text": "Wallets everywhere.", "created_at": created,
             "_matched_term": "#ExampleTheme"},
            {"id": P4, "source": "x", "author": self.partner, "text": f"{self.stealth} joins the round.", "created_at": created,
             "_matched_term": "#ExampleTheme"},
        ]
        with open(os.path.join(self.state, "listening-2026-11-10.json"), "w", encoding="utf-8") as f:
            json.dump({"items": items}, f)
        os.makedirs(os.path.join(self.state, "x-stream"))
        with open(os.path.join(self.state, "x-stream", "2026-11-10.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": P5, "handle": "someone_else", "text": "Thank you, this helped.", "is_reply": True,
                                "in_reply_to": self.own, "received_at": created, "rule_tag": f"{self.root}:mentions"}) + "\n")
        with open(os.path.join(self.state, "signals.json"), "w", encoding="utf-8") as f:
            json.dump({"stream": self.name, "warmest_themes": {"ranked": [{"theme": "#SecondTheme"}, {"theme": "#ExampleTheme"}]}}, f)

    def plan(self, **kw):
        return reactions.plan(self.root, self.state, now=NOW, **kw)

    def by_id(self, out=None):
        return {c["id"]: c for c in (out or reactions.load(self.state))["candidates"]}

    def due(self, **kw):
        kw.setdefault("at", NOW)
        kw.setdefault("sleep", lambda s: self.slept.append(s))
        return reactions.send_due(self.state, **kw)

    slept: list = []


class Plan(Base):
    def test_candidates_are_a_post_id_a_tier_and_a_theme_and_never_a_handle(self):
        out = self.plan()
        cands = self.by_id(out)
        self.assertEqual(set(cands), {f"like:{P1}", f"repost:{P1}", f"like:{P2}", f"like:{P4}", f"repost:{P4}", f"like:{P5}"},
                         "a stranger's post is not a candidate at all")
        self.assertEqual((cands[f"like:{P1}"]["tier"], cands[f"like:{P1}"]["theme"], cands[f"like:{P1}"]["source"]),
                         ("institution", "#SecondTheme", "listening"))
        self.assertEqual((cands[f"like:{P2}"]["tier"], cands[f"like:{P2}"]["source"]), ("peer", "watchlist"))
        self.assertEqual((cands[f"like:{P5}"]["tier"], cands[f"like:{P5}"]["source"]), ("other", "replies"))
        self.assertNotIn(f"repost:{P2}", cands, "a repost is for a cleared partner's post")
        with open(reactions.path(self.state), encoding="utf-8") as f:
            blob = f.read()
        for secret in (self.partner, "watched_one", "someone_else", "@", "The standard is the public part", "x.com/"):
            self.assertNotIn(secret.lower(), blob.lower())
        self.assertEqual(set(cands[f"like:{P1}"]), {"id", "kind", "channel", "target_id", "tier", "theme", "source", "stream",
                                                    "planned_at", "state", "reason", "rank"})
        self.assertEqual(state_check.check(self.state)[0], [], "every candidate names its stream")

    def test_a_post_that_fails_the_target_checks_is_kept_as_refused_with_the_reason(self):
        cands = self.by_id(self.plan())
        bad = cands[f"like:{P4}"]
        self.assertEqual((bad["state"], bad["check"]), ("refused", "target"))
        self.assertIn("stealth", bad["reason"])
        self.assertNotIn(self.stealth.lower(), json.dumps(bad).lower(), "the reason never repeats the term it refused")
        self.assertEqual(cands[f"like:{P1}"]["state"], "queued")

    def test_ranked_by_tier_then_by_the_warm_themes(self):
        order = [c["id"] for c in sorted(self.plan()["candidates"], key=lambda c: c["rank"])]
        self.assertEqual(order[0], f"like:{P1}", "a partner's post on the warmest theme first")
        self.assertLess(order.index(f"repost:{P1}"), order.index(f"like:{P2}"), "tier outranks the kind")
        self.assertLess(order.index(f"like:{P2}"), order.index(f"like:{P5}"))

    def test_a_second_plan_queues_nothing_twice_and_keeps_what_was_done(self):
        self.plan()
        data = reactions.load(self.state)
        self.by_id(data)[f"like:{P1}"].update(state="done", done_at="2026-11-10T10:05:00+00:00")
        reactions.save(data, self.state)
        again = self.by_id(self.plan())
        self.assertEqual(len(again), 6)
        self.assertEqual(again[f"like:{P1}"]["state"], "done")

    def test_a_dry_plan_writes_nothing_and_an_old_post_is_not_read(self):
        self.plan(write=False)
        self.assertFalse(os.path.exists(reactions.path(self.state)))
        late = NOW + dt.timedelta(days=10)
        self.assertEqual(reactions.read_posts(self.state, now=late), {})

    def test_the_file_refuses_to_hold_a_handle(self):
        with self.assertRaises(ValueError):
            reactions.save({"candidates": [{"id": "like:1", "author": "@someone"}]}, self.state)


class Send(Base):
    def setUp(self):
        super().setUp()
        self.slept = []
        self.autopilot()
        self.plan()

    def test_dry_is_the_default_and_writes_nothing(self):
        before = open(reactions.path(self.state), encoding="utf-8").read()
        self.set("repost")
        rows = self.due()
        by = {r["id"]: r for r in rows}
        self.assertEqual(by[f"repost:{P1}"]["outcome"], "sent", "on auto, inside the cap: it would go")
        self.assertEqual(by[f"like:{P1}"]["outcome"], "waiting")
        self.assertEqual(open(reactions.path(self.state), encoding="utf-8").read(), before)
        self.assertFalse(os.path.exists(os.path.join(self.state, channels.LEDGER_FILE)))
        self.assertEqual((self.fake.calls, self.slept), ([], []))

    def test_live_sends_through_channels_send_spaced_out_and_marks_each_candidate(self):
        self.set("repost")
        rows = self.due(live=True, driver=self.fake)
        sent = [r for r in rows if r["outcome"] == "sent"]
        self.assertEqual([r["id"] for r in sent], [f"repost:{P1}"])
        (call,) = self.fake.calls
        self.assertEqual((call["kind"], call["ref"]["target_id"], call["text"]), ("repost", P1, ""))
        cands = self.by_id()
        self.assertEqual((cands[f"repost:{P1}"]["state"], cands[f"repost:{P1}"]["reason"]), ("done", ""))
        self.assertTrue(cands[f"repost:{P1}"]["done_at"])
        self.assertEqual(cands[f"like:{P1}"]["state"], "waiting")
        self.assertIn("person's click", cands[f"like:{P1}"]["reason"])
        self.assertEqual([ln["outcome"] for ln in self.lines() if ln["kind"] == "repost"], ["sent"])
        (act,) = engage.load(self.state)["acts"]
        self.assertEqual((act["kind"], act["shape"], act["tier"], act["target_post"], act["theme"]),
                         ("repost", "repost", "institution", P1, "#SecondTheme"))
        self.assertIn("institution / repost", engage.ledger(self.state))
        again = self.due(live=True, driver=self.fake)
        self.assertEqual([r for r in again if r["outcome"] == "sent"], [], "what was done is not tried again")

    def test_the_per_run_limit_and_the_wait_between_two_sends(self):
        for kind, post in (("like", P1), ("like", P2), ("like", P5)):
            a = acts.record("decision", self.root, f"{kind}:{post}", {"decision": "approve"},
                            base=channels.reaction_hash("x", kind, post), path=self.acts)
            acts.applied(a["id"], path=self.acts)
        rows = self.due(live=True, driver=self.fake, limit=2)
        self.assertEqual(sum(1 for r in rows if r["outcome"] == "sent"), 2)
        self.assertIn("per-run limit of 2", next(r["reason"] for r in rows if r["outcome"] == "skipped"))
        self.assertEqual(self.slept, [45.0], "one wait between two sends, none before the first")

    def test_a_like_on_x_waits_for_a_click_whatever_the_mode_and_one_click_sends_it(self):
        self.set("like")
        rows = self.due(live=True, driver=self.fake)
        self.assertEqual({r["outcome"] for r in rows if r["kind"] == "like"}, {"waiting"})
        self.assertEqual(self.fake.calls, [])
        got = reactions.click(f"like:{P1}", by="Some Person", state=self.state, driver=self.fake, at=NOW)
        self.assertEqual(got["outcome"], "sent")
        (act,) = [a for a in acts.list_acts(path=self.acts) if a["kind"] == "decision" and a["target"] == f"like:{P1}"]
        self.assertEqual((act["by"], act["outcome"], act["base"]), ("alpha", "applied", channels.reaction_hash("x", "like", P1)))
        self.assertEqual(self.by_id()[f"like:{P1}"]["state"], "done")
        with self.assertRaises(KeyError):
            reactions.click(f"like:{P1}", state=self.state, driver=self.fake, at=NOW)
        with self.assertRaises(KeyError):
            reactions.click("like:never-planned", state=self.state, driver=self.fake, at=NOW)

    def test_a_post_that_left_the_listening_files_is_refused_not_guessed(self):
        os.remove(os.path.join(self.state, "listening-2026-11-10.json"))
        a = acts.record("decision", self.root, f"like:{P1}", {"decision": "approve"}, base=channels.reaction_hash("x", "like", P1), path=self.acts)
        acts.applied(a["id"], path=self.acts)
        rows = {r["id"]: r for r in self.due(live=True, driver=self.fake)}
        self.assertEqual((rows[f"like:{P1}"]["outcome"], rows[f"like:{P1}"]["check"]), ("refused", "target"))
        self.assertIn("no longer in the listening files", rows[f"like:{P1}"]["reason"])
        self.assertEqual(rows[f"like:{P5}"]["outcome"], "waiting", "the reply is still in the monitors' file")

    def test_the_summary_groups_by_state_and_shows_an_undone_like(self):
        reactions.click(f"like:{P1}", state=self.state, driver=self.fake, at=NOW)
        got = control.takedown(f"like:{P1}", state_dir=self.state, driver=self.fake, at=NOW)
        self.assertEqual(got["outcome"], "taken down")
        self.assertEqual((self.fake.calls[-1]["kind"], self.fake.calls[-1]["target_kind"]), ("delete", "like"))
        s = reactions.summary(self.state)
        self.assertEqual([c["id"] for c in s["done"]], [f"like:{P1}"])
        self.assertTrue(s["done"][0]["undone"])
        self.assertEqual({c["id"] for c in s["refused"]}, {f"like:{P4}", f"repost:{P4}"})
        self.assertTrue(all(c["reason"] for c in s["refused"]))
        self.assertEqual({c["id"] for c in s["queued"]}, {f"repost:{P1}", f"like:{P2}", f"like:{P5}"})


class TheJob(Base):
    def test_the_engagement_chain_plans_then_runs_the_scheduled_sender(self):
        with open(os.path.join(ENGINE, "engine.json"), encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc["params"]["chains"]["engagement"], ["engage", "community", "react"])
        react = doc["params"]["workflows"]["react"]
        self.assertEqual([s["run"] for s in react["steps"]],
                         [["engine", "reactions", "plan"],
                          ["engine", "reactions", "send-due", "--scheduled"],
                          ["engine", "state_check"]])
        self.assertTrue(react["optional"], "a reaction that cannot be planned never holds the reply drafts")
        self.assertFalse([s for s in react["steps"] if "model" in s], "no model decides a like")
        r = doc["params"]["reactions"]
        self.assertEqual((r["job"], r["live"], r["per_run"]), ("engagement", False, 3))

    def test_scheduled_is_dry_unless_the_setting_says_live(self):
        self.autopilot()
        self.plan()
        self.set("repost")
        seen = []
        real = reactions.send_due

        def spy(state=None, live=False, **kw):
            seen.append(live)
            return real(state, live=False, **kw)

        with mock.patch.object(reactions, "send_due", spy), mock.patch("builtins.print"):
            self.assertEqual(reactions.main(["--state", self.state, "send-due", "--scheduled"]), 0)
            real_cfg = config.cfg
            with mock.patch.object(config, "cfg", lambda k, d=None, **kw: True if k == "reactions.live" else real_cfg(k, d, **kw)):
                reactions.main(["--state", self.state, "send-due", "--scheduled"])
            reactions.main(["--state", self.state, "send-due"])
        self.assertEqual(seen, [False, True, False])

    def test_engage_record_takes_a_reaction_and_refuses_a_kind_it_does_not_know(self):
        act = engage.record("like:1", "#T", "X", "1", "peer", "like", "", self.name, self.state, kind="like")
        self.assertEqual(act["kind"], "like")
        plain = engage.record("Q-1", "#T", "X", "2", "peer", "sharper question", "9", self.name, self.state)
        self.assertNotIn("kind", plain, "a comment is recorded as it always was")
        with self.assertRaises(ValueError):
            engage.record("x", "#T", "X", "3", "peer", "poke", "", self.name, self.state, kind="poke")
        with self.assertRaises(ValueError):
            engage.record("x", "#T", "X", "@someone", "peer", "like", "", self.name, self.state, kind="like")


if __name__ == "__main__":
    import unittest
    unittest.main()
