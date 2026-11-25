#!/usr/bin/env python3
"""
x_stream.py - standing X monitors through twitterapi.io: the filter rules, and
the WebSocket that receives what they match.

X only. LinkedIn keeps its own API; nothing here reads or writes LinkedIn. And
nothing here posts: the only calls that change anything are the rule calls,
which set what twitterapi.io watches for this API key.

The rules are built from shared memory and themes.json, never typed here:

  <slug>:mentions      our own X handle (handles.md, own channels), or the brand by
                       name (themes.json `mentions`), not from us
  <slug>:own           from: our own handle, so autopilot posts show up too
  <slug>:partners      from: every X handle in handles.md (cleared partners, standards bodies)
  <slug>:hashtags      the theme hashtags (themes.md) and the tags our posts carry
                       (OWN_TAGS), as bare words: X search does not index every hashtag
                       in a post as one, and the bare word matches the tag too
  <slug>:theme:<Tag>   each theme's x_search from themes.json, verbatim

`<slug>` is the brand's root stream (engine.json brand.slug).

A rule's value is capped at 255 characters by twitterapi.io, so every x_search in
themes.json stays at or under that, and building a rule over it fails loudly.

Billing: twitterapi.io bills an active rule per tweet matched (USD 0.15 per
1,000), from activation, whether or not a client is connected. `rules --off`
deactivates every rule this script owns. Rules it does not own (their tag does
not start with `<slug>:`) are never touched.

Usage:
  python3 x_stream.py rules              # desired against live; changes nothing
  python3 x_stream.py rules --apply      # add, update and activate; deactivate owned leftovers;
                                         # refused unless params.x_stream.mode is websocket AND the
                                         # effective X read driver is twitterapi
  python3 x_stream.py rules --off        # deactivate every owned rule
  python3 x_stream.py poll [--dry-run]   # the scheduled search (params.x_stream.mode "poll", the default):
                                         # every planned rule through channels.search, since_id persisted
                                         # in state/x-stream/poll.json, matches appended to the same
                                         # <date>.jsonl; --dry-run plans the queries and calls nothing
  python3 x_stream.py listen             # hold the WebSocket, append to state/x-stream/<date>.jsonl
  python3 x_stream.py digest [--hours N] # what came in, per rule, and the listener's heartbeat

Token: TWITTERAPI_IO_API_KEY through scripts/secrets.py (environment, then the
keychain item under the brand's service). Scheduled by the x-stream job of engine.json.
"""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import socket
import ssl
import struct
import sys
import time
import urllib.error
import urllib.request

import memory
import secrets
from listen import ignored

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
STATE = os.path.join(paths.state(), "x-stream")
API = "https://api.twitterapi.io/oapi/tweet_filter/"
WS_HOST, WS_PATH = "ws.twitterapi.io", "/twitter/tweet/websocket"
# Every rule this script owns is tagged `<slug>:`; the slug is the brand's root stream.
PREFIX = f"{memory.DEFAULT_STREAM}:"
BRAND_NAME = memory.DEFAULT_STREAM_NAME
MAX_RULE = 255
# Tags our own posts carry that are not themes. A tag is added here by a person.
OWN_TAGS = []
# Check cadence in seconds. Mentions are the ones a reply may be owed on.
INTERVAL = {PREFIX + "mentions": 600}
DEFAULT_INTERVAL = 3600


class RuleError(RuntimeError):
    """A rule could not be built as specified. Never shortened or guessed."""


def own_x_handle():
    """Our own X handle from handles.md's own channels (`@name`); RuleError when none is recorded.

    Never guessed: a stream without an own X row has no `own` or `mentions` rule."""
    for (brand, platform), row in memory.own_channels().items():
        if platform.strip().lower() == "x":
            h = memory._handle(row.get("handle", ""))
            if re.fullmatch(r"@\w+", h):
                return h
    raise RuleError("handles.md has no verified own X handle under `own channels`; the own and mentions rules need one")


def _site_host():
    try:
        import config
        from urllib.parse import urlparse
        return urlparse(str(config.cfg("site.post_url", ""))).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def about_pattern():
    """Matches text that names the brand: its name, its own X handle, its site's host.

    Built on demand, never at import: a fresh clone has no own handle yet, and
    `import x_stream` must still work there so `rules` can say what is missing."""
    parts = [r"\b" + re.escape(BRAND_NAME) + r"\b"]
    try:
        parts.append(re.escape(own_x_handle()[1:]))
    except (RuleError, memory.SharedMemoryError):
        pass
    host = _site_host()
    if host and host != "example.com":
        parts.append(re.escape(host))
    return re.compile("|".join(parts), re.I)


# --- the rules ----------------------------------------------------------------

def partner_handles():
    """X handles in handles.md's cleared-partner and standards tables, in file order."""
    h = memory.load_handles()
    out = []
    for r in h["cleared_partners"] + h["standards_bodies"]:
        x = memory._handle(r.get("x", ""))
        if re.fullmatch(r"@\w+", x) and x not in out:
            out.append(x)
    return out


def desired_rules(cfg=None):
    """[(tag, value, interval_seconds)] for every rule this script keeps active."""
    if cfg is None:
        with open(os.path.join(paths.instance(), "themes.json")) as f:
            cfg = json.load(f)
    tags = memory.theme_tags()
    terms = cfg["search_terms"]
    if set(tags) != set(terms):
        raise RuleError(f"themes.json and themes.md disagree on the roster: {sorted(set(tags) ^ set(terms))}")
    mentions = cfg["mentions"]["x_search"].replace(" lang:en", "")
    own = own_x_handle()
    rules = [
        (PREFIX + "mentions", f"({own} OR {mentions}) -from:{own[1:]}"),
        (PREFIX + "own", f"from:{own[1:]}"),
        (PREFIX + "partners", " OR ".join("from:" + h[1:] for h in partner_handles()
                                          if not ignored(h, cfg.get("ignore", {}).get("keywords", [])))),
        (PREFIX + "hashtags", "(" + " OR ".join(t[1:] for t in tags + OWN_TAGS) + f") -from:{own[1:]}"),
    ] + [(f"{PREFIX}theme:{t[1:]}", terms[t]["x_search"]) for t in tags]
    for tag, value in rules:
        if not value.strip():
            raise RuleError(f"{tag}: empty rule")
        if len(value) > MAX_RULE:
            raise RuleError(f"{tag}: {len(value)} characters, twitterapi.io takes {MAX_RULE}: {value}")
    return [(tag, value, INTERVAL.get(tag, DEFAULT_INTERVAL)) for tag, value in rules]


# --- the REST side ----------------------------------------------------------------

def call(key, path, body=None):
    req = urllib.request.Request(API + path, headers={"X-API-Key": key, "Content-Type": "application/json"},
                                 data=None if body is None else json.dumps(body).encode(),
                                 method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            out = json.load(r)
    except urllib.error.HTTPError as exc:
        raise RuleError(f"{path}: HTTP {exc.code} {exc.read()[:300]!r}") from None
    if out.get("status") != "success":
        raise RuleError(f"{path}: {out}")
    return out


def rules_cmd(key, apply=False, off=False):
    live = [r for r in call(key, "get_rules").get("rules") or [] if (r.get("tag") or "").startswith(PREFIX)]
    by_tag = {r["tag"]: r for r in live}
    want = [] if off else desired_rules()
    plan = []
    for tag, value, interval in want:
        r = by_tag.get(tag)
        if r is None:
            plan.append(("add", tag, value, interval, None))
        elif r.get("value") != value or int(r.get("interval_seconds") or 0) != interval:
            plan.append(("update", tag, value, interval, r["rule_id"]))
        else:
            plan.append(("activate", tag, value, interval, r["rule_id"]))  # is_effect is not readable; set it
    wanted = {t for t, _, _ in want}
    for r in live:
        if r["tag"] not in wanted:
            plan.append(("deactivate", r["tag"], r["value"], int(r.get("interval_seconds") or DEFAULT_INTERVAL), r["rule_id"]))
    for verb, tag, value, interval, _ in plan:
        print(f"{verb:10} {tag:28} every {interval:>5}s  {len(value):>3} ch  {value}")
    if not (apply or off):
        print(f"\n{len(plan)} rule(s); nothing changed. --apply to set them, --off to stop billing.")
        return
    for verb, tag, value, interval, rid in plan:
        if verb == "add":
            rid = call(key, "add_rule", {"tag": tag, "value": value, "interval_seconds": interval})["rule_id"]
        call(key, "update_rule", {"rule_id": rid, "tag": tag, "value": value, "interval_seconds": interval,
                                  "is_effect": 0 if verb == "deactivate" else 1})
    print(f"\n{len(plan)} rule(s) set; {sum(1 for p in plan if p[0] != 'deactivate')} active.")


# --- the poll: the same monitors as a scheduled search ----------------------------------

MODES = ("poll", "websocket")
DEFAULT_POLL_MAX = 12          # per query, the same bound listen.py keeps
DEFAULT_LOOKBACK_HOURS = 6     # the first poll of a rule, before any since_id is persisted


def x_mode():
    """`params.x_stream.mode`: `poll` (the default; the scheduled search) or `websocket`."""
    import config
    mode = str(config.cfg("x_stream.mode", "poll") or "poll").strip().lower()
    if mode not in MODES:
        raise RuleError(f"x_stream.mode is {mode!r}; one of {', '.join(MODES)}")
    return mode


def apply_refusal(stream=None):
    """None when live rules may be applied, else the reason they may not.

    Rules are billed per matched post from the moment they are active, so they are applied
    only while the owner chose the websocket mode AND the stream's effective X read driver
    is twitterapi. In poll mode the monitors are searches and no live rule is wanted."""
    import channels
    mode = x_mode()
    if mode != "websocket":
        return f"x_stream.mode is {mode!r}, not 'websocket': the monitors run as the scheduled poll, no live rule is wanted"
    driver, _held = channels.effective_x_read(stream or memory.DEFAULT_STREAM)
    if driver != "twitterapi":
        return f"the effective X read driver is {driver!r}, not 'twitterapi': live rules are a twitterapi.io feature"
    return None


def poll_state_path():
    return os.path.join(STATE, "poll.json")


def load_poll_state():
    """{rule tag: {"since_id": str, "since_ts": int, "at": iso}}; empty when never polled."""
    try:
        with open(poll_state_path()) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_poll_state(state):
    os.makedirs(STATE, exist_ok=True)
    with open(poll_state_path() + ".tmp", "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    os.replace(poll_state_path() + ".tmp", poll_state_path())


def _id_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def poll_plan(rules=None, state=None, now=None, lookback_hours=None):
    """[(tag, query, since_ts, since_id)] for one poll: every planned rule's query, the
    persisted since_id, and the timestamp the search is bounded by."""
    rules = desired_rules() if rules is None else rules
    state = load_poll_state() if state is None else state
    now = int(time.time()) if now is None else int(now)
    back = now - int(3600 * (DEFAULT_LOOKBACK_HOURS if lookback_hours is None else lookback_hours))
    out = []
    for tag, value, _interval in rules:
        rec = state.get(tag) or {}
        out.append((tag, value, int(rec.get("since_ts") or back), str(rec.get("since_id") or "")))
    return out


def poll(dry_run=False, rules=None, search=None, stream=None, now=None, max_items=None, skip=None):
    """Run every planned rule once through `channels.search` and append what is new to
    state/x-stream/<date>.jsonl, the file the WebSocket writes, so downstream is unchanged.

    `since_id` is persisted per rule: only posts with a higher id are kept, and a rule that
    fails keeps its old since_id for the next poll. `dry_run` plans the queries and makes no
    call and writes nothing."""
    import channels
    import config
    stream = stream or memory.DEFAULT_STREAM
    max_items = int(max_items or config.cfg("x_stream.poll_max", DEFAULT_POLL_MAX) or DEFAULT_POLL_MAX)
    max_items = min(max_items, DEFAULT_POLL_MAX)
    now = int(time.time()) if now is None else int(now)
    plan = poll_plan(rules, now=now)
    driver, held = channels.effective_x_read(stream)
    print(f"x_stream poll: {len(plan)} quer{'y' if len(plan) == 1 else 'ies'}, driver {driver}"
          + (f" ({held})" if held else "") + f", <= {max_items} per query, mode {x_mode()}")
    if dry_run:
        for tag, query, since_ts, since_id in plan:
            print(f"{'would run':10} {tag:28} since_id {since_id or '-':>20}  since {dt.datetime.fromtimestamp(since_ts, dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ}  {len(query):>3} ch  {query}")
        print("\nnothing called, nothing written.")
        return 0
    search = search or channels.search
    os.makedirs(STATE, exist_ok=True)
    skip = ignore_keywords() if skip is None else skip
    seen = seen_ids()
    state = load_poll_state()
    day = dt.datetime.fromtimestamp(now, dt.timezone.utc).date()
    new = failed = 0
    for tag, query, since_ts, since_id in plan:
        try:
            items = search(query, since_ts, max_items, stream=stream, query_type="Latest")
        except Exception as exc:  # one rule failing leaves its since_id where it was
            failed += 1
            log(f"poll {tag}: {exc}")
            continue
        newest = since_id
        fresh = []
        for t in items or []:
            tid = str(t.get("id") or "")
            if not tid:
                continue
            if _id_int(tid) > _id_int(newest):
                newest = tid
            if _id_int(tid) <= _id_int(since_id) or tid in seen:
                continue
            if ignored((t.get("text") or "") + " " + ((t.get("quoted_tweet") or {}).get("text") or ""), skip):
                continue
            seen.add(tid)
            fresh.append(t)
        if fresh:
            with open(day_file(day), "a") as f:
                for t in fresh:
                    f.write(json.dumps(record(t, None, tag), ensure_ascii=False) + "\n")
        new += len(fresh)
        state[tag] = {"since_id": newest, "since_ts": now - 60, "at": dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        log(f"poll {tag}: {len(items or [])} found, {len(fresh)} new")
    save_poll_state(state)
    heartbeat(state="poll", last_poll_at=dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    print(f"poll done: {new} new, {failed} failed of {len(plan)}")
    return 1 if failed == len(plan) and plan else 0


# --- the WebSocket ------------------------------------------------------------------

class Closed(Exception):
    def __init__(self, code, reason=""):
        super().__init__(f"closed {code} {reason}".strip())
        self.code = code


class WebSocket:
    """A minimal RFC 6455 client: text messages in, pings answered. Standard library only.

    Frames are parsed from a buffer and consumed only when complete, so a socket
    timeout in the middle of a frame loses nothing.
    """
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, key, timeout=30):
        raw = socket.create_connection((WS_HOST, 443), timeout=timeout)
        self.s = ssl.create_default_context().wrap_socket(raw, server_hostname=WS_HOST)
        nonce = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET {WS_PATH} HTTP/1.1\r\nHost: {WS_HOST}\r\nUpgrade: websocket\r\n"
                        f"Connection: Upgrade\r\nSec-WebSocket-Key: {nonce}\r\nSec-WebSocket-Version: 13\r\n"
                        f"x-api-key: {key}\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.s.recv(4096)
            if not chunk:
                raise ConnectionError("closed during the handshake")
            head += chunk
        head, self.buf = head.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        if not re.match(r"HTTP/1\.1 101\b", lines[0]):
            raise ConnectionError(f"handshake refused: {lines[0]}")
        headers = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:])}
        expect = base64.b64encode(hashlib.sha1((nonce + self.GUID).encode()).digest()).decode()
        if headers.get("sec-websocket-accept") != expect:
            raise ConnectionError("handshake: bad Sec-WebSocket-Accept")
        self.parts = []

    def send(self, opcode, payload=b""):
        mask = os.urandom(4)
        n = len(payload)
        if n < 126:
            head = struct.pack("!BB", 0x80 | opcode, 0x80 | n)
        elif n < 65536:
            head = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, n)
        else:
            head = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, n)
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def _frame(self):
        b = self.buf
        if len(b) < 2:
            return None
        n, i = b[1] & 0x7F, 2
        if n == 126:
            if len(b) < 4:
                return None
            n, i = struct.unpack("!H", b[2:4])[0], 4
        elif n == 127:
            if len(b) < 10:
                return None
            n, i = struct.unpack("!Q", b[2:10])[0], 10
        mask = None
        if b[1] & 0x80:
            if len(b) < i + 4:
                return None
            mask, i = b[i:i + 4], i + 4
        if len(b) < i + n:
            return None
        data = b[i:i + n]
        if mask:
            data = bytes(x ^ mask[k % 4] for k, x in enumerate(data))
        self.buf = b[i + n:]
        return b[0] & 0x80, b[0] & 0x0F, data

    def recv(self):
        """The next text message. Raises socket.timeout (state kept), Closed, or ConnectionError."""
        while True:
            f = self._frame()
            while f is None:
                chunk = self.s.recv(65536)
                if not chunk:
                    raise ConnectionError("closed by the server without a close frame")
                self.buf += chunk
                f = self._frame()
            fin, op, data = f
            if op == 0x9:
                self.send(0xA, data)
            elif op == 0xA:
                continue
            elif op == 0x8:
                code = struct.unpack("!H", data[:2])[0] if len(data) >= 2 else 1005
                try:
                    self.send(0x8, data[:2])
                except OSError:
                    pass
                raise Closed(code, data[2:].decode("utf-8", "replace"))
            else:
                self.parts.append(data)
                if fin:
                    msg, self.parts = b"".join(self.parts), []
                    return msg.decode("utf-8", "replace")

    def close(self):
        try:
            self.send(0x8, struct.pack("!H", 1000))
            self.s.close()
        except OSError:
            pass


def channels_error():
    import channels
    return channels.ChannelError


def log(msg):
    print(f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%dT%H:%M:%SZ} {msg}", flush=True)


def record(t, rule_id, rule_tag, about=None):
    about = about or about_pattern()
    a = t.get("author") or {}
    q = t.get("quoted_tweet") or {}
    text = t.get("text") or ""
    return {
        "received_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rule_id": rule_id, "rule_tag": rule_tag,
        "id": t.get("id"), "url": t.get("url") or f"https://x.com/{a.get('userName')}/status/{t.get('id')}",
        "created": t.get("createdAt"), "handle": a.get("userName"), "name": a.get("name"),
        "followers": a.get("followers") or 0, "text": text,
        "is_reply": bool(t.get("isReply")), "in_reply_to": t.get("inReplyToUsername") or "",
        "quoted": {"handle": (q.get("author") or {}).get("userName"), "id": q.get("id"), "text": (q.get("text") or "")[:500]} if q else None,
        "about_brand": bool(about.search(text + " " + (q.get("text") or ""))),
        "likes": t.get("likeCount") or 0, "reposts": t.get("retweetCount") or 0,
        "replies": t.get("replyCount") or 0, "quotes": t.get("quoteCount") or 0, "views": t.get("viewCount") or 0,
    }


def day_file(day):
    return os.path.join(STATE, f"{day:%Y-%m-%d}.jsonl")


def seen_ids():
    today = dt.datetime.now(dt.timezone.utc).date()
    ids = set()
    for d in (today - dt.timedelta(days=1), today):
        if os.path.exists(day_file(d)):
            with open(day_file(d)) as f:
                ids.update(json.loads(l)["id"] for l in f if l.strip())
    return ids


def heartbeat(**kw):
    path = os.path.join(STATE, "listener.json")
    try:
        with open(path) as f:
            hb = json.load(f)
    except (OSError, ValueError):
        hb = {}
    hb.update(kw, pid=os.getpid(), at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    with open(path + ".tmp", "w") as f:
        json.dump(hb, f, indent=1)
    os.replace(path + ".tmp", path)


def ignore_keywords():
    """themes.json `ignore`: posts naming another stream are not recorded."""
    with open(os.path.join(paths.instance(), "themes.json")) as f:
        return json.load(f).get("ignore", {}).get("keywords", [])


def listen(key):
    os.makedirs(STATE, exist_ok=True)
    seen = seen_ids()
    skip = ignore_keywords()
    about = about_pattern()
    log(f"listener start, pid {os.getpid()}, {len(seen)} ids already on file")
    while True:
        wait = 90  # twitterapi.io holds a dropped slot for up to 90 s
        try:
            ws = WebSocket(key)
            log("connected")
            heartbeat(connected_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), state="connected")
            last_rx = time.time()
            while True:
                try:
                    msg = ws.recv()
                except socket.timeout:
                    if time.time() - last_rx > 150:
                        raise ConnectionError("nothing from the server for 150 s")
                    ws.send(0x9, b"ka")
                    continue
                last_rx = time.time()
                ev = json.loads(msg)
                kind = ev.get("event_type")
                if kind == "ping":
                    heartbeat(state="connected")
                    continue
                if kind == "connected":
                    log("key accepted")
                    continue
                tweets = ev.get("tweets") or ([ev["tweet"]] if ev.get("tweet") else [])
                fresh = [t for t in tweets if t.get("id") and t["id"] not in seen
                         and not ignored((t.get("text") or "") + " " + ((t.get("quoted_tweet") or {}).get("text") or ""), skip)]
                if not fresh:
                    continue
                with open(day_file(dt.datetime.now(dt.timezone.utc).date()), "a") as f:
                    for t in fresh:
                        seen.add(t["id"])
                        f.write(json.dumps(record(t, ev.get("rule_id"), ev.get("rule_tag"), about), ensure_ascii=False) + "\n")
                log(f"{kind} {ev.get('rule_tag') or '-'}: {len(fresh)} new")
                heartbeat(state="connected", last_tweet_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        except Closed as c:
            log(f"server {c}")
            if c.code == 1008:  # another connection holds this key's one slot
                wait = 300
        except (OSError, ConnectionError, ValueError) as exc:
            log(f"dropped: {exc}")
        except KeyboardInterrupt:
            log("stopped")
            heartbeat(state="stopped")
            return
        heartbeat(state=f"reconnecting in {wait} s")
        time.sleep(wait)


# --- the digest -----------------------------------------------------------------------

def digest(hours):
    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(hours=hours)
    rows = []
    for k in range(hours // 24 + 2):
        p = day_file((now - dt.timedelta(days=k)).date())
        if os.path.exists(p):
            with open(p) as f:
                rows += [json.loads(l) for l in f if l.strip()]
    rows = [r for r in rows if dt.datetime.strptime(r["received_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc) >= since]
    try:
        with open(os.path.join(STATE, "listener.json")) as f:
            hb = json.load(f)
        print(f"listener: {hb.get('state')}, last seen {hb.get('at')}, pid {hb.get('pid')}")
    except (OSError, ValueError):
        print("listener: never ran on this machine")
    print(f"{len(rows)} post(s) in the last {hours} h\n")
    by = {}
    for r in rows:
        by.setdefault(r.get("rule_tag") or "-", []).append(r)
    for tag in sorted(by):
        rs = sorted(by[tag], key=lambda r: r["followers"], reverse=True)
        print(f"{tag}: {len(rs)}" + (f", {sum(r['about_brand'] for r in rs)} name {BRAND_NAME}" if any(r["about_brand"] for r in rs) else ""))
        for r in rs[:3]:
            print(f"   @{r['handle']} ({r['followers']:,}) {r['text'][:110]!r}  {r['url']}")
    try:
        own = own_x_handle()[1:].lower()
    except (RuleError, memory.SharedMemoryError):
        own = ""
    us = [r for r in rows if r["about_brand"] and (r["handle"] or "").lower() != own]
    if us:
        print(f"\nnaming {BRAND_NAME}:")
        for r in us:
            print(f"   {r['created']}  @{r['handle']}  {r['text'][:140]!r}  {r['url']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rules")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true")
    g.add_argument("--off", action="store_true")
    sub.add_parser("listen")
    pl = sub.add_parser("poll")
    pl.add_argument("--dry-run", action="store_true")
    d = sub.add_parser("digest")
    d.add_argument("--hours", type=int, default=24)
    args = ap.parse_args(argv)
    if args.cmd == "digest":
        return digest(args.hours)
    if args.cmd == "poll":
        try:
            return poll(dry_run=args.dry_run)
        except (RuleError, memory.SharedMemoryError) as e:
            print(f"x_stream: {e}", file=sys.stderr)
            return 1
    if args.cmd == "rules" and args.apply:
        try:
            why = apply_refusal()
        except (RuleError, memory.SharedMemoryError, channels_error()) as e:
            why = str(e)
        if why:
            print(f"x_stream: --apply refused: {why}", file=sys.stderr)
            return 2
    try:
        key = secrets.get_secret("TWITTERAPI_IO_API_KEY", required=False)
        if args.cmd == "rules":
            if key is None and not (args.apply or args.off):
                # A plan needs no key: say what the rules would be and that the
                # live set was not read. Exit 1 is the answer "not configured",
                # which engine.py doctor reports rather than counts as failed.
                for tag, value, interval in desired_rules():
                    print(f"{'desired':10} {tag:28} every {interval:>5}s  {len(value):>3} ch  {value}")
                print("\nTWITTERAPI_IO_API_KEY not set: desired rules only, the live rules were not read "
                      "(engine.py secrets --set TWITTERAPI_IO_API_KEY).")
                return 1
            if key is None:
                raise RuleError("TWITTERAPI_IO_API_KEY not set; --apply and --off need it")
            return rules_cmd(key, apply=args.apply, off=args.off)
        if key is None:
            raise RuleError("TWITTERAPI_IO_API_KEY not set; the listener needs it")
        return listen(key)
    except (RuleError, memory.SharedMemoryError, secrets.SecretNotFound) as e:
        # What is missing, on one line, never a traceback: a fresh clone has no
        # own handle recorded yet and no key seeded.
        print(f"x_stream: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
