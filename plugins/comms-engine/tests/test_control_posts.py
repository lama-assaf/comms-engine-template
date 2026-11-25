#!/usr/bin/env python3
"""
The control page's calendar acts on posts (`scripts/control.py`): a team post written there
(`/api/new-post`) and a date change before the send (`/api/schedule`).

1. A new post is gated by the text-level gate first: a `block` writes nothing. Otherwise it is
   one note at status Idea, `drafted_by: team`, with its text on the one channel, and an act
   with the role; it is not scheduled and not sent.
2. It is approved like any draft once gated: only its own channel is scheduled.
3. A date change moves the note, and the lifecycle of the post and its scheduled channels, within
   the guardrails; it is refused once a channel of it is sent, and nothing moves on a refusal.
4. The website's feed lists only the articles marked live, from the views and from
   `engine.py export-published`.

Fakes only: a temp vault and state directory on the fixture memory. Nothing is sent.
"""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import json  # noqa: E402

import acts  # noqa: E402
import control  # noqa: E402
import engine  # noqa: E402
import desk_acts  # noqa: E402
import fixture_memory  # noqa: E402
import gate_lint  # noqa: E402
import lifecycle  # noqa: E402
import repo  # noqa: E402
import views  # noqa: E402

DAY = "2026-11-12"


def ok_guard(item, date):
    return True, ""


class Case(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="control-posts-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cal = os.path.join(self.tmp, "Content", "Calendar")
        saved = (repo.CAL, repo.STATE)
        repo.CAL, repo.STATE = self.cal, self.tmp
        self.addCleanup(lambda: (setattr(repo, "CAL", saved[0]), setattr(repo, "STATE", saved[1])))
        p = mock.patch.object(control, "STATE", self.tmp)
        p.start()
        self.addCleanup(p.stop)
        self.apath = os.path.join(self.tmp, "acts.jsonl")
        self.lpath = os.path.join(self.tmp, "lifecycle.jsonl")

    def new(self, **kw):
        args = dict(stream=fixture_memory.ROOT, channel="x", date=DAY, text="A team sentence, said plainly.",
                    title="Team note", by="Some Person")
        args.update(kw)
        return control.new_post(**args)

    def approve(self, eid):
        repo.set_fields(eid, {"gate": {"verdict": "pass"}})
        items = {i["id"]: i for i in repo.load_items()}
        made = desk_acts.turn_into_acts([{"id": eid, "status": "approved", "by": "alpha", "at": "t"}], [], [], [],
                                        items, {}, self.tmp, guard=ok_guard)
        self.assertEqual("applied", made[0]["outcome"], made)
        return items[eid]


class NewPost(Case):
    def test_a_new_post_is_one_team_note_at_idea_and_nothing_moves(self):
        got = self.new()
        self.assertTrue(got["id"].startswith("T-2026-11-12-team-note-"))
        self.assertIn(got["gate"], ("pass", "pass-with-edits"))
        item = {i["id"]: i for i in repo.load_items()}[got["id"]]
        self.assertEqual((item["teaser_x"], item["teaser_linkedin"], item["post"]),
                         ("A team sentence, said plainly.", "", ""))
        self.assertEqual((item["drafted_by"], item["alpha_status"], item["slot"]["date"], item["stream"]),
                         (repo.TEAM_BY, "proposed", DAY, fixture_memory.ROOT_NAME))
        self.assertEqual({}, item["gate"], "the gatekeeper gates it like any draft")
        fm, _ = repo.parse_note(os.path.join(self.cal, "Team note.md"))
        self.assertEqual("Idea", fm["status"])
        (act,) = acts.list_acts(path=self.apath)
        self.assertEqual((act["kind"], act["by"], act["outcome"]), ("new-post", "alpha", "applied"))
        self.assertFalse(os.path.exists(self.lpath))
        self.assertNotEqual(got["id"], self.new(title="Team note two")["id"])

    def test_refusals_write_nothing(self):
        for kw, why in (({"text": " "}, "empty"), ({"channel": "blog"}, "channel"), ({"date": "soon"}, "not a date"),
                        ({"stream": "umbra"}, "not a stream")):
            with self.assertRaises(control.Refused) as cm:
                self.new(**kw)
            self.assertIn(why, str(cm.exception), kw)
        blocked = {"verdict": "block", "checks": [{"check": "lint: stealth", "result": "block", "fix": "a held term"}]}
        with mock.patch.object(gate_lint, "lint_text", return_value=blocked):
            with self.assertRaises(control.Refused) as cm:
                self.new()
        self.assertIn("the gate blocks it: lint: stealth: a held term", str(cm.exception))
        self.assertFalse(os.path.exists(self.cal) and os.listdir(self.cal))
        self.new()
        with self.assertRaises(control.Refused) as cm:
            self.new()
        self.assertIn("already called", str(cm.exception))

    def test_approved_like_any_draft_only_its_channel_is_scheduled(self):
        eid = self.new(channel="linkedin", text="A team sentence for LinkedIn readers.")["id"]
        self.approve(eid)
        self.assertEqual("scheduled", lifecycle.state(f"{eid}:linkedin", self.lpath))
        self.assertEqual("draft", lifecycle.state(f"{eid}:x", self.lpath))


    def test_an_approval_writes_approved_onto_the_note(self):
        """Regression: an approval scheduled the post but left the note `proposed`, so publish.py
        refused the item and the desk mirror showed it undecided."""
        eid = self.new()["id"]
        self.approve(eid)
        self.assertEqual({i["id"]: i for i in repo.load_items()}[eid]["alpha_status"], "approved")


class Schedule(Case):
    def setUp(self):
        super().setUp()
        self.eid = self.new()["id"]

    def test_before_approval_only_the_note_moves(self):
        got = control.schedule_post(self.eid, "2026-11-14", "alpha", guard=ok_guard)
        self.assertEqual((got["date"], got["from"], got["moved"]), ("2026-11-14", DAY, []))
        self.assertEqual("2026-11-14", {i["id"]: i for i in repo.load_items()}[self.eid]["slot"]["date"])
        act = [a for a in acts.list_acts(path=self.apath) if a["kind"] == "schedule"][0]
        self.assertEqual((act["outcome"], act["payload"]["date"]), ("applied", "2026-11-14"))

    def test_after_approval_the_lifecycle_moves_with_the_note(self):
        self.approve(self.eid)
        got = control.schedule_post(self.eid, "2026-11-16", "alpha", guard=ok_guard)
        self.assertEqual(sorted(got["moved"]), [self.eid, f"{self.eid}:x"])
        self.assertEqual("2026-11-16", lifecycle.current(f"{self.eid}:x", self.lpath)["date"])
        with self.assertRaises(control.Refused) as cm:
            control.schedule_post(self.eid, "2026-11-17", "alpha", guard=lambda i, d: (False, "a weekend"))
        self.assertIn("a weekend", str(cm.exception))
        self.assertEqual("2026-11-16", {i["id"]: i for i in repo.load_items()}[self.eid]["slot"]["date"],
                         "nothing moves on a refusal")

    def test_refused_once_sent_and_for_no_change(self):
        self.approve(self.eid)
        lifecycle.sent(f"{self.eid}:x", {"id": f"{self.eid}:x", "sent_at": "2026-11-12T09:00:00Z"}, path=self.lpath)
        with self.assertRaises(control.Refused) as cm:
            control.schedule_post(self.eid, "2026-11-20", "alpha", guard=ok_guard)
        self.assertIn("already sent", str(cm.exception))
        self.assertEqual(DAY, {i["id"]: i for i in repo.load_items()}[self.eid]["slot"]["date"])
        with self.assertRaises(control.Refused):
            control.schedule_post(self.eid, DAY, "alpha", guard=ok_guard)
        with self.assertRaises(control.Refused):
            control.schedule_post(self.eid, "next week", "alpha", guard=ok_guard)
        self.assertTrue(dt.date.fromisoformat(DAY))
        # regression: the page read only the item's own id, which stays scheduled, so a sent post
        # showed "Scheduled" and still offered a new day
        self.assertEqual("sent", views.post_acts(self.tmp)[self.eid]["state"])


class Published(Case):
    def test_only_articles_marked_live_are_in_the_feed(self):
        repo.write_item({"id": "Q-1", "title": "Piece one", "theme": "#ExampleTheme", "stream": fixture_memory.ROOT_NAME,
                         "post": "The article, in full.", "teaser_x": "One sentence. #ExampleTheme",
                         "slot": {"date": DAY}, "tags": ["#ExampleTheme"], "excerpt": "The claim."}, "Idea")
        repo.write_item({"id": "Q-2", "title": "Piece two", "theme": "#ExampleTheme", "stream": fixture_memory.ROOT_NAME,
                         "post": "Another article.", "slot": {"date": DAY}}, "Idea")
        self.approve("Q-1")
        self.approve("Q-2")
        self.assertEqual([], views.published_posts(DAY, state_dir=self.tmp)["posts"])
        got = control.blog_live("Q-1", "alpha", webhook=lambda: "skipped")
        self.assertEqual("applied", got["outcome"])
        feed = views.published_posts(DAY, state_dir=self.tmp)
        (post,) = feed["posts"]
        self.assertEqual((post["id"], post["slug"], post["url"], post["body"], post["category"], post["topics"]),
                         ("Q-1", "piece-one", repo.post_url("piece-one"), "The article, in full.", "ExampleTheme",
                          ["ExampleTheme"]))
        self.assertTrue(post["published_at"])
        out = os.path.join(self.tmp, "published.json")
        self.assertEqual(0, engine.export_published(out, state_dir=self.tmp))
        with open(out, encoding="utf-8") as f:
            self.assertEqual(["Q-1"], [p["id"] for p in json.load(f)["posts"]])


if __name__ == "__main__":
    unittest.main()
