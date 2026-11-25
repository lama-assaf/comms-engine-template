"""
gate_eval.py: the reviewers are measured on labelled drafts before a code rule is retired.

No model is called here: the reviewers are fakes that return findings. What is pinned:

- the shipped case set reads, has should-block, should-flag and should-pass cases for every
  rule, and is a fair test: the code catches today what the reviewers will be asked to catch
- a reviewer pair that catches everything passes; one that misses a case, or blocks a draft
  labelled pass, does not, and the result names the case
- a house-style rule leaves the code only while BOTH hold: a person listed it under
  `house_style.retired`, and the last evaluation, for the case set as it stands now, shows
  every case of it caught. No result, a stale result, a missed case, or no listing: the code
  keeps checking
- the item-level cite check lets a capability sentence through on an unrelated evidenced row;
  the sentence-level review does not (the case set carries that draft)
- the live run is two headless calls with a budget each, no file a reviewer may write, and it
  is in no scheduled job
"""
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import fixture_memory  # noqa: E402
import gate_eval  # noqa: E402
import gate_lint  # noqa: E402
import review  # noqa: E402

#: for each claims case, the sentence the reviewers must stop and how an honest reviewer reads it
HONEST = {
    "claims-capability-uncited": {"operates the issuance platform": (None, "", False)},
    "claims-capability-wrong-row": {"runs the settlement layer": ("C-acme-5", "demonstrable issuance platform", False)},
    "claims-statistic-unsourced": {"grew 40%": (None, "", False)},
    "claims-superseded-row": {"four vetted members": ("C-acme-6", "four vetted members", True)},
    "claims-uncorroborated-row": {"second jurisdiction": ("C-acme-8", "A second jurisdiction is reading", True)},
    "claims-date-not-on-record": {"goes live": (None, "", False)},
    "claims-intended-as-done": {"provides the identity layer": ("C-acme-9", "plans to provide the identity layer", False)},
    "pass-capability-on-its-row": {"operates a demonstrable": ("C-acme-5", "operates a demonstrable issuance platform", True)},
    "pass-source-third-party": {"puts it plainly": ("S1", "which root a credential chains to is a governance question", True)},
    "claims-source-not-linked": {"puts it plainly": ("S1", "which root a credential chains to is a governance question", True)},
    "claims-source-about-the-brand": {"Acme already answers": ("S1", "which root a credential chains to is a governance question", True)},
}


def reviewer(cases, miss=(), block=(), name="first"):
    """Findings for every case as an honest reviewer would return them, except the cases in
    `miss` (read as clean) and `block` (a check that blocks)."""
    out = {}
    for case in cases:
        item, cid = case["item"], case["id"]
        claims = {} if cid in miss else HONEST.get(cid, {})
        rows = []
        for field, s in review.sentences(item):
            row = {"field": field, "text": s, "claim": False}
            for part, (cite, rests_on, supported) in claims.items():
                if part in s:
                    row.update({"claim": True, "cite": cite, "rests_on": rests_on, "supported": supported})
            rows.append(row)
        checks = []
        if case["expect"] == "flag" and cid not in miss:
            checks.append({"check": "register", "result": "edit", "line": item["title"], "fix": f"{case['rule']}: {case['why']}"})
        if cid in block:
            checks.append({"check": "names", "result": "block", "line": "x", "fix": "an invented fault"})
        out[item["id"]] = {"id": item["id"], "sentences": rows, "checks": checks, "reviewer": name}
    return out


class Case(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        self.cases = gate_eval.load_cases()
        self.state = tempfile.mkdtemp(prefix="gate-eval-")
        self.addCleanup(shutil.rmtree, self.state, True)
        p = mock.patch.object(gate_eval, "STATE", self.state)
        p.start()
        self.addCleanup(p.stop)

    def run_eval(self, **kw):
        return gate_eval.evaluate(self.cases, reviewer(self.cases, **kw), reviewer(self.cases, name="second", **kw))

    def save(self, result):
        with open(gate_eval.result_path(), "w", encoding="utf-8") as f:
            json.dump(dict(result, at="2026-11-13T10:00:00+00:00"), f)

    def retire(self, *names):
        with open(self.fixture.path("gate-rules.json"), "w", encoding="utf-8") as f:
            json.dump({"house_style": {"retired": list(names)}}, f)


class TheSet(Case):
    def test_the_shipped_set_reads_and_covers_every_rule(self):
        by_rule = {}
        for c in self.cases:
            by_rule.setdefault(c["rule"], []).append(c["expect"])
            self.assertTrue(c["why"].strip(), c["id"])
            self.assertTrue(c["item"]["id"].startswith("G-"), "a case id can never be a live item's")
            self.assertEqual(c["item"]["stream"], fixture_memory.ROOT_NAME, "every case is the fixture brand's")
        self.assertEqual(set(by_rule), set(gate_eval.RULES))
        for rule in gate_lint.RETIRABLE:
            self.assertIn("flag", by_rule[rule], f"no should-flag case for {rule}: it could never be retired")
        self.assertGreaterEqual(by_rule["claims"].count("block"), 5)
        self.assertGreaterEqual(by_rule["claims"].count("pass"), 2, "a reviewer that blocks everything must fail the set")
        self.assertEqual(len({c["id"] for c in self.cases}), len(self.cases))

    def test_the_set_is_a_fair_test_of_the_code_rules(self):
        self.assertEqual(gate_eval.fair(self.cases), [])
        unfair = copy.deepcopy(self.cases)
        clean = next(c for c in unfair if c["id"] == "pass-clean-argument")
        clean.update(rule="hook", expect="flag")
        self.assertIn("the code's hook check passes it", " ".join(gate_eval.fair(unfair)))

    def test_the_item_level_cite_check_passes_what_the_sentence_level_review_stops(self):
        case = next(c for c in self.cases if c["id"] == "claims-capability-uncited")
        verdict, failing = gate_eval.code_verdict(case)
        self.assertNotEqual(verdict, "block", "one evidenced row in `cites` satisfies the lint, whatever it is about")
        item = case["item"]
        own = {item["id"]: reviewer([case])[item["id"]]}
        self.assertEqual(gate_eval.judge(case, own[item["id"]], None), (True, "blocked"))
        lenient = reviewer([case], miss=[case["id"]])[item["id"]]
        gate = review.review(item, lenient)
        self.assertEqual(gate["review"]["verdict"], "block", "and a reviewer who calls it not a claim is overruled in code")

    def test_a_case_that_does_not_read_is_an_error(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with self.assertRaises(gate_eval.EvalError):
            gate_eval.load_cases(d)
        with open(os.path.join(d, "x.json"), "w") as f:
            json.dump({"id": "x", "rule": "claims", "expect": "flag", "item": {"id": "G-x"}}, f)
        with self.assertRaises(gate_eval.EvalError):
            gate_eval.load_cases(d)


class Results(Case):
    def test_reviewers_that_catch_everything_pass(self):
        result = self.run_eval()
        self.assertTrue(result["passed"], [r for r in result["rows"] if not r["caught"]])
        self.assertEqual(result["false_blocks"], [])
        for rule, r in result["rules"].items():
            self.assertEqual((r["caught"], r["missed"]), (r["cases"], []), rule)
        self.assertEqual(result["cases_hash"], gate_eval.cases_hash(self.cases))
        self.assertIn("gate eval: passed (22 cases)", gate_eval.lines(result))

    def test_a_missed_case_and_a_false_block_fail_the_set_and_are_named(self):
        result = self.run_eval(miss=["style-hook-emoji", "claims-date-not-on-record"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["rules"]["hook"]["missed"], ["style-hook-emoji"])
        self.assertEqual(result["rules"]["claims"]["missed"], ["claims-date-not-on-record"])
        self.assertEqual(result["rules"]["tag line"]["missed"], [])
        result = self.run_eval(block=["pass-clean-argument"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["false_blocks"], ["pass-clean-argument"])

    def test_one_reviewer_naming_the_fault_is_enough_to_flag_it(self):
        case = next(c for c in self.cases if c["id"] == "style-cta-missing")
        hit = reviewer([case])[case["item"]["id"]]
        quiet = reviewer([case], miss=[case["id"]])[case["item"]["id"]]
        self.assertTrue(gate_eval.judge(case, quiet, hit)[0])
        self.assertFalse(gate_eval.judge(case, quiet, quiet)[0])
        wrong = dict(hit, checks=[{"check": "register", "result": "edit", "line": "x", "fix": "hook: too long"}])
        self.assertFalse(gate_eval.judge(case, wrong, None)[0], "the fault named must be the rule's own")


class Retirement(Case):
    def hook_case(self):
        return next(c["item"] for c in self.cases if c["id"] == "style-hook-too-long")

    def hook(self):
        return next(c for c in gate_lint.lint(self.hook_case())["checks"] if c["check"] == "lint: hook")

    def test_the_code_keeps_checking_until_a_person_lists_the_rule_and_the_set_passes(self):
        self.assertEqual(self.hook()["result"], "edit", "the shipped state: nothing is retired")
        self.retire("hook")
        self.assertEqual(self.hook()["result"], "edit", "listed, but no evaluation has been run")
        self.assertIn("no gate evaluation", gate_lint.retired("hook")[1])
        self.save(self.run_eval())
        got = self.hook()
        self.assertEqual(got["result"], "pass")
        self.assertIn("Retired from the code", got["fix"])
        self.assertEqual(gate_lint.lint(self.hook_case())["verdict"], "pass")
        tag = next(c["item"] for c in self.cases if c["id"] == "style-tag-missing")
        self.assertEqual(next(c for c in gate_lint.lint(tag)["checks"] if c["check"] == "lint: tag line")["result"], "edit",
                         "a rule nobody listed stays in the code, whatever the evaluation says")
        self.assertEqual(next(c for c in gate_lint.lint(self.hook_case(), retire=False)["checks"]
                              if c["check"] == "lint: hook")["result"], "edit", "the evaluation itself always measures the code")

    def test_a_missed_case_a_false_block_or_a_changed_set_puts_the_rule_back(self):
        self.retire("hook", "cta")
        self.save(self.run_eval(miss=["style-hook-emoji"]))
        self.assertEqual(self.hook()["result"], "edit")
        self.assertIn("missed 1 of 4", gate_lint.retired("hook")[1])
        self.assertTrue(gate_lint.retired("cta")[0], "another rule the reviewers did catch is cleared on its own")
        self.save(self.run_eval(block=["pass-clean-argument"]))
        self.assertFalse(gate_lint.retired("cta")[0])
        good = self.run_eval()
        self.save(dict(good, cases_hash="an-older-set"))
        ok, why = gate_lint.retired("hook")
        self.assertFalse(ok)
        self.assertIn("changed since the last evaluation", why)

    def test_only_the_four_house_style_rules_can_be_listed(self):
        import memory
        self.retire("stealth")
        with self.assertRaises(memory.SharedMemoryError):
            memory.load_gate_rules()
        self.assertEqual(gate_lint.lint(self.hook_case())["verdict"], "block", "rules that do not read block; nothing is retired by a typo")
        self.assertEqual(gate_lint.RETIRABLE, ("hook", "tag line", "cta", "shape"))
        self.assertEqual(set(gate_lint.RETIRABLE_CHECKS.values()), set(gate_lint.RETIRABLE))


class TheLiveRun(Case):
    def test_it_is_two_headless_calls_that_may_write_nothing(self):
        calls = []
        first, second = reviewer(self.cases), reviewer(self.cases, name="second")

        def execute(argv, timeout, env):
            calls.append(argv)
            reply = {"items": list((first if "--agent" in argv else second).values())}
            return 0, json.dumps({"type": "result", "is_error": False, "structured_output": reply, "total_cost_usd": 1.25}), ""

        a, b, cost = gate_eval.run_reviewers(self.cases, self.fixture, budget=2, execute=execute)
        self.assertEqual((len(calls), cost), (2, 2.5))
        self.assertEqual(calls[0][calls[0].index("--agent") + 1], "gatekeeper")
        self.assertNotIn("--agent", calls[1])
        for argv in calls:
            tools = argv[argv.index("--allowedTools") + 1].split(",")
            self.assertFalse([t for t in tools if t.startswith(("Edit", "Write"))])
            self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "2")
            self.assertIn(self.fixture.dir, argv[2], "the brief names the fixture memory, never the brand's")
        self.assertTrue(gate_eval.evaluate(self.cases, a, b)["passed"])

        def broken(argv, timeout, env):
            return 0, json.dumps({"type": "result", "is_error": True, "result": "Exceeded USD budget", "total_cost_usd": 2}), ""

        with self.assertRaises(gate_eval.EvalError):
            gate_eval.run_reviewers(self.cases, self.fixture, budget=2, execute=broken)

    def test_it_is_in_no_scheduled_job_and_the_dry_run_is_the_default(self):
        with open(os.path.join(ENGINE, "engine.json"), encoding="utf-8") as f:
            doc = json.load(f)
        self.assertNotIn("gate_eval", json.dumps(doc["jobs"]))
        self.assertNotIn("gate_eval", json.dumps(doc["params"]["workflows"]))
        with open(os.path.join(ENGINE, "scripts", "gate_eval.py"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn('ap.add_argument("--live", action="store_true"', text)


if __name__ == "__main__":
    unittest.main()
