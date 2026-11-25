# deck-reader

A Claude Code skill for reading presentations in four passes: extraction and
layout parsing, semantic structuring, multi-modal interpretation, and synthesis.

The skill body is `SKILL.md`. This README covers installation, the `/deck-read`
command, the corpus flow that feeds `.atelier/memory/`, and the standalone use
of the extractor.

## Install

Nothing to install: `.claude/skills/deck-reader` and the `.claude/commands/`
entries for `/deck-read` and `/corpus-*` are tracked relative symlinks into this
folder, so a fresh clone has them. `bash skills/deck-reader/install.sh`
recreates the symlinks after a new command file is added here and reports which
rendering dependencies are present.

## Reading a new deck

```
/deck-read <path-or-filename of .pptx/.pdf> [output-folder-name]
```

Takes the deck's original location (a full path, a repo-relative path, or a bare
filename, which it resolves against the strategy corpus named by
`params.corpus.root` in `engine.json`). Runs all four
passes and writes `Decks/<name>/narrative.md`: the story, the arc, and a
slide-by-slide of what every slide says. Content only, no design or
construction material, which is what separates it from `deck_reading.md`.

The command ends by checking that the number of slide sections equals the number
of renders, and greps its own output to prove no design material leaked in.

## The corpus flow: source, reading, brief, memory

```
/corpus-cycle [--apply]        the entry point; chains the four below
/corpus-sweep                  1. where every file in the corpus stands
/corpus-read [all|<file>]      2. decks via the deck reader, prose via extract_doc.py
/corpus-analyse [<slug>]       3. a brief in Docs/Research/: asserted vs evidenced,
                                  checked against memory, ending in proposed edits
/corpus-update [<brief>] [--apply]   4. the only step that writes .atelier/memory/
```

The corpus is one folder, `params.corpus.root` in `engine.json`. A fresh clone
carries a placeholder; `engine setup
corpus --root <path>` writes the real one into the gitignored
`engine.local.json`, and until then the sweep exits 2 (`root not found`).

The sweep walks **every folder** under that root, fingerprints each file and
tracks it through `unread`, `read`, `analysed`, `applied` (a changed source
drops to `stale` and runs the chain again). A file is `read` when
`Decks/**/<name>/narrative.md` or `Docs/Research/sources/<stem>.md` is newer
than it, or the manifest points at a brief that covers it.

`/corpus-update` plans by default and writes only with `--apply`, under the
rules in `commands/corpus-update.md`: `status.md` only tightens, a loosening
needs evidence rather than a deck, new partner names arrive as `collect` with
"participation not confirmed", stealth names go to the denylist and never to
themes. It runs the social-engine tests afterwards because the engine parses
`themes.md`, `handles.md` and `claims.md`.

Standalone:

```bash
engine corpus_sweep                 # report, writes nothing
engine corpus_sweep --write         # + manifest.json, sweep.md
engine corpus_sweep --only-todo     # the three to-do tables
engine corpus_sweep --mark-read  "<rel>" --as "<repo path>"
engine corpus_sweep --mark-brief "<rel>" --as "Docs/Research/<brief>.md"
engine corpus_sweep --mark-applied "Docs/Research/<brief>.md"
```

State lives in `Docs/Research/_corpus/` (gitignored, like the briefs: file names
alone can name stealth partners). Exit code 1 while anything is pending.

### Running it on the schedule

`scripts/corpus_cycle_daily.sh` is the program of the `corpus-cycle` job in
`engine.json` (launchd label
`<brand.label_prefix>.corpus-cycle`, weekdays at 06:30 by default): the cheap
sweep gate first, and only when something is new, changed or stale a headless
`claude -p "/corpus-cycle --apply --max 8"` with a tool allowlist and a budget
cap (`params.corpus.budget_usd`). Memory is written under the tighten-only
rule; nothing is committed, the diff waits in the working tree. Log:
`state/corpus-cycle.log`. `python3
scripts/engine.py setup corpus` asks the root, the cap
and the budget; `engine enable corpus` loads the job.

## Reading prose sources

```bash
engine extract_doc "<path.docx|.xlsx|.html|.txt|.pdf>"
```

`--probe` prints `slides` or `prose` for a PDF so `/corpus-read` can route it.
Writes `Docs/Research/sources/<stem>.md` with a header (source path, mtime,
sha256) and the text: headings and tables from Word (plus review comments),
every sheet from Excel as a table, text from HTML, page-marked text from a prose
PDF. `--stdout` prints instead. Slides still go through `/deck-read`.

## Dependencies

| dependency | needed for | install |
|---|---|---|
| `pdfplumber` | PDF geometry and text, **required** | `pip install pdfplumber` |
| `pdftoppm` | rendering, **required** | `brew install poppler` |
| `python-pptx` | reading `.pptx` sources | `pip install python-pptx` |
| `soffice` | rendering a `.pptx` | `brew install --cask libreoffice` |
| `tesseract` | OCR for image-only slides | `brew install tesseract` |

## Standalone use

```bash
engine extract_deck deck.pptx -o Decks/deck
```

| flag | default | meaning |
|---|---|---|
| `-o, --outdir` | `Decks/<stem>` | where to write |
| `--dpi` | 150 | render resolution |
| `--chunk` | 5 | slides per chunk in the Pass 2 chunk map |
| `--ocr` | auto | `auto` OCRs only pages with images and no text layer |

Writes `slides/`, `shape_structure.txt`, `rawmeta.txt` and `outline.md`. It does
not write `deck_reading.md` or overwrite a `README.md`, so it is safe to re-run
over a folder holding a curated reading.

## Notes

- Prefer the source `.pptx` over an exported PDF. Shape names, speaker notes,
  author, revision count, edit time, theme and chart series values exist only in
  the source file. `SKILL.md` has the full comparison.
- `[zNN]` in `shape_structure.txt` is **true paint order**, including across
  object types. A hand-made dump produced by an older extractor may carry a
  caveat saying cross-type ordering claims are invalid; that caveat does not
  apply to output from this extractor.
- `references/caveats.md` lists every remaining limit on what you may claim.
  Read it before writing findings.

## Where the readings go

The template ships no `Decks/` folder; the first `/deck-read` creates it at the
repository root. Whether narratives are committed is the team's call: they
quote internal decks, so a private repository is the usual answer. A reading is
a source for `/corpus-analyse`, never memory itself: nothing under `Decks/` or
`Docs/Research/` is read by the gate.
