#!/usr/bin/env python3
"""
reactions.py - likes and reposts: which posts are worth one, and the sender that makes them.

Why: a brand that only posts looks like it is not listening. A like or a repost on a partner's
post, on an account a person watches, or on a reply to one of our own, is the smallest act of
taking part, and it is cheap to get wrong: the brand's name ends up beside whatever it liked.
So the plan is code, the limits are code, and every reaction goes through `channels.send()`,
which asks again at the moment of sending.

  plan       candidates from what the engine already read: the listening pass and its
             `@watched` pass (state/listening-*.json), the standing monitors' replies to our own
             account (state/x-stream/<day>.jsonl), ranked by tier and by the themes the last
             assessment found warm (state/signals.json). Written to state/reactions.json as a
             post id, a tier and a theme. Never a handle, never the post's words.
  send-due   each queued candidate through `channels.send()`: the stream's own account, one
             reaction per target ever, a target we may touch, the hours, the day's cap, and
             either a person's click or the kind's review mode on `auto`. Dry by default (a
             copy of the records and a driver that sends nothing); `--live` really sends,
             spaced out, with a limit per run.
  status     what is queued, done, waiting for a click and refused, with each reason.

A like on X is never sent on its mode alone: X requires a like to be initiated by the
account's user (decisions/2026-11-13-reactions-platform-rules.md). Such a candidate ends
`waiting`, and one click on the Engagement page sends it. LinkedIn has no like from here: no
tool creates one. A quote post is not planned here: it carries text of ours, so it is drafted,
gated and decided like a reply.

The author's handle and the post's text are needed to decide whether a post may be touched, and
they are needed again when it is sent. They are read each time from the listening files (the
gitignored audit trail) and written into no record here (standing rule 6).

  engine reactions plan [--dry-run] [--stream <slug>]
  engine reactions send-due              # dry: every check, nothing sent
  engine reactions send-due --live [--max 3]
  engine reactions send-due --scheduled  # live only when reactions.live is true
  engine reactions status
"""
import argparse
import datetime as dt
import glob
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
STATE = paths.state()
FILE = "reactions.json"
sys.path.insert(0, HERE)

import channels  # noqa: E402
import config  # noqa: E402
import memory  # noqa: E402

#: the tiers a candidate may carry (engage.TIERS), best first: a cleared partner, an account a
#: person watches, anyone who answered us
RANK = {"institution": 0, "peer": 1, "other": 2}
SOURCES = ("watchlist", "listening", "replies")
STATES = ("queued", "waiting", "done", "refused")
#: which reaction a tier earns: every eligible post a like, a cleared partner's also a repost
KINDS_FOR = {"institution": ("like", "repost"), "peer": ("like",), "other": ("like",)}
KEEP_DAYS = 14


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def path(state=None):
    return os.path.join(state or STATE, FILE)


def load(state=None):
    try:
        with open(path(state), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        data = {"candidates": []}
    return data


def save(data, state=None):
    p = path(state)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    blob = json.dumps(data, indent=1, ensure_ascii=False)
    if "@" in blob:
        # the one rule this file may not break: a candidate is a post id, a tier and a theme
        raise ValueError("reactions.json would hold a handle; a candidate carries a post id, never an author")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(blob + "\n")
    os.replace(tmp, p)
    return p


# --- what the engine read: the facts a check needs, never stored ---------------------------------

def _recent(value, cutoff):
    try:
        when = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return True  # a post with no readable date is judged on the file it came in
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when >= cutoff


def read_posts(state=None, days=None, now=None):
    """`{(channel, post id): {author, text, theme, source, in_reply_to_handle}}` for every post in
    the listening files and the standing monitors' day files of the last `days`.

    In memory only: this is where a candidate's author and words come from at plan time and
    again at send time, and nothing here is written back."""
    state = state or STATE
    now = now or _now()
    days = int(days if days is not None else config.cfg("reactions.window_days", 3))
    cutoff = now - dt.timedelta(days=days)
    out = {}
    for file in sorted(glob.glob(os.path.join(state, "listening-*.json"))):
        try:
            with open(file, encoding="utf-8") as f:
                items = (json.load(f) or {}).get("items") or []
        except (OSError, ValueError):
            continue
        for it in items:
            key = "linkedin" if it.get("source") == "linkedin" else "x"
            pid = str(it.get("id") or "").strip()
            if not pid or not _recent(it.get("created_at"), cutoff):
                continue
            term = str(it.get("_matched_term") or "")
            out[(key, pid)] = {"author": str(it.get("author") or ""), "text": str(it.get("text") or ""),
                               "theme": term if term.startswith("#") else "",
                               "source": "watchlist" if term == "@watched" else "listening", "in_reply_to_handle": ""}
    for file in sorted(glob.glob(os.path.join(state, "x-stream", "*.jsonl"))):
        try:
            with open(file, encoding="utf-8") as f:
                rows = [json.loads(line) for line in f if line.strip()]
        except (OSError, ValueError):
            continue
        for r in rows:
            pid = str(r.get("id") or "").strip()
            if not pid or not r.get("is_reply") or not r.get("in_reply_to") or not _recent(r.get("received_at"), cutoff):
                continue
            out.setdefault(("x", pid), {"author": str(r.get("handle") or ""), "text": str(r.get("text") or ""), "theme": "",
                                        "source": "replies", "in_reply_to_handle": str(r.get("in_reply_to") or "")})
            out[("x", pid)]["in_reply_to_handle"] = str(r.get("in_reply_to") or "")
    return out


def _warm(state):
    """`{theme: position}` from the last assessment's warmest themes; a theme it does not rank comes last."""
    try:
        with open(os.path.join(state or STATE, "signals.json"), encoding="utf-8") as f:
            ranked = ((json.load(f) or {}).get("warmest_themes") or {}).get("ranked") or []
    except (OSError, ValueError):
        ranked = []
    return {str(r.get("theme")): i for i, r in enumerate(ranked) if isinstance(r, dict)}


def tier_of(stream, key, fact, state):
    """`institution` for a verified cleared partner, `peer` for a watched account, `other` for a
    reply to our own account, None for anyone else (who is not a candidate at all)."""
    author = channels._handle(fact.get("author"))
    cleared = set()
    for row in memory.taggable_handles(stream).values():
        cleared |= {channels._handle(row.get(k)) for k in ("x", "linkedin") if row.get(k)}
    if author and author in cleared:
        return "institution"
    if author and author in channels._watched(state):
        return "peer"
    own = channels._handle(dict(channels.stream_channels(stream)).get(key))
    if own and channels._handle(fact.get("in_reply_to_handle")) == own:
        return "other"
    return None


def ref_for(cand, fact):
    """The `ref` channels.send() takes for a candidate: its id and target, and the transient facts."""
    return {"id": cand["id"], "target_id": cand["target_id"], "author": fact.get("author", ""),
            "target_text": fact.get("text", ""), "in_reply_to_handle": fact.get("in_reply_to_handle", "")}


# --- plan --------------------------------------------------------------------------------------

def plan(stream=None, state=None, now=None, write=True, posts=None):
    """Find the posts worth a like or a repost and queue them. Returns the file's content.

    A candidate keeps its state across plans: what was done stays done, and a post is never
    queued twice. A post that fails the target checks is kept as `refused` with the reason, so a
    person can see what was considered and why not. Candidates older than KEEP_DAYS go."""
    state = state or STATE
    now = now or _now()
    slug = (stream or memory.DEFAULT_STREAM).strip().lower()
    name = memory.stream(slug)["name"]
    posts = read_posts(state, now=now) if posts is None else posts
    warm = _warm(state)
    own_channels = [k for k, _ in channels.stream_channels(slug)]
    data = load(state)
    keep_after = (now - dt.timedelta(days=KEEP_DAYS)).isoformat()
    have = {c["id"]: c for c in data["candidates"]
            if isinstance(c, dict) and c.get("id") and str(c.get("planned_at", "")) >= keep_after and c.get("stream") == name}
    others = [c for c in data["candidates"] if isinstance(c, dict) and c.get("stream") not in (None, name)]
    for (key, pid), fact in sorted(posts.items()):
        if key not in own_channels:
            continue
        tier = tier_of(slug, key, fact, state)
        if tier is None:
            continue
        for kind in KINDS_FOR[tier]:
            if key == "linkedin" and (kind == "like" or not pid.startswith("urn:li:")):
                continue  # no tool likes on LinkedIn; a reshare needs the post's URN
            cid = f"{kind}:{pid}"
            if cid in have:
                continue
            cand = {"id": cid, "kind": kind, "channel": key, "target_id": pid, "tier": tier, "theme": fact.get("theme", ""),
                    "source": fact.get("source", "listening"), "stream": name,
                    "planned_at": now.isoformat(timespec="seconds"), "state": "queued", "reason": ""}
            why = channels.target_refusal(slug, key, ref_for(cand, fact), state)
            if why:
                cand.update(state="refused", check="target", reason=why)
            have[cid] = cand
    rows = sorted(have.values(), key=lambda c: (RANK.get(c.get("tier"), 9), warm.get(c.get("theme"), 99),
                                                0 if c.get("kind") == "like" else 1, c["id"]))
    for i, c in enumerate(rows, 1):
        c["rank"] = i
    out = {"stream": name, "planned_at": now.isoformat(timespec="seconds"), "candidates": rows + others}
    if write:
        save(out, state)
    return out


# --- send ----------------------------------------------------------------------------------------

def _dry_driver(request):
    return {"url": f"dry-run://{request['ref'].get('id')}", "urn": None}


def _driver(stream, key):
    import control
    return control.reply_driver(stream, key)


def send_one(cand, fact, state=None, live=False, driver=None, at=None):
    """One candidate through `channels.send()`. Returns `{id, kind, channel, outcome, check?, reason?}`
    with `outcome` `sent`, `waiting` (it needs a person's click), `refused` or `failed`."""
    slug = memory.slug_for(cand.get("stream") or memory.DEFAULT_STREAM)
    key, kind = cand["channel"], cand["kind"]
    row = {"id": cand["id"], "kind": kind, "channel": key}
    if fact is None:
        return dict(row, outcome="refused", check="target",
                    reason="the post is no longer in the listening files, so there is nothing to check it against")
    use = driver or (_driver(slug, key) if live else _dry_driver)
    try:
        channels.send(slug, key, kind, "", ref_for(cand, fact), driver=use, state=state, at=at)
    except channels.SendRefused as exc:
        waiting = exc.check == "kind rule"
        return dict(row, outcome="waiting" if waiting else "refused", check=exc.check, reason=exc.reason)
    except channels.ChannelError as exc:
        return dict(row, outcome="failed", reason=str(exc)[:200])
    return dict(row, outcome="sent")


def send_due(state=None, live=False, driver=None, at=None, limit=None, sleep=time.sleep, only=None):
    """Send what is queued. Returns one row per candidate tried.

    `live=False`, the default, runs every check against a temp copy of the send records with a
    driver that sends nothing, and writes nothing. `live=True` sends through the stream's write
    driver (or `driver`), waits `reactions.spacing_seconds` between two sends, stops at `limit`
    sends (`reactions.per_run`), marks each candidate, and records each reaction as an engagement
    act so the 72-hour ledger can say which ones earned a reply. `only` is one candidate id: the
    click on the Engagement page."""
    state = state or STATE
    limit = int(limit if limit is not None else config.cfg("reactions.per_run", 3))
    spacing = float(config.cfg("reactions.spacing_seconds", 45))
    data = load(state)
    posts = read_posts(state, now=at)
    work, tmp = state, None
    if not live:
        import switches
        tmp = tempfile.mkdtemp(prefix="reactions-dry-")
        for name in (channels.ACTS_FILE, channels.LIFECYCLE_FILE, channels.LEDGER_FILE, channels.SENDS_LOG, switches.FILE,
                     channels.WATCHLIST_FILE):
            if os.path.exists(os.path.join(state, name)):
                shutil.copy2(os.path.join(state, name), os.path.join(tmp, name))
        work = tmp
    rows, sent, just_sent = [], 0, False
    try:
        for cand in sorted((c for c in data["candidates"] if isinstance(c, dict)), key=lambda c: c.get("rank", 999)):
            if only is not None and cand.get("id") != only:
                continue
            if cand.get("state") not in ("queued", "waiting"):
                continue
            if sent >= limit:
                rows.append({"id": cand["id"], "kind": cand["kind"], "channel": cand["channel"], "outcome": "skipped",
                             "reason": f"the per-run limit of {limit} is reached"})
                continue
            if live and just_sent:
                sleep(spacing)  # two sends are never back to back, whatever is refused in between
            row = send_one(cand, posts.get((cand["channel"], cand["target_id"])), state=work, live=live, driver=driver, at=at)
            rows.append(row)
            just_sent = row["outcome"] == "sent"
            if just_sent:
                sent += 1
            if not live:
                continue
            stamp = (at or _now()).astimezone(dt.timezone.utc).isoformat(timespec="seconds")
            if row["outcome"] == "sent":
                cand.update(state="done", done_at=stamp, reason="", check="")
                _record(cand, state, at)
            elif row["outcome"] == "waiting":
                cand.update(state="waiting", check=row.get("check", ""), reason=row.get("reason", ""))
            elif row["outcome"] == "refused":
                done = row.get("check") == "dedupe"
                cand.update(state="done" if done else "refused", check=row.get("check", ""), reason=row.get("reason", ""))
            else:
                cand.update(check="driver", reason=row.get("reason", ""))  # a failed send stays queued for the next run
        if live:
            save(data, state)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    return rows


def _record(cand, state, at=None):
    """The reaction as an engagement act: its kind, the target's tier and theme, and no handle."""
    import engage
    try:
        engage.record(cand["id"], cand.get("theme") or "", channels.DISPLAY.get(cand["channel"], cand["channel"]),
                      cand["target_id"], cand.get("tier") if cand.get("tier") in engage.TIERS else "other", cand["kind"],
                      "", cand.get("stream") or memory.DEFAULT_STREAM_NAME, state, now=at, kind=cand["kind"])
    except (ValueError, OSError):
        pass  # the reaction went out; a ledger row that could not be written does not undo it


def click(cand_id, by="alpha", state=None, driver=None, at=None):
    """A person's one click on a candidate: an applied approval for exactly this reaction on this
    target, then the send, at once. Returns the send's row, with the act's id."""
    import acts
    import desk_acts
    state = state or STATE
    cand = next((c for c in load(state)["candidates"] if isinstance(c, dict) and c.get("id") == cand_id), None)
    if cand is None:
        raise KeyError(f"no reaction candidate {cand_id!r}")
    if cand.get("state") not in ("queued", "waiting"):
        raise KeyError(f"{cand_id} is {cand.get('state')}; only a queued or waiting reaction can be sent")
    slug = memory.slug_for(cand.get("stream") or memory.DEFAULT_STREAM)
    apath = os.path.join(state, channels.ACTS_FILE)
    act = acts.record("decision", slug, cand_id, {"decision": "approve", "item_kind": cand["kind"], "source": "dashboard"},
                      base=channels.reaction_hash(cand["channel"], cand["kind"], cand["target_id"]),
                      by=desk_acts.role_of(by), path=apath)
    acts.applied(act["id"], path=apath)
    rows = send_due(state, live=True, driver=driver, at=at, limit=1, only=cand_id)
    row = rows[0] if rows else {"id": cand_id, "outcome": "skipped", "reason": "nothing was tried"}
    return dict(row, act=act["id"])


def summary(state=None):
    """The candidates as the Engagement page shows them: grouped by state, undone ones marked."""
    data = load(state)
    ledger = channels._load_ledger(state)["sends"]
    out = {s: [] for s in STATES}
    for c in data["candidates"]:
        if not isinstance(c, dict) or c.get("state") not in STATES:
            continue
        row = {k: c.get(k) for k in ("id", "kind", "channel", "target_id", "tier", "theme", "source", "rank", "stream",
                                     "planned_at", "done_at", "check", "reason")}
        row["undone"] = ((ledger.get(c["id"]) or {}).get("taken_down") or {}).get("at")
        out[c["state"]].append(row)
    return {"planned_at": data.get("planned_at"), "stream": data.get("stream"), **out}


# --- CLI -----------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="likes and reposts: plan the candidates, send what is due")
    ap.add_argument("--state", default=STATE)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("plan")
    p.add_argument("--stream", default=memory.DEFAULT_STREAM)
    p.add_argument("--dry-run", action="store_true", help="show the candidates, write nothing")
    s = sub.add_parser("send-due")
    s.add_argument("--live", action="store_true", help="really send, through the stream's write driver (default: dry)")
    s.add_argument("--scheduled", action="store_true", help="live only when engine.json reactions.live is true")
    s.add_argument("--max", type=int, default=None, help="most reactions to send in one run")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":
            out = plan(a.stream, a.state, write=not a.dry_run)
            counts = {st: sum(1 for c in out["candidates"] if c.get("state") == st) for st in STATES}
            print(f"reactions plan for {out['stream']}: " + ", ".join(f"{n} {st}" for st, n in counts.items())
                  + ("  (dry run: nothing written)" if a.dry_run else ""))
            for c in out["candidates"][:20]:
                print(f"  {c['rank']:>3}  {c['id']:<34} {c['channel']:<9} {c['tier']:<12} {c['theme'] or '-':<18} {c['state']}"
                      + (f"  {c['reason'][:90]}" if c.get("reason") else ""))
            return 0
        if a.cmd == "send-due":
            live = a.live or (a.scheduled and bool(config.cfg("reactions.live", False)))
            rows = send_due(a.state, live=live, limit=a.max)
            for r in rows:
                extra = " ".join(x for x in (r.get("check"), r.get("reason")) if x)
                print(f"{'LIVE' if live else 'dry '}  {r['id']:<34} {r['channel']:<9} {r['outcome']}  {extra}".rstrip())
            print(f"reactions send-due: {sum(1 for r in rows if r['outcome'] == 'sent')} sent of {len(rows)} tried"
                  + ("" if live else "  (dry run: nothing sent, nothing written)"))
            return 0
        if a.cmd == "status":
            s_ = summary(a.state)
            print(f"planned {s_.get('planned_at') or 'never'}: " + ", ".join(f"{len(s_[st])} {st}" for st in STATES))
            for st in STATES:
                for c in s_[st]:
                    print(f"  {st:<8} {c['id']:<34} {c['channel']:<9} {c['tier']:<12}" + (f"  {c['reason'][:90]}" if c.get("reason") else ""))
            return 0
    except (memory.SharedMemoryError, ValueError, KeyError) as e:
        print(f"reactions: {e}", file=sys.stderr)
        return 1
    print(__doc__.strip().splitlines()[0])
    ap.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
