#!/usr/bin/env python3
"""
held_theme.py - the one writer of `themes.md` besides `/corpus-update --apply`:
a person's two acts on themes, made on the control page. A person adds a theme,
and it enters at the lowest grade, `held`. A person grades a theme's licence,
allowing it or holding it again, with the reason that lets them.

Why a module of its own: `memory.py` reads memory and writes nothing, and
`ORCHESTRATION.md` §7 names one writer per store. Which themes we have and how
freely we may argue each is a person's decision (`Principles` s5, Alpha
column). This module is where that decision becomes rows, and nothing else
writes them. It never deletes: a new grade replaces the basis cell, and the
status log keeps the grade and the basis it replaced, with the day and where.

What one add writes, in the stream's `themes.md`:

- a row in the theme dictionary (the first table): the hashtag, what it is,
  why it is different, and `—` or `not yet` for what is not known yet;
- a row in `## licence and layer`: layer `proposed`, licence `held`, and a
  basis that says when and where it was added and what `held` allows;
- a dated line in `## theme status log`.

Each row is built from its own table's header, after the table's last filled
row (a template's empty rows stay below it). The file is written whole through
a temp file, read back with `memory.load_themes()`, and put back as it was if
the roster does not read back with the new tag.

Refused: a tag that is not a hashtag, one already a theme (in `themes.md` or in
the extra tags a caller names, such as `themes.json`'s), one on the file's
`## excluded from listening` list, and one that matches a name on the private
denylist. Without the denylist nothing is added: the gate could not check the
theme either.

A grade is one of `licensed` (argue it freely inside voice.md),
`licensed-with-hedge` (only with the cleared wording, which the basis must
quote) or `held` (the general idea only: no capability, initiative, partner or
date of ours). A grade is refused without a reason of a few words, when it is
the grade the theme already has, and for a hashtag that is not a theme.
Allowing a theme does not clear any claim: the gate still refuses a claim that
is not in `claims.md`.

  held_theme.prepare(tag, what, different)        -> (tag, old_text, new_text)   checks only
  held_theme.prepare_grade(tag, licence, basis)   -> (old_text, new_text, was)   checks only
  held_theme.write(old_text, new_text, tag)       -> digest                      writes, reads back
  held_theme.undo(old_text)                                                      puts the file back
"""
import datetime as dt
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memory  # noqa: E402

TAG_RE = re.compile(r"#[A-Za-z][A-Za-z0-9]{2,39}")
GRADES = ("licensed", "licensed-with-hedge", "held")
QUOTED = re.compile(r'"[^"]{3,}"|“[^”]{3,}”')


class Refused(ValueError):
    """A theme that may not be added, said in one line for the person."""


def path(stream=None):
    return memory.paths(stream)["themes_md"]


def _cell(value, most, name, required=True):
    value = " ".join(str(value or "").split())
    if "|" in value:
        raise Refused(f"{name}: a | would break the table; write it without one")
    if required and not value:
        raise Refused(f"{name} is needed")
    if len(value) > most:
        raise Refused(f"{name}: at most {most} characters")
    return value


def _line_of(text, heading):
    for n, line in enumerate(text.split("\n")):
        if line.strip().lower() == heading:
            return n
    return None


def _insert_row(text, after_line, values):
    """Add a row to the first markdown table at or after line `after_line`, after
    its last filled row, built from the table's own header so the columns line up."""
    lines = text.split("\n")
    i = after_line
    while i < len(lines) - 1 and not (lines[i].lstrip().startswith("|")
                                      and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1])):
        i += 1
    if i >= len(lines) - 1:
        raise Refused("themes.md has no table where one is expected")
    header = [c.strip().lower() for c in lines[i].strip().strip("|").split("|")]
    last, j = i + 1, i + 2
    while j < len(lines) and lines[j].lstrip().startswith("|"):
        if lines[j].strip().strip("|").split("|")[0].strip():
            last = j
        j += 1
    lines.insert(last + 1, "| " + " | ".join(values.get(h, "—") for h in header) + " |")
    return "\n".join(lines)


def normalise(tag):
    tag = str(tag or "").strip()
    if not tag.startswith("#"):
        tag = "#" + tag
    if not TAG_RE.fullmatch(tag):
        raise Refused("a theme is a hashtag: # then a letter, then 2 to 39 letters or digits, no spaces")
    return tag


def prepare(tag, what, different="", today=None, stream=None, also_taken=(), where="the control page"):
    """Check a new theme and build the file it would make. Writes nothing.

    Returns (tag, old_text, new_text)."""
    tag = normalise(tag)
    today = today or dt.date.today().isoformat()
    what = _cell(what, 220, "What it is")
    different = _cell(different, 300, "Why it is ours", required=False)
    md_path = path(stream)
    with open(md_path, encoding="utf-8") as f:
        md = f.read()
    roster = {t["tag"].lower() for t in memory.load_themes(stream)} | {str(t).lower() for t in also_taken}
    if tag.lower() in roster:
        raise Refused(f"{tag} is a theme already")
    excluded = _line_of(md, "## excluded from listening")
    if excluded is not None:
        section = md.split("\n")[excluded:]
        end = next((n for n, line in enumerate(section[1:], 1) if line.startswith("## ")), len(section))
        if tag.lower() in "\n".join(section[:end]).lower():
            raise Refused(f"{tag} is on themes.md's excluded-from-listening list")
    try:
        deny = memory.denylist(stream)
    except Exception:  # noqa: BLE001 - no denylist, no new theme: the gate cannot check it either
        raise Refused("the private denylist cannot be read; restore handles.private.md first")
    bare = tag[1:].lower()
    if any(t and (t.lower().replace(" ", "") in bare or bare in t.lower().replace(" ", "")) for t in deny):
        raise Refused(f"{tag} matches a name on the private denylist")

    licence_at = _line_of(md, "## licence and layer")
    if licence_at is None:
        raise Refused("themes.md has no '## licence and layer' table")
    new = _insert_row(md, licence_at, {
        "hashtag": tag, "layer": "proposed", "licence": "held", "logics": "—",
        "licence basis": f"Added on {where} on {today}. Held until a person grades it against "
                         "status.md: argue the general idea only, never what we do, a partner or a date."})
    new = _insert_row(new, 0, {"hashtag": tag, "what it is": what, "why it is different": different or "—",
                               "fact it links back to": "—", "partner tags": "—", "intro post": "not yet"})
    log_at = _line_of(new, "## theme status log")
    if log_at is not None:
        lines = new.split("\n")
        end = next((n for n in range(log_at + 1, len(lines)) if lines[n].startswith("## ")), len(lines))
        while end > log_at + 1 and not lines[end - 1].strip():
            end -= 1
        lines.insert(end, f"- {today} — {tag} added on {where} as held, with its X search; "
                          "a person grades its licence against status.md.")
        new = "\n".join(lines)
    return tag, md, new


def _table_rows(lines, start):
    """The header and the filled rows of the first markdown table at or after
    line `start`, as (header cells, [(line number, cells)])."""
    i = start
    while i < len(lines) - 1 and not (lines[i].lstrip().startswith("|") and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1])):
        i += 1
    if i >= len(lines) - 1:
        raise Refused("themes.md has no licence table where one is expected")
    header = [c.strip().lower() for c in lines[i].strip().strip("|").split("|")]
    rows, j = [], i + 2
    while j < len(lines) and lines[j].lstrip().startswith("|"):
        cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
        if cells and cells[0]:
            rows.append((j, cells))
        j += 1
    return header, rows


def prepare_grade(tag, licence, basis, today=None, stream=None, where="the control page"):
    """Check a person's grade of one theme's licence and build the file it would
    make. Writes nothing. Returns (old_text, new_text, the grade it replaces)."""
    tag = normalise(tag)
    licence = str(licence or "").strip()
    if licence not in GRADES:
        raise Refused(f"a grade is one of: {', '.join(GRADES)}")
    basis = _cell(basis, 400, "Why")
    if len(basis) < 15:
        raise Refused("Why: say in a few words what lets us, such as the status.md line, the claim or the source")
    if licence == "licensed-with-hedge" and not QUOTED.search(basis):
        raise Refused('careful wording: put the exact words we may use in quotes, such as "is in the process of"')
    today = today or dt.date.today().isoformat()
    md_path = path(stream)
    with open(md_path, encoding="utf-8") as f:
        md = f.read()
    at = _line_of(md, "## licence and layer")
    if at is None:
        raise Refused("themes.md has no '## licence and layer' table")
    lines = md.split("\n")
    header, rows = _table_rows(lines, at)
    if "licence" not in header or "licence basis" not in header:
        raise Refused("the licence table has no licence or licence basis column")
    li, bi = header.index("licence"), header.index("licence basis")
    hit = next(((n, cells) for n, cells in rows if cells[0].lower() == tag.lower()), None)
    if not hit:
        raise Refused(f"{tag} is not a theme in themes.md")
    n, cells = hit
    cells = cells + [""] * (len(header) - len(cells))
    was, was_basis = cells[li], cells[bi]
    if was == licence:
        raise Refused(f"{tag} is {licence} already")
    cells[li] = licence
    cells[bi] = f"{basis} (Graded {licence} on {where} on {today}; it was {was}.)"
    lines[n] = "| " + " | ".join(cells) + " |"
    new = "\n".join(lines)
    log_at = _line_of(new, "## theme status log")
    if log_at is not None:
        lines = new.split("\n")
        end = next((k for k in range(log_at + 1, len(lines)) if lines[k].startswith("## ")), len(lines))
        while end > log_at + 1 and not lines[end - 1].strip():
            end -= 1
        before = " ".join(was_basis.split()) or "none given"
        lines.insert(end, f"- {today} — {tag}: licence {was} → {licence}, by a person on {where}. Why: {basis} "
                          f"Basis before: {before}")
        new = "\n".join(lines)
    return md, new, was


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def write(old, new, tag, stream=None, licence=None):
    """Write the file `prepare` or `prepare_grade` built, if the file is still
    the one it read; read it back, and put it back as it was if the tag (with
    its new `licence`, for a grade) does not read."""
    md_path = path(stream)
    with open(md_path, encoding="utf-8") as f:
        if f.read() != old:
            raise Refused("themes.md changed while this was being saved; reload and try again")
    tmp = f"{md_path}.held-theme-{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
    os.replace(tmp, md_path)
    try:
        read = {t["tag"]: t.get("licence") for t in memory.load_themes(stream)}
        if tag not in read:
            raise Refused("themes.md did not read back with the theme")
        if licence and read[tag] != licence:
            raise Refused(f"themes.md did not read back {tag} as {licence}")
    except Exception:
        undo(old, stream)
        raise
    return digest(new)


def undo(old, stream=None):
    """Put themes.md back as `prepare` read it."""
    with open(path(stream), "w", encoding="utf-8") as f:
        f.write(old)
