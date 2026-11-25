#!/usr/bin/env python3
"""
jobs_status.py - what runs, and when it last did.

One table, read from the files the jobs write and from launchd: each scheduled
job's label, whether launchd has it loaded, when it last ran, and whether that
is older than its schedule allows. The job list and each job's one-line `what`
are engine.json's `jobs`; the staleness rule and where each job leaves its
trace are kept here, per job name (the label is the brand's prefix plus that
name, derived by config.py), because they describe what the scripts write, not
what launchd runs. Reads only; nothing is called. engine.py status builds on
rows(), handing it the loaded labels from its own launchctl seam.

  engine jobs_status
  engine jobs_status --json
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
STATE = paths.state()
REPO = paths.instance()
ENGINE_JSON = os.path.join(ENGINE, "engine.json")
sys.path.insert(0, HERE)
import config  # noqa: E402

# per job name: stale after (hours), how the last run is found. A job in
# engine.json with no row here is listed as never stale ("none").
HOW = {
    "social-engine": (30, ("runs", ("assess", "draft", "gate", "distribute"))),
    "engagement": (30, ("runs", ("engage",))),
    "score": (26, ("runs", ("score", "metrics", "tests"))),
    "claims-check": (26, ("runs", ("claims-check", "claims_check"))),
    "corpus-cycle": (30, ("log", os.path.join(STATE, "corpus-cycle.log"))),
    "autopilot": (8, ("autopilot",)),
    "x-stream": (1, ("xstream",)),
    "nosleep": (None, ("none",)),
}
WHAT_WIDTH = 72


def one_line(what):
    """engine.json's `what` cut to its first clause, so the table stays one line per job."""
    return re.split(r"[;(]", what or "")[0].strip()[:WHAT_WIDTH]


def jobs(path=None):
    """(label, what, stale_h, how) per job of engine.json, in file order.

    The file is config.py's current ENGINE_JSON unless given, resolved when
    called, so a redirected config.py (the test fixture) is followed."""
    out = []
    for j in config.jobs(path or config.ENGINE_JSON):
        stale_h, how = HOW.get(j["name"], (None, ("none",)))
        out.append((j["label"], one_line(j.get("what", "")), stale_h, how))
    return out


def loaded_labels():
    """The labels under the brand's prefix that launchctl has loaded."""
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return set()
    prefix = config.brand()["label_prefix"] + "."
    return {line.split()[-1] for line in out.splitlines() if line.split() and line.split()[-1].startswith(prefix)}


def _parse(ts):
    try:
        t = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def last_run_entry(steps):
    path = os.path.join(STATE, "runs.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    times = [_parse(r.get("at") or r.get("ts")) for r in rows if r.get("step") in steps]
    times = [t for t in times if t]
    return max(times) if times else None


def last_log_line(path):
    if not os.path.exists(path):
        return None
    last = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:\d{2})?", line)
            if m:
                last = m.group(0)
    return _parse(last) if last else None


def last_autopilot():
    return last_log_line(os.path.join(STATE, "autopilot.log"))


def last_xstream():
    d = os.path.join(STATE, "x-stream")
    if not os.path.isdir(d):
        return None
    files = sorted(f for f in os.listdir(d) if f.endswith(".jsonl"))
    if not files:
        return None
    return dt.datetime.fromtimestamp(os.path.getmtime(os.path.join(d, files[-1])), dt.timezone.utc)


def rows(now=None, loaded=None):
    """One dict per job; `loaded` is the set of loaded labels when the caller
    already read launchctl (engine.py does), else it is read here."""
    now = now or dt.datetime.now(dt.timezone.utc)
    loaded = loaded_labels() if loaded is None else set(loaded)
    out = []
    for label, what, stale_h, how in jobs():
        kind = how[0]
        last = None
        if kind == "runs":
            last = last_run_entry(how[1])
        elif kind == "log":
            last = last_log_line(how[1])
        elif kind == "autopilot":
            last = last_autopilot()
        elif kind == "xstream":
            last = last_xstream()
        age_h = (now - last).total_seconds() / 3600 if last else None
        if stale_h is None:
            state = "loaded" if label in loaded else "not loaded"
        elif label not in loaded:
            state = "not loaded"
        elif last is None:
            state = "loaded, never ran"
        elif age_h > stale_h:
            state = f"stale ({age_h / 24:.1f} d)"
        else:
            state = "ok"
        out.append({"job": label, "what": what, "loaded": label in loaded,
                    "last_run": last.isoformat(timespec="minutes") if last else None, "state": state})
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    data = rows()
    if "--json" in argv:
        print(json.dumps(data, indent=2))
        return 0
    w = max(len(r["job"]) for r in data)
    print(f"{'job':<{w}}  {'last run':<17}  {'state':<22}  what")
    for r in data:
        print(f"{r['job']:<{w}}  {(r['last_run'] or '-'):<17}  {r['state']:<22}  {r['what']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
