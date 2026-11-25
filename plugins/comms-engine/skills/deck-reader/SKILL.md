---
name: deck-reader
description: Read a presentation (.pptx, .pdf, Keynote-exported PDF) end to end in four passes - extract text and layout geometry, structure it into a slide hierarchy, interpret charts and diagrams with vision, then synthesise a reading. Use whenever asked to read, analyse, summarise, critique, teardown or extract insight from a deck, slide deck, presentation, pitch deck or board deck, or when handed a .pptx/.pdf that is slides rather than prose.
---

# Deck reader

A four-pass method for reading a presentation properly. The point of the passes
is that **each one sees things the others cannot**: text gives you the argument,
geometry gives you the emphasis, the render gives you what a viewer actually
sees, and the file metadata gives you the history nobody meant to leave in.

Skipping to "summarise the text" throws away three quarters of the evidence.

## Pass 1 — extraction and layout parsing

Run the extractor. It handles `.pptx` and `.pdf` and writes everything the
later passes need.

```bash
engine extract_deck <source> -o Decks/<name>
```

Options: `--dpi 150` (render resolution), `--chunk 5` (slides per Pass 2 chunk),
`--ocr auto|always|never`.

It produces four artefacts:

| file | what it holds |
|---|---|
| `slides/slide-N.png` | rendered pages — the input to Pass 3 |
| `shape_structure.txt` | every object with geometry, fill, and **true paint order**; text blocks with font, point size, hex colour |
| `rawmeta.txt` | doc properties, theme, fonts, media inventory |
| `outline.md` | Pass 2 output: hierarchy, function labels, chunk map |

Layout awareness is handled for you: repeating headers, footers and page numbers
are detected across pages and stripped from the outline (they are still listed,
labelled, so you can see what was removed); reading order is column-aware, with
full-width headlines kept out of the gutter sweep; a page that paints images but
carries no text layer is OCR'd from its render via tesseract.

**Prefer the `.pptx` over any exported PDF.** It is not a small difference:

| | `.pptx` | exported `.pdf` |
|---|---|---|
| shape names | **yes** — the single best archaeology in a deck | no |
| speaker notes | **yes** | no, and you cannot prove absence |
| author, revision count, edit time | **yes** | no |
| theme, masters, layouts | **yes** | no |
| chart series values | **yes**, as numbers | only as painted pixels |
| line styles (dashed vs solid) | **yes** | no |

If you only have the PDF, say so in the write-up and do not make claims that
need the source file.

## Pass 2 — semantic chunking and structuring

Read `outline.md`. It already carries, per slide: the title/bullet/sub-bullet
hierarchy inferred from point size and indent, a heuristic **function label**
(Title Slide, Agenda, Executive Summary, Problem, Solution, Financial, Roadmap,
Team, Traction, Governance, Appendix, Closing), tags for charts/tables/images,
and speaker notes where the source had them.

The function labels are heuristics — **confirm them against the render in Pass 3**
and correct them before relying on them.

For a large deck, work chunk by chunk using the chunk map at the bottom of
`outline.md`. Each chunk names the exact renders it covers, so you can hold one
chunk's text and images in context at a time and carry forward only your notes.

## Pass 3 — multi-modal analysis

**Actually look at the renders.** Read `slides/slide-N.png` with the Read tool,
a chunk at a time. This pass is not optional.

You are looking for two different things, and the second matters more: what the
slide *shows*, and what that tells you about what it *argues*. A diagram's shape
is a claim about how the system works; emphasis is a claim about what matters;
a chart is a claim about magnitude. Read them as claims.

For each slide, reconcile three sources: the render, the `shape_structure.txt`
entry, and the outline text. Specifically:

- **Charts and diagrams** — read axis labels, units, scale start, and series
  from the image. On a `.pptx` the extractor prints the real series values;
  compare them against what the chart *appears* to show and against the claim
  in the slide text. A truncated y-axis, a mislabelled unit, or a total that
  does not match its parts is a finding.
- **Cross-reference text against data.** "Revenue tripled" over a chart showing
  2.1x is the kind of thing this pass exists to catch.
- **Emphasis and hierarchy** come from geometry: point size, weight, colour and
  position tell you what the deck wants read first, which is often not what the
  text order implies.
- **Composition order.** `[zNN]` in `shape_structure.txt` is genuine paint order,
  so "this was added over that" is a supportable claim (see caveats — this was
  *not* true of older dumps in this repo).
- **Defects** — clipped text, overlaps, misalignment, placeholder art left in,
  inconsistent margins. Read them as evidence about how the deck was made.

## Pass 4 — synthesis and output

Write to `Decks/<name>/deck_reading.md`, and a `README.md` alongside it stating
method, limits, and the headline findings. Follow
`the deck-reader skill's references/output-template.md`.

**Lead with the argument, not the artefact.** A deck is a piece of persuasion
before it is a file. The reader of your write-up wants to know what it claims,
whether the claims hold, and what it is really asking for. Construction findings
— geometry, colour, watermarks, layout defects — are *evidence*, and they earn
their place when they change what you believe about the argument (a chip named
for a dropped partner, a status claim that contradicts a sibling deck). They do
not carry a reading on their own. If a finding cannot be connected to what the
deck argues or to whether it can be trusted, it belongs in a short appendix or
nowhere.

So structure the reading around these, in this order:

- **The spine.** State the deck's core claim in one or two sentences, in its own
  words where possible. Then say whether the deck actually argues it.
- **The arc.** How the argument is sequenced, where it turns, what it builds to,
  and whether the title matches the destination. A deck that concedes its real
  product four slides from the end is telling you something.
- **The claim ladder.** For each load-bearing claim: what is asserted, how
  strongly, and what evidence stands behind it. Distinguish *fact*, *plan*,
  *ambition* and *assertion*, and quote the exact wording — the difference
  between "certified", "in final stage" and "9 of 10 steps approved" is the whole
  finding.
- **What is missing.** A named customer, a price, a competitor, a failure mode,
  a downside. Absences are findings; readers of the deck will notice them too.
- **The ask.** What the deck actually wants from its audience, which is often not
  what its title says.

**Across a family of decks**, do this once more at corpus level, and write it to
a shared `NARRATIVE.md`. The highest-value findings usually live between decks,
not inside one: the same claim stated at different strengths to different
audiences, a slide reused verbatim, a strategic question two decks answer
differently, a register one deck uses that the others should. Check whether
confidence tracks audience scrutiny — if a claim gets bolder as the reader gets
less able to verify it, say so plainly.

Match the depth to the ask. A quick summary is a legitimate output; so is a
page-by-page teardown. What does not change is the evidence discipline:

- **Cite where each claim came from** — page number, and which pass produced it.
- **Separate what the deck says from what is true.** Decks state the *ambition*;
  applications, contracts, specs and engineering notes state the *position*.
  When they disagree, the primary source wins — the deck was written to persuade.
  A status word with no artefact behind it ("live", "on track", "backed by") is
  an assertion, not a fact, and should be reported as one.
- **Verify before reporting a structural claim.** If you are about to say a
  colour has no theme entry, or a shape is dashed, or an asset repeats — grep
  the dumps and confirm the count. Do not infer it from the render alone.
- **State what the source could not give up**, in a Method section. This is what
  keeps the reading honest, and it differs by source type (see the table above).

## Caveats that affect what you may claim

Read `the deck-reader skill's references/caveats.md` before writing findings. In
short: text-block heights exclude descender overshoot; a `.pptx` rendered through
LibreOffice may substitute fonts, so treat the render as approximate for
typography and trust `shape_structure.txt` for the real typeface; OCR'd text is
a best guess and is labelled as such; and function labels are heuristic.
