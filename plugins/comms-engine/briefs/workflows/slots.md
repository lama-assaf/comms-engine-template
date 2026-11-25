# slots

Pick next week's blog slots. You know nothing of this repository beyond this
brief. Read `.atelier/memory/instincts.md`, the current campaign file under
`.atelier/memory/campaigns/`, `state/queue.json` and
`state/planning.json`. Pick two blogs for the next ISO
week, at least three days apart, from the queue and the planning order;
everything else is social-only; each pick names which planning query it
answers. Leave `time` and `time_why` out: the step after you suggests them
with salon's `launch-window` skill, which an agent cannot load. Write
`state/strategy.json` (`stream`, `picks`,
`not_this_week`, `week`, `summary`; `stream` is "{stream_name}"). Every entry
of `picks` and of `not_this_week` carries `stream` "{stream_name}" too:
`state_check.py` refuses any record without it. Write nothing
else: no campaign file, no note and no queue entry. Code logs the step.

Return: `picks` (how many blogs you picked) and `week` (the ISO week, such as
"2026-W47").
