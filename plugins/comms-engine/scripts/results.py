#!/usr/bin/env python3
"""
results.py - what each scheduled job produced since a moment, in one digest.

Why: the console (engine.py status) says what ran and whether it is stale; the
outputs sit in eight places (the queue notes, signals.json, engagement.json,
metrics.json, claims-review.json, the corpus and autopilot logs, the run log).
Nothing answered "what did the engine produce since I last looked". This module
does, from those files only, and two faces show it: the console
(`engine.py results`) and /engine in chat. The dashboard page does not: since
2026-11-06 it carries the posts and what is live, and no run or job. It reads;
it never writes.

  engine results                 # since the brief marker's last_session, else 48 h
  engine results --since 7d      # or 36h, or an ISO timestamp
  engine results --json

Each line names the job, says what came out, and points at the file or the
command that acts on it. Counts and shapes only: no person's handle is read
from any record (rule 6 of the loop), and the inventory's private companion is
never opened.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
REPO = paths.instance()
STATE = paths.state()
MARKER = os.path.join(REPO, ".claude", "session-brief.json")
ENGINE_JSON = os.path.join(ENGINE, "engine.json")
DEFAULT_WINDOW = dt.timedelta(hours=48)

sys.path.insert(0, HERE)
try:
    import config  # the brand's timezone (params.autopilot.timezone) and job labels
except Exception:  # pragma: no cover - a copy without config.py still digests
    config = None


def _local_tz():
    """The zone the jobs' logs are stamped in: params.autopilot.timezone, else the machine's."""
    try:
        from zoneinfo import ZoneInfo
        name = str(config.cfg("autopilot.timezone", "") or "") if config else ""
        return ZoneInfo(name) if name else dt.datetime.now().astimezone().tzinfo
    except Exception:
        return dt.datetime.now().astimezone().tzinfo


LOCAL = _local_tz()

#: Which run-log steps belong to which job (short name). The cycle job is the
#: whole /social-cycle; its steps are listed so a partial run still shows.
STEPS = {
    "cycle": ("listen", "assess", "strategy", "draft", "gate", "distribute", "edits", "inventory", "dashboard"),
    "engagement": ("engage",),
    "score": ("score",),
    "claims-check": ("claims-check",),
    "autopilot": ("autopilot",),
    "corpus": ("corpus",),
}
ORDER = ("corpus", "cycle", "autopilot", "engagement", "score", "claims-check", "x-stream")


# ---------------------------------------------------------------- time

def parse_ts(s, assume=LOCAL):
    """ISO timestamp, with or without zone (`2026-11-05T20:13:14` is local)."""
    if not s:
        return None
    s = str(s).strip()
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})", s)
        if not m:
            return None
        t = dt.datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:{m.group(3)}")
    if t.tzinfo is None:
        t = t.replace(tzinfo=assume)
    return t.astimezone(dt.timezone.utc)


def since_from(arg, now, marker_path=MARKER):
    """`--since` as a timedelta (`36h`, `7d`), an ISO stamp, or None: the brief
    marker's time when it has one, else 48 hours ago."""
    if arg:
        m = re.fullmatch(r"(\d+)([hd])", arg)
        if m:
            n, unit = int(m.group(1)), m.group(2)
            return now - (dt.timedelta(hours=n) if unit == "h" else dt.timedelta(days=n))
        t = parse_ts(arg)
        if t:
            return t
        raise ValueError(f"--since takes 36h, 7d or an ISO timestamp, not {arg!r}")
    try:
        with open(marker_path, encoding="utf-8") as f:
            mk = json.load(f)
        t = parse_ts(mk.get("last_session") or mk.get("at") or mk.get("saved_at"))
        if t and t < now:
            return t
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return now - DEFAULT_WINDOW


def _load(state_dir, name, default):
    p = os.path.join(state_dir, name)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _clip(s, n=140):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _line(text, where=None):
    return {"text": text, "where": where or ""}


# ---------------------------------------------------------------- per job

def _runs_since(runs, steps, since):
    out = []
    for r in runs if isinstance(runs, list) else []:
        if r.get("step") in steps:
            t = parse_ts(r.get("at"))
            if t and t >= since:
                out.append((t, r))
    return sorted(out, key=lambda x: x[0])


def cycle_lines(items, runs, signals, since):
    lines = []
    new = [i for i in items if (parse_ts(i.get("drafted_at")) or dt.datetime.min.replace(tzinfo=dt.timezone.utc)) >= since]
    if new:
        by_verdict = {}
        for i in new:
            by_verdict.setdefault((i.get("gate") or {}).get("verdict") or "ungated", []).append(i)
        parts = "; ".join(f"{len(v)} {k}" for k, v in sorted(by_verdict.items()))
        lines.append(_line(f"{len(new)} draft{'s' if len(new) != 1 else ''} written or rewritten ({parts})", "/alpha-queue"))
        for i in sorted(new, key=lambda x: (x.get("slot") or {}).get("date", ""))[:6]:
            lines.append(_line(
                f"{i.get('id')} · {(i.get('slot') or {}).get('date', '?')} {i.get('theme') or ''} · "
                f"gate {(i.get('gate') or {}).get('verdict') or 'none'} · Alpha {i.get('alpha_status') or 'proposed'}",
                f"Content/Calendar/{i.get('title', '')}.md" if i.get("title") else ""))
    sig_to = parse_ts(((signals or {}).get("window") or {}).get("to") or (signals or {}).get("run_at"))
    if signals and sig_to and sig_to >= since:
        per = signals.get("per_theme") or {}
        ranked = sorted(((k, v) for k, v in per.items() if str(k).startswith("#")),
                        key=lambda kv: (kv[1] or {}).get("relevance", 0), reverse=True)[:3]
        warm = "; ".join(f"{k} {v.get('relevance', 0):.1f}" for k, v in ranked)
        held = sum(len(v) for k, v in (signals.get("handed_on") or {}).items() if "hold" in k)
        lines.append(_line(
            f"listening pass {signals.get('run_id', '?')}: {len(signals.get('findings') or [])} findings"
            + (f", warmest {warm}" if warm else "") + (f", {held} held for a person" if held else ""),
            "state/signals.json; the session brief"))
    for t, r in _runs_since(runs, ("distribute", "edits"), since):
        if r.get("item"):
            lines.append(_line(f"{r['step']}: {r['item']} → {', '.join(r.get('published_to') or []) or 'nothing published'}", "state/runs.json"))
        elif r.get("detail"):
            lines.append(_line(f"{r['step']}: {_clip(r['detail'])}", "state/runs.json"))
    gates = _runs_since(runs, ("gate",), since)
    if gates and not new:
        lines.append(_line(f"gate: {_clip(gates[-1][1].get('detail'))}", "state/runs.json"))
    return lines


def engagement_lines(eng, runs, since):
    lines = []
    passed = parse_ts((eng or {}).get("pass_at"))
    if eng and passed and passed >= since:
        props = eng.get("proposals") or []
        shapes = {}
        for p in props:
            shapes[f"{p.get('platform', '?')} · {p.get('theme', '')} · {p.get('shape', '')}".strip(" ·")] = shapes.get(p.get("platform"), 0) + 1
        lines.append(_line(f"{len(props)} comment draft{'s' if len(props) != 1 else ''} waiting for Alpha, "
                           f"{len(eng.get('skipped') or [])} skipped" + (": " + "; ".join(list(shapes)[:4]) if shapes else ""),
                           "state/engagement.json; the page's Replies to place"))
        inbound = eng.get("inbound") or {}
        if isinstance(inbound, dict) and inbound:
            n = inbound.get("posts_in_last_three_days")
            lines.append(_line("inbound: " + (f"{n} own post{'s' if n != 1 else ''} in the three-day window" if n is not None
                                            else _clip(inbound.get("summary") or "see engagement.json", 120)), "state/engagement.json"))
    for t, r in _runs_since(runs, ("engage",), since):
        if not lines:
            lines.append(_line(f"engage: {_clip(r.get('detail'))}", "state/runs.json"))
    return lines


def score_lines(metrics, runs, since):
    lines = []
    computed = parse_ts((metrics or {}).get("computed_at"))
    if metrics and computed and computed >= since:
        rows = metrics.get("rows") or []
        status = {}
        for r in rows:
            status[r.get("status") or "?"] = status.get(r.get("status") or "?", 0) + 1
        lines.append(_line(f"scorecard recomputed: {len(rows)} rows (" + ", ".join(f"{v} {k}" for k, v in sorted(status.items())) + ")",
                           "engine metrics --dry-run"))
    for t, r in _runs_since(runs, ("score",), since)[-1:]:
        lines.append(_line(f"score: {_clip(r.get('detail'))}", "state/runs.json"))
    return lines


def claims_lines(review, runs, since):
    lines = []
    checked = parse_ts((review or {}).get("checked_at"))
    if review and checked and checked >= since:
        n = len(review.get("items") or [])
        lines.append(_line(f"claims check: {n} note{'s' if n != 1 else ''} whose cited claim moved" + (", for a person" if n else ""),
                           "state/claims-review.json"))
    for t, r in _runs_since(runs, ("claims-check",), since)[-1:]:
        lines.append(_line(f"claims-check: {_clip(r.get('detail'))}", "state/runs.json"))
    return lines


def corpus_lines(log_text, since, repo=REPO):
    lines = []
    stamped = []
    for ln in (log_text or "").splitlines():
        m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})\s+(.*)", ln)
        if m:
            t = parse_ts(m.group(1))
            if t and t >= since:
                stamped.append((t, m.group(2)))
    runs_found = [s for t, s in stamped if "pending work found" in s]
    exits = [s for t, s in stamped if "/corpus-cycle exit" in s]
    quiet = [s for t, s in stamped if "nothing pending" in s]
    if runs_found or exits:
        lines.append(_line(f"{len(runs_found)} Claude run{'s' if len(runs_found) != 1 else ''} on the corpus"
                           + (f", last {exits[-1]}" if exits else ""), "state/corpus-cycle.last.md"))
    elif quiet:
        lines.append(_line(f"{len(quiet)} sweep{'s' if len(quiet) != 1 else ''}, nothing pending; no Claude run", "state/corpus-cycle.log"))
    try:
        out = subprocess.run(["git", "-C", repo, "log", f"--since={since.isoformat()}", "--format=%h %s", "--", ".atelier/memory"],
                             capture_output=True, text=True, timeout=10)
        commits = [l for l in out.stdout.splitlines() if l.strip()]
        if commits:
            lines.append(_line(f"{len(commits)} memory commit{'s' if len(commits) != 1 else ''}: " + "; ".join(_clip(c, 70) for c in commits[:3]),
                               "git log -- .atelier/memory"))
        dirty = subprocess.run(["git", "-C", repo, "diff", "--stat", "--", ".atelier/memory"], capture_output=True, text=True, timeout=10)
        tail = [l for l in dirty.stdout.splitlines() if l.strip()]
        if tail:
            lines.append(_line("uncommitted memory edits: " + _clip(tail[-1], 90), "git diff .atelier/memory"))
    except (OSError, subprocess.SubprocessError):
        pass
    return lines


def autopilot_lines(log_text, ledger, since):
    lines = []
    posted = refused = stale = replies = 0
    seen_runs = 0
    for ln in (log_text or "").splitlines():
        m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?)\s+(.*)", ln)
        if not m:
            continue
        t = parse_ts(m.group(1))
        if not t or t < since:
            continue
        body = m.group(2)
        if body.startswith("posted "):
            seen_runs += 1
            try:
                posted += int(body.split()[1])
            except (IndexError, ValueError):
                pass
        elif body.startswith("stale "):
            stale += 1
        elif "refus" in body or "quiet hours" in body:
            refused += 1
        elif body.startswith("link replies added"):
            try:
                replies += int(body.split()[-1])
            except ValueError:
                pass
    raw = (ledger or {}).get("sends") or []
    recs = list(raw.values()) if isinstance(raw, dict) else raw
    floor = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    sends = [r for r in recs if isinstance(r, dict) and (parse_ts(r.get("at") or r.get("sent_at")) or floor) >= since]
    if seen_runs or refused or sends:
        lines.append(_line(
            f"{seen_runs} run{'s' if seen_runs != 1 else ''}: posted {posted or len(sends)}, link replies {replies}"
            + (f", {refused} refused by guardrails" if refused else "") + (f", {stale} stale row{'s' if stale != 1 else ''} not posted" if stale else ""),
            "state/autopilot.log; engine autopilot status"))
    return lines


def xstream_lines(state_dir, since):
    hb = _load(os.path.join(state_dir, "x-stream"), "listener.json", None)
    if not hb:
        return []
    t = parse_ts(hb.get("at"))
    if not t or t < since:
        return []
    return [_line(f"stream listener {hb.get('state', '?')}, last heartbeat {t.isoformat(timespec='minutes')}",
                  "engine x_stream digest")]


# ---------------------------------------------------------------- schedule

def next_fire(calendar, now, tz=None):
    """The next launchd StartCalendarInterval fire, local time, as UTC; None for a job with no calendar."""
    if not calendar:
        return None
    entries = calendar if isinstance(calendar, list) else [calendar]
    local_now = now.astimezone(tz or LOCAL)
    best = None
    for e in entries:
        hour, minute = int(e.get("Hour", 0)), int(e.get("Minute", 0))
        wd = e.get("Weekday")
        for d in range(0, 8):
            cand = (local_now + dt.timedelta(days=d)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            if wd is not None and cand.isoweekday() % 7 != int(wd) % 7:
                continue
            if cand <= local_now:
                continue
            if best is None or cand < best:
                best = cand
            break
    return best.astimezone(dt.timezone.utc) if best else None


def _label(j):
    if j.get("label"):
        return j["label"]
    try:
        return config.label(j["name"])
    except Exception:
        return "com.acme." + str(j.get("name", "?"))


def schedule(jobs, now, tz=None):
    """[{label, what, next, keep_alive}] from engine.json's jobs (labels derived from the brand)."""
    out = []
    for j in jobs:
        nxt = next_fire(j.get("calendar"), now, tz)
        out.append({"label": _label(j), "what": j.get("what", ""), "next": nxt.isoformat(timespec="minutes") if nxt else None,
                    "keep_alive": bool(j.get("keep_alive")), "optional": bool(j.get("optional"))})
    return out


# ---------------------------------------------------------------- digest

def digest(since=None, now=None, state_dir=STATE, items=None, repo=REPO, marker_path=MARKER, engine_json=ENGINE_JSON):
    now = now or dt.datetime.now(dt.timezone.utc)
    since = since or since_from(None, now, marker_path)
    runs = _load(state_dir, "runs.json", [])
    if isinstance(runs, dict):
        runs = runs.get("runs", [])
    if items is None:
        try:
            if HERE not in sys.path:
                sys.path.insert(0, HERE)
            import repo as repo_mod
            items = repo_mod.load_items()
        except Exception:
            items = []
    def text(name):
        p = os.path.join(state_dir, name)
        try:
            with open(p, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return ""
    per = {
        "corpus": corpus_lines(text("corpus-cycle.log"), since, repo),
        "cycle": cycle_lines(items, runs, _load(state_dir, "signals.json", None), since),
        "autopilot": autopilot_lines(text("autopilot.log"), _load(state_dir, "send-ledger.json", {}), since),
        "engagement": engagement_lines(_load(state_dir, "engagement.json", None), runs, since),
        "score": score_lines(_load(state_dir, "metrics.json", None), runs, since),
        "claims-check": claims_lines(_load(state_dir, "claims-review.json", None), runs, since),
        "x-stream": xstream_lines(state_dir, since),
    }
    try:
        with open(engine_json, encoding="utf-8") as f:
            spec = json.load(f)
        jobs = spec.get("jobs", [])
    except (OSError, json.JSONDecodeError):
        jobs = []
    labels = {}
    for j in jobs:
        lab = _label(j)
        short = lab.rsplit(".", 1)[-1]
        labels[{"corpus-cycle": "corpus", "social-engine": "cycle"}.get(short, short)] = lab
    return {
        "since": since.isoformat(timespec="minutes"),
        "now": now.isoformat(timespec="minutes"),
        "jobs": [{"short": s, "label": labels.get(s, ""), "lines": per.get(s, [])} for s in ORDER],
        "schedule": schedule(jobs, now),
    }


def lines(d):
    out = [f"results since {d['since']} (now {d['now']})"]
    nxt = {s["label"]: s["next"] for s in d.get("schedule", [])}
    for j in d["jobs"]:
        if not j["lines"]:
            continue
        head = j["short"] + (f"  next {nxt[j['label']][11:16]} UTC {nxt[j['label']][:10]}" if nxt.get(j["label"]) else "")
        out.append(head)
        for l in j["lines"]:
            out.append("  - " + l["text"] + (f"  [{l['where']}]" if l["where"] else ""))
    if len(out) == 1:
        out.append("nothing produced in the window; engine.py status says what ran")
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    now = dt.datetime.now(dt.timezone.utc)
    since_arg = argv[argv.index("--since") + 1] if "--since" in argv and argv.index("--since") + 1 < len(argv) else None
    try:
        since = since_from(since_arg, now)
    except ValueError as e:
        print(f"results: {e}", file=sys.stderr)
        return 2
    d = digest(since=since, now=now)
    if "--json" in argv:
        print(json.dumps(d, indent=1, ensure_ascii=False))
    else:
        print("\n".join(lines(d)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
