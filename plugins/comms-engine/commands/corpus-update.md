---
description: Carry a brief's proposed memory edits into .atelier/memory/ under the tighten-only rule - plan by default, write with --apply - then verify and mark the brief applied. Step 4 of /corpus-cycle, and the only command that writes shared memory.
argument-hint: [Docs/Research/<brief>.md | all] [--apply]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# /corpus-update

The one place the corpus flow touches `.atelier/memory/`. The engine and every
atelier and salon agent read that directory, so this command is conservative by
construction: it plans, shows the plan, and writes only with `--apply`.

Arguments: a brief path applies that brief; `all` or nothing takes every brief
the sweep lists under **needs memory update**. `--apply` writes; without it the
command prints the plan and stops.

## Step 1: load

Read in full: the brief's **Proposed memory edits** table, and every memory file
the table names. Read `status.md` whole even if only one row touches it; its
"as of" header and its "what can and cannot be said" section have to stay
consistent with whatever changes below.

## Step 2: check every row against the rules

Reject a row, and say why in the plan, when:

- **it loosens.** A row that would make a claim more true (signed, live,
  certified, accredited, launched, a new date) is allowed only if its source is
  evidence, not assertion: a standards body's or regulator's own document, an
  executed agreement, an invoice, a certificate, a running system. A deck,
  draft, proposal or ToR is never enough. `status.md` outranks `project.md`;
  `reviews.md` can tighten but never loosen; a row that conflicts with a
  standing review is rejected.
- **it names a partner as a partner.** New partner names enter `partners.md`
  or `handles.md` with `collect` status and the footer *in discussion,
  participation not confirmed* unless the source is a signed agreement.
- **it publishes a stealth topic.** Anything on the stealth list, or newly
  flagged by the brief, may enter `handles.private.md` (the denylist) and the
  stealth line in `instincts.md`; it may not enter `themes.md`, `project.md`'s
  public sections or the "can be said" list in `status.md`.
- **it adds a date nobody can source.** A plan date is written as a plan with
  its source; a retired date is retired, never replaced with a guess.
- **it would duplicate.** Grep the target file first; if the fact is already
  there, the row becomes *no change* or a wording tighten of the existing line.

Everything else is accepted as written. Do not improve the proposed text beyond
fitting the file's register; the brief is where the thinking happened.

## Step 3: plan

Print one block per target file: the rows accepted (with the exact text), the
rows rejected (with the rule), and for `status.md` the new "as of" line. Then,
without `--apply`, stop here: *plan only, re-run with `--apply` to write.*

## Step 4: apply (only with `--apply`)

Per file, in this order, using the Edit tool (never rewrite a file whole):

1. **`status.md`**: apply tightens and evidenced replaces in place. Update the
   header's "as of" date and append one line under it:
   `Updated <date> from <brief filename>: <one clause per change>.`
   If the milestone table or the "can and cannot be said" section changed,
   keep the two consistent.
2. **`handles.private.md`**: denylist additions. This file is gitignored and
   must exist; if it does not, stop and say so (the claim gate blocks without
   it, and that is correct).
3. **`instincts.md`**: append under a dated italic line in the existing style:
   `_added <date>, from <brief filename>. ..._` followed by the bold-rule bullets.
   Corrections only; preferences do not belong here.
4. **`decisions/<date>-<slug>.md`**: one file per `decision` row, in the
   existing shape: title line, *decision*, *why*, *what stays*, *supersedes*.
5. **`lessons.md`**: append a dated entry per `lesson` row: what memory
   believed, what the source showed, the cost had it stood.
6. **`claims.md`** (and `streams/<slug>/claims.md` for another stream): the
   citable index of `status.md`, parsed by `scripts/memory.py` and read by the
   gate, so keep the eleven columns and the closed vocabularies exactly as the
   file's header states them. Allowed rows: `add` (a new claim with its
   grade, source, date, tier, themes and corroboration, id `C-<slug>-<n>` as
   the next number); `tighten` (a grade falls, or a corroboration falls);
   `supersede` (a new row carrying `supersedes: <old id>`, and `superseded_by:
   <new id>` written on the old row, which is never deleted); `corroborate`
   (a corroboration rises from `watching` or `single` to `two-independent` or
   `primary` only with the second independent source or the primary artefact
   named in the row's `source` cell). Never raise a grade, never delete a row,
   never edit a row's `claim` text in place: a changed claim is a supersession.
   A row whose `themes` cell names a hashtag `themes.md` does not list is
   rejected. Append one line to the file's register log.
7. **`project.md`, `themes.md`, `partners.md`, `handles.md`, `glossary.md`,
   `logics.md`, `open-conflicts.md`**: additive edits. `themes.md` and
   `handles.md` are parsed by the engine: keep their table columns and the
   `verified` / `collect` vocabulary exactly as they are.

Never touch `reviews.md` (written by `desk_sync.py --pull` alone),
`calendar.md`, `campaigns/`, or anything under `Content/`.

## Step 5: verify

```bash
git diff --stat .atelier/memory/
engine apply --check           # streams.md still matches brand.json
engine listen --dry-run        # themes.md still loads
engine memory                  # claims.md parses: no ERROR line
```

If a test fails, revert the file it names (`git checkout -- <file>`), report the
failure with its output, and leave the brief unapplied.

Then record and re-sweep:

```bash
engine corpus_sweep --mark-applied "Docs/Research/<brief>.md"
engine corpus_sweep --write
```

Report: files changed with one line each, rows rejected and why, test result,
and that `.atelier/memory/` is ready to commit. Do not commit; the user does.
