#!/usr/bin/env python3
"""
state_check.py - every record in `state/` names the stream it serves (plan v2, A3).

The engine serves several streams from one directory, so a record that does
not say which stream it belongs to cannot be read back per stream: the desk's
switcher, the scorer's baselines and the gate's memory choice all key on it.
This checks each state file and fails on the first record without the key or
with a value the registry does not list. `Both` is accepted and reported: it
is the calendar's value for an item that serves two streams, and the
single-pillar test says such an item is split before it is drafted further.

  engine state_check            # check, exit 1 on a failure
  engine state_check --stamp [NAME]   # one-off: add the key where it is missing (default the brand's name)

`--stamp` exists for records written before the key existed, all of them the
root stream's. It never changes a record that already carries a stream, and it logs
itself in `runs.json` as a `migrate` step so the desk shows it.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
STATE = paths.state()
sys.path.insert(0, HERE)
import memory  # noqa: E402

BOTH = "Both"


def _records(name, data):
    """Yield (where, record) for every record a state file holds."""
    if name == "queue.json":
        for i, item in enumerate(data or []):
            yield f"queue[{i}] {item.get('id', '?')}", item
    elif name == "signals.json":
        yield "signals (top level)", data or {}
        for i, f in enumerate((data or {}).get("findings", []) or []):
            yield f"signals.findings[{i}] {f.get('id', '?')}", f
    elif name in ("decisions.json", "edits.json", "arguments.json"):
        for k, v in (data or {}).items():
            yield f"{name[:-5]}[{k}]", v
    elif name == "runs.json":
        for i, r in enumerate(data or []):
            yield f"runs[{i}] {r.get('step', '?')} {r.get('run_id', '')}", r
    elif name == "engagement.json":
        yield "engagement (top level)", data or {}
        for key in ("proposals", "skipped"):
            for i, p in enumerate((data or {}).get(key, []) or []):
                yield f"engagement.{key}[{i}]", p
        ledger = (data or {}).get("ledger")
        if isinstance(ledger, list):
            for i, e in enumerate(ledger):
                if isinstance(e, dict):
                    yield f"engagement.ledger[{i}]", e
    elif name == "strategy.json":
        yield "strategy (top level)", data or {}
        for key in ("picks", "not_this_week"):
            for i, p in enumerate((data or {}).get(key, []) or []):
                if isinstance(p, dict):
                    yield f"strategy.{key}[{i}]", p


    elif name == "evidence.json":
        for i, s in enumerate((data or {}).get("sources", []) or []):
            yield f"evidence.sources[{i}]", s
    elif name == "reactions.json":
        yield "reactions (top level)", data or {}
        for i, c in enumerate((data or {}).get("candidates", []) or []):
            if isinstance(c, dict):
                yield f"reactions.candidates[{i}] {c.get('id', '?')}", c


FILES = ("queue.json", "signals.json", "decisions.json", "edits.json", "arguments.json",
         "runs.json", "engagement.json", "strategy.json", "reactions.json", "evidence.json")


def _load(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check(state=None, registry_path=None):
    """`(problems, split)`: records without a valid stream, and records at `Both`."""
    state = state or STATE
    names = {r["name"] for r in memory.load_streams(registry_path).values()}
    problems, split = [], []
    for name in FILES:
        data = _load(os.path.join(state, name))
        if data is None:
            continue
        for where, rec in _records(name, data):
            if not isinstance(rec, dict):
                continue
            s = str(rec.get("stream") or "").strip()
            if not s:
                problems.append(f"{name}: {where}: no stream")
            elif s == BOTH:
                split.append(f"{name}: {where}: Both (needs split)")
            elif s not in names:
                problems.append(f"{name}: {where}: stream {s!r} is not in the registry {sorted(names)}")
    return problems, split


def stamp(stream_name, state=None, registry_path=None):
    """Add `stream` to every record that lacks it. Returns the count stamped."""
    state = state or STATE
    names = {r["name"] for r in memory.load_streams(registry_path).values()}
    if stream_name not in names:
        raise memory.SharedMemoryError(f"{stream_name!r} is not a stream name in the registry {sorted(names)}")
    stamped = 0
    for name in FILES:
        path = os.path.join(state, name)
        data = _load(path)
        if data is None:
            continue
        n = 0
        for _, rec in _records(name, data):
            if isinstance(rec, dict) and not str(rec.get("stream") or "").strip():
                rec["stream"] = stream_name
                n += 1
        if n:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, path)
        stamped += n
    return stamped


def main(argv=None):
    ap = argparse.ArgumentParser(description="every state record names its stream")
    ap.add_argument("--state", default=STATE, help="the state directory (default state/)")
    ap.add_argument("--stamp", metavar="NAME", nargs="?", const=memory.DEFAULT_STREAM_NAME,
                    help="add `stream: NAME` to records that lack it (default the brand's name), then check")
    a = ap.parse_args(argv)
    try:
        if a.stamp:
            n = stamp(a.stamp, a.state)
            print(f"stamped {n} record(s) with stream {a.stamp}")
            if n:
                import runlog
                runlog.append("migrate", f"state_check: stamped {n} record(s) written before the stream key existed",
                              stream=a.stamp, runs_path=os.path.join(a.state, "runs.json"))
        problems, split = check(a.state)
    except memory.SharedMemoryError as e:
        print(f"state_check: {e}", file=sys.stderr)
        return 2
    for line in split:
        print(f"needs split  {line}")
    for line in problems:
        print(f"FAIL  {line}")
    if problems:
        print(f"state_check: {len(problems)} record(s) without a valid stream")
        return 1
    print(f"state_check: ok ({len(split)} at Both)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
