#!/usr/bin/env python3
"""
score.py - scoring at 72 hours and 7 days (plan v2, item A9).

For every published item of a stream, read what the engine can see of its
reception, weight it by intent, log negatives, normalise against the stream's
own baseline for that platform and format, strip identifiers, and write the
record into `state/engagement.json` (`records`) and the actual band into
`state/predictions.json`. Until the LinkedIn and X logins exist (Block C) the
record is marked `partial`: it is computed from listening and from numbers a
person typed in, not from platform analytics.

Where the numbers come from, all local files, no network call:

  state/metrics-input/<item id>.json   numbers a person read off the platform
                                       (the shape below); the only full source
                                       today. One file per item, `at` per read.
  state/x-stream/<date>.jsonl          posts the twitterapi.io stream matched:
                                       replies to and quotes of our X post ids.
  state/listening-*.json               Apify passes: items quoting our post URL.

  {"reads": [{"at": "2026-10-10T08:00:00+00:00", "platform": "X",
              "impressions": 1200, "likes": 14, "reposts": 3, "quotes": 2,
              "replies": 5, "substantive_replies": 2, "saves": 1,
              "link_clicks": 9, "profile_clicks": 4,
              "negatives": {"unfollows": 0, "hides": 0, "corrections": 1}}]}

Sources are labelled apart on every window: "platform read" (typed in), "public counts"
(twitterapi.io, partial) and "official analytics" (`source: composio`, the platform's own
numbers through channels.metrics). Impressions are a CHANGE OF MEASURE between the last two:
twitterapi.io's view count is public, the analytics impression count is the platform's own,
so a window that holds both carries `impressions_measure` and the two are not compared.

Weights (the guide's intent ladder): saves, quote posts, substantive replies,
link and profile clicks 3; reposts 2; likes 1; impressions 0 (context);
negatives counted apart as the guardrail. `score` is the weighted sum;
`baseline` is the median score of the stream's earlier records on the same
platform and format once three exist; `index` is score over baseline;
the `actual` band is below (< 0.75), baseline, above (> 1.25).

Published items are read from the vault (`published_at` on an engine note)
and from the autopilot's ledgers (`state/publish-log.json`,
`state/send-ledger.json`); their id is the queue id when the title matches,
else the page id.

  engine score            # score what is due, write
  engine score --dry-run  # print, write nothing
  engine score --demand   # also write demand per theme into signals.json
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
REPO = paths.instance()
STATE = paths.state()


def _merged_log(state_path):
    """The autopilot's publish log, entries de-duplicated by page_id, target and time."""
    out, seen = {"entries": []}, set()
    for e in (_load(state_path, {}) or {}).get("entries", []) or []:
        key = (e.get("page_id"), e.get("target"), e.get("published_at"))
        if key not in seen:
            seen.add(key)
            out["entries"].append(e)
    return out


def _merged_ledger(state_path):
    """The send ledger, keyed by page id."""
    return {"sends": dict((_load(state_path, {}) or {}).get("sends", {}) or {})}
sys.path.insert(0, HERE)
import memory  # noqa: E402
import predictions  # noqa: E402
import repo  # noqa: E402
import runlog  # noqa: E402

WEIGHTS = {"saves": 3, "quotes": 3, "substantive_replies": 3, "link_clicks": 3, "profile_clicks": 3,
           # a repost or quote by a cleared partner handle (A17): the Partners
           # amplify key result, counted as the high-intent signal it is
           "partner_reposts": 3,
           "reposts": 2, "likes": 1}
CONTEXT = ("impressions", "replies")
NEGATIVES = ("unfollows", "hides", "corrections")
WINDOWS = {"at_72h": dt.timedelta(hours=72), "at_7d": dt.timedelta(days=7)}
BASELINE_MIN = 3
BAND_LOW, BAND_HIGH = 0.75, 1.25
# `x.com/<handle>/status/<id>` and the autopilot's `x.com/i/web/status/<id>` alike.
X_STATUS = re.compile(r"(?:x\.com|twitter\.com)/(?:i/web|[^/\s]+)/status/(\d+)")


def _parse(ts):
    if not ts:
        return None
    try:
        d = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


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


# ── what was published ──────────────────────────────────────────────────────

#: Publish-log entries that are a publication rather than a row creation:
#: a post on a handle (`linkedin`, `x`, written when the autopilot sent it) or
#: a Blog row set Published. Entries at `Idea` or `Ready` record a calendar
#: row being created, and nothing went out.
def _is_publication(entry):
    target = str(entry.get("target", ""))
    return target in ("linkedin", "x") or str(entry.get("state", "")) == "Published"


def published_items(stream_name=memory.DEFAULT_STREAM_NAME, items=None, publish_log=None, ledger=None, queue=None):
    """`[{id, stream, theme, title, platform, format, published_at, urls}]`.

    Vault engine notes with `published_at` first; then the autopilot's real
    publications (`_is_publication`), joined to the drafting queue by the entry's
    `id` where it carries one, else by title, for the theme and the id. The
    earliest publication of an item is its `published_at`; every post URL is
    kept so listening can find replies and quotes to any of them.
    """
    out = {}
    for it in (repo.load_items() if items is None else items):
        if it.get("published_at") and it.get("stream") == stream_name:
            out[it["id"]] = {"id": it["id"], "stream": stream_name, "theme": it.get("theme", ""),
                             "title": it.get("title", ""), "platform": (it.get("slot") or {}).get("platform", "Blog"),
                             "format": it.get("format", ""), "published_at": it["published_at"],
                             "urls": [u for u in [it.get("cta", "")] if u]}
    log = _merged_log(os.path.join(STATE, "publish-log.json")) if publish_log is None else publish_log
    q = _load(os.path.join(STATE, "queue.json"), []) if queue is None else queue
    qitems = [i for i in (q.get("items", q) if isinstance(q, dict) else q) if isinstance(i, dict)]
    by_id = {str(i.get("id", "")): i for i in qitems}
    by_title = {str(i.get("title", "")).strip().lower(): i for i in qitems}

    def join(entry):
        qi = by_id.get(str(entry.get("id", ""))) or by_title.get(str(entry.get("title", "")).strip().lower())
        if qi and str(qi.get("stream", memory.DEFAULT_STREAM_NAME)) != stream_name:
            return None, None
        return qi, (qi["id"] if qi else entry.get("page_id", ""))

    def add(iid, qi, title, url, when):
        rec = out.setdefault(iid, {"id": iid, "stream": stream_name, "theme": (qi or {}).get("theme", ""),
                                   "title": title or (qi or {}).get("title", ""), "platform": "Blog",
                                   "format": "", "published_at": when, "urls": []})
        for u in (url, (qi or {}).get("cta", "")):
            if u and u not in rec["urls"]:
                rec["urls"].append(u)
        pa, cur = _parse(when), _parse(rec["published_at"])
        if pa and (not cur or pa < cur):
            rec["published_at"] = when

    for e in (log.get("entries", []) if isinstance(log, dict) else log) or []:
        if not _is_publication(e):
            continue
        qi, iid = join(e)
        if iid:
            add(iid, qi, str(e.get("title", "")).strip(), e.get("url", "") if e.get("target") in ("linkedin", "x") else "",
                e.get("published_at", ""))
    led = _merged_ledger(os.path.join(STATE, "send-ledger.json")) if ledger is None else ledger
    for s_ in (led.get("sends", {}) or {}).values():
        if s_.get("state") != "sent" or not s_.get("url"):
            continue
        qi, iid = join(s_)
        if iid:
            add(iid, qi, str(s_.get("title", "")).strip(), s_["url"], s_.get("at", ""))
    return [r for r in out.values() if _parse(r["published_at"])]


def x_ids(urls):
    return {m.group(1) for u in urls for m in [X_STATUS.search(u or "")] if m}


# ── what was seen ───────────────────────────────────────────────────────────

def manual_reads(item_id, state):
    data = _load(os.path.join(state, "metrics-input", f"{item_id}.json"), {})
    return [r for r in data.get("reads", []) if isinstance(r, dict)]


def partner_handles(stream=memory.DEFAULT_STREAM):
    """The cleared partners' X handles, lower-cased, for counting only."""
    try:
        rows = memory.load_handles(stream)["cleared_partners"]
    except memory.SharedMemoryError:
        return set()
    return {str(r.get("x", "")).lstrip("@").lower() for r in rows if str(r.get("x", "")).startswith("@")}


def stream_reactions(ids, urls, state, until, partners=frozenset()):
    """Replies, quotes and partner reposts seen by the x-stream and the Apify
    passes before `until`: counts only, no author, no text kept."""
    counts = {"replies": 0, "quotes": 0, "partner_reposts": 0}
    for path in sorted(glob.glob(os.path.join(state, "x-stream", "*.jsonl"))):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    p = json.loads(line)
                except ValueError:
                    continue
                when = _parse(p.get("createdAt") or p.get("created_at"))
                if when and when > until:
                    continue
                if str(p.get("inReplyToId") or p.get("in_reply_to_status_id") or "") in ids:
                    counts["replies"] += 1
                q = p.get("quoted_tweet") or p.get("quotedTweet") or {}
                rt = p.get("retweeted_tweet") or p.get("retweetedTweet") or {}
                author = str(((p.get("author") or {}).get("userName") or (p.get("author") or {}).get("screen_name") or "")).lstrip("@").lower()
                if str((q or {}).get("id") or "") in ids:
                    counts["quotes"] += 1
                    if author in partners:
                        counts["partner_reposts"] += 1
                if str((rt or {}).get("id") or "") in ids and author in partners:
                    counts["partner_reposts"] += 1
    for path in sorted(glob.glob(os.path.join(state, "listening-*.json"))):
        data = _load(path, {})
        for it in data.get("items", []) or []:
            when = _parse(it.get("created_at"))
            if when and when > until:
                continue
            text = it.get("text") or ""
            if any(u and u in text for u in urls) or any(f"/status/{i}" in text for i in ids):
                counts["quotes"] += 1
    return counts


def window_record(item, state, now, window, published_at):
    """The counts for one window, or None when the window has not closed."""
    end = published_at + window
    if now < end:
        return None
    counts = {k: 0 for k in list(WEIGHTS) + list(CONTEXT)}
    negatives = {k: 0 for k in NEGATIVES}
    source = []
    reads = [r for r in manual_reads(item["id"], state) if _parse(r.get("at")) and _parse(r["at"]) <= end]
    if reads:
        # the latest read before the window closed, per platform, summed
        latest = {}
        for r in sorted(reads, key=lambda r: _parse(r["at"])):
            latest[r.get("platform", "")] = r
        for r in latest.values():
            for k in counts:
                counts[k] += int(r.get(k) or 0)
            for k in negatives:
                negatives[k] += int((r.get("negatives") or {}).get(k) or 0)
        # A read typed in from the platform's own analytics is full; public
        # counts from twitterapi.io (x_metrics.py) carry no clicks and no
        # reply substance, so they stay partial. The official analytics read
        # through Composio (`source: composio`) is the platform's own number,
        # labelled apart: its impressions are a CHANGE OF MEASURE from the
        # public view count, so the two are never silently compared.
        srcs = {r.get("source") for r in latest.values()}
        if srcs - {"twitterapi.io", "composio"}:
            source.append("platform read")
        if "composio" in srcs:
            source.append("official analytics")
        if "twitterapi.io" in srcs:
            source.append("public counts")
    seen = stream_reactions(x_ids(item["urls"]), item["urls"], state, end, partner_handles())
    counts["partner_reposts"] += seen["partner_reposts"]
    if not reads:
        counts["replies"] += seen["replies"]
        counts["quotes"] += seen["quotes"]
    if seen["replies"] or seen["quotes"]:
        source.append("listening")
    score = sum(WEIGHTS[k] * counts[k] for k in WEIGHTS)
    return {"closed_at": end.isoformat(timespec="seconds"), **counts, "negatives": negatives,
            "negatives_total": sum(negatives.values()), "score": score,
            "source": source or ["none"], "partial": not ({"platform read", "official analytics"} & set(source)),
            **({"impressions_measure": "mixed: public views and analytics impressions, do not compare"}
               if {"official analytics", "public counts"} <= set(source) else {})}


def baseline_for(records, platform, fmt, exclude_id):
    scores = [r["score"] for r in records
              if r.get("id") != exclude_id and r.get("platform") == platform and r.get("format", "") == fmt
              and r.get("score") is not None]
    return round(statistics.median(scores), 2) if len(scores) >= BASELINE_MIN else None


def band(index):
    if index is None:
        return None
    return "below" if index < BAND_LOW else "above" if index > BAND_HIGH else "baseline"


def score_all(stream=memory.DEFAULT_STREAM, state=None, now=None, items=None, publish_log=None, ledger=None, queue=None, dry_run=False):
    """Score every published item whose window has closed, in two passes.

    Pass one fills the 72 h and 7 d windows. Pass two computes each record's
    baseline from the stream's other records on the same platform and format,
    the index and the band, and writes the actual beside the prediction. The
    second pass runs over every record, not only the ones touched tonight, so
    a piece scored before three others existed gets its baseline, and its
    actual, as soon as they do. A window already full is never rewritten.
    """
    state = state or STATE
    now = now or dt.datetime.now(dt.timezone.utc)
    row = memory.stream(stream)
    eng = _load(os.path.join(state, "engagement.json"), {})
    records = [r for r in eng.get("records", []) or [] if isinstance(r, dict)]
    by_id = {r["id"]: r for r in records if r.get("id")}
    done = set()
    for item in published_items(row["name"], items, publish_log, ledger, queue):
        pa = _parse(item["published_at"])
        rec = by_id.get(item["id"])
        if rec is None:
            rec = {"id": item["id"], "stream": row["name"], "theme": item["theme"], "title": item["title"],
                   "platform": item["platform"], "format": item["format"], "published_at": item["published_at"]}
            records.append(rec)
            by_id[item["id"]] = rec
            done.add(item["id"])
        for key, window in WINDOWS.items():
            if rec.get(key) and not rec[key].get("partial"):
                continue  # a full window is never rewritten
            w = window_record(item, state, now, window, pa)
            if w and w != rec.get(key):
                rec[key] = w
                done.add(item["id"])

    preds = {p["id"]: p for p in predictions.load(state)}
    for rec in records:
        if rec.get("stream", row["name"]) != row["name"]:
            continue
        final = rec.get("at_7d") or rec.get("at_72h")
        if not final:
            continue
        others = [r for r in records if r.get("id") != rec["id"] and (r.get("at_7d") or r.get("at_72h"))]
        for o in others:
            o.setdefault("score", (o.get("at_7d") or o.get("at_72h"))["score"])
        before = (rec.get("baseline"), rec.get("index"))
        rec["score"] = final["score"]
        rec["baseline"] = baseline_for(others, rec.get("platform"), rec.get("format", ""), rec["id"])
        rec["index"] = round(rec["score"] / rec["baseline"], 2) if rec["baseline"] else None
        rec["partial"] = bool(final["partial"]) or rec["baseline"] is None
        rec["negatives_total"] = final["negatives_total"]
        if (rec["baseline"], rec["index"]) != before:
            done.add(rec["id"])
        if rec["id"] in done:
            rec["scored_at"] = now.isoformat(timespec="seconds")
        p = preds.get(rec["id"])
        if rec.get("at_7d") and p is not None and not dry_run:
            b = band(rec["index"])
            if (p.get("actual"), p.get("index"), p.get("score"), p.get("partial")) != (b, rec["index"], rec["score"], rec["partial"]):
                predictions.set_actual(rec["id"], b, score=rec["score"], index=rec["index"],
                                       partial=rec["partial"], state=state, now=now)
    eng["records"] = records
    eng.setdefault("stream", row["name"])
    if not dry_run:
        _write(os.path.join(state, "engagement.json"), eng)
    return records, sorted(done)


def demand(stream=memory.DEFAULT_STREAM, state=None, dry_run=False):
    """`demand` per theme into `signals.json` per_theme: conversation-shaped
    findings plus substantive replies and quotes on the theme's scored items.
    Counts only; no handle is read or written."""
    state = state or STATE
    sig = _load(os.path.join(state, "signals.json"), {})
    eng = _load(os.path.join(state, "engagement.json"), {})
    per = sig.setdefault("per_theme", {})
    tags = memory.theme_tags(stream)
    out = {}
    for t in tags:
        d = 0
        for f in sig.get("findings", []) or []:
            conv = f.get("conversation")
            if f.get("theme") == t and conv and str(conv).strip().lower() not in ("none", "null", "", "{}"):
                d += 1
        for r in eng.get("records", []) or []:
            if r.get("theme") == t:
                w = r.get("at_7d") or r.get("at_72h") or {}
                d += int(w.get("substantive_replies") or 0) + int(w.get("quotes") or 0)
        per.setdefault(t, {})["demand"] = d
        per[t]["demand_source"] = "qualitative" if eng.get("records") else "listening"
        out[t] = d
    if not dry_run:
        _write(os.path.join(state, "signals.json"), sig)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="score published items at 72 h and 7 days")
    ap.add_argument("--stream", default=memory.DEFAULT_STREAM)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--demand", action="store_true", help="also write demand per theme into signals.json")
    ap.add_argument("--state", default=STATE)
    a = ap.parse_args(argv)
    try:
        records, done = score_all(a.stream, a.state, dry_run=a.dry_run)
    except memory.SharedMemoryError as e:
        print(f"score: {e}", file=sys.stderr)
        return 2
    partial = sum(1 for r in records if r.get("partial"))
    detail = f"score: {len(done)} item(s) scored or updated, {len(records)} record(s), {partial} partial"
    print(detail)
    for r in records:
        if r["id"] in done:
            print(f"  {r['id']:<40} score {r.get('score')}  baseline {r.get('baseline')}  index {r.get('index')}"
                  f"  neg {r.get('negatives_total', 0)}  {'partial' if r.get('partial') else 'full'}")
    if a.demand:
        d = demand(a.stream, a.state, a.dry_run)
        print("demand: " + ", ".join(f"{t} {v}" for t, v in d.items()))
    if not a.dry_run:
        runlog.append("score", detail, stream=memory.stream(a.stream)["name"],
                      runs_path=os.path.join(a.state, "runs.json"), items=len(done))
    return 0


if __name__ == "__main__":
    sys.exit(main())
