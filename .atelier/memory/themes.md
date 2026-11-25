# themes - the hashtags where this stream leads the debate

The theme dictionary the engine listens for and drafts under. A theme is a
hashtag the brand means to own in public debate, defined once here from the
brand's own strategy material through `/corpus-update --apply`, never from a
draft. Eight rows is the shape the engine was built for: enough rotation for
two posts a week without repeating an argument inside a month, few enough that
each theme gets an introduction post and a measurable share of listening.

**Rules that bind this file.** Deciding when a theme changes, and what that
does to the architecture, is a human decision. The engine never adds, merges or
renames a row. A hashtag not in this table is not a theme: the gate refuses a
draft whose theme is not a row here, and the listener searches for nothing else.

The `fact` column names the evidenced fact a theme post may link back to today
(`status.md` is the authority; `claims.md` is its citable index). A theme with no
shipped proof point is argued through a logic from `logics.md` that needs
nothing shipped, until one exists. `partner tags` names the handles from
`handles.md` a post under this theme may tag, or `none cleared`; a standards
body is named `(cite only)`. `intro post` is `not yet` until the theme's
introduction post is live, then its date.

The eight rows below are empty on purpose. A row is a theme the moment its
hashtag cell is filled; until then the parser reads an empty roster, and
`memory.py` reports `themes 0`. Fill rows in place, top to bottom, and keep the
two tables of this file matched row for row.

| hashtag | what it is | why it is different | fact it links back to | partner tags | intro post |
|---|---|---|---|---|---|
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |
|  |  |  |  |  |  |

## licence and layer

How a theme is licensed, in two lines: *a theme is licensed by the stack layer
beneath it, and a layer that has not shipped yields no theme.* The licence grade
is read from this table by every runtime and nothing keeps its own copy; it is
graded against `status.md` and may only tighten between corpus updates.

- **licensed**: argue it freely inside `voice.md`.
- **licensed-with-hedge**: argue it only with the cleared hedge named in the
  basis; the hedge is not optional.
- **held**: the layer beneath has not shipped. Argue the standards principle
  only: no capability, initiative, partner or date of the brand under a held theme.

`layer` names where in the brand's stack the theme sits (for example: leading
narrative, initiatives, core services, execution infrastructure). `logics` names
the arguments from `logics.md` a post under this theme runs. The roster here
must match the dictionary table above row for row; the engine fails loudly
rather than guessing when it does not.

| hashtag | layer | licence | logics | licence basis |
|---|---|---|---|---|
|  |  |  |  |  |
|  |  |  |  |  |
|  |  |  |  |  |
|  |  |  |  |  |
|  |  |  |  |  |
|  |  |  |  |  |
|  |  |  |  |  |
|  |  |  |  |  |

## excluded from listening

Hashtags that belong to another narrative, another stream or a stealth
initiative. The listener does not query them and does not report them. The
engine-local search terms live in `themes.json`, which
carries one search term per row of the dictionary table and an `ignore` list
for the terms below.

| term | why |
|---|---|

## theme status log

- 2026-11-05: template created, eight empty rows. No introduction post is live
  for any theme (0 of 8). Rows are filled by `/corpus-update --apply` from the
  brand's own strategy corpus; the search terms follow in
  `themes.json`, one per row, before the first listening pass.
