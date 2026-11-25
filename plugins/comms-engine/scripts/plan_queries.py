#!/usr/bin/env python3
"""
plan_queries.py - the three planning queries before a draft (plan v2, item A8).

Per theme of a stream, from the files the engine already keeps:

  gaps       demand is high and little has been published: demand per theme
             (`signals.json` per_theme `demand`, or a proxy from count and
             relevance until the qualitative pass writes it) against the
             pieces published or queued on that theme in the last WINDOW days.
  freshness  claims register rows on that theme added or changed since the
             theme's last piece (`claims.md` dates, `state/claims-changes.json`).
  depth      the same follow-up keeps coming: conversation-shaped findings and
             substantive replies on that theme (A17 feeds the second; until
             then the count is listening only and marked partial).

The pick a strategist makes names which query it answers (`query` on the
item). Until the research store exists (A16) every query runs over the files,
and the output says so: `"queries": "files"`.

It also draws how each theme's next draft is written, so posts stop reading
alike: a **format** (the stream's `formats.json`) and a **logic** (the theme's
`logics` cell), by weighted draw over how each did before
(`state/predictions.json`: `above`, `baseline`, `below`), inside the 60/25/15
budget livetests.py holds for proven patterns, variations and experiments.

  proven      the format with this logic was scored at least twice and held the baseline
  variation   the format is proven; this logic with it is not yet
  experiment  everything else: a format with fewer than two scored pieces

The kind is drawn first, by the budget over the kinds that have a candidate;
then a format and logic within it, by the format's weight times how it did. The
draw is seeded (stream, theme, day, slot), so the same day gives the same draw,
and the seed and the draw are written into planning.json for the writer to put
on the note (`format`, `logic`, `draw`).

  engine plan_queries              # the root stream, writes state/planning.json
  engine plan_queries --stream beta --dry-run
  engine plan_queries --draw '#Theme' [--slot 2]   # one more draw for a theme, as JSON
"""
import argparse
import datetime as dt
import json
import os
import random
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
STATE = paths.state()
sys.path.insert(0, HERE)
import memory  # noqa: E402
import repo  # noqa: E402

WINDOW_DAYS = 28
QUERIES = ("gaps", "freshness", "depth")
#: what a scored piece says about the format and logic it ran
BAND_SCORE = {"below": 0.5, "baseline": 1.0, "above": 1.5}
#: scored pieces before a format, or a format with a logic, counts as proven
MIN_PROVEN = 2
#: a note written before formats existed carries the calendar's old label
LEGACY_FORMATS = ("", "Observation")


def _load(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _date(v):
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def pieces_by_theme(stream_name, tags, cal=None, today=None):
    """Published or queued pieces per theme from the vault notes: `{tag: [dates]}`.
    A note carries `theme` (engine) or `category` (team); both map to a tag."""
    cal = cal or repo.CAL
    today = today or dt.date.today()
    out = {t: [] for t in tags}
    by_cat = {t.lstrip("#").lower(): t for t in tags}
    if not os.path.isdir(cal):
        return out
    for name in sorted(os.listdir(cal)):
        if not name.endswith(".md"):
            continue
        fm, _ = repo.parse_note(os.path.join(cal, name))
        if str(fm.get("stream", "")).strip() != stream_name:
            continue
        tag = (fm.get("theme") or "").strip() or by_cat.get(str(fm.get("category") or "").strip().lstrip("#").lower(), "")
        if tag not in out:
            continue
        d = _date(fm.get("date"))
        if d and (today - d).days <= WINDOW_DAYS * 3:
            out[tag].append(d)
    return out


def demand_by_theme(signals, tags):
    """`{tag: (demand, source)}`: the qualitative pass's `demand` where written,
    else a proxy from count and relevance, so the query runs on day one."""
    per = signals.get("per_theme", {}) or {}
    out = {}
    for t in tags:
        row = per.get(t, {}) or {}
        if row.get("demand") is not None:
            out[t] = (float(row["demand"]), "qualitative")
        else:
            try:
                out[t] = (round(float(row.get("count", 0) or 0) * float(row.get("relevance", 0) or 0) / 10.0, 2), "proxy")
            except (TypeError, ValueError):
                out[t] = (0.0, "proxy")
    return out


def depth_by_theme(signals, engagement, tags):
    """Conversation-shaped findings plus substantive replies per theme."""
    out = {t: 0 for t in tags}
    for f in signals.get("findings", []) or []:
        t = f.get("theme")
        conv = f.get("conversation")
        if t in out and conv and str(conv).strip().lower() not in ("none", "null", "", "{}"):
            out[t] += 1
    for r in engagement.get("records", []) or []:
        t = r.get("theme")
        if t in out:
            out[t] += int(((r.get("at_7d") or r.get("at_72h") or {}).get("substantive_replies") or 0))
    return out


def freshness_by_theme(register, changes, pieces, tags, today):
    """Rows added or changed on the theme since its last piece (or in the window)."""
    out = {}
    for t in tags:
        last = max(pieces.get(t) or [today - dt.timedelta(days=WINDOW_DAYS)])
        since = last
        rows = [r for r in register.values() if t in r["themes"] and not r["superseded_by"]]
        new = [r["id"] for r in rows if (_date(r["date"]) or dt.date.min) > since]
        ids = {r["id"] for r in rows}
        changed = sorted({c["id"] for c in changes if c["id"] in ids and (_date(c["seen_at"]) or dt.date.min) > since})
        out[t] = {"new": new, "changed": [c for c in changed if c not in new], "since": since.isoformat()}
    return out


# --- the draw: a format and a logic per draft --------------------------------------

def past_scores(records, stream_name):
    """`({format: [score]}, {(format, logic): [score]})` from the scored predictions of a stream."""
    by_format, by_combo = {}, {}
    for r in records or []:
        if r.get("stream") != stream_name or r.get("actual") not in BAND_SCORE:
            continue
        fmt = memory.DEFAULT_FORMAT if r.get("format") in LEGACY_FORMATS else str(r.get("format"))
        score = BAND_SCORE[r["actual"]]
        by_format.setdefault(fmt, []).append(score)
        by_combo.setdefault((fmt, str(r.get("logic") or "")), []).append(score)
    return by_format, by_combo


def _proven(scores):
    return len(scores) >= MIN_PROVEN and statistics.mean(scores) >= BAND_SCORE["baseline"]


def kind_of(fmt, logic, by_format, by_combo):
    """`proven`, `variation` or `experiment` for one format and logic (livetests.KINDS)."""
    if _proven(by_combo.get((fmt, logic), [])):
        return "proven"
    if _proven(by_format.get(fmt, [])):
        return "variation"
    return "experiment"


def draw_seed(stream, theme, day, slot=1):
    return f"{stream}:{theme}:{day.isoformat()}:{slot}"


def draw(formats, logics, records, stream_name, seed, licence=""):
    """One format and one logic for a draft, by weighted draw inside the 60/25/15 budget.

    `formats` is memory.load_formats(), `logics` the theme's logics (may be empty),
    `records` state/predictions.json. A format that needs evidence is left out for a theme
    whose licence is `held`. Returns `{format, logic, kind, seed, weight, pool}`; `pool` is
    how many candidates each kind had, so a person can see what the draw chose among.
    Deterministic for a seed.
    """
    import livetests
    by_format, by_combo = past_scores(records, stream_name)
    held = str(licence).strip().lower() == "held"
    pools = {k: [] for k in livetests.KINDS}
    for fmt, spec in formats.items():
        if held and spec.get("needs_evidence"):
            continue
        for logic in (logics or [""]):
            seen = by_combo.get((fmt, logic)) or by_format.get(fmt)
            weight = float(spec.get("weight", 1)) * (statistics.mean(seen) if seen else 1.0)
            pools[kind_of(fmt, logic, by_format, by_combo)].append((fmt, logic, round(weight, 3)))
    live = [k for k in livetests.KINDS if pools[k]]
    if not live:
        raise memory.SharedMemoryError("no format can be drawn: every format needs evidence and the theme is held")
    rng = random.Random(seed)
    kind = rng.choices(live, weights=[livetests.BUDGET[k] for k in live])[0]
    fmt, logic, weight = rng.choices(pools[kind], weights=[c[2] for c in pools[kind]])[0]
    return {"format": fmt, "logic": logic, "kind": kind, "seed": seed, "weight": weight,
            "pool": {k: len(pools[k]) for k in livetests.KINDS}}


def draw_for(stream, theme, state=None, today=None, slot=1, records=None):
    """The draw for one theme of a stream on a day; `slot` gives a second draft its own."""
    import predictions
    state = state or STATE
    today = today or dt.date.today()
    row = memory.stream(stream)
    spec = next((t for t in memory.load_themes(stream) if t["tag"] == theme), None)
    if spec is None:
        raise memory.SharedMemoryError(f"{theme} is not a theme of the {stream} stream")
    records = predictions.load(state) if records is None else records
    out = draw(memory.load_formats(stream), spec.get("logics") or [], records, row["name"],
               draw_seed(stream, theme, today, slot), licence=spec.get("licence", ""))
    out["at"] = today.isoformat()
    return out


def run(stream=memory.DEFAULT_STREAM, state=None, cal=None, today=None, register=None, signals=None, engagement=None, changes=None):
    state = state or STATE
    today = today or dt.date.today()
    row = memory.stream(stream)
    tags = memory.theme_tags(stream)
    register = memory.load_claims(stream) if register is None else register
    signals = _load(os.path.join(state, "signals.json"), {}) if signals is None else signals
    engagement = _load(os.path.join(state, "engagement.json"), {}) if engagement is None else engagement
    changes = _load(os.path.join(state, "claims-changes.json"), []) if changes is None else changes
    pieces = pieces_by_theme(row["name"], tags, cal, today)
    demand = demand_by_theme(signals, tags)
    depth = depth_by_theme(signals, engagement, tags)
    fresh = freshness_by_theme(register, changes, pieces, tags, today)
    themes = {}
    for t in tags:
        recent = [d for d in pieces[t] if (today - d).days <= WINDOW_DAYS]
        gaps = round(demand[t][0] / (1 + len(recent)), 2)
        f = len(fresh[t]["new"]) + len(fresh[t]["changed"])
        themes[t] = {
            "gaps": {"score": gaps, "demand": demand[t][0], "demand_source": demand[t][1], "pieces_in_window": len(recent)},
            "freshness": {"score": f, **fresh[t]},
            "depth": {"score": depth[t], "partial": not (engagement.get("records"))},
        }
        best = max(QUERIES, key=lambda q: themes[t][q]["score"])
        themes[t]["answer"] = best if themes[t][best]["score"] > 0 else "none"
        try:
            themes[t]["draw"] = draw_for(stream, t, state=state, today=today)
        except (memory.SharedMemoryError, RuntimeError, ValueError) as e:
            # a draw that cannot be made is said on the plan; the writer then writes a theme post
            themes[t]["draw"] = {"format": memory.DEFAULT_FORMAT, "logic": "", "kind": "proven", "seed": "", "error": str(e)}
    # the suggestion order: strongest signal first, across queries
    order = sorted(tags, key=lambda t: -max(themes[t][q]["score"] for q in QUERIES))
    return {"stream": row["name"], "queries": "files", "window_days": WINDOW_DAYS,
            "run_at": today.isoformat(), "order": order, "themes": themes}


def table(out):
    lines = [f"{'theme':<22} {'gaps':>6} {'fresh':>6} {'depth':>6}  {'answers':<10} draw"]
    for t in out["order"]:
        x = out["themes"][t]
        d = x.get("draw") or {}
        how = f"{d.get('format', '-')}" + (f" + {d['logic']}" if d.get("logic") else "") + (f" ({d['kind']})" if d.get("kind") else "")
        lines.append(f"{t:<22} {x['gaps']['score']:>6} {x['freshness']['score']:>6} {x['depth']['score']:>6}  {x['answer']:<10} {how}")
    lines.append(f"queries: {out['queries']}  (demand {', '.join(sorted({x['gaps']['demand_source'] for x in out['themes'].values()}))}; depth {'partial' if any(x['depth']['partial'] for x in out['themes'].values()) else 'full'})")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="gaps, freshness and depth per theme")
    ap.add_argument("--stream", default=memory.DEFAULT_STREAM)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--state", default=STATE)
    ap.add_argument("--draw", metavar="THEME", help="print one draw (format, logic, kind, seed) for this theme and stop")
    ap.add_argument("--slot", type=int, default=1, help="with --draw: which draft of the day on this theme (default 1)")
    a = ap.parse_args(argv)
    if a.draw:
        try:
            print(json.dumps(draw_for(a.stream, a.draw, state=a.state, slot=a.slot), indent=1))
        except (memory.SharedMemoryError, RuntimeError) as e:
            print(f"plan_queries: {e}", file=sys.stderr)
            return 2
        return 0
    try:
        out = run(a.stream, a.state)
    except memory.SharedMemoryError as e:
        print(f"plan_queries: {e}", file=sys.stderr)
        return 2
    print(table(out))
    if not a.dry_run:
        path = os.path.join(a.state, "planning.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
            f.write("\n")
        print(f"wrote {os.path.relpath(path, repo.REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
