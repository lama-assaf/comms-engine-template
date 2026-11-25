#!/usr/bin/env python3
"""
memory.py - the engine's read path into `.atelier/memory/`.

`.atelier/memory/` is the single source for theme and handle data. Nothing
keeps a copy: every script and agent reads it through this module.

What lives where:

  .atelier/memory/streams.md  the registry: one row per stream (one business
                              the engine serves), its memory path, owner
                              state, autopilot rule, guardrails and pair
                              rules. An unknown slug raises, never defaults.
  .atelier/memory/themes.md   the eight hashtags - what each is, why it is
                              different, the fact it links back to, cleared
                              partner tags, intro-post state, and (second
                              table) layer, licence, logics, licence basis
  .atelier/memory/handles.md  own channels, cleared partners, standards bodies;
                              per row a status, the themes it may be tagged on
                              and a last_verified date
  .atelier/memory/gate-rules.json
                              the gate's brand rules as data: status words,
                              cleared hedges, capability verbs, the house-style
                              switches and the announcement flags
  .atelier/memory/formats.json
                              the formats a stream may write in, each with its
                              structure and the channels it fits
  themes.json                 engine-local only: the X search term and keyword
                              set per theme, which no other runtime needs

Nothing here writes. Deciding when a theme changes is a human act
(`Principles` s5, Alpha column); a hashtag not in `themes.md` is not a theme.
A person's new theme (at `held`) and a person's licence grade enter `themes.md`
through `held_theme.py`.

The brand's root stream (engine.json brand.slug, the first row of streams.md)
has its memory at the root of `.atelier/memory/`; every other stream lives
under `.atelier/memory/streams/<slug>/` with the same file set (plan v2,
decision 10). Every loader takes `stream=None`, meaning the root stream, so
the module-level path constants a test may redirect keep working.

Usage as a script - the summary both the dry run and a person can read:

  python3 memory.py                   the root stream
  python3 memory.py --stream <slug>   one stream's rosters
  python3 memory.py --list            the registry
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
REPO = paths.instance()
MEMORY = os.path.join(REPO, ".atelier", "memory")

THEMES_MD = os.path.join(MEMORY, "themes.md")
HANDLES_MD = os.path.join(MEMORY, "handles.md")
HANDLES_PRIVATE_MD = os.path.join(MEMORY, "handles.private.md")
STREAMS_MD = os.path.join(MEMORY, "streams.md")
CLAIMS_MD = os.path.join(MEMORY, "claims.md")
sys.path.insert(0, HERE)
import config as _config  # noqa: E402

#: The root stream: engine.json brand.slug. Its memory is MEMORY itself.
DEFAULT_STREAM = _config.brand()["slug"]
#: The display name notes and records carry for the root stream (brand.name).
DEFAULT_STREAM_NAME = _config.brand()["name"]

#: The register's closed vocabularies (claims.md, "Columns").
CLAIM_GRADES = ("evidenced", "asserted", "intended")
CLAIM_TIERS = ("primary", "institutional", "trade", "social")
CLAIM_CORROBORATION = ("primary", "two-independent", "single", "watching")
#: What a draft may cite: the rest is `watching` or `single` and uncitable.
CITABLE_CORROBORATION = ("primary", "two-independent")


class SharedMemoryError(RuntimeError):
    """Shared memory did not read as expected. Never guessed around."""


# --- markdown table reading -------------------------------------------------

def _read(path):
    if not os.path.exists(path):
        raise SharedMemoryError(f"shared memory file missing: {path}")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _sections(text):
    """Split a markdown file into {heading: body} on its `##` headings."""
    out = {}
    heading = ""
    buf = []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.*?)\s*$", line)
        if m:
            out[heading] = "\n".join(buf)
            heading = m.group(1).strip().lower()
            buf = []
        else:
            buf.append(line)
    out[heading] = "\n".join(buf)
    return out


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_tables(body):
    """Every pipe table in a chunk of markdown, as lists of header-keyed dicts."""
    tables = []
    rows = None
    header = None
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            cells = _cells(s)
            if header is None:
                header = [c.lower() for c in cells]
                rows = []
                continue
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            if len(cells) != len(header):
                raise SharedMemoryError(
                    f"malformed table row under header {header}: {len(cells)} cells, expected "
                    f"{len(header)} - {s}"
                )
            rows.append(dict(zip(header, cells)))
        else:
            if header is not None:
                tables.append(rows)
            header = None
            rows = None
    if header is not None:
        tables.append(rows)
    # A header with no rows is an empty roster, not a missing table: a new
    # stream's files carry the headings and nothing under them yet.
    return tables


def table_in(text, heading, prefix=False):
    """The first table under the `##` heading named, matched case-insensitively.

    With `prefix=True` the first section whose heading starts with `heading`
    is used, so a per-stream file may carry the stream's own name in a heading
    such as `cleared partners (public via Beta's own releases)`.
    """
    sec = _sections(text)
    key = heading.strip().lower()
    if prefix and key not in sec:
        matches = [k for k in sec if k.startswith(key)]
        if len(matches) == 1:
            key = matches[0]
    if key not in sec:
        raise SharedMemoryError(f"no '## {heading}' section found; have: {sorted(k for k in sec if k)}")
    tables = parse_tables(sec[key])
    if not tables:
        raise SharedMemoryError(f"no table under '## {heading}'")
    return tables[0]


# --- streams ----------------------------------------------------------------

def load_streams(path=None):
    """The registry from `streams.md`: `{slug: row}` in file order.

    Each row carries the registry columns plus `guardrails` (the row of the
    second table) and `pair_rules` (the rows of the third table where `from`
    is this slug). A slug present in one table and absent from another is an
    error, never a skip.
    """
    text = _read(path or STREAMS_MD)
    reg = table_in(text, "registry")
    guard = {r["slug"]: r for r in table_in(text, "guardrails")}
    pairs = table_in(text, "pair rules")
    out = {}
    for r in reg:
        slug = r["slug"]
        if slug in out:
            raise SharedMemoryError(f"{STREAMS_MD}: slug {slug!r} listed twice")
        if slug not in guard:
            raise SharedMemoryError(f"{STREAMS_MD}: no guardrails row for {slug!r}")
        row = dict(r)
        row["guardrails"] = {k: v for k, v in guard[slug].items() if k != "slug"}
        row["pair_rules"] = [p for p in pairs if p["from"] == slug]
        out[slug] = row
    extra = sorted(set(guard) - set(out))
    if extra:
        raise SharedMemoryError(f"{STREAMS_MD}: guardrails for unknown stream(s) {extra}")
    for p in pairs:
        for side in ("from", "to"):
            if p[side] not in out:
                raise SharedMemoryError(f"{STREAMS_MD}: pair rule names unknown stream {p[side]!r}")
    return out


def streams(path=None):
    """The registry's slugs, in file order."""
    return list(load_streams(path))


def stream(slug, path=None):
    """One registry row. An unknown slug raises; nothing ever defaults."""
    reg = load_streams(path)
    key = (slug or "").strip().lower()
    if key not in reg:
        raise SharedMemoryError(f"unknown stream {slug!r}; the registry has {list(reg)}")
    return reg[key]


def slug_for(name, path=None):
    """The slug for a stream's display name as notes carry it (`Acme`, `Beta`).

    `Both` is not a stream and raises: an item that serves two streams is split
    before it is drafted (the single-pillar test).
    """
    key = (name or "").strip().lower()
    for slug, row in load_streams(path).items():
        if key in (slug, row["name"].lower()):
            return slug
    raise SharedMemoryError(f"{name!r} is not a stream in the registry")


def stream_dir(slug, path=None):
    """The absolute memory directory of a stream, from its `memory` column."""
    rel = stream(slug, path)["memory"].strip().strip("`")
    return os.path.normpath(os.path.join(REPO, rel))


def may_draft(slug, path=None):
    """Whether a stream may draft at all: owner confirmed and a `voice.md` present.

    `autopilot` says what may leave the queue; this says whether anything may
    enter it (plan decision 11).
    """
    row = stream(slug, path)
    return row["owner"].strip().lower() == "confirmed" and os.path.exists(
        os.path.join(stream_dir(slug, path), "voice.md")
    )


def paths(stream_slug=None):
    """The memory files of a stream. `None` is the root stream through the module constants."""
    if stream_slug in (None, DEFAULT_STREAM):
        return {
            "dir": MEMORY,
            "themes_md": THEMES_MD,
            "handles_md": HANDLES_MD,
            "handles_private_md": HANDLES_PRIVATE_MD,
            "claims_md": CLAIMS_MD,
            "gate_rules_json": os.path.join(MEMORY, GATE_RULES_FILE),
            "formats_json": os.path.join(MEMORY, FORMATS_FILE),
        }
    d = stream_dir(stream_slug)
    return {
        "dir": d,
        "themes_md": os.path.join(d, "themes.md"),
        "handles_md": os.path.join(d, "handles.md"),
        "handles_private_md": os.path.join(d, "handles.private.md"),
        "claims_md": os.path.join(d, "claims.md"),
        "gate_rules_json": os.path.join(d, GATE_RULES_FILE),
        "formats_json": os.path.join(d, FORMATS_FILE),
    }


# --- gate rules ---------------------------------------------------------------

GATE_RULES_FILE = "gate-rules.json"
#: What a stream without a gate-rules.json is held to: no status rule written
#: yet, the standard capability verbs, the house style on.
DEFAULT_CAPABILITY_VERBS = (
    "runs?", "operates?", "issues?", "provides?", "settles?", "checks?", "enforces?", "prevents?",
    "offers?", "delivers?", "verif(?:y|ies)", "processes", "hosts?", "secures?", "connects?",
    "certif(?:y|ies)", "guarantees?")
DEFAULT_HOOK_WORDS = (6, 17)
#: The house-style checks a person may hand from the code to the reviewers (gate_lint.RETIRABLE).
RETIRABLE_RULES = ("hook", "tag line", "cta", "shape")


def _regex(pattern, where):
    if not isinstance(pattern, str) or not pattern.strip():
        raise SharedMemoryError(f"{where}: a pattern must be non-empty text")
    try:
        re.compile(pattern)
    except re.error as e:
        raise SharedMemoryError(f"{where}: {pattern!r} is not a regular expression ({e})")
    return pattern


def _pairs(rows, second, where):
    """`[{"pattern", second}]` as `[(pattern, text)]`, every pattern compiled once to prove it reads."""
    if not isinstance(rows, list):
        raise SharedMemoryError(f"{where}: must be a list")
    out = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get(second), str) or not row[second].strip():
            raise SharedMemoryError(f"{where}[{i}]: needs `pattern` and `{second}` as text")
        out.append((_regex(row.get("pattern"), f"{where}[{i}]"), row[second].strip()))
    return out


def load_gate_rules(stream=None, path=None):
    """The gate's brand rules for a stream, from its `gate-rules.json`.

    `{status_words: [(pattern, fix)], cleared_hedges: [phrase],
    capability_verbs: [regex alternative], house_style: {hook_words: (min,
    max), what_we_do_not_claim: bool, tag_line: bool, retired: [rule]},
    announce: {status_flags:
    [(pattern, why)], cleared_phrases: [regex], voice_flags: [(pattern, why)]}}`.
    A stream without the file gets the defaults (no status rule, the standard
    verbs, house style on), never another stream's rules. A file that does not
    parse, a wrong type or a pattern that is not a regular expression raises:
    the gate must not pass on rules it cannot read.
    """
    path = path or paths(stream)["gate_rules_json"]
    doc = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except ValueError as e:
            raise SharedMemoryError(f"{path}: does not parse as JSON ({e})")
        if not isinstance(doc, dict):
            raise SharedMemoryError(f"{path}: must be a JSON object")
    hedges = doc.get("cleared_hedges", [])
    verbs = doc.get("capability_verbs", list(DEFAULT_CAPABILITY_VERBS))
    for name, value in (("cleared_hedges", hedges), ("capability_verbs", verbs)):
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            raise SharedMemoryError(f"{path}: {name}: must be a list of non-empty text")
    if not verbs:
        raise SharedMemoryError(f"{path}: capability_verbs: empty, so no capability sentence would ever need a cite; "
                                "leave the key out to keep the standard verbs")
    style = doc.get("house_style", {})
    announce = doc.get("announce", {})
    if not isinstance(style, dict) or not isinstance(announce, dict):
        raise SharedMemoryError(f"{path}: house_style and announce must be objects")
    hook = style.get("hook_words", {"min": DEFAULT_HOOK_WORDS[0], "max": DEFAULT_HOOK_WORDS[1]})
    if hook is not False:
        ok = isinstance(hook, dict) and all(isinstance(hook.get(k), int) and not isinstance(hook.get(k), bool)
                                            for k in ("min", "max")) and 1 <= hook["min"] <= hook["max"]
        if not ok:
            raise SharedMemoryError(f"{path}: house_style.hook_words: must be {{\"min\": n, \"max\": n}} with min <= max, or false")
    for key in ("what_we_do_not_claim", "tag_line"):
        if not isinstance(style.get(key, True), bool):
            raise SharedMemoryError(f"{path}: house_style.{key}: must be true or false")
    retired = style.get("retired", [])
    if not isinstance(retired, list) or any(r not in RETIRABLE_RULES for r in retired):
        raise SharedMemoryError(f"{path}: house_style.retired: a list of {', '.join(RETIRABLE_RULES)}; "
                                "no other check can leave the code")
    cleared = announce.get("cleared_phrases", [])
    if not isinstance(cleared, list):
        raise SharedMemoryError(f"{path}: announce.cleared_phrases: must be a list")
    return {
        "path": path,
        "present": os.path.exists(path),
        "status_words": _pairs(doc.get("status_words", []), "fix", f"{path}: status_words"),
        "cleared_hedges": [h.strip() for h in hedges],
        "capability_verbs": [_regex(v, f"{path}: capability_verbs") for v in verbs],
        "house_style": {
            "hook_words": None if hook is False else (hook["min"], hook["max"]),
            "what_we_do_not_claim": style.get("what_we_do_not_claim", True),
            "tag_line": style.get("tag_line", True),
            "retired": list(retired),
        },
        "announce": {
            "status_flags": _pairs(announce.get("status_flags", []), "why", f"{path}: announce.status_flags"),
            "cleared_phrases": [_regex(p, f"{path}: announce.cleared_phrases") for p in cleared],
            "voice_flags": _pairs(announce.get("voice_flags", []), "why", f"{path}: announce.voice_flags"),
        },
    }


# --- formats ------------------------------------------------------------------

FORMATS_FILE = "formats.json"
FORMAT_CHANNELS = ("blog", "linkedin", "x")
#: The one format every stream has: the theme post with its teasers. A stream
#: without a formats.json writes this and nothing else, as the engine always did.
DEFAULT_FORMAT = "theme-post"
DEFAULT_FORMATS = {
    DEFAULT_FORMAT: {
        "name": "Theme post with teasers",
        "when": "a content-shaped finding with a fact to anchor on, or a theme's introduction",
        "structure": ["hook", "the change or the deadlock", "the structural reading",
                      "the standing point: the theme's differentiator", "the honest limit, in the post's own words"],
        "channels": ["blog", "linkedin", "x"], "length": "350 to 700 words; teasers re-cut", "weight": 3.0,
        "needs_evidence": False, "skill": "",
    },
}


def load_formats(stream=None, path=None):
    """The formats a stream may write in, from its `formats.json`: `{key: {name, when,
    structure: [beat], channels: [blog|linkedin|x], length, weight, needs_evidence, skill}}`.

    A stream without the file has the one default format. A file that does not parse, a
    format without a structure or with a channel that is not one, or a weight that is not a
    positive number raises: a draw is never made over formats that could not be read.
    """
    path = path or paths(stream)["formats_json"]
    if not os.path.exists(path):
        return {k: dict(v) for k, v in DEFAULT_FORMATS.items()}
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except ValueError as e:
        raise SharedMemoryError(f"{path}: does not parse as JSON ({e})")
    rows = doc.get("formats") if isinstance(doc, dict) else None
    if not isinstance(rows, dict) or not rows:
        raise SharedMemoryError(f"{path}: needs a `formats` object with at least one format")
    out = {}
    for key, row in rows.items():
        if key.startswith("_"):
            continue
        where = f"{path}: formats.{key}"
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", key) or not isinstance(row, dict):
            raise SharedMemoryError(f"{where}: a format is keyed by a short lower-case name and is an object")
        structure, channels = row.get("structure"), row.get("channels")
        if not isinstance(structure, list) or not structure or not all(isinstance(b, str) and b.strip() for b in structure):
            raise SharedMemoryError(f"{where}.structure: a list of the beats the format runs, in order")
        if not isinstance(channels, list) or not channels or any(c not in FORMAT_CHANNELS for c in channels):
            raise SharedMemoryError(f"{where}.channels: one or more of {', '.join(FORMAT_CHANNELS)}")
        weight = row.get("weight", 1)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or weight <= 0:
            raise SharedMemoryError(f"{where}.weight: a number above 0")
        out[key] = {"name": str(row.get("name") or key), "when": str(row.get("when") or ""),
                    "structure": [b.strip() for b in structure], "channels": list(channels),
                    "length": str(row.get("length") or ""), "weight": float(weight),
                    "needs_evidence": row.get("needs_evidence") is True, "skill": str(row.get("skill") or "")}
    if not out:
        raise SharedMemoryError(f"{path}: needs at least one format")
    return out


# --- claims -----------------------------------------------------------------

def _list_cell(cell):
    cell = (cell or "").strip()
    return [] if cell in ("", "—", "-") else [x.strip() for x in cell.split(",") if x.strip()]


def _ref_cell(cell):
    cell = (cell or "").strip()
    return "" if cell in ("", "—", "-") else cell


def load_claims(stream=None, path=None):
    """The claims register of a stream: `{id: row}` in file order.

    Each row carries the columns of `claims.md` with `themes` as a list and the
    reference cells (`supersedes`, `superseded_by`, `from`) as strings, empty
    where the cell is a dash. Raises on a malformed register: an id used
    twice, a value outside the closed vocabularies, a supersession that does
    not point both ways, a theme the stream's `themes.md` does not list, or a
    `from` that names no registry stream. A malformed register is never read
    around: the gate must not pass on a row it cannot trust.
    """
    claims_md = path or paths(stream)["claims_md"]
    text = _read(claims_md)
    rows = table_in(text, "register")
    themes_known = {t["tag"] for t in load_themes(stream)} if path is None else None
    out = {}
    for r in rows:
        cid = r["id"].strip()
        if cid in out:
            raise SharedMemoryError(f"{claims_md}: claim id {cid!r} listed twice")
        row = dict(r)
        row["id"] = cid
        row["themes"] = _list_cell(r.get("themes"))
        for k in ("supersedes", "superseded_by", "from"):
            row[k] = _ref_cell(r.get(k))
        for k, vocab in (("grade", CLAIM_GRADES), ("tier", CLAIM_TIERS), ("corroboration", CLAIM_CORROBORATION)):
            if row.get(k, "").strip() not in vocab:
                raise SharedMemoryError(f"{claims_md}: {cid}: {k} {row.get(k)!r} is not one of {vocab}")
        if themes_known is not None:
            bad = [t for t in row["themes"] if t not in themes_known]
            if bad:
                raise SharedMemoryError(f"{claims_md}: {cid}: themes {bad} are not in themes.md")
        if row["from"]:
            src = row["from"].split("/", 1)[0]
            if src not in load_streams():
                raise SharedMemoryError(f"{claims_md}: {cid}: from {row['from']!r} names no registry stream")
        out[cid] = row
    for cid, row in out.items():
        for k, back in (("supersedes", "superseded_by"), ("superseded_by", "supersedes")):
            ref = row[k]
            if not ref:
                continue
            if ref not in out:
                raise SharedMemoryError(f"{claims_md}: {cid}: {k} {ref!r} is not a row")
            if out[ref][back] != cid:
                raise SharedMemoryError(f"{claims_md}: {cid} {k} {ref} but {ref} does not point back")
    return out


def claim(cid, stream=None):
    """One register row. An unknown id raises."""
    reg = load_claims(stream)
    key = (cid or "").strip()
    if key not in reg:
        raise SharedMemoryError(f"unknown claim {cid!r} in the {stream or DEFAULT_STREAM} register")
    return reg[key]


def citable(cid, stream=None, claims=None):
    """`(ok, reason)`: whether a draft may cite this id right now.

    Citable means: the id is a row, it is not superseded, and its
    corroboration is `primary` or `two-independent`. The grade is not judged
    here: the gate decides what an `asserted` or `intended` row may support.
    """
    reg = load_claims(stream) if claims is None else claims
    key = (cid or "").strip()
    if key not in reg:
        return False, f"{key or '(empty)'}: no such claim in the register"
    row = reg[key]
    if row["superseded_by"]:
        return False, f"{key}: superseded by {row['superseded_by']}"
    if row["corroboration"] not in CITABLE_CORROBORATION:
        return False, f"{key}: corroboration is {row['corroboration']}, not yet citable"
    return True, ""


def current_claims(stream=None):
    """The rows that are not superseded, in file order."""
    return [r for r in load_claims(stream).values() if not r["superseded_by"]]


# --- themes -----------------------------------------------------------------

def load_themes(stream=None):
    """The themes from `themes.md`, definition joined to licence by tag.

    Returns a list of dicts in file order carrying the fields the engine reads:
    `tag`, `what`, `different`, `fact`, `partner_tags`, `intro_post`, `layer`,
    `licence`, `licence_basis`, `logics`. A stream whose file carries the
    headings and no rows yields an empty list, never another stream's roster.
    """
    themes_md = paths(stream)["themes_md"]
    text = _read(themes_md)
    defs = parse_tables(_sections(text)[""])
    if not defs:
        raise SharedMemoryError(f"{themes_md}: no theme dictionary table found")
    defs = defs[0]
    lic = {r["hashtag"]: r for r in table_in(text, "licence and layer")}

    def_tags = [r["hashtag"] for r in defs]
    if set(def_tags) != set(lic):
        missing = sorted(set(def_tags) - set(lic))
        extra = sorted(set(lic) - set(def_tags))
        raise SharedMemoryError(
            f"{themes_md}: the two tables disagree on the theme roster; "
            f"no licence row for {missing}, no dictionary row for {extra}"
        )

    themes = []
    for r in defs:
        tag = r["hashtag"]
        l = lic[tag]
        themes.append({
            "tag": tag,
            "what": r.get("what it is", ""),
            "different": r.get("why it is different", ""),
            "fact": r.get("fact it links back to", ""),
            "partner_tags": _partner_tags(r.get("partner tags", "")),
            "intro_post": r.get("intro post", ""),
            "layer": l.get("layer", ""),
            "licence": l.get("licence", ""),
            "logics": [x.strip() for x in l.get("logics", "").split(",") if x.strip()],
            "licence_basis": l.get("licence basis", ""),
        })
    return themes


def _partner_tags(cell):
    """The handles a theme's partner-tag cell names, `none cleared` yielding []."""
    return re.findall(r"@[A-Za-z0-9_]+", cell or "")


def theme_tags(stream=None):
    return [t["tag"] for t in load_themes(stream)]


# --- handles ----------------------------------------------------------------

def load_handles(stream=None):
    """The inventory from `handles.md`, with the private companion's presence.

    Returns `{own_channels, cleared_partners, standards_bodies, private}`. The
    committed file is the whole taggable inventory; the gitignored companion
    carries stealth and unsigned-draft parties and the denylist, which are
    read-time context for the gate rather than tag targets, so this reports
    only whether it is present.
    """
    p = paths(stream)
    text = _read(p["handles_md"])
    return {
        "own_channels": table_in(text, "own channels"),
        "cleared_partners": table_in(text, "cleared partners", prefix=True),
        "standards_bodies": table_in(text, "standards bodies", prefix=True),
        "private": {
            "path": p["handles_private_md"],
            "present": os.path.exists(p["handles_private_md"]),
        },
    }


def cleared_names(stream=None):
    """The organisations a draft may name, in `handles.md` order."""
    return [r["partner"] for r in load_handles(stream)["cleared_partners"]]


def taggable_handles(stream=None):
    """`{party: {x, linkedin}}` for cleared partners whose status is `verified`.

    A handle is tagged only if its owner is on the cleared list *and* the row is
    marked `verified` (`handles.md`, the rule at the top). Everything `collect`
    is a placeholder, never a tag.
    """
    out = {}
    for r in load_handles(stream)["cleared_partners"]:
        if r.get("status", "").lower() != "verified":
            continue
        out[r["partner"]] = {
            "x": _handle(r.get("x", "")),
            "linkedin": _handle(r.get("linkedin", "")),
            "themes": [t.strip() for t in r.get("themes", "").split(",") if t.strip()],
        }
    return out


def private_expected(stream=None):
    """Whether `handles.md` declares the private companion at all.

    The committed file's *the private companion* section names
    `handles.private.md` and states that a checkout without it is an incomplete
    read. That declaration is what makes the companion *expected*: the reader
    never guesses. `gate_lint` turns an expected-but-absent companion into a
    block; this function only reports the declaration.
    """
    return "handles.private.md" in _read(paths(stream)["handles_md"])


def denylist(stream=None):
    """The terms a draft may not echo, from the private companion.

    The list moved out of `themes.json` into `handles.private.md` on
    2026-09-08 and is closed: only Alpha adds to it or removes from it. Raises
    `SharedMemoryError` when the companion is not in the checkout — a caller
    that wants the term list gets it or gets an error, never an empty list it
    could mistake for a clean read.
    """
    text = _read(paths(stream)["handles_private_md"])
    return [r["term"] for r in table_in(text, "the denylist — terms a draft may not echo")]


def own_channels(stream=None):
    """`{(brand, platform): row}` for the stream's own channels."""
    return {(r["brand"], r["platform"]): r for r in load_handles(stream)["own_channels"]}


def _handle(cell):
    cell = (cell or "").strip()
    return "" if cell.lower() in ("", "collect", "—", "-") else cell


# --- summary ----------------------------------------------------------------

def summary(stream=None):
    p = paths(stream)
    themes = load_themes(stream)
    h = load_handles(stream)
    lines = [
        f"stream        {stream or DEFAULT_STREAM}  memory {os.path.relpath(p['dir'], REPO)}",
        f"themes    {len(themes):>2}  from {os.path.relpath(p['themes_md'], REPO)}"
        f"  ({sum(1 for t in themes if t['licence'] == 'held')} held)",
        f"cleared   {len(h['cleared_partners']):>2}  from {os.path.relpath(p['handles_md'], REPO)}"
        f"  ({sum(1 for r in h['cleared_partners'] if r.get('status') == 'verified')} verified)",
        f"own       {len(h['own_channels']):>2}  own channels; {len(h['standards_bodies'])} standards bodies",
        f"private       {'present' if h['private']['present'] else 'ABSENT'}"
        f"  {os.path.relpath(p['handles_private_md'], REPO)}",
    ]
    try:
        claims = load_claims(stream)
        cur = [r for r in claims.values() if not r["superseded_by"]]
        lines.append(
            f"claims   {len(claims):>3}  from {os.path.relpath(p['claims_md'], REPO)}"
            f"  ({len(cur)} current, {sum(1 for r in cur if r['corroboration'] in CITABLE_CORROBORATION)} citable)"
        )
    except SharedMemoryError as e:
        lines.append(f"claims        ERROR  {e}")
    return "\n".join(lines)


def registry_table():
    """The registry as the lines `memory.py --list` prints."""
    lines = [f"{'slug':<8} {'name':<8} {'owner':<10} {'autopilot':<10} {'corpus':<10} memory"]
    for slug, r in load_streams().items():
        auto = "nothing" if r["autopilot"].strip().lower().startswith("nothing") else "rule"
        lines.append(
            f"{slug:<8} {r['name']:<8} {r['owner']:<10} {auto:<10} {r['corpus status']:<10} "
            f"{r['memory'].strip('`')}"
            + ("" if may_draft(slug) else "   drafts: no")
        )
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stream", default=None, help="a registry slug; default the root stream (brand.slug) at the memory root")
    ap.add_argument("--list", action="store_true", help="print the stream registry and exit")
    a = ap.parse_args()
    try:
        if a.list:
            print(registry_table())
            sys.exit(0)
        print(summary(a.stream))
        for t in load_themes(a.stream):
            print(f"  {t['tag']:<22} {t['layer']:<24} {t['licence']}")
        print("cleared: " + ", ".join(cleared_names(a.stream)))
    except SharedMemoryError as e:
        sys.exit(f"memory.py: {e}")
