# draft

Draft for the stream {stream_name} with `--drafts {drafts}`, as your definition
describes. Read `state/planning.json` first and name on every draft which
planning query the pick answers. Write each draft in the format and the logic
that file drew for its theme, and copy `format`, `logic` and `draw` onto the
item as given. For each finding write three candidates that differ in one
named variable, rank them, queue the first and keep the other two on it as
`alternatives`. Proposals go to `state/queue.json`, the
drafting inbox for items that have no note yet; an item that already has a note
is read from and written to that note. Log `draft` through `scripts/runlog.py`.

Return: `drafted` (how many proposals you appended this run), `ids` (their
ids, as a list of strings; empty when you drafted nothing) and `formats` (the
format of each, in the same order).
