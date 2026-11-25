#!/usr/bin/env python3
"""
`gate_lint.lint_text` - the text-level gate a reply or comment meets. The
predicates are the ones `lint(item)` calls; these fixtures show the reply side
blocks a stealth term, a status word and an uncited capability sentence, passes
a clean reply, reads @mentions as partner tags, and fails closed without the
private companion.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import fixture_memory  # noqa: E402
import gate_lint  # noqa: E402

STREAM = fixture_memory.ROOT_NAME
CLEAN = "A relying party can check the identifier against the standard."


def by_name(result):
    return {c["check"].replace(gate_lint.PREFIX, ""): c for c in result["checks"]}


class LintText(fixture_memory.FixtureMemoryCase):
    def run_text(self, text, cites=None, stream=STREAM):
        return gate_lint.lint_text(stream, "X", text, cites)

    def test_shape_matches_lint(self):
        r = self.run_text(CLEAN)
        self.assertEqual({"verdict", "checks", "channel"}, set(r))
        for c in r["checks"]:
            self.assertEqual(["check", "fix", "line", "result"], sorted(c))
        self.assertEqual("pass", r["verdict"], [c for c in r["checks"] if c["result"] != "pass"])

    def test_stealth_term_blocks(self):
        r = self.run_text("Ruritania is where this is heading.")
        self.assertEqual("block", r["verdict"])
        self.assertEqual("block", by_name(r)["stealth"]["result"])
        self.assertTrue(by_name(r)["stealth"]["line"])

    def test_status_word_blocks(self):
        with open(self.fixture.path("gate-rules.json"), "w", encoding="utf-8") as f:
            json.dump({"status_words": [{"pattern": r"\bcertified\b", "fix": "never certified"}]}, f)
        r = self.run_text("We are certified for this.")
        self.assertEqual("block", by_name(r)["status words"]["result"])
        self.assertEqual("block", r["verdict"])

    def test_uncited_capability_sentence_blocks(self):
        r = self.run_text("Acme operates the issuance platform today.")
        self.assertEqual("block", by_name(r)["cites"]["result"])
        self.assertEqual("block", r["verdict"])

    def test_evidenced_cite_clears_capability_sentence(self):
        r = self.run_text("Acme operates the issuance platform today.", cites=["C-acme-5"])
        self.assertEqual("pass", by_name(r)["cites"]["result"])
        self.assertEqual("pass", r["verdict"])

    def test_non_evidenced_or_unknown_cite_blocks(self):
        for cites in (["C-acme-3"], ["C-acme-999"]):
            r = self.run_text("Acme operates the issuance platform today.", cites=cites)
            self.assertEqual("block", by_name(r)["cites"]["result"], cites)

    def test_mentions_are_partner_tags(self):
        self.assertEqual("pass", by_name(self.run_text("Thanks @betalabs"))["partner tags"]["result"])
        r = self.run_text("Thanks @randomperson for the thread.")
        self.assertEqual("block", by_name(r)["partner tags"]["result"])
        r = self.run_text("Thanks @epsilon for this.")
        self.assertEqual("block", by_name(r)["partner tags"]["result"])

    def test_unknown_stream_blocks(self):
        r = self.run_text(CLEAN, stream="Nowhere")
        self.assertEqual("block", by_name(r)["stream"]["result"])

    def test_proposal_reads_cites(self):
        p = {"stream": STREAM, "platform": "X", "draft_comment": "Acme operates the issuance platform today.",
             "cites": ["C-acme-5"]}
        self.assertEqual("pass", gate_lint.lint_proposal(p)["verdict"])
        p.pop("cites")
        self.assertEqual("block", gate_lint.lint_proposal(p)["verdict"])


class LintTextWithoutCompanion(fixture_memory.FixtureMemoryCase):
    PRIVATE = False

    def test_fails_closed(self):
        r = gate_lint.lint_text(STREAM, "X", CLEAN)
        self.assertEqual("block", by_name(r)["stealth"]["result"])
        self.assertEqual("block", r["verdict"])


if __name__ == "__main__":
    unittest.main()
