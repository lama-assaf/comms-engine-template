#!/usr/bin/env python3
"""
engage.py - engagement acts in the loop (plan v2, item A17).

The engagement pass drafts comments and replies; the autopilot logs them in
dry-run; nothing here sends. What this adds is the record: every placed
comment with its shape, the target's tier and its outcome at 72 hours, so the
ledger learns which shapes earn a reply from which tier, and the inbound
counts feed `score.py`'s demand pass. Identifiers are never stored: the
target is a post id and a tier, not a handle.

  acts  in `state/engagement.json`:
  {"id": "A-2026-10-27-1", "stream": "Acme", "item_id": "Q-…", "theme": "#…",
   "platform": "X", "target_post": "2103…", "tier": "institution | peer | critic | trade | other",
   "shape": "sharper question", "placed_at": "…", "comment_id": "…",
   "outcome": null | "author replied" | "follow" | "nothing", "outcome_at": null}

  engine engage record --item Q-1 --theme '#ExampleTheme' \\
      --platform X --target 2103… --tier institution --shape "sharper question" --comment-id 2104…
  engine engage record --item like:2103… --theme '#ExampleTheme' \\
      --platform X --target 2103… --tier institution --shape like --kind like      # a reaction; reactions.py writes these
  engine engage outcome A-2026-10-27-1 "author replied"
  engine engage due          # acts past 72 h with no outcome
  engine engage ledger       # which shapes earn a reply from which tier
  engine engage send-due     # dry: every check, a fake driver, nothing written
  engine engage send-due --live   # the stream's write driver, through channels.send()

`send-due` is the auto-reply: for each drafted proposal still waiting it sends through
`channels.send()` (never directly) when the stream's auto-reply switch for that channel is
on (switches.py, set on the dashboard), so the gate, cites, hold, quiet hours and dedupe all
apply; with the switch off it sends nothing. The dry run copies the send state to a temp
directory and uses a fake driver, so it checks everything and changes nothing. It is not part
of any scheduled job.
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
sys.path.insert(0, HERE)
import memory  # noqa: E402

TIERS = ("institution", "peer", "critic", "trade", "other")
OUTCOMES = ("author replied", "follow", "nothing")
# engine.json engagement.window_days (engine.py setup engagement writes it);
# the shipped 72 h when config.py or the file cannot be read.
try:
    import config as _config
    OUTCOME_WINDOW = dt.timedelta(days=int(_config.cfg("engagement.window_days", 3)))
except Exception:
    OUTCOME_WINDOW = dt.timedelta(hours=72)
GOLDEN_HOUR = [
    ("T+0", "post goes live; pin it; then leave it alone 30 to 45 minutes"),
    ("T+0 to T+5 min", "reply to every early comment as it lands"),
    ("T+5 to T+15 min", "engage 5 to 10 adjacent in-niche posts through comment-strategy, drafts only"),
    ("T+15 to T+30 min", "recheck the post and reply to anything new"),
    ("T+1 to T+2 h", "final pass, then step back; no verdict before 48 to 72 h"),
]


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _parse(ts):
    try:
        d = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def path(state=None):
    return os.path.join(state or STATE, "engagement.json")


def load(state=None):
    p = path(state)
    if not os.path.exists(p):
        return {"proposals": [], "ledger": [], "acts": []}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(data, state=None):
    p = path(state)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)


#: what an engagement act can be: a comment or a reply (the default), or a reaction
KINDS = ("comment", "reply", "like", "repost", "quote")


def record(item_id, theme, platform, target_post, tier, shape, comment_id="", stream=memory.DEFAULT_STREAM_NAME, state=None, now=None,
           kind=None):
    """Record one placed act. `kind` names a reaction (`like`, `repost`, `quote`); left out, the act
    is a comment or a reply, as every act was before reactions existed. A reaction's `shape` is its
    kind, so the ledger reads `institution / like` beside `institution / sharper question`."""
    if tier not in TIERS:
        raise ValueError(f"tier {tier!r} is not one of {TIERS}")
    if kind is not None and kind not in KINDS:
        raise ValueError(f"kind {kind!r} is not one of {KINDS}")
    if "@" in str(target_post) or "@" in str(comment_id):
        raise ValueError("a target or comment is a post id, never a handle")
    now = now or _now()
    data = load(state)
    acts = data.setdefault("acts", [])
    n = sum(1 for a in acts if str(a.get("placed_at", ""))[:10] == now.date().isoformat()) + 1
    act = {"id": f"A-{now.date().isoformat()}-{n}", "stream": stream, "item_id": item_id, "theme": theme,
           "platform": platform, "target_post": str(target_post), "tier": tier, "shape": shape,
           "placed_at": now.isoformat(timespec="seconds"), "comment_id": str(comment_id),
           "outcome": None, "outcome_at": None}
    if kind:
        act["kind"] = kind
    acts.append(act)
    save(data, state)
    return act


def outcome(act_id, result, state=None, now=None):
    if result not in OUTCOMES:
        raise ValueError(f"outcome {result!r} is not one of {OUTCOMES}")
    data = load(state)
    for a in data.get("acts", []):
        if a["id"] == act_id:
            a["outcome"] = result
            a["outcome_at"] = (now or _now()).isoformat(timespec="seconds")
            save(data, state)
            return a
    raise KeyError(act_id)


def due(state=None, now=None):
    now = now or _now()
    return [a for a in load(state).get("acts", [])
            if a.get("outcome") is None and _parse(a.get("placed_at")) and now - _parse(a["placed_at"]) >= OUTCOME_WINDOW]


def ledger(state=None):
    """`{(tier, shape): {placed, replied, follow, nothing}}` - what earns a reply."""
    out = {}
    for a in load(state).get("acts", []):
        key = f"{a.get('tier')} / {a.get('shape')}"
        row = out.setdefault(key, {"placed": 0, "author replied": 0, "follow": 0, "nothing": 0, "open": 0})
        row["placed"] += 1
        row[a["outcome"] if a.get("outcome") in OUTCOMES else "open"] += 1
    return out


INBOUND_KEEP_DAYS = 14
_PATTERN_KEYS = ("channel", "tier", "shape", "theme", "target_post")


def merge_inbound(patterns, stream=memory.DEFAULT_STREAM_NAME, state=None, now=None):
    """Fold one inbound poll's patterns into `state/engagement.json` `inbound`; returns the section.

    A pattern is `{channel, tier, shape, theme, target_post, count}`: our own post's id and
    counts, never a handle, a name or a third party's text (rule 6). One that holds an `@`, a
    tier outside TIERS or an unknown key is refused whole, before anything is written. Counts
    add to the row for the same day and the same five fields; rows older than
    INBOUND_KEEP_DAYS go. The section's other keys (`posts_in_last_three_days`, `summary`) are kept."""
    clean = []
    for p in patterns or []:
        if set(p) - set(_PATTERN_KEYS) - {"count"}:
            raise ValueError(f"an inbound pattern carries only {_PATTERN_KEYS} and count, got {sorted(p)}")
        if p.get("tier") not in TIERS:
            raise ValueError(f"tier {p.get('tier')!r} is not one of {TIERS}")
        if any("@" in str(p.get(k, "")) for k in _PATTERN_KEYS):
            raise ValueError("an inbound pattern holds a handle; patterns carry counts only")
        clean.append(p)
    now = now or _now()
    day = now.date().isoformat()
    data = load(state)
    section = data.get("inbound")
    if not isinstance(section, dict):
        section = {}
    rows = [r for r in section.get("patterns") or [] if isinstance(r, dict)
            and r.get("day", "") >= (now.date() - dt.timedelta(days=INBOUND_KEEP_DAYS)).isoformat()]
    for p in clean:
        key = {k: str(p.get(k, "")) for k in _PATTERN_KEYS}
        key["stream"] = stream
        for r in rows:
            if r.get("day") == day and all(r.get(k) == v for k, v in key.items()):
                r["count"] = int(r.get("count", 0)) + int(p.get("count", 1))
                break
        else:
            rows.append(dict(key, day=day, count=int(p.get("count", 1))))
    section["patterns"] = rows
    section["counts"] = {"total": sum(int(r.get("count", 0)) for r in rows),
                         "by_channel": _tally(rows, "channel"), "by_tier": _tally(rows, "tier"),
                         "by_shape": _tally(rows, "shape")}
    section["updated_at"] = now.isoformat(timespec="seconds")
    data["inbound"] = section
    save(data, state)
    return section


def _tally(rows, field):
    out = {}
    for r in rows:
        out[r.get(field, "")] = out.get(r.get(field, ""), 0) + int(r.get("count", 0))
    return out


def _fake_driver(request):
    return {"url": f"dry-run://{request['ref'].get('id')}", "urn": None}


def _request(p):
    """`(channel key, kind, text, target)` for a drafted proposal: a reply on X, a comment on LinkedIn."""
    import channels
    key = channels.channel_key(p.get("platform"))
    kind = "reply" if key == "x" else "comment"
    target = str(p.get("target_url") or "").strip()
    if key == "linkedin" and str(p.get("target_post") or "").startswith("urn:li:"):
        target = str(p["target_post"]).strip()
    return key, kind, str(p.get("draft_comment") or ""), target


def send_due(state=None, live=False, driver=None, at=None, limit=None):
    """Send each drafted proposal that is still waiting through `channels.send()`, when its stream's
    auto-reply switch for the channel is on. Returns one row per proposal: `{id, channel, outcome, ...}`
    with `outcome` `sent`, `refused` (the check and reason), `failed` or `skipped` (and why).

    `live=False` (the default) runs every check against a temp copy of the send state with a fake
    driver: nothing is sent and nothing real is written. `live=True` uses `driver`, else the stream's
    write driver (`control.reply_driver`), and records each sent reply as an engagement act. `limit` is
    the most replies sent in one run (engine.json `engagement.send_max`, default 3)."""
    import channels
    import config
    import desk_sync
    import shutil
    import switches
    import tempfile
    state = state or STATE
    limit = int(limit if limit is not None else config.cfg("engagement.send_max", 3))
    work, tmp = state, None
    if not live:
        tmp = tempfile.mkdtemp(prefix="send-due-")
        for name in (channels.ACTS_FILE, channels.LIFECYCLE_FILE, channels.LEDGER_FILE, channels.SENDS_LOG, switches.FILE):
            if os.path.exists(os.path.join(state, name)):
                shutil.copy2(os.path.join(state, name), os.path.join(tmp, name))
        work, driver = tmp, driver or _fake_driver
    try:
        decisions = {}
        try:
            with open(os.path.join(state, "decisions.json"), encoding="utf-8") as f:
                decisions = json.load(f)
        except (OSError, ValueError):
            pass
        rows, sent = [], 0
        for p in load(state).get("proposals") or []:
            pid = desk_sync.proposal_id(p)
            row = {"id": pid}
            d = decisions.get(pid)
            if ((d.get("status") if isinstance(d, dict) else d) or "proposed") != "proposed":
                rows.append(dict(row, outcome="skipped", reason="already placed, held or rejected on the desk"))
                continue
            try:
                key, kind, text, target = _request(p)
            except channels.ChannelError as exc:
                rows.append(dict(row, outcome="skipped", reason=str(exc)))
                continue
            row.update(channel=key, kind=kind)
            try:
                stream = _slug(p.get("stream"))
                on = channels.auto_reply_on(stream, key, work)
            except Exception as exc:  # an unknown stream or an unreadable registry: nothing is sent
                rows.append(dict(row, outcome="skipped", reason=str(exc)[:200]))
                continue
            if not on:
                rows.append(dict(row, outcome="skipped", reason=f"the auto-reply switch is off for {stream}/{key}"))
                continue
            if sent >= limit:
                rows.append(dict(row, outcome="skipped", reason=f"the per-run limit of {limit} replies is reached"))
                continue
            ref = {"id": pid, "target": target, "cites": p.get("cites") or [], "title": p.get("target_title") or pid}
            use = driver
            if use is None:
                import control
                use = control.reply_driver(stream, key)
            try:
                got = channels.send(stream, key, kind, text, ref, driver=use, state=work, at=at)
            except channels.SendRefused as exc:
                rows.append(dict(row, outcome="refused", check=exc.check, reason=exc.reason))
                continue
            except channels.ChannelError as exc:
                rows.append(dict(row, outcome="failed", reason=str(exc)[:200]))
                continue
            sent += 1
            rows.append(dict(row, outcome="sent", url=got.get("url", "")))
            if live:
                tier = p.get("tier") if p.get("tier") in TIERS else "other"
                record(p.get("finding_id") or pid, p.get("theme") or "", p.get("platform") or key, p.get("target_post") or target,
                       tier, p.get("shape") or kind, "", stream, state)
        return rows
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def _slug(name):
    """A proposal's stream (a name such as `Acme`, or nothing) as the registry's slug."""
    import memory
    return memory.slug_for(name) if name else memory.DEFAULT_STREAM


def checklist(item, now=None):
    """The golden-hour checklist for a published item, timed from its real
    publish time, for the desk card; empty for an unpublished item."""
    pub = _parse(item.get("published_at"))
    if not pub:
        return []
    now = now or _now()
    out = []
    for label, action in GOLDEN_HOUR:
        out.append({"when": label, "action": action, "from": pub.isoformat(timespec="seconds")})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="engagement acts: record, outcome, due, ledger")
    ap.add_argument("--state", default=STATE)
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("record")
    for k in ("--item", "--theme", "--platform", "--target", "--tier", "--shape"):
        r.add_argument(k, required=True)
    r.add_argument("--comment-id", default="")
    r.add_argument("--kind", choices=KINDS, default=None, help="a reaction's kind (like, repost, quote); a comment or reply needs none")
    r.add_argument("--stream", default=memory.DEFAULT_STREAM_NAME)
    o = sub.add_parser("outcome"); o.add_argument("id"); o.add_argument("result", choices=OUTCOMES)
    sub.add_parser("due"); sub.add_parser("ledger")
    sd = sub.add_parser("send-due", help="send drafted replies through channels.send() where the auto-reply switch is on")
    sd.add_argument("--live", action="store_true", help="really send, with the stream's write driver (default: dry, fake driver)")
    sd.add_argument("--max", type=int, default=None, help="most replies to send in one run")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "record":
            act = record(a.item, a.theme, a.platform, a.target, a.tier, a.shape, a.comment_id, a.stream, a.state, kind=a.kind)
            print(f"recorded {act['id']}: {act['shape']} on a {act['tier']} target for {act['item_id']}")
        elif a.cmd == "outcome":
            act = outcome(a.id, a.result, a.state)
            print(f"{act['id']}: {act['outcome']}")
        elif a.cmd == "due":
            for act in due(a.state):
                print(f"{act['id']}  {act['platform']}  {act['tier']} / {act['shape']}  placed {act['placed_at']}")
        elif a.cmd == "ledger":
            for key, row in ledger(a.state).items():
                print(f"{key:<40} placed {row['placed']}  replied {row['author replied']}  follow {row['follow']}  nothing {row['nothing']}  open {row['open']}")
        elif a.cmd == "send-due":
            for r in send_due(a.state, live=a.live, limit=a.max):
                extra = r.get("url") or " ".join(x for x in (r.get("check"), r.get("reason")) if x)
                print(f"{'LIVE' if a.live else 'dry '}  {r['id']}  {r.get('channel', '-')}  {r['outcome']}  {extra}".rstrip())
        else:
            ap.print_help()
    except (ValueError, KeyError) as e:
        print(f"engage: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
