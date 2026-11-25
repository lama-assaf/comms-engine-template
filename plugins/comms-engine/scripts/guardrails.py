#!/usr/bin/env python3
"""
guardrails.py - the registry's guardrails, enforced before anything leaves (A13).

`.atelier/memory/streams.md` carries per stream: the channels that are
drafts-only, posts per channel per day, quiet hours, blocked topics and the
hold-for-review classes. The stream's `reactions_per_day` setting in brand.json
(`{"x": {"like": 20, "repost": 3}}`) is the cap on likes, reposts and quote posts;
a kind with no number there is capped at none. `publish.py` asks this module before it writes a
Ready row; the autopilot gets the same answer through `--check` (Block R
wires it). A refusal quotes the rule, so a person reads why.

  engine guardrails --stream acme --channel X --at 2026-10-27T09:00:00+02:00
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import zoneinfo

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
STATE = paths.state()
REPO = paths.instance()
sys.path.insert(0, HERE)
import memory  # noqa: E402

import config  # noqa: E402

CHANNELS = ("Blog", "LinkedIn", "X")
# The local time quiet hours and daily caps are judged in: engine.json
# autopilot.timezone (an IANA name; `engine.py setup autopilot --timezone`
# writes it). UTC until a brand sets its own.
TZ = str(config.cfg("autopilot.timezone", "UTC"))


def parse_guardrails(row):
    """The guardrails row of one stream, as structures.

    `drafts-only channels`: `all`, `none`, or channel names (`none for themes
    ... all for facts` reads as none for the theme kind). `posts per channel
    per day`: `X 2; LinkedIn 1; Blog 2 per ISO week` -> per-day caps and a
    per-week cap for Blog. `quiet hours`: weekends and a daily window.
    """
    g = row["guardrails"]
    txt = g.get("drafts-only channels", "").strip().lower()
    if txt.startswith("all"):
        drafts_only = set(CHANNELS)
    elif txt.startswith("none"):
        drafts_only = set()
    else:
        drafts_only = {c for c in CHANNELS if c.lower() in txt}
    caps, week_caps = {}, {}
    for part in g.get("posts per channel per day", "").split(";"):
        m = re.match(r"\s*(Blog|LinkedIn|X)\s+(\d+)(?:\s+per\s+ISO\s+week)?", part.strip(), re.I)
        if not m:
            continue
        ch = next(c for c in CHANNELS if c.lower() == m.group(1).lower())
        if "week" in part.lower():
            week_caps[ch] = int(m.group(2))
        else:
            caps[ch] = int(m.group(2))
    q = g.get("quiet hours", "").strip().lower()
    apart = re.search(r"at least\s+(\d+)\s+days?\s+apart", g.get("posts per channel per day", ""), re.I)
    quiet = {"weekends": "weekend" in q, "all": q.startswith("all"), "before": None, "after": None,
             "min_days_between_blogs": int(apart.group(1)) if apart else 0}
    m = re.search(r"before\s+(\d{1,2}):(\d{2})", q)
    if m:
        quiet["before"] = (int(m.group(1)), int(m.group(2)))
    m = re.search(r"after\s+(\d{1,2}):(\d{2})", q)
    if m:
        quiet["after"] = (int(m.group(1)), int(m.group(2)))
    return {"drafts_only": drafts_only, "caps": caps, "week_caps": week_caps, "quiet": quiet,
            "blocked_topics": g.get("blocked topics", ""), "hold_for_review": g.get("hold for review", ""),
            "autopilot": row.get("autopilot", "").strip(), "reactions": reaction_caps(row.get("slug"))}


def reaction_caps(slug):
    """`{channel key: {kind: n}}` from the stream's `reactions_per_day` setting in brand.json.

    Whole numbers of 0 or more only; anything else is left out, and a kind that is left out
    has no allowance at all: a reaction is never sent on a cap nobody set."""
    if not slug:
        return {}
    raw = config.cfg(f"streams.{str(slug).strip().lower()}.reactions_per_day", {}) or {}
    out = {}
    for channel, caps in raw.items() if isinstance(raw, dict) else []:
        if not isinstance(caps, dict):
            continue
        clean = {k: v for k, v in caps.items() if isinstance(v, int) and not isinstance(v, bool) and v >= 0}
        if clean:
            out[str(channel).lower()] = clean
    return out


def reaction_cap(stream, channel_key, kind, registry_path=None):
    """The most reactions of this kind the stream may make on this channel in a day; 0 when none is set."""
    row = memory.stream(stream, registry_path)
    return int(parse_guardrails(row)["reactions"].get(channel_key, {}).get(kind, 0))


def check_hours(stream, channel, at, registry_path=None):
    """`(ok, reason)`: may the stream send anything on this channel at this time, caps aside.

    The stream may send at all (autopilot, owner, voice), the channel is not drafts-only, and
    the time is outside the quiet hours. What a reaction is asked, since the post caps are not
    its caps."""
    row = memory.stream(stream, registry_path)
    g = parse_guardrails(row)
    if g["autopilot"].lower().startswith("nothing") or not memory.may_draft(stream, registry_path):
        return False, (f"{row['name']}: autopilot is '{g['autopilot'] or 'nothing'}' and owner is "
                       f"'{row['owner']}'. streams.md: a stream whose autopilot is nothing drafts and posts nothing.")
    if channel in g["drafts_only"]:
        return False, f"{row['name']}: {channel} is drafts-only (streams.md guardrails: drafts-only channels = {row['guardrails']['drafts-only channels']})."
    local = at.astimezone(zoneinfo.ZoneInfo(TZ))
    q = g["quiet"]
    if q["all"]:
        return False, f"{row['name']}: quiet hours are 'all hours' until onboarded (streams.md)."
    if q["weekends"] and local.weekday() >= 5:
        return False, f"{row['name']}: {local.strftime('%A')} is inside the quiet hours (streams.md: {row['guardrails']['quiet hours']})."
    hm = (local.hour, local.minute)
    if q["before"] and hm < q["before"]:
        return False, f"{row['name']}: {local.strftime('%H:%M')} is before {q['before'][0]:02d}:{q['before'][1]:02d} (streams.md: {row['guardrails']['quiet hours']})."
    if q["after"] and hm >= q["after"]:
        return False, f"{row['name']}: {local.strftime('%H:%M')} is after {q['after'][0]:02d}:{q['after'][1]:02d} (streams.md: {row['guardrails']['quiet hours']})."
    return True, ""


def check(stream, channel, at, published_today=0, published_this_week=0, last_blog_days_ago=None, registry_path=None):
    """`(ok, reason)` for one send on one channel at one time, given what has
    already gone out. `at` is timezone-aware; the quiet hours are read in
    the brand's timezone (TZ)."""
    ok, reason = check_hours(stream, channel, at, registry_path)
    if not ok:
        return False, reason
    row = memory.stream(stream, registry_path)
    g = parse_guardrails(row)
    q = g["quiet"]
    cap = g["caps"].get(channel)
    if cap is not None and published_today >= cap:
        return False, f"{row['name']}: {channel} is at its daily cap of {cap} (streams.md: {row['guardrails']['posts per channel per day']})."
    wcap = g["week_caps"].get(channel)
    if wcap is not None and published_this_week >= wcap:
        return False, f"{row['name']}: {channel} is at its weekly cap of {wcap} (streams.md: {row['guardrails']['posts per channel per day']})."
    if channel == "Blog" and q["min_days_between_blogs"] and last_blog_days_ago is not None and last_blog_days_ago < q["min_days_between_blogs"]:
        return False, f"{row['name']}: the last Blog went out {last_blog_days_ago} day(s) ago; at least {q['min_days_between_blogs']} days apart (streams.md)."
    return True, ""


def counts_from_notes(stream_name, channel, at, cal=None, exclude_engine_id=None):
    """How many notes of this stream and channel are already Ready, Scheduled
    or Published today and this ISO week, and the days since the last Blog.
    `exclude_engine_id` leaves the item being checked out of its own count."""
    import repo
    cal = cal or repo.CAL
    local_day = at.astimezone(zoneinfo.ZoneInfo(TZ)).date()
    week = local_day.isocalendar()[:2]
    today = this_week = 0
    last_blog = None
    if not os.path.isdir(cal):
        return 0, 0, None
    for name in os.listdir(cal):
        if not name.endswith(".md"):
            continue
        fm, _ = repo.parse_note(os.path.join(cal, name))
        if str(fm.get("stream", "")) != stream_name or str(fm.get("status", "")) not in ("Ready", "Scheduled", "Published"):
            continue
        if exclude_engine_id and str(fm.get("engine_id", "")) == str(exclude_engine_id):
            continue
        try:
            d = dt.date.fromisoformat(str(fm.get("date", ""))[:10])
        except ValueError:
            continue
        plat = str(fm.get("platform", ""))
        if plat == channel:
            if d == local_day:
                today += 1
            if d.isocalendar()[:2] == week:
                this_week += 1
        if plat == "Blog" and d <= local_day:
            ago = (local_day - d).days
            last_blog = ago if last_blog is None else min(last_blog, ago)
    return today, this_week, last_blog


def main(argv=None):
    ap = argparse.ArgumentParser(description="may this stream send on this channel now?")
    ap.add_argument("--stream", default=memory.DEFAULT_STREAM)
    ap.add_argument("--channel", default="X", choices=CHANNELS)
    ap.add_argument("--at", help="ISO time with offset (default now)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    at = dt.datetime.fromisoformat(a.at) if a.at else dt.datetime.now(dt.timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=dt.timezone.utc)
    try:
        row = memory.stream(a.stream)
        today, week, last = counts_from_notes(row["name"], a.channel, at)
        ok, why = check(a.stream, a.channel, at, today, week, last)
    except memory.SharedMemoryError as e:
        print(f"guardrails: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps({"ok": ok, "reason": why, "published_today": today, "published_this_week": week, "last_blog_days_ago": last}))
    else:
        print(("ok" if ok else "refused") + (f": {why}" if why else f": {row['name']} may send on {a.channel} now ({today} today, {week} this week)"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
