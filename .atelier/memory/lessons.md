# lessons

Dated takeaways for this brand. Add as you go, newest at the bottom.

Format, which `scripts/session_brief.py` parses (every dated `##` heading is a
lesson, and the first `lesson:` line under it is what the brief shows):

    ## YYYY-MM-DD — title

    context: what was happening.

    lesson: the one sentence to carry forward.

    cost: what ignoring it would have cost.

    ---

The engine appends its own entries in the same shape when a live test keeps a
pattern (`scripts/livetests.py`), with four more lines the monthly readout
reads: `evidence:` (item ids), `confidence:` (medium or high), `since:` (a date;
`scripts/readout.py` appends `decayed:` after 90 days without new evidence) and
`decay:` (when to re-test). Keep the heading shape exactly: the date first, then
the title.

A lesson is a pattern with evidence behind it; a rule goes in `instincts.md`
and a decision in `decisions/`. Replies and comments are summarised here as
patterns only, never per person.

---
