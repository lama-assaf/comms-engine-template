#!/usr/bin/env python3
"""
predictions.py - `state/predictions.json`: predicted beside actual, per item (A8, A9).

One record per drafted item that carries a `predicted` band: appended when the
item is ingested into the vault (`repo.py --all`), with `actual` empty.
`score.py` fills `actual` at 7 days. The file is what the monthly readout
correlates (A12): a prediction is never edited once written, and an item has
one record.

Bands: `below`, `baseline`, `above` - the item's engagement index against the
stream's baseline for its platform and format. `test_id` is `T-<slug>-<n>` or
`none`.

  engine predictions --list
"""
import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
STATE = paths.state()

BANDS = ("below", "baseline", "above")
QUERIES = ("gaps", "freshness", "depth", "reactive", "intro")


def path(state=None):
    return os.path.join(state or STATE, "predictions.json")


def load(state=None):
    p = path(state)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise RuntimeError(f"{p} is not a JSON list - refusing to overwrite it")
    return data


def save(records, state=None):
    p = path(state)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)
    return p


def complete(item):
    """Whether the item carries the three A8 fields in valid form."""
    return bool(str(item.get("hypothesis") or "").strip()) and \
        str(item.get("predicted") or "").strip() in BANDS and \
        bool(str(item.get("test_id") or "").strip())


def record_for(item, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    return {
        "id": item["id"], "stream": item.get("stream", ""), "theme": item.get("theme", ""),
        "platform": (item.get("slot") or {}).get("platform", "Blog"), "format": item.get("format", ""),
        # the argument shape it ran: with `format`, what the next draw weighs (plan_queries.draw)
        "logic": item.get("logic", ""),
        "query": item.get("query", ""), "hypothesis": item.get("hypothesis", ""),
        "predicted": item.get("predicted", ""), "test_id": item.get("test_id", ""),
        "predicted_at": now.isoformat(timespec="seconds"),
        "actual": None, "actual_at": None, "score": None, "index": None, "partial": None,
    }


def append_for(items, state=None, now=None):
    """Append a record for every item with a valid prediction and no record
    yet. Returns the ids appended. Never touches an existing record."""
    records = load(state)
    have = {r["id"] for r in records}
    added = []
    for item in items:
        if item.get("id") in have or not complete(item):
            continue
        records.append(record_for(item, now))
        have.add(item["id"])
        added.append(item["id"])
    if added:
        save(records, state)
    return added


def set_actual(item_id, band, score=None, index=None, partial=None, state=None, now=None):
    """Write the outcome beside the prediction. Returns the record or None."""
    now = now or dt.datetime.now(dt.timezone.utc)
    records = load(state)
    for r in records:
        if r["id"] == item_id:
            r.update({"actual": band, "actual_at": now.isoformat(timespec="seconds"),
                      "score": score, "index": index, "partial": partial})
            save(records, state)
            return r
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="predicted beside actual, per item")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--state", default=STATE)
    a = ap.parse_args(argv)
    recs = load(a.state)
    for r in recs:
        print(f"{r['id']:<40} {r['predicted']:<9} -> {r['actual'] or '—':<9} {r['test_id']}  {r['hypothesis'][:50]}")
    print(f"{len(recs)} prediction(s), {sum(1 for r in recs if r['actual'])} with an actual")
    return 0


if __name__ == "__main__":
    sys.exit(main())
