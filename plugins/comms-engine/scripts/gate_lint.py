#!/usr/bin/env python3
"""
gate_lint.py - the deterministic half of the gate.

`claim-gate` is nine checks a model performs by reading. Seven of the things it
looks for are decidable without judgment, and a machine should decide those:
the `gatekeeper` runs this script **before** its own reading, and the model
then spends its attention on the five checks that are genuinely judgment
(present-tense spec properties, dates, names, stats, the single-pillar test and
the licence cap).

The checks here, in the order they run. Every one reads the memory of the
**item's stream** (plan v2, A7): `.atelier/memory/` for the root stream, the stream's
own directory under `streams/<slug>/` otherwise. A missing stream, `Both`, an
unknown slug, a stream directory without the file, or a theme the stream's
`themes.md` does not list, blocks with the reason named - the gate never
reads another stream's memory to fill the gap.

  lint: stream            the item names a registry stream, its memory
                          directory is present, and its theme is one of that
                          stream's hashtags. Block otherwise.
  lint: status words      the stream's status rules (`status_words` of its
                          gate-rules.json, written from its status.md:
                          certification, accreditation, go-live and capability
                          words it may not use yet). Block. The cleared hedges
                          (`cleared_hedges`, the forms approved copy already
                          carries) are masked before the scan, so an approved
                          hedge passes and an upgrade of it does not. Both
                          ship empty in the template. A rules file that does
                          not read blocks: it is never read around.
  lint: stealth           any term on the closed denylist in
                          `.atelier/memory/handles.private.md`, case-insensitive
                          and whole-word. Block. **If `handles.md` declares the
                          companion and the checkout does not have it, this
                          blocks too**: a missing private half is an incomplete
                          read, and the check never passes vacuously.
  lint: partner tags      every `partner_tags` entry is a handle on a cleared
                          row of `.atelier/memory/handles.md` that is marked
                          `verified`, and that row's themes cell clears it on
                          this item's theme. Block - "when in doubt, cut the
                          tag".
  lint: what we do not claim   the post carries the honest limit: either a
                          `limit` field quoted verbatim from the post, in the
                          post's own words, or (as before) a "what we do not
                          claim" sentence. Block: the limit is what makes the
                          rest credible, and no mechanical edit can write it.
                          (Decision 2026-11-07-vary-the-template.)
  lint: tag line          the theme hashtag is in each teaser's tag line, and
                          no hashtag other than the item's theme appears
                          anywhere. Edit.
  lint: cta               the CTA is present, is the brand's post URL
                          (engine.json site.post_url) for the item's slug, and
                          both teasers carry it. Edit.
  lint: hook              title and both teaser hooks are 6-17 words, with no
                          hashtag and no emoji. A question is a hook like any
                          other since 2026-11-07. Edit.
  lint: shape             the draft's hook form, opening, closing, format and
                          logic against the three pieces dated just before it
                          in its stream: an edit when each of the three shares
                          at least four of the five with it - the same piece
                          with a new hashtag. A pass with fewer than three
                          before it, and when lint() is given no corpus. Edit,
                          never block.
                          Hook, tag line, cta and shape are house style: a
                          person may hand each to the reviewers
                          (`house_style.retired` in gate-rules.json), and the
                          code stops checking it only while the last gate
                          evaluation (gate_eval.py) shows the reviewers caught
                          every labelled case of it.
  lint: hypothesis        the item names the planning query it answers, a
                          one-variable hypothesis, a predicted band (below,
                          baseline, above) and a test id. Edit when any is
                          missing: a draft without a prediction cannot be
                          scored against one. (Plan v2, A8.)
  lint: cites             every id in the item's `cites` is a row of the
                          stream's claims register (`.atelier/memory/claims.md`),
                          not superseded, and corroborated (primary or
                          two-independent): block otherwise. A present-tense
                          capability sentence with the brand or "we" as its subject
                          needs a cite at grade evidenced: block without one.
                          An item with no cites at all: edit - name the rows
                          the post leans on. (Plan v2, A5.)

A post the team wrote (`drafted_by: team`: a control-page post, an announcement) is
judged by the checks that bind every surface - stream, status words, stealth,
partner tags (its @mentions among them) and cites, where a present-tense capability
sentence still needs an evidenced cite but a missing `cites` list is no edit. The
limit, tag line, CTA, hook length, hypothesis and shape are the engine's drafting
discipline for theme posts; asked of a team post they blocked every one of them,
so none could ever be approved. `lint_text` and `announce_check.py` draw the same line.

Results are recorded in `gate.checks` in the same shape the model's checks use
- `{check, result, line, fix}`, `line` empty when the check is clean - and are
distinguished only by the `lint: ` prefix on the name, which is also the handle
`--write` uses to replace a previous run's entries rather than pile onto them.
A check result is `pass`, `edit` or `block`; the verdict over a set of checks
is `block` if any blocks, `pass-with-edits` if any edits, else `pass`.

`--write` merges the lint entries into the item's `gate`, ahead of the model's,
and recomputes `gate.verdict` as the worst of both halves. It therefore never
lowers a recorded block, and never approves: like the skill, this clears a
draft for Alpha or stops it.

CLI:
  python3 gate_lint.py                       # every item, one line each
  python3 gate_lint.py Q-2026-09-09-...      # one item, check by check
  python3 gate_lint.py --json                # the full result as JSON
  python3 gate_lint.py --write [<id> ...]    # record into gate.checks
Exit status is 1 when any item linted blocks, 0 otherwise.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import memory  # noqa: E402
import config  # noqa: E402
import repo  # noqa: E402

PREFIX = "lint: "

# Ordered worst-last, so `max` over a set of results is the verdict-bearing one.
RANK = {"pass": 0, "edit": 1, "block": 2}
VERDICT = {0: "pass", 1: "pass-with-edits", 2: "block"}
RECORDED_RANK = {v: k for k, v in VERDICT.items()}

HASHTAG = re.compile(r"#[A-Za-z][A-Za-z0-9_]*")
# Real emoji blocks only. Em dashes, curly quotes and arrows are house
# punctuation and must not read as an emoji.
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]")

# The brand's rules are data, not code: `.atelier/memory/gate-rules.json` (a
# stream's own under streams/<slug>/), read through memory.load_gate_rules.
# Status words are (regex, fix) pairs: a word or form status.md forbids in
# public copy, and the cleared form to use instead. The cleared hedges are the
# cleared forms themselves, masked before the scan so the hedge passes and an
# upgrade of it does not. Both ship empty: a brand fills them from its
# status.md when it is written (TEMPLATE-CONTRACT.md, "Not done"), and until
# then `lint: status words` passes every item. The capability verbs and the
# house-style switches (hook length, the honest limit, the tag line) are in the
# same file.


def rules(slug=None):
    """The gate rules of a stream (None: the root stream), as memory.load_gate_rules returns them.

    Raises memory.SharedMemoryError when the file does not read; every check
    that uses a rule turns that into a block, never a pass."""
    return memory.load_gate_rules(slug)


NO_CLAIM = re.compile(r"what we do not claim", re.I)

# A capability sentence: the brand (or "we") as subject, a present-tense verb
# of running or providing something. Negations and design language are masked
# first, so "we do not settle" and "<Brand> plans to provide" are not caught.
BRAND_NAME = memory.DEFAULT_STREAM_NAME


def capability_pattern(brand_name, verbs=None):
    """The capability-sentence regex for a brand name and the verbs of its gate rules
    (the standard verbs when none are given; the module's CAPABILITY is that for the root stream)."""
    verbs = list(verbs or memory.DEFAULT_CAPABILITY_VERBS)
    return re.compile(
        r"\b(?:" + re.escape(brand_name) + r"|we)\s+(?:now\s+|already\s+|today\s+)?"
        r"(?:" + "|".join(verbs) + r")\b", re.I)


CAPABILITY = capability_pattern(BRAND_NAME)


def capability_for(slug=None):
    """The capability pattern a stream's text is read with: its own name as the subject, its own verbs."""
    name = BRAND_NAME
    if slug and slug != memory.DEFAULT_STREAM:
        name = memory.stream(slug)["name"]
    return capability_pattern(name, rules(slug)["capability_verbs"])
CAPABILITY_MASK = re.compile(
    r"\b(?:do(?:es)?\s+not|don't|doesn't|never|cannot|can't|will|would|could|"
    r"plans?\s+to|intends?\s+to|aims?\s+to|is\s+designed\s+to|are\s+designed\s+to|"
    r"is\s+building|are\s+building|if\s+we|should\s+we|when\s+we)\b[^.!?\n]*", re.I)


class LintError(RuntimeError):
    """The lint could not be performed. Never silently degraded into a pass."""


# ── the surfaces a check reads ──────────────────────────────────────────────

def surfaces(item):
    """The four pieces of copy that ship, named so a fix can say which one."""
    return [
        ("title", item.get("title", "")),
        ("post", item.get("post", "")),
        ("teaser_linkedin", item.get("teaser_linkedin", "")),
        ("teaser_x", item.get("teaser_x", "")),
    ]


def _line_of(text, pos):
    """The whole line a match sits on - the quote the gatekeeper must show."""
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text[start:end if end != -1 else len(text)].strip()


def _last_line(text):
    """The last non-empty line - what a check quotes when the fault is that
    something required is not there, so an absence still shows Alpha a place."""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    return lines[-1] if lines else ""


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _mask(text, hedges=()):
    """Blank out the cleared hedges before a banned-word scan."""
    for hedge in hedges:
        text = re.sub(re.escape(hedge), " " * len(hedge), text, flags=re.I)
    return text


def check(name, result="pass", line="", fix=""):
    """One entry in `gate.checks`, in the shape the model's checks use."""
    return {"check": PREFIX + name, "result": result, "line": line, "fix": fix}


def hooks(item):
    """The three hook lines: the title, and the first line of each teaser."""
    out = [("title", item.get("title", "").strip())]
    for field in ("teaser_linkedin", "teaser_x"):
        first = (item.get(field, "") or "").strip().split("\n")[0].strip()
        out.append((field, first))
    return [(f, h) for f, h in out if h]


# ── the seven checks ────────────────────────────────────────────────────────

def check_stream(item, slug=None):
    name = str(item.get("stream") or "").strip()
    if not name:
        return check("stream", "block", "stream: (missing)",
                     "The item names no stream. Every record names the stream it serves "
                     "(A3); the gate cannot choose a memory to read it against.")
    if name == repo.BOTH:
        return check("stream", "block", f"stream: {name}",
                     "An item that serves two streams is split before it is drafted "
                     "further (the single-pillar test). Make it one stream's item.")
    try:
        slug = memory.slug_for(name)
    except memory.SharedMemoryError as e:
        return check("stream", "block", f"stream: {name}", f"{e}. Register the stream or fix the item.")
    d = memory.stream_dir(slug)
    if not os.path.isdir(d):
        return check("stream", "block", f"stream: {name}",
                     f"The memory directory for {slug} is missing: {os.path.relpath(d, memory.REPO)}. "
                     "Nothing is gated against another stream's memory.")
    try:
        tags = memory.theme_tags(slug)
    except memory.SharedMemoryError as e:
        return check("stream", "block", f"stream: {name}", f"{slug}'s themes.md did not read: {e}")
    theme = (item.get("theme") or "").strip()
    if theme and theme not in tags:
        return check("stream", "block", f"theme: {theme}",
                     f"{theme} is not a theme of the {slug} stream "
                     f"({', '.join(tags) if tags else 'its themes.md has no rows yet'}). "
                     "A hashtag not in the stream's themes.md is not a theme.")
    return check("stream", "pass", f"stream: {name}",
                 f"Gated against the {slug} memory at {os.path.relpath(d, memory.REPO)}.")


def resolve_slug(item):
    """The registry slug the item is gated against, or None when it has none
    (`lint: stream` then blocks and the other checks read the root stream's memory only
    to produce their lines; the verdict is already block)."""
    try:
        return memory.slug_for(str(item.get("stream") or ""))
    except memory.SharedMemoryError:
        return None


def check_status_words(item, slug=None):
    return scan_status_words(surfaces(item), slug)


def scan_status_words(fields, slug=None):
    """Text-level: the stream's status rules (gate-rules.json) over `[(field, text)]`."""
    try:
        r = rules(slug)
    except memory.SharedMemoryError as e:
        return check("status words", "block", "",
                     f"The gate rules did not read, so the status scan blocks rather than passing: {e}")
    words, hedges = r["status_words"], r["cleared_hedges"]
    for field, text in fields:
        masked = _mask(text, hedges)
        for pattern, fix in words:
            m = re.search(pattern, masked, re.I)
            if m:
                return check("status words", "block", _line_of(text, m.start()),
                             f"{field}: {fix}")
    if not words:
        return check("status words", "pass", "",
                     "No status rules are written for this stream yet (`status_words` of its "
                     "gate-rules.json is empty); nothing to scan title, post or teasers for.")
    return check("status words", "pass", "",
                 f"None of the {len(words)} status.md forms in title, post or teasers.")


def check_stealth(item, slug=None):
    return scan_stealth(surfaces(item) + [("partner_tags", " ".join(item.get("partner_tags") or []))], slug)


def scan_stealth(fields, slug=None):
    """Text-level: the closed denylist over `[(field, text)]`, failing closed
    when handles.private.md is declared and missing."""
    try:
        handles = memory.load_handles(slug)
    except memory.SharedMemoryError as e:
        return check("stealth", "block", "", f"{slug or memory.DEFAULT_STREAM}: handles.md did not read: {e}")
    if not handles["private"]["present"]:
        if memory.private_expected(slug):
            return check(
                "stealth", "block", "",
                f"{os.path.relpath(handles['private']['path'], memory.REPO)} is "
                "declared by handles.md and missing from this checkout. The "
                "denylist cannot be read, so the stealth check blocks rather "
                "than passing vacuously. Restore the companion and re-run.")
        raise LintError(
            "handles.md no longer declares the private companion; the denylist "
            "has no home. Fix shared memory before running the gate.")
    terms = memory.denylist(slug)
    for field, text in fields:
        for term in terms:
            pattern = r"\b" + r"\s+".join(re.escape(w) for w in term.split()) + r"\b"
            m = re.search(pattern, text, re.I)
            if m:
                return check("stealth", "block", _line_of(text, m.start()),
                             f'{field}: "{term}" is on the closed denylist in '
                             "handles.private.md. Stealth is stealth until "
                             "proven - cut the line, whatever the source thread "
                             "was discussing.")
    return check("stealth", "pass", "",
                 f"None of the {len(terms)} denylist terms appears in title, post, "
                 "teasers or partner tags.")


def check_partner_tags(item, slug=None):
    return scan_partner_tags(list(item.get("partner_tags") or []), (item.get("theme") or "").strip(), slug)


def scan_partner_tags(tags, theme="", slug=None):
    """Text-level: every tag is a verified handle on a cleared row (and cleared
    for `theme` when one is named)."""
    tags = list(tags)
    if not tags:
        return check("partner tags", "pass", "",
                     "No partner tag to clear. A tag implies the partner follows; "
                     "no tag claims nothing.")
    try:
        taggable = memory.taggable_handles(slug)
    except memory.SharedMemoryError as e:
        return check("partner tags", "block", ", ".join(tags), f"{slug or memory.DEFAULT_STREAM}: handles.md did not read: {e}")
    known = {}
    for party, row in taggable.items():
        for handle in (row["x"], row["linkedin"]):
            if handle:
                known[handle.lstrip("@").lower()] = party
    for tag in tags:
        party = known.get(tag.lstrip("@").lower())
        if not party:
            return check("partner tags", "block", tag,
                         f'"{tag}" is not a verified handle on a cleared row of '
                         "handles.md. A handle is tagged only if its owner is on "
                         "the cleared list and its row is marked verified; "
                         "anything collect is a placeholder. Cut the tag.")
        cleared = taggable[party]["themes"]
        if theme and not any(t.lower() == theme.lower() for t in cleared):
            return check("partner tags", "block", tag,
                         f"handles.md clears {party} for "
                         f"{', '.join(cleared) or 'no theme'}, not for {theme}. "
                         "The themes cell governs the tag together with the "
                         "status: a party can be cleared to name and cleared for "
                         "no tag on this theme. Cut the tag.")
    named = ", ".join(sorted({known[t.lstrip('@').lower()] for t in tags}))
    return check("partner tags", "pass", "",
                 f"Every partner tag is a verified handle on a cleared row, and "
                 f"handles.md clears it on {theme}: {named}.")


def _style(slug, key):
    """One house-style switch of the stream's gate rules; a rules file that does not read
    keeps the check on (the status scan is what blocks on it)."""
    try:
        return rules(slug)["house_style"][key]
    except memory.SharedMemoryError:
        return {"hook_words": memory.DEFAULT_HOOK_WORDS}.get(key, True)


TEASERS = {"linkedin": "teaser_linkedin", "x": "teaser_x"}


def format_channels(item, slug=None):
    """The channels the item's format ships on (formats.json). An item with no format, or one the
    stream does not list, is held to the theme post's: an article and both teasers."""
    fmt = str(item.get("format") or "").strip() or memory.DEFAULT_FORMAT
    try:
        row = memory.load_formats(slug).get(fmt)
    except memory.SharedMemoryError:
        row = None
    return list((row or memory.DEFAULT_FORMATS[memory.DEFAULT_FORMAT])["channels"])


def _teaser_fields(item, slug=None):
    return [TEASERS[c] for c in format_channels(item, slug) if c in TEASERS]


def _body(item, slug=None):
    """The piece the honest limit belongs in: the post, or for a format with no article (a
    thread, a short take) the teasers it ships as."""
    if "blog" in format_channels(item, slug):
        return item.get("post", "") or ""
    return "\n\n".join(item.get(f, "") or "" for f in _teaser_fields(item, slug))


def check_no_claim(item, slug=None):
    if not _style(slug, "what_we_do_not_claim"):
        return check("what we do not claim", "pass", "",
                     "Switched off for this stream (house_style.what_we_do_not_claim in its gate-rules.json).")
    post = _body(item, slug)
    limit = str(item.get("limit") or "").strip()
    if limit:
        if limit in post:
            return check("what we do not claim", "pass", limit,
                         "The honest limit is in the post, in its own words (decision "
                         "2026-11-07-vary-the-template).")
        return check("what we do not claim", "block", limit,
                     "The `limit` field quotes a sentence the post does not carry. "
                     "Quote the post's honest limit verbatim, or put it in the post.")
    m = NO_CLAIM.search(post)
    if not m:
        # The line quoted for an absence is the site of the absence: the last
        # line of the post, where the honest sentence belongs.
        return check("what we do not claim", "block", _last_line(post),
                     "The post says nowhere what we do not claim or have not shipped. "
                     "Write that limit in the post's own words and quote it in a "
                     "`limit` field (decision 2026-11-07-vary-the-template). Alpha "
                     "cannot read a verdict off a post that never says what is unshipped.")
    return check("what we do not claim", "pass", _line_of(post, m.start()),
                 "The honest sentence is present, under the fixed heading. It passes; "
                 "the writer should not default to it (decision 2026-11-07).")


def check_tag_line(item, slug=None):
    if not _style(slug, "tag_line"):
        return check("tag line", "pass", "",
                     "Switched off for this stream (house_style.tag_line in its gate-rules.json).")
    theme = (item.get("theme") or "").strip()
    if not theme.startswith("#"):
        return check("tag line", "edit", theme,
                     "The item names no theme hashtag, so nothing can carry it. "
                     "Set `theme` to one of the eight tags in themes.md.")
    for field, text in surfaces(item):
        for m in HASHTAG.finditer(text):
            if m.group(0).lower() != theme.lower():
                return check("tag line", "edit", _line_of(text, m.start()),
                             f"{field}: {m.group(0)} is not this item's theme "
                             f"({theme}). One theme per item - a post that tags "
                             "two themes claims a licence it was not graded for.")
    for field in _teaser_fields(item, slug):
        text = item.get(field, "") or ""
        if not any(h.lower() == theme.lower() for h in HASHTAG.findall(text)):
            return check("tag line", "edit", _last_line(text),
                         f"{field}: the tag line does not carry {theme}. Insight "
                         "posts claim a theme hashtag - add the tag line above "
                         "the CTA.")
    return check("tag line", "pass", "",
                 f"Every teaser of its format carries {theme} and no other hashtag "
                 "appears in title, post or teasers.")


def check_cta(item, slug=None):
    cta = (item.get("cta") or "").strip()
    teasers = _teaser_fields(item, slug)
    if "blog" not in format_channels(item, slug):
        if cta:
            return check("cta", "edit", cta,
                         f"The format ({item.get('format')}) has no article, so the link points at a "
                         "page the note never writes. Drop the CTA, or draw a format with a post.")
        return check("cta", "pass", "",
                     f"The format ({item.get('format')}) has no article; there is no post to link back to.")
    slug = (item.get("slug") or "").strip()
    template = str(config.cfg("site.post_url", "https://www.example.com/insights/{slug}"))
    if not cta:
        return check("cta", "edit", _last_line(item.get("teaser_linkedin", "")),
                     "No CTA. Every teaser ends with the link back to the post "
                     f"on the brand's site: {template.replace('{slug}', '<slug>')}.")
    expected = template.format(slug=slug) if slug else ""
    if expected and cta != expected:
        return check("cta", "edit", cta,
                     f"The CTA does not match the item's slug ({slug}). The link "
                     f"the teasers carry must be {expected}, or the teaser points "
                     "at a page the note does not write.")
    shape = re.escape(template).replace(re.escape("{slug}"), r"[a-z0-9-]+")
    if not slug and not re.fullmatch(shape, cta):
        return check("cta", "edit", cta,
                     "The CTA is not a post URL on the brand's site (engine.json "
                     "site.post_url). Website first: the teasers link back to the post.")
    for field in teasers:
        if cta not in (item.get(field, "") or ""):
            return check("cta", "edit", _last_line(item.get(field, "")),
                         f"{field} does not carry the CTA {cta}. A teaser without "
                         "the link is reach with nowhere to land.")
    return check("cta", "pass", "",
                 f"CTA {cta} matches the slug and is carried by both teasers.")


def check_hook(item, slug=None):
    span = _style(slug, "hook_words")
    for field, hook in hooks(item):
        words = len(hook.split())
        if span and not span[0] <= words <= span[1]:
            return check("hook", "edit", hook,
                         f"{field}: {words} words, outside the evidenced {span[0]}-"
                         f"{span[1]} range (voice.md; house_style.hook_words). Cut it to "
                         "one of the five house patterns, period-separated.")
        if HASHTAG.search(hook):
            return check("hook", "edit", hook,
                         f"{field}: no hashtag in the hook line. Tags live in the "
                         "tag line, under the teaser.")
        if EMOJI.search(hook):
            return check("hook", "edit", hook,
                         f"{field}: no emoji in the hook. The editorial register "
                         "(voice.md) carries none.")
    counts = ", ".join(f"{f} {len(h.split())}" for f, h in hooks(item))
    return check("hook", "pass", "",
                 f"Hooks in range and clean ({counts} words), no hashtag or emoji.")


def check_cites(item, slug=None):
    return scan_cites(surfaces(item), item.get("cites"), slug, last_line=_last_line(item.get("post", "")))


def scan_cites(fields, cites, slug=None, last_line="", require_cites=True):
    """Text-level: cited rows are current and corroborated, and a present-tense
    capability sentence in `[(field, text)]` needs a cite at grade evidenced.
    `require_cites=False` passes an item that cites nothing and claims nothing."""
    cites = [str(c).strip() for c in (cites or []) if str(c).strip()]
    try:
        register = memory.load_claims(slug)
    except SharedMemoryErrorAlias as e:
        # A register that does not parse cannot clear anything; a missing one
        # for a stream blocks that stream.
        return check("cites", "block", "cites: [" + ", ".join(cites) + "]",
                     f"{slug or memory.DEFAULT_STREAM}: the claims register did not read: {e}")
    quoted = "cites: [" + ", ".join(cites) + "]"
    for cid in cites:
        ok, why = memory.citable(cid, claims=register)
        if not ok:
            return check("cites", "block", quoted,
                         f"{why}. A draft may lean only on a current, corroborated row "
                         f"of .atelier/memory/claims.md; supersede or corroborate the "
                         f"row through /corpus-update, or cut what leans on it.")
    evidenced = [c for c in cites if register[c]["grade"] == "evidenced"]
    try:
        capability = capability_for(slug)
    except memory.SharedMemoryError as e:
        return check("cites", "block", quoted,
                     f"The gate rules did not read, so no capability sentence can be cleared: {e}")
    for field, text in fields:
        for sentence in _sentences(text):
            masked = CAPABILITY_MASK.sub("", sentence)
            m = capability.search(masked)
            if m and not evidenced:
                return check("cites", "block", sentence,
                             f"{field}: a present-tense capability sentence needs a "
                             f"cite at grade evidenced, and this item cites "
                             f"{'none' if not cites else 'only ' + ', '.join(cites) + ' (not evidenced)'}. "
                             f"Cite the evidenced row, or rewrite to design language.")
    if not cites and not require_cites:
        return check("cites", "pass", quoted, "No cites, and no present-tense capability sentence to cite for.")
    if not cites:
        return check("cites", "edit", last_line,
                     "No cites. Name the claims register rows the post leans on "
                     "(`cites: [C-…]`); an evergreen argument that leans on no "
                     "claim of the brand's own still cites the standard or fact it reads from.")
    return check("cites", "pass", quoted,
                 f"{len(cites)} cite(s) resolve to current, corroborated rows"
                 f"{' (' + str(len(evidenced)) + ' evidenced)' if evidenced else ''}.")


SharedMemoryErrorAlias = memory.SharedMemoryError


def check_hypothesis(item, slug=None):
    import predictions
    missing = []
    if str(item.get("query") or "").strip() not in predictions.QUERIES:
        missing.append(f"query (one of {', '.join(predictions.QUERIES)})")
    if not str(item.get("hypothesis") or "").strip():
        missing.append("hypothesis (one variable: hook form, format, length or angle)")
    if str(item.get("predicted") or "").strip() not in predictions.BANDS:
        missing.append(f"predicted (one of {', '.join(predictions.BANDS)})")
    if not str(item.get("test_id") or "").strip():
        missing.append("test_id (T-<slug>-<n>, or none)")
    if missing:
        return check("hypothesis", "edit",
                     f"query: {item.get('query') or '—'}; hypothesis: {str(item.get('hypothesis') or '—')[:60]}; "
                     f"predicted: {item.get('predicted') or '—'}; test_id: {item.get('test_id') or '—'}",
                     "Missing " + "; ".join(missing) + ". theme-post step 4c: every draft "
                     "names the query it answers, one variable, a predicted band and a "
                     "test id before it leaves the queue (plan v2, A8).")
    return check("hypothesis", "pass",
                 f"{item.get('query')}: {str(item.get('hypothesis'))[:80]} -> {item.get('predicted')} ({item.get('test_id')})",
                 "Query, hypothesis, predicted band and test id are all present.")

# ── shape (decision 2026-11-07-vary-the-template) ───────────────────────────

MONTHS = ("January|February|March|April|May|June|July|August|September|October|"
          "November|December")
NEWS_OPENING = re.compile(rf"^(On|In|Last|By|Since|Earlier)\b[^.]{{0,60}}?\b(\d{{1,2}}\s+)?({MONTHS}|week|month)\b")
SHAPE_WINDOW = 3


def _paragraphs(text):
    return [p.strip() for p in (text or "").split("\n") if p.strip()]


#: How many of the five a draft may share with each of the pieces before it and still vary.
#: Pieces written before formats existed all carry the same format, so two of hook form,
#: opening and closing in common is still what makes a repeat, as it was.
SHAPE_SHARED = 4
#: the calendar's label on a note written before formats existed
LEGACY_FORMATS = ("", "Observation")


def shape_of(item):
    """(hook form, opening, closing, format, logic) of one piece."""
    title = (item.get("title") or "").strip()
    sentences = [x for x in re.split(r"(?<=[.!?])\s+", title) if x]
    if title.endswith("?"):
        hook = "question"
    elif len(sentences) >= 2 and all(x.endswith(".") for x in sentences):
        hook = "short declaratives"
    elif len(sentences) == 1:
        hook = "single sentence"
    else:
        hook = f"{len(sentences)} sentences"
    paras = _paragraphs(item.get("post"))
    opening = "dated news hook" if paras and NEWS_OPENING.search(paras[0]) else "other"
    closing = "fixed heading" if paras and NO_CLAIM.match(paras[-1]) else "own words"
    fmt = str(item.get("format") or "")
    fmt = memory.DEFAULT_FORMAT if fmt in LEGACY_FORMATS else fmt
    return (hook, opening, closing, fmt, str(item.get("logic") or ""))


def _date_of(item):
    return str((item.get("slot") or {}).get("date") or item.get("date") or "")


# A piece that never ran and will not (rejected, sent back, replaced by its
# redraft) is not "the piece before" anything; a reader never saw it.
NOT_RUNNING = ("rejected", "rewrite", "superseded")


def check_shape(item, slug=None, corpus=None):
    if not corpus:
        return check("shape", "pass", "", "No corpus given; the shape check runs from gate_lint.py's own CLI.")
    mine, day, stream = shape_of(item), _date_of(item), item.get("stream")
    before = sorted((p for p in corpus
                     if p.get("id") != item.get("id") and p.get("stream") == stream and p.get("post")
                     and p.get("alpha_status") not in NOT_RUNNING and p.get("id") != item.get("redraft_of")
                     and _date_of(p) and day and _date_of(p) < day), key=_date_of)[-SHAPE_WINDOW:]
    if len(before) < SHAPE_WINDOW:
        return check("shape", "pass", "", f"Fewer than {SHAPE_WINDOW} pieces before it in {stream}; nothing to compare.")
    said = " / ".join(x or "no logic" for x in mine)
    if all(sum(a == b for a, b in zip(mine, shape_of(p))) >= SHAPE_SHARED for p in before):
        return check("shape", "edit", said,
                     f"Same shape as the {SHAPE_WINDOW} pieces before it ({', '.join(p.get('id', '?') for p in before)}): "
                     "change at least two of hook form, opening, closing, format and logic - another format "
                     "or logic from the draw, a question or a scene for the hook, a reader's problem before "
                     "the news, the limit in the post's own words (decisions 2026-11-07-vary-the-template "
                     "and 2026-11-13-autonomy-variety-engagement).")
    return check("shape", "pass", said, "Varies from the pieces before it.")


MENTION = re.compile(r"(?<![\w@])@[A-Za-z0-9_]{1,30}")


def lint_text(stream, channel, text, cites=None):
    """The text-level gate for a reply or comment: `{verdict, checks}` in the
    shape `lint` returns. Runs the stream, status-word, stealth, partner-handle
    and capability-needs-evidenced-cite predicates over the one text; every
    @mention is read as a partner tag. `channel` is carried for the caller's
    record; no predicate here differs by channel."""
    text = text or ""
    item = {"stream": stream}
    slug = resolve_slug(item)
    fields = [("text", text)]
    mentions = MENTION.findall(text)
    checks = [
        check_stream(item, slug),
        scan_status_words(fields, slug),
        scan_stealth(fields, slug),
        scan_partner_tags(mentions, "", slug),
        scan_cites(fields, cites, slug, last_line=_last_line(text), require_cites=False),
    ]
    return {"verdict": verdict_of(checks), "checks": checks, "channel": channel}


def lint_proposal(proposal, stream=None):
    """`lint_text` over one engagement proposal (`state/engagement.json`): its
    `draft_comment`, on its `platform`, with its optional `cites` list."""
    return lint_text(stream or proposal.get("stream") or "", proposal.get("platform", ""),
                     proposal.get("draft_comment", ""), proposal.get("cites"))


CHECKS = (check_stream, check_status_words, check_stealth, check_partner_tags, check_no_claim,
          check_tag_line, check_cta, check_hook, check_cites, check_hypothesis, check_shape)


def check_team_partner_tags(item, slug=None):
    """A team post's partner tags: the listed ones and every @mention in its copy, as lint_text reads a text."""
    mentions = [m for _f, text in surfaces(item) for m in MENTION.findall(text or "")]
    return scan_partner_tags(list(item.get("partner_tags") or []) + mentions, (item.get("theme") or "").strip(), slug)


def check_team_cites(item, slug=None):
    return scan_cites(surfaces(item), item.get("cites"), slug, last_line=_last_line(item.get("post", "")),
                      require_cites=False)


TEAM_CHECKS = (check_stream, check_status_words, check_stealth, check_team_partner_tags, check_team_cites)

#: The house-style checks that may leave the code for the reviewers (decision
#: 2026-11-13-autonomy-variety-engagement), and the function each one is.
RETIRABLE = memory.RETIRABLE_RULES
RETIRABLE_CHECKS = {check_hook: "hook", check_tag_line: "tag line", check_cta: "cta", check_shape: "shape"}


def retired(name, slug=None):
    """`(True, why)` when a house-style check is the reviewers' and no longer the code's.

    Two things must hold, and both are checked at every run: a person listed the rule under
    `house_style.retired` in the stream's gate-rules.json, and the last gate evaluation
    (gate_eval.py, on the labelled set as it stands now) shows the reviewers caught every case
    of that rule. Either one missing and the code keeps checking: a rule is never retired on
    an assumption."""
    try:
        listed = name in rules(slug)["house_style"]["retired"]
    except memory.SharedMemoryError:
        return False, "the gate rules did not read"
    if not listed:
        return False, "not retired"
    import gate_eval
    return gate_eval.cleared(name)


# ── running them ────────────────────────────────────────────────────────────

def verdict_of(checks):
    return VERDICT[max([RANK[c["result"]] for c in checks] or [0])]


def lint(item, corpus=None, retire=True):
    """Every deterministic check over one item: `{verdict, checks}`.

    The checks read the memory of the item's stream (A7). An item with no
    resolvable stream is blocked by `lint: stream`; the remaining checks then
    run against the root stream's memory so their lines still show a person something.
    A house-style check that is retired (`retired`) is recorded as a pass that says so;
    `retire=False` runs every check whatever was retired (gate_eval.py measures with it)."""
    slug = resolve_slug(item)
    if item.get("drafted_by") == repo.TEAM_BY:
        checks = [fn(item, slug) for fn in TEAM_CHECKS]
    else:
        checks = []
        for fn in CHECKS:
            name = RETIRABLE_CHECKS.get(fn)
            if retire and name:
                gone, why = retired(name, slug)
                if gone:
                    checks.append(check(name, "pass", "", f"Retired from the code: the reviewers read it as house style ({why})."))
                    continue
            checks.append(fn(item, slug, corpus) if fn is check_shape else fn(item, slug))
    return {"verdict": verdict_of(checks), "checks": checks}


def merge(gate, result):
    """The item's gate with this run's lint entries ahead of the model's.

    A previous run's entries are replaced rather than added to, and the verdict
    is recomputed over both halves, so a recorded block is never lowered.
    """
    gate = dict(gate or {})
    kept = [c for c in (gate.get("checks") or [])
            if not str(c.get("check", "")).startswith(PREFIX)]
    gate["checks"] = result["checks"] + kept
    # Worst of both halves - and never below the verdict already recorded. A
    # model block can rest on judgment it wrote into `note_for_alpha` rather
    # than on a check, and a recomputation from checks alone would clear it.
    rank = max([RANK[c["result"]] for c in gate["checks"] if c.get("result") in RANK]
               + [RECORDED_RANK.get(gate.get("verdict"), 0)])
    gate["verdict"] = VERDICT[rank]
    gate["linted_at"] = repo.dt.datetime.now(repo.dt.timezone.utc).isoformat(timespec="seconds")
    gate["linted_by"] = "gate_lint.py"
    return gate


def items_by_id():
    """Every item the engine holds: the vault's notes, then the drafting inbox.

    The note is the record, so a vault item wins over a `queue.json` entry of
    the same id; an item the writer has just appended and the vault has not
    ingested yet is linted from the inbox.
    """
    items = {}
    try:
        inbox = repo.load_queue()
    except OSError:
        # The index is a derivation; its absence loses nothing and must not
        # stop the gate reading the notes.
        inbox = []
    for item in inbox:
        if item.get("id"):
            items[item["id"]] = item
    for item in repo.load_items():
        items[item["id"]] = item
    return items


def write_result(item_id, item, result):
    """Record the lint into `gate.checks` where the item actually lives."""
    return write_gate(item_id, merge(item.get("gate"), result))


def write_gate(item_id, gate):
    """Write an item's whole `gate` where the item lives: its note, or its queue entry while it
    has none. Used by this script's `--write` and by review.py, the two writers of a verdict."""
    if item_id in repo.scan_notes():
        repo.set_fields(item_id, {"gate": gate})
        return "note"
    queue = repo.load_queue()
    for entry in queue:
        if entry.get("id") == item_id:
            entry["gate"] = gate
            break
    else:
        raise LintError(f"{item_id}: neither a calendar note nor a queue entry")
    path = os.path.join(repo.STATE, "queue.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=1, ensure_ascii=False)
        f.write("\n")
    return "queue.json"


def main(argv=None):
    p = argparse.ArgumentParser(description="the deterministic half of the gate")
    p.add_argument("ids", nargs="*", help="item ids (default: every item)")
    p.add_argument("--write", action="store_true",
                   help="record the results into the item's gate.checks")
    p.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = p.parse_args(argv)

    try:
        items = items_by_id()
    except Exception as e:  # a shared-memory or vault read that did not resolve
        return f"gate_lint: {e}"
    ids = args.ids or sorted(items)
    missing = [i for i in ids if i not in items]
    if missing:
        return f"gate_lint: no such item: {', '.join(missing)}"
    if not ids:
        # Say that the gate ran and what the first draft will meet, rather than
        # exit silently: a fresh clone has no queue and no notes yet.
        try:
            present = memory.load_handles()["private"]["present"]
        except memory.SharedMemoryError:
            present = False
        denylist = "present" if present else "missing, every item would block (handles.private.md)"
        if args.json:
            print("{}")
        else:
            print(f"gate_lint: no items (state/queue.json and Content/Calendar/ are empty); denylist: {denylist}")
        return 0

    try:
        import rewrites  # the person's last act over the note's, before the distributor writes it
        corpus = rewrites.effective(list(items.values()))
    except ImportError:  # a checkout without rewrites.py judges the notes as they stand
        corpus = list(items.values())
    out = {}
    for item_id in ids:
        item = items[item_id]
        try:
            result = lint(item, corpus=corpus)
        except (LintError, memory.SharedMemoryError) as e:
            return f"gate_lint: {e}"
        recorded = (item.get("gate") or {}).get("verdict", "")
        merged = merge(item.get("gate"), result)["verdict"]
        out[item_id] = {"lint": result["verdict"], "recorded": recorded,
                        "merged": merged, "checks": result["checks"]}
        if args.write:
            out[item_id]["written_to"] = write_result(item_id, item, result)

    if args.json:
        print(json.dumps(out, indent=1, ensure_ascii=False))
    else:
        for item_id, r in out.items():
            print(f"{item_id}  lint {r['lint']}"
                  f"  recorded {r['recorded'] or '—'}  merged {r['merged']}"
                  + (f"  written to {r['written_to']}" if args.write else ""))
            if len(ids) == 1 or r["lint"] != "pass":
                for c in r["checks"]:
                    if len(ids) == 1 or c["result"] != "pass":
                        print(f"    {c['result']:<5} {c['check']}")
                        if c["line"]:
                            print(f"          line: {c['line'][:120]}")
                        if c["result"] != "pass":
                            print(f"          fix:  {c['fix']}")
    return 1 if any(r["lint"] == "block" for r in out.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
