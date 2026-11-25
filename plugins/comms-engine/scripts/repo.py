#!/usr/bin/env python3
"""
repo.py - the content repository is the single source.

A queue item becomes a `Content/Calendar/` note at **draft** time, not at
publish time. This module owns every note the engine writes; `publish.py` is
now only the approval path (refusal checks, webhook, run log) and
calls in here for the writing.

  write_item(item, status) -> {"post": <path>, "teasers": <path>}

is called twice in an item's life:

  * at draft, with `status="Idea"`   - by `python3 repo.py --all` (the sweep
    `/social-cycle` step 5 runs once the gatekeeper has written `gate` and the
    distributor has applied the decisions, so `gate_verdict` and `alpha_status`
    on the note are the gate's and Alpha's rather than the writer's self-gate)
  * on approval, with `status="Ready"` - by `publish.py <id>`

Two notes are written per item, as before:

  Content/Calendar/<title>.md              the full post   platform: Blog
  Content/Calendar/<title> - teasers.md    the teasers     platform: LinkedIn

Both carry the calendar frontmatter the Obsidian views read, plus seven
engine keys: `engine_id`, `theme`, `finding_id`,
`logic`, `gate_verdict`, `alpha_status` and `hooks_considered`. **`platform:
Blog` is what identifies the item's own note**; the teasers note is its
companion and carries the same `engine_id`.

An item's existing note is found by `engine_id`, never by title, so the
approval rewrite lands on the note the draft wrote even if the title changed,
and the publish record on it is carried forward.

The note is the record; `state/queue.json` is a **derived index**. Reading
runs the other way through the same module:

  load_items()          every engine note in Content/Calendar, as queue items
  write_index()         rebuild state/queue.json from those items
  set_fields(id, {..})  write a decision, a gate verdict, a publish record or
                        one of Alpha's desk edits onto the item's note
  base_hash(item)       the digest the desk records with an edit, so
                        apply_edits.py can tell a note nobody has touched from
                        one that has moved on

`build_dashboard.py` builds the dashboard page from `load_items()`, so deleting
`queue.json` loses nothing: `python3 repo.py --index` puts it back from the
notes. Because the index is a derivation, nothing writes an *existing* item
from it - `--all` only ingests drafts that have no note yet, and everything
else goes through `set_fields`. Rewriting a live note from the index would
clobber an Obsidian edit, which the standing never-clobber
rule forbids.

CLI:
  python3 repo.py Q-2026-01-05-example-1                     # one item, status Idea
  python3 repo.py Q-... --status Ready                        # one item at a chosen status
  python3 repo.py Q-... --set alpha_status=approved           # a field onto the item's note
  python3 repo.py --all                                       # ingest new drafts, then rebuild the index
  python3 repo.py --index                                     # rebuild the index from the notes
  python3 repo.py --all --dry-run                             # say what would be written
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.parse

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402


def post_url(slug):
    """Where a Blog row lives on the brand's own site, by slug: engine.json site.post_url.

    The CTA every teaser carries and the link the autopilot replies with; the
    gate checks the teasers against the same template."""
    return str(config.cfg("site.post_url", "https://www.example.com/insights/{slug}")).format(slug=slug)

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
sys.path.insert(0, HERE)
import memory  # noqa: E402  the stream registry
ENGINE = os.path.dirname(HERE)
REPO = paths.instance()
STATE = paths.state()
CAL = os.path.join(REPO, "Content", "Calendar")

# The calendar vocabulary in Content/Content Dashboard.md.
STATUSES = ("Idea", "Drafting", "Ready", "Scheduled", "Published")

# The seven engine keys, local to the vault.
ENGINE_KEYS = ("engine_id", "theme", "finding_id", "logic", "gate_verdict",
               "alpha_status", "hooks_considered")

# The rest of the item's record, written on the post note only, so the note is
# the whole item and `state/queue.json` can be rebuilt from it.
RECORD_KEYS = ("cta", "partner_tags", "campaign", "freshness_deadline",
               "drafted_by", "drafted_at", "gate", "gate_writer", "desk_edit",
               # the claims register rows the post leans on (plan v2, A5)
               "cites",
               # the planning query the pick answers, the one-variable
               # hypothesis, the predicted band and the test id (plan v2, A8)
               "query", "hypothesis", "predicted", "test_id",
               # the post's honest-limit sentence, verbatim (decision
               # 2026-11-07-vary-the-template), and the rewrite chain: a
               # redraft names the note it replaces, and that note names it
               "limit", "redraft_of", "superseded_by",
               # how the draft was drawn (plan_queries.draw: the seed, the kind and
               # the pool) and the candidates the audit ranked below it, each a
               # version a person can swap in (decision 2026-11-13)
               "draw", "alternatives")

# Written only when the item carries them, so a note drafted before they
# existed reads back, and hashes, exactly as it did.
OPTIONAL_KEYS = ("limit", "redraft_of", "superseded_by", "draw", "alternatives", "sources")

# `drafted_by` on a post a person on the team wrote on the control page, not the engine.
TEAM_BY = "team"

# A note whose redraft has landed. It stays in the vault as the record of what
# was sent back, but nothing offers it again: the redraft holds its slot.
SUPERSEDED = "superseded"

# Written by publish.py once the item has been released, and carried across a
# later rewrite rather than re-derived.
PUBLISH_KEYS = ("published_to", "published_at", "vault_note")

# Kept on an existing note across a rewrite: losing the publish record would
# re-offer a released item as unpublished.
CARRY_KEYS = PUBLISH_KEYS

FM_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)

# An item that serves two streams. It may exist in the vault (the calendar
# carries it) but it is flagged everywhere and never drafted further: the
# single-pillar test says split it into two items.
BOTH = "Both"


def stream_of(item):
    """The item's stream as the registry knows it, or `Both`.

    Raises `ValueError` on a missing stream or one the registry does not list:
    a record without a stream is refused, never defaulted (plan v2, A3).
    """
    name = str(item.get("stream") or "").strip()
    if not name:
        raise ValueError(f"item {item.get('id', '?')}: no stream; every record names the stream it serves")
    if name == BOTH:
        return BOTH
    try:
        slug = memory.slug_for(name)
    except memory.SharedMemoryError as e:
        raise ValueError(f"item {item.get('id', '?')}: {e}") from None
    return memory.stream(slug)["name"]


def needs_split(item):
    return str(item.get("stream") or "").strip() == BOTH


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:80]


def safe_title(s):
    return re.sub(r'[\\/:*?"<>|]', "", s).strip()[:120]


def as_date(value):
    """A real YAML date, the way every other calendar note carries it, so the
    Bases views' `date(note.date)` reads the same type from every note."""
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return value


def slug_for(item):
    """The slug the CTA already points at, so the two cannot disagree."""
    if item.get("slug"):
        return item["slug"]
    cta = item.get("cta") or ""
    if cta:
        seg = urllib.parse.urlparse(cta).path.rstrip("/").rsplit("/", 1)[-1]
        if seg:
            return seg
    return slugify(item["title"])


# The four fields Alpha edits on the desk, and the order they are hashed in.
# `dashboard/template.html` computes the same digest in JavaScript over the
# values `build_dashboard.py` inlined from the note, and stores it on the edit
# as `base_hash`. `apply_edits.py` applies an edit only while the note still
# hashes to it, so a desk edit and a vault-side change cannot clobber one
# another. The two implementations must agree byte for byte; the JS one carries
# this function as a comment.
HASH_FIELDS = ("post", "teaser_linkedin", "teaser_x", "title")


def base_hash(item):
    """sha256 over the four edited fields, U+001F-separated, UTF-8."""
    s = "\u001f".join("" if item.get(f) is None else str(item.get(f)) for f in HASH_FIELDS)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def parse_note(path):
    """(frontmatter, body) for an existing note, or ({}, '') if unreadable."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}, ""
    m = FM_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}, m.group(2)
    return (fm if isinstance(fm, dict) else {}), m.group(2)


def find_note(engine_id, platform):
    """The note already written for this item on this platform, if any."""
    if not os.path.isdir(CAL):
        return None
    for name in sorted(os.listdir(CAL)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(CAL, name)
        fm, _ = parse_note(path)
        if fm.get("engine_id") == engine_id and fm.get("platform") == platform:
            return path
    return None


def write_note(path, fm, body):
    """One serialisation for every engine write, so the file's format never
    flips - and so a hook carrying ': ' or a theme starting '#' is quoted
    rather than breaking the frontmatter."""
    y = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=4096).strip()
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"---\n{y}\n---\n\n{body.strip()}\n")


def _place(path, existing):
    """Move an item's note to its current title, so there is one note per item."""
    if existing and os.path.abspath(existing) != os.path.abspath(path):
        os.replace(existing, path)


def _frontmatter(item, status, slug, date):
    verdict = (item.get("gate") or {}).get("verdict") or (item.get("gate_writer") or {}).get("verdict", "")
    alpha = item.get("alpha_status", "proposed")
    notes = (f"Theme post. Theme {item['theme']}, logic {item.get('logic','')}. "
             f"Drafted by social-engine ({item.get('drafted_by','')}), gate {verdict}.")
    if alpha == "approved":
        notes += f" Alpha approved {item.get('alpha_decided_at','')}."
    notes += f" Finding {item.get('finding_id','')}."
    excerpt = item.get("excerpt") or (item.get("teaser_linkedin", "").split("\n")[0][:200])
    fm = {
        "title": item["title"],
        "date": as_date(date),
        "status": status,
        "stream": stream_of(item),
        "type": item.get("type", "Evergreen"),
        "pillar": item.get("pillar", ""),
        "platform": "Blog",
        "format": item.get("format", "Observation"),
        "owner": item.get("owner", "EV"),
        "proof_gate": item.get("anchor", ""),
        "assets": "",
        "notes": notes,
        "category": item["theme"].lstrip("#"),
        "slug": slug,
        "excerpt": excerpt,
        "feature": False,
        "topics": [t.lstrip("#") for t in item.get("tags", [])],
        "tags": ["content"],
        # engine keys - local to the vault
        "engine_id": item["id"],
        "theme": item["theme"],
        "finding_id": item.get("finding_id", ""),
        "logic": item.get("logic", ""),
        "gate_verdict": verdict,
        "alpha_status": alpha,
        "hooks_considered": list(item.get("hooks_considered", [])),
        # ── the rest of the item's record ──────────────────────────
        # What the calendar has no column of its own for. The note is the
        # item, so it carries the whole item: `load_items()` below reads
        # these back and `state/queue.json` is rebuilt from them.
        "cta": item.get("cta") or post_url(slug),
        "partner_tags": list(item.get("partner_tags", [])),
        "cites": [str(c) for c in (item.get("cites") or [])],
        "query": item.get("query", ""),
        "hypothesis": item.get("hypothesis", ""),
        "predicted": item.get("predicted", ""),
        "test_id": item.get("test_id", ""),
        "campaign": (item.get("slot") or {}).get("campaign", ""),
        "freshness_deadline": item.get("freshness_deadline", ""),
        "drafted_by": item.get("drafted_by", ""),
        "drafted_at": item.get("drafted_at", ""),
        # The gatekeeper's record and the writer's own pre-gate check, verbatim.
        # `gate_verdict` above is the flat, readable copy of `gate.verdict` that
        # the milestone's decision names; this is the reasoning behind it, and
        # dropping it would lose the review the desk shows check by check.
        "gate": item.get("gate") or {},
        "gate_writer": item.get("gate_writer") or {},
        # How Alpha's last desk edit was resolved against this note:
        # {edited_at, by, base_hash, resolution: applied|desk|vault, at}.
        # `apply_edits.py` writes it; `publish.py` reads it, and refuses the
        # item until the gatekeeper has re-read the text it left behind.
        "desk_edit": item.get("desk_edit") or {},
    }
    for k in OPTIONAL_KEYS + PUBLISH_KEYS:
        if item.get(k):
            fm[k] = item[k]
    return fm


def _carry(fm, existing, keys=CARRY_KEYS):
    """Keep the note's publish record across a rewrite; without it a released
    item loses its publish record."""
    if not existing:
        return
    old, _ = parse_note(existing)
    for k in keys:
        if old.get(k) and not fm.get(k):
            fm[k] = old[k]


HANDOFF = ("Hand to the scheduling MCP only after {cta} resolves, and only with "
           "the user's confirmation on this exact text.")


def tagline_for(fm):
    """The tag line under each teaser: the item's theme, then any partner tag."""
    return " ".join([fm.get("theme", "")] + list(fm.get("partner_tags") or [])).strip()


def teaser_body(linkedin, x, tagline, cta):
    """The teasers note's body. `read_teasers` below is its exact inverse."""
    return (f"## LinkedIn\n\n{linkedin.strip()}\n\n{tagline}\n{cta}\n\n"
            f"## X\n\n{x.strip()}\n\n{tagline}\n{cta}\n\n"
            f"---\n{HANDOFF.format(cta=cta)}\n")


def _strip_appended(text, tagline, cta):
    """Remove the one tag line `teaser_body` appended, and only that one.

    A teaser may end with its own hashtag and CTA - the writer's, part of the
    teaser - and the note then shows the pair twice. Because the append is
    unconditional, taking exactly one block off the end gives the teaser back
    as it was written, whichever way the writer ended it.
    """
    if text.strip() == f"{tagline}\n{cta}".strip():
        # The tag line is all there is: the teaser itself was empty.
        return ""
    for suffix in (f"\n\n{tagline}\n{cta}", f"\n{tagline}\n{cta}", f"\n\n{tagline}", f"\n\n{cta}"):
        if suffix.strip() and text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def read_teasers(body, tagline, cta):
    """(linkedin, x) as they were written, from a teasers note's body."""
    def section(head, end):
        m = re.search(rf"^## {head}[ \t]*\n(.*?)(?=\n^{end})", body, re.S | re.M)
        return m.group(1).strip() if m else ""
    return (_strip_appended(section("LinkedIn", r"## X"), tagline, cta),
            _strip_appended(section("X", r"---$"), tagline, cta))


def write_item(item, status):
    """Write (or rewrite) this queue item's calendar notes at `status`.

    Returns {"post": <abs path>, "teasers": <abs path>}.
    """
    if status not in STATUSES:
        raise ValueError(f"status {status!r} is not one of {', '.join(STATUSES)}")
    if status == "Published":
        # The deck's manual release: the engine never sets it.
        raise ValueError("the engine never writes status: Published")

    stream_of(item)  # refuses an item with no stream before anything is written
    title = item["title"]
    slug = slug_for(item)
    date = (item.get("slot") or {}).get("date") or dt.date.today().isoformat()
    os.makedirs(CAL, exist_ok=True)

    # ── the post ────────────────────────────────────────────────────
    fm = _frontmatter(item, status, slug, date)
    existing = find_note(item["id"], "Blog")
    _carry(fm, existing)
    post_path = os.path.join(CAL, safe_title(title) + ".md")
    _place(post_path, existing)
    write_note(post_path, fm, item.get("post", ""))

    # ── the teasers companion ───────────────────────────────────────
    cta = fm["cta"]
    teasers = teaser_body(item.get("teaser_linkedin", ""), item.get("teaser_x", ""),
                          tagline_for(fm), cta)
    fm_t = dict(fm)
    # The teasers note is the companion, not a second record: it carries the
    # seven engine keys so it can be found by `engine_id`, and none of the
    # record keys, which live once, on the post note.
    for k in RECORD_KEYS + PUBLISH_KEYS:
        fm_t.pop(k, None)
    fm_t.update({
        "title": title + " - teasers",
        "platform": "LinkedIn",
        # The teasers trail the post: they are handed to the scheduler only
        # once the live URL resolves, so they are never Ready with it.
        "status": "Idea" if status == "Idea" else "Drafting",
        "slug": "",
        "excerpt": "",
        "notes": f"Teasers for the theme post '{title}'. Platform-native re-cuts, not copies. CTA to the blog.",
    })
    existing_t = find_note(item["id"], "LinkedIn")
    teaser_path = os.path.join(CAL, safe_title(title) + " - teasers.md")
    _place(teaser_path, existing_t)
    write_note(teaser_path, fm_t, teasers)

    return {"post": post_path, "teasers": teaser_path}


# ── reading the notes back ──────────────────────────────────────────
# The other direction. `write_item` puts an item into the vault; everything
# below reads the vault and gives the item back, so `state/queue.json` is a
# derived index rather than the record, and the desk is built from the notes.


def item_from_note(fm, body, teasers=None):
    """The queue item this note holds - the inverse of `_frontmatter`.

    `teasers` is the (frontmatter, body) of the companion LinkedIn note, if it
    is there; without it the teaser fields come back empty rather than wrong.
    """
    slug = fm.get("slug") or ""
    cta = fm.get("cta") or (post_url(slug) if slug else "")
    lin, x = read_teasers(teasers[1], tagline_for(fm), cta) if teasers else ("", "")
    item = {
        "id": fm.get("engine_id", ""),
        "theme": fm.get("theme", ""),
        "stream": fm.get("stream", ""),
        "type": fm.get("type", ""),
        "finding_id": fm.get("finding_id", ""),
        "anchor": fm.get("proof_gate", ""),
        "logic": fm.get("logic", ""),
        "title": fm.get("title", ""),
        "hooks_considered": list(fm.get("hooks_considered") or []),
        "excerpt": fm.get("excerpt", ""),
        "post": body.strip(),
        "teaser_linkedin": lin,
        "teaser_x": x,
        "tags": ["#" + str(t).lstrip("#") for t in (fm.get("topics") or [])],
        "partner_tags": list(fm.get("partner_tags") or []),
        "cites": [str(c) for c in (fm.get("cites") or [])],
        "query": fm.get("query", ""),
        "hypothesis": fm.get("hypothesis", ""),
        "predicted": fm.get("predicted", ""),
        "test_id": fm.get("test_id", ""),
        "cta": cta,
        # The note's own slug, carried on the item so a reader can check the
        # CTA against it rather than deriving one from the other. `slug_for`
        # prefers it, so the value round-trips through the next write.
        "slug": slug,
        "pillar": fm.get("pillar", ""),
        "format": fm.get("format", ""),
        "gate_writer": fm.get("gate_writer") or {},
        "gate": fm.get("gate") or {},
        "desk_edit": fm.get("desk_edit") or {},
        "slot": {"date": str(fm.get("date", "")),
                 "platform": fm.get("platform", "Blog"),
                 "campaign": fm.get("campaign", "")},
        "freshness_deadline": fm.get("freshness_deadline", ""),
        "owner": fm.get("owner", ""),
        "alpha_status": fm.get("alpha_status", "proposed"),
        "drafted_by": fm.get("drafted_by", ""),
        "drafted_at": fm.get("drafted_at", ""),
    }
    if needs_split(item):
        item["needs_split"] = True
    for k in OPTIONAL_KEYS + PUBLISH_KEYS:
        if fm.get(k):
            item[k] = fm[k]
    return item


TEAM_CHANNELS = {"x": "teaser_x", "linkedin": "teaser_linkedin"}


def team_item(stream, channel, date, text, title=None, theme=""):
    """The item a person on the team writes on the control page: one post on one channel, no
    article, `drafted_by: team`, a draft (`alpha_status: proposed`) the gatekeeper gates and a
    person approves like any other. Raises ValueError on what it cannot take."""
    if channel not in TEAM_CHANNELS:
        raise ValueError(f"channel is one of {', '.join(TEAM_CHANNELS)}, not {channel!r}")
    text = str(text or "").strip()
    if not text:
        raise ValueError("the post is empty")
    day = as_date(date)
    if not isinstance(day, dt.date):
        raise ValueError(f"{date!r} is not a date (YYYY-MM-DD)")
    title = " ".join(str(title or "").split()) or " ".join(text.split())[:60]
    if not safe_title(title):
        raise ValueError("the title is empty once the characters a file name cannot carry are taken out")
    item = {"title": safe_title(title), "theme": str(theme or ""), "stream": stream, "post": "",
            "teaser_x": "", "teaser_linkedin": "", "slot": {"date": day.isoformat()}, "drafted_by": TEAM_BY,
            "drafted_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "alpha_status": "proposed",
            "format": "Team post", "owner": TEAM_BY, "slug": slugify(title)}
    item[TEAM_CHANNELS[channel]] = text
    item["stream"] = stream_of(item)
    base = f"T-{day.isoformat()}-{slugify(title)[:30].strip('-') or 'post'}"
    have = scan_notes()
    n = 1
    while f"{base}-{n}" in have:
        n += 1
    item["id"] = f"{base}-{n}"
    return item


def write_team_item(item):
    """Write a team item's notes at status Idea; refused when a note already carries its title."""
    for path in (os.path.join(CAL, item["title"] + ".md"), os.path.join(CAL, item["title"] + " - teasers.md")):
        if os.path.exists(path):
            raise ValueError(f"a note is already called {os.path.basename(path)!r}; give the post another title")
    return write_item(item, "Idea")


def split_report(items=None):
    """The items the index lists under *needs split*: `stream: Both`, and any
    note whose stream is empty or unknown to the registry."""
    items = load_items() if items is None else items
    out = []
    for i in items:
        if needs_split(i):
            out.append((i["id"], "Both"))
            continue
        try:
            stream_of(i)
        except ValueError as e:
            out.append((i["id"], str(e).split(": ", 1)[-1]))
    return out


def scan_notes():
    """Every engine note in Content/Calendar, read once, keyed by engine_id:
    {engine_id: {"Blog": (path, fm, body), "LinkedIn": (path, fm, body)}}."""
    found = {}
    if not os.path.isdir(CAL):
        return found
    for name in sorted(os.listdir(CAL)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(CAL, name)
        fm, body = parse_note(path)
        eid = fm.get("engine_id")
        if eid:
            found.setdefault(eid, {})[fm.get("platform", "")] = (path, fm, body)
    return found


def load_items():
    """The queue, read from the notes. Ordered by slot date, then id, so a
    rebuild of the index and of the desk is deterministic."""
    items = []
    for eid, notes in scan_notes().items():
        post = notes.get("Blog")
        if not post:
            # A teasers note with no post is a half-written item, not an item.
            continue
        teasers = notes.get("LinkedIn")
        items.append(item_from_note(post[1], post[2], (teasers[1], teasers[2]) if teasers else None))
    items.sort(key=lambda i: ((i.get("slot") or {}).get("date", ""), i["id"]))
    return items


def write_index(items=None):
    """Rebuild `state/queue.json` from the notes. It is an index of what the
    vault holds, not the record: deleting it loses nothing - with one
    exception. A draft the theme-writer appended that `--all` has not ingested
    yet exists only here (the drafting inbox), so a rebuild carries every
    queued item that has no note over unchanged. Lesson of 2026-11-05: the
    distributor's rebuild dropped three drafts before the ingest ran."""
    items = load_items() if items is None else items
    path = os.path.join(STATE, "queue.json")
    os.makedirs(STATE, exist_ok=True)
    try:
        with open(path, encoding="utf-8") as f:
            before = json.load(f)
    except (OSError, ValueError):
        before = []
    before = before.get("items", before) if isinstance(before, dict) else before
    noted = {i.get("id") for i in items}
    inbox = [i for i in before if isinstance(i, dict) and i.get("id") and i["id"] not in noted
             and not scan_notes().get(i["id"])]
    items = list(items) + inbox
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=1, ensure_ascii=False)
        f.write("\n")
    return path


def set_fields(engine_id, fields):
    """Write field values onto an item's note - the way a decision, a gate
    verdict or a publish record reaches the item now that the note is the
    record. Returns the paths rewritten."""
    notes = scan_notes().get(engine_id)
    if not notes or "Blog" not in notes:
        raise KeyError(f"no calendar note for {engine_id}")
    item = item_from_note(*notes["Blog"][1:], teasers=(notes["LinkedIn"][1], notes["LinkedIn"][2]) if "LinkedIn" in notes else None)
    unknown = set(fields) - set(item) - set(PUBLISH_KEYS) - set(OPTIONAL_KEYS) - {"status"}
    if unknown:
        # A field the note has no home for would be written and then read back
        # as nothing. Refuse rather than lose it silently.
        raise KeyError(f"{engine_id}: no such item field: {', '.join(sorted(unknown))}")
    fields = dict(fields)
    if item.get("alpha_status") == SUPERSEDED and fields.get("alpha_status") in ("rewrite", "proposed"):
        # The rewrite was answered: its redraft is a note. Re-applying the
        # standing "rewrite" decision every cycle must not offer it again.
        fields.pop("alpha_status")
        if not fields:
            return {"post": notes["Blog"][0], "teasers": (notes.get("LinkedIn") or [None])[0]}
    status = fields.pop("status", None) or notes["Blog"][1].get("status", "Idea")
    item.update(fields)
    return write_item(item, status)


#: What a person has already decided: such a text is not swapped under them.
SWAP_REFUSED = ("approved", "rejected", SUPERSEDED)


def swap_alternative(engine_id, n):
    """Put the n-th alternative (1-based) of a note in place of what the note carries now.

    The writer leaves the candidates the audit ranked second and third on the note as
    `alternatives`; each differs from the draft in one named variable and holds only the
    fields that differ (of `title`, `post`, `teaser_linkedin`, `teaser_x`). Swapping one in
    keeps the version it replaces as an alternative in its place, so a swap can be undone,
    and clears the gate: it is a new text, and the gate reads it again before anyone may
    approve it. Refused once a person has approved or rejected the item.
    Returns the paths rewritten."""
    notes = scan_notes().get(engine_id)
    if not notes or "Blog" not in notes:
        raise KeyError(f"no calendar note for {engine_id}")
    item = item_from_note(*notes["Blog"][1:], teasers=(notes["LinkedIn"][1], notes["LinkedIn"][2]) if "LinkedIn" in notes else None)
    alts = [a for a in (item.get("alternatives") or []) if isinstance(a, dict)]
    if not isinstance(n, int) or not 1 <= n <= len(alts):
        raise KeyError(f"{engine_id}: no alternative {n}; the note has {len(alts)}")
    if item.get("alpha_status") in SWAP_REFUSED:
        raise KeyError(f"{engine_id}: a person has {item['alpha_status']} this text; an alternative is not swapped under a decision")
    chosen = alts[n - 1]
    fields = {k: chosen[k] for k in HASH_FIELDS if isinstance(chosen.get(k), str) and chosen[k].strip()}
    if not fields:
        raise KeyError(f"{engine_id}: alternative {n} carries no text to swap in")
    back = {k: v for k, v in chosen.items() if k not in HASH_FIELDS}
    back.update({"value": "the draft this replaced", "why": "swapped out by a person", **{k: item.get(k, "") for k in fields}})
    alts[n - 1] = back
    return set_fields(engine_id, {**fields, "alternatives": alts, "gate": {}, "alpha_status": "proposed"})


def supersede_originals(items):
    """Mark the note each redraft replaces: `alpha_status: superseded` and
    `superseded_by: <redraft id>`. Run after the redrafts are notes, so the
    original leaves the desk and /today the moment its replacement is on them.
    Returns [(original id, redraft id)] for what was marked."""
    marked = []
    have = scan_notes()
    for item in items:
        old = item.get("redraft_of")
        if not old or old not in have or old == item.get("id"):
            continue
        fm = have[old].get("Blog", (None, {}))[1]
        if fm.get("alpha_status") == SUPERSEDED and fm.get("superseded_by") == item["id"]:
            continue
        set_fields(old, {"alpha_status": SUPERSEDED, "superseded_by": item["id"]})
        marked.append((old, item["id"]))
    return marked


def load_queue():
    """`state/queue.json` as it stands - the drafting inbox the theme-writer
    appends to, before `--all` ingests it into the vault. Everything that
    reads an *existing* item reads the notes, through `load_items()`."""
    with open(os.path.join(STATE, "queue.json")) as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description="write queue items into Content/Calendar, and rebuild the index from them")
    ap.add_argument("id", nargs="?", help="queue item id (omit with --all or --index)")
    ap.add_argument("--all", action="store_true",
                    help="ingest every drafted item that has no note yet")
    ap.add_argument("--index", action="store_true",
                    help="rebuild state/queue.json from the notes")
    ap.add_argument("--set", action="append", metavar="KEY=VALUE", default=[],
                    help="write a field onto an item's note (repeatable), e.g. --set alpha_status=approved")
    ap.add_argument("--swap", type=int, metavar="N",
                    help="put the note's N-th alternative in place of its text (the gate reads it again)")
    ap.add_argument("--status", default="Idea", choices=[s for s in STATUSES if s != "Published"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.id and args.all:
        ap.error("give one queue item id, or --all, not both")
    if not (args.id or args.all or args.index):
        ap.error("give one queue item id, or --all, or --index")

    # ── an alternative in place of the note's text ───────────────────
    if args.swap is not None:
        if not args.id:
            ap.error("--swap needs the queue item id")
        if args.dry_run:
            print(f"would swap alternative {args.swap} into {args.id}")
            return
        try:
            paths = swap_alternative(args.id, args.swap)
        except KeyError as e:
            sys.exit(str(e).strip("'"))
        print(f"swapped alternative {args.swap} into {os.path.relpath(paths['post'], REPO)}; the gate reads it again")
        print(f"index {os.path.relpath(write_index(), REPO)}")
        return

    # ── a field onto one item's note ────────────────────────────────
    if args.set:
        if not args.id:
            ap.error("--set needs the queue item id")
        fields = {}
        for pair in args.set:
            if "=" not in pair:
                ap.error(f"--set wants KEY=VALUE, got {pair!r}")
            k, v = pair.split("=", 1)
            fields[k.strip()] = v
        if args.dry_run:
            print(f"would set {fields} on {args.id}")
        else:
            try:
                paths = set_fields(args.id, fields)
            except KeyError as e:
                sys.exit(str(e).strip("'"))
            print(f"set {', '.join(fields)} on {os.path.relpath(paths['post'], REPO)}")
            print(f"index {os.path.relpath(write_index(), REPO)}")
        return

    if args.id or args.all:
        queue = load_queue()
        if args.all:
            # Ingest only. An item that already has a note is *held* in that
            # note: rewriting it from the index would clobber an Obsidian edit
            # with a stale derivation. Approved items are
            # written by publish.py, which runs the refusal checks first.
            have = set(scan_notes())
            items = [q for q in queue
                     if q.get("alpha_status") != "approved" and q["id"] not in have]
        else:
            item = next((q for q in queue if q["id"] == args.id), None)
            if not item:
                sys.exit(f"no queue item {args.id}")
            items = [item]

        for item in items:
            if args.dry_run:
                print(f"would write {safe_title(item['title'])}.md at status {args.status}")
                continue
            try:
                paths = write_item(item, args.status)
            except ValueError as e:
                # A draft with no stream, or a stream the registry does not
                # list, stays in the inbox and is named; the rest still land.
                print(f"refused {item.get('id', '?')}: {e}")
                continue
            for path in (paths["post"], paths["teasers"]):
                print(f"wrote {os.path.relpath(path, REPO)}  ({args.status})")
        if not items:
            print("nothing to ingest: every drafted item is already a note")
        elif not args.dry_run:
            for old, new in supersede_originals(items):
                print(f"superseded {old} by its redraft {new}")
            # A8: a prediction is recorded the moment the draft is a note, with
            # no actual; score.py fills the actual at 7 days.
            import predictions
            added = predictions.append_for(items)
            if added:
                print(f"predictions {os.path.relpath(predictions.path(), REPO)}  +{len(added)}: {', '.join(added)}")

    # ── the derived index ───────────────────────────────────────────
    if args.index or args.all:
        if args.dry_run:
            print(f"would rebuild the index from {len(load_items())} notes")
        else:
            items = load_items()
            print(f"index {os.path.relpath(write_index(items), REPO)}  ({len(items)} items from the notes)")
            split = split_report(items)
            if split:
                print(f"needs split ({len(split)}): an item serves one stream; split or fix before it is drafted further")
                for eid, why in split:
                    print(f"  {eid}: {why}")


if __name__ == "__main__":
    main()
