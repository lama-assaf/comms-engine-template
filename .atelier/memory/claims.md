# claims - the register of what this stream's content may cite

One row per checkable claim (glossary: *claims register*). A draft may lean on
a claim only by citing its `id` in the note's `cites`; the gate checks that the
id exists, is not superseded, and that a present-tense capability sentence
cites a row at grade `evidenced`. `status.md` stays the prose authority; this
table is its citable index, and where the two disagree `status.md` wins until
`/corpus-update` reconciles them.

**Rules that bind this file.** Written only by `/corpus-update --apply`,
tighten-only: a grade may fall, a row may be superseded, a `corroboration` may
rise only with the source that earns it; a row is never raised by hand and
never deleted. Supersession is a new row plus `superseded_by` on the old one,
which keeps `latest-source-governs` mechanical. Nothing from `status.md` §6
(hard-confidential) or the stealth denylist enters this file. Statistics and
named counterparties in a row are facts, not clearance: the gate's partner and
hold-for-review checks still apply when a draft uses them.

**Columns.** `id` `C-<slug>-<n>`, numbered in order of entry and never reused;
`grade` evidenced (a primary artefact shows it true today) · asserted (a dated
document says it; the brand's own decks are assertions) · intended (a plan or
an exploration, with its source); `tier` of the source: primary (the issuing
party's own executed artefact, a regulator, a standards body, a published
release) · institutional (a report by a named institution) · trade (trade
press) · social; `themes` the hashtags from `themes.md` the claim bears on, or
`-`; `supersedes` and `superseded_by` the ids either side of a supersession, or
`-`; `from` `<stream>/<id>` on a snapshot row cited from another stream under a
pair rule, or `-`; `corroboration` primary · two-independent · single ·
watching (not yet citable: a single non-primary source, or a primary source
that is not public). The gate treats `watching` and `single` as uncitable.

The one row below is a worked example of the shape and nothing else. Its
corroboration is `watching`, so no draft can cite it; `/corpus-update --apply`
supersedes it with the first real claim or leaves it as `C-acme-0`.

## register

| id | claim | grade | source | date | tier | themes | supersedes | superseded_by | from | corroboration |
|---|---|---|---|---|---|---|---|---|---|---|
| C-acme-0 | Example row, not a claim: the shape every row takes. A real row states one checkable fact in one sentence, in the tense its source uses, with the hedge the source cleared. | asserted | this file, as the example of the form | 2026-11-05 | primary | - | - | - | - | watching |

## register log

- 2026-11-05: template created with the example row `C-acme-0` at `watching`,
  uncitable by construction. Real rows arrive through `/corpus-update --apply`
  from `status.md` once that file grades the brand's evidence.
