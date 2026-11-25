# Output template — Pass 4

Two files, written next to the extraction artefacts in `Decks/<name>/`.

Scale the depth to the ask. A three-paragraph summary is a legitimate output;
the structure below is what a full reading looks like. What never scales down
is the Method section and the citation discipline — those are what separate a
reading from an impression.

---

## `deck_reading.md`

```markdown
# deck read: `<filename>`

<One paragraph: what this deck is, who it is aimed at, what it argues.>

**Source**: `<absolute path>`
**<N> slides · <W>×<H>pt · <typefaces> · <application/producer>, created <date>,
modified <date> · <revision count> revisions · <edit time> · <N> speaker notes.**

Read <date> in four passes: every slide rendered and looked at; every shape
dumped with geometry, fill and paint order; document properties, theme and media
inventory read from the source; then synthesised. What this source cannot give
up is set out in `README.md` under **Method**.

---

## why this deck matters more than its filename suggests

<Lead with the finding that changes how a reader should treat the deck — a
date that settles a dispute, a lineage, an edit that has a direction. If the
deck is unremarkable, say that plainly and move on.>

---

## the spine

<The deck's core claim, in one or two sentences, in its own words where
possible. Then: does the deck actually argue it, and does the title match where
the argument lands?>

## the arc

<How the argument is sequenced and where it turns. What it builds to. If the
deck concedes something late, or its real ask differs from its title, that
belongs here.>

---

## page-by-page

### page 1 — <function label> — "<title>"

<What it argues, and how the construction supports or undercuts that. Cite
evidence — paint order, point size, shape name — only where it changes the
reading.>

<Repeat per page, or per chunk for a long deck.>

---

## the claim ladder

<Per load-bearing claim: exact wording, how strong it is, what stands behind it.
Distinguish fact / plan / ambition / assertion. Quote verbatim — the difference
between "certified", "in final stage" and "9 of 10 steps approved" is the whole
finding. A table works well here.>

## charts and data

<Per chart: what it shows, what its axes actually say, what the slide text
claims, and whether they agree. Note any truncated axis, missing unit, or total
that does not match its parts.>

## what is missing

<A named customer, a price, a competitor, a failure mode, a downside. Absences
are findings — the deck's readers will notice them too.>

## the ask

<What the deck actually wants from its audience, which is often not what its
title says.>

## appendix — what the construction reveals

<Short. Only findings that changed the reading: a status claim contradicting a
sibling deck, a shape still named for a dropped partner, a defect that would
embarrass on send. Geometry, colour and layout notes that do not bear on the
argument belong here or nowhere.>
```

---

## `README.md`

```markdown
# <deck name>

<One paragraph orientation.>

## Headline findings

1. <finding> — <one line of evidence>
2. ...

## Method — four passes

1. **Rendered** — every slide looked at at <dpi>dpi, plus crops where detail mattered.
2. **Structured** — every object with geometry, fill and true paint order; every
   text block with typeface, point size and hex colour.
3. **Raw** — document properties, theme colour scheme, font list, media inventory.
4. **Synthesised** — this reading.

## What this source could not give up

<Be specific and honest. For an exported PDF this list is long: no shape names,
no speaker notes (and no way to prove absence), no author or revision count, no
theme or masters, no line styles. For a .pptx, note instead what was rendered
through LibreOffice and anything locked inside SmartArt or embedded OLE.>

## Artefacts

- `slides/` — <N> rendered pages
- `shape_structure.txt` — geometry and text, true paint order
- `rawmeta.txt` — properties, theme, fonts, media
- `outline.md` — hierarchy, function labels, chunk map
- `deck_reading.md` — the reading
```
