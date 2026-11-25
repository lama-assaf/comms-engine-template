---
description: Open the local control page - upcoming posts and their motion cards, the content calendar, themes and their search terms, the accounts we monitor and watch, suggested accounts, listening, replies, claims, scores and jobs - served from this machine only.
argument-hint: [stop|status]
allowed-tools: Bash
---

# /control

1. With no argument, run `engine control start`.
   It starts the page in the background on 127.0.0.1 (or finds it already
   running), prints the URL and opens it in the browser, on the story: the
   run's short deck, in the solid colours of the brand genome's palette, with its big questions to answer. With `stop` or
   `status`, run `control.py stop` or `control.py status` instead. The page is
   the web app in `ui/` (built into `ui/dist`, which is
   committed); the first page is still at `/classic`.
2. Give the person the URL and say what the page can change: a theme's X
   query and keywords (`themes.json`, logged), a new theme (added as held, in
   `themes.md` and `themes.json`, until a person grades it), a theme's licence (Allow…: careful
   wording or free to use, or hold it again, always with the reason), and the watched accounts
   (watch a suggested account, add one by hand, stop watching, dismiss a
   suggestion), which the next listening pass reads. Everything else on it is
   read live from the engine's files and only shown.
3. Decisions on posts stay on the desk (`cd Tooling/desk && npm run
   dev`, port 4310); the page links each post to it.

Never start the page on any address but 127.0.0.1, and never publish it: it
shows the engine's whole state, the private denylist's size included.
