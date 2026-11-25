---
description: Run only the listening half of the cycle - X via twitterapi.io plus primary sources - and refresh state/signals.json and the dashboard.
argument-hint: [theme tags, comma-separated] [--max N]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, WebSearch
---

# /listen-themes

Spawn the `comms-engine:listener` agent with `$ARGUMENTS` as the restriction (theme tags
from `.atelier/memory/themes.md` and/or `--max N` for items per search term).
Then run `engine build_dashboard`.

Report the per-theme table and the top findings. Nothing is drafted or posted.
