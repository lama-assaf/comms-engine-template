#!/usr/bin/env python3
"""
autopilot.py - the sender, and the calendar snapshot.

The calendar is the vault notes (`Content/Calendar/`, written by `repo.py`) plus the
lifecycle (`lifecycle.py`, state/lifecycle.jsonl). An item gives three calendar rows: its
Blog post, its LinkedIn teaser and its X teaser, on the note's date. This is what has to
happen between the loop and the handles:

  snapshot   build state/calendar-snapshot.json and the agent-readable digest
             .atelier/memory/calendar.md from the notes (the only writer of that file)
  approve    the approval with no person in it: each gated draft of the brand's
             stream whose verdict is pass, where a person switched the stream's
             post mode to `auto` for every channel it sends on (switches.py). One
             `decision` act with `by: engine` and the switch act that allowed it,
             then the same applier a person's approval runs. With the mode on
             `review`, the default, this step approves nothing
  post       send each channel post (`<item id>:x`, `<item id>:linkedin`) that is
             `scheduled` in the lifecycle for today or at most GRACE_DAYS back, the
             brand's stream, with the teaser's text from the note, within the
             registry's guardrails (streams.md: autopilot rule, quiet hours, caps)
  links      a first reply on X / first comment on LinkedIn carrying the article
             link, once a person has marked the item's article live on the control
             page (the `blog-live` act)
  run        snapshot, approve, post, links
  commit     commit the snapshot, ledger, log and digest (opt in; never part of run)

A post is scheduled by an approval (`desk_acts.approve`, from the desk or the control
page), which schedules one lifecycle id per channel with its own applied approve act for
that teaser's text. Every send, and the `links` step's link-reply, is `channels.send()`:
it runs the gate, cites, stealth, hold, pair, guardrail, quiet-hour and kind checks,
writes the ledger first and one line to state/sends.jsonl, whoever calls it. The ledger
is the record of what went out, with its URL; no note is flipped to Published.

Which write driver sends is engine.json `channels.write_driver.<stream>`: `native` (the
default; the xurl and linkedin_api code below, wrapped as drivers) or `composio`. A dry run
sends through a driver that sends nothing, on a copy of the records.

Rules carried over unchanged: the ledger (state/send-ledger.json) is written BEFORE a send
and a text is never sent twice; a post is looked up by its own id and by the hash of its
text; a failed send is recorded and the next post still goes; a post past GRACE_DAYS stays
scheduled and is logged as stale; another stream's posts are never touched; a teaser with a
link in the body or editorial voice is held, with the reason. Every send asks
`guardrails.check` first, so the decision whether the brand posts automatically at all is
one row in streams.md.

Credentials come from `scripts/secrets.py` (environment, then the keychain): LINKEDIN_*
for the page; X through `npx @xdevplatform/xurl` with the brand's slug as the app name
(OAuth login once: `xurl auth oauth2 --app <slug>`).

Every send passes channels.send() with its checks, from here or anywhere else;
the PreToolUse hook only refuses a raw platform write that bypasses it, and
does not ask who runs this script. `--dry` prints what would happen and writes
nothing, from anywhere.

  engine autopilot snapshot
  engine autopilot approve --dry    # what the engine would approve, and why not the rest
  engine autopilot run --dry
  engine autopilot status
"""
from __future__ import annotations

import datetime as dt
import atexit
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
REPO = paths.instance()
STATE = paths.state()
sys.path.insert(0, HERE)
import channels  # noqa: E402
import desk_acts  # noqa: E402
import guardrails  # noqa: E402
import lifecycle  # noqa: E402
import linkedin_api  # noqa: E402
import memory  # noqa: E402
import repo  # noqa: E402
import runlog  # noqa: E402

LEDGER_FILE = os.path.join(STATE, "send-ledger.json")
PUBLISH_LOG = os.path.join(STATE, "publish-log.json")
SNAPSHOT_FILE = os.path.join(STATE, "calendar-snapshot.json")
LOG_FILE = os.path.join(STATE, "autopilot.log")
AUTO_STATE = os.path.join(STATE, "autopilot-state.json")
MEMORY_DIGEST = os.path.join(REPO, ".atelier", "memory", "calendar.md")
LEGACY = {}  # earlier ledgers to seed the state copies from, so no send is repeated; none in the template

# The brand's stream: engine.json brand.slug / brand.name through memory.py.
STREAM = memory.DEFAULT_STREAM
STREAM_NAME = memory.DEFAULT_STREAM_NAME
STREAM_NAMES = (STREAM_NAME, "Both")
# engine.json autopilot.grace_days (engine.py setup autopilot writes it) and
# site.post_url (where an article lives by its slug); the shipped constants
# when config.py or the file cannot be read, so the sender never stops over
# its own configuration.
try:
    import config as _config
    GRACE_DAYS = int(_config.cfg("autopilot.grace_days", 2))
    SITE_POST_URL = str(_config.cfg("site.post_url", "https://www.example.com/insights/{slug}"))
except Exception:
    GRACE_DAYS = 2
    SITE_POST_URL = "https://www.example.com/insights/{slug}"
X_LIMIT = 280
X_URL_WEIGHT = 23
X_APP = STREAM  # the xurl OAuth app name: `xurl auth oauth2 --app <slug>`
ACTOR = "engine autopilot (Claude Code, streams.md rule)"
LINKEDIN_SOCIAL_BLOCK_HOURS = 24
LINK_CAPTIONS = {"X": channels.LINK_CAPTIONS["x"], "LinkedIn": channels.LINK_CAPTIONS["linkedin"]}  # channels.send() checks a link-reply against these
LEAK_PATTERN = re.compile(
    r"no draft should|until the handle is verified|status record|per instincts|claim gate|post-audit|frontmatter|"
    r"first (comment|reply) (has|carries|contains)|in (the )?first (comment|reply)|pillar for this piece|"
    r"communications rule|this piece|this draft|the point of this post|the " + re.escape(STREAM_NAME) + r" line|"
    + re.escape(STREAM_NAME) + r" (should|must) (argue|state|keep)",
    re.I)
STAGE_DIRECTION = re.compile(r"[^.\n]*\b(first (comment|reply)|source note|blog CTA|CTA in|link in)\b[^.\n]*[.!]\s*", re.I)
URL_RE = re.compile(r"https?://\S+")

# Both spellings: the posting hook lets either through as a dry run, so both must be one.
DRY = "--dry" in sys.argv or "--dry-run" in sys.argv
TODAY = dt.date.today()
NOW_DT = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
NOW = NOW_DT.isoformat()


# ------------------------------------------------------------------ small helpers


def log(message: str) -> None:
    line = f"{dt.datetime.now().isoformat(timespec='seconds')} {'[dry] ' if DRY else ''}{message}"
    print(line)
    if not DRY:
        os.makedirs(STATE, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def load_json(path: str, default=None):
    if not os.path.exists(path):
        if path in LEGACY and os.path.exists(LEGACY[path]):
            if not DRY:
                shutil.copyfile(LEGACY[path], path)
                log(f"seeded {os.path.relpath(path, REPO)} from {os.path.relpath(LEGACY[path], REPO)}")
            with open(LEGACY[path], encoding="utf-8") as f:
                return json.load(f)
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data) -> None:
    if DRY:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(path + ".tmp", path)


def x_weighted_length(text: str) -> int:
    """X counts every URL as X_URL_WEIGHT characters whatever its length."""
    return len(URL_RE.sub("x" * X_URL_WEIGHT, text))


def text_hash(platform: str, text: str) -> str:
    return hashlib.sha256((platform + "\n" + re.sub(r"\s+", " ", text.strip().lower())).encode()).hexdigest()[:20]


def teaser_problem(platform: str, text: str) -> str | None:
    """Why a teaser may not be posted as written; None when clean."""
    if not text or not text.strip():
        return "empty"
    if platform == "X" and x_weighted_length(text) > X_LIMIT:
        return f"{x_weighted_length(text)} weighted characters exceeds {X_LIMIT}"
    if URL_RE.search(text):
        return "link inside the body (the link goes in the first reply or comment, decision 2026-10-12)"
    leak = LEAK_PATTERN.search(text) or STAGE_DIRECTION.search(text)
    if leak:
        return f"editorial voice or stage direction ('{leak.group(0).strip()[:50]}')"
    return None


def due(day: dt.date | None, today: dt.date = None) -> str | None:
    """None when the row is due today or inside the grace window; else why not."""
    today = today or TODAY
    if day is None:
        return "no date"
    if day > today:
        return "future"
    if (today - day).days > GRACE_DAYS:
        return f"more than {GRACE_DAYS} days late, not posted"
    return None


# ------------------------------------------------------------------ the calendar, from the notes


def load_notes() -> dict:
    """Every engine note, as `repo.scan_notes()` reads them: {id: {"Blog": (path, fm, body), "LinkedIn": ...}}."""
    return repo.scan_notes()


def note_items(notes: dict) -> dict:
    """{id: (item, post frontmatter, teasers frontmatter)} for each item with a post note."""
    out = {}
    for eid, pair in notes.items():
        post = pair.get("Blog")
        if not post:
            continue
        teasers = pair.get("LinkedIn")
        item = repo.item_from_note(post[1], post[2], (teasers[1], teasers[2]) if teasers else None)
        out[eid] = (item, post[1], teasers[1] if teasers else {})
    return out


def _day(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def article_link_for(item: dict | None, state: str | None = None) -> str | None:
    """The live article's URL once a person has marked it live (the `blog-live` act), else None."""
    if not item:
        return None
    return desk_acts.live_url(item, state or state_dir())


def _channel_status(cid: str, fallback: str, sends: dict, lpath: str) -> tuple[str, str | None]:
    """A channel row's status and date: Published once sent, Scheduled / Ready by the lifecycle, else the note's."""
    line = lifecycle.current(cid, lpath) or {}
    if (sends.get(cid) or {}).get("state") == "sent" or line.get("to") in ("sent", "scored"):
        return "Published", line.get("date")
    if line.get("to") == "scheduled":
        return "Scheduled", line.get("date")
    if line.get("to") == "decided":
        return "Ready", None
    return fallback, None


def calendar_rows(notes: dict | None = None, state: str | None = None, today: dt.date | None = None) -> list[dict]:
    """The calendar as rows, built from the notes: Blog, LinkedIn and X per item, in the snapshot's shape.

    `page_id` is `<item id>:<channel>`; the body is kept for rows within 30 days of today."""
    notes = load_notes() if notes is None else notes
    state = state or state_dir()
    today = today or TODAY
    lpath = _lifecycle_path(state)
    sends = channels._load_ledger(state).get("sends") or {}
    rows = []
    for eid, (item, fm, fm_t) in note_items(notes).items():
        status = str(fm.get("status") or "Idea")
        if item.get("alpha_status") in (repo.SUPERSEDED, "rejected"):
            status = "pause"
        slug = item.get("slug") or ""
        base = {"title": item.get("title") or eid, "stream": item.get("stream") or "", "pillar": item.get("pillar") or "",
                "engine": item.get("drafted_by") != repo.TEAM_BY, "id": eid}
        note_day = _day((item.get("slot") or {}).get("date"))
        if str(item.get("post") or "").strip():
            live = article_link_for(item, state)
            rows.append(dict(base, page_id=f"{eid}:blog", platform="Blog", slug=slug,
                             status="Published" if live else status, date=note_day, body=item["post"], url=live))
        for key, field, platform in desk_acts.CHANNELS:
            text = str(item.get(field) or "").strip()
            if not text:
                continue
            cid = desk_acts.channel_id(eid, key)
            fallback = status if status == "pause" else str(fm_t.get("status") or status)
            st, when = _channel_status(cid, fallback, sends, lpath)
            rows.append(dict(base, page_id=cid, platform=platform, slug=f"{slug}-{key}" if slug else "", status=st,
                             date=_day(when) or note_day, body=text, url=(sends.get(cid) or {}).get("url")))
    for r in rows:
        near = r["date"] is not None and abs((r["date"] - today).days) <= 30
        r["date"] = r["date"].isoformat() if r["date"] else None
        r["body"] = r["body"] if near else ""
    rows.sort(key=lambda r: (r["date"] or "", r["platform"], r["page_id"]))
    return rows


def digest_lines(rows: list[dict], now: str = NOW) -> list[str]:
    """`.atelier/memory/calendar.md`: the brand's rows that are not paused, as the
    agents read them before proposing. The theme-writer's duplicate check reads
    these columns."""
    ours = [r for r in rows if r["stream"] in STREAM_NAMES and r["status"] != "pause"]
    lines = ["# calendar - what is already planned and published", "",
             f"Generated by the engine autopilot from the calendar notes (Content/Calendar) and the lifecycle on {now}. Do not edit by hand.",
             "Read this before proposing or drafting. A proposal whose headline or argument repeats a row below is a duplicate:",
             "attach the signal to the existing piece instead. Never reuse a headline or a sentence that appears here.",
             "Full text of rows within 30 days is in `state/calendar-snapshot.json`.", "",
             "| date | platform | status | by | headline | opening line |", "|---|---|---|---|---|---|"]
    for r in ours:
        first = (r["body"].split("\n")[0] if r["body"] else "").replace("|", "/")[:110]
        by = "engine" if r.get("engine") else "team"
        lines.append(f"| {r['date'] or '-'} | {r['platform']} | {r['status']} | {by} | {r['title'].replace('|', '/')[:110]} | {first} |")
    return lines


def step_snapshot(notes: dict | None = None) -> int:
    rows = calendar_rows(notes)
    log(f"snapshot {len(rows)} calendar rows from the notes ({sum(1 for r in rows if r['body'])} with body text)")
    if DRY:
        return len(rows)
    save_json(SNAPSHOT_FILE, {"taken_at": NOW, "source": "notes", "rows": rows})
    with open(MEMORY_DIGEST, "w", encoding="utf-8") as f:
        f.write("\n".join(digest_lines(rows)) + "\n")
    return len(rows)


# ------------------------------------------------------------------ senders


def x_ready() -> bool:
    try:
        out = subprocess.run(["npx", "-y", "@xdevplatform/xurl", "auth", "status"],
                             capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    block = re.search(rf"^\W*{X_APP}\s.*?(?=^\S|\Z)", out, re.S | re.M)
    oauth = re.search(r"oauth2:\s*(.+)", block.group(0)) if block else None
    return bool(oauth and "(none)" not in oauth.group(1) and oauth.group(1).strip() not in ("–", "-"))


def _xurl(*args: str) -> str:
    result = subprocess.run(["npx", "-y", "@xdevplatform/xurl", "--app", X_APP, *args],
                            capture_output=True, text=True, timeout=120)
    match = re.search(r'"id"\s*:\s*"(\d+)"', result.stdout)
    if result.returncode != 0 or not match:
        raise RuntimeError(f"xurl {args[0]} failed: {(result.stderr or result.stdout)[-300:]}")
    return f"https://x.com/i/web/status/{match.group(1)}"


def post_x(text: str) -> str:
    return _xurl("post", text)


def post_x_reply(post_url: str, text: str) -> str:
    return _xurl("reply", post_url.rsplit("/", 1)[-1], text)


def post_linkedin(text: str) -> tuple[str, str]:
    config = linkedin_api.settings(STREAM)
    author = linkedin_api.author_urn(config)
    result = linkedin_api.create_post(config, linkedin_api.build_post_payload(author=author, text=text))
    return result.get("url") or "", result.get("urn") or ""


def post_linkedin_comment(post_urn: str, text: str) -> str:
    config = linkedin_api.settings(STREAM)
    actor = linkedin_api.author_urn(config)
    return linkedin_api.create_comment(config, post_urn, linkedin_api.build_comment_payload(actor=actor, text=text)).get("urn") or ""


def linkedin_social_blocked() -> str | None:
    state = load_json(AUTO_STATE, {}) or {}
    at = state.get("linkedin_social_actions_blocked_at")
    if not at:
        return None
    since = dt.datetime.fromisoformat(at)
    if NOW_DT - since > dt.timedelta(hours=LINKEDIN_SOCIAL_BLOCK_HOURS):
        return None
    return f"LinkedIn comments blocked since {at[:16]}Z (socialActions answered 403; retried after {LINKEDIN_SOCIAL_BLOCK_HOURS} h)"


def note_linkedin_social_failure(exc: Exception) -> None:
    text = str(exc)
    if "partnerApiSocialActions" in text or "ACCESS_DENIED" in text or "HTTP 403" in text:
        state = load_json(AUTO_STATE, {}) or {}
        state["linkedin_social_actions_blocked_at"] = NOW
        save_json(AUTO_STATE, state)


# ------------------------------------------------------------------ write drivers, state


#: What the native paths can carry. Anything else (a take down, a like, a repost, a quote) is
#: refused by name: a kind this code does not know must never be sent as if it were a reply.
NATIVE_REPLY_KINDS = ("reply", "comment", "link-reply")


def _native_only(request: dict, channel: str) -> None:
    if request.get("media"):
        raise RuntimeError(f"the native {channel} driver cannot attach media; set channels.write_driver to composio "
                           "for this stream, or approve the post without its card")
    if request["kind"] != "post" and request["kind"] not in NATIVE_REPLY_KINDS:
        raise RuntimeError(f"the native {channel} driver has no {request['kind']}; set channels.write_driver to "
                           "composio for this stream, or do it on the platform by hand")


def native_x_driver(request: dict) -> dict:
    """The xurl path as a write driver: a post, or a reply to `target` (a post URL)."""
    _native_only(request, "X")
    if request["kind"] == "post":
        return {"url": post_x(request["text"])}
    return {"url": post_x_reply(request["target"], request["text"])}


def native_linkedin_driver(request: dict) -> dict:
    """The linkedin_api path as a write driver: a post, or a comment on `target` (a post URN)."""
    _native_only(request, "LinkedIn")
    if request["kind"] == "post":
        url, urn = post_linkedin(request["text"])
        return {"url": url, "urn": urn}
    return {"url": "", "urn": post_linkedin_comment(request["target"], request["text"])}


def dry_driver(request: dict) -> dict:
    """What a dry run sends through: every check runs, nothing leaves the machine."""
    return {"url": "(dry run)", "urn": None}


NATIVE_DRIVERS = {"x": native_x_driver, "linkedin": native_linkedin_driver}
_WRITE_DRIVER_LOGGED = []


def write_drivers() -> dict:
    """The write driver of each channel, chosen by `channels.write_driver.<stream>` in engine.json
    (`native`, the default: the code above; `composio`: channels.py's drivers). Registered into
    channels.send() and returned; a dry run gets the dry driver whatever is configured. A value
    that is neither is logged and read as native, so a typo never stops the sender."""
    name, why = channels.write_driver(STREAM)
    if why and why not in _WRITE_DRIVER_LOGGED:
        _WRITE_DRIVER_LOGGED.append(why)
        log(f"channels.write_driver.{STREAM} is {name!r} ({why}); using native")
    if DRY:
        return {key: dry_driver for key in NATIVE_DRIVERS}
    if name == "composio" and not why:
        channels.register_defaults()
        return {"x": channels.x_driver, "linkedin": channels.linkedin_driver}
    for key, fn in NATIVE_DRIVERS.items():
        channels.register_driver(key, fn)
    return dict(NATIVE_DRIVERS)


_DRY_STATE: list = []


def state_dir() -> str:
    """The directory channels.send(), lifecycle.py and acts.py keep their records in: beside the
    ledger. A dry run works on a throwaway copy of those records, so the checks that read them
    (never-send-twice, the lifecycle, the approvals, the caps) run for real and nothing is written."""
    real = os.path.dirname(LEDGER_FILE)
    if not DRY:
        return real
    if not _DRY_STATE or _DRY_STATE[0] != real:
        tmp = tempfile.mkdtemp(prefix="autopilot-dry-")
        atexit.register(shutil.rmtree, tmp, True)
        for name in (channels.LEDGER_FILE, channels.SENDS_LOG, channels.LIFECYCLE_FILE, channels.ACTS_FILE):
            src = os.path.join(real, name)
            if not os.path.exists(src) and os.path.join(real, name) == LEDGER_FILE:
                src = LEGACY.get(LEDGER_FILE, src)
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(tmp, name))
        _DRY_STATE[:] = [real, tmp]
    return _DRY_STATE[1]


def _sync(ledger: dict) -> None:
    """Make the caller's ledger dict what channels.send() has on disk (it is the only writer)."""
    ledger.clear()
    ledger.update(channels._load_ledger(state_dir()))


def do_send(platform: str, kind: str, text: str, ref: dict, drivers: dict):
    """The one way this script sends: through channels.send(), which refuses what fails a check and
    records the attempt. Raises SendRefused or ChannelError."""
    key = platform.lower()
    return channels.send(STREAM, key, kind, text, ref, driver=drivers.get(key), state=state_dir(), at=NOW_DT)


def _lifecycle_path(state: str) -> str:
    return os.path.join(state, channels.LIFECYCLE_FILE)


# ------------------------------------------------------------------ approve


def step_approve(notes: dict | None = None) -> int:
    """Approve what may go without a person: `desk_acts.engine_approve` over each draft of the
    brand's stream that still waits. It refuses unless a person switched the post mode to `auto`
    for every channel of the item, so on a stream left on `review` this approves nothing. A dry
    run asks every check and records nothing."""
    state = state_dir()
    lpath = _lifecycle_path(state)
    items = {eid: triple[0] for eid, triple in note_items(load_notes() if notes is None else notes).items()}
    approved = 0
    for eid in sorted(items):
        item = items[eid]
        if item.get("stream") not in STREAM_NAMES or lifecycle.state(eid, lpath) in desk_acts.MOVED:
            continue
        got = desk_acts.engine_approve(eid, items, state, dry=DRY)
        title = str(item.get("title") or "")[:60]
        if got["outcome"] in ("applied", "would approve"):
            approved += 1
            log(f"approve {eid} {title}: {got['outcome']} by the engine" + (f", scheduled {got['date']}" if got["date"] else ""))
        elif got["outcome"].startswith("refused: ") and "review mode" not in got["outcome"]:
            # a stream on review is the normal case and not worth a line per draft
            log(f"wait {eid} {title}: {got['outcome'][len('refused: '):]}")
    return approved


# ------------------------------------------------------------------ post


def guardrail(channel: str) -> tuple[bool, str]:
    """May the brand send on this channel right now, by the registry."""
    try:
        row = memory.stream(STREAM)
        today, week, last = guardrails.counts_from_notes(row["name"], channel, NOW_DT)
        return guardrails.check(STREAM, channel, NOW_DT, today, week, last)
    except memory.SharedMemoryError as exc:
        return False, f"registry unreadable: {exc}"


def _scheduled_posts(items: dict, lpath: str) -> list:
    """`[(date, item, key, line)]`: each channel post of the brand's stream that is `scheduled` in the lifecycle."""
    work = []
    for pid, line in lifecycle.fold(lpath).items():
        if line["to"] != "scheduled" or line.get("stream") not in (None, STREAM, STREAM_NAME):
            continue
        eid, sep, key = pid.rpartition(":")
        if not sep or key not in NATIVE_DRIVERS:
            if pid not in items:
                log(f"skip scheduled post {pid}: no calendar note carries it")
            continue  # an item's own line: what goes out is its channel posts
        if eid not in items:
            log(f"skip scheduled post {pid}: no calendar note carries it")
            continue
        work.append((_day(line.get("date")), items[eid][0], key, line))
    return work


def step_post(ledger: dict, publish_log: dict, notes: dict | None = None) -> int:
    """Send what is due: the lifecycle's `scheduled` channel posts whose date has come within
    GRACE_DAYS, with the teaser's text from the note. Every send is channels.send()."""
    state = state_dir()
    lpath = _lifecycle_path(state)
    _sync(ledger)
    items = note_items(load_notes() if notes is None else notes)
    work = _scheduled_posts(items, lpath)
    drivers = write_drivers()
    posted, x_ok, allowed = 0, None, {}
    fields = {key: field for key, field, _platform in desk_acts.CHANNELS}
    for day, item, key, line in sorted(work, key=lambda w: ((w[0] or TODAY).isoformat(), w[3]["id"])):
        platform, title, post_id = channels.DISPLAY[key], str(item.get("title") or "")[:60], line["id"]
        if item.get("stream") not in STREAM_NAMES:
            continue
        why = due(day)
        if why == "future" or why == "no date":
            continue
        if why:
            log(f"stale {platform} {day} {title}: {why}")
            continue
        if platform not in allowed:
            allowed[platform] = guardrail(platform)
        ok, reason = allowed[platform]
        if not ok:
            log(f"refused {platform} {day} {title}: {reason}")
            continue
        text = str(item.get(fields[key]) or "").strip()
        problem = teaser_problem(platform, text)
        if problem:
            log(f"hold {platform} {day} {title}: {problem}; the post goes once the teaser is rewritten")
            continue
        if platform == "X" and drivers.get("x") is native_x_driver and not DRY:
            if x_ok is None:
                x_ok = x_ready()
            if not x_ok:
                log(f"blocked X {title}: no X login for app '{X_APP}' (xurl auth oauth2 --app {X_APP})")
                continue
        digest = channels.text_hash(key, text)
        sends = ledger.setdefault("sends", {})
        prior = sends.get(post_id) or next((v for v in sends.values() if v.get("hash") == digest), None)
        if prior and prior.get("state") == "sending":
            log(f"unsure {platform} {title}: an earlier send did not confirm; not re-sent, check the account by hand")
            continue
        if prior and prior.get("state") == "sent" and prior.get("page_id") != post_id:
            log(f"duplicate {platform} {title}: identical text already posted {prior.get('url')}")
            continue
        if prior and prior.get("state") == "sent":
            log(f"already sent {platform} {title} {prior.get('url') or ''}".rstrip())
            continue
        what = f"{platform} {day} {title} ({x_weighted_length(text) if platform == 'X' else len(text)} chars)"
        log(f"post {what}")
        ref = {"id": post_id, "title": title, "text_gate": True, "text_hash": digest, "cites": item.get("cites") or []}
        media = desk_acts.approved_media(post_id, state)
        if media:
            # the card or film a person approved with this post, by its hash; channels.send() hashes the file again
            ref["media"] = media
        try:
            result = do_send(platform, "post", text, ref, drivers)
        except channels.SendRefused as exc:
            log(f"refused {platform} {day} {title}: {exc.check}: {exc.reason}")
            continue
        except Exception as exc:  # one failed post must not stop the others
            log(f"failed {platform} {title}: {exc}")
            if platform == "LinkedIn":
                note_linkedin_social_failure(exc)
            _sync(ledger)
            continue
        _sync(ledger)
        url = result["url"]
        sent_now = ledger["sends"].get(post_id, {})
        if DRY:
            posted += 1
            continue
        link = article_link_for(item, state)
        if link:
            try:
                send_first_reply(platform, url if platform == "X" else sent_now.get("urn"), link, parent_id=post_id)
                _sync(ledger)
                log(f"first {'reply' if platform == 'X' else 'comment'} with the article link sent")
            except Exception as exc:
                note_linkedin_social_failure(exc)
                log(f"first reply with link failed ({exc}); step links will retry")
        publish_log.setdefault("entries", []).append({"target": key, "page_id": post_id, "title": title,
                                                      "url": url, "published_at": NOW, "approved_by": ACTOR, "stream": STREAM_NAME})
        save_json(PUBLISH_LOG, publish_log)
        posted += 1
        # the daily cap is re-read after each send so a second post on the same channel is judged on the new count
        allowed[platform] = guardrail(platform)
    return posted


def send_first_reply(platform: str, post_ref: str, link: str, parent_id: str | None = None) -> str:
    """The article link as a link-reply (channels.py's own kind): the fixed caption and the live
    article's URL, on our own sent post `parent_id`. Returns the reply's URL (a comment's URN on LinkedIn)."""
    key = platform.lower()
    text = f"{channels.LINK_CAPTIONS[key]} {link}"
    ref = {"parent_id": parent_id, "target": post_ref, "blog_row": {"status": "Published", "url": link}}
    result = do_send(platform, "link-reply", text, ref, write_drivers())
    return result.get("url") or result.get("urn") or ""


def step_links(ledger: dict, notes: dict | None = None) -> int:
    """Posts that went out before their article was live get the link once a person has
    marked it live: a first reply on X, a first comment on LinkedIn."""
    added = 0
    items = note_items(load_notes() if notes is None else notes)
    for key, send in list(ledger.get("sends", {}).items()):
        if send.get("state") != "sent" or send.get("kind") in ("reply", "comment", "link-reply") or send.get("link_reply"):
            continue
        page_id, platform, url = send.get("page_id"), send.get("platform"), send.get("url")
        if not page_id or platform not in LINK_CAPTIONS or not url:
            continue
        item = items.get(str(page_id).rpartition(":")[0], (None,))[0]
        link = article_link_for(item)
        if not link:
            continue
        title = str(item.get("title") or "")
        blocked = linkedin_social_blocked() if platform == "LinkedIn" else None
        if blocked:
            log(f"wait link comment on LinkedIn {title[:40]}: {blocked}")
            continue
        log(f"link reply on {platform} {title[:50]} -> {link}")
        if DRY:
            added += 1
            continue
        try:
            post_ref = url if platform == "X" else (send.get("urn") or urllib.parse.unquote(url.split("/feed/update/")[-1]))
            reply_url = send_first_reply(platform, post_ref, link, parent_id=key)
        except Exception as exc:
            note_linkedin_social_failure(exc)
            log(f"link reply failed on {platform}: {exc}")
            continue
        fresh = channels._load_ledger(state_dir())
        if (fresh["sends"].get(key) or {}).get("link_reply"):
            ledger.clear()
            ledger.update(fresh)  # channels.send() recorded the reply; its record is the truth
        else:
            send["link_reply"] = {"url": reply_url, "at": NOW, "link": link}
            save_json(LEDGER_FILE, ledger)
        added += 1
    return added


# ------------------------------------------------------------------ commit, status


def step_commit() -> bool:
    if DRY:
        return False
    paths = [os.path.relpath(p, REPO) for p in (SNAPSHOT_FILE, LEDGER_FILE, PUBLISH_LOG, MEMORY_DIGEST) if os.path.exists(p)]
    subprocess.run(["git", "-C", REPO, "add", "--", *paths], check=True, capture_output=True, text=True, timeout=60)
    staged = subprocess.run(["git", "-C", REPO, "diff", "--cached", "--name-only"], capture_output=True, text=True, timeout=60).stdout
    if not staged.strip():
        return False
    subprocess.run(["git", "-C", REPO, "-c", f"user.name={STREAM_NAME} engine autopilot", "-c", f"user.email=autopilot@{STREAM}.local",
                    "commit", "-q", "-m", "engine autopilot: calendar snapshot and sends"], check=True, capture_output=True, text=True, timeout=60)
    log("commit " + subprocess.run(["git", "-C", REPO, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip())
    return True


def status() -> dict:
    ledger = load_json(LEDGER_FILE, {"sends": {}}) or {"sends": {}}
    sends = [s for s in ledger.get("sends", {}).values() if s.get("state") == "sent"]
    snap = load_json(SNAPSHOT_FILE, {}) or {}
    ok_x, why_x = guardrail("X")
    ok_li, why_li = guardrail("LinkedIn")
    return {"sends": len(sends), "last_send": max((s.get("at", "") for s in sends), default=None),
            "snapshot_taken_at": snap.get("taken_at"), "snapshot_rows": len(snap.get("rows", [])),
            "may_send_now": {"X": ok_x or why_x, "LinkedIn": ok_li or why_li}, "dry": DRY}


# ------------------------------------------------------------------ main


def main() -> int:
    command = next((a for a in sys.argv[1:] if not a.startswith("-")), "status")
    if command not in ("snapshot", "approve", "post", "links", "run", "commit", "status"):
        print(__doc__)
        return 2
    if command == "status":
        print(json.dumps(status(), indent=2))
        return 0
    ledger = load_json(LEDGER_FILE, {"sends": {}}) or {"sends": {}}
    publish_log = load_json(PUBLISH_LOG, {"entries": []}) or {"entries": []}
    detail = []
    try:
        if command in ("snapshot", "run"):
            try:
                detail.append(f"snapshot {step_snapshot()} rows")
            except (OSError, ValueError) as exc:
                log(f"snapshot skipped, the notes could not be read: {str(exc)[:120]}")
                detail.append("snapshot skipped")
        if command in ("approve", "run"):
            n = step_approve()
            log(f"approved {n} draft(s) with no person in the loop")
            detail.append(f"approved {n}")
        if command in ("post", "run"):
            n = step_post(ledger, publish_log)
            log(f"posted {n} row(s)")
            detail.append(f"posted {n}")
        if command in ("links", "run"):
            n = step_links(ledger)
            log(f"link replies added {n}")
            detail.append(f"link replies {n}")
        if command == "commit":
            detail.append("committed" if step_commit() else "nothing to commit")
    finally:
        if not DRY and command != "snapshot":
            try:
                runlog.append("autopilot", "autopilot: " + ", ".join(detail), stream=STREAM_NAME, agent="autopilot", action=command)
            except Exception as exc:  # the log must never stop the sender
                log(f"runlog failed: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
