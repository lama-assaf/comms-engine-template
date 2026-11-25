# status - what is actually true, as of 2026-11-05

**Read this before writing anything that makes a claim.** `project.md` carries
the strategy; this file carries the evidence behind the claims that strategy
wants to make. Where they disagree, this file wins. It is written only by
`/corpus-update --apply`, tighten-only, from the primary source corpus, and
every update is dated at the top with the brief it came from. Nothing in it is
graded yet: this is the template, and the sections below say what belongs in each.

## how to read this file

Every load-bearing claim is graded at one of three tiers, and the tiers are
never mixed in one sentence:

- **evidenced**: a primary artefact shows it true today (an executed contract,
  a regulator's record, a published release, a running system a person has seen).
- **asserted**: a dated document says it; the brand's own decks are assertions.
- **intended**: a plan or an exploration, with its source and its date.

`claims.md` indexes the rows a draft may cite; this file is the prose behind them.

## 1. core services

What the brand's core services are, and for each: what is genuinely evidenced,
what is not, and the one correction that matters most (the word the brand's own
material uses that the evidence does not carry). Any discrepancy between where
the brand says a thing runs and where it runs goes here, unresolved, until it is.

## 2. what is specified but not shipped

The layers at design or build stage: what the specification says, what is
implemented, what has no launch date, and the custody, fee or legal questions
that are still open. A design property never wears the present tense.

## 3. infrastructure and partners

Hard artefacts only: procurement, contracts, go-live evidence or its absence,
and what each named partner's clearance actually covers. Every figure is marked
measured or modelled.

## 4. what can and cannot be said publicly today

The cleared phrasings, verbatim from published material, and the banned words
with the reason each is banned. This section is the source for the gate's
status rules and the announcement checker's, which are data in
`gate-rules.json` beside this file (`status_words`, `cleared_hedges`,
`announce.status_flags`, `announce.cleared_phrases`): when a word is added
here, it is added there in the same commit.

## 5. milestone table

One row per milestone the strategy carries: what was announced, what the
evidence grade is, and the date on record or "none". A date that is gone is not
replaced by a new number.

| milestone | strategy says | evidence says | grade |
|---|---|---|---|

## 6. hard-confidential, beyond the normal stealth list

What may not appear in any draft, any claim row or any public artefact, even
hedged: unannounced corporate events, unpriced commercial terms, unpublished
third-party working material. Named here so a reader knows the class; the
terms themselves live in `handles.private.md`.

## status log

- 2026-11-05: template created. Nothing graded. The first `/corpus-update --apply`
  fills §1 to §6 from the brand's own corpus and dates the entry here.
