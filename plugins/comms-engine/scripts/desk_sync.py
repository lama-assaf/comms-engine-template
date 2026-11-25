#!/usr/bin/env python3
"""
desk_sync.py - the bridge between the desk application and the engine.

The desk (`Tooling/desk/`, Next.js over Drizzle) reads and writes
one SQLite file, `state/desk.db`. This script is the only thing that moves data
across that boundary, in both directions:

  --push   the engine's state into the desk's read-only mirror tables:
           `items` (from the `Content/Calendar/` notes, through repo.py),
           `themes` and `inventory` (from `.atelier/memory/`, through memory.py
           and inventory.py), `findings`, `proposals` and `runs` (from
           state/*.json). Every row is a derivation; the tables are replaced
           wholesale and nothing is lost by deleting the file.

  --pull   Alpha's acts back out of the desk into the shapes the cycle already
           reads: `state/decisions.json`, `state/edits.json`,
           `state/arguments.json`, and the standing reviews appended to
           `.atelier/memory/reviews.md`. Each pulled decision, edit, argument line
           and review also becomes an act (desk_acts.py); an approval is applied to
           the lifecycle (gated -> decided -> scheduled for the note's date, within
           the guardrails) and every act ends with one outcome.

The rule that governs the whole design: **the database is a derived index and a
decision store, never the record.** `Content/Calendar/<title>.md` is the record
and `scripts/repo.py` is its only writer. The desk never touches a note, never
touches `.atelier/memory/`. It writes its own four tables,
and `--pull` is what turns those rows into something the engine acts on -
through `apply_edits.py` for the edits, which still reconciles by skipping and
never by clobbering.

Two consequences worth stating because they are easy to break:

  * `--push` must never write the four decision-store tables. It replaces the
    mirror tables only. An Alpha act that had not been pulled yet would
    otherwise be destroyed by a routine refresh.

  * `handles.private.md` is never read. The stealth counterparties are the one
    part of the inventory that must not reach a store that can be deployed, so
    `inventory` carries the public rows with `identity` dropped. The desk reports
    the private companion as present or absent and never holds its contents.

Schema DDL has a single source: `desk/db/schema.ts` generates
`desk/drizzle/*.sql` with `npm run generate`, and this script applies those same
files. The two runtimes cannot end up with different tables.

CLI:
  python3 desk_sync.py --push              # engine state -> desk.db
  python3 desk_sync.py --pull              # Alpha's acts -> state/*.json + memory
  python3 desk_sync.py --push --pull       # pull first, then push (what the cycle wants)
  python3 desk_sync.py --pull --dry-run    # say what would be written, write nothing
  python3 desk_sync.py --init              # create the tables and stop
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
sys.path.insert(0, HERE)

import desk_acts  # noqa: E402
import inventory  # noqa: E402
import memory  # noqa: E402
import repo  # noqa: E402

ENGINE = os.path.dirname(HERE)
STATE = paths.state()
REPO_ROOT = paths.instance()
DESK = os.path.join(REPO_ROOT, "Tooling", "desk")
MIGRATIONS = os.path.join(DESK, "drizzle")
DB_PATH = os.environ.get("DESK_DB", os.path.join(STATE, "desk.db"))
REVIEWS_MD = os.path.join(REPO_ROOT, ".atelier", "memory", "reviews.md")

# The mirror tables. `--push` replaces these and only these.
MIRROR_TABLES = ("items", "findings", "proposals", "runs", "themes", "inventory")
# The decision store. `--push` never writes these; `--pull` only reads them,
# apart from stamping `reviews.synced_at`.
STORE_TABLES = ("decisions", "edits", "argument_lines", "reviews")

REVIEWS_HEADER = """# reviews

Alpha's standing reviews, appended by `scripts/desk_sync.py --pull`
from the decisions recorded on the desk. One entry per review Alpha marked as *standing*:
the part of the reasoning that outlives the item it was written about.

`theme-writer` reads this file before drafting and `gatekeeper` reads it before gating,
which is the point of it - a judgement Alpha has already made once should not have to be
made again on the next draft of the same shape. Reviews scoped to a single item stay on
the desk and on the item's note; they are not repeated here.

Plain markdown on purpose: agents and people read the memory files and have no reach
into the desk's database.

---
"""


def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------- the database


def connect(path=DB_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _has_desk_tables(path):
    """True when the file holds the desk's decision store; read only, and nothing is created."""
    if not os.path.isfile(path):
        return False
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
    except sqlite3.Error:
        return False
    return bool(set(STORE_TABLES) & have)


def ensure_schema(con):
    """Apply `desk/drizzle/*.sql` for any table that is not there yet.

    Drizzle's generated files separate statements with `--> statement-breakpoint`.
    Each statement is `CREATE TABLE`/`CREATE INDEX`, so applying a file twice is
    harmless once the `IF NOT EXISTS` is added: drizzle-kit does not emit it, and
    re-running a migration on a live database has to be a no-op here because
    `--push` calls this on every run.
    """
    have = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if set(MIRROR_TABLES + STORE_TABLES + ("sync_meta",)) <= have:
        ensure_stream_columns(con)
        return False
    if not os.path.isdir(MIGRATIONS):
        raise SystemExit(f"no migrations at {MIGRATIONS} - run `npm run generate` in desk/ first")
    for name in sorted(os.listdir(MIGRATIONS)):
        if not name.endswith(".sql"):
            continue
        with open(os.path.join(MIGRATIONS, name), encoding="utf-8") as f:
            sql = f.read()
        for stmt in sql.split("--> statement-breakpoint"):
            stmt = stmt.strip()
            if not stmt:
                continue
            stmt = re.sub(r"^CREATE TABLE `", "CREATE TABLE IF NOT EXISTS `", stmt)
            stmt = re.sub(r"^CREATE INDEX `", "CREATE INDEX IF NOT EXISTS `", stmt)
            stmt = re.sub(r"^CREATE UNIQUE INDEX `", "CREATE UNIQUE INDEX IF NOT EXISTS `", stmt)
            con.execute(stmt)
    con.commit()
    ensure_stream_columns(con)
    return True


#: The mirror tables that gained a `stream` column with plan v2 (A14). The
#: `items` table had one from the start; the store tables carry it through
#: the item they are about, never on their own rows.
STREAM_COLUMN_TABLES = ("findings", "proposals", "runs", "themes", "inventory")


#: Columns plan v2 added to `items`: cites (A5) and the prediction (A8).
ITEM_V2_COLUMNS = (("cites", "TEXT"), ("query", "TEXT NOT NULL DEFAULT ''"),
                   ("hypothesis", "TEXT NOT NULL DEFAULT ''"), ("predicted", "TEXT NOT NULL DEFAULT ''"),
                   ("test_id", "TEXT NOT NULL DEFAULT ''"))


def ensure_stream_columns(con):
    """Add `stream` to each mirror table that lacks it, and the plan-v2 item
    columns to `items`. Idempotent, so a database made before plan v2 and one
    made after read the same; the Drizzle schema declares the same columns."""
    added = []
    for table in STREAM_COLUMN_TABLES:
        cols = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
        if "stream" not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN stream TEXT NOT NULL DEFAULT ''")
            added.append(table)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(items)")}
    for name, decl in ITEM_V2_COLUMNS:
        if name not in cols:
            con.execute(f"ALTER TABLE items ADD COLUMN {name} {decl}")
            added.append(f"items.{name}")
    if added:
        con.commit()
    return added


def meta_set(con, key, value):
    con.execute(
        "INSERT INTO sync_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def replace(con, table, rows):
    """Replace a mirror table wholesale. Refuses to touch the decision store."""
    if table not in MIRROR_TABLES:
        raise ValueError(f"{table} is not a mirror table - --push must not write it")
    con.execute(f"DELETE FROM {table}")
    if not rows:
        return 0
    cols = list(rows[0].keys())
    marks = ", ".join("?" for _ in cols)
    sql = f"INSERT INTO {table} ({', '.join('`' + c + '`' for c in cols)}) VALUES ({marks})"
    con.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
    return len(rows)


def j(value):
    """A JSON column, in the text form Drizzle's `mode: 'json'` reads back."""
    return json.dumps(value, ensure_ascii=False)


def load_json(name, default):
    p = os.path.join(STATE, name)
    if not os.path.exists(p):
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------- the push


def item_rows(now):
    """Every engine note in `Content/Calendar/`, as the desk's `items` table.

    `repo.load_items()` is the read path; the note's own frontmatter is opened
    alongside it for the three values the item shape does not carry - the
    calendar `status`, the gate verdict and the publish record -
    because the calendar is a view over exactly those.
    """
    notes = repo.scan_notes()
    rows = []
    for item in repo.load_items():
        blog = notes.get(item["id"], {}).get("Blog")
        path, fm = (blog[0], blog[1]) if blog else ("", {})
        slot = item.get("slot") or {}
        rows.append({
            "id": item["id"],
            "title": item.get("title", ""),
            "theme": item.get("theme", ""),
            "stream": item.get("stream", ""),
            "type": item.get("type", ""),
            "pillar": item.get("pillar", ""),
            "platform": slot.get("platform", "") or fm.get("platform", ""),
            "format": item.get("format", ""),
            "owner": item.get("owner", ""),
            "campaign": slot.get("campaign", ""),
            "date": slot.get("date") or None,
            "status": fm.get("status", "Idea"),
            "alpha_status": item.get("alpha_status", "proposed"),
            "gate_verdict": (item.get("gate") or {}).get("verdict", ""),
            "gate": j(item.get("gate") or None),
            "logic": item.get("logic", ""),
            "finding_id": item.get("finding_id", ""),
            "anchor": item.get("anchor", ""),
            "slug": item.get("slug", ""),
            "excerpt": item.get("excerpt", ""),
            "cta": item.get("cta", ""),
            "post": item.get("post", ""),
            "teaser_linkedin": item.get("teaser_linkedin", ""),
            "teaser_x": item.get("teaser_x", ""),
            "hooks_considered": j(item.get("hooks_considered") or []),
            "partner_tags": j(item.get("partner_tags") or []),
            "freshness_deadline": item.get("freshness_deadline") or None,
            "drafted_by": item.get("drafted_by", ""),
            "drafted_at": item.get("drafted_at") or None,
            # The note as it stands right now. The desk stamps an edit with
            # this, and apply_edits.py re-derives it from the note: where the
            # two disagree the note has moved and nothing is written.
            "note_hash": repo.base_hash(item),
            "note_path": os.path.relpath(path, REPO_ROOT) if path else "",
            "desk_edit": j(item.get("desk_edit") or None),
            "published_at": item.get("published_at") or None,
            # plan v2: the register rows the post leans on (A5) and the
            # planning query, hypothesis, predicted band and test (A8)
            "cites": j(item.get("cites") or []),
            "query": item.get("query", "") or "",
            "hypothesis": item.get("hypothesis", "") or "",
            "predicted": item.get("predicted", "") or "",
            "test_id": item.get("test_id", "") or "",
            "synced_at": now,
        })
    return rows


def finding_rows():
    """Every finding in `state/signals.json`, carrying the strategist's verdict.

    The verdict comes from `state/strategy.json`, which names a finding in
    exactly two of its keys: `picks` and `not_this_week`, both lists of objects
    with a `finding_id`. A finding named in neither has no verdict yet and keeps
    the empty status — the desk shows it as undecided rather than inventing a
    third state for it.

    `held_slot` is deliberately not read here. It is a prose paragraph about the
    reactive calendar row — whether the week's trigger fired and what would fire
    it — and it never names a finding, so there is nothing in this file that a
    `held` status could be derived from. It was a key here once; it matched
    nothing, and a status with no source is worse than an absent one.
    """
    sig = load_json("signals.json", {})
    picks = {}
    strat = load_json("strategy.json", {})
    for key, status in (("picks", "picked"), ("not_this_week", "not-this-week")):
        for entry in strat.get(key, []) or []:
            if isinstance(entry, dict):
                fid = entry.get("finding_id") or entry.get("id")
            else:
                fid = entry
            if fid:
                picks[fid] = status
    rows = []
    for f in sig.get("findings", []) or []:
        ev = (f.get("evidence") or [{}])[0]
        rows.append({
            "id": f.get("id", ""),
            "stream": f.get("stream") or sig.get("stream", ""),
            "theme": f.get("theme", ""),
            "summary": f.get("finding", "") or f.get("summary", ""),
            "why": f.get("why", "") or f.get("so_what", ""),
            "shape": f.get("shape", "") or ("conversation" if f.get("conversation") else "content"),
            "relevance": str(f.get("relevance", "")),
            "sentiment": str(f.get("sentiment", "")),
            "source": ev.get("source", "") or ev.get("title", ""),
            "url": ev.get("url", "") or ev.get("link", ""),
            "at": f.get("at") or ev.get("at") or None,
            "status": picks.get(f.get("id", ""), ""),
        })
    return rows


def proposal_id(p):
    """The id the desk gives a comment proposal.

    Identical to `proposalId` in `dashboard/template.html`, because a decision
    Alpha made on the artifact desk and one made in the app have to land on the
    same key in `state/decisions.json`.
    """
    return "C-" + str(p.get("finding_id", "")) + "-" + re.sub(r"[^A-Za-z0-9_]", "", str(p.get("author", "")))


def proposal_rows():
    eng = load_json("engagement.json", {})
    return [{
        "id": proposal_id(p),
        "stream": p.get("stream") or eng.get("stream", ""),
        "theme": p.get("theme", ""),
        "author": p.get("author", ""),
        "handle": p.get("author", ""),
        "platform": p.get("platform", ""),
        "url": p.get("target_url", ""),
        "why": p.get("why", "") or p.get("shape", ""),
        "draft": p.get("draft_comment", ""),
        "at": p.get("at") or None,
    } for p in eng.get("proposals", []) or []]


def run_rows():
    out = []
    for r in load_json("runs.json", []) or []:
        out.append({
            "run_id": r.get("run_id", ""),
            "stream": r.get("stream", ""),
            "step": r.get("step", ""),
            "at": r.get("at") or None,
            "detail": r.get("detail", ""),
            "items": r.get("items"),
            "terms": r.get("terms"),
            "elapsed_s": str(r.get("elapsed_s")) if r.get("elapsed_s") is not None else None,
            "file": r.get("file", ""),
        })
    return out


def theme_rows():
    return [{
        "tag": t.get("tag", ""),
        "stream": memory.DEFAULT_STREAM_NAME,
        "differentiator": t.get("different", ""),
        "licence": t.get("licence", ""),
        "fact": t.get("fact", ""),
        "partners": j(t.get("partner_tags") or []),
    } for t in memory.load_themes()]


def inventory_rows():
    """The public handle inventory, with `identity` dropped.

    The same projection `build_dashboard.py` makes before the state is inlined
    into a published artifact, for the same reason: `handles.private.md` holds
    the stealth denylist and must not reach a store that can be deployed. This
    function reads `inventory.inventory_rows()`, which reads the public file
    only, and drops the `identity` key on the way past.
    """
    rows = []
    for r in inventory.inventory_rows():
        handles = r.get("handles") or [{}]
        for h in handles:
            rows.append({
                "scope": "own" if "own" in str(r.get("table", "")) else "partner",
                "brand": r.get("party", ""),
                "name": r.get("party", ""),
                "platform": h.get("platform", ""),
                "handle": h.get("handle", ""),
                "status": r.get("status", ""),
                "last_verified": r.get("last_verified") or None,
                "stale": 1 if r.get("stale") else 0,
                "note": r.get("note", ""),
            })
    return rows


def push(con, verbose=True):
    now = utcnow()
    counts = {
        "items": replace(con, "items", item_rows(now)),
        "findings": replace(con, "findings", finding_rows()),
        "proposals": replace(con, "proposals", proposal_rows()),
        "runs": replace(con, "runs", run_rows()),
        "themes": replace(con, "themes", theme_rows()),
        "inventory": replace(con, "inventory", inventory_rows()),
    }
    meta_set(con, "last_push", now)
    meta_set(con, "engine_root", ENGINE)
    meta_set(con, "private_handles_present", "1" if memory.load_handles()["private"]["present"] else "0")
    meta_set(con, "inventory_window_days", inventory.WINDOW_DAYS)
    con.commit()
    if verbose:
        print("push " + " · ".join(f"{k} {v}" for k, v in counts.items()))
    return counts


# ------------------------------------------------------------------- the pull


def write_json(path, payload, dry_run=False):
    if dry_run:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    return True


def item_streams():
    """`{item id: stream}` from the notes, so every pulled act names the stream
    of the item it was made on (plan v2, A3). An id with no note - a comment
    proposal, say - carries the engagement file's stream when it names one."""
    streams = {i["id"]: i.get("stream", "") for i in repo.load_items()}
    eng = load_json("engagement.json", {})
    for p in eng.get("proposals", []) or []:
        streams.setdefault(proposal_id(p), p.get("stream") or eng.get("stream", ""))
    return streams


def recorded_streams(name):
    """`{id: stream}` as the state file already records it. An act whose item
    has left the notes or the engagement file (a September comment proposal
    after a new engagement pass) keeps the stream it was stamped with, rather
    than being pulled back to '' and failing `state_check` (2026-11-05)."""
    existing = load_json(name, {})
    return {k: v.get("stream", "") for k, v in existing.items() if isinstance(v, dict)}


def stream_for(item_id, streams, kept):
    return streams.get(item_id) or kept.get(item_id, "")


def pull_decisions(con, streams=None):
    """`state/decisions.json` - `{id: {status, note, by, at, stream}}`.

    The shape `publish.py`, the `distributor` and `build_dashboard.py` already
    read, so nothing downstream changes when the store moves off claude.ai.
    """
    streams = item_streams() if streams is None else streams
    kept = recorded_streams("decisions.json")
    return {r["id"]: {"status": r["status"], "note": r["note"], "by": r["by"], "at": r["at"],
                      "stream": stream_for(r["id"], streams, kept)}
            for r in con.execute("SELECT * FROM decisions ORDER BY id")}


def pull_edits(con, streams=None):
    """`state/edits.json` - the shape `apply_edits.py` reads, unchanged.

    `base_hash` is the digest of the note as the desk showed it, computed in
    `desk/lib/hash.ts` to agree with `repo.base_hash()`. `apply_edits.py`
    applies an edit only while the note still hashes to it, and reports a
    conflict rather than clobbering either side.
    """
    streams = item_streams() if streams is None else streams
    kept = recorded_streams("edits.json")
    return {r["item_id"]: {"title": r["title"], "post": r["post"],
                           "teaser_linkedin": r["teaser_linkedin"], "teaser_x": r["teaser_x"],
                           "base_hash": r["base_hash"], "by": r["by"], "at": r["at"],
                           "stream": stream_for(r["item_id"], streams, kept)}
            for r in con.execute("SELECT * FROM edits ORDER BY item_id")}


def pull_arguments(con, streams=None):
    """`state/arguments.json` - `{id: {act, hook, claim, by, at, stream}}`."""
    streams = item_streams() if streams is None else streams
    kept = recorded_streams("arguments.json")
    return {r["item_id"]: {"act": r["act"], "hook": r["hook"], "claim": r["claim"],
                           "by": r["by"], "at": r["at"], "stream": stream_for(r["item_id"], streams, kept)}
            for r in con.execute("SELECT * FROM argument_lines ORDER BY item_id")}


def review_entry(r):
    day = str(r["at"])[:10]
    head = f"## {day} — {r['theme'] or 'no theme'} — {r['verdict'] or 'reviewed'}"
    body = (r["rationale"] or "").strip()
    return (f"\n{head}\n\n"
            f"item: `{r['item_id']}`" + (f" — “{r['title']}”" if r["title"] else "") + "\n"
            f"by: {r['by']}\n\n"
            f"{body}\n\n---\n")


def reviews_target(stream_name):
    """The `reviews.md` a standing review belongs to (A14): the item's
    stream's own file. The root stream's is `REVIEWS_MD` (the memory root); another
    stream's is `streams/<slug>/reviews.md`; an item with no resolvable
    stream falls back to the root file and is named as such."""
    try:
        slug = memory.slug_for(stream_name or "")
    except memory.SharedMemoryError:
        return REVIEWS_MD
    if slug == memory.DEFAULT_STREAM:
        return REVIEWS_MD
    return os.path.join(memory.stream_dir(slug), "reviews.md")


def pull_reviews(con, dry_run=False, streams=None):
    """Append Alpha's standing reviews to the stream's `reviews.md`.

    Only `scope = 'standing'` rows travel: those are the ones Alpha marked as
    outliving the item. `synced_at` is stamped once the file is written and is
    what stops an entry being appended twice; a `--push` never clears it.
    Each returned row carries `stream` and `target`, the file it goes to, so a
    dry run names the destination per review (A14).

    The engine writes these files and nothing else in `.atelier/memory/`. They
    are additive by construction - entries are appended, never rewritten - so
    the other runtime reading the same directory keeps working.
    """
    streams = item_streams() if streams is None else streams
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM reviews WHERE scope = 'standing' AND (synced_at IS NULL OR synced_at = '') "
        "ORDER BY at, rowid")]
    for r in rows:
        r["stream"] = streams.get(r["item_id"], "")
        r["target"] = reviews_target(r["stream"])
    if not rows or dry_run:
        return rows
    by_target = {}
    for r in rows:
        by_target.setdefault(r["target"], []).append(r)
    for target, trows in by_target.items():
        os.makedirs(os.path.dirname(target), exist_ok=True)
        fresh = not os.path.exists(target)
        with open(target, "a", encoding="utf-8") as f:
            if fresh:
                f.write(REVIEWS_HEADER)
            for r in trows:
                f.write(review_entry(r))
    now = utcnow()
    con.executemany("UPDATE reviews SET synced_at = ? WHERE rowid = ?",
                    [(now, r["rowid"]) for r in rows])
    con.commit()
    return rows


def pull_acts(con, decisions, edits, args_, streams, dry_run=False, guard=None):
    """Turn every desk row into an act (desk_acts.py) and apply the approvals to the lifecycle.

    The rows are read from the store tables unchanged; an act is made once per row. A dry run
    works on throwaway copies of `acts.jsonl` and `lifecycle.jsonl` so the checks run for real
    and nothing on disk changes."""
    rows = lambda sql: [dict(r) for r in con.execute(sql)]  # noqa: E731
    state_dir = STATE
    if dry_run:
        state_dir = tempfile.mkdtemp(prefix="desk-pull-dry-")
        for name in (desk_acts.ACTS_FILE, desk_acts.LIFECYCLE_FILE):
            src = os.path.join(STATE, name)
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(state_dir, name))
    try:
        return desk_acts.turn_into_acts(
            rows("SELECT * FROM decisions ORDER BY id"), rows("SELECT * FROM edits ORDER BY item_id"),
            rows("SELECT * FROM argument_lines ORDER BY item_id"), rows("SELECT rowid, * FROM reviews ORDER BY rowid"),
            {i["id"]: i for i in repo.load_items()}, streams, state_dir, guard=guard)
    finally:
        if dry_run:
            shutil.rmtree(state_dir, ignore_errors=True)


def pull(con, dry_run=False, verbose=True, guard=None):
    streams = item_streams()
    decisions, edits, args_ = pull_decisions(con, streams), pull_edits(con, streams), pull_arguments(con, streams)
    write_json(os.path.join(STATE, "decisions.json"), decisions, dry_run)
    write_json(os.path.join(STATE, "edits.json"), edits, dry_run)
    write_json(os.path.join(STATE, "arguments.json"), args_, dry_run)
    made = pull_acts(con, decisions, edits, args_, streams, dry_run, guard)
    reviews = pull_reviews(con, dry_run, streams)
    if not dry_run:
        meta_set(con, "last_pull", utcnow())
        con.commit()
    if verbose:
        what = (f"{len(decisions)} decisions · {len(edits)} edits · {len(args_)} argument lines · "
                f"{len(reviews)} standing review{'' if len(reviews) == 1 else 's'} to memory · "
                f"{len(made)} new act{'' if len(made) == 1 else 's'}")
        print(("pull (dry run) " if dry_run else "pull ") + what)
        for r in reviews:
            print(f"  review {r['item_id']} ({r['stream'] or 'no stream'}) -> {os.path.relpath(r['target'], REPO_ROOT)}")
        for m in made:
            print(f"  act {m['kind']} {m['target']}: {m['outcome']}")
    return {"decisions": decisions, "edits": edits, "arguments": args_, "reviews": reviews, "acts": made}


# -------------------------------------------------------------------- the CLI


def main(argv=None):
    ap = argparse.ArgumentParser(description="move engine state into the desk database and Alpha's acts back out")
    ap.add_argument("--push", action="store_true", help="engine state -> desk.db")
    ap.add_argument("--pull", action="store_true", help="Alpha's acts -> state/*.json and memory")
    ap.add_argument("--init", action="store_true", help="create the tables and stop")
    ap.add_argument("--dry-run", action="store_true", help="say what --pull would write, write nothing")
    ap.add_argument("--db", default=DB_PATH, help=f"database file (default {DB_PATH})")
    a = ap.parse_args(argv)
    if not (a.push or a.pull or a.init):
        ap.error("nothing to do: pass --push, --pull or --init")
    if not os.path.isdir(DESK) and not _has_desk_tables(a.db):
        # the desk is an optional module of the instance; with neither it nor a database holding
        # its tables there is no act to carry out and no mirror to fill (one that has them is pulled)
        print(f"no desk in this instance ({os.path.relpath(DESK, REPO_ROOT)}) and no desk tables in "
              f"{os.path.basename(a.db)}: nothing to pull or push")
        return 0

    con = connect(a.db)
    try:
        created = ensure_schema(con)
        if created:
            print(f"created the desk schema in {a.db}")
        if a.init and not (a.push or a.pull):
            return 0
        # Pull before push, always. A push replaces the mirror tables from the
        # notes, and an act Alpha made against the rows it is about to replace
        # should be on disk in state/ before that happens.
        if a.pull:
            pull(con, dry_run=a.dry_run)
        if a.push:
            push(con)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
