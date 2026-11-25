# streams/ - engine-local search terms per stream

One directory per stream other than the brand's own, `streams/<slug>/themes.json`,
with the shape of `../themes.json`: `search_terms` keyed by hashtag, `mentions`,
`ignore` and a `_term_log`. It is empty (`"search_terms": {}`) until the
stream's `.atelier/memory/streams/<slug>/themes.md` has rows, and the two must
match row for row: `listen.py` exits when a theme has no term or a term has no
theme. `onboard.py <slug> --themes-file streams/<slug>/themes.json`
records the path in `engine.local.json`.

Nothing here is doctrine: what a theme is, why it is different, what it links
back to and whether it is licensed live in the stream's `themes.md`. This
directory holds only how to search for it.
