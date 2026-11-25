#!/usr/bin/env python3
"""
twitterapi.py - the one client for reading X (owner decision 2026-10-26:
"stick to twitterapi for x"; `.atelier/memory/decisions/2026-10-26-twitterapi-for-x.md`).

twitterapi.io is a third-party read API for X, not X's own. Three uses here:

  search        GET /twitter/tweet/advanced_search  - the 7-day listening pass
                (`listen.py`), X advanced-search operators, `since_time:` with
                a Unix timestamp, up to 20 tweets a page, `next_cursor` to page
  lookup        GET /twitter/tweets?tweet_ids=...    - public counts for our own
                posts (`x_metrics.py`), up to 50 ids a call; a deleted or
                private tweet is omitted, so results are matched by id
  stream        the filter rules and WebSocket in `x_stream.py`, unchanged

Price, from twitterapi.io's pricing page on 2026-10-26: USD 0.15 per 1,000
tweets returned (15 credits a tweet), with a minimum of 15 credits a call, so
a search that returns nothing still costs one tweet. A page returns up to 20
tweets and is billed for what it returns, so `--max 12` costs up to 20.

Key: TWITTERAPI_IO_API_KEY through `scripts/secrets.py` (environment, then the
keychain item under the brand's service). Never read from a file.
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

import secrets

BASE = "https://api.twitterapi.io"
PAGE_SIZE = 20
LOOKUP_BATCH = 50
KEY_NAME = "TWITTERAPI_IO_API_KEY"


class TwitterAPIError(RuntimeError):
    """A call that did not succeed. Never read around as an empty result."""


def load_key(stream=None):
    try:
        return secrets.get_secret(KEY_NAME, stream=stream)
    except secrets.SecretNotFound as e:
        sys.exit(f"ERROR: {e}")


def _get(key, path, params, timeout=40, opener=None):
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"X-API-Key": key}, method="GET")
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
            out = json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        raise TwitterAPIError(f"{path}: HTTP {exc.code} {exc.read()[:300]!r}") from None
    if isinstance(out, dict) and out.get("status") == "error":
        raise TwitterAPIError(f"{path}: {out.get('msg') or out}")
    return out


def search(key, query, max_items, since_ts=None, query_type="Latest", opener=None, max_pages=10):
    """Tweets for one advanced-search query, newest first, at most `max_items`
    (rounded up to whole pages for billing). `since_ts` adds `since_time:`."""
    q = query if not since_ts else f"{query} since_time:{int(since_ts)}"
    out, cursor, pages = [], "", 0
    while len(out) < max_items and pages < max_pages:
        page = _get(key, "/twitter/tweet/advanced_search", {"query": q, "queryType": query_type, "cursor": cursor},
                    opener=opener)
        pages += 1
        out.extend(t for t in page.get("tweets") or [] if isinstance(t, dict) and t.get("id"))
        if not page.get("has_next_page") or not page.get("next_cursor"):
            break
        cursor = page["next_cursor"]
    return out[:max_items]


def user_info(key, user_name, opener=None):
    """The profile for one handle: `("found", data)`, `("not found", msg)` or
    `("unavailable", reason)`. The endpoint answers HTTP 200 either way and
    says which in `status`, so a missing handle is a definite answer, not an
    error; a suspended account comes back as `unavailable`."""
    url_q = {"userName": user_name.strip().lstrip("@")}
    page = None
    try:
        page = _get(key, "/twitter/user/info", url_q, opener=opener)
    except TwitterAPIError as e:
        if "user not found" in str(e).lower():
            return "not found", "user not found"
        raise
    data = page.get("data") or {}
    if data.get("unavailable"):
        return "unavailable", str(data.get("unavailableReason") or data.get("message") or "unavailable")
    return "found", data


def lookup(key, ids, opener=None):
    """`{id: tweet}` for the ids that still exist, in batches of 50."""
    ids = [str(i) for i in dict.fromkeys(ids) if str(i).strip()]
    found = {}
    for n in range(0, len(ids), LOOKUP_BATCH):
        batch = ids[n:n + LOOKUP_BATCH]
        page = _get(key, "/twitter/tweets", {"tweet_ids": ",".join(batch)}, opener=opener)
        for t in page.get("tweets") or []:
            if isinstance(t, dict) and str(t.get("id") or "") in batch:
                found[str(t["id"])] = t
    return found
