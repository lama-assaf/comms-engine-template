"""
gate_lint.py after decision 2026-11-07-vary-the-template.

- the honest limit: a `limit` field quoted verbatim from the post passes
  without the "What we do not claim" heading; a `limit` the post does not
  carry blocks; no limit and no heading still blocks; the heading still passes
- a question hook is no longer an edit
- `lint: shape`: hook form, opening and closing of a draft against the three
  pieces dated just before it in its stream; an edit when each of the three
  shares at least two of those with it, a pass when the draft varies, when
  fewer than three came before, and when no corpus is given (lint(item) alone)
"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import fixture_memory  # noqa: E402
import gate_lint  # noqa: E402

with open(os.path.join(HERE, "fixtures.json"), encoding="utf-8") as f:
    BASE = json.load(f)["base"]

TEMPLATE_POST = ("On 2 November a regulator did a thing.\n\nThe middle of the argument.\n\n"
                 "What we do not claim: that the layer runs.")


def piece(i, date, title="One thing holds. Another thing does not.", post=TEMPLATE_POST, stream=fixture_memory.ROOT_NAME):
    return {"id": f"Q-{i}", "stream": stream, "title": title, "post": post, "slot": {"date": date}}


def named(result, name):
    return {c["check"]: c for c in result["checks"]}[gate_lint.PREFIX + name]


class HonestLimit(fixture_memory.FixtureMemoryCase):
    def item(self, **kw):
        it = copy.deepcopy(BASE)
        it.update(kw)
        return it

    def test_own_words_limit_passes(self):
        post = "A wallet holds a credential.\n\nNone of this runs in a system today, and no date is set for it."
        r = gate_lint.lint(self.item(post=post, limit="None of this runs in a system today, and no date is set for it."))
        self.assertEqual(named(r, "what we do not claim")["result"], "pass")

    def test_limit_not_in_post_blocks(self):
        r = gate_lint.lint(self.item(post="A wallet holds a credential.", limit="Nothing here is running."))
        self.assertEqual(named(r, "what we do not claim")["result"], "block")

    def test_no_limit_no_heading_blocks(self):
        r = gate_lint.lint(self.item(post="A wallet holds a credential. That is all."))
        self.assertEqual(named(r, "what we do not claim")["result"], "block")

    def test_heading_still_passes(self):
        self.assertEqual(named(gate_lint.lint(self.item()), "what we do not claim")["result"], "pass")


class QuestionHook(fixture_memory.FixtureMemoryCase):
    def test_question_hook_passes(self):
        it = copy.deepcopy(BASE)
        it["title"] = "Which root does a company credential chain to, and who decides?"
        self.assertEqual(named(gate_lint.lint(it), "hook")["result"], "pass")


class Shape(fixture_memory.FixtureMemoryCase):
    PRIOR = [piece(1, "2026-11-01"), piece(2, "2026-11-03"), piece(3, "2026-11-05")]

    def test_same_template_is_an_edit(self):
        draft = piece(9, "2026-11-10", title="A key proves a sender. A credential proves an entity.")
        r = gate_lint.lint(draft, corpus=self.PRIOR + [draft])
        self.assertEqual(named(r, "shape")["result"], "edit")
        self.assertTrue(named(r, "shape")["line"])

    def test_varied_draft_passes(self):
        draft = piece(9, "2026-11-10", title="Who answers when an agent signs for a company?",
                      post="A treasurer approves a payment she never saw.\n\nThe middle.\n\n"
                           "None of this runs in a system today.")
        r = gate_lint.lint(draft, corpus=self.PRIOR + [draft])
        self.assertEqual(named(r, "shape")["result"], "pass")

    def test_fewer_than_three_before_passes(self):
        draft = piece(9, "2026-11-10")
        r = gate_lint.lint(draft, corpus=self.PRIOR[:2] + [draft])
        self.assertEqual(named(r, "shape")["result"], "pass")

    def test_other_streams_and_later_pieces_do_not_count(self):
        draft = piece(9, "2026-11-04")
        corpus = [piece(1, "2026-11-01"), piece(2, "2026-11-02", stream=fixture_memory.OTHER_NAME),
                  piece(3, "2026-11-03"), piece(4, "2026-11-20"), draft]
        self.assertEqual(named(gate_lint.lint(draft, corpus=corpus), "shape")["result"], "pass")

    def test_no_corpus_passes(self):
        self.assertEqual(named(gate_lint.lint(piece(9, "2026-11-10")), "shape")["result"], "pass")

    def test_shape_of(self):
        self.assertEqual(gate_lint.shape_of(piece(1, "2026-11-01")),
                         ("short declaratives", "dated news hook", "fixed heading", "theme-post", ""))
        self.assertEqual(gate_lint.shape_of(piece(1, "x", title="Why would a bank trust a PDF?",
                                                  post="A clerk opens a file.\n\nWe do not run this."))[:3],
                         ("question", "other", "own words"))
        self.assertEqual(gate_lint.shape_of(dict(piece(1, "x"), format="Observation"))[3], "theme-post",
                         "a note written before formats existed is a theme post")
        self.assertEqual(gate_lint.shape_of(dict(piece(1, "x"), format="x-thread", logic="L2"))[3:], ("x-thread", "L2"))

    def test_another_format_or_logic_is_what_varies_a_draft_now(self):
        """The shape is five things: hook form, opening, closing, format and logic. A draft that
        repeats the last three pieces in all but one still reads the same; one that changes the
        format and the logic does not, even with the same hook form and opening."""
        same = piece(9, "2026-11-10", title="A key proves a sender. A credential proves an entity.")
        thread = dict(same, format="x-thread", logic="L2")
        self.assertEqual(named(gate_lint.lint(thread, corpus=self.PRIOR + [thread]), "shape")["result"], "pass")
        only_format = dict(same, format="short-take")
        r = named(gate_lint.lint(only_format, corpus=self.PRIOR + [only_format]), "shape")
        self.assertEqual(r["result"], "edit", "one change in five is still the same piece")
        self.assertIn("format and logic", r["fix"])
        self.assertIn("short-take", r["line"])
        logic_only = [dict(p, logic="L1") for p in self.PRIOR]
        varied = dict(same, logic="L3", title="Who answers when an agent signs for a company?")
        self.assertEqual(named(gate_lint.lint(varied, corpus=logic_only + [varied]), "shape")["result"], "pass")

    def test_the_shape_check_is_an_edit_and_never_a_block(self):
        draft = piece(9, "2026-11-10")
        self.assertNotEqual(named(gate_lint.lint(draft, corpus=self.PRIOR + [draft]), "shape")["result"], "block")


if __name__ == "__main__":
    unittest.main()
