---
name: theme-post
description: Draft one piece on a theme in the format and logic the plan drew for it: by default the full post for the brand's own site with a LinkedIn teaser and an X teaser, or an X thread, a short take, a quote commentary, a question, a data note or a case story where the stream's formats.json has them. Three candidates that differ in one variable, ranked; the first goes to the gate. Use when a listening finding is content-shaped, or when a theme needs its introduction post.
---

# theme-post

Themes are *reach*: AI-assisted in sourcing, teasers and distribution, tagged,
unsynchronised, arguable by design. But *writing the theme insight* is Alpha.
So this skill drafts, labels the draft as a proposal, and sends it through
`claim-gate` into the queue. It never publishes.

## inputs

1. One finding from `state/signals.json` (or a theme tag for an introduction post).
2. `.atelier/memory/voice.md`: the brand's register; the evidenced headline
   patterns; the rhythm table (editorial, not newsroom).
3. `.atelier/memory/logics.md`: pick one logic and run it. The file says which
   logics need nothing shipped and which are strongest for which themes.
4. `.atelier/memory/themes.md`: the theme's *what* and *why it is different*:
   the post must land the differentiator, not just the topic. The same row names
   the fact the theme may link back to and the partner tags it clears; the
   licence table below it grades the theme licensed / licensed-with-hedge /
   held, which caps what the draft may claim. This file is the source every
   runtime reads; `themes.json` holds only the listening
   search terms and says nothing about a theme.
4b. `.atelier/memory/handles.md`: the handles behind those partner tags. A
   handle goes in a tag line only if its owner is on the cleared list *and* its
   row is marked `verified`; anything `collect` is a placeholder, and a blank
   cell is a value nobody has established. When in doubt, cut the tag.
5. The active campaign file under `.atelier/memory/campaigns/` for an open slot.
6. `.atelier/memory/formats.json`: the formats this stream may write in, each
   with its `structure` (the beats, in order), the `channels` it fits and its
   `length`. A stream without the file has one format, `theme-post`.
7. `state/planning.json`: for the item's theme, the
   `draw`: which `format` and which `logic` this draft is written in, the
   `kind` (proven, variation, experiment) and the `seed`. Code made the draw
   (`scripts/plan_queries.py`), weighted by how each format and logic scored
   before; you write what it drew.

## workflow

1. **Anchor.** Name the fact the post links back to (*insight posts claim a
   theme hashtag and link back to the fact*). A fact is a shipped component of
   the brand's own (few exist; see status.md) or an external, dated,
   primary-source event. If there is no fact, the post is evergreen and must
   run one of the logics `logics.md` marks as needing nothing shipped.
2. **Format and logic.** Take both from the draw. State the logic in one
   line before drafting, and read the format's `structure`: those beats, in
   that order, are the piece. The five-part structure of step 4 is the format
   `theme-post`; it is one format, not the only one. A format that fits one
   channel (an X thread, a short take) has no article: leave `post` empty and
   write the piece in the teaser field of each channel it fits. Where the
   format names a `skill` (`salon:x-thread` for a thread), use it for the
   format's own craft; the claims, the cites and the limit are still yours.
3. **Hook.** Run salon `hook-writing`'s six-angle drill; pick by the campaign
   goal (qualified citations, not clicks). Keep it 6 to 17 words,
   period-separated, in one of the house patterns from `voice.md`. Never a
   question on X.
4. **The piece.** For the format `theme-post`, the full post for the brand's
   site: 350 to 700 words, editorial register: "we" allowed, short
   declaratives, one figure callout at most and only with its source.
   Structure: hook, the change or the deadlock, the structural reading, the
   standing point (the differentiator `themes.md` names), the honest limit
   (one sentence, in the post's own words, quoted in `limit`). For any other
   format, the beats and the length `formats.json` gives it. Whatever the
   format, a piece that claims anything says what it does not claim.
4b. **Cites.** Name the rows of `.atelier/memory/claims.md` the post leans on,
   by id, under `cites`. Any sentence with the brand or "we" as subject and a
   present-tense capability verb needs a row at grade `evidenced`; a row at
   `watching` or `single`, or one that is superseded, cannot be cited and the
   gate blocks it. An evergreen piece that argues from a standard cites the
   standard's row (`C-<slug>-<n>`, the register's id shape). No row for what
   you want to say means the sentence is not sayable yet: rewrite to design
   language or cut. A fact about a third party that a finding carries (a
   body's publication, a regulator's words) may instead rest on that
   finding's evidence: copy it under `sources` as `{id: "S1", url, title,
   quote, finding}`, word for word, link the `url` in the post (in a teaser
   for a format with no post), and the gate checks the sentence against the
   quote. Never a source for the brand, "we", a statistic or a capability.
4c. **Query, hypothesis, prediction, test.** Read `state/planning.json`
   (written by `scripts/plan_queries.py` before drafting) and name under
   `query` which planning query this piece answers: `gaps`, `freshness`,
   `depth`, or `reactive` (a held-slot trigger) / `intro` (a theme's
   introduction post). Write `hypothesis` as one variable only (hook form,
   format, length or angle: "a two-sentence contrast hook beats a single
   declarative on this theme"), `predicted` as the band you expect against
   the stream's baseline for this platform and format (`below`, `baseline`,
   `above`), and `test_id` (`T-<slug>-<n>` from `state/tests.json` when the
   piece belongs to a live test, else `none`). The gate marks a draft
   without all four as pass-with-edits; the record is appended to
   `state/predictions.json` when the draft becomes a note, and scored at
   7 days.
5. **Teasers.** LinkedIn: 60 to 120 words, the conclusion not the setup, then a
   tag line `#Theme  @partner-handles` (handles taken from `handles.md`,
   `verified` rows only, and only where the theme's own `partner tags` cell
   clears them) and the CTA link. X: one hook line, one reframing line, tag
   line, link. Each teaser is re-cut, never copy-pasted. The CTA is the
   article's URL on the brand's site: `site.post_url` in `engine.json` with
   the slug filled (`repo.post_url(slug)`).
5b. **Three candidates.** Write three versions that differ in the one
   variable the hypothesis names (hook form, length, angle or opening) and in
   nothing else. Rank them with `salon:post-audit`. The first is the draft.
   The other two go on the item as `alternatives`: each `{variable, value,
   rank, why}` plus only those of `title`, `post`, `teaser_linkedin` and
   `teaser_x` that differ from the draft. They are what a person can swap in
   with `repo.py <id> --swap <n>`; a swapped-in text is gated again.
6. **Claim-gate.** Run `claim-gate` on the draft, as a self-check before it is
   queued. The verdict that counts is the reviewers' and `review.py`'s, later.
7. **Queue.** Append to `state/queue.json`, the inbox
   for a draft that is not in the vault yet. `/social-cycle` step 6 ingests it
   into `Content/Calendar/` and rebuilds that file from the notes, so append
   only; never rewrite an entry that already has a note. `stream` is the
   brand's name as `streams.md` spells it (`Acme` in a fresh clone).

```json
{
  "id": "Q-2026-11-05-theme-1",
  "theme": "#Theme", "stream": "Acme", "type": "Evergreen | Reactive | Milestone",
  "finding_id": "F3", "anchor": "...the fact...", "logic": "L4", "format": "theme-post",
  "draw": {"seed": "acme:#Theme:2026-11-05:1", "kind": "variation", "at": "2026-11-05"},
  "alternatives": [
    {"variable": "hook form", "value": "a question", "rank": 2, "why": "sharper, but a question on X underperformed twice",
     "title": "...", "teaser_x": "..."},
    {"variable": "hook form", "value": "a scene", "rank": 3, "why": "slower to the point", "title": "...", "teaser_linkedin": "...", "teaser_x": "..."}
  ],
  "title": "...the hook...", "post": "...", "teaser_linkedin": "...", "teaser_x": "...",
  "tags": ["#Theme"], "partner_tags": [], "cites": ["C-acme-4"], "cta": "https://www.example.com/insights/<slug>",
  "query": "gaps", "hypothesis": "hook form: a two-sentence contrast beats a single declarative", "predicted": "baseline", "test_id": "none",
  "gate": {"verdict": "pass", "checks": []},
  "slot": {"date": "2026-11-10", "platform": "Blog", "campaign": "<campaign slug>"},
  "freshness_deadline": "...", "alpha_status": "proposed", "drafted_by": "theme-writer", "drafted_at": "..."
}
```

## rules

- One pillar per output. A paired stream is never the narrator here.
- No hashtag, emoji or colon-as-hook in the hook line. Tags live in the tag line.
- Partner tags only from the cleared list, and only where the partner is
  actually part of the fact. A tag implies the partner "follows"; tagging a
  party we are pitching is a claim.
- The post says what we do not claim. That panel is what makes the rest credible.
- `format`, `logic` and `draw` are copied from the plan's draw, never chosen
  and never invented. The gate reads the last three pieces: a draft that
  shares hook form, opening, closing, format and logic with them comes back
  as an edit.
- `alpha_status` starts at `proposed`. Only Alpha moves it, on the desk.
