---
name: claim-gate
description: The "zero claims of live or deployed capability ahead of delivery" check, the one rule of the doctrine phrased as a prohibition. Run on every draft before it enters the Alpha queue, and again before publish. Returns pass, pass-with-edits, or block, with the offending line quoted.
---

# claim-gate

The one key result the stream's doctrine sources (named in `status.md`) phrase
as a prohibition. This skill makes it mechanical so Alpha reads a verdict, not
a draft.

## sources of truth (read all of them, every time)

They are the **item's stream's** files (plan v2, A7): for the root stream the
root of `.atelier/memory/`; for any other stream the same file set under
`.atelier/memory/streams/<slug>/`, resolved from `.atelier/memory/streams.md`
by `scripts/memory.py`. Never read another stream's memory to fill a gap: a
stream whose file is missing, whose `handles.private.md` is absent, or whose
`themes.md` does not list the item's theme is blocked, with the reason named.

- `.atelier/memory/status.md`: what is evidenced. Where it disagrees with
  `project.md`, status.md wins.
- `.atelier/memory/instincts.md`: banned constructions and the cleared hedges.
- `.atelier/memory/themes.md`: the theme's licence status and cap (the
  *licence and layer* table), its differentiator and the fact it may link back
  to. Shared memory is the single source; `themes.json` carries only the
  engine's X search terms.
- `.atelier/memory/handles.md`: the cleared names and which handles are
  taggable, merged with `handles.private.md` where present.
- `.atelier/memory/claims.md`: the register every cite resolves against.

## the deterministic half runs first

`scripts/gate_lint.py` decides mechanically what needs no
judgment and records it into `gate.checks` as `lint: <name>` entries: the status
words of check 1, the stealth denylist of check 5, the taggable-handle half of
check 4, the hook and tag-line half of check 8, plus the CTA, the presence of
the "what we do not claim" sentence, and the item's `cites` against
`.atelier/memory/claims.md` (every id a current, corroborated row; a
present-tense capability sentence backed by a row at grade evidenced). The
`gatekeeper` runs it before reading, so the checks below are performed against
an item that already carries those verdicts. Read them, do not redo them, and
never overwrite one: they are reproducible and yours are not. A `lint:` entry
blocks the item on its own when `handles.private.md` is missing from the
checkout: an unreadable denylist is not a clean stealth check.

The status-word patterns and the cleared hedges are data, not code:
`status_words` and `cleared_hedges` of the stream's
`.atelier/memory/gate-rules.json`. They ship **empty** in the template. Until
the brand writes them from its `status.md`, `lint: status words` passes every
item and check 1 below is entirely your judgment.

## the checks, in order

1. **Status words.** Block on any self-description `status.md` does not
   evidence: certified, accredited, licensed, approved, registered, a
   membership or mark the brand does not hold, a jurisdiction or data-centre
   claim the record does not carry. The only cleared self-descriptions are the
   hedged forms `instincts.md` lists (the shape is *"is in the process of
   obtaining ..."*, with the date it was first published).
2. **Present-tense spec properties.** Block on any sentence where a specified
   but unshipped property wears the present indicative. The linter has
   already checked that a capability sentence has an evidenced cite; your
   judgment is whether the cited row actually supports *that* sentence (a row
   that evidences a demonstrable platform does not evidence "runs in
   production today"). Block on the operating verbs: "checks every ... before
   it settles", "enforces", "prevents", "live", "in production", "mainnet" or
   its equivalent in the brand's domain. Rewrite to design language ("is
   designed to", "the specification separates") or cut.
3. **Dates.** Block any launch, go-live or accreditation date that `status.md`
   does not carry with its source. The honest line is the gate, not a number.
4. **Names.** Every organisation named must be on the cleared list in
   `.atelier/memory/handles.md` (*cleared partners*), or be a third-party fact
   cited to that party's own publication (a standards body's own announcement
   is a fact, not a partner). Anyone else: cut, or attach *"in discussion,
   participation not confirmed"* only if Alpha has cleared it.
5. **Stealth.** Block on any term in the denylist held by
   `.atelier/memory/handles.private.md`, the gitignored companion merged on top
   of `.atelier/memory/handles.md` at read time. The check is case-insensitive
   and whole-word. If that companion is missing from the checkout, this check
   blocks; it never passes vacuously.
6. **Stats.** A number ships with its source and link or it does not ship.
   No count of third parties (members, licensees, issuers) as the brand's own
   statement: record the source and let the post say where it is published.
7. **Single-pillar test.** The draft serves one stream. Another stream is
   named only under a pair rule in `.atelier/memory/streams.md`, in the wording
   that rule allows. Any merge: block.
8. **Register.** Editorial/social copy: hooks 6 to 17 words, period-separated,
   no hashtag inside the hook line, no emoji, no hedge words in the hook. Theme
   tag and partner tags go in the teaser's tag line, not the hook. Newsroom
   boilerplate ("best-in-class", "next-generation", "robust") stays out.
9. **Licence.** Grade the theme from the *licence and layer* table in
   `.atelier/memory/themes.md`. If the theme is `held`, the draft may argue the
   standards principle only. Any brand capability, initiative, partner or date
   under a held theme: block.

## output

You return findings; you do not write the verdict. `scripts/review.py` looks
every sentence you quote up in the text, every `rests_on` up in the row you
cite, and stamps the verdict itself, keyed by the hash of the text. Its schema
is `engine review schema`. The sentences to
judge are the ones `engine review sentences
[<id>...]` prints: copy each `field` and `text` as printed and leave none out,
since a sentence left unjudged blocks the item.

A fact about a third party (another
body's publication, a regulator's words, a public event) may instead rest on a
source the item lists under `sources`: its `cite` is that source's id (`S1`)
and `rests_on` is copied from the source's `quote`. Never a source for a
sentence about the brand ("we", "our", the brand's name), a statistic or a
capability: those need a register row.

```json
{
  "items": [
    {
      "id": "Q-2026-11-05-exampletheme-1",
      "sentences": [
        {"field": "title", "text": "A wallet holds a credential.", "claim": false},
        {"field": "post", "text": "Acme operates a demonstrable issuance platform.", "claim": true,
         "cite": "C-acme-5", "rests_on": "operates a demonstrable issuance platform", "supported": true,
         "why": "the row says exactly this, in this tense"},
        {"field": "post", "text": "It runs in production for every issuer today.", "claim": true,
         "cite": "C-acme-5", "rests_on": "demonstrable issuance platform", "supported": false,
         "why": "a platform shown to auditors is not production for every issuer"}
      ],
      "checks": [
        {"check": "dates", "result": "pass"},
        {"check": "names", "result": "block", "line": "...quoted...", "fix": "..."}
      ],
      "note": "one sentence on what judgment remains for a person"
    }
  ]
}
```

- `sentences`: every sentence of `title`, `post`, `teaser_linkedin` and
  `teaser_x`, in order, word for word. A tag line or a bare link is not a
  sentence. A sentence you leave out blocks the item.
- `claim`: true when the sentence states a checkable fact about the brand, a
  partner, a number or a date. An argument about the general idea is not a
  claim.
- `cite`, `rests_on`, `supported`: for a claim only. The id must be one the
  item lists in its `cites`; the words must be copied from that row's `claim`
  cell; `supported` is whether that row carries this sentence in this tense.
  A claim with nothing to cite has `cite: null`, and blocks.
- `checks`: the checks above that are not about one sentence, by these names:
  `status words`, `present-tense spec`, `dates`, `names`, `stealth`, `stats`,
  `single-pillar`, `register`, `licence`. `register` is house style (the hook,
  the tag line, the link back to the post, the shape, boilerplate): report it
  as `edit` with the line quoted and a `fix` that starts with the rule it
  breaks (`hook:`, `tag line:`, `cta:` or `shape:`). It is advice, kept for
  the writer and a person; it never changes the verdict.

A second reviewer reads the same items with a different brief. Where the two
of you differ on a sentence, the item blocks, whichever of you was right.

The gate never approves. It clears a draft for a person, or for a stream a
person switched to automatic, or stops it.
