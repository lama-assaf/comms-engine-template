# readout

The monthly readout for the stream {stream_name}. `scripts/readout.py` has
already run in this workflow. Run
`engine research_store topic-map --write .atelier/memory/campaigns/<current campaign>.md`,
then invoke the `salon:campaign-retro` skill (the Skill tool) over the readout
file (`state/readout-<month>.json`) and the scorecard,
writing `## retro` into the campaign file. A lesson it promotes keeps the
`## YYYY-MM-DD` heading `lessons.md` is read by. The readout's correlation is
the one number; a decision file is written only when a person agrees to it,
never by you. If the skill is not available, the plugin is not installed: write
the retro yourself as this brief reads and say so in `summary`. Code logs the
step.

Return: `retro_written` (true or false) and `lessons` (how many lessons were
promoted).
