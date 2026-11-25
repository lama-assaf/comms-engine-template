#!/usr/bin/env python3
"""
gate_eval.py - measure the reviewers on labelled drafts before a code rule is retired.

Why: house style (hook length, the tag line, the CTA, the shape) is checked by
code in gate_lint.py. The plan moves it to the reviewers, whose findings
review.py records as advice that never blocks. A rule may leave the code only
when the reviewers are shown to catch what the rule caught, and that has to be
measured, not assumed. This runs the two reviewers of the `gate` workflow over
the labelled drafts in `tests/fixtures/gate_cases/`, against the fixture
brand's memory, and says per rule how many cases they caught.

A case is `{id, rule, expect, why, item, before?, evidence?}`; `evidence` is what
listening read, for a claim that rests on a source (review.py's source cites):

  expect  block   the claim checks must stop it (review.py's verdict on the
                  reviewers' findings is `block`)
          flag    a reviewer must name the house-style fault of `rule` (a
                  `register` check that is not a pass and names the rule)
          pass    it must not be blocked
  rule    claims, or one of gate_lint.RETIRABLE (hook, tag line, cta, shape)

The result is `state/gate-eval.json`: when, the hash of the case set, and per
rule the cases, the caught and the missed. gate_lint.py retires a house-style
rule only while two things hold: a person listed it under
`house_style.retired` in the stream's gate-rules.json, and this file says the
reviewers caught every case of that rule in the case set as it stands now
(`cleared`). Change a case and the result is stale: the rule is back in force
until the set is run again.

The dry run (the default) calls no model: it checks the labels and proves the
set is a fair one, that is, the code catches today every case the reviewers
will be asked to catch. `--live` makes paid model calls (two per run, each
with its own budget), so it is not part of the unit suite and nothing
schedules it.

  engine gate_eval              # dry: the cases, and what the code does with each
  engine gate_eval --live       # the two reviewers, paid; writes state/gate-eval.json
  engine gate_eval --status     # the last result, and which rules it clears
  engine eval gate [--live]
"""
import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
REPO = paths.instance()
STATE = paths.state()
TESTS = os.path.join(ENGINE, "tests")
CASES = os.path.join(TESTS, "fixtures", "gate_cases")
RESULT_FILE = "gate-eval.json"
EXPECT = ("block", "flag", "pass")
sys.path.insert(0, HERE)

import config  # noqa: E402
import gate_lint  # noqa: E402
import review  # noqa: E402

RULES = ("claims",) + gate_lint.RETIRABLE


class EvalError(RuntimeError):
    """The case set or a reviewer's reply could not be read."""


def load_cases(directory=None):
    """The labelled drafts, by id, in file order. A case that does not read is an error, not a skip."""
    directory = directory or CASES
    out = []
    try:
        names = sorted(n for n in os.listdir(directory) if n.endswith(".json"))
    except OSError as e:
        raise EvalError(f"no case set at {directory}: {e}")
    for name in names:
        with open(os.path.join(directory, name), encoding="utf-8") as f:
            try:
                case = json.load(f)
            except ValueError as e:
                raise EvalError(f"{name}: does not parse ({e})")
        if case.get("rule") not in RULES or case.get("expect") not in EXPECT or not isinstance(case.get("item"), dict) \
                or not case["item"].get("id") or not str(case.get("id") or "").strip():
            raise EvalError(f"{name}: needs an id, a rule of {', '.join(RULES)}, an expect of {', '.join(EXPECT)} and an item")
        if case["expect"] == "flag" and case["rule"] == "claims":
            raise EvalError(f"{name}: a claims case is block or pass; flag is for a house-style rule")
        out.append(case)
    if not out:
        raise EvalError(f"no case in {directory}")
    return out


def cases_hash(cases):
    """What a result is valid for: the case set, word for word."""
    blob = json.dumps([{k: c.get(k) for k in ("id", "rule", "expect", "item", "before")} for c in cases],
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@contextlib.contextmanager
def fixture_memory():
    """The fixture brand's memory, for the length of an evaluation: the cases cite its register."""
    sys.path.insert(0, TESTS)
    import fixture_memory as fm
    fixture = fm.FixtureMemory().start()
    try:
        yield fixture
    finally:
        fixture.stop()


def code_verdict(case):
    """What the deterministic gate does with a case today: `(verdict, [names of checks that are not a pass])`."""
    corpus = [case["item"], *(case.get("before") or [])]
    result = gate_lint.lint(case["item"], corpus=corpus, retire=False)
    return result["verdict"], [c["check"][len(gate_lint.PREFIX):] for c in result["checks"] if c["result"] != "pass"]


def fair(cases):
    """Problems with the set as a test of the code rules: a house-style case the code does not
    catch today proves nothing about what retiring the rule would lose."""
    out = []
    for case in cases:
        verdict, failing = code_verdict(case)
        if case["expect"] == "flag" and case["rule"] not in failing:
            out.append(f"{case['id']}: labelled as a {case['rule']} fault, and the code's {case['rule']} check passes it")
        if case["expect"] == "pass" and verdict == "block":
            out.append(f"{case['id']}: labelled pass, and the code blocks it ({', '.join(failing)})")
    return out


def flagged(finding, rule):
    """Whether a reviewer named the house-style fault of `rule` on this item."""
    for c in (finding or {}).get("checks") or []:
        if not isinstance(c, dict) or c.get("check") != "register" or c.get("result") == "pass":
            continue
        if str(c.get("fix") or "").strip().lower().startswith(rule):
            return True
    return False


def judge(case, first, second):
    """`(caught, what happened)` for one case against the two reviewers' findings on its item."""
    item = case["item"]
    if case["expect"] == "flag":
        hit = flagged(first, case["rule"]) or flagged(second, case["rule"])
        return hit, "flagged" if hit else f"no reviewer named a {case['rule']} fault"
    # what listening read comes with the case, never from this checkout's state/
    gate = review.review(item, first or {"id": item["id"]}, second, corpus=[item, *(case.get("before") or [])],
                         evidence=list(case.get("evidence") or []))
    blocked = gate["review"]["verdict"] == "block"
    if case["expect"] == "block":
        return blocked, "blocked" if blocked else "the review passed it"
    why = (gate["review"]["problems"] or ["a reviewer's check blocked it"])[0]
    return not blocked, "passed" if not blocked else f"blocked: {why[:160]}"


def evaluate(cases, first, second):
    """The result of one run: per rule the cases, the caught and the missed, and the false blocks."""
    rules = {r: {"cases": 0, "caught": 0, "missed": []} for r in RULES}
    false_blocks, rows = [], []
    for case in cases:
        item_id = case["item"]["id"]
        caught, said = judge(case, first.get(item_id), second.get(item_id) if second is not None else None)
        rows.append({"id": case["id"], "rule": case["rule"], "expect": case["expect"], "caught": caught, "said": said})
        if case["expect"] == "pass":
            if not caught:
                false_blocks.append(case["id"])
            continue
        r = rules[case["rule"]]
        r["cases"] += 1
        if caught:
            r["caught"] += 1
        else:
            r["missed"].append(case["id"])
    return {"cases": len(cases), "cases_hash": cases_hash(cases), "rules": rules, "false_blocks": false_blocks,
            "passed": all(not r["missed"] for r in rules.values()) and not false_blocks, "rows": rows}


def result_path(state=None):
    return os.path.join(state or STATE, RESULT_FILE)


def load_result(state=None):
    try:
        with open(result_path(state), encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def cleared(rule, state=None, cases=None):
    """`(ok, why)`: did the reviewers catch every case of this rule, in the case set as it stands now.

    False without a result, with a result for another case set, with no case of the rule, or
    with one missed. A reviewer that also blocked a draft labelled pass clears nothing either."""
    doc = load_result(state)
    if not doc:
        return False, "no gate evaluation has been run (gate_eval.py --live)"
    try:
        now = cases_hash(load_cases() if cases is None else cases)
    except EvalError as e:
        return False, str(e)
    if doc.get("cases_hash") != now:
        return False, "the labelled set changed since the last evaluation; run it again"
    r = (doc.get("rules") or {}).get(rule) or {}
    if not r.get("cases"):
        return False, f"the labelled set has no case of {rule}"
    if r.get("missed"):
        return False, f"the reviewers missed {len(r['missed'])} of {r['cases']} case(s) of {rule}: {', '.join(r['missed'])}"
    if doc.get("false_blocks"):
        return False, f"the reviewers blocked a draft labelled pass ({', '.join(doc['false_blocks'])})"
    return True, f"{r['caught']} of {r['cases']} case(s) caught on {str(doc.get('at') or '')[:10]}"


def run_reviewers(cases, fixture, budget=None, execute=None):
    """The two reviewers over the case set, as the gate workflow calls them: `(first, second, cost)`.

    Paid. Each is one headless `claude -p` with a brief, a budget and a JSON reply this script
    checks; neither may write a file. `execute` is for tests."""
    import workflow
    execute = execute or workflow._execute
    budget = float(budget if budget is not None else config.cfg("gate_eval.budget_usd", 3))
    with tempfile.NamedTemporaryFile("w", suffix=".json", prefix="gate-cases-", delete=False, encoding="utf-8") as f:
        json.dump([dict(c["item"], before=[{k: b.get(k) for k in ("id", "title", "post")} for b in c.get("before") or []])
                   for c in cases], f, indent=1, ensure_ascii=False)
        cases_file = f.name
    values = {"cases_file": cases_file, "memory_dir": fixture.dir, "stream_name": "Acme"}
    tools = ["Read", "Glob", "Grep", "Bash(engine review schema*)",
             "Bash(engine review sentences*)"]
    out, cost = [], 0.0
    try:
        for agent, extra in (("gatekeeper", []), (None, ["Skill(salon:adversarial-refinement)"])):
            model = {"prompt": "gate-eval.md", "budget_usd": budget, "tools": tools + extra, "expects": {"items": "list"}}
            if agent:
                model["agent"] = agent
            argv = workflow.claude_argv(model, workflow.prompt_text(model, values), budget)
            rc, stdout, stderr = execute(argv, workflow.MODEL_TIMEOUT, workflow._model_env())
            reply, spent, error = workflow.read_reply(stdout)
            cost += spent
            error = error or (f"claude exit {rc}" if rc else None) or workflow.check_output(reply, model["expects"])
            if error:
                raise EvalError(f"the {'first' if agent else 'second'} reviewer did not return findings: {error}")
            out.append({row["id"]: dict(row, reviewer=agent or "gate-eval.md") for row in reply["items"]
                        if isinstance(row, dict) and isinstance(row.get("id"), str)})
    finally:
        os.unlink(cases_file)
    return out[0], out[1], cost


def lines(result):
    out = []
    for name, r in result["rules"].items():
        if r["cases"]:
            out.append(f"{name:<9} {r['caught']}/{r['cases']} caught" + (f"  missed: {', '.join(r['missed'])}" if r["missed"] else ""))
    if result["false_blocks"]:
        out.append(f"blocked a draft labelled pass: {', '.join(result['false_blocks'])}")
    out.append("gate eval: " + ("passed" if result["passed"] else "not passed") + f" ({result['cases']} cases)")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="measure the reviewers on the labelled drafts")
    ap.add_argument("--live", action="store_true", help="run the two reviewers (paid model calls) and write state/gate-eval.json")
    ap.add_argument("--status", action="store_true", help="the last result and which rules it clears")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        cases = load_cases()
    except EvalError as e:
        print(f"gate_eval: {e}", file=sys.stderr)
        return 2
    if args.status:
        doc = load_result()
        print("no evaluation yet" if not doc else f"last run {doc.get('at')}: {'passed' if doc.get('passed') else 'not passed'}, "
              f"{doc.get('cases')} cases, cost {doc.get('cost_usd', 0):.2f} USD")
        for rule in gate_lint.RETIRABLE:
            ok, why = cleared(rule, cases=cases)
            print(f"  {rule:<9} {'cleared' if ok else 'not cleared'}: {why}")
        return 0
    with fixture_memory() as fixture:
        problems = fair(cases)
        if not args.live:
            for case in cases:
                verdict, failing = code_verdict(case)
                print(f"{case['id']:<30} {case['rule']:<9} expect {case['expect']:<5}  code: {verdict}"
                      + (f" ({', '.join(failing)})" if failing else ""))
            for p in problems:
                print(f"UNFAIR  {p}")
            print(f"gate eval: dry run, {len(cases)} cases, no model called"
                  + ("" if not problems else f"; {len(problems)} case(s) the code does not treat as labelled"))
            return 1 if problems else 0
        if problems:
            print("gate_eval: the set is not a fair test; fix the cases first:\n  " + "\n  ".join(problems), file=sys.stderr)
            return 1
        try:
            first, second, cost = run_reviewers(cases, fixture)
            result = evaluate(cases, first, second)
        except EvalError as e:
            print(f"gate_eval: {e}", file=sys.stderr)
            return 1
    result.update({"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "cost_usd": round(cost, 4),
                   "stream": config.brand()["name"]})
    os.makedirs(STATE, exist_ok=True)
    tmp = result_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, result_path())
    print(json.dumps(result, indent=1) if args.json else "\n".join(lines(result)))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
