#!/usr/bin/env python3
"""
x_metrics.py - public counts for our own X posts, before the scorer runs.

Until the X login exists (plan v2, Block C) the scorer has no platform
analytics. twitterapi.io's lookup returns each post's public counts: views,
likes, reposts, quotes, replies and bookmarks. This script reads them for every
published item whose 7-day window has not long closed and appends one read per
item to `state/metrics-input/<id>.json`, marked `source: twitterapi.io`, which
`score.py` labels "public counts": better than listening, still partial,
because link clicks, profile clicks and the substance of a reply are not in
public counts.

When the stream's effective own-reads driver is composio (`channels.x_own.<stream>` set and
`params.listen.x_own_price_signoff` recorded; listening's `x_read` driver is a separate class), the read comes from `channels.metrics`: the official
analytics, marked `source: composio`, which `score.py` labels "official analytics". The
impressions there are a different measure from twitterapi.io's public view count. A
composio read that fails falls back to twitterapi.io and is logged. LinkedIn share stats
are read only when the stream's LinkedIn composio account is linked; unlinked, they are
skipped and logged, and nothing else changes.

Counts only: no author, no text, no handle is written.

  engine x_metrics            # look up and write
  engine x_metrics --dry-run  # say which posts, call nothing
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
sys.path.insert(0, HERE)
import channels  # noqa: E402
import memory  # noqa: E402
import runlog  # noqa: E402
import score  # noqa: E402
import twitterapi  # noqa: E402

#: Look a post up while its windows are open, plus one day to catch the 7-day read.
LOOKUP_DAYS = 8


def due(items, now):
    """`[(item id, [x ids])]` for published items inside the lookup window."""
    out = []
    for it in items:
        pa = score._parse(it.get("published_at"))
        ids = sorted(score.x_ids(it.get("urls") or []))
        if pa and ids and dt.timedelta(0) <= now - pa <= dt.timedelta(days=LOOKUP_DAYS):
            out.append((it["id"], ids))
    return out


LI_URN = re.compile(r"urn:li:(?:share|ugcPost|activity):\d+")


def linkedin_due(items, now):
    """`[(item id, [share URNs])]` for published items with a LinkedIn post inside the lookup window."""
    out = []
    for it in items:
        pa = score._parse(it.get("published_at"))
        urns = sorted({m.group(0) for u in it.get("urls") or [] for m in [LI_URN.search((u or "").replace("%3A", ":"))] if m})
        if pa and urns and dt.timedelta(0) <= now - pa <= dt.timedelta(days=LOOKUP_DAYS):
            out.append((it["id"], urns))
    return out


def read_from(tweets, now):
    """One read, summed over the item's X posts, in the metrics-input shape."""
    r = {"at": now.isoformat(timespec="seconds"), "platform": "X", "source": "twitterapi.io",
         "impressions": 0, "likes": 0, "reposts": 0, "quotes": 0, "replies": 0, "saves": 0}
    for t in tweets:
        r["impressions"] += int(t.get("viewCount") or 0)
        r["likes"] += int(t.get("likeCount") or 0)
        r["reposts"] += int(t.get("retweetCount") or 0)
        r["quotes"] += int(t.get("quoteCount") or 0)
        r["replies"] += int(t.get("replyCount") or 0)
        r["saves"] += int(t.get("bookmarkCount") or 0)
    r["posts"] = len(tweets)
    return r


def append_read(state, item_id, read):
    d = os.path.join(state, "metrics-input")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{item_id}.json")
    data = {"reads": []}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    data.setdefault("reads", []).append(read)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
        f.write("\n")
    os.replace(tmp, p)
    return p


def run(stream=memory.DEFAULT_STREAM, state=None, now=None, items=None, key=None, opener=None, dry_run=False,
        driver=None, linked=None, runs_path=None):
    state = state or STATE
    now = now or dt.datetime.now(dt.timezone.utc)
    row = memory.stream(stream)
    items = score.published_items(row["name"]) if items is None else items
    todo = due(items, now)
    li_todo = linkedin_due(items, now)
    driver = driver or channels.effective_x_own(stream)[0]
    out = {"due": todo, "written": [], "missing": [], "driver": driver,
           "linkedin_due": li_todo, "linkedin_written": [], "linkedin_skipped": ""}
    if dry_run:
        return out
    runs_path = runs_path or os.path.join(state, "runs.json")
    if li_todo:
        if linked is None:
            linked = channels.linkedin_linked(stream)
        if not linked:
            out["linkedin_skipped"] = "no linked LinkedIn composio account"
        else:
            for item_id, urns in li_todo:
                try:
                    read = channels.metrics(stream, "linkedin", urns, now=now)
                except channels.ChannelError as exc:
                    out["linkedin_skipped"] = str(exc)[:200]
                    break
                if read:
                    append_read(state, item_id, read)
                    out["linkedin_written"].append(item_id)
    if not todo:
        return out
    pending = list(todo)
    if driver == "composio":
        rest = []
        for n, (item_id, ids) in enumerate(pending):
            try:
                read = channels.metrics(stream, "x", ids, now=now)
            except channels.ChannelError as exc:
                channels._log_fallback(stream, f"own-post metrics: {exc}", runs_path)
                rest = pending[n:]
                break
            if read:
                append_read(state, item_id, read)
                out["written"].append(item_id)
            else:
                out["missing"].append(item_id)
        pending = rest
    if pending:
        key = key or twitterapi.load_key(stream if stream != memory.DEFAULT_STREAM else None)
        found = twitterapi.lookup(key, [i for _, ids in pending for i in ids], opener=opener)
        for item_id, ids in pending:
            tweets = [found[i] for i in ids if i in found]
            if not tweets:
                out["missing"].append(item_id)
                continue
            append_read(state, item_id, read_from(tweets, now))
            out["written"].append(item_id)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="public counts for our own X posts")
    ap.add_argument("--stream", default=memory.DEFAULT_STREAM)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--state", default=STATE)
    a = ap.parse_args(argv)
    try:
        out = run(a.stream, a.state, dry_run=a.dry_run)
    except (memory.SharedMemoryError, twitterapi.TwitterAPIError, channels.ChannelError) as e:
        print(f"x_metrics: {e}", file=sys.stderr)
        return 2
    posts = sum(len(ids) for _, ids in out["due"])
    detail = (f"x_metrics: {len(out['due'])} item(s) in the window, {posts} X post(s); "
              f"{len(out['written'])} read(s) written, {len(out['missing'])} not found")
    print(detail + (" (dry run, nothing called)" if a.dry_run else ""))
    for item_id, ids in out["due"]:
        print(f"  {item_id:<40} {', '.join(ids)}")
    if out["linkedin_due"]:
        print(f"x_metrics: {len(out['linkedin_due'])} LinkedIn item(s) in the window; read only when a LinkedIn "
              f"composio account is linked" + (f" (skipped: {out['linkedin_skipped']})" if out["linkedin_skipped"] else ""))
    if not a.dry_run and (out["due"] or out["linkedin_due"]):
        if out["linkedin_skipped"]:
            detail += f"; linkedin skipped: {out['linkedin_skipped']}"
        runlog.append("x-metrics", detail, stream=memory.stream(a.stream)["name"],
                      runs_path=os.path.join(a.state, "runs.json"), items=len(out["written"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
