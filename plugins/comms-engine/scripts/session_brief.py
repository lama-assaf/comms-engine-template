#!/usr/bin/env python3
"""
session_brief.py - what changed since the last session, printed into a new one.

Runs as the `SessionStart` hook of the comms-engine plugin (hooks/hooks.json),
in the instance the session opens. Stdout lands in the model's context, so
the brief is short and says where the full record is. Two things a person
would otherwise have to ask for every morning:

  monitoring   the latest listening pass (state/signals.json): window, summary,
               held slot, mentions, the warmest themes and what is held for a
               person; the live X stream's digest when the listener has run on
               this machine; the last rows of runs.json; one line from the
               engine console (scripts/engine.py): how many launchd jobs are
               stale or not loaded, so a silent job is seen the next morning.
  lessons      every `## YYYY-MM-DD — …` heading in .atelier/memory/lessons.md,
               every decisions/YYYY-MM-DD-*.md and every reviews.md heading
               that is new since the previous session on this clone.

"New since" is kept in `.claude/session-brief.json` (gitignored, per clone):
the headings and filenames already shown, and when. The first run on a clone
shows the last WINDOW_DAYS days. Reading only; the brief never edits memory or
state, and the marker is the only file it writes.

  engine session_brief            # as the hook: stdin JSON, marker updated
  engine session_brief --dry-run  # print, marker untouched
  engine session_brief --reset    # forget what was shown
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
REPO = paths.instance()
MEMORY = os.path.join(REPO, ".atelier", "memory")
STATE = paths.state()
MARKER = os.path.join(REPO, ".claude", "session-brief.json")
sys.path.insert(0, HERE)
import config  # noqa: E402

#: The brand's display name for the brief's title (engine.json brand.name).
BRAND_NAME = config.brand()["name"]

WINDOW_DAYS = 14
MAX_LESSONS = 6
SUMMARY_CHARS = 600

HEADING_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\b(.*)$")
DECISION_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-.+\.md$")


# ---------------------------------------------------------------- helpers

def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _age(iso, now):
    """'3 d' / '5 h' for an ISO timestamp, '' when it cannot be read."""
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return ""
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    secs = (now - t).total_seconds()
    if secs < 0:
        return "ahead of the clock"
    if secs < 3600 * 36:
        return f"{int(secs // 3600)} h ago"
    return f"{int(secs // 86400)} d ago"


def _clip(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


# ---------------------------------------------------------------- monitoring

def monitoring(state_dir, now):
    """Lines describing the latest listening pass and the X stream."""
    out = []
    sig = _json(os.path.join(state_dir, "signals.json"), None)
    if not sig:
        out.append("no listening pass on file (state/signals.json missing); run /listen-themes")
    else:
        win = sig.get("window") or {}
        to = win.get("to", "")
        out.append(
            f"listening pass {sig.get('run_id', '?')} ({sig.get('stream', '?')}), "
            f"window {win.get('from', '?')[:10]} to {to[:10]}, {_age(to, now) or 'age unknown'}"
        )
        if sig.get("summary"):
            out.append("summary: " + _clip(sig["summary"], SUMMARY_CHARS))
        held = sig.get("held_slot") or {}
        if held:
            out.append(
                "held slot: " + ("TRIGGERED" if held.get("triggered") else "not triggered")
                + (f" ({_clip(held.get('reason', ''), 160)})" if held.get("reason") else "")
            )
        if sig.get("mentions_note"):
            out.append("mentions: " + _clip(sig["mentions_note"], 220))
        per = sig.get("per_theme") or {}
        ranked = sorted(
            ((k, v) for k, v in per.items() if k.startswith("#")),
            key=lambda kv: (kv[1] or {}).get("relevance", 0),
            reverse=True,
        )
        if ranked:
            out.append(
                "warmest themes: "
                + "; ".join(f"{k} {v.get('relevance', 0):.1f} over {v.get('count', 0)}" for k, v in ranked[:3])
            )
        handed = sig.get("handed_on") or {}
        for key, items in handed.items():
            if "hold for review" in key and items:
                out.append(f"held for a person ({len(items)}): " + "; ".join(_clip(i, 70) for i in items[:4]))
    # live stream, only when the listener has run on this machine
    hb = _json(os.path.join(state_dir, "x-stream", "listener.json"), None)
    if hb:
        out.append(
            f"x stream listener: {hb.get('state', '?')}, last heartbeat {_age(hb.get('at', ''), now) or '?'}; "
            "digest: engine x_stream digest"
        )
    runs = _json(os.path.join(state_dir, "runs.json"), [])
    if isinstance(runs, list) and runs:
        last = runs[-1]
        out.append(
            f"last engine step: {last.get('step', '?')} {_age(last.get('at', ''), now) or ''} "
            f"({_clip(last.get('detail') or '', 110) or 'no detail'})"
        )
    return out



# ---------------------------------------------------------------- engine console

def engine_line(now):
    """One line from the console: how many jobs are stale or not loaded, and which.

    Reads engine.status_rows() (launchctl list and the state files, nothing
    spawned beyond that) and never raises: the console is context for the
    brief, and a brief that failed on it would cost the session more than the
    line is worth."""
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import engine
        rows = engine.status_rows(now)
        bad = engine.status_unhealthy({"jobs": rows})
    except Exception as e:  # engine.py missing, launchctl absent, a broken state file
        return f"engine console: unavailable ({type(e).__name__}: {e}); run engine.py status"
    if bad:
        return (f"engine console: {len(bad)} of {len(rows)} jobs stale or not loaded "
                f"({', '.join(bad)}); run engine.py status, then engine.py logs <job>")
    return f"engine console: {len(rows)} jobs, none stale or unloaded"

# ---------------------------------------------------------------- lessons

def lesson_entries(text):
    """(date, heading, first 'lesson:' sentence) for every dated ## heading."""
    entries = []
    cur = None
    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            cur = {"date": m.group(1), "heading": line[3:].strip(), "lesson": ""}
            entries.append(cur)
            continue
        if cur is not None and not cur["lesson"] and line.lower().startswith("lesson:"):
            cur["lesson"] = line.split(":", 1)[1].strip()
        elif cur is not None and cur["lesson"] and not cur.get("_closed"):
            if line.strip():
                cur["lesson"] += " " + line.strip()
            else:
                cur["_closed"] = True
    for e in entries:
        e.pop("_closed", None)
        e["lesson"] = _clip(e["lesson"], 240)
    return entries


def decision_files(decisions_dir):
    try:
        names = sorted(os.listdir(decisions_dir))
    except OSError:
        return []
    out = []
    for n in names:
        m = DECISION_RE.match(n)
        if not m:
            continue
        title = ""
        for line in _read(os.path.join(decisions_dir, n)).splitlines():
            if line.startswith("# "):
                title = re.sub(r"^decision:\s*", "", line[2:].strip())
                break
        out.append({"date": m.group(1), "file": n, "title": title})
    return out


def review_headings(text):
    return [{"date": m.group(1), "heading": line[3:].strip()} for line in text.splitlines() if (m := HEADING_RE.match(line))]


def new_since(memory_dir, seen, now):
    """(to show, to mark seen) for lessons, decisions and reviews.

    Not in `seen` means new. On the first run on a clone only the last
    WINDOW_DAYS are shown, but everything on file is marked seen, so an old
    entry is not "new" on the second run either.
    """
    floor = (now - dt.timedelta(days=WINDOW_DAYS)).date().isoformat()
    first_run = not seen
    everything = (
        lesson_entries(_read(os.path.join(memory_dir, "lessons.md"))),
        decision_files(os.path.join(memory_dir, "decisions")),
        review_headings(_read(os.path.join(memory_dir, "reviews.md"))),
    )
    keys = ("heading", "file", "heading")
    names = ("lessons", "decisions", "reviews")
    unseen = tuple(
        [e for e in items if e[key] not in seen.get(name, [])]
        for items, key, name in zip(everything, keys, names)
    )
    shown = tuple(
        [e for e in items if not first_run or e["date"] >= floor]
        for items in unseen
    )
    return shown, unseen


def lesson_lines(lessons, decisions, reviews):
    out = []
    shown = sorted(lessons, key=lambda e: e["date"], reverse=True)[:MAX_LESSONS]
    for e in shown:
        out.append(f"- {e['heading']}" + (f" — {e['lesson']}" if e["lesson"] else ""))
    if len(lessons) > len(shown):
        out.append(f"- …and {len(lessons) - len(shown)} more in lessons.md")
    for d in sorted(decisions, key=lambda d: d["date"], reverse=True):
        out.append(f"- decision {d['date']}: {d['title'] or d['file']} (decisions/{d['file']})")
    for r in sorted(reviews, key=lambda r: r["date"], reverse=True):
        out.append(f"- review {r['heading']} (reviews.md)")
    return out


# ---------------------------------------------------------------- marker

def story_lines(state_dir):
    """The latest story's cover line, the questions waiting for a person, the
    owner's rating of it, and the notes they asked the engine to always
    remember (the story's closing frame, state/story/feedback.json): so every
    session starts knowing them, not only the storyteller."""
    d = os.path.join(state_dir, "story")
    latest = _json(os.path.join(d, "latest.json"), {})
    if not latest:
        return []
    cover = (latest.get("slides") or [{}])[0]
    out = [f"latest story {latest.get('run_id')}: {_clip(cover.get('title', ''), 160)}"]
    waiting = [x for x in (_json(os.path.join(d, "questions.json"), {}).get("questions") or []) if x.get("status") == "open"]
    if waiting:
        out.append(f"questions waiting for a person ({len(waiting)}): "
                   + "; ".join(_clip(x.get("question", ""), 90) for x in waiting[:3]))
    feedback = _json(os.path.join(d, "feedback.json"), {}).get("feedback") or []
    mine = next((x for x in feedback if x.get("run_id") == latest.get("run_id")), None)
    if mine and mine.get("rating"):
        out.append(f"the owner rated it: {mine['rating']}")
    for n in sorted((x for x in feedback if x.get("remember")), key=lambda x: str(x.get("at") or ""), reverse=True)[:5]:
        out.append(f"always remember ({str(n.get('at', ''))[:10]}): {_clip(n['remember'], 200)}")
    return out


def load_marker(path):
    return _json(path, {})


def save_marker(path, seen, lessons, decisions, reviews, now):
    seen = dict(seen)
    seen["lessons"] = sorted(set(seen.get("lessons", [])) | {e["heading"] for e in lessons})
    seen["decisions"] = sorted(set(seen.get("decisions", [])) | {d["file"] for d in decisions})
    seen["reviews"] = sorted(set(seen.get("reviews", [])) | {r["heading"] for r in reviews})
    seen["last_session"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=1, ensure_ascii=False)
    os.replace(path + ".tmp", path)


# ---------------------------------------------------------------- brief

def brief(memory_dir=MEMORY, state_dir=STATE, marker_path=MARKER, now=None, write=True):
    now = now or dt.datetime.now(dt.timezone.utc)
    seen = load_marker(marker_path)
    (lessons, decisions, reviews), mark = new_since(memory_dir, seen, now)
    lines = [f"# {BRAND_NAME} comms: since the last session"]
    last = seen.get("last_session")
    lines.append(f"previous session on this clone: {last[:16].replace('T', ' ')}Z" if last else
                 f"first brief on this clone: showing the last {WINDOW_DAYS} days")
    lines.append("")
    lines.append("## social monitoring")
    lines += monitoring(state_dir, now)
    lines.append(engine_line(now))
    story = story_lines(state_dir)
    if story:
        lines.append("")
        lines.append("## the story, and what to remember")
        lines += story
    lines.append("")
    lines.append("## new lessons and decisions")
    body = lesson_lines(lessons, decisions, reviews)
    lines += body or ["nothing new since the last session"]
    lines.append("")
    lines.append("full record: state/signals.json · .atelier/memory/lessons.md · "
                 ".atelier/memory/decisions/ · status.md outranks everything above.")
    if write:
        save_marker(marker_path, seen, *mark, now)
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print without updating the marker")
    ap.add_argument("--reset", action="store_true", help="delete the marker so the next brief shows the window again")
    a = ap.parse_args(argv)
    if a.reset:
        try:
            os.remove(MARKER)
            print(f"marker removed: {MARKER}")
        except FileNotFoundError:
            print("no marker to remove")
        return 0
    # the hook passes JSON on stdin; nothing in it is needed, but drain it
    if not sys.stdin.isatty():
        try:
            sys.stdin.read()
        except OSError:
            pass
    try:
        print(brief(write=not a.dry_run))
    except Exception as e:  # a broken brief must never block a session
        print(f"session brief unavailable: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
