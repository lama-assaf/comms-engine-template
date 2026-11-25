"""
review.py: the reviewers return findings, code checks them and stamps the verdict.

- a review two reviewers agree on, every claim on a current row whose words it quotes,
  passes and is stamped for the hash of the text; a text that changes after has no stamp
- a sentence quoted that the text does not carry, a sentence left unjudged, a claim with no
  cite, a cite the item does not list, a row that is superseded or uncorroborated, words that
  are not in the row, a row said not to support the sentence: each blocks, naming the sentence
- a present-tense capability sentence must be read as a claim and rest on its OWN evidenced
  cite: an evidenced cite elsewhere in the item clears nothing, and neither does a reviewer
  who calls it not a claim; a statistic needs a cite of its own
- two reviewers who differ on a sentence block the item; one reviewer alone is stamped but is
  not enough to go out without a person
- the reviewer writes nothing: its definition holds no Edit and its output has no stamp
- `apply` reads the two replies, writes each verdict where the item lives and logs the gate

The fixture memory, a temp vault and queue; no model and no process.
"""
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import fixture_memory  # noqa: E402
import gate_lint  # noqa: E402
import repo  # noqa: E402
import review  # noqa: E402

with open(os.path.join(HERE, "fixtures.json"), encoding="utf-8") as f:
    BASE = json.load(f)["base"]

CAPABILITY = "Acme operates a demonstrable issuance platform."
ROW_5 = "operates a demonstrable issuance platform"            # C-acme-5, evidenced
ROW_3 = "Two trade outlets report a regulator reading"         # C-acme-3, asserted
ROW_4 = "identifier governed by a public standard"             # C-acme-4, evidenced


def findings(item, claims=None, skip=(), reviewer="first", checks=None):
    """Findings that judge every sentence of `item`: not a claim unless `claims` names it,
    as `{part of the sentence: (cite, rests_on, supported)}`."""
    rows = []
    for field, s in review.sentences(item):
        if any(part in s for part in skip):
            continue
        row = {"field": field, "text": s, "claim": False}
        for part, (cite, rests_on, supported) in (claims or {}).items():
            if part in s:
                row.update({"claim": True, "cite": cite, "rests_on": rests_on, "supported": supported, "why": "as the row says"})
        rows.append(row)
    return {"id": item["id"], "sentences": rows, "checks": checks or [], "note": "Clean on the facts.", "reviewer": reviewer}


def with_line(line, cites=("C-acme-4",)):
    """The base item with one more sentence in the post, ahead of the honest limit."""
    item = copy.deepcopy(BASE)
    head, sep, tail = item["post"].rpartition("\n\n")
    item["post"] = f"{head}\n\n{line}{sep}{tail}"
    item["cites"] = list(cites)
    return item


class Case(fixture_memory.FixtureMemoryCase):
    def gate(self, item, first, second=None):
        return review.review(item, first, second)

    def problems(self, item, first, second=None):
        gate = self.gate(item, first, second)
        return gate["verdict"], " | ".join(gate["review"]["problems"])


class Passing(Case):
    def test_two_reviewers_who_agree_pass_and_the_stamp_is_keyed_by_the_text(self):
        item = copy.deepcopy(BASE)
        gate = self.gate(item, findings(item), findings(item, reviewer="second"))
        self.assertEqual(gate["verdict"], "pass", gate["review"]["problems"])
        stamp = gate["review"]
        self.assertEqual((stamp["verdict"], stamp["reviewers"], stamp["text_hash"]), ("pass", ["first", "second"], repo.base_hash(item)))
        self.assertEqual(stamp["sentences"], len(review.sentences(item)))
        self.assertEqual((gate["reviewed_by"], gate["reviewed_at"]), ("review.py", stamp["at"]))
        names = [c["check"] for c in gate["checks"]]
        self.assertIn("lint: stealth", names, "the deterministic gate ran again on the same text")
        self.assertIn("review: claims", names)
        self.assertIn("review: agreement", names)
        item["gate"] = gate
        self.assertEqual(review.approvable(item), (True, ""))
        item["post"] += " One more sentence."
        self.assertIsNone(review.current(item), "the stamp says nothing about a text that changed")
        self.assertIn("no review stamp", review.approvable(item)[1])

    def test_a_claim_on_its_own_row_with_the_rows_own_words_passes(self):
        item = with_line(CAPABILITY, cites=("C-acme-4", "C-acme-5"))
        claims = {"operates a demonstrable": ("C-acme-5", ROW_5, True)}
        gate = self.gate(item, findings(item, claims), findings(item, claims, reviewer="second"))
        self.assertEqual(gate["verdict"], "pass", gate["review"]["problems"])
        self.assertEqual(gate["review"]["claims"], 1)

    def test_one_reviewer_is_stamped_but_is_not_enough_to_go_out_without_a_person(self):
        item = copy.deepcopy(BASE)
        item["gate"] = self.gate(item, findings(item))
        self.assertEqual(item["gate"]["verdict"], "pass")
        ok, why = review.approvable(item)
        self.assertFalse(ok)
        self.assertIn("two who agree", why)

    def test_a_verdict_written_any_other_way_does_not_count(self):
        item = copy.deepcopy(BASE)
        item["gate"] = {"verdict": "pass", "reviewed_by": "gatekeeper", "reviewed_at": "2026-11-13T07:00:00+00:00"}
        self.assertFalse(review.approvable(item)[0])
        item["gate"] = {"verdict": "pass", "reviewed_by": "gatekeeper",
                        "review": {"text_hash": repo.base_hash(item), "verdict": "pass", "reviewers": ["a", "b"]}}
        self.assertFalse(review.approvable(item)[0], "a stamp is review.py's or it is nothing")


class Blocking(Case):
    def test_a_sentence_the_text_does_not_carry_and_a_sentence_left_unjudged(self):
        item = copy.deepcopy(BASE)
        f = findings(item)
        f["sentences"].append({"field": "post", "text": "Acme is fully certified.", "claim": False})
        verdict, why = self.problems(item, f)
        self.assertEqual(verdict, "block")
        self.assertIn("quotes a sentence the post does not carry", why)
        verdict, why = self.problems(item, findings(item, skip=("Europe is building wallets",)))
        self.assertEqual(verdict, "block")
        self.assertIn("did not judge (post): 'Europe is building wallets.'", why)
        verdict, why = self.problems(item, {"id": item["id"]})
        self.assertIn("returned no sentences", why)

    def test_a_claim_needs_a_cite_the_item_lists_on_a_current_row(self):
        line = "Two trade outlets report a regulator reading the specification."
        cases = (
            ((None, "", True), ("C-acme-4", "C-acme-3"), "a claim with no cite"),
            (("C-acme-3", ROW_3, True), ("C-acme-4",), "which the item's `cites` does not list"),
            (("C-acme-99", ROW_3, True), ("C-acme-4", "C-acme-99"), "C-acme-99"),
            (("C-acme-8", "A second jurisdiction is reading", True), ("C-acme-4", "C-acme-8"), "C-acme-8"),
            (("C-acme-6", "four vetted members", True), ("C-acme-4", "C-acme-6"), "C-acme-6"),
            (("C-acme-3", "a regulator has approved the specification", True), ("C-acme-4", "C-acme-3"), "are not in row C-acme-3"),
            (("C-acme-3", "Two", True), ("C-acme-4", "C-acme-3"), "are not in row C-acme-3"),
            (("C-acme-3", ROW_3, False), ("C-acme-4", "C-acme-3"), "row C-acme-3 does not support it"),
        )
        for claim, cites, why in cases:
            item = with_line(line, cites=cites)
            verdict, said = self.problems(item, findings(item, {"Two trade outlets": claim}))
            self.assertEqual(verdict, "block", (claim, said))
            self.assertIn(why, said)
            self.assertIn("Two trade outlets report", said, "the sentence is named")
        item = with_line(line, cites=("C-acme-4", "C-acme-3"))
        self.assertEqual(self.gate(item, findings(item, {"Two trade outlets": ("C-acme-3", ROW_3, True)}))["review"]["verdict"], "pass")

    def test_a_capability_sentence_rests_on_its_own_evidenced_cite(self):
        item = with_line(CAPABILITY, cites=("C-acme-4", "C-acme-5", "C-acme-3"))
        self.assertNotEqual(gate_lint.lint(item)["verdict"], "block", "the item-level check is satisfied: an evidenced cite is listed")
        verdict, why = self.problems(item, findings(item))
        self.assertEqual(verdict, "block")
        self.assertIn("capability sentence the reviewer did not read as a claim", why)
        verdict, why = self.problems(item, findings(item, {"operates a demonstrable": ("C-acme-3", ROW_3, True)}))
        self.assertEqual(verdict, "block")
        self.assertIn("whose own cite is not at grade evidenced", why)
        other = {"operates a demonstrable": ("C-acme-3", ROW_3, True), "An identifier governed": ("C-acme-4", ROW_4, True)}
        verdict, why = self.problems(item, findings(item, other))
        self.assertEqual(verdict, "block", "an evidenced cite on another sentence clears nothing")
        self.assertEqual(self.gate(item, findings(item, {"operates a demonstrable": ("C-acme-5", ROW_5, True)}))["review"]["verdict"], "pass")

    def test_a_statistic_needs_a_cite_of_its_own(self):
        item = with_line("Adoption grew 40% across the registries.")
        verdict, why = self.problems(item, findings(item))
        self.assertEqual(verdict, "block")
        self.assertIn("a statistic with no cite of its own", why)

    def test_the_reviewers_own_checks_count_and_a_malformed_one_blocks(self):
        item = copy.deepcopy(BASE)
        edit = self.gate(item, findings(item, checks=[{"check": "names", "result": "edit", "line": "x", "fix": "spell the body's name in full"}]))
        self.assertEqual(edit["verdict"], "pass-with-edits")
        block = self.gate(item, findings(item, checks=[{"check": "dates", "result": "block", "line": "in March", "fix": "cut the date"}]))
        self.assertEqual(block["verdict"], "block")
        self.assertIn("review: dates", [c["check"] for c in block["checks"] if c["result"] == "block"])
        bad = self.gate(item, findings(item, checks=[{"check": "dates", "result": "fine"}]))
        self.assertEqual(bad["verdict"], "block")

    def test_a_block_from_the_lint_stands_whatever_the_review_says(self):
        item = copy.deepcopy(BASE)
        item["post"] = item["post"].split("What we do not claim")[0].strip()
        gate = self.gate(item, findings(item), findings(item, reviewer="second"))
        self.assertEqual((gate["review"]["verdict"], gate["verdict"]), ("pass", "block"))
        item["gate"] = gate
        self.assertFalse(review.approvable(item)[0])


class HouseStyle(Case):
    """What a reviewer says under `register` is advice: kept for the writer and a person, never part of the verdict."""

    def test_house_style_is_kept_as_advice_and_never_moves_the_verdict(self):
        item = copy.deepcopy(BASE)
        style = [{"check": "register", "result": "edit", "line": item["title"], "fix": "hook: 19 words, cut it to one of the house patterns"}]
        even_block = [{"check": "register", "result": "block", "line": "x", "fix": "tag line: a second hashtag"}]
        gate = self.gate(item, findings(item, checks=style), findings(item, reviewer="second", checks=even_block))
        self.assertEqual(gate["verdict"], "pass", gate["review"]["problems"])
        self.assertEqual([s["fix"] for s in gate["style"]], ["hook: 19 words, cut it to one of the house patterns", "tag line: a second hashtag"])
        entry = next(c for c in gate["checks"] if c["check"] == "review: register")
        self.assertEqual(entry["result"], "pass")
        self.assertIn("as advice", entry["fix"])
        item["gate"] = gate
        self.assertTrue(review.approvable(item)[0], "advice does not keep a draft from going out where a person switched that on")
        self.assertEqual(self.gate(item, findings(item))["style"], [])


class TwoReviewers(Case):
    def test_a_disagreement_on_a_sentence_blocks(self):
        line = "Two trade outlets report a regulator reading the specification."
        item = with_line(line, cites=("C-acme-4", "C-acme-3"))
        a = findings(item, {"Two trade outlets": ("C-acme-3", ROW_3, True)})
        b = findings(item, reviewer="second")
        self.assertEqual(self.gate(item, a)["review"]["verdict"], "pass")
        gate = self.gate(item, a, b)
        self.assertEqual(gate["verdict"], "block")
        agreement = next(c for c in gate["checks"] if c["check"] == "review: agreement")
        self.assertEqual(agreement["result"], "block")
        self.assertIn("one reviewer reads it as a claim and the other does not", agreement["fix"])
        self.assertIn("Two trade outlets", agreement["fix"])

    def test_a_block_by_either_reviewer_blocks(self):
        item = copy.deepcopy(BASE)
        b = findings(item, reviewer="second", checks=[{"check": "names", "result": "block", "line": "x", "fix": "cut the name"}])
        gate = self.gate(item, findings(item), b)
        self.assertEqual(gate["verdict"], "block")
        self.assertIn("review (second): names", [c["check"] for c in gate["checks"]])
        self.assertIn("one reviewer blocks the item and the other does not", " ".join(gate["review"]["problems"]))


class Apply(Case):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="review-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = (repo.CAL, repo.STATE)
        repo.CAL, repo.STATE = os.path.join(self.tmp, "Content", "Calendar"), self.tmp
        self.addCleanup(lambda: (setattr(repo, "CAL", saved[0]), setattr(repo, "STATE", saved[1])))
        self.item = dict(copy.deepcopy(BASE), id="Q-1", alpha_status="proposed")
        self.other = dict(with_line("Adoption grew 40% across the registries."), id="Q-2", alpha_status="proposed")
        with open(os.path.join(self.tmp, "queue.json"), "w", encoding="utf-8") as f:
            json.dump([self.item, self.other], f)

    def write(self, name, doc):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        return path

    def test_apply_writes_each_verdict_where_the_item_lives(self):
        a = self.write("a.json", {"items": [findings(self.item), findings(self.other)], "reviewer": "gatekeeper"})
        b = self.write("b.json", {"outputs": {"items": [findings(self.item)]}})  # a run record carries the reply as outputs
        results = review.apply(a, b)
        self.assertEqual({k: v["verdict"] for k, v in results.items()}, {"Q-1": "pass", "Q-2": "block"})
        self.assertIn("did not judge", " ".join(results["Q-2"]["problems"]), "an item the second reviewer left out is unread by it")
        items = gate_lint.items_by_id()
        self.assertEqual(items["Q-1"]["gate"]["review"]["reviewers"], ["gatekeeper", "second"])
        self.assertTrue(review.approvable(items["Q-1"])[0])
        self.assertFalse(review.approvable(items["Q-2"])[0])
        self.assertIn("review.py: 1 pass, 0 pass-with-edits, 1 block", review.summary(results))
        self.assertIn("nothing approved", review.summary(results))

    def test_a_dry_run_writes_nothing_and_an_unknown_id_is_skipped(self):
        a = self.write("a.json", {"items": [findings(self.item), {"id": "Q-9", "sentences": []}]})
        results = review.apply(a, write=False)
        self.assertEqual((results["Q-1"]["verdict"], results["Q-9"]["verdict"]), ("pass", "skipped"))
        self.assertNotIn("gate", gate_lint.items_by_id()["Q-1"])

    def test_findings_that_do_not_read_are_an_error_never_a_pass(self):
        bad = self.write("bad.json", {"no": "items"})
        with self.assertRaises(review.ReviewError):
            review.apply(bad)
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            self.assertEqual(review.main(["apply", "--first", bad]), 1)
            self.assertEqual(review.main(["apply", "--first", os.path.join(self.tmp, "missing.json")]), 1)
        self.assertIn("no `items` list", err.getvalue())
        self.assertNotIn("gate", gate_lint.items_by_id()["Q-1"])



class SourceCites(Case):
    """Rule 5: a fact about a third party may rest on a primary source cited in the piece, which
    listening read; the brand, a statistic and a capability still need a register row."""

    URL = "https://standards.example.org/consultations/root-issuers"
    QUOTE = "The question of which root a credential chains to is a governance question."
    LINE = "The standards body says which root a credential chains to is a governance question."

    def item(self, line=LINE, url=URL, link=True):
        item = with_line(line + (f" ({url})" if link else ""))
        item["sources"] = [{"id": "S1", "url": url, "title": "Consultation", "quote": self.QUOTE, "finding": "F1"}]
        return item

    def heard(self, url=URL, quote=QUOTE, stream="Acme"):
        return [{"stream": stream, "finding": "F1", "url": url, "title": "Consultation", "quote": quote}]

    def check(self, item, line=LINE, cite="S1", rests="which root a credential chains to is a governance question",
              evidence=None):
        f = findings(item, claims={line: (cite, rests, True)})
        return " | ".join(review.verify(item, f, "acme", self.heard() if evidence is None else evidence)["problems"])

    def test_a_third_party_fact_on_a_source_listening_read_passes(self):
        self.assertEqual(self.check(self.item()), "")

    def test_each_condition_blocks_by_name(self):
        self.assertIn("not linked in the text that ships", self.check(self.item(link=False)))
        self.assertIn("not one listening read", self.check(self.item(), evidence=[]))
        self.assertIn("not one listening read", self.check(self.item(), evidence=self.heard(stream="Beta")))
        self.assertIn("not in what listening quoted", self.check(self.item(), rests="a governance question for the wallet"))
        self.assertIn("which the item's `sources` does not list", self.check(self.item(), cite="S2"))
        mine = "Acme says which root a credential chains to is a governance question."
        self.assertIn("about the brand", self.check(self.item(line=mine), line=mine))
        ours = "Our view: which root a credential chains to is a governance question."
        self.assertIn("about the brand", self.check(self.item(line=ours), line=ours))

    def test_a_statistic_or_a_capability_never_rests_on_a_source(self):
        stat = "The standards body says 40% of roots are a governance question."
        self.assertIn("a statistic with no cite of its own", self.check(self.item(line=stat), line=stat))
        self.assertIn("about the brand", self.check(self.item(line=CAPABILITY), line=CAPABILITY))

    def test_evidence_is_kept_after_the_pass_that_read_it(self):
        state = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, state, True)
        signals = {"stream": "Acme", "findings": [{"id": "F1", "stream": "Acme", "evidence": [
            {"title": "Consultation", "url": self.URL, "quote": self.QUOTE}, {"url": "http://plain.example.org/x", "quote": "q"}]}]}
        with open(os.path.join(state, "signals.json"), "w", encoding="utf-8") as f:
            json.dump(signals, f)
        self.assertEqual(review.record_evidence(state), 1, "https only")
        self.assertEqual(review.record_evidence(state), 0, "once per link and quote")
        os.unlink(os.path.join(state, "signals.json"))
        self.assertEqual([(e["url"], e["stream"]) for e in review.load_evidence(state)], [(self.URL, "Acme")])
        import state_check
        self.assertIn("evidence.json", state_check.FILES)
        self.assertIn("sources", repo.OPTIONAL_KEYS, "the note keeps its sources, so a re-gate still finds them")

class TheReviewerWritesNothing(unittest.TestCase):
    def read(self, *parts):
        with open(os.path.join(ENGINE, *parts), encoding="utf-8") as f:
            return f.read()

    def test_the_gatekeeper_holds_no_edit_and_stamps_nothing(self):
        text = self.read("agents", "gatekeeper.md")
        import re
        tools = json.loads(re.search(r"^tools:\s*(\[.*\])\s*$", text, re.M).group(1))
        self.assertNotIn("Edit", tools)
        self.assertNotIn("Write", tools)
        self.assertIn("you write no `gate`, no verdict, no `reviewed_at`", " ".join(text.split()))
        self.assertNotIn("runlog.py gate", text, "the gate's log line is review.py's")

    def test_the_skill_returns_findings_in_the_schema_and_no_stamp(self):
        out = self.read("skills", "claim-gate", "SKILL.md").split("## output", 1)[1]
        self.assertNotIn('"reviewed_at"', out)
        self.assertNotIn('"verdict"', out)
        sentence = review.SCHEMA["properties"]["items"]["items"]["properties"]["sentences"]["items"]["properties"]
        for key in sentence:
            self.assertIn(f'"{key}"', out, key)
        for name in review.CHECK_NAMES:
            self.assertIn(f"`{name}`", out, name)
        for brief in ("gate.md", "gate-second.md"):
            text = self.read("briefs", "workflows", brief)
            for key in ("rests_on", "supported", "cite", "claim", "sentences"):
                self.assertIn(key, text, (brief, key))
            self.assertIn("write", text)

    def test_the_gate_workflow_is_two_reviewers_then_code(self):
        with open(os.path.join(ENGINE, "engine.json"), encoding="utf-8") as f:
            steps = json.load(f)["params"]["workflows"]["gate"]["steps"]
        kinds = ["model" if "model" in s else os.path.basename(s["run"][1]) for s in steps]
        self.assertEqual(kinds, ["gate_lint", "model", "model", "review", "state_check"])
        first, second = steps[1]["model"], steps[2]["model"]
        self.assertEqual(first["agent"], "comms-engine:gatekeeper")
        self.assertIn("Skill(salon:adversarial-refinement)", second["tools"])
        for model in (first, second):
            self.assertFalse([t for t in model["tools"] if t.startswith(("Edit", "Write"))], "a reviewer writes no file")
        self.assertEqual(steps[3]["run"][2:], ["apply", "--first", "{reply_1}", "--second", "{reply_2}"])



class SentencesToJudge(Case):
    """The reviewer copies the sentences code will look for, so none is left unjudged by a
    different reading of where a sentence ends (the 2026-11-13 evaluation: a title skipped)."""

    def test_the_list_is_exactly_what_verify_looks_for_title_first(self):
        item = copy.deepcopy(BASE)
        listed = review.to_judge([item])["items"][0]
        self.assertEqual(listed["id"], item["id"])
        self.assertEqual(listed["sentences"][0], {"field": "title", "text": "A wallet holds a credential."})
        rows = [dict(s, claim=False) for s in listed["sentences"]]
        _, why = self.problems(item, {"id": item["id"], "sentences": rows, "checks": [], "note": ""})
        self.assertNotIn("did not judge", why)
        self.assertNotIn("does not carry", why)

    def test_ids_choose_the_items_and_otherwise_only_those_awaiting_a_decision(self):
        a, b, c = (dict(copy.deepcopy(BASE), id=i, alpha_status=s)
                   for i, s in (("a", "proposed"), ("b", "approved"), ("c", "published")))
        self.assertEqual([i["id"] for i in review.to_judge([a, b, c])["items"]], ["a", "b"])
        self.assertEqual([i["id"] for i in review.to_judge([a, b, c], ids=["c"])["items"]], ["c"])

    def test_the_command_reads_a_file_and_every_brief_sends_the_reviewer_to_it(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump([BASE], f)
        self.addCleanup(os.unlink, f.name)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(review.main(["sentences", "--file", f.name]), 0)
        self.assertEqual(json.loads(out.getvalue()), review.to_judge([BASE]))
        for brief in ("gate.md", "gate-second.md", "gate-eval.md"):
            with open(os.path.join(ENGINE, "briefs", "workflows", brief), encoding="utf-8") as fh:
                self.assertIn("engine review sentences", " ".join(fh.read().split()), brief)
        with open(os.path.join(ENGINE, "engine.json"), encoding="utf-8") as fh:
            steps = json.load(fh)["params"]["workflows"]["gate"]["steps"]
        for model in (steps[1]["model"], steps[2]["model"]):
            self.assertIn("Bash(engine review sentences*)", model["tools"])

if __name__ == "__main__":
    unittest.main()
