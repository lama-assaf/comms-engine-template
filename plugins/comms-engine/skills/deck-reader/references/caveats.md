# Caveats — what the extractor can and cannot support

Read this before writing findings. Every item here is a limit on what you may
claim, not a bug to route around.

## Fixed in this extractor (do not carry the old warnings forward)

Earlier hand-made dumps in `Decks/*/shape_structure.txt` carried two warnings
that **no longer apply** to output from `extract_deck.py`:

- **Z-order is now real.** The old dumps emitted objects grouped by type (every
  RECT, then every LINE, then every IMAGE), so cross-type ordering claims were
  invalid. This extractor walks pdfminer's `LTPage` children, which interleave
  in true content-stream paint order. `[zNN]` is a genuine paint index: a higher
  index paints over a lower one, across types. Composition claims are supportable.
- **Columns are no longer merged.** The old extractor joined any two text runs
  sharing a baseline, so two columns became one nonsense line. This one breaks a
  line when the horizontal jump exceeds 2x the point size, and orders blocks
  column-by-column using a gutter sweep.

- **`.pptx` shape fills and lines are now captured**, not just text colour, and
  each slide lists the shapes it **inherits from its layout**. Both were blind
  spots, and together they produced a real error: a reading asserted that a
  theme's accent red was "used zero times" while a rule painted in exactly that
  colour sat on the cover of two decks — because the rule was a shape (not text)
  on the layout (not the slide). Inherited paint is reported as
  `theme:<slot>` so it is distinguishable from a hard-coded value.

If you are reading an *old* dump rather than regenerating it, the old warnings
still apply to that file.

## The lesson behind those fixes

**A colour, font or element you cannot find in the dump may still be on the
slide.** Before writing "X is never used", ask what the extractor is actually
looking at — text runs only? slide shapes only? — and confirm against the
render. A count of zero from an instrument that cannot see the thing is not
evidence of absence.

The general form: **negative claims need a positive check.** "Not present in the
dump" is a statement about the dump. Look at the pixels, or read the raw XML,
before turning it into a statement about the deck.

## Still true — text geometry

- **Block heights exclude descender overshoot.** A block whose arithmetic shows
  6pt of clearance can still visibly clip in the render. Trust the render for
  collision and clipping, not the numbers.
- **Font subset prefixes are stripped.** `AAAAAB+Arial` is reported as `Arial`.
  The prefix is assigned per embedded subset and is not meaningful, but it does
  mean you cannot count subsets from `shape_structure.txt` — use the font list
  in `rawmeta.txt` for that.
- **Colour is the fill of the first glyph in a block.** A block with a coloured
  word inside it reports only the run colour it started with.
- **Reading order is inferred, not authored.** The gutter sweep is reliable for
  standard column layouts and degrades to top-to-bottom, left-to-right elsewhere.
  For a collage or a diagram-heavy slide, trust the render.

## Still true — rendering

- **A `.pptx` is rendered via LibreOffice**, which substitutes fonts it does not
  have and occasionally reflows text. So:
  - for **typography claims** (typeface, size, weight) trust
    `shape_structure.txt` and `rawmeta.txt`, which read the source file;
  - for **layout and clipping claims** on a `.pptx`, say the render is
    LibreOffice's, or open the file in PowerPoint/Keynote before asserting a
    visual defect. A "clipped" heading may be a substituted font, not a defect.
- A `.pdf` is rendered by poppler from the file itself, so its render is faithful.

## Still true — content

- **Function labels are heuristic** keyword matches against the slide title,
  falling back to body text. They are a starting point; confirm against the
  render and relabel freely.
- **OCR text is a guess.** Pages with no text layer are OCR'd from the render and
  marked in both `shape_structure.txt` (`[OCR]`) and `outline.md`. Never quote
  OCR'd text as exact wording without checking the image.
- **Chrome detection needs at least 3 pages** and a >=50% recurrence rate. On a
  short deck, headers and footers will not be stripped. They are always listed
  when detected, so you can see what was removed.
- **Grouped shapes** in a `.pptx` are walked recursively and indented; a shape
  inside a group has its own name and its own geometry.
- **SmartArt and embedded OLE** (think-cell charts, embedded spreadsheets) appear
  as a graphic frame. The extractor will not give up their internals; read them
  from the render, and note in the write-up that the underlying data was not
  accessible.

## Evidence discipline

- Grep the dumps to confirm a structural claim before making it. "This colour is
  not in the theme" means `grep -c` returned 0, not that you did not notice it.
- A deck states ambition. Applications, contracts, specs and engineering notes
  state position. When they disagree, the primary source wins.
