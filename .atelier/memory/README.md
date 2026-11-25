# .atelier/memory - the doctrine every script and agent reads

Shared memory is the single source for what the brand may say. Nothing keeps a
copy: every script resolves it through `scripts/memory.py`
and every agent reads it before drafting. New material reaches it through one
path, `/corpus-update --apply`, tighten-only; the two exceptions are
`calendar.md` (the autopilot's snapshot) and `reviews.md` (the desk's pull).
`status.md` outranks `project.md` wherever they disagree. Every file, in two lines:

- `streams.md`: the registry of the streams the engine serves, one row each
  with owner state, autopilot cell, guardrails and pair rules. A person edits it on a decision.
- `themes.md`: the hashtags the brand leads under, eight rows, with the fact
  each links back to, its partner tags and its licence grade. Empty rows are not themes.
- `claims.md`: the register of checkable claims a draft may cite by id, graded
  and corroborated. Written only by `/corpus-update --apply`; rows are superseded, never deleted.
- `handles.md`: own channels, cleared partners and standards bodies with
  `status`, `themes` and `last_verified`. Only a `verified` handle on a cleared row is tagged.
- `handles.private.example.md`: the shape of the gitignored companion that holds
  stealth parties and the denylist. Copy it to `handles.private.md`; the gate blocks without it.
- `brand-genome.json`: how the brand looks (flat colours, typeface, corner
  radius, logo), read by every visual the engine makes; fill it from your website.
- `voice.md`: how the brand sounds, one stream, sliders unfilled until a brief
  evidences them. A stream with no voice drafts nothing.
- `instincts.md`: the standing rules, structural first and brand-specific
  below, injected into every session. Never loosened by hand.
- `status.md`: what is actually evidenced, graded evidenced, asserted or intended,
  with §4 the cleared and banned phrasings the gate's status rules come from. Outranks `project.md`.
- `project.md`: the strategy, section by section, as the corpus states it.
  Read it second, after `status.md`.
- `logics.md`: the reusable argument shapes, numbered `L<n>`, named per theme in
  `themes.md`. `L1` shows the form.
- `glossary.md`: the engine's own terms (stream, theme, claim grade, Alpha and
  Beta, gate, autopilot cell, held slot, licence grade) and then the brand's.
- `lessons.md`: dated takeaways under `## YYYY-MM-DD — title` headings, which
  the session brief parses and the readout decays. Patterns only, never per person.
- `calendar.md`: what is planned and published, rewritten by the autopilot's
  snapshot step. Read before proposing; never edited by hand.
- `reviews.md`: Alpha's standing reviews, appended by `desk_sync.py --pull`
  alone. Absent until the first one; it can tighten a rule, never loosen it.
- `decisions/`: one dated file per decision, `YYYY-MM-DD-slug.md`, the only
  thing that loosens memory. The README carries the template.
- `campaigns/`: one file per campaign with brief, calendar, engager ledger
  (patterns only) and retro. The README says what each section holds.
- `templates/`: the shapes a script copies; `voice.md` is the one
  `onboard.py --write-voice` fills for a new stream.
- `streams/`: the memory of every stream but the brand's own, one directory per
  slug with this same file set. The README says how one is laid out.
- `.gitignore`: keeps `handles.private.md` (and every stream's) out of the
  repository. Do not loosen it.

## maintenance

Once a quarter: prune instincts that no longer apply, check `handles.md` dates,
confirm every claim's source still resolves. Memory that grows unchecked stops
being useful; memory loosened by hand stops being true.
