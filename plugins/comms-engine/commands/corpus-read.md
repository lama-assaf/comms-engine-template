---
description: Read every unread or stale source in the strategy corpus - decks through the four-pass deck reader, prose through the extractor - and record the readings in the manifest. Step 2 of /corpus-cycle.
argument-hint: [<rel path or filename> | all] [--max N]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# /corpus-read

Turn sources into readings. Nothing here interprets or edits memory; that is
`/corpus-analyse` and `/corpus-update`.

Arguments: a single source (path relative to the corpus root, or a bare
filename) reads just that one. `all` or nothing reads everything the sweep
lists as `unread` or `stale`. `--max N` caps the number of sources this run
(default 8; decks are slow and every slide must be looked at).

## Step 1: what needs reading

```bash
engine corpus_sweep --only-todo
```

Take the **needs reading** table. Order: `stale` first (an operative deck that
changed outranks everything), then by modified date, newest first. An archive
folder (one whose name says so) last: it is presumptively dead material, read
for history, never for claims.

## Step 2: collapse duplicates before reading

The corpus holds the same document in several formats. Read one, point the
others at it:

- `.pptx` beside a `.pdf` of the same stem: read the `.pptx` only.
- `.docx` beside a `.pdf` (and `[n]` copies) of the same stem: read the `.docx`.
- Confirm a suspected twin with a word-set diff, never by name alone:

  ```bash
  engine extract_doc "<a>" --stdout | tr -cs 'A-Za-z0-9' '\n' | sort -u > /tmp/a.w
  engine extract_doc "<b>" --stdout | tr -cs 'A-Za-z0-9' '\n' | sort -u > /tmp/b.w
  comm -3 /tmp/a.w /tmp/b.w | wc -l     # near zero = twin
  ```

  (use `extract_deck.py ... ` outline for a `.pptx`). After reading the primary:

  ```bash
  engine corpus_sweep --mark-read "<twin rel path>" --as "<repo path of the primary's reading>"
  ```

## Step 3: read each source

Decide slides or prose. `.pptx` and `.key` are slides. For a `.pdf`:

```bash
engine extract_doc "<path.pdf>" --probe     # prints slides | prose
```

**Slides**: follow `/deck-read` end to end
(extract, read the outline, look at **every** render, write `narrative.md`).
The output folder mirrors the corpus folder so the sweep finds it:

| corpus folder | narrative goes to |
|---|---|
| `<folder>/<name>.pptx` | `Decks/<folder without leading underscores>/<name>/narrative.md` |
| `<name>.pptx` at the root | `Decks/<name>/narrative.md` |

If a narrative already exists and the source is `stale`, move the old one to
`narrative.<old-mtime-date>.md` in the same folder before writing the new one,
and end the new narrative with a **## what changed** section listing the
slides that differ. That diff is the most valuable thing a re-read produces.

**Prose**:

```bash
engine extract_doc "<path>"
```

then open `Docs/Research/sources/<stem>.md` with the Read tool and read it in
full. For a document over about 8,000 words, read it in two or three passes
rather than skimming. Extraction without reading does not count as read: the
next step needs you to know what the document says.

Sources with no reader (`.key` without a PDF twin, unknown types): say so and
leave them `unread`.

## Step 4: record

```bash
engine corpus_sweep --write
```

Report: what was read, what was pointed at a twin, what was skipped and why,
and the new counts. Then say `/corpus-analyse` is next.
