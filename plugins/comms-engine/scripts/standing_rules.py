#!/usr/bin/env python3
"""
standing_rules.py - the desk's two standing rules, held once for every face that approves.

  * Approving a post stays closed until its argument line is confirmed and current: the
    hook and the claim are Alpha's act, and the act only counts while it names the hook now
    on the card (a rewritten hook reopens it). A post the claim gate blocked is not approved.
  * A hold, a rejection and a rewrite carry a written reason. An approval may (owner decision,
    2026-11-11): a reason typed with one is still stored, and one marked `standing` becomes an
    entry in `.atelier/memory/reviews.md`, written by `desk_sync.py --pull` alone; an approval
    with no reason records no review.

The engine's own approval (`desk_acts.engine_approve`, where a person switched the stream's
post mode to `auto`) is asked the same check with `role="engine"`: the argument line is a
person's act and is not asked of it, the gate still is. No other role skips anything.

`refusal()` is the check. The dashboard (`control.approve_post`, `control.approve_reply`),
`desk_acts.approve_post` and `today.py` all call it; the desk's own copy is
`desk/lib/rules.ts`, and `tests/test_standing_rules.py` runs both over the same vectors.

The dashboard records what it does in the desk's own store, so the desk and the single
writer of `reviews.md` see it: the argument line goes to `argument_lines` (as `today.py
confirm` does) and the reason to `reviews`, each also as the act `--pull` would make
(same id, so pulling it later records nothing twice). This module never writes
`reviews.md`.
"""
import datetime as dt
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

REASON = "A hold, a rejection or a rewrite carries a reason. Write what made you decide this before recording it."
ARGUMENT = ("Confirm or rewrite the argument line first — the hook and the claim are your act, "
            "and nothing is approved without it.")
BLOCKED = "The claim gate blocked this one. Fix the line and let the gatekeeper re-read it before approving."
STATUSES = ("approved", "held", "rejected", "rewrite")
SCOPES = ("item", "standing")


ENGINE_ROLE = "engine"


def refusal(status, reason, kind="post", argument_current=False, blocked=False, role=None):
    """The reason a decision may not be recorded, or None. Same order as the desk: reason first
    (not asked of an approval), then (approve of a post only) the argument line, then the gate.
    `role="engine"` skips the argument line and nothing else."""
    if status != "approved" and not str(reason or "").strip():
        return REASON
    if kind == "post" and status == "approved":
        if not argument_current and role != ENGINE_ROLE:
            return ARGUMENT
        if blocked:
            return BLOCKED
    return None


def norm_scope(value):
    """`item` or `standing`; nothing given is `item`. Anything else is an error, not a guess."""
    value = str(value or "item").strip().lower()
    if value not in SCOPES:
        raise ValueError(f"scope is item or standing, not {value!r}")
    return value


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def db_path(state_dir=None):
    """The desk database: `DESK_DB` if set, else `desk.db` in the state directory."""
    import store
    return os.environ.get("DESK_DB") or os.path.join(state_dir or store.STATE, "desk.db")


def _read(path, sql, *args):
    """One row of the desk database as a dict, or None (no file, no table, no row). Never writes."""
    if not os.path.exists(path):
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute(sql, args).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    return dict(row) if row else None


def post_facts(item, path):
    """What the rules need to know about a post: the hook now on the card (a saved desk edit's
    title over the note's), the claim, the confirmed argument line if any, whether it is current,
    and whether the claim gate blocked it. Read from the desk database, as the desk reads it."""
    edit = _read(path, "SELECT title FROM edits WHERE item_id = ?", item["id"])
    arg = _read(path, "SELECT * FROM argument_lines WHERE item_id = ?", item["id"])
    hook = edit["title"] if edit and edit["title"] is not None else item.get("title", "")
    return {"hook": hook, "claim": item.get("excerpt", "") or "", "argument": arg,
            "argument_current": bool(arg) and arg["hook"] == hook,
            "blocked": (item.get("gate") or {}).get("verdict") == "block"}


def _connect(path):
    import desk_sync
    con = desk_sync.connect(path)
    desk_sync.ensure_schema(con)
    return con


def _act_once(kind, stream, target, payload, aid, by, at, state_dir):
    import acts
    import desk_acts
    apath = os.path.join(state_dir, desk_acts.ACTS_FILE)
    if any(a["id"] == aid for a in acts.list_acts(path=apath)):
        return aid
    acts.record(kind, stream, target, payload, base=None, by=by, id=aid, at=at, path=apath)
    acts.applied(aid, path=apath)
    return aid


def confirm_argument(item, by, state_dir, path=None):
    """Confirm the argument line as it stands, as `today.py confirm` does: one `argument_lines` row
    (act `confirmed`, the hook on the card, the claim), and the act the desk's pull would make."""
    import desk_acts
    path = path or db_path(state_dir)
    facts = post_facts(item, path)
    role, at = desk_acts.role_of(by), now()
    con = _connect(path)
    try:
        con.execute("INSERT INTO argument_lines (item_id, act, hook, claim, by, at) "
                    "VALUES (?, 'confirmed', ?, ?, ?, ?) "
                    "ON CONFLICT(item_id) DO UPDATE SET act=excluded.act, hook=excluded.hook, claim=excluded.claim, "
                    "by=excluded.by, at=excluded.at", (item["id"], facts["hook"], facts["claim"], role, at))
        con.commit()
    finally:
        con.close()
    stream = item.get("stream") or desk_acts.DEFAULT_STREAM
    aid = _act_once("argument_line", stream, item["id"],
                    {"act": "confirmed", "hook": facts["hook"], "claim": facts["claim"], "source": "dashboard"},
                    desk_acts.act_id("argument", item["id"], "confirmed", at), role, at, state_dir)
    return {"id": item["id"], "act": "confirmed", "hook": facts["hook"], "claim": facts["claim"], "by": role, "at": at,
            "act_id": aid}


def record_review(item_id, kind, theme, title, verdict, reason, scope, by, stream, state_dir, path=None):
    """The reason as the desk records it: a `reviews` row of this scope. `desk_sync.py --pull` is
    what appends a `standing` one to `reviews.md`; the matching `review` act is made now with the
    id the pull would give it. Returns the row, or None when the reason is empty (nothing recorded)."""
    import desk_acts
    path = path or db_path(state_dir)
    role, at, scope = desk_acts.role_of(by), now(), norm_scope(scope)
    reason = str(reason or "").strip()
    if not reason:  # an approval needs none; with none there is no review to keep
        return None
    con = _connect(path)
    try:
        cur = con.execute("INSERT INTO reviews (item_id, kind, theme, title, verdict, rationale, scope, by, at) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (item_id, kind, theme or "", title or "", verdict, reason, scope, role, at))
        rowid = cur.lastrowid
        con.commit()
    finally:
        con.close()
    _act_once("review", stream or desk_acts.DEFAULT_STREAM, item_id,
              {"verdict": verdict, "scope": scope, "theme": theme or "", "rationale": reason},
              desk_acts.act_id("review", rowid, item_id, at), role, at, state_dir)
    return {"rowid": rowid, "item_id": item_id, "verdict": verdict, "scope": scope, "at": at}
