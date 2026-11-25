# distribute

Distribute for the stream {stream_name}, as your definition describes: apply the
saved edits to the items' notes (`scripts/apply_edits.py`), apply the decisions
to those notes, run the `publish` skill for approved items, and log
`distribute` through `scripts/runlog.py`.

An edit reaches a note only while the note still hashes to the `base_hash` the
desk recorded. Where it does not, nothing is written, both versions are kept and
the item is flagged until a person runs `scripts/apply_edits.py <id> --prefer
desk|vault`. The resolution is never yours to pick: report the conflict.

An applied edit is a new draft, so `publish.py` refuses it until the gate has
re-read it. Do not gate it yourself: name its id in `edited_ids` and the runner
runs the gate over those ids and then calls you once more.

Return: `decisions_applied`, `edits_applied`, `published` (whole numbers),
`edited_ids` (ids whose edit you applied this call and that still need the gate;
empty on the second call) and `conflicts` (ids left flagged for a person).
