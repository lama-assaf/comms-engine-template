# brief: when a piece goes out (salon:launch-window)

Use the skill to suggest, for each blog pick of the week, the hour it and its
teasers should go out. The suggestion is advice for a person; the sender runs
at the times `engine.json` schedules, inside the stream's quiet hours.

- Stay inside the stream's hours: its `quiet hours` cell in
  `.atelier/memory/streams.md`, judged in the timezone of `engine.json`
  `autopilot.timezone`. Never suggest a time inside them.
- Two blogs are at least three days apart; the cap per channel per day is the
  stream's own. A window that needs more than the cap is not a window.
- Give a time as `HH:MM` and one clause of why. No claim about an audience
  the engine has no numbers for.

You write only the `time` and `time_why` of each pick in
`state/strategy.json`. Nothing is scheduled by you.
