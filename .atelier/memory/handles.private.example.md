# handles.private - stealth parties, draft parties, and the denylist (example)

This is the shape of the private companion to `handles.md`. Copy it:

    cp .atelier/memory/handles.private.example.md .atelier/memory/handles.private.md

then replace the two fake terms with the brand's own and fill the tables.
`handles.private.md` is gitignored (`.atelier/memory/.gitignore`) and never
committed; the engine merges it on top of `handles.md` at read time, and
`gate_lint` blocks every draft while it is absent, because a stealth check with
no list to check against is not a pass. This example file is committed, is not
read by anything, and must never carry a real stealth term.

What goes here and nowhere else: counterparties the brand is talking to but has
not signed or announced, initiatives that are not public, and the terms a draft
may not echo. A party leaves this file for `handles.md` only on a decision file
that clears it, and its term leaves the denylist in the same commit.

## stealth parties

| party | what it is | why it stays dark |
|---|---|---|
| Project Umbra | an example placeholder for an unannounced initiative | nothing is signed or published; replace this row |

## draft and unsigned parties

| party | stage on record | why it is not taggable |
|---|---|---|
| Ruritania Trust Ltd | an example placeholder for a counterparty in discussion | a pitch is not a partner; replace this row |

## the denylist — terms a draft may not echo

One term per row, matched case-insensitively against the title, the post and
both teasers. Only Alpha adds a term or removes one. The heading above is read
verbatim by `memory.denylist`; keep it exactly as it is.

| term |
|---|
| Project Umbra |
| Ruritania |

## log

- 2026-11-05: example shape written with two fake terms. Replace them.
