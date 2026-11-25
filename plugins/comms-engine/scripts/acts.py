#!/usr/bin/env python3
"""
acts.py - the log of what a person did (PLAN-surfaces, the core).

One shape: {id, at, stream, kind, target, payload, base, by}. `by` is a role,
never a name. Each act ends with one outcome: `applied`, `skipped: moved` or
`refused: <reason>`. Storage is store.py's; this module checks the shape and the
vocabulary on top of it and holds no state of its own.

  record(kind, stream, target, payload, base, by)   append a pending act
  list_acts(since, status)                          the acts with their outcomes
  applied(id) / skipped(id) / refused(id, reason)   end an act
"""
import json
import os
import re
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import store  # noqa: E402

KINDS = (
    "decision", "edit", "review", "argument_line", "answer", "slide_response",
    "story_feedback", "watch", "unwatch", "dismiss", "terms", "theme", "grade", "switch", "blog-live",
    "schedule", "new-post",
    # the review switch's companions: stop every send of a stream, take a sent post down, change the setup
    "pause", "takedown", "setup",
)
ROLE = re.compile(r"^[a-z][a-z0-9_-]*$")


class ActError(store.StoreError):
    """An act that does not have the shape, or an outcome outside the vocabulary."""


def check_outcome(outcome):
    if outcome in ("applied", "skipped: moved"):
        return outcome
    if isinstance(outcome, str) and outcome.startswith("refused: ") and outcome[len("refused: "):].strip():
        return outcome
    raise ActError(f"outcome {outcome!r} is not applied, 'skipped: moved' or 'refused: <reason>'")


def record(kind, stream, target, payload=None, base=None, by="alpha", id=None, at=None, path=None):
    if kind not in KINDS:
        raise ActError(f"unknown kind {kind!r}; known: {list(KINDS)}")
    if not isinstance(by, str) or not ROLE.match(by):
        raise ActError(f"`by` is a role (lower-case, no name or address), got {by!r}")
    act = {
        "id": id or uuid.uuid4().hex[:12],
        "stream": stream,
        "kind": kind,
        "target": target,
        "payload": {} if payload is None else payload,
        "base": base,
        "by": by,
    }
    if at:
        act["at"] = at
    return store.append_act(act, path=path)


def list_acts(since=None, status=None, path=None):
    return store.acts(since=since, status=status, path=path)


def applied(id, path=None):
    return store.mark(id, check_outcome("applied"), path=path)


def skipped(id, path=None):
    return store.mark(id, check_outcome("skipped: moved"), path=path)


def refused(id, reason, path=None):
    return store.mark(id, check_outcome(f"refused: {reason}"), path=path)


if __name__ == "__main__":
    print(json.dumps(list_acts(status="pending"), indent=2))
