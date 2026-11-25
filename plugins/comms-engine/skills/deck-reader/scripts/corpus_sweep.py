#!/usr/bin/env python3
"""Sweep the strategy corpus and report where every source stands.

Walks every folder under the corpus root (engine.json corpus.root, or --root), fingerprints each file, and
tracks it through four stages:

  unread    nothing in the repo reads it
  read      Decks/**/<name>/narrative.md or Docs/Research/sources/<stem>.md
            exists and is newer than the source (or a --mark-read pointer)
  analysed  a research brief in Docs/Research/ covers it (--mark-brief, or
            --mark-read --as <brief>)
  applied   that brief's proposed memory edits were carried into
            .atelier/memory/ (--mark-applied <brief>)

and classifies each file as new / changed / unchanged / gone since the last
sweep. A changed source drops back to `stale` and must be read again.

Nothing here touches `.atelier/memory/`. The sweep says what to do next; the
commands /corpus-read, /corpus-analyse and /corpus-update do it, and the claim
gate relies on status.md only ever tightening, so the last step stays reviewed.

Usage
  corpus_sweep.py                       # report only, writes nothing
  corpus_sweep.py --write               # also record manifest.json and sweep.md
  corpus_sweep.py --only-todo           # just the to-do tables
  corpus_sweep.py --json                # machine-readable rows
  corpus_sweep.py --mark-read  "<rel>" --as "<repo path>"   # reading lives elsewhere
  corpus_sweep.py --mark-brief "<rel>" --as "Docs/Research/<brief>.md"
  corpus_sweep.py --mark-applied "Docs/Research/<brief>.md"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _default_root() -> Path:
    """engine.json's corpus.root through config.py when it imports, else the
    template's placeholder under this home; no machine is named either way.
    `engine.py setup corpus --root <dir>` is what sets the real one."""
    try:
        sys.path.insert(0, str(REPO / "Tooling" / "social-engine" / "scripts"))
        import config  # noqa: WPS433

        root = config.cfg("corpus.root", "")
        if root:
            return Path(root)
    except Exception:  # a checkout without the engine: the shipped path
        pass
    return Path.home() / "Documents" / "Strategy"


DEFAULT_ROOT = _default_root()
DECKS = REPO / "Decks"
SOURCES = REPO / "Docs" / "Research" / "sources"
# Docs/Research/ is gitignored on purpose: source file names alone name stealth
# partners, so the manifest lives beside the other internal-only syntheses.
STATE_DIR = REPO / "Docs" / "Research" / "_corpus"
MANIFEST = STATE_DIR / "manifest.json"
REPORT = STATE_DIR / "sweep.md"

READABLE = {".pptx", ".pdf", ".docx", ".xlsx", ".html", ".htm", ".txt", ".md", ".key"}
SLIDES = {".pptx", ".key"}
SKIP_NAMES = {".DS_Store", "desktop.ini"}
KEEP = ("sha256", "size", "mtime", "kind", "read", "reading", "read_as", "brief", "applied", "stage")


def _probe_pdf(path: Path) -> str:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from extract_doc import probe  # noqa: WPS433

        return probe(path)
    except Exception:  # pdfplumber missing or a broken PDF: fall back to prose
        return "prose"


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat(timespec="minutes")


def walk(root: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            if fn in SKIP_NAMES or fn.startswith("~$") or fn.startswith("."):
                continue
            out.append(Path(dirpath) / fn)
    return out


def find_reading(stem: str, read_as: str | None) -> Path | None:
    """Locate the repo's reading of a source, if any."""
    if read_as:
        p = REPO / read_as
        return p if p.exists() else None
    for cand in (DECKS / stem / "narrative.md", *DECKS.glob(f"*/{stem}/narrative.md")):
        if cand.exists():
            return cand
    cand = SOURCES / f"{stem}.md"
    if cand.exists():
        return cand
    return None


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {"root": str(DEFAULT_ROOT), "swept_at": None, "files": {}}


def save_manifest(m: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")


def sweep(root: Path, prev: dict) -> list[dict]:
    prev_files: dict = prev.get("files", {})
    rows: list[dict] = []
    seen: set[str] = set()
    for path in walk(root):
        rel = str(path.relative_to(root))
        seen.add(rel)
        st = path.stat()
        digest = sha256(path)
        old = prev_files.get(rel) or {}
        if not old:
            change = "new"
        elif old.get("sha256") != digest:
            change = "changed"
        else:
            change = "unchanged"

        read_as = old.get("read_as")
        brief = old.get("brief")
        applied = old.get("applied")
        # a source that changed since its brief was written needs the whole
        # chain again: reading, analysis, update.
        if change == "changed":
            read_as = brief = applied = None

        # slides or prose: by extension, except PDFs, which the probe settles
        # (landscape pages or sparse text = slides). Reuse the previous answer
        # while the file is unchanged.
        if path.suffix.lower() == ".pdf":
            kind = old.get("kind") if change == "unchanged" and old.get("kind") else _probe_pdf(path)
        else:
            kind = "slides" if path.suffix.lower() in SLIDES else "prose"

        reading = find_reading(path.stem, read_as)
        if reading is None:
            read = "unread"
        elif reading.stat().st_mtime >= st.st_mtime:
            read = "read"
        else:
            read = "stale"

        if read != "read":
            stage = read  # unread | stale
        elif applied:
            stage = "applied"
        elif brief and (REPO / brief).exists():
            stage = "analysed"
        else:
            stage = "read"

        rows.append(
            {
                "path": rel,
                "folder": str(Path(rel).parent) if Path(rel).parent != Path(".") else "",
                "ext": path.suffix.lower(),
                "kind": kind,
                "size": st.st_size,
                "mtime": iso(st.st_mtime),
                "sha256": digest,
                "change": change,
                "read": read,
                "reading": str(reading.relative_to(REPO)) if reading else None,
                "read_as": read_as,
                "brief": brief,
                "applied": applied,
                "stage": stage,
                "readable": path.suffix.lower() in READABLE,
            }
        )
    for rel, old in prev_files.items():
        if rel not in seen:
            rows.append({**old, "path": rel, "change": "gone", "stage": old.get("stage", "unread")})
    return rows


def live(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["change"] != "gone"]


def todo_read(rows):      return [r for r in live(rows) if r["stage"] in ("unread", "stale")]
def todo_analyse(rows):   return [r for r in live(rows) if r["stage"] == "read"]
def todo_apply(rows):     return [r for r in live(rows) if r["stage"] == "analysed"]


def render_table(rows: list[dict], extra: str | None = None) -> str:
    head = "| folder | file | kind | modified | change | stage |"
    sep = "|---|---|---|---|---|---|"
    if extra:
        head += f" {extra} |"
        sep += "---|"
    lines = [head, sep]
    for r in rows:
        name = Path(r["path"]).name
        line = (
            f"| {r.get('folder') or '.'} | {name} | {r.get('kind','')} | {r.get('mtime','')[:10]} | "
            f"{r['change']} | {r['stage']} |"
        )
        if extra:
            line += f" {r.get(extra) or '—'} |"
        lines.append(line)
    return "\n".join(lines) if rows else "_none_"


def render_report(root: Path, rows: list[dict], when: str) -> str:
    lv = live(rows)
    stages = {k: sum(1 for r in lv if r["stage"] == k) for k in ("unread", "stale", "read", "analysed", "applied")}
    changes = {k: sum(1 for r in rows if r["change"] == k) for k in ("new", "changed", "unchanged", "gone")}
    out = [
        f"# corpus sweep — {when}",
        "",
        f"root: `{root}`",
        "",
        f"files: {len(lv)} · unread {stages['unread']} · stale {stages['stale']} · "
        f"read {stages['read']} · analysed {stages['analysed']} · applied {stages['applied']}",
        f"since last sweep: new {changes['new']} · changed {changes['changed']} · "
        f"unchanged {changes['unchanged']} · gone {changes['gone']}",
        "",
        "## 1. needs reading  →  /corpus-read",
        "",
        render_table(todo_read(rows)),
        "",
        "## 2. needs analysis  →  /corpus-analyse",
        "",
        render_table(todo_analyse(rows), extra="reading"),
        "",
        "## 3. needs memory update  →  /corpus-update",
        "",
        render_table(todo_apply(rows), extra="brief"),
        "",
        "## everything",
        "",
        render_table(rows, extra="brief"),
        "",
    ]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--write", action="store_true", help="record manifest.json and sweep.md")
    ap.add_argument("--only-todo", action="store_true", help="print only the to-do tables")
    ap.add_argument("--json", action="store_true", help="print rows as JSON")
    ap.add_argument("--mark-read", metavar="REL", help="source (relative to root) whose reading lives at --as")
    ap.add_argument("--mark-brief", metavar="REL", help="source (relative to root) covered by the brief at --as")
    ap.add_argument("--as", dest="target", metavar="REPO_PATH", help="repo-relative file for --mark-read / --mark-brief")
    ap.add_argument("--mark-applied", metavar="BRIEF", help="brief whose edits are now in .atelier/memory/")
    args = ap.parse_args()

    root: Path = args.root
    if not root.is_dir():
        print(f"root not found: {root}", file=sys.stderr)
        return 2

    prev = load_manifest()
    files = prev.setdefault("files", {})

    def need_target() -> str:
        if not args.target:
            ap.error("--mark-read / --mark-brief need --as <repo path>")
        if not (REPO / args.target).exists():
            ap.error(f"no such file in repo: {args.target}")
        return args.target

    def need_source(rel: str) -> dict:
        if not (root / rel).exists():
            ap.error(f"no such source under root: {rel}")
        return files.setdefault(rel, {})

    if args.mark_read:
        t = need_target()
        e = need_source(args.mark_read)
        e["read_as"] = t
        if t.startswith("Docs/Research/") and "/sources/" not in t:
            e["brief"] = t  # a brief that reads a source also analyses it
        save_manifest(prev)
        print(f"marked read: {args.mark_read} → {t}")
    if args.mark_brief:
        t = need_target()
        e = need_source(args.mark_brief)
        e["brief"] = t
        e.pop("applied", None)
        save_manifest(prev)
        print(f"marked analysed: {args.mark_brief} → {t}")
    if args.mark_applied:
        if not (REPO / args.mark_applied).exists():
            ap.error(f"no such brief: {args.mark_applied}")
        n = 0
        for rel, e in files.items():
            if e.get("brief") == args.mark_applied:
                e["applied"] = date.today().isoformat()
                n += 1
        save_manifest(prev)
        print(f"marked applied: {args.mark_applied} ({n} sources)")
    if args.mark_read or args.mark_brief or args.mark_applied:
        return 0  # a mark is a bookkeeping act; the next sweep picks it up

    rows = sweep(root, prev)
    when = datetime.now().astimezone().isoformat(timespec="minutes")

    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    elif args.only_todo:
        print("## needs reading\n\n" + render_table(todo_read(rows)))
        print("\n## needs analysis\n\n" + render_table(todo_analyse(rows), extra="reading"))
        print("\n## needs memory update\n\n" + render_table(todo_apply(rows), extra="brief"))
    else:
        print(render_report(root, rows, when))

    if args.write:
        manifest = {
            "root": str(root),
            "swept_at": when,
            "files": {r["path"]: {k: r[k] for k in KEEP if k in r} for r in live(rows)},
        }
        save_manifest(manifest)
        REPORT.write_text(render_report(root, rows, when))
        print(f"\nwrote {MANIFEST.relative_to(REPO)} and {REPORT.relative_to(REPO)}", file=sys.stderr)

    return 1 if (todo_read(rows) or todo_analyse(rows) or todo_apply(rows)) else 0


if __name__ == "__main__":
    sys.exit(main())
