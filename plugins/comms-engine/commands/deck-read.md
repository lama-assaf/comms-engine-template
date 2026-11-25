---
description: Read a new deck end to end from its original file and write a narrative.md - story, arc and slide-by-slide, no design material.
argument-hint: <path-or-filename of .pptx/.pdf> [output-folder-name]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# Read a new deck

Produce a **narrative reading** of the deck at `$1`, following the `deck-reader`
skill's four passes, and write it to `Decks/<name>/narrative.md`.

`$2`, if given, is the output folder name. Otherwise derive it from the source
filename with the extension stripped.

Run from the repo root: the extractor is at
`skills/deck-reader/scripts/extract_deck.py` and output goes under `Decks/`.

## Step 0: resolve the source

`$1` may be an absolute path, a repo-relative path, or a bare filename.

If it is not a path that exists, search the strategy corpus for it before giving
up. The corpus root is `params.corpus.root` in `engine.json`
(`config.py get corpus.root` prints the merged value):

```bash
find "$(engine config get corpus.root)" \
  -iname "*<stem>*" \( -name '*.pptx' -o -name '*.pdf' -o -name '*.key' \) 2>/dev/null | head
```

Report the resolved path before extracting. If several match, list them and ask
which. If none match, say so and stop; do not read a different deck.

**Prefer a `.pptx` over an exported `.pdf`** whenever both exist for the same
deck. A PDF cannot give up shape names, speaker notes, author, revision count,
edit time, theme, or chart series values, and you cannot prove absence of notes
from one. If only the PDF exists, say so in the Method line and do not make
claims that need the source file.

## Step 1: extract

```bash
engine extract_deck "<resolved source>" -o "Decks/<name>" --dpi 130
```

If `Decks/<name>/` already exists, stop and ask before overwriting.

This writes `slides/slide-N.png`, `shape_structure.txt`, `rawmeta.txt` and
`outline.md`.

## Step 2: read the text

Read `Decks/<name>/outline.md` in full. It carries per-slide hierarchy, a
heuristic function label, chart/table/image tags, and speaker notes where the
source had them.

Treat the function labels as guesses and the shape order as **not** reading
order; both get corrected in Step 3 against the render.

Speaker notes are the closest thing to what was actually *said*. If `rawmeta.txt`
reports a note count but the outline shows none, check the source directly before
concluding there are none; placeholder notes holding only a slide number are
common and are not real notes:

```bash
unzip -p "<source.pptx>" 'ppt/notesSlides/notesSlide*.xml' | grep -o '<a:t>[^<]*</a:t>'
```

## Step 3: look at every render

**Read `Decks/<name>/slides/slide-N.png` with the Read tool. Every slide, no
exceptions.** Work in chunks of 4 to 5 using the chunk map at the foot of
`outline.md`.

The render is what settles reading order, which items group with which, and what
the deck wants read first. Extracted text order frequently disagrees with the
page; when they differ, **the page wins**.

Read the visuals as claims: a diagram's shape is a claim about how the system
works, a chart is a claim about magnitude, emphasis is a claim about what
matters. Cross-check numbers in charts against the assertions in the text.

## Step 4: write `Decks/<name>/narrative.md`

The deliverable. **Content only: what is said and how the argument moves.** No
colour values, typefaces, layouts, shape names, revision counts, dpi or file
forensics; those belong in `deck_reading.md`, not here.

Use this structure. If the repository already holds a narrative under `Decks/`,
read one before writing to match register:

```markdown
# `<deck-name>`: the narrative

*N slides. What each one says, and how the argument moves.*

Content only. No design, construction or file-forensics material.

## The story in one paragraph
The whole argument, in prose, as the deck would tell it.

## The arc
Movements with slide ranges (I, II, III...). Name where the argument turns and
what that turn buys. If the title points somewhere different from where the deck
lands, say so here.

## Slide by slide

### N: <slide title>
What it says, quoting the actual lines. Use a table where the slide is a table
or a grid. Then **Does:** what the slide is doing for the argument, why it sits
here, and what it hands to the next one.

(Every slide gets its own `### N:` section. No skipping, no merging.)

## The through-line
Five or six quoted sentences, in slide order, that carry the argument end to end,
then one line reading them as a sequence.

## What the deck never says
Absences that a reader will notice: a price, a named customer, a competitor, a
date, a failure condition.

## Where the story pulls against itself
Internal contradictions, and claims that conflict with sibling decks in the same
folder. Quote both sides and cite the slides.
```

Quote the deck's own words wherever they carry weight; the difference between
"certified", "in final stage" and "9 of 10 steps approved" is often the finding
itself. Where a claim about status appears, check how the same claim is worded in
neighbouring decks and note any drift, especially if it strengthens as the
audience gets less able to verify it.

## Step 5: verify before reporting

Run these and report the actual numbers:

```bash
# every slide covered exactly once
ls Decks/<name>/slides/*.png | wc -l
grep -c '^### [0-9]' Decks/<name>/narrative.md

# no design material leaked into the narrative
grep -niE 'hex|#[0-9A-F]{6}|typeface|font|Arial|dpi|revision [0-9]|shape_structure|paint order' Decks/<name>/narrative.md
```

The two counts must match, and the grep must return nothing. Fix and re-check if
either fails. State both results in your summary.

## Optional, only if asked

- `deck_reading.md` + `README.md`: the argument-led reading *with* construction
  findings as evidence, per `the deck-reader skill's references/output-template.md`.
- `NARRATIVE.md` at the folder level: cross-deck findings, when the new deck
  joins a family. The highest-value findings usually live between decks: a claim
  stated at different strengths to different audiences, a slide reused verbatim,
  a strategic question two decks answer differently.

Read `the deck-reader skill's references/caveats.md` before making any structural
claim.
