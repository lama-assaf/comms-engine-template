# streams/ - the memory of every stream but the brand's own

The brand's own stream (the first row of `../streams.md`, slug `engine.json`
`brand.slug`) keeps its memory at the root of `.atelier/memory/`. Every other
stream the engine serves lives here, under `streams/<slug>/`, with the same
file set and the same shapes, and nothing in it copied from another stream.
`scripts/memory.py` resolves the directory from the registry row's `memory`
cell, which reads `.atelier/memory/streams/<slug>`.

## how a second stream's directory is laid out

```
streams/<slug>/
├── voice.md             shaped from ../templates/voice.md by `onboard.py <slug> --write-voice`
├── status.md            the sections of ../status.md, nothing graded
├── instincts.md         the structural instincts apply; the stream's own never-say lines go here
├── themes.md            the two tables of ../themes.md, headings and no rows
├── handles.md           own channels, cleared partners, standards bodies; headings and no rows
├── handles.private.md   gitignored (../.gitignore: streams/*/handles.private.md); copied from ../handles.private.example.md
├── claims.md            the register header of ../claims.md, no rows
├── reviews.md           written by desk_sync.py --pull; absent until the first standing review
├── lessons.md           the heading shape of ../lessons.md, no entries
├── calendar.md          the header of ../calendar.md, no rows; the autopilot snapshot rewrites it
├── campaigns/README.md  what a campaign file holds (../campaigns/README.md)
└── decisions/README.md  the dated-filename convention (../decisions/README.md)
```

`scripts/onboard.py` walks this list (`onboard.FILE_SET`) and reports each file
present or missing. Every file carries the headings of its root counterpart
and none of its content: `themes.md` with the two tables and no rows reads as
an empty roster, `handles.md` with `## own channels`, `## cleared partners
(public via <Name>'s own releases)` and `## standards bodies (cite, never
claim)` reads as no partners, and `claims.md` with the register header reads as
no claims. A partner heading may carry the stream's name in brackets; the
reader matches it as a prefix.

## what registers a stream

1. A row in each of the three tables of `../streams.md`, owner `unset`,
   autopilot `nothing`, memory `.atelier/memory/streams/<slug>`.
2. This directory, created by hand from the shapes above (copy the root files,
   delete their rows). `voice.md` is the one file a script shapes.
3. `streams/<slug>/themes.json`, the engine-local search
   terms, empty until `themes.md` has rows; `onboard.py <slug> --themes-file`
   records its path in `engine.local.json`.
4. A corpus root, written by `onboard.py <slug> --corpus-root <path>` into
   `engine.local.json`, never into the registry.
5. A decision file in `streams/<slug>/decisions/` that confirms the owner.

Until all five are done, `memory.may_draft(<slug>)` is false and the stream
drafts nothing, publishes nothing and posts nothing, by every path. A stream
names another only under a pair rule in `../streams.md`.
