#!/usr/bin/env python3
"""
`scripts/views.py`, every view of the engine computed once from the record.

1. **The registry.** Every view has a name, `get` answers each by name and
   refuses an unknown one plainly, and `snapshot` carries every view with the
   stream and the day. One view that cannot be read is listed in `errors` and
   leaves the others standing.
2. **Read-only.** Building every view writes nothing: the state folder is the
   same before and after.
3. **Handles and suggestions.** A handle in any of its forms; authors seen on a
   theme at least twice, not monitored, watched or dismissed, ranked by how
   often they were seen.
4. **The command line.** No name lists the views; a name prints that view as
   JSON; an unknown name is refused.

  python3 -m unittest discover plugins/comms-engine/tests
"""
import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import views  # noqa: E402

NAMES = ["genome", "story", "posts", "calendar", "themes", "accounts", "suggested",
         "listening", "replies", "claims", "learning", "engine", "setup", "policy", "reactions", "reviews"]


class Registry(unittest.TestCase):
    def test_every_view_has_a_name_in_page_order(self):
        self.assertEqual(list(views.VIEWS), NAMES)

    def test_an_unknown_view_is_refused_plainly(self):
        with self.assertRaises(KeyError) as e:
            views.get("nothing")
        self.assertIn("the views are: genome, story", str(e.exception))

    def test_one_broken_view_never_blanks_the_others(self):
        def broken(today):
            raise OSError("unreadable")
        with mock.patch.dict(views.VIEWS, {"claims": broken, "learning": lambda today: {"rows": []}}):
            snap = views.snapshot(["claims", "learning"])
        self.assertIsNone(snap["claims"])
        self.assertEqual(snap["learning"], {"rows": []})
        self.assertEqual(snap["errors"], ["claims: unreadable"])
        for key in ("built_at", "stream", "today"):
            self.assertIn(key, snap)

    def test_the_snapshot_is_json_and_writes_nothing(self):
        def tree():
            out = {}
            for root, _, files in os.walk(views.STATE):
                for f in files:
                    full = os.path.join(root, f)
                    out[full] = os.stat(full).st_mtime_ns
            return out
        before = tree()
        snap = views.snapshot()
        json.dumps(snap, default=str)
        self.assertEqual(tree(), before, "building the views writes nothing")
        for name in NAMES:
            self.assertIn(name, snap)


class Handles(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(views.norm_handle("@StandardsOrg"), "standardsorg")
        self.assertEqual(views.norm_handle("StandardsOrg"), "standardsorg")
        self.assertEqual(views.norm_handle("see @Some_Body today"), "some_body")
        self.assertEqual(views.norm_handle("collect", cell=True), "", "a status in a handles.md cell is no handle")
        self.assertEqual(views.norm_handle("@acme_hq", cell=True), "acme_hq")
        self.assertEqual(views.norm_handle(""), "")


class Suggestions(unittest.TestCase):
    def item(self, author, theme="#ExampleTheme", relevance=0.5, source="x", n=0):
        return {"id": f"{author}-{theme}-{n}", "author": author, "author_name": author.title(), "theme": theme,
                "source": source, "followers": 100 + n, "url": f"https://x.com/{author}/status/{n}",
                "text": "on theme", "created_at": "2026-11-05T10:00:00+0000",
                "prescore": {"relevance": relevance, "engagement": 3}}

    def test_seen_twice_on_a_theme_and_not_monitored(self):
        items = [self.item("bank", n=1), self.item("bank", "#SecondTheme", n=2), self.item("bank", n=3),
                 self.item("once"),
                 self.item("monitored", n=1), self.item("monitored", n=2),
                 self.item("watched", n=1), self.item("watched", n=2),
                 self.item("dismissed", n=1), self.item("dismissed", n=2),
                 self.item("offtheme", relevance=0, n=1), self.item("offtheme", relevance=0, n=2),
                 self.item("mention", "@mentions", n=1), self.item("mention", "@mentions", n=2),
                 self.item("second", n=1), self.item("second", n=2)]
        wl = {"watched": [{"handle": "@watched"}], "dismissed": [{"handle": "@dismissed"}]}
        rows = views.suggested(items, known={"monitored"}, wl=wl)
        self.assertEqual([r["handle"] for r in rows], ["@bank", "@second"])
        self.assertEqual(rows[0]["hits"], 3)
        self.assertEqual(rows[0]["themes"], ["#ExampleTheme", "#SecondTheme"])
        self.assertLessEqual(len(rows[0]["samples"]), 3)


class CommandLine(unittest.TestCase):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = views.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_no_name_lists_the_views(self):
        code, out, _ = self.run_main()
        self.assertEqual(code, 0)
        for name in NAMES:
            self.assertIn(name, out)

    def test_a_name_prints_that_view(self):
        with mock.patch.dict(views.VIEWS, {"claims": lambda today: {"register": 3}}):
            code, out, _ = self.run_main("claims")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["claims"], {"register": 3})

    def test_an_unknown_name_is_refused(self):
        code, _, err = self.run_main("nothing")
        self.assertEqual(code, 2)
        self.assertIn("no view called nothing", err)


class Standing(unittest.TestCase):
    """Where a post stands, in the words the control page shows (2026-11-10)."""

    def item(self, **kw):
        base = {"id": "Q-1", "title": "A hook", "post": "p", "teaser_x": "x", "teaser_linkedin": "l",
                "gate": {"verdict": "pass", "checks": []}}
        base.update(kw)
        return base

    def place(self, item, status="proposed", edit=None, argument=None):
        return views.standing(item, status, edit, views.edit_state(item, edit), argument)

    def test_a_posted_post_says_posted(self):
        self.assertEqual(self.place(self.item(published_to=["X"]))["label"], "Posted")

    def test_a_blocked_post_quotes_the_line(self):
        it = self.item(gate={"verdict": "block", "checks": [{"check": "lint: status words", "result": "block", "line": "certified"}]})
        s = self.place(it)
        self.assertEqual((s["key"], s["label"]), ("needs-you", "Blocked by a check"))
        self.assertIn("certified", s["note"])

    def test_proposed_asks_for_the_hook_until_it_is_confirmed(self):
        self.assertEqual(self.place(self.item())["label"], "Confirm the hook")
        self.assertEqual(self.place(self.item(), argument={"hook": "A hook"})["label"], "Ready to approve")
        self.assertEqual(self.place(self.item(), argument={"hook": "An old hook"})["label"], "Confirm the hook")

    def test_an_edit_whose_note_moved_is_a_conflict(self):
        it = self.item()
        fresh = {"at": "t", "title": "A hook", "base_hash": views.repo.base_hash(it)}
        self.assertEqual(views.edit_state(it, fresh), "pending")
        self.assertEqual(self.place(it, edit=dict(fresh, base_hash="0" * 64))["label"], "Pick a version")

    def test_other_states_read_plainly(self):
        self.assertEqual(self.place(self.item(), "rewrite")["label"], "Being rewritten")
        self.assertEqual(self.place(self.item(), "held")["label"], "On hold")
        self.assertEqual(self.place(self.item(), "approved")["key"], "approved")


class OpenReplies(unittest.TestCase):
    def test_a_reply_decided_on_the_desk_leaves_the_page(self):
        p1, p2 = {"finding_id": "F1", "author": "a"}, {"finding_id": "F2", "author": "b"}
        files = {"engagement.json": {"proposals": [p1, p2]}, "decisions.json": {"C-F1-a": {"status": "approved"}}}
        with mock.patch.object(views, "load_json", lambda path, d: files.get(os.path.basename(path), d)), \
                mock.patch.object(views, "heard_text", lambda: {}):
            r = views.replies()
        self.assertEqual([p["finding_id"] for p in r["proposals"]], ["F2"])
        self.assertEqual(r["done"], 1)


if __name__ == "__main__":
    unittest.main()
