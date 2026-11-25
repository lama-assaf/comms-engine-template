#!/usr/bin/env python3
"""
apply_edits.py - Alpha's desk edits into the vault notes, without clobbering.

Alpha edits a draft in place on the desk (`Tooling/desk/`), and
"Save edit" stores `edits/<id>` in the desk's `edits` table as

    {post, teaser_linkedin, teaser_x, title, by, at, base_hash}

`base_hash` is `repo.base_hash()` over the four edited fields **as the desk
rendered them** - the values `desk_sync.py --push` mirrored from the item's
`Content/Calendar` note. `/social-cycle` step 1 pulls the table into
`state/edits.json` (`desk_sync.py --pull`), and the `distributor` runs this script.

The rule is the milestone's standing one, applied to the desk-to-vault
edge: **reconcile by skipping, never by clobbering.** An
edit is applied only while the note still hashes to the `base_hash` the desk
recorded. Three states, decided by `status_of()`:

  resolved   the note's `desk_edit` marker already names this edit's timestamp.
             Nothing to do; a second run is a no-op.
  pending    the note still hashes to `base_hash`. Nobody has touched the four
             fields since Alpha was shown them, so the edit applies cleanly.
  conflict   it does not. The note moved - an Obsidian edit, a
             gatekeeper fix - after Alpha saved. **Nothing is written**: the
             note is left untouched, the edit stays in `edits/<id>` and in
             `state/edits.json`, the item is flagged on the desk card and in
             `state/runs.json`, and it stays flagged until a person resolves it
             with an explicit `--prefer desk|vault`.

Neither version is ever lost: the vault holds one, the decision store holds the
other, and a human picks. The resolution is recorded on the note in `desk_edit`
`{edited_at, by, base_hash, resolution, at}`, which is what makes a dropped edit
durable (`--prefer vault` cannot delete the desk record - this script has no
reach into the artifact database) and what `publish.py` reads: an applied edit
is a new draft, so it refuses the item until the **gatekeeper** has re-read it
and stamped a `gate.reviewed_at` later than the resolution.

CLI:
  python3 apply_edits.py                       # every pending edit
  python3 apply_edits.py <id>                  # just this one
  python3 apply_edits.py <id> --prefer desk    # resolve a conflict: Alpha's text wins
  python3 apply_edits.py <id> --prefer vault   # resolve a conflict: the note stands
  python3 apply_edits.py --dry-run             # say what would happen, write nothing

Exit 1 while any conflict is left standing, so the cycle and the distributor see
it rather than reading past it.
"""
import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memory  # noqa: E402
import repo  # noqa: E402  - the engine's note reader and writer, next to this file

# The four fields the desk lets Alpha edit. Written onto the note as they stand;
# `repo.HASH_FIELDS` is the same four, in the order they are hashed.
EDIT_FIELDS = ("title", "post", "teaser_linkedin", "teaser_x")

RESOLVED, PENDING, CONFLICT = "resolved", "pending", "conflict"


def edits_path():
    return os.path.join(repo.STATE, "edits.json")


def load_edits():
    """`state/edits.json` - the `edits` collection as /social-cycle pulled it,
    a dict keyed by engine id, the same shape as `state/decisions.json`."""
    p = edits_path()
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def status_of(item, edit):
    """Where this edit stands against the note as it is now.

    The marker, not field equality, decides `resolved`: the four fields are
    `.strip()`ped on the way into the note, and a gatekeeper fix or an Obsidian
    tweak may legitimately move the text after the edit landed. Comparing text
    would turn every one of those into a permanent false conflict.
    """
    de = item.get("desk_edit") or {}
    if de.get("edited_at") and edit.get("at") and de["edited_at"] == edit["at"]:
        return RESOLVED
    if edit.get("base_hash") and repo.base_hash(item) == edit["base_hash"]:
        return PENDING
    return CONFLICT


def parse_ts(value):
    """An ISO timestamp from either side as an aware datetime, or None. The
    desk writes JavaScript's `...Z`, the engine writes `+00:00`; comparing the
    two as strings would silently order them wrong."""
    if not value:
        return None
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def stale_gate(item):
    """The `desk_edit` marker if the gatekeeper has not read the text it left
    behind, else None. An edit is a new draft: whichever way a conflict was
    resolved, the verdict on the note predates the text now on it until the
    gatekeeper stamps a later `gate.reviewed_at`. `gate.linted_at` is not that
    stamp - the deterministic half is not the reading."""
    de = item.get("desk_edit") or {}
    at = parse_ts(de.get("at"))
    if not at:
        return None
    reviewed = parse_ts((item.get("gate") or {}).get("reviewed_at"))
    return None if (reviewed and reviewed > at) else de


def marker(edit, resolution):
    return {
        "edited_at": edit.get("at", ""),
        "by": edit.get("by", ""),
        "base_hash": edit.get("base_hash", ""),
        "resolution": resolution,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }


def apply_one(item_id, edit, resolution):
    """Write the edit's four fields and the marker onto the item's note."""
    fields = {f: str(edit.get(f, "")) for f in EDIT_FIELDS}
    fields["desk_edit"] = marker(edit, resolution)
    return repo.set_fields(item_id, fields)


def keep_vault(item_id, edit):
    """Drop the edit: the note's own text stands. Only the marker is written,
    so the four fields come back out of `write_item` exactly as they went in."""
    return repo.set_fields(item_id, {"desk_edit": marker(edit, "vault")})


def log_run(applied, resolved, conflicts, missing):
    """One `edits` entry in state/runs.json. `detail` is what the desk's
    operations table shows for a step that carries no item count."""
    bits = []
    if applied:
        bits.append(f"{len(applied)} applied")
    if resolved:
        bits.append(f"{len(resolved)} resolved by hand")
    if conflicts:
        ids = ", ".join(c["id"] for c in conflicts)
        bits.append(f"{len(conflicts)} conflict skipped ({ids}): the note moved after Alpha "
                    f"saved, so nothing was written - resolve with --prefer desk|vault")
    if missing:
        bits.append(f"{len(missing)} not in the vault yet")
    if not bits:
        return None
    now = dt.datetime.now(dt.timezone.utc)
    entry = {
        "run_id": now.strftime("%Y%m%dT%H%M%SZ"),
        "step": "edits",
        "stream": memory.DEFAULT_STREAM_NAME,
        "at": now.isoformat(timespec="seconds"),
        "applied": applied,
        "resolved": resolved,
        "conflicts": conflicts,
        "detail": "apply_edits: " + "; ".join(bits),
    }
    runs_p = os.path.join(repo.STATE, "runs.json")
    runs = []
    if os.path.exists(runs_p):
        with open(runs_p, encoding="utf-8") as f:
            runs = json.load(f)
    runs.append(entry)
    os.makedirs(repo.STATE, exist_ok=True)
    with open(runs_p, "w", encoding="utf-8") as f:
        json.dump(runs, f, indent=1, ensure_ascii=False)
    return entry


def run(only=None, prefer=None, dry_run=False, log=True, out=print):
    """Apply what can be applied, skip what cannot, report all of it.

    Returns {"applied": [...], "resolved": [...], "conflicts": [...],
             "missing": [...], "unchanged": [...]}.
    """
    edits = load_edits()
    items = {i["id"]: i for i in repo.load_items()}
    ids = [only] if only else sorted(edits)
    applied, resolved, conflicts, missing, unchanged = [], [], [], [], []

    if only and only not in edits:
        out(f"no desk edit for {only} in {os.path.relpath(edits_path(), repo.REPO)}")
        return {"applied": [], "resolved": [], "conflicts": [], "missing": [], "unchanged": []}

    for item_id in ids:
        edit = edits[item_id]
        item = items.get(item_id)
        if not item:
            # Drafted but not ingested: the vault sweep writes the note, and the
            # next run applies the edit to it. Not a conflict.
            missing.append(item_id)
            out(f"{item_id}: no calendar note yet - left for the vault sweep")
            continue

        state = status_of(item, edit)
        if state == RESOLVED and not prefer:
            unchanged.append(item_id)
            de = item.get("desk_edit") or {}
            out(f"{item_id}: already {de.get('resolution', 'applied')} ({de.get('at', '')}) - nothing to do")
            continue

        if state == CONFLICT and not prefer:
            note_hash = repo.base_hash(item)
            rec = {"id": item_id, "edited_at": edit.get("at", ""), "by": edit.get("by", ""),
                   "base_hash": edit.get("base_hash", ""), "note_hash": note_hash}
            conflicts.append(rec)
            out(f"{item_id}: CONFLICT - the note now hashes {note_hash[:12]}, Alpha edited "
                f"{(edit.get('base_hash') or 'nothing')[:12]}. Nothing written; the edit is kept. "
                f"Resolve with: python3 apply_edits.py {item_id} --prefer desk|vault")
            continue

        if prefer == "vault":
            if dry_run:
                out(f"{item_id}: would keep the vault text and record the edit as dropped")
            else:
                keep_vault(item_id, edit)
                out(f"{item_id}: vault text kept; the desk edit is recorded as dropped, not applied")
            resolved.append({"id": item_id, "prefer": "vault", "was": state})
            continue

        # `desk` is the record of a person choosing Alpha's text over the note,
        # whatever the note said; `applied` is the clean, unattended case.
        resolution = "desk" if prefer == "desk" else "applied"
        if dry_run:
            out(f"{item_id}: would apply Alpha's edit ({state}{', forced' if resolution == 'desk' else ''})")
        else:
            paths = apply_one(item_id, edit, resolution)
            out(f"{item_id}: applied Alpha's edit ({state}) → {os.path.relpath(paths['post'], repo.REPO)}")
        if prefer:
            resolved.append({"id": item_id, "prefer": "desk", "was": state})
        else:
            applied.append(item_id)

    if not dry_run and (applied or resolved):
        repo.write_index()
    if log and not dry_run:
        log_run(applied, resolved, conflicts, missing)
    if conflicts:
        out(f"\n{len(conflicts)} item(s) left flagged. Both versions are intact: the vault holds "
            f"one, {os.path.relpath(edits_path(), repo.REPO)} and the desk hold the other.")
    return {"applied": applied, "resolved": resolved, "conflicts": conflicts,
            "missing": missing, "unchanged": unchanged}


def main(argv=None):
    ap = argparse.ArgumentParser(description="apply Alpha's desk edits to the vault notes, skipping conflicts")
    ap.add_argument("id", nargs="?", help="engine id (default: every pending edit)")
    ap.add_argument("--prefer", choices=["desk", "vault"],
                    help="resolve a flagged conflict by hand: desk applies Alpha's text, vault keeps the note")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.prefer and not args.id:
        ap.error("--prefer resolves one flagged item: give its id")
    result = run(only=args.id, prefer=args.prefer, dry_run=args.dry_run)
    if not any(result[k] for k in ("applied", "resolved", "conflicts", "missing", "unchanged")):
        print("no desk edits to apply")
    sys.exit(1 if result["conflicts"] else 0)


if __name__ == "__main__":
    main()
