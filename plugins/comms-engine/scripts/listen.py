#!/usr/bin/env python3
"""
listen.py - Beta pipeline 5: "monitoring of themes and mentions".

Runs one listening pass over X - and, only when asked, LinkedIn - for every
theme in `.atelier/memory/themes.md` (one search term per theme, processed
separately), normalises the results, machine-prescores relevance and sentiment
per theme, and writes:

  state/raw/<stream>/x-<timestamp>.json        everything the X actor returned
  state/raw/<stream>/linkedin-<timestamp>.json everything the LinkedIn actors returned
  state/listening-<timestamp>.json    the normalised, prescored items

The prescore is a hint for the listener agent, never a verdict. Reading
"relevance and sentiment into content decisions" is an Alpha act (Principles
s5); the theme-listening skill does the reading and writes state/signals.json.

The theme roster, and every fact about a theme other than how to search for it,
come from `.atelier/memory/themes.md` through scripts/memory.py - the single
source of them. themes.json holds only the
engine-local search material per theme - the X advanced-search term, the
LinkedIn search-bar string and the keyword set - joined to the roster by tag: a
theme with no search term, or a term with no theme row, is an error.

Two corrections this script carries since the 2026-09-07 pass:

  * **The `--days` window is enforced here, not trusted to the actor.** On a
    low-volume term the X actor ignores `since_time` and backfills older posts:
    35 of the 180 items in the 2026-09-07 pass predated their own window. Every
    item's timestamp is now parsed and the item dropped if it is older than the
    window, or if the timestamp cannot be read at all - an item whose age
    cannot be shown is not evidence that it is inside the window. The count
    lands in `dropped_stale`.

  * **LinkedIn sits behind `--linkedin`.** The X actor charges USD 0.00018-0.00025
    per tweet; the two harvestapi actors charge USD 0.0015-0.002 per post, and
    post-search bills a second event of the same size for the author profile
    attached to each result - about sixteen times the X rate per item. So a
    default pass, and therefore every scheduled run, calls neither of them.

Source for X: twitterapi.io's advanced search (`scripts/twitterapi.py`), by
owner decision of 2026-10-26 ("stick to twitterapi for x"). USD 0.15 per 1,000
tweets returned, billed per page of up to 20 and at least one tweet a call, so a
default pass of nine terms at `--max 12` costs at most 180 tweets, about USD
0.03. The Apify X actor used until then is retired for X; Apify stays for
LinkedIn only.
With `--linkedin`, harvestapi/linkedin-post-search adds one call per theme and
harvestapi/linkedin-company-posts one call over the verified LinkedIn rows in
`.atelier/memory/handles.md` - see the cost note below before turning it on.

Usage:
  python3 listen.py                 # full pass, all themes + mentions, X only
  python3 listen.py --max 8         # fewer items per term
  python3 listen.py --themes "#ExampleTheme,#SecondTheme"
  python3 listen.py --dry-run       # print the queries, call nothing
  python3 listen.py --days 3        # look-back window (default 7)
  python3 listen.py --linkedin      # add the two paid LinkedIn actors

Keys: resolved by scripts/secrets.py - TWITTERAPI_IO_API_KEY for X, and
APIFY_TOKEN only when --linkedin is given - in the environment, else the macOS
keychain item (the brand's service, account = the key's name). No key is read
from a file.
"""
import argparse
import datetime as dt
import email.utils
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import channels
import memory
import secrets
import twitterapi

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
REPO = paths.instance()
STATE = paths.state()
X_SOURCE = "twitterapi.io advanced_search"
# Most-engaged first, not newest first. At 12 items a term, newest first samples
# the last few hours of a seven-day window (the first live pass saw two hours
# of one theme); what is new arrives through the stream.
X_ORDER = "Top"
#: the most items one term may ask for, whichever driver reads it
MAX_PER_TERM = 12
LINKEDIN_SEARCH_ACTOR = "harvestapi~linkedin-post-search"
LINKEDIN_COMPANY_ACTOR = "harvestapi~linkedin-company-posts"

POS = ["clear", "useful", "finally", "progress", "welcome", "good", "great", "strong", "adopt", "launch", "live", "support"]
NEG = ["scam", "fail", "failed", "hack", "exploit", "ban", "banned", "fine", "fined", "warning", "risk", "collapse", "lawsuit", "fraud", "bad", "broken", "concern", "worse"]


def load_token():
    """The Apify token (LinkedIn only), only ever through scripts/secrets.py.

    This script does not know where a token is stored and must not learn: the
    chain (environment, then the macOS keychain) lives in one place so a later
    sovereign store is a change there and nowhere else.
    """
    try:
        return secrets.get_secret("APIFY_TOKEN")
    except secrets.SecretNotFound as e:
        sys.exit(f"ERROR: {e}")


def terms_file(stream=None):
    """The engine-local search file: `themes.json` for the root stream, `streams/<slug>/themes.json` otherwise."""
    if stream in (None, memory.DEFAULT_STREAM):
        return os.path.join(REPO, "themes.json")
    return os.path.join(REPO, "streams", stream, "themes.json")


def ignored(text, keywords):
    """True when a result names another stream (themes.json `ignore`): a
    stream's listening is that stream's only, so a post about another one is
    dropped, not scored."""
    low = (text or "").lower()
    return any(k in low for k in keywords)


def raw_dir(stream=None):
    """Raw actor output lands per stream: `state/raw/<slug>/` (plan v2, A3)."""
    return os.path.join(STATE, "raw", stream or memory.DEFAULT_STREAM)


def load_themes(stream=None):
    """The theme roster from shared memory, joined to the engine-local terms.

    `.atelier/memory/themes.md` decides which hashtags are themes; themes.json
    only says how to search for one. Neither half may carry a tag the other
    does not - a silent skip would drop a theme from the pass unnoticed.
    """
    with open(terms_file(stream)) as f:
        local = json.load(f)
    terms = local["search_terms"]
    themes = memory.load_themes(stream)

    roster = {t["tag"] for t in themes}
    if roster != set(terms):
        missing = sorted(roster - set(terms))
        extra = sorted(set(terms) - roster)
        sys.exit(
            "listen.py: themes.json and .atelier/memory/themes.md disagree on the roster; "
            f"no search term for {missing}, no theme row for {extra}"
        )

    for t in themes:
        t["x_search"] = terms[t["tag"]]["x_search"]
        t["linkedin_search"] = terms[t["tag"]].get("linkedin_search", "")
        t["keywords"] = terms[t["tag"]]["keywords"]
    return {"themes": themes, "mentions": local["mentions"],
            "ignore": local.get("ignore", {}).get("keywords", [])}


def watched_passes(path=None, limit=None, most=30):
    """The `@watched` X passes: the accounts a person watches from the control
    page (`state/watchlist.json`, scripts/control.py), as `from:` searches of at
    most `limit` characters each, at most `most` accounts. `limit` defaults to the
    effective X read driver's query limit, `listen.query_limit` in engine.json (255 for
    twitterapi.io, X's own 512 for composio).
    Empty when nothing is watched; the root stream's only."""
    try:
        with open(path or os.path.join(STATE, "watchlist.json"), encoding="utf-8") as f:
            watched = json.load(f).get("watched") or []
    except (OSError, ValueError):
        return []
    handles = []
    for w in watched:
        h = str(w.get("handle") or "").lstrip("@")
        if re.fullmatch(r"[A-Za-z0-9_]{1,15}", h) and h.lower() not in {x.lower() for x in handles}:
            handles.append(h)
    if limit is None:
        limit = channels.query_limit(channels.effective_x_read(memory.DEFAULT_STREAM)[0])
    handles, tail = handles[:most], " -filter:replies"
    passes, chunk = [], []
    for h in handles:
        if chunk and len("(" + " OR ".join(f"from:{x}" for x in chunk + [h]) + ")" + tail) > limit:
            passes.append(chunk)
            chunk = []
        chunk.append(h)
    if chunk:
        passes.append(chunk)
    return [{"source": "x", "tag": "@watched", "query": "(" + " OR ".join(f"from:{x}" for x in c) + ")" + tail}
            for c in passes]


def linkedin_company_urls():
    """Verified LinkedIn company pages from `.atelier/memory/handles.md`.

    Only rows already marked `verified` are targets, cleared partners and own
    channels alike. `handles.md` carries a deliberately blank LinkedIn handle
    for the brand - the slug is not a fact this engine has the authority to
    establish - and most other rows are `collect`, so this list is short and
    may be empty. Empty means the company-posts actor is not called at all: a
    slug is never guessed to give it something to run over.
    """
    rows = [(party, h.get("linkedin", "")) for party, h in memory.taggable_handles().items()]
    for (brand, platform), row in memory.own_channels().items():
        if platform.strip().lower() != "linkedin":
            continue
        if row.get("status", "").strip().lower() != "verified":
            continue
        rows.append((brand, row.get("handle", "")))

    urls = {}
    for party, slug in rows:
        slug = (slug or "").strip()
        if slug.lower() in ("", "collect", "-", "—"):
            continue
        slug = re.sub(r"^https?://", "", slug)
        slug = re.sub(r"^(www\.)?linkedin\.com/", "", slug).strip("/")
        if not slug:
            continue
        urls.setdefault(f"https://www.linkedin.com/{slug}/", party)
    return urls


def call_actor(actor, token, body, timeout=300, actor_memory=256):
    q = urllib.parse.urlencode({"token": token, "timeout": timeout, "memory": actor_memory})
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?{q}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout + 30) as r:
        return json.loads(r.read().decode())


def run_x(key, query, max_items, since_ts, opener=None, stream=None):
    """One X search through `channels.search`, the stream's X read driver: the term as
    written in themes.json, `since` applied, most-engaged first (X_ORDER). The driver
    changes which API is read, never what is kept; both return the tweet shape
    `norm_item` reads (author.userName, likeCount, createdAt, ...)."""
    return channels.search(query, since_ts, min(max_items, MAX_PER_TERM), stream=stream, query_type=X_ORDER,
                           key=key, opener=opener)


def run_linkedin_search(token, query, max_items, since_dt, timeout=600):
    """One LinkedIn keyword search. Paid; only reached through --linkedin."""
    body = {
        "searchQueries": [query],
        "maxPosts": max_items,
        "postedLimitDate": since_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sortBy": "date",
        "profileScraperMode": "short",
    }
    return call_actor(LINKEDIN_SEARCH_ACTOR, token, body, timeout=timeout, actor_memory=1024)


def run_linkedin_company(token, urls, max_items, since_dt, timeout=600):
    """Recent posts from verified partner pages. Paid; only through --linkedin."""
    body = {
        "targetUrls": list(urls),
        "maxPosts": max_items,
        "postedLimitDate": since_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "includeReposts": False,
    }
    return call_actor(LINKEDIN_COMPANY_ACTOR, token, body, timeout=timeout, actor_memory=1024)


def parse_when(value):
    """A UTC datetime for whatever an actor called a timestamp, else None.

    The sources disagree: X returns "Fri Sep 04 03:24:50 +0000 2026" (RFC 2822),
    harvestapi returns a `postedAt` object carrying both an ISO date and epoch
    milliseconds. None means "unreadable", and the caller drops the item rather
    than keeping something it cannot place inside the window.
    """
    if isinstance(value, dict):
        for key in ("date", "timestamp", "postedAt"):
            if value.get(key) is not None:
                when = parse_when(value[key])
                if when is not None:
                    return when
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e11:  # milliseconds
            ts /= 1000.0
        try:
            return dt.datetime.fromtimestamp(ts, dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        pass
    try:
        d = email.utils.parsedate_to_datetime(s)
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        pass
    if s.isdigit():
        return parse_when(int(s))
    return None


def norm_item(it):
    a = it.get("author") or {}
    text = it.get("text") or it.get("full_text") or ""
    return {
        "id": str(it.get("id") or it.get("id_str") or ""),
        "url": it.get("url") or it.get("twitterUrl") or "",
        "text": text,
        "created_at": it.get("createdAt") or it.get("created_at") or "",
        "author": a.get("userName") or a.get("screen_name") or it.get("author_username") or "",
        "author_name": a.get("name") or "",
        "followers": a.get("followers") or a.get("followers_count") or 0,
        "likes": it.get("likeCount") or it.get("favorite_count") or 0,
        "retweets": it.get("retweetCount") or it.get("retweet_count") or 0,
        "replies": it.get("replyCount") or it.get("reply_count") or 0,
        "views": it.get("viewCount") or 0,
        "lang": it.get("lang") or "",
        "source": "x",
        "_matched_term": it.get("_matched_term") or "",
    }


def norm_linkedin(it):
    """A harvestapi post in the same shape, so one prescore reads both sources.

    `retweets` and `replies` carry LinkedIn's shares and comments: the field
    names stay X's so the engagement arithmetic below, and every reader of
    listening-*.json, needs no branch. `source` is what tells them apart.
    """
    a = it.get("author") or {}
    eng = it.get("engagement") or {}
    posted = it.get("postedAt") or ""
    return {
        "id": str(it.get("id") or it.get("entityId") or ""),
        "url": it.get("linkedinUrl") or "",
        "text": it.get("content") or "",
        "created_at": (posted.get("date") or posted.get("timestamp") or "")
                      if isinstance(posted, dict) else posted,
        "author": a.get("publicIdentifier") or a.get("universalName") or "",
        "author_name": a.get("name") or "",
        "followers": a.get("followers") or 0,
        "likes": eng.get("likes") or 0,
        "retweets": eng.get("shares") or 0,
        "replies": eng.get("comments") or 0,
        "views": 0,
        "lang": "",
        "source": "linkedin",
        "_matched_term": it.get("_matched_term") or "",
    }


def prescore(item, theme):
    t = item["text"].lower()
    kws = theme.get("keywords", [])
    hits = [k for k in kws if k in t]
    relevance = round(min(1.0, len(hits) / max(3, len(kws) * 0.4)), 2)
    pos = sum(t.count(w) for w in POS)
    neg = sum(t.count(w) for w in NEG)
    if neg > pos + 1:
        sentiment = "critical"
    elif neg > pos:
        sentiment = "negative"
    elif pos > neg:
        sentiment = "positive"
    else:
        sentiment = "neutral"
    eng = item["likes"] + 2 * item["retweets"] + 3 * item["replies"]
    return {"relevance": relevance, "hits": hits, "sentiment": sentiment, "engagement": eng}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=12, help="max items per search term (at most 12)")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--themes", default="", help="comma-separated tags to restrict to")
    ap.add_argument("--no-mentions", action="store_true")
    ap.add_argument("--linkedin", action="store_true",
                    help="also run the two paid harvestapi LinkedIn actors (off by default)")
    ap.add_argument("--stream", default=memory.DEFAULT_STREAM,
                    help="registry slug of the stream to listen for (default the root stream, brand.slug)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    args.max = max(1, min(args.max, MAX_PER_TERM))

    try:
        stream_row = memory.stream(args.stream)
    except memory.SharedMemoryError as e:
        sys.exit(f"listen.py: {e}")
    stream_name = stream_row["name"]
    cfg = load_themes(args.stream)
    want = {t.strip() for t in args.themes.split(",") if t.strip()}
    themes = [t for t in cfg["themes"] if not want or t["tag"] in want]
    # A stream whose engine-local file carries no mentions term yet (a new
    # stream, A2) runs no mentions pass rather than failing on the key.
    with_mentions = not args.no_mentions and not want and bool(cfg["mentions"].get("x_search"))

    passes = [{"source": "x", "tag": t["tag"], "query": t["x_search"]} for t in themes]
    if with_mentions:
        passes.append({"source": "x", "tag": "@mentions", "query": cfg["mentions"]["x_search"]})
    if not want and args.stream in (None, memory.DEFAULT_STREAM):
        passes += watched_passes()

    # LinkedIn is a cost gate, not a default. Nothing below is reached, and no
    # harvestapi call is made, unless --linkedin was passed.
    companies = {}
    if args.linkedin:
        for t in themes:
            if t.get("linkedin_search"):
                passes.append({"source": "linkedin", "actor": "post-search",
                               "tag": t["tag"], "query": t["linkedin_search"]})
        if with_mentions:
            if cfg["mentions"].get("linkedin_search"):
                passes.append({"source": "linkedin", "actor": "post-search",
                               "tag": "@mentions", "query": cfg["mentions"]["linkedin_search"]})
            companies = linkedin_company_urls()
            if companies:
                passes.append({"source": "linkedin", "actor": "company-posts", "tag": "@mentions",
                               "query": " ".join(sorted(companies))})

    since_dt = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)
    since = int(since_dt.timestamp())
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print(memory.summary(args.stream))
    print(f"listen.py: {len(passes)} terms x {args.max} items, since {args.days}d, X order {X_ORDER}, stamp {stamp}")
    for p in passes:
        print(f"  {p['source']:<8} {p['tag']:<22} {p['query']}")
    if not args.linkedin:
        print("  linkedin off (cost gate) - pass --linkedin to add the two harvestapi actors")
    elif not with_mentions:
        print("  linkedin company-posts skipped: it follows the mentions term, which this pass omits")
    elif not companies:
        print("  linkedin company-posts skipped: no verified LinkedIn row in handles.md")
    x_driver, held = channels.effective_x_read(args.stream)
    print(f"  x read driver {x_driver}" + (f" ({held}; configured: {channels.x_read_driver(args.stream)[0]})" if held else "")
          + f", @watched query limit {channels.query_limit(x_driver)}")
    if args.dry_run:
        if x_driver == "composio":
            try:
                channels.search(passes[0]["query"], since, args.max, stream=args.stream, query_type=X_ORDER, dry_run=True)
                print("  composio dry-run ok: TWITTER_RECENT_SEARCH validated by the CLI, nothing executed")
            except channels.ChannelError as e:
                print(f"  composio dry-run failed ({e}); a live run would fall back to twitterapi.io and log it")
        return

    x_key = twitterapi.load_key(None if args.stream == memory.DEFAULT_STREAM else args.stream) if x_driver == "twitterapi" else None
    token = load_token() if args.linkedin else None
    os.makedirs(raw_dir(args.stream), exist_ok=True)
    t0 = time.time()
    raw_all = []
    # One search per term so we can attribute results to a theme reliably.
    for p in passes:
        try:
            if p["source"] == "x":
                items = run_x(x_key, p["query"], args.max, since, stream=args.stream)
            elif p.get("actor") == "post-search":
                items = run_linkedin_search(token, p["query"], args.max, since_dt)
            else:
                items = run_linkedin_company(token, sorted(companies), args.max, since_dt)
        except Exception as e:  # keep going; a failed term is reported, not fatal
            print(f"  ! {p['source']} {p['tag']}: {e}")
            items = []
        for it in items:
            it["_matched_term"] = p["tag"]
            it["_source"] = p["source"]
        raw_all.extend(items)
        print(f"  {p['source']:<8} {p['tag']:<22} {len(items)} items")
    elapsed = round(time.time() - t0, 1)

    for src, prefix in (("x", "x"), ("linkedin", "linkedin")):
        batch = [it for it in raw_all if it.get("_source", "x") == src]
        if src == "x" or batch:
            with open(os.path.join(raw_dir(args.stream), f"{prefix}-{stamp}.json"), "w") as f:
                json.dump(batch, f, indent=1)

    by_tag = {t["tag"]: t for t in cfg["themes"]}
    out = []
    seen = set()
    dropped_stale = dropped_ignored = 0
    for it in raw_all:
        n = norm_linkedin(it) if it.get("_source") == "linkedin" else norm_item(it)
        if not n["id"] or not n["text"].strip():
            continue
        key = (n["source"], n["id"])
        if key in seen:
            continue
        # The window is enforced here: the actor backfills past `since_time` on
        # low-volume terms, and an unreadable timestamp is treated as out of
        # window rather than waved through.
        when = parse_when(n["created_at"])
        if when is None or when < since_dt:
            dropped_stale += 1
            continue
        seen.add(key)
        if ignored(n["text"], cfg["ignore"]):
            dropped_ignored += 1
            continue
        tag = n["_matched_term"]
        if tag == "@watched":
            # A watched account posts on any theme: score it against them all.
            theme = {"keywords": sorted({k for t in cfg["themes"] for k in t["keywords"]})}
        else:
            theme = by_tag.get(tag, {"keywords": cfg["mentions"]["keywords"]})
        n["theme"] = tag
        n["stream"] = stream_name
        n["prescore"] = prescore(n, theme)
        out.append(n)
    out.sort(key=lambda x: (-x["prescore"]["relevance"], -x["prescore"]["engagement"]))

    source = "x via " + X_SOURCE
    if args.linkedin:
        source += f" + linkedin via {LINKEDIN_SEARCH_ACTOR}, {LINKEDIN_COMPANY_ACTOR}"
    result = {
        "run_id": stamp,
        "stream": stream_name,
        "source": source,
        "linkedin": args.linkedin,
        "window_days": args.days,
        "window_since": since_dt.isoformat(timespec="seconds"),
        "max_per_term": args.max,
        "terms": [{"source": p["source"], "tag": p["tag"], "query": p["query"]} for p in passes],
        "count_raw": len(raw_all),
        "dropped_stale": dropped_stale,
        "dropped_ignored": dropped_ignored,
        "count": len(out),
        "elapsed_s": elapsed,
        "items": out,
    }
    path = os.path.join(STATE, f"listening-{stamp}.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=1)
    with open(os.path.join(STATE, "listening-latest.json"), "w") as f:
        json.dump(result, f, indent=1)

    # Append to the run log.
    runs_p = os.path.join(STATE, "runs.json")
    runs = []
    if os.path.exists(runs_p):
        with open(runs_p) as f:
            runs = json.load(f)
    runs.append({"run_id": stamp, "step": "listen", "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                 "stream": stream_name, "items": len(out), "terms": len(passes), "dropped_stale": dropped_stale,
                 "linkedin": args.linkedin, "x_driver": x_driver, "elapsed_s": elapsed, "file": os.path.relpath(path, ENGINE)})
    with open(runs_p, "w") as f:
        json.dump(runs, f, indent=1)

    print(f"wrote {path} ({len(out)} items, {dropped_stale} dropped as stale, {dropped_ignored} as another stream, {elapsed}s)")


if __name__ == "__main__":
    main()
