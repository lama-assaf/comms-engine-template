---
description: Analyse the sources that have been read but not yet briefed - write a research brief in Docs/Research/ that separates asserted from evidenced, checks every finding against .atelier/memory/, and ends with proposed memory edits. Step 3 of /corpus-cycle.
argument-hint: [<cluster slug>] [--sources "<rel path>,<rel path>"]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# /corpus-analyse

Turn readings into a **brief**: the one document per cluster that says what
the sources claim, what is actually evidenced, where they contradict what
memory believes, and what memory should therefore say. The brief is the
only input `/corpus-update` accepts, so everything it will need has to be here,
quoted and cited.

Arguments: a cluster slug names the brief. `--sources` restricts it to the
listed sources; otherwise take every source the sweep lists under **needs
analysis**, grouped into clusters by corpus folder (one brief per folder, an
archive folder always its own brief).

## Step 1: load the ground truth first

Before reading a single finding, read in full:

- `.atelier/memory/status.md`: what is evidenced. **Outranks everything.**
- `.atelier/memory/instincts.md`: standing rules, including the stealth list.
- `.atelier/memory/project.md`, `themes.md`, `glossary.md`, `logics.md`, and
  `partners.md` and `open-conflicts.md` where the stream keeps them.
- `.atelier/memory/reviews.md` if present: Alpha's standing reviews; they can
  only tighten.
- The latest existing briefs in `Docs/Research/` for the same topic, so the
  new brief continues the numbering and does not repeat settled findings.

```bash
engine corpus_sweep --only-todo    # the "needs analysis" table
ls Docs/Research/*.md                                              # letters used so far
```

## Step 2: read the readings

For each source in the cluster, open its reading (`Decks/**/<name>/narrative.md`
or `Docs/Research/sources/<stem>.md`) with the Read tool. Narratives carry a
slide-by-slide; cite slide numbers. Extracted prose carries `<!-- page n -->`
markers for PDFs; cite pages. Word documents: cite the heading.

## Step 3: write the brief

Path: `Docs/Research/<today>-<next letter>-<cluster slug>.md`. Letters run on
from the last one used in that folder (a fresh clone starts at A). Match the
format of the existing cluster briefs:

1. **Header**: cluster name, source folder, file count, one paragraph on
   what kind of material it is and the governing caveat (for the brand's own
   decks: *every claim below is asserted by a deck, not independently
   established*).
2. **Inventory** table: original path, what it is, date, author if known,
   twin-of if a duplicate.
3. **Findings**, numbered sections by topic. Every finding:
   - one bold claim sentence;
   - tagged **evidenced** (a standards body's or regulator's own document, an
     executed contract, an invoice, a certificate, a running system) or
     **asserted** (the brand's or a partner's own deck, draft, proposal);
   - `[source: <path>, slide n | page n | § heading]` with a short quote.
4. **Against memory**: for each finding that touches something memory
   already states, grep the memory files and record one of:
   - *confirms* (memory already says this; cite the line);
   - *tightens* (the source shows a current claim is weaker than memory
     states, e.g. a date retired, a partner not signed, a layer not live);
   - *loosens* (the source would let memory claim more). A loosening is only
     allowed through if the finding is **evidenced**; an asserted loosening is
     recorded here and goes no further;
   - *contradicts* (two sources disagree; name both, do not resolve).
5. **Stealth and confidentiality**: every partner, jurisdiction, technology
   or person named that is not on the public record. Compare against the
   stealth list in `instincts.md` and the confidentiality section of
   `status.md`. New names are denylist candidates.
6. **Dates and numbers**: every date, figure and percentage, with source and
   whether it is a plan or an outcome. Retired dates are called out as such.
7. **Proposed memory edits**: the hand-off to `/corpus-update`. One table, in
   exactly this shape:

   | # | file | action | where | proposed text | source |
   |---|---|---|---|---|---|

   - `file`: `status.md`, `claims.md`, `project.md`, `themes.md`, `partners.md`,
     `handles.md`, `handles.private.md`, `glossary.md`, `logics.md`,
     `instincts.md`, `lessons.md`, `open-conflicts.md`, `decisions/<slug>.md`.
     Every `status.md` row that changes what is evidenced has a `claims.md`
     companion row: `add` for a new checkable claim, `supersede` where a claim
     changed, `tighten` where a grade or corroboration falls, `corroborate`
     where a second independent source or a primary artefact appeared. The
     `proposed text` of a `claims.md` row is the full table row.
   - `action`: `add`, `tighten`, `replace`, `retire`, `denylist`, `decision`,
     `lesson`; for `claims.md` also `supersede`, `corroborate`. Never `loosen`:
     a loosening that is evidenced is a `replace` whose source column names
     the evidence document; an asserted one does not appear in this table at
     all.
   - `where`: the section heading or the line being changed, quoted.
   - `proposed text`: the exact words to write, in the file's own register
     (`status.md` is sober and evidential; `instincts.md` entries are one
     bold rule plus one sentence).
   - `source`: the `[source: ...]` citation from the findings.

   Order the rows `status.md` first, then stealth, then the rest. A brief with
   nothing to change still has this section, with the line *no memory edits
   proposed* and a sentence on why.

Write the brief with the Write tool. Do not edit anything under
`.atelier/memory/` from this command.

## Step 4: record

```bash
engine corpus_sweep --mark-brief "<rel path>" --as "Docs/Research/<brief>.md"   # once per source
engine corpus_sweep --write
```

Report the brief path, the counts of evidenced vs asserted findings, how many
rows the edit table holds and how many are `tighten` or `denylist`. Then say
`/corpus-update` is next.
