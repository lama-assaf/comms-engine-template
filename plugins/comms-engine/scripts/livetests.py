#!/usr/bin/env python3
"""
livetests.py - live tests and their outcomes (plan v2, item A11).

`state/tests.json` holds one record per hypothesis under test: the variable,
the primary metric, the guardrails, the minimum sample, the maturation window,
the slots (item ids, variant and control), and the outcome: `keep`,
`discard`, `trending`, `inconclusive`, or `open`. Organic channels test with
matched sequential slots over several weeks, so a test closes only when its
maturation window has passed for every slot and the sample is there.

The weekly editor applies the budget: of the coming week's slots, about 60 %
proven patterns, 25 % variations, 15 % experiments (`kind` on the test), and
one or two open tests per channel. A kept pattern that won in two separate
periods is appended to `.atelier/memory/lessons.md` with `evidence`,
`confidence` and `since`; one win is `trending` and writes nothing.

  engine livetests new --id T-acme-1 --variable "hook form" \\
      --hypothesis "a contrast hook beats a declarative" --channel X --kind variation
  engine livetests assign T-acme-1 --variant Q-… --control Q-…
  engine livetests close            # every test whose window passed
  engine livetests budget --slots '[{"id":"Q-1","channel":"X","kind":"proven"}]'
  engine livetests --list
"""
import argparse
import datetime as dt
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
STATE = paths.state()
REPO = paths.instance()
LESSONS = os.path.join(REPO, ".atelier", "memory", "lessons.md")
sys.path.insert(0, HERE)
import memory  # noqa: E402

KINDS = ("proven", "variation", "experiment")
BUDGET = {"proven": 0.60, "variation": 0.25, "experiment": 0.15}
OUTCOMES = ("open", "keep", "discard", "trending", "inconclusive")
MAX_OPEN_PER_CHANNEL = 2
#: the variant must beat the control's median by this share to count as a win
WIN_MARGIN = 0.10
DEFAULTS = {"metric": "score", "min_sample": 2, "maturation_days": 7}


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _parse(ts):
    try:
        d = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def path(state=None):
    return os.path.join(state or STATE, "tests.json")


def load(state=None):
    p = path(state)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise RuntimeError(f"{p} is not a JSON list - refusing to overwrite it")
    return data


def save(tests, state=None):
    p = path(state)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tests, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)


def new(test_id, variable, hypothesis, channel, kind, stream=memory.DEFAULT_STREAM_NAME, metric=None, guardrails=None,
        min_sample=None, maturation_days=None, state=None, now=None):
    tests = load(state)
    if any(t["id"] == test_id for t in tests):
        raise ValueError(f"{test_id} exists")
    if kind not in KINDS:
        raise ValueError(f"kind {kind!r} is not one of {KINDS}")
    open_on_channel = [t for t in tests if t["channel"] == channel and t["outcome"] == "open" and t["stream"] == stream]
    if len(open_on_channel) >= MAX_OPEN_PER_CHANNEL:
        raise ValueError(f"{channel} already has {len(open_on_channel)} open test(s): "
                         f"{', '.join(t['id'] for t in open_on_channel)}. One or two per channel.")
    rec = {
        "id": test_id, "stream": stream, "variable": variable, "hypothesis": hypothesis,
        "channel": channel, "kind": kind, "metric": metric or DEFAULTS["metric"],
        "guardrails": guardrails or ["negatives_total stays at or below the stream's median"],
        "min_sample": int(min_sample or DEFAULTS["min_sample"]),
        "maturation_days": int(maturation_days or DEFAULTS["maturation_days"]),
        "slots": {"variant": [], "control": []},
        "created_at": (now or _now()).isoformat(timespec="seconds"),
        "outcome": "open", "outcome_at": None, "wins": [], "readings": [],
    }
    tests.append(rec)
    save(tests, state)
    return rec


def assign(test_id, variant=(), control=(), state=None):
    tests = load(state)
    for t in tests:
        if t["id"] == test_id:
            for iid in variant:
                if iid not in t["slots"]["variant"]:
                    t["slots"]["variant"].append(iid)
            for iid in control:
                if iid not in t["slots"]["control"]:
                    t["slots"]["control"].append(iid)
            save(tests, state)
            return t
    raise KeyError(test_id)


def _records(state):
    p = os.path.join(state or STATE, "engagement.json")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        eng = json.load(f)
    return {r["id"]: r for r in eng.get("records", []) or [] if isinstance(r, dict) and r.get("id")}


def reading(test, records, now):
    """`(result, detail)` for one test from the scored records of its slots:
    `open`, `win`, `discard` or `inconclusive`."""
    metric = test["metric"]

    def values(ids):
        out = []
        for iid in ids:
            r = records.get(iid)
            if not r or r.get(metric) is None:
                continue
            pub = _parse(r.get("published_at"))
            if pub and (now - pub).days < test["maturation_days"]:
                return None  # a slot has not matured: the test stays open
            out.append(float(r[metric]))
        return out
    v, c = values(test["slots"]["variant"]), values(test["slots"]["control"])
    if v is None or c is None:
        return "open", "a slot has not reached its maturation window"
    if len(v) < test["min_sample"] or len(c) < test["min_sample"]:
        return "open", f"sample {len(v)} variant / {len(c)} control, minimum {test['min_sample']} each"
    mv, mc = statistics.median(v), statistics.median(c)
    if mc == 0 and mv == 0:
        return "inconclusive", "both medians are zero; nothing was measured"
    lift = (mv - mc) / mc if mc else float("inf")
    if lift >= WIN_MARGIN:
        return "win", f"variant median {mv} against control {mc} (+{round(lift * 100)}%)"
    if lift <= -WIN_MARGIN:
        return "discard", f"variant median {mv} against control {mc} ({round(lift * 100)}%)"
    return "inconclusive", f"variant median {mv} against control {mc}: inside the margin"


def period_of(now):
    return now.strftime("%G-W%V")


def close(state=None, now=None, records=None, frozen=False):
    """Close every open test whose window has passed. A win in a new period
    makes the test `trending` after one and `keep` after two; a kept test
    writes a lesson. With the scorer frozen (A12) nothing closes as keep."""
    now = now or _now()
    tests = load(state)
    records = _records(state) if records is None else records
    closed = []
    for t in tests:
        if t["outcome"] not in ("open", "trending"):
            continue
        result, detail = reading(t, records, now)
        if result == "open":
            continue
        t["readings"].append({"at": now.isoformat(timespec="seconds"), "period": period_of(now), "result": result, "detail": detail})
        if result == "win":
            if period_of(now) not in t["wins"]:
                t["wins"].append(period_of(now))
            if len(t["wins"]) >= 2 and not frozen:
                t["outcome"] = "keep"
                t["lesson"] = write_lesson(t, now)
            else:
                t["outcome"] = "trending"
        else:
            t["outcome"] = result
        t["outcome_at"] = now.isoformat(timespec="seconds")
        closed.append((t["id"], t["outcome"], detail))
    if closed:
        save(tests, state)
    return closed


def write_lesson(test, now, lessons_path=None):
    """Append the kept pattern to lessons.md in the file's own format, with
    the evidence (item ids), a confidence and a `since` the readout decays."""
    lessons_path = lessons_path or LESSONS
    evidence = test["slots"]["variant"] + test["slots"]["control"]
    conf = "medium" if len(test["wins"]) == 2 else "high"
    entry = (f"\n## {now.date().isoformat()} — kept pattern: {test['variable']} ({test['id']})\n\n"
             f"context: live test {test['id']} on {test['channel']}, {test['kind']}; hypothesis: {test['hypothesis']}. "
             f"Won in periods {', '.join(test['wins'])}.\n\n"
             f"lesson: {test['hypothesis']}. Apply it as the default for {test['variable']} on {test['channel']} "
             f"until the monthly readout decays it.\n\n"
             f"cost: ignoring it spends slots on the pattern the test showed to be weaker.\n\n"
             f"evidence: {', '.join(evidence)}\nconfidence: {conf}\nsince: {now.date().isoformat()}\n"
             f"decay: re-test after 90 days or when the platform changes.\n\n---\n")
    with open(lessons_path, "a", encoding="utf-8") as f:
        f.write(entry)
    return {"path": os.path.relpath(lessons_path, REPO), "since": now.date().isoformat(), "confidence": conf}


def budget(week_slots, state=None):
    """How a week's slots sit against 60/25/15. `week_slots` is a list of
    `{"id", "channel", "kind"}` (kind from the item's test, else `proven`)."""
    n = max(len(week_slots), 1)
    counts = {k: sum(1 for s in week_slots if s.get("kind", "proven") == k) for k in KINDS}
    shares = {k: round(counts[k] / n, 2) for k in KINDS}
    over = [k for k in KINDS if shares[k] > BUDGET[k] + 0.15]
    under = [k for k in KINDS if shares[k] < BUDGET[k] - 0.15]
    per_channel = {}
    for t in load(state):
        if t["outcome"] == "open":
            per_channel[t["channel"]] = per_channel.get(t["channel"], 0) + 1
    collisions = {c: k for c, k in per_channel.items() if k > MAX_OPEN_PER_CHANNEL}
    return {"slots": len(week_slots), "counts": counts, "shares": shares, "budget": BUDGET,
            "over": over, "under": under, "open_per_channel": per_channel, "collisions": collisions,
            "holds": [f"{k}: {shares[k]:.0%} of the week against a {BUDGET[k]:.0%} budget" for k in over]
                     + [f"{c}: {k} open tests, at most {MAX_OPEN_PER_CHANNEL}" for c, k in collisions.items()]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="live tests and their outcomes")
    ap.add_argument("--state", default=STATE)
    ap.add_argument("--list", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    n = sub.add_parser("new")
    n.add_argument("--id", required=True); n.add_argument("--variable", required=True)
    n.add_argument("--hypothesis", required=True); n.add_argument("--channel", required=True)
    n.add_argument("--kind", required=True, choices=KINDS); n.add_argument("--stream", default=memory.DEFAULT_STREAM_NAME)
    n.add_argument("--metric"); n.add_argument("--min-sample", type=int); n.add_argument("--maturation-days", type=int)
    a_ = sub.add_parser("assign"); a_.add_argument("id"); a_.add_argument("--variant", nargs="*", default=[]); a_.add_argument("--control", nargs="*", default=[])
    sub.add_parser("close")
    b = sub.add_parser("budget"); b.add_argument("--slots", help="JSON list of {id, channel, kind}", default="[]")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "new":
            t = new(a.id, a.variable, a.hypothesis, a.channel, a.kind, a.stream, a.metric, None, a.min_sample, a.maturation_days, a.state)
            print(f"new test {t['id']} ({t['kind']}, {t['channel']}): {t['hypothesis']}")
        elif a.cmd == "assign":
            t = assign(a.id, a.variant, a.control, a.state)
            print(f"{t['id']}: variant {t['slots']['variant']} control {t['slots']['control']}")
        elif a.cmd == "close":
            for tid, outcome, detail in close(a.state):
                print(f"{tid}: {outcome} - {detail}")
        elif a.cmd == "budget":
            print(json.dumps(budget(json.loads(a.slots), a.state), indent=1))
        if a.cmd is None or a.list:
            for t in load(a.state):
                print(f"{t['id']:<12} {t['outcome']:<12} {t['channel']:<9} {t['kind']:<10} wins {len(t['wins'])}  {t['hypothesis'][:60]}")
    except (ValueError, KeyError) as e:
        print(f"livetests: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
