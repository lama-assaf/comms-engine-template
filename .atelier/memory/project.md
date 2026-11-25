# project: the brand's communications

The single source of truth for this project's **strategy**. Read this first,
then read `status.md`, which carries what is actually *evidenced*. Where the
two disagree, `status.md` wins. Filled by `/corpus-update --apply` from the
brand's strategy corpus; each section below says what belongs in it.

_Sources: listed here as the corpus is read, with dates, so a reader knows how
old the strategy is relative to the evidence._

---

## what this is

One paragraph on the business this stream serves and the narrative it carries.
If a second brand shares the substrate, say so here and point at the pair rule
in `streams.md`; the narratives never merge.

## the core mechanism (say it in plain language)

The thing the brand does, in sentences a regulator, a customer and an engineer
would each accept. No metaphors that outrun the evidence.

## the one existential risk

The claim-to-evidence gap the strategy is most exposed to, named plainly.

## content pillars

The three to five pillars every piece serves one of, each with the themes from
`themes.md` that argue it. A piece that serves two pillars is two pieces.

## audiences (who needs what proof)

Each audience and the proof class it accepts: a regulator wants a record, a
counterparty wants a running system, an engineer wants a specification.

## content operating system

The loop the engine runs: listen, draft, gate, review, publish, score, learn.
Who owns each step (Alpha, Beta, the autopilot) and which store each writes.

## channels and cadence

The evergreen floors per channel and the quiet hours, as the guardrails row in
`streams.md` enforces them. Local time is `engine.json` `autopilot.timezone`.

## team, workstream leads and spokespeople

Roles only: who approves, who clears a partner, who speaks on record. Names are
not written in shared memory; the operator holds them.

## delivery status and milestones

A pointer, not a copy: `status.md` §5 is the milestone table and outranks
anything written here.

## key events (dated)

Dated public events the brand sponsors or speaks at, with the decision file
that cleared the event copy.

## stealth

A pointer, not a list: the denylist and the stealth parties live in
`handles.private.md`, gitignored, and are never named in this file.

## where the rest of the memory lives

`status.md` (evidence), `claims.md` (the citable index), `themes.md` (the
roster and licence), `handles.md` (who may be named and tagged), `voice.md`
(how it sounds), `logics.md` (how it argues), `instincts.md` (the standing
rules), `lessons.md` and `decisions/` (what was learned and decided),
`campaigns/` (periods of work), `calendar.md` (what is planned and published).

## tooling

The engine in `plugins/comms-engine/` and the corpus reader in
`skills/deck-reader/`; the console is `scripts/engine.py`. Nothing publishes
itself: the autopilot sends only what the registry's `autopilot` cell allows.
