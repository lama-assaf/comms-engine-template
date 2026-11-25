#!/usr/bin/env python3
"""
metrics.py - the scorecard rows (plan v2, item A10).

`state/metrics.json` per stream, beside the twelve key results of the
communications principles (three objectives, four each; KEY_RESULTS below):

  engagement index    mean index of the stream's scored records (score over
                      the stream's own baseline); "partial" while any record
                      is computed from listening alone or has no baseline
  negatives guardrail negatives per published item over the last 30 days
  reach (context)     impressions over the last 30 days; context, never an
                      objective unless the registry row opts in
  correlation         predicted band against actual band over the records
                      that have both, as a rank correlation; blank, not zero,
                      before five pairs (A12 reads it as the one number)
  variety             the homogenisation guard: share of distinct formats,
                      logics and hook openers over the last twelve pieces

Reads `engagement.json`, `predictions.json`, the vault notes and the
registry; writes `state/metrics.json`. The desk renders the rows (the
dashboard page shows no scorecard); nothing here changes a note or a record.

  engine metrics            # the root stream, write
  engine metrics --dry-run
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
sys.path.insert(0, HERE)
import memory  # noqa: E402
import repo  # noqa: E402

WINDOW_DAYS = 30
VARIETY_WINDOW = 12
CORRELATION_MIN = 5
BAND_RANK = {"below": 0, "baseline": 1, "above": 2}

KEY_RESULTS = [
    ("Facts for trust", "Two releases per week published on the brand's own site ahead of any other channel"),
    ("Facts for trust", "Every release jointly authored and synchronised with the partner"),
    ("Facts for trust", "Every release passes the dedicated approval flow; manual release only"),
    ("Facts for trust", "Zero claims of live or deployed capability ahead of delivery"),
    ("Themes build leadership", "Introduction post live for each of the eight theme hashtags"),
    ("Themes build leadership", "Every theme post carries a hashtag, partner tags and a CTA to the blog"),
    ("Themes build leadership", "Website traffic and blog reads per theme, tracked monthly"),
    ("Themes build leadership", "Listener signals per theme: mentions, relevance, sentiment"),
    ("Partners amplify", "Company and personal handles collected for every partner"),
    ("Partners amplify", "Share of theme posts reposted or followed by tagged partners"),
    ("Partners amplify", "Third-party mentions and event panels assigned to a theme"),
    ("Partners amplify", "New partners joining, communicated as evidence of the architecture"),
]


def _load(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _parse(ts):
    try:
        d = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def spearman(pairs):
    """Rank correlation over (predicted rank, actual rank) pairs; ties by mean rank."""
    if len(pairs) < 2:
        return None

    def ranks(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            mean = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = mean
            i = j + 1
        return r
    a, b = ranks([p[0] for p in pairs]), ranks([p[1] for p in pairs])
    ma, mb = statistics.mean(a), statistics.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
    return round(num / den, 3) if den else None


def correlation(predictions):
    pairs = [(BAND_RANK[p["predicted"]], BAND_RANK[p["actual"]]) for p in predictions
             if p.get("predicted") in BAND_RANK and p.get("actual") in BAND_RANK]
    if len(pairs) < CORRELATION_MIN:
        return {"value": None, "pairs": len(pairs), "note": f"blank until {CORRELATION_MIN} items carry predicted and actual"}
    return {"value": spearman(pairs), "pairs": len(pairs), "note": ""}


def hook_opener(title):
    words = [w for w in str(title or "").replace("—", " ").split() if w]
    return (words[0].lower().rstrip(".,:;") if words else "")


def variety(items):
    recent = sorted(items, key=lambda i: str((i.get("slot") or {}).get("date", "")))[-VARIETY_WINDOW:]
    n = len(recent)
    if not n:
        return {"pieces": 0, "formats": None, "logics": None, "openers": None, "score": None}
    fmts = len({i.get("format", "") for i in recent})
    logics = len({i.get("logic", "") for i in recent})
    openers = len({hook_opener(i.get("title")) for i in recent})
    score = round((fmts + logics + openers) / (3 * n), 2)
    return {"pieces": n, "formats": round(fmts / n, 2), "logics": round(logics / n, 2), "openers": round(openers / n, 2), "score": score}


def rows(stream=memory.DEFAULT_STREAM, state=None, now=None, items=None, engagement=None, predictions=None):
    state = state or STATE
    now = now or dt.datetime.now(dt.timezone.utc)
    reg = memory.stream(stream)
    eng = _load(os.path.join(state, "engagement.json"), {}) if engagement is None else engagement
    preds = _load(os.path.join(state, "predictions.json"), []) if predictions is None else predictions
    items = [i for i in (repo.load_items() if items is None else items) if i.get("stream") == reg["name"]]
    records = [r for r in eng.get("records", []) or [] if isinstance(r, dict) and r.get("stream", reg["name"]) == reg["name"]]
    recent = [r for r in records if _parse(r.get("published_at")) and (now - _parse(r["published_at"])).days <= WINDOW_DAYS]
    indexed = [r["index"] for r in records if r.get("index") is not None]
    partial = any(r.get("partial") for r in records) or not indexed
    negatives = sum(int(r.get("negatives_total") or 0) for r in recent)
    impressions = sum(int(((r.get("at_7d") or r.get("at_72h") or {}).get("impressions") or 0)) for r in recent)
    reach_objective = "reach" in str(reg.get("objectives", "")).lower() and "context only" not in str(reg.get("objectives", "")).lower()
    corr = correlation(preds)
    var = variety(items)
    out = {
        "stream": reg["name"], "computed_at": now.isoformat(timespec="seconds"), "window_days": WINDOW_DAYS,
        "scorer_frozen": bool(_load(os.path.join(state, "metrics.json"), {}).get("scorer_frozen", False)),
        "rows": [
            {"row": "engagement index", "value": round(statistics.mean(indexed), 2) if indexed else None,
             "records": len(records), "status": "partial" if partial else "full",
             "note": "mean of score over the stream's baseline; partial while any record is listening-only or has no baseline"},
            {"row": "negatives guardrail", "value": round(negatives / len(recent), 2) if recent else None,
             "records": len(recent), "status": "partial" if partial else "full",
             "note": "negatives per published item, last 30 days: unfollows, hides, correction replies"},
            {"row": "reach", "value": impressions, "records": len(recent),
             "status": "objective" if reach_objective else "context",
             "note": "impressions, last 30 days; context unless the registry row opts in"},
            {"row": "correlation", "value": corr["value"], "records": corr["pairs"],
             "status": "blank" if corr["value"] is None else "live", "note": corr["note"] or "predicted band against actual band, rank correlation"},
            {"row": "variety", "value": var["score"], "records": var["pieces"],
             "status": "blank" if var["score"] is None else "live",
             "note": f"distinct formats {var['formats']}, logics {var['logics']}, hook openers {var['openers']} over the last {VARIETY_WINDOW} pieces"},
        ],
        "key_results": [{"objective": o, "key_result": k} for o, k in KEY_RESULTS],
    }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="the scorecard rows")
    ap.add_argument("--stream", default=memory.DEFAULT_STREAM)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--state", default=STATE)
    a = ap.parse_args(argv)
    try:
        out = rows(a.stream, a.state)
    except memory.SharedMemoryError as e:
        print(f"metrics: {e}", file=sys.stderr)
        return 2
    for r in out["rows"]:
        print(f"{r['row']:<20} {str(r['value']) if r['value'] is not None else '—':>8}  {r['status']:<9} ({r['records']} records)")
    if out["scorer_frozen"]:
        print("scorer frozen (A12): no pattern is kept until the correlation recovers")
    if not a.dry_run:
        p = os.path.join(a.state, "metrics.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
            f.write("\n")
        print(f"wrote {os.path.relpath(p, repo.REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
