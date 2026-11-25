# slots, the send times

Suggest when next week's blog picks should go out, for the stream
{stream_name}. You know nothing of this repository beyond this brief. The
picks are in `state/strategy.json`, written by the step
before you; read it, and read the brief
`briefs/send-timing.md` first: where it and the
skill differ, the brief wins.

Invoke the `salon:launch-window` skill (the Skill tool) and, for each entry of
`picks`, write its `time` (`HH:MM`) and `time_why` into that entry, and
nothing else: no other field, no other entry, no other file. If the skill is
not available the plugin is not installed: write nothing and say so in
`summary`.

Return: `timed` (how many picks you gave a time) and `summary` (one sentence).
