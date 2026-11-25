---
description: Run the full corpus flow end to end - sweep the strategy corpus (the root from engine.json), read what is new or changed, analyse it into briefs, and update .atelier/memory/ (plan only unless --apply). The entry point.
argument-hint: [--apply] [--max N] [--no-read] [--no-analyse]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# /corpus-cycle

One turn of **source, reading, brief, memory**. Each step is its own command
and can be run alone; this one chains them and stops where a human decision is
due.

The corpus is the folder `params.corpus.root` in
`engine.json` names (`engine setup corpus --root`
writes the real one into `engine.local.json`; a fresh clone carries a
placeholder and the sweep says `root not found`). Every step below resolves
it through `corpus_sweep.py`, which reads the merged configuration.

Arguments: `--apply` lets the last step write `.atelier/memory/` (default is
plan only). `--max N` caps the sources read this run (default 8). `--no-read`
and `--no-analyse` skip those steps for a run that only wants to apply briefs
already written.

## steps

1. **Sweep.** Follow `corpus-sweep.md`. If nothing is pending at any stage,
   say so and stop.

2. **Read.** Unless `--no-read`: follow `corpus-read.md` with `all` and the
   `--max` cap. Stale operative decks go first.

3. **Analyse.** Unless `--no-analyse`: follow `corpus-analyse.md` for every
   source now at stage `read`, one brief per corpus folder.

4. **Update.** Follow `corpus-update.md` with `all`, passing `--apply` only if
   this command received it. Without it the run ends with the plan printed,
   which is the normal ending: the plan is what the user reviews.

5. **Close.** Re-run the sweep with `--write` and report, in this order:
   - counts per stage before and after;
   - sources read this run, and twins collapsed;
   - briefs written, each with its evidenced / asserted / tighten / denylist
     counts;
   - the memory plan (or, with `--apply`, the files changed and the test
     result);
   - what is still pending and why (over the `--max` cap, no reader for the
     type, waiting on `--apply`).

## rules that bind every step

- Nothing in this flow publishes, and nothing writes memory except step 4
  with `--apply`.
- `status.md` only tightens. A loosening needs evidence, never a deck.
- Stealth stays stealth: new names go to the denylist, not to themes.
- Read every slide; extraction is not reading.
- The brief is the record. If a finding is not in a brief with a citation, it
  does not reach memory.
