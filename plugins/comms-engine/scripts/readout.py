#!/usr/bin/env python3
"""
readout.py - the monthly readout's data (plan v2, item A12).

On the first cycle of the month, per stream: the correlation on the
scorecard (the one number), lessons promoted or decayed, hypotheses whose
variable predicted nothing, platform changes as dated events, the month's
stage (explore, exploit or deepen, from what the month's pieces answered),
and whether the scorer is frozen: a correlation that fell against the last
readout freezes it, and no live test is closed as `keep` until it recovers.

The prose readout is salon's `campaign-retro`, which `/social-cycle
--readout` runs over this file's output and writes into the stream's campaign
file. This script writes `state/readout-<YYYY-MM>.json`, the `scorer_frozen`
flag in `state/metrics.json`, a decay note under each lesson past its window
in `lessons.md`, and a `readout` row in `runs.json`.

  engine readout            # the root stream, this month
  engine readout --dry-run
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
STATE = paths.state()
REPO = paths.instance()
sys.path.insert(0, HERE)
import memory  # noqa: E402
import metrics  # noqa: E402
import repo  # noqa: E402
import runlog  # noqa: E402

LESSON_DECAY_DAYS = 90
STAGE_OF_QUERY = {"gaps": "explore", "reactive": "explore", "intro": "explore", "freshness": "exploit", "depth": "deepen"}
FREEZE_DROP = 0.2


def _load(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def month_of(d):
    return d.strftime("%Y-%m")


def previous_readout(state, stream_name, before_month):
    files = sorted(f for f in os.listdir(state) if re.match(r"readout-\d{4}-\d{2}\.json$", f)) if os.path.isdir(state) else []
    prev = None
    for f in files:
        m = f[len("readout-"):-len(".json")]
        if m < before_month:
            data = _load(os.path.join(state, f), {})
            if data.get("stream") == stream_name:
                prev = data
    return prev


def variables_that_predicted_nothing(predictions):
    """Per hypothesis variable (the text before the colon), the share of
    records whose predicted band matched the actual; below chance with at
    least three records is 'predicted nothing'."""
    by = {}
    for p in predictions:
        if not p.get("actual") or not p.get("predicted"):
            continue
        var = str(p.get("hypothesis", "")).split(":", 1)[0].strip().lower() or "(unnamed)"
        hit = by.setdefault(var, [0, 0])
        hit[1] += 1
        if p["actual"] == p["predicted"]:
            hit[0] += 1
    return [{"variable": v, "hits": h, "records": n, "accuracy": round(h / n, 2)}
            for v, (h, n) in sorted(by.items()) if n >= 3 and h / n <= 1 / 3]


def lessons_decay(lessons_path, today, dry_run):
    """Kept-pattern lessons whose `since` is older than the decay window and
    carry no decay note yet: append one. Returns the lesson headings touched."""
    if not os.path.exists(lessons_path):
        return []
    with open(lessons_path, encoding="utf-8") as f:
        text = f.read()
    blocks = re.split(r"(?m)^(?=## )", text)
    out, changed = [], False
    for i, b in enumerate(blocks):
        m = re.search(r"(?m)^since: (\d{4}-\d{2}-\d{2})\s*$", b)
        if not m or "decayed:" in b:
            continue
        since = dt.date.fromisoformat(m.group(1))
        if (today - since).days >= LESSON_DECAY_DAYS:
            head = b.splitlines()[0].lstrip("# ").strip()
            out.append(head)
            if not dry_run:
                note = f"decayed: {today.isoformat()} - {LESSON_DECAY_DAYS} days without new evidence; re-test before relying on it.\n"
                blocks[i] = b.rstrip("\n").rstrip("-").rstrip("\n") + "\n" + note + "\n---\n"
                changed = True
    if changed:
        with open(lessons_path, "w", encoding="utf-8") as f:
            f.write("".join(blocks))
    return out


def stage_of_month(items, month):
    counts = {"explore": 0, "exploit": 0, "deepen": 0}
    for i in items:
        d = str((i.get("slot") or {}).get("date", ""))[:7]
        if d != month:
            continue
        counts[STAGE_OF_QUERY.get(str(i.get("query", "")).strip(), "explore")] += 1
    total = sum(counts.values())
    stage = max(counts, key=counts.get) if total else "explore"
    return {"stage": stage, "counts": counts, "pieces": total,
            "shares": {k: (round(v / total, 2) if total else None) for k, v in counts.items()}}


def run(stream=memory.DEFAULT_STREAM, state=None, today=None, dry_run=False, lessons_path=None, items=None):
    state = state or STATE
    today = today or dt.date.today()
    row = memory.stream(stream)
    month = month_of(today.replace(day=1) - dt.timedelta(days=1))  # the month that just closed
    rows = metrics.rows(stream, state, items=items)
    corr = next(r for r in rows["rows"] if r["row"] == "correlation")
    prev = previous_readout(state, row["name"], month)
    prev_corr = (prev or {}).get("correlation", {}).get("value") if prev else None
    frozen = bool(corr["value"] is not None and prev_corr is not None and corr["value"] < prev_corr - FREEZE_DROP)
    tests = _load(os.path.join(state, "tests.json"), [])
    promoted = [t["id"] for t in tests if t.get("outcome") == "keep" and str(t.get("outcome_at", ""))[:7] == month]
    decayed = lessons_decay(lessons_path or os.path.join(REPO, ".atelier", "memory", "lessons.md"), today, dry_run)
    preds = _load(os.path.join(state, "predictions.json"), [])
    events = [e for e in _load(os.path.join(state, "platform-events.json"), []) if str(e.get("at", ""))[:7] == month]
    out = {
        "stream": row["name"], "month": month, "computed_at": today.isoformat(),
        "correlation": {"value": corr["value"], "pairs": corr["records"], "previous": prev_corr},
        "scorer_frozen": frozen,
        "lessons": {"promoted": promoted, "decayed": decayed},
        "predicted_nothing": variables_that_predicted_nothing(preds),
        "platform_events": events,
        "stage": stage_of_month(repo.load_items() if items is None else items, month),
        "scorecard": rows["rows"],
    }
    if not dry_run:
        _write(os.path.join(state, f"readout-{month}.json"), out)
        mpath = os.path.join(state, "metrics.json")
        m = _load(mpath, rows)
        m["scorer_frozen"] = frozen
        _write(mpath, m)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="the monthly readout's data")
    ap.add_argument("--stream", default=memory.DEFAULT_STREAM)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--state", default=STATE)
    a = ap.parse_args(argv)
    try:
        out = run(a.stream, a.state, dry_run=a.dry_run)
    except memory.SharedMemoryError as e:
        print(f"readout: {e}", file=sys.stderr)
        return 2
    c = out["correlation"]
    detail = (f"readout {out['month']}: correlation {c['value'] if c['value'] is not None else 'blank'} "
              f"({c['pairs']} pairs, previous {c['previous']}); scorer {'FROZEN' if out['scorer_frozen'] else 'running'}; "
              f"stage {out['stage']['stage']} over {out['stage']['pieces']} pieces; "
              f"{len(out['lessons']['promoted'])} lesson(s) promoted, {len(out['lessons']['decayed'])} decayed; "
              f"{len(out['predicted_nothing'])} variable(s) predicted nothing; {len(out['platform_events'])} platform event(s)")
    print(detail)
    for v in out["predicted_nothing"]:
        print(f"  predicted nothing: {v['variable']} ({v['hits']}/{v['records']})")
    if not a.dry_run:
        runlog.append("readout", detail, stream=out["stream"], runs_path=os.path.join(a.state, "runs.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
