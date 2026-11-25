#!/usr/bin/env python3
"""
store.py - the storage interface behind the acts log (PLAN-surfaces, the drivers).

The interface is three calls:

  append_act(act, stream=None)   add one act; returns it as stored
  acts(since=None, status=None)  the acts, oldest first, each with its outcome
  mark(id, outcome)              record how an act ended

Only the `files` driver exists. `params.store.driver` names it; any other value
(`sqlite`, `postgres`) is refused until its driver is built. The files driver
keeps one append-only file, `state/acts.jsonl`, with two kinds of line:

  {"id", "at", "stream", "kind", "target", "payload", "base", "by"}   an act
  {"mark": <id>, "outcome": <text>, "at": <time>}                    its outcome

An act's outcome is the last mark for its id (none = pending). Nothing is ever
rewritten. A torn last line (a write cut short) is skipped on read and never
raised; a torn line anywhere else is also skipped, so one bad line cannot hide
the acts after it. Writes append one whole line under an exclusive lock.

`status` filters acts(): "pending" (no mark), "applied", "skipped", "refused",
or the exact outcome text.

This module checks only what storage needs (an id, a stream, a kind, no repeated
id, a known id on mark). What an act means is acts.py's business.
"""
import datetime as dt
import fcntl
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
sys.path.insert(0, HERE)

import config  # noqa: E402

ENGINE = os.path.dirname(HERE)
STATE = paths.state()
ACTS_FILE = "acts.jsonl"
DRIVERS = ("files",)


class StoreError(RuntimeError):
    """A store call that could not be honoured."""


def driver():
    name = config.cfg("store.driver", "files")
    if name not in DRIVERS:
        raise StoreError(f"store driver {name!r} is not built; available: {list(DRIVERS)}")
    return name


def acts_path(path=None):
    return path or os.path.join(STATE, ACTS_FILE)


def now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path):
    """(acts in file order, {id: last mark line}); unreadable lines skipped."""
    found, marks = [], {}
    if not os.path.exists(path):
        return found, marks
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            if "mark" in row:
                marks[row["mark"]] = row
            elif "id" in row:
                found.append(row)
    return found, marks


def _append(path, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
    with open(path, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            # a torn last line has no newline: start a fresh line so the new one parses
            size = f.seek(0, os.SEEK_END)
            if size:
                f.seek(size - 1)
                if f.read(1) != "\n":
                    data = "\n" + data
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _with_outcome(act, marks):
    out = dict(act)
    m = marks.get(act["id"])
    out["outcome"] = m["outcome"] if m else None
    return out


def append_act(act, stream=None, path=None):
    driver()
    if not isinstance(act, dict):
        raise StoreError("an act is a JSON object")
    row = dict(act)
    if stream is not None:
        row["stream"] = stream
    for key in ("id", "stream", "kind"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            raise StoreError(f"an act needs a non-empty {key}")
    if "mark" in row or "outcome" in row:
        raise StoreError("an act carries no mark or outcome; mark() records one")
    p = acts_path(path)
    existing, _ = _read(p)
    if any(a["id"] == row["id"] for a in existing):
        raise StoreError(f"act {row['id']!r} already exists")
    row.setdefault("at", now())
    _append(p, row)
    return row


def acts(since=None, status=None, path=None):
    driver()
    found, marks = _read(acts_path(path))
    out = []
    for a in found:
        if since is not None and str(a.get("at", "")) < str(since):
            continue
        a = _with_outcome(a, marks)
        if status is not None and not _status_matches(a["outcome"], status):
            continue
        out.append(a)
    return out


def _status_matches(outcome, status):
    if status == "pending":
        return outcome is None
    if outcome is None:
        return False
    return outcome == status or outcome.split(":", 1)[0] == status


def mark(id, outcome, path=None):
    driver()
    if not isinstance(outcome, str) or not outcome.strip():
        raise StoreError("an outcome is a non-empty string")
    p = acts_path(path)
    found, _ = _read(p)
    if not any(a["id"] == id for a in found):
        raise StoreError(f"no act {id!r}")
    row = {"mark": id, "outcome": outcome, "at": now()}
    _append(p, row)
    return row


if __name__ == "__main__":
    print(json.dumps(acts(), indent=2))
