#!/usr/bin/env python3
"""
claims_check.py - the supersession and decay check (plan v2, item A6).

The register (`.atelier/memory/claims.md`) moves under published and queued
pieces: a row is superseded, a grade or a corroboration falls. A piece that
cited the row still stands with its old wording, and the engine never edits a
published piece. So this script finds every note whose cited claim changed
after the gate last read the note, and raises each as *review: update,
annotate or retire* for a person. It also raises a published piece whose
engagement has decayed below the stream's baseline for its age (the guide's
refresh flag), once scoring records exist (A9).

How "changed after the gate read it" is known without a date on the row: the
script keeps a snapshot of the register (`state/claims-snapshot.json`: id ->
grade, corroboration, superseded_by) and appends every difference it sees to
`state/claims-changes.json` with the time it saw it. A change logged later
than a note's gate reading flags the note. The first run bootstraps the
snapshot and logs nothing. Independently of time, a cite that is superseded
or no longer citable *now* always flags the note: a stale snapshot can delay
a flag, never hide one.

Writes `state/claims-review.json`, one entry per note with its reasons, and
one `claims-check` row in `state/runs.json`. Reads everything through
`memory.py` and `repo.py`; writes no note and no register.

  engine claims_check            # check and write
  engine claims_check --dry-run  # print, write nothing
"""
import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
STATE = paths.state()
sys.path.insert(0, HERE)
import memory  # noqa: E402
import repo  # noqa: E402
import runlog  # noqa: E402

ACTION = "review: update, annotate or retire"
#: A published piece is judged for decay only once it is older than this.
DECAY_AGE_DAYS = 14
#: ...and flagged when its index is below this share of the baseline.
DECAY_SHARE = 0.5

TRACKED = ("grade", "corroboration", "superseded_by")


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _parse(ts):
    if not ts:
        return None
    try:
        d = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def _load(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


# ── the register's movement ─────────────────────────────────────────────────

def snapshot_of(register):
    return {cid: {k: r.get(k, "") for k in TRACKED} for cid, r in register.items()}


def diff(old, new, seen_at):
    """Every tracked change between two snapshots, each with the time seen."""
    changes = []
    for cid, cur in new.items():
        was = old.get(cid)
        if was is None:
            continue  # a new row flags nothing; nothing could have cited it
        for k in TRACKED:
            if was.get(k, "") != cur.get(k, ""):
                changes.append({"id": cid, "field": k, "from": was.get(k, ""), "to": cur.get(k, ""),
                                "seen_at": seen_at})
    return changes


def update_log(state, register, now, dry_run=False):
    """Compare the register to the last snapshot, append the differences to
    the change log, and return the whole log. The first run bootstraps."""
    snap_path = os.path.join(state, "claims-snapshot.json")
    log_path = os.path.join(state, "claims-changes.json")
    old = _load(snap_path, None)
    new = snapshot_of(register)
    log = _load(log_path, [])
    fresh = diff(old, new, now.isoformat(timespec="seconds")) if old is not None else []
    log.extend(fresh)
    if not dry_run:
        _write(snap_path, new)
        if fresh or not os.path.exists(log_path):
            _write(log_path, log)
    return log, fresh, old is None


# ── the notes that lean on it ───────────────────────────────────────────────

def gate_read_at(item):
    """When the gate last read this note: the gatekeeper's `reviewed_at`,
    else the linter's `linted_at`; None when it has never been read."""
    g = item.get("gate") or {}
    return _parse(g.get("reviewed_at")) or _parse(g.get("linted_at"))


def standing_of(item):
    if item.get("published_at"):
        return "published"
    return "queued"


def reasons_for(item, register, log):
    """Why this note needs a person: current-state faults on any cite, and
    logged changes to a cite after the gate read the note."""
    out = []
    cites = [str(c) for c in (item.get("cites") or [])]
    read_at = gate_read_at(item)
    for cid in cites:
        ok, why = memory.citable(cid, claims=register)
        if not ok:
            out.append({"claim": cid, "kind": "uncitable now", "detail": why})
        for ch in log:
            if ch["id"] != cid:
                continue
            seen = _parse(ch["seen_at"])
            if read_at is None or (seen and seen > read_at):
                out.append({"claim": cid, "kind": f"{ch['field']} changed after the gate read it",
                            "detail": f"{ch['field']}: {ch['from'] or '—'} -> {ch['to'] or '—'} (seen {ch['seen_at']})"})
    # one entry per (claim, kind): the log can hold several steps of one move
    seen_keys, dedup = set(), []
    for r in out:
        key = (r["claim"], r["kind"])
        if key not in seen_keys:
            seen_keys.add(key)
            dedup.append(r)
    return dedup


def decay_reason(item, records, now):
    """The refresh flag: a published piece past DECAY_AGE_DAYS whose scored
    index sits below DECAY_SHARE of its baseline. Needs an A9 record."""
    pub = _parse(item.get("published_at"))
    if not pub or (now - pub).days < DECAY_AGE_DAYS:
        return None
    rec = records.get(item["id"])
    if not rec or rec.get("score") is None or not rec.get("baseline"):
        return None
    if rec["score"] < DECAY_SHARE * rec["baseline"]:
        return {"claim": "", "kind": "engagement decayed",
                "detail": f"score {rec['score']} against baseline {rec['baseline']} at {(now - pub).days} days"
                          + (" (partial)" if rec.get("partial") else "")}
    return None


def engagement_records(state):
    """`{item id: record}` from `engagement.json`'s `records` list (A9 shape).
    Empty until scoring exists."""
    eng = _load(os.path.join(state, "engagement.json"), {})
    out = {}
    for r in eng.get("records", []) or []:
        if isinstance(r, dict) and r.get("id"):
            out[r["id"]] = r
    return out


def run(state=None, items=None, register=None, now=None, dry_run=False):
    state = state or STATE
    now = now or _now()
    register = memory.load_claims() if register is None else register
    items = repo.load_items() if items is None else items
    log, fresh, bootstrapped = update_log(state, register, now, dry_run)
    records = engagement_records(state)
    review = []
    for item in items:
        reasons = reasons_for(item, register, log)
        d = decay_reason(item, records, now)
        if d:
            reasons.append(d)
        if reasons:
            review.append({
                "id": item["id"], "title": item.get("title", ""), "stream": item.get("stream", ""),
                "standing": standing_of(item), "cites": list(item.get("cites") or []),
                "gate_read_at": (gate_read_at(item) or dt.datetime.min.replace(tzinfo=dt.timezone.utc)).isoformat(timespec="seconds")
                if gate_read_at(item) else "",
                "reasons": reasons, "action": ACTION,
            })
    payload = {"checked_at": now.isoformat(timespec="seconds"), "action": ACTION,
               "changes_seen_this_run": fresh, "bootstrapped": bootstrapped, "items": review}
    if not dry_run:
        _write(os.path.join(state, "claims-review.json"), payload)
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description="notes whose cited claims moved, and pieces that decayed")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--state", default=STATE)
    a = ap.parse_args(argv)
    try:
        out = run(state=a.state, dry_run=a.dry_run)
    except memory.SharedMemoryError as e:
        print(f"claims_check: {e}", file=sys.stderr)
        return 2
    n = len(out["items"])
    detail = (f"claims_check: {n} note(s) for review, {len(out['changes_seen_this_run'])} register change(s) seen"
              + (" (snapshot bootstrapped)" if out["bootstrapped"] else ""))
    print(detail)
    for it in out["items"]:
        print(f"  {it['standing']:<9} {it['id']}  {it['title'][:60]}")
        for r in it["reasons"]:
            print(f"      {r['kind']}: {r['detail']}")
    if not a.dry_run:
        runlog.append("claims-check", detail, stream=memory.DEFAULT_STREAM_NAME, runs_path=os.path.join(a.state, "runs.json"),
                      items=n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
