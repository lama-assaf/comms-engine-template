#!/usr/bin/env python3
"""
`scripts/theme_words.py`, each theme's licence in plain words for the people
who decide.

1. **Facts.** Every theme with its grade, its rule and a hash of the two, and
   whether its words are missing, out of date or current.
2. **The check.** A draft is refused for an unknown theme, a hash that is not
   the current rule's, a missing or over-long field, a file name, section mark,
   argument or finding code or backtick, a block from the gate's denylist or
   status-word check, and when the denylist cannot be read.
3. **Publish and staleness.** Published words read as current until the rule
   behind them changes, then as out of date.

Every file here is a temp file; nothing reads live state.

  python3 -m unittest discover plugins/comms-engine/tests
"""
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import gate_lint  # noqa: E402
import memory  # noqa: E402
import theme_words  # noqa: E402

THEMES_MD = """# themes

| hashtag | what it is | why it is different | fact it links back to | partner tags | intro post |
|---|---|---|---|---|---|
| #ExampleTheme | An example. | Ours. | C-acme-1 | — | not yet |
| #HeldTheme | Another idea. | Also ours. | — | — | not yet |

## licence and layer

| hashtag | layer | licence | logics | licence basis |
|---|---|---|---|---|
| #ExampleTheme | core services | licensed | L1 | Shipped and checkable. |
| #HeldTheme | initiatives | held | L3 | Nothing shipped; argue the standard only (L3, `status.md` §2). |

## theme status log

- 2026-09-07 - seeded.
"""

PASS = lambda item, slug=None: {"check": "x", "result": "pass", "line": "", "fix": ""}  # noqa: E731


def words(**kw):
    w = {"now": "We may argue the general idea freely.", "not": "We never say it runs today.",
         "why": "Nothing behind it has shipped yet.", "next": "When the first piece ships."}
    w.update(kw)
    return w


class ThemeWords(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.md = os.path.join(self.dir, "themes.md")
        with open(self.md, "w", encoding="utf-8") as f:
            f.write(THEMES_MD)
        for p in (mock.patch.object(memory, "THEMES_MD", self.md),
                  mock.patch.object(memory, "denylist", lambda stream=None: ["Umbra Capital"]),
                  mock.patch.object(theme_words, "DIR", os.path.join(self.dir, "words")),
                  mock.patch.object(gate_lint, "check_stealth", PASS),
                  mock.patch.object(gate_lint, "check_status_words", PASS),
                  mock.patch.object(gate_lint, "resolve_slug", lambda item: None)):
            p.start()
            self.addCleanup(p.stop)
        self.f = theme_words.facts()
        self.h = {t["tag"]: t["hash"] for t in self.f["themes"]}

    def draft(self, **per_tag):
        return {"themes": {tag: dict(w, hash=self.h[tag]) for tag, w in per_tag.items()}}

    def test_facts_name_every_theme_its_rule_and_what_is_missing(self):
        self.assertEqual([t["tag"] for t in self.f["themes"]], ["#ExampleTheme", "#HeldTheme"])
        held = self.f["themes"][1]
        self.assertEqual((held["licence"], held["words"]), ("held", "missing"))
        self.assertIn("argue the standard only", held["rule"])

    def test_a_good_draft_publishes_and_reads_current(self):
        self.assertEqual(theme_words.publish(self.draft(**{"#HeldTheme": words()}), self.f), [])
        cur = theme_words.current()
        self.assertTrue(cur["#HeldTheme"]["current"])
        self.assertEqual(cur["#HeldTheme"]["licence"], "held")
        self.assertEqual([t["words"] for t in theme_words.facts()["themes"]], ["missing", "current"])

    def test_words_go_out_of_date_when_the_rule_changes(self):
        theme_words.publish(self.draft(**{"#HeldTheme": words()}), self.f)
        with open(self.md, "w", encoding="utf-8") as f:
            f.write(THEMES_MD.replace("| #HeldTheme | initiatives | held |", "| #HeldTheme | initiatives | licensed |"))
        self.assertFalse(theme_words.current()["#HeldTheme"]["current"])
        self.assertEqual(theme_words.facts()["themes"][1]["words"], "out of date")

    def test_refusals(self):
        cases = (
            ({"#NotATheme": dict(words(), hash="x")}, "not a theme"),
            ({"#HeldTheme": dict(words(), hash="old")}, "not the current rule's"),
            ({"#HeldTheme": dict(words(why=""), hash=None)}, "`why` is needed"),
            ({"#HeldTheme": dict(words(now="x" * 261), hash=None)}, "at most 260"),
            ({"#HeldTheme": dict(words(why="As status.md says."), hash=None)}, "a file name"),
            ({"#HeldTheme": dict(words(why="Per section §2."), hash=None)}, "a section mark"),
            ({"#HeldTheme": dict(words(now="Argue L3 only."), hash=None)}, "an argument code"),
            ({"#HeldTheme": dict(words(now="See F1."), hash=None)}, "a finding code"),
            ({"#HeldTheme": dict(words(now="Use `this`."), hash=None)}, "a backtick"),
        )
        for themes, why in cases:
            with self.subTest(why=why):
                for e in themes.values():
                    if e.get("hash") is None:
                        e["hash"] = self.h["#HeldTheme"]
                problems = theme_words.check({"themes": themes}, self.f)
                self.assertTrue(any(why in p for p in problems), problems)
        self.assertEqual(theme_words.check({}, self.f), ["the draft has no `themes` (an object of hashtag to its words)"])

    def test_the_gate_and_the_denylist_stop_what_they_would_stop_in_a_post(self):
        block = lambda item, slug=None: {"check": "stealth", "result": "block", "line": "a name", "fix": "Cut it."}  # noqa: E731
        with mock.patch.object(gate_lint, "check_stealth", block):
            self.assertTrue(any("stealth" in p for p in theme_words.check(self.draft(**{"#HeldTheme": words()}), self.f)))

        def unreadable(stream=None):
            raise OSError("no file")
        with mock.patch.object(memory, "denylist", unreadable):
            problems = theme_words.publish(self.draft(**{"#HeldTheme": words()}), self.f)
        self.assertTrue(any("denylist cannot be read" in p for p in problems))
        self.assertFalse(os.path.exists(os.path.join(theme_words.DIR, "latest.json")), "nothing published")


if __name__ == "__main__":
    unittest.main()
