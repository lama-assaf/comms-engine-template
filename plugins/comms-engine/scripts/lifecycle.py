#!/usr/bin/env python3
"""
lifecycle.py - one post's state, held in an append-only log (PLAN-workflows, step 2).

The only writer of `state/lifecycle.jsonl`. One line per move:

  {"id", "from", "to", "at", "stream", "allowed_by": {...}, ...detail}

`id` is an engine id, or a reply's proposal id. A post's current state is the fold
of its lines (the `to` of the last one); no line means `draft`. The calendar note
carries no lifecycle key. A torn last line (a write cut short) is skipped on read,
and the next append starts a fresh line; any other unreadable line is skipped too.

States and moves (each move checks what it needs and raises LifecycleError if not):

  draft -> gated        gate(id, text_hash, verdict_hash)    a gate verdict that is not block (GATE_OK) for this text
  gated -> decided      decide(id, act_id)                   an applied desk/dashboard approve act
                                                             for this id (and this text, if the act names it)
  decided -> scheduled  schedule(id, date, guard)            guard() = (ok, reason), e.g. guardrails.check
  scheduled -> scheduled reschedule(id, date, guard)       a date change before the send; guard() as above
  scheduled -> sent     sent(id, ledger_row)                 a ledger row written first, for this id
  sent -> scored        scored(id, ledger_row)               published_at is the ledger's sent time
  any live -> blocked   block(id, reason)                    blocked -> gated again via gate()
  any live -> retired   retire(id, reason)                   final

`allowed_by` records what allowed the move: the gate verdict hash, the decision act
id, the guard result, the ledger row. A text that changes after the gate is a new
text hash: gate() again, and the old decision no longer covers it.
"""
import datetime as dt
import fcntl
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
sys.path.insert(0, HERE)

import store  # noqa: E402

ENGINE = os.path.dirname(HERE)
STATE = paths.state()
LOG_FILE = "lifecycle.jsonl"

STATES = ("draft", "gated", "decided", "scheduled", "sent", "scored", "blocked", "retired")
LIVE = ("draft", "gated", "decided", "scheduled", "sent", "blocked")
FLOW = {  # the one forward move out of each state
    "draft": "gated", "gated": "decided", "decided": "scheduled",
    "scheduled": "sent", "sent": "scored",
}


#: The gate verdicts that let a post on: the one rule desk_acts, the dashboard's approve and
#: channels.send() share. `block` refuses; `pass-with-edits` is allowed (its fixes are on the note).
GATE_OK = ("pass", "pass-with-edits")


class LifecycleError(RuntimeError):
    """A move the lifecycle refuses."""


def gate_refusal(verdict):
    """None when a gate verdict lets a post on, else the reason in one line."""
    if verdict in GATE_OK:
        return None
    return f"the gate verdict is {verdict or 'missing'}, not pass or pass-with-edits"


def log_path(path=None):
    return path or os.path.join(STATE, LOG_FILE)


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("id") and row.get("to") in STATES:
                rows.append(row)
    return rows


def _append(path, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
    with open(path, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
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


def fold(path=None):
    """{id: the last line for that id}; the current state of every post."""
    out = {}
    for row in _read(log_path(path)):
        out[row["id"]] = row
    return out


def lines(id, path=None):
    return [r for r in _read(log_path(path)) if r["id"] == id]


def state(id, path=None):
    row = fold(path).get(id)
    return row["to"] if row else "draft"


def current(id, path=None):
    """The last line for `id`, or None for a post still at draft."""
    return fold(path).get(id)


def _need(cond, msg):
    if not cond:
        raise LifecycleError(msg)


def _text(value, what):
    _need(isinstance(value, str) and value.strip(), f"{what} is required")
    return value


def _move(id, to, allowed_by, stream=None, path=None, **detail):
    _text(id, "id")
    frm = state(id, path)
    row = {"id": id, "from": frm, "to": to, "at": _now(), "allowed_by": allowed_by}
    prev = current(id, path)
    stream = stream or (prev or {}).get("stream")
    if stream:
        row["stream"] = stream
    row.update(detail)
    _append(log_path(path), row)
    return row


def _expect(id, frm, to, path):
    cur = state(id, path)
    _need(cur == frm, f"{id}: cannot move to {to} from {cur}; {to} follows {frm}")


def gate(id, text_hash, verdict_hash, verdict="pass", stream=None, path=None):
    """draft (or blocked) -> gated, on a passing gate verdict for this text."""
    cur = state(id, path)
    _need(cur in ("draft", "blocked"), f"{id}: cannot move to gated from {cur}; gated follows draft")
    _text(text_hash, "text_hash")
    _text(verdict_hash, "verdict_hash")
    _need(verdict in GATE_OK, f"{id}: the gate verdict is {verdict!r}, not pass or pass-with-edits")
    return _move(id, "gated", {"gate_verdict": verdict_hash}, stream=stream, path=path, text_hash=text_hash)


def decide(id, act_id, acts_path=None, stream=None, path=None):
    """gated -> decided, on an applied approve act for this post (and this text)."""
    _expect(id, "gated", "decided", path)
    _text(act_id, "act_id")
    found = [a for a in store.acts(path=acts_path) if a["id"] == act_id]
    _need(found, f"{id}: no act {act_id!r}")
    act = found[0]
    _need(act.get("kind") == "decision", f"{id}: act {act_id} is a {act.get('kind')}, not a decision")
    _need(act.get("target") == id, f"{id}: act {act_id} is a decision on {act.get('target')!r}")
    _need((act.get("payload") or {}).get("decision") == "approve",
          f"{id}: act {act_id} is not an approval")
    _need(act.get("outcome") == "applied", f"{id}: act {act_id} is {act.get('outcome') or 'pending'}, not applied")
    gated_hash = current(id, path).get("text_hash")
    if act.get("base") is not None:
        _need(act["base"] == gated_hash, f"{id}: act {act_id} approved a different text than the gated one")
    return _move(id, "decided", {"decision_act": act_id}, stream=stream or act.get("stream"), path=path,
                 text_hash=gated_hash)


def schedule(id, date, guard, stream=None, path=None):
    """decided -> scheduled for `date` (YYYY-MM-DD); `guard()` returns (ok, reason)."""
    _expect(id, "decided", "scheduled", path)
    try:
        dt.date.fromisoformat(str(date))
    except ValueError:
        raise LifecycleError(f"{id}: {date!r} is not a date (YYYY-MM-DD)")
    _need(callable(guard), f"{id}: scheduling needs a guardrails check")
    ok, reason = guard()
    _need(ok, f"{id}: guardrails refuse: {reason}")
    return _move(id, "scheduled", {"guardrails": "pass"}, stream=stream, path=path,
                 date=str(date), text_hash=current(id, path).get("text_hash"))


def reschedule(id, date, guard, stream=None, path=None):
    """scheduled -> scheduled for a new `date`, within the guardrails; refused once sent or before scheduled."""
    _expect(id, "scheduled", "scheduled", path)
    try:
        dt.date.fromisoformat(str(date))
    except ValueError:
        raise LifecycleError(f"{id}: {date!r} is not a date (YYYY-MM-DD)")
    _need(callable(guard), f"{id}: rescheduling needs a guardrails check")
    ok, reason = guard()
    _need(ok, f"{id}: guardrails refuse: {reason}")
    cur = current(id, path)
    return _move(id, "scheduled", {"guardrails": "pass", "rescheduled_from": cur.get("date")}, stream=stream,
                 path=path, date=str(date), text_hash=cur.get("text_hash"))


def sent(id, ledger_row, stream=None, path=None):
    """scheduled -> sent; the ledger row ({"id" or "ref", "text_hash"?, "sent_at"}) is written first."""
    _expect(id, "scheduled", "sent", path)
    _need(isinstance(ledger_row, dict), f"{id}: sent needs the ledger row")
    _need(ledger_row.get("sent_at"), f"{id}: the ledger row has no sent_at")
    owner = ledger_row.get("id", ledger_row.get("ref"))
    _need(owner == id, f"{id}: the ledger row is for {owner!r}")
    cur = current(id, path)
    if ledger_row.get("text_hash") is not None:
        _need(ledger_row["text_hash"] == cur.get("text_hash"), f"{id}: the ledger row is for a different text")
    return _move(id, "sent", {"ledger": ledger_row}, stream=stream, path=path,
                 sent_at=ledger_row["sent_at"], text_hash=cur.get("text_hash"))


def scored(id, ledger_row, stream=None, path=None):
    """sent -> scored; published_at is the ledger's sent time, never Ready."""
    _expect(id, "sent", "scored", path)
    _need(isinstance(ledger_row, dict) and ledger_row.get("sent_at"), f"{id}: scored needs the ledger row's sent_at")
    cur = current(id, path)
    _need(ledger_row["sent_at"] == cur.get("sent_at"), f"{id}: published_at must be the sent time on the ledger")
    return _move(id, "scored", {"ledger": ledger_row}, stream=stream, path=path,
                 published_at=ledger_row["sent_at"])


def block(id, reason, stream=None, path=None):
    cur = state(id, path)
    _need(cur in LIVE and cur != "blocked", f"{id}: cannot block from {cur}")
    _need(cur != "sent", f"{id}: a sent post cannot be blocked")
    _text(reason, "reason")
    return _move(id, "blocked", {"reason": reason}, stream=stream, path=path)


def retire(id, reason, stream=None, path=None):
    cur = state(id, path)
    _need(cur not in ("retired", "scored"), f"{id}: cannot retire from {cur}")
    _need(cur != "sent", f"{id}: a sent post cannot be retired")
    _text(reason, "reason")
    return _move(id, "retired", {"reason": reason}, stream=stream, path=path)


if __name__ == "__main__":
    print(json.dumps({k: v["to"] for k, v in fold().items()}, indent=2))
