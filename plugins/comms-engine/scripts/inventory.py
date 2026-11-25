#!/usr/bin/env python3
"""
inventory.py - keep `.atelier/memory/handles.md` current, on a schedule.

The deck asks for a "theme, partner and handles inventory kept current"
(`Principles` s5, Beta 2). The inventory is `.atelier/memory/handles.md` - the
one table both runtimes read - and this script is the half of "kept current"
that a machine can do: confirm that a recorded X handle still resolves, stamp
the row's `last_verified`, and hand everything else to a person.

**One threshold governs both the flag and the spend.** A row is stale when its
`last_verified` is more than WINDOW_DAYS old, or is `-` because the status was
never established. The paid profile check is made for stale rows only, so the
bill lands at roughly one profile lookup per handle per month rather than one per
handle per cycle. A second run inside the window makes no call at all: the
first run wrote today's date onto the rows it confirmed, and they are no longer
stale.

**A handle that changed is due whatever its date says.** `last_verified` records
when a *status* was established, so a handle edited or added after that date has
a date that refers to something else. `state/inventory-ledger.json` carries the
handle string this script last saw per row, and a row whose handle no longer
matches is checked again. The ledger is run state, in the family of
`decisions.json` and `edits.json`; it is not a second inventory, and no
`inventory.json` exists (milestone 1, "Partner and handles inventory").

**LinkedIn slugs stay manual.** No LinkedIn actor is called here, not even under
`--force-all`: harvestapi bills about sixteen times the X rate per item and a
company slug is a fact a person establishes once, not a thing to poll. LinkedIn
rows, and every row whose handle cell is blank, are reported for Alpha instead.
A blank own LinkedIn slug is routed that way by design - the engine has no
authority to establish it, so it asks rather than guesses.

Writing back is surgical: only the `status` and `last_verified` cells of a row
this run actually confirmed are rewritten, and every other byte of the file is
left as it stands, because agents and a person read the same file.
No row is ever added or removed here - a partner is never added without Alpha -
and a status is never downgraded. `collect` becomes `verified` only when every
non-blank handle the row records has been confirmed; a row that still carries a
manual LinkedIn slug keeps its status and is reported.

Usage:
  python3 inventory.py                # check the stale rows, write the dates back
  python3 inventory.py --dry-run      # print what would be checked, call nothing
  python3 inventory.py --force-all    # deliberate full sweep of every X handle
  python3 inventory.py --window 45    # a different staleness window, this run only

Key: resolved by scripts/secrets.py - TWITTERAPI_IO_API_KEY in the
environment, else the macOS keychain item (the brand's service, engine.json).

Cost: one twitterapi.io profile lookup per row checked (decision 2026-10-26:
every read of X goes through twitterapi.io), USD 0.00018 a profile at this
volume. The lookup answers definitely: a handle that does not exist and a
suspended account both come back as such, and both stay inconclusive here,
routed to a person rather than written. Nothing here posts, and nothing here
adds a partner.
"""
import argparse
import datetime as dt
import json
import os
import sys

import memory

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
STATE = paths.state()
LEDGER = os.path.join(STATE, "inventory-ledger.json")

WINDOW_DAYS = 30
PROFILE_SOURCE = "twitterapi.io user/info"

BLANK = ("", "collect", "-", "—")

# The three tables of the inventory, each named by its `##` heading in
# handles.md, with the columns that identify a row and the handle columns the
# row carries. `platform` on `own channels` is an identity column because the
# brand holds one row per platform; a partner holds both handles on one row.
# A heading is matched as a prefix, so a stream's file may qualify it
# (`cleared partners (public via Acme's own releases)`).
TABLES = [
    {
        "heading": "own channels",
        "identity": ("brand", "platform"),
        "party": "brand",
        "handles": [("", "handle")],          # platform comes from the row itself
        "clearance": "own channel",
    },
    {
        "heading": "cleared partners",
        "identity": ("partner",),
        "party": "partner",
        "handles": [("X", "x"), ("LinkedIn", "linkedin")],
        "clearance": None,                    # the row's own `clearance` cell
    },
    {
        "heading": "standards bodies (cite, never claim)",
        "identity": ("body",),
        "party": "body",
        "handles": [("X", "x")],
        "clearance": "cite only, never a partner",
    },
]


class InventoryError(RuntimeError):
    """The inventory did not read or write as expected. Never guessed around."""


# --- reading ----------------------------------------------------------------

def _blank(cell):
    return (cell or "").strip().lower() in BLANK


def parse_date(cell):
    """The `last_verified` cell as a date, or None where it was never set."""
    cell = (cell or "").strip()
    if cell in ("", "-", "—"):
        return None
    try:
        return dt.date.fromisoformat(cell)
    except ValueError:
        return None


def is_stale(last_verified, today=None, window_days=WINDOW_DAYS):
    """Whether a row is past the window. A row that was never verified always is."""
    d = parse_date(last_verified)
    if d is None:
        return True
    return ((today or dt.date.today()) - d).days > window_days


def inventory_rows(handles_path=None, today=None, window_days=WINDOW_DAYS):
    """Every inventory row, flat, carrying the staleness flag this script acts on.

    One record per row of the three tables in `handles.md`, in file order, with
    its handles as a list so a caller renders own channels, partners and
    standards bodies through one shape. `stale` is computed here and nowhere
    else: the desk shows the same flag the refresh acts on, from one threshold.
    """
    path = handles_path or memory.HANDLES_MD
    text = memory._read(path)
    today = today or dt.date.today()
    out = []
    for spec in TABLES:
        for row in memory.table_in(text, spec["heading"], prefix=True):
            party = row.get(spec["party"], "")
            handles = []
            for platform, col in spec["handles"]:
                handles.append({
                    "platform": platform or row.get("platform", ""),
                    "handle": (row.get(col) or "").strip(),
                    "column": col,
                })
            last_verified = (row.get("last_verified") or "").strip()
            out.append({
                "table": spec["heading"],
                "party": party,
                "identity": {c: row.get(c, "") for c in spec["identity"]},
                "handles": handles,
                "clearance": spec["clearance"] or row.get("clearance", ""),
                "scope": row.get("scope on record", ""),
                "status": (row.get("status") or "").strip(),
                "themes": (row.get("themes") or "").strip(),
                "last_verified": last_verified,
                "stale": is_stale(last_verified, today, window_days),
                "note": row.get("note", ""),
            })
    return out


def row_key(row, handle=None):
    """A stable key for the ledger: the table plus the row's identity cells."""
    ident = "/".join(row["identity"][c] for c in sorted(row["identity"]))
    base = f"{row['table']}|{ident}"
    return f"{base}|{handle['platform']}" if handle else base


# --- what is due ------------------------------------------------------------

def plan(rows, ledger, force_all=False, today=None, window_days=WINDOW_DAYS):
    """Split the inventory into what gets a paid call and what goes to a person.

    Checkable means an X handle that is actually recorded: LinkedIn is manual by
    decision, a website row is not a profile, and a blank cell is a value the
    engine has no authority to establish. Of the checkable rows, one is due when
    its row is stale, or when its handle is not the one the ledger last saw -
    a handle added or edited since the last run has a date that refers to a
    different value.
    """
    due, fresh, manual = [], [], []
    for row in rows:
        for h in row["handles"]:
            platform = (h["platform"] or "").strip().lower()
            target = {
                "key": row_key(row, h),
                "party": row["party"],
                "platform": h["platform"],
                "handle": h["handle"],
                "column": h["column"],
                "row": row,
            }
            if platform not in ("x", "linkedin"):
                continue                      # a website row is not a profile
            if _blank(h["handle"]):
                manual.append(dict(target, reason="no handle recorded - a person collects "
                                                  "it; the engine does not guess one"))
                continue
            if platform == "linkedin":
                manual.append(dict(target, reason="LinkedIn slugs stay manual - no LinkedIn "
                                                  "actor is called here, forced or not"))
                continue
            seen = ledger.get("rows", {}).get(target["key"])
            # No ledger entry means no previous run saw this row, not that the
            # handle changed: the recorded date is then the only authority, and
            # a first run checks exactly the rows that date calls stale.
            changed = seen is not None and seen.get("handle") != h["handle"]
            if force_all or row["stale"] or changed:
                target["why"] = ("forced full sweep" if force_all and not (row["stale"] or changed)
                                 else "handle added or edited since the last run" if changed and not row["stale"]
                                 else "never verified" if parse_date(row["last_verified"]) is None
                                 else f"last verified {row['last_verified']}, past the {window_days}-day window")
                due.append(target)
            else:
                fresh.append(dict(target, why=f"last verified {row['last_verified']}"))
    return due, fresh, manual


# --- the paid check ---------------------------------------------------------

def _default_call(name):
    """The one place a paid call is made: twitterapi.io's profile lookup."""
    import twitterapi
    return twitterapi.user_info(twitterapi.load_key(), name)


def check_x_handle(handle, call=None):
    """Does this X handle resolve? `confirmed`, `inconclusive` or `error`.

    One profile lookup per handle. `confirmed` only when the profile comes back
    under the same handle; a handle that does not exist, a suspended account or
    a profile under another name is `inconclusive`, which writes nothing and
    goes to a person: whether a partner changed handle is not the engine's to
    decide.
    """
    name = handle.strip().lstrip("@")
    try:
        state, data = (call or _default_call)(name)
    except Exception as e:                                    # noqa: BLE001
        return "error", f"{type(e).__name__}: {e}"
    if state == "found":
        got = str((data or {}).get("userName") or "").strip().lstrip("@")
        if got.lower() == name.lower():
            return "confirmed", f"@{got}"
        return "inconclusive", f"the lookup returned @{got or '?'}, not @{name}"
    if state == "not found":
        return "inconclusive", "twitterapi.io: no such handle"
    return "inconclusive", f"twitterapi.io: account {data}"


# --- writing back -----------------------------------------------------------

def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def set_cells(handles_path, updates):
    """Rewrite named cells on named rows of `handles.md`, and nothing else.

    `updates` is a list of `(heading, identity_dict, {column: value})`. Only a
    row whose identity cells all match is touched, only the named columns on it
    change, and a row whose cells already carry those values is left byte for
    byte as it was. Returns the number of lines actually rewritten.
    """
    with open(handles_path, encoding="utf-8") as f:
        lines = f.read().split("\n")

    wanted = []
    for heading, identity, cols in updates:
        wanted.append((heading.strip().lower(), {k.lower(): v for k, v in identity.items()}, cols))

    heading = ""
    header = None
    written = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("## "):
            heading, header = s[3:].strip().lower(), None
            continue
        if not (s.startswith("|") and s.endswith("|")):
            header = None
            continue
        cells = _cells(s)
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if all(set(c) <= set(":-") and c for c in cells if c):
            continue
        if len(cells) != len(header):
            raise InventoryError(f"{handles_path}:{i+1}: {len(cells)} cells under a "
                                 f"{len(header)}-column header - refusing to write")
        row = dict(zip(header, cells))
        for h, identity, cols in wanted:
            if heading != h and not heading.startswith(h + " "):
                continue
            if any(row.get(k, "").strip() != v.strip() for k, v in identity.items()):
                continue
            new = list(cells)
            changed = False
            for col, value in cols.items():
                if col.lower() not in header:
                    raise InventoryError(f"{handles_path}: no '{col}' column under '## {h}'")
                j = header.index(col.lower())
                if new[j] != value:
                    new[j] = value
                    changed = True
            if changed:
                lines[i] = "| " + " | ".join(new) + " |"
                written += 1
    with open(handles_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return written


def status_after(row, confirmed_platforms):
    """The status a row may carry once this run's confirmations are in.

    A status is never downgraded, and `collect` becomes `verified` only when the
    row has no non-blank handle left unconfirmed. A partner row still carrying a
    manual LinkedIn slug therefore keeps `collect` and is reported: the engine
    confirmed one of the two handles, and saying otherwise would license a tag
    on the half it never checked.
    """
    if row["status"].strip().lower() == "verified":
        return "verified"
    for h in row["handles"]:
        if _blank(h["handle"]):
            continue
        if h["platform"] not in confirmed_platforms:
            return row["status"]
    return "verified" if confirmed_platforms else row["status"]


# --- the ledger -------------------------------------------------------------

def load_ledger(path=None):
    p = path or LEDGER
    if not os.path.exists(p):
        return {"rows": {}}
    with open(p, encoding="utf-8") as f:
        led = json.load(f)
    led.setdefault("rows", {})
    return led


def save_ledger(ledger, path=None):
    p = path or LEDGER
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=1, ensure_ascii=False)


# --- the run ----------------------------------------------------------------

def log_run(report, runs_path=None):
    """One `inventory` entry in state/runs.json, in the shape the desk reads."""
    p = runs_path or os.path.join(STATE, "runs.json")
    runs = []
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            runs = json.load(f)
    now = dt.datetime.now(dt.timezone.utc)
    runs.append({
        "run_id": now.strftime("%Y%m%dT%H%M%SZ"),
        "step": "inventory",
        "stream": memory.DEFAULT_STREAM_NAME,
        "at": now.isoformat(timespec="seconds"),
        "detail": (f"inventory-refresh: {report['rows']} rows, {report['calls']} paid checks "
                   f"({report['confirmed']} confirmed, {report['inconclusive']} inconclusive, "
                   f"{len(report['errors'])} errors), {len(report['fresh'])} inside the "
                   f"{report['window_days']}-day window, {len(report['manual'])} for Alpha"),
    })
    with open(p, "w", encoding="utf-8") as f:
        json.dump(runs, f, indent=1, ensure_ascii=False)


def run(force_all=False, dry_run=False, window_days=WINDOW_DAYS, today=None,
        handles_path=None, ledger_path=None, call=None, log=True, out=print):
    """One refresh. Returns the report; prints it through `out`."""
    handles_path = handles_path or memory.HANDLES_MD
    today = today or dt.date.today()
    rows = inventory_rows(handles_path, today=today, window_days=window_days)
    ledger = load_ledger(ledger_path)
    due, fresh, manual = plan(rows, ledger, force_all=force_all, today=today,
                              window_days=window_days)

    report = {
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "window_days": window_days,
        "force_all": force_all,
        "dry_run": dry_run,
        "rows": len(rows),
        "due": [{k: t[k] for k in ("party", "platform", "handle", "why")} for t in due],
        "fresh": [{k: t[k] for k in ("party", "platform", "handle", "why")} for t in fresh],
        "manual": [{k: t[k] for k in ("party", "platform", "handle", "reason")} for t in manual],
        "calls": 0,
        "confirmed": 0,
        "inconclusive": 0,
        "errors": [],
        "written": [],
    }

    out(f"inventory: {len(rows)} rows, window {window_days} days"
        f"{' (FORCED full sweep)' if force_all else ''}"
        f"{' - dry run, nothing is called and nothing is written' if dry_run else ''}")
    for t in fresh:
        out(f"  fresh      {t['party']:<28} {t['platform']:<9} {t['handle']:<22} {t['why']}")
    for t in manual:
        out(f"  for Alpha  {t['party']:<28} {t['platform']:<9} "
            f"{(t['handle'] or '(blank)'):<22} {t['reason']}")
    for t in due:
        out(f"  due        {t['party']:<28} {t['platform']:<9} {t['handle']:<22} {t['why']}")
    # One handle, one call. A second stream's X handle can be recorded on two rows,
    # its own channel and its cleared-partner row, and paying twice to ask the same
    # question of the same profile is spend the threshold was meant to stop.
    distinct = []
    for t in due:
        name = t["handle"].strip().lstrip("@").lower()
        if name not in distinct:
            distinct.append(name)
    if dry_run:
        out(f"  would make {len(distinct)} twitterapi.io profile lookup(s) for {len(due)} row(s); "
            f"0 LinkedIn calls, always.")
        return report

    answers = {}
    for name in distinct:
        answers[name] = check_x_handle(name, call=call)
        report["calls"] += 1

    confirmed_by_row = {}
    checked = {}
    for t in due:
        name = t["handle"].strip().lstrip("@").lower()
        result, detail = answers[name]
        checked[t["key"]] = result
        out(f"  checked    {t['party']:<28} {t['platform']:<9} {t['handle']:<22} {result} ({detail})")
        if result == "confirmed":
            report["confirmed"] += 1
            k = row_key(t["row"])
            confirmed_by_row.setdefault(k, {"row": t["row"], "platforms": set()})
            confirmed_by_row[k]["platforms"].add(t["platform"])
        elif result == "error":
            report["errors"].append({"party": t["party"], "handle": t["handle"], "detail": detail})
        else:
            report["inconclusive"] += 1

    # What this run saw, recorded for every checkable row and not only the
    # checked ones: the next run compares against it to spot a handle a person
    # added or edited in between, which is due whatever its date says.
    for t in due + fresh:
        prev = ledger["rows"].get(t["key"], {})
        ledger["rows"][t["key"]] = {
            "handle": t["handle"],
            "seen_at": str(today),
            "result": checked.get(t["key"], prev.get("result", "")),
            "checked_at": str(today) if t["key"] in checked else prev.get("checked_at", ""),
        }

    updates = []
    for entry in confirmed_by_row.values():
        row = entry["row"]
        cols = {"last_verified": str(today)}
        after = status_after(row, entry["platforms"])
        if after != row["status"]:
            cols["status"] = after
        updates.append((row["table"], row["identity"], cols))
        report["written"].append({"party": row["party"], "last_verified": str(today),
                                  "status": cols.get("status", row["status"])})
    if updates:
        n = set_cells(handles_path, updates)
        out(f"  wrote      {n} row(s) in {os.path.relpath(handles_path, os.path.dirname(ENGINE))}")
    save_ledger(ledger, ledger_path)
    if log:
        log_run(report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="print what is due and call nothing")
    ap.add_argument("--force-all", action="store_true",
                    help="check every recorded X handle regardless of its date. LinkedIn is "
                         "never called, forced or not.")
    ap.add_argument("--window", type=int, default=WINDOW_DAYS,
                    help=f"staleness window in days (default {WINDOW_DAYS})")
    args = ap.parse_args()
    try:
        report = run(force_all=args.force_all, dry_run=args.dry_run, window_days=args.window)
    except (memory.SharedMemoryError, InventoryError) as e:
        sys.exit(f"inventory.py: {e}")
    if report["errors"]:
        sys.exit(f"inventory.py: {len(report['errors'])} handle check(s) failed")


if __name__ == "__main__":
    main()
