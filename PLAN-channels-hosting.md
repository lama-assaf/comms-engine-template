# Plan: every official channel through Composio, the dashboard as the only surface, self-hosted

Written 2026-11-10. Owner direction, the same day: "run everything through
dashboard and self host in the future, and have composio running through all
official channels". It builds on `PLAN-surfaces.md` (one core, one web app,
acts) and `PLAN-workflows.md` step 2 (the post lifecycle) and step 6 (the
engine as a plugin). Written here first, because this repository is the master
copy; each step ships in both repositories, as the other plans do.

## What it changes in the earlier plans

- `PLAN-surfaces.md`, "What stays as it is": **Notion stops being a publish
  target.** It becomes an optional one-way mirror, and then it goes.
- `PLAN-surfaces.md` step 6, "Hosted (optional)": **hosting becomes a goal.**
  It is still last in the order.
- `PLAN-workflows.md` step 2: the sender reads the lifecycle's `scheduled`
  state, not a Notion row.
- `PLAN-workflows.md` step 6: the plugin carries the channel connector and the
  extended posting guard.

## Scope

**"Official channels"** are the handles each stream lists in the `channels`
cell of its `streams.md` row: today X and a LinkedIn page, and later Telegram
and Discord where a row lists them. Composio carries, for those accounts:

- **writes:** post, reply, comment, delete (Composio's
  `TWITTER_CREATION_OF_A_POST`, the `LINKEDIN_*` post and comment tools,
  `TELEGRAM_SEND_MESSAGE`, `DISCORDBOT_CREATE_MESSAGE`);
- **our own posts' numbers:** `TWITTER_GET_POST_ANALYTICS` and
  `LINKEDIN_GET_SHARE_STATS`. These give impressions where we now see public
  counts only;
- **inbound on our own accounts:** mentions, replies and comments, through
  Composio triggers (`composio listen`);
- **listening on X** (owner, 2026-11-10: "use official x for listening as
  well"): the listening pass's search and the standing monitors use X's own
  API through Composio (`TWITTER_RECENT_SEARCH`,
  `TWITTER_SEARCH_RECENT_COUNTS`) by default. twitterapi.io stays an option
  (owner, same day: "keep twitter api as option when api is available"); see
  step L.

**Out of scope:**

- **Listening on LinkedIn.** It stays on Apify behind `--linkedin`: LinkedIn
  has no official search for other people's posts.
- **The website.** It is not a channel: the site reads the engine (step N3).

## Principles

1. **One connector module.** `scripts/channels.py` exposes `post`, `reply`,
   `comment`, `delete`, `metrics` and `inbound`. It has two drivers:
   - `composio`, the default;
   - `native` (xurl, `linkedin_api.py`), kept only until parity.

   The driver is chosen per stream and channel in
   `engine.json params.channels`. No other script calls Composio, xurl or a
   platform API.
2. **One Composio user per stream.** The `user_id` is the stream slug, and each
   channel is a connected account under it. `channels.py` resolves an account
   only within the stream that asks, so one stream's run cannot reach another
   stream's account. Every connected account's handle must match the stream's
   `channels` cell, or `doctor` fails.
3. **The brand's own app where it has one.** A Composio auth config with the
   brand's X and LinkedIn developer apps,
   so posts show the brand's app and the rate limits are ours.
4. **One send function, with the checks inside it** (owner, 2026-11-10,
   replacing the posting guard and "nothing publishes itself"). Every send,
   from the scheduled sender, the dashboard or an agent, goes through
   `channels.send()`, and it refuses unless every check passes (step C0).
   Who presses send stops mattering; what the text passes is what counts.
5. **Secrets.** `COMPOSIO_API_KEY` resolves through `secrets.py`. The platform
   OAuth tokens live at Composio. That is the one part that is not
   self-hosted, and it is accepted as a dependency.
6. **Rule 6 holds.** Inbound from triggers is summarised as patterns; no
   handle is stored.

## Steps

### C: channels through Composio

- **C0. The send gate, before any account is connected.**
  `channels.send(stream, channel, kind, text, ref)` refuses unless every check
  passes, records each send and each refusal with its reason, and is the only
  code that calls a write tool. The checks:
  1. **The deterministic gate** (`gate_lint.py`) on the exact text.
  2. **Claims:** every `cites` id is current and corroborated in the stream's
     `claims.md`. A post carries its note's cites; a reply carries its own or
     makes no claim.
  3. **The stealth denylist** from `handles.private.md`. If the file is
     missing, the gate blocks; it never passes.
  4. **Hold for review** (rule 4, kept for now): a statistic not in
     `claims.md`, a named counterparty not cleared, or a partner name. Any of
     these needs a person's approval recorded on the item, or the send is
     refused.
  5. **The account belongs to the stream** (principle 2), and **the pair
     rules** of `streams.md` hold.
  6. **Timing and caps** (`guardrails.py`): quiet hours and posts per
     channel per day.
  7. **The kind is allowed:**
     - a post needs an approval and its scheduled time has come;
     - a reply or comment needs either a person's approve-and-send or the
       stream's auto-reply switch on (step D2).

  Before it goes, the guard changes in three ways:
  - `guard_posting.py` stops judging who runs a command;
  - it keeps one job: refusing a raw platform write that bypasses
    `channels.send` (`composio execute` of a write slug, `composio proxy`
    writes, `xurl post`, curl to a platform write endpoint);
  - `<PREFIX>AUTOPILOT_JOB` retires.

  If a Composio MCP server is added, its write tools go into
  `permissions.deny` for the same reason.
- **C1. Connect.** `engine.py setup composio <stream>` links each channel in
  the stream's row. `doctor` gets one line per stream and channel: connected,
  active, and the handle matches.
- **C2. Writes and metrics.** Build `channels.py` with the `composio` driver
  for X and LinkedIn. `autopilot.py` sends through it. Parity tests compare it
  with the native payloads, and the dry runs show the slug and arguments.
  `x_metrics.py` moves to own-post analytics. Scoring then gains impressions,
  recorded as a change of measure on the scorecard, not a result.
- **C3. Inbound.** Composio triggers for mentions and replies on our own
  accounts feed `engage.py`, as patterns only.
- **C4. Retire native.** After two weeks of parity: xurl, `linkedin_api.py`
  and the `LINKEDIN_*` secrets go, and the guard patterns for them stay.
  Owner, 2026-11-10: "if simpler keep composio now". Composio is the only write
  driver, and no X or LinkedIn MCP server is added. If self-hosting later
  needs the tokens back in our hands, a `native` driver returns behind
  `channels.py`, with no change to any caller.
- **C5. Further channels.** Telegram and Discord, when a stream's row lists
  them.

### L: listening on X through the official API

- **L0. Price it first.**
  - Confirm the X API plan behind the stream's auth config and its cost per
    read, then record the monthly cap in `engine.json params.listen`.
  - Reads are billed to the developer app that the Composio auth config uses,
    so this needs principle 3 (the brand's own app).
  - The 2026-10-26 decision rejected the official API on cost. This step
    records the new numbers beside that decision.
- **L1. The listening pass.**
  - `channels.py` gains `search(query, since, max)` and `counts(query)`.
  - `listen.py` searches through it: a counts call first to size each term,
    then a search per term, with `--max` at or under 12 as today.
  - Recent search covers seven days; the pass's window is four.
  - Run the old and new clients side by side for a week. Record how many
    items each keeps per theme, then switch.
- **L2. The standing monitors.**
  - Composio has no tool for X's filtered stream, so the always-on
    WebSocket in `x_stream.py` becomes a scheduled job. It runs the same
    rules as searches with a `since_id`, every 30 minutes in working hours
    (`engine.json jobs`).
  - The held slot's 48-hour trigger does not need anything closer to real
    time.
  - `x_stream.py rules` keeps planning the rules, which become queries.
- **L3. The watchlist.** The `@watched` pass (`from:` each account) moves
  with L1. X's own query length allows more accounts per search than today's
  255 characters, so the search packing in `listen.py` reads the limit from
  config.
- **L4. twitterapi.io stays as a second listening driver.** It is not
  retired.
  - `channels.py`'s `search` and `counts` take a driver, `composio` (the
    default) or `twitterapi`, set per stream in
    `engine.json params.listen.x_driver`.
  - `twitterapi` is used when it is chosen and `TWITTERAPI_IO_KEY` resolves
    through `secrets.py`.
  - It is also the fallback when the official API is unavailable: no
    connected account, an exhausted cap, or an error. The fallback is
    logged on the run, never silent.
  - The always-on WebSocket in `x_stream.py` stays available on the same
    terms, for a stream that wants real time. Its rules are applied only
    while that driver is chosen, because an active rule is billed per match.
  - `doctor` gets one line saying which X read driver each stream uses, and
    whether the fallback is armed.
  - Read-only: twitterapi.io never posts.
  - **Two read classes, one hold each (owner choice, 2026-11-11).** The
    price hold is per read class, not one switch. Listening and the standing
    monitors (`search`, `counts`, `x_stream.py poll`) take
    `channels.x_read.<stream>` and `listen.x_price_signoff`. Our own accounts
    (own-post numbers through `x_metrics.py`, mentions and replies through
    `inbound.py`) take `channels.x_own.<stream>` and
    `listen.x_own_price_signoff`. Each driver is `twitterapi` (the default) or
    `composio`; a class runs on composio only when its driver says composio
    and its own sign-off is recorded, and one class's sign-off never releases
    the other. A sign-off is a dated owner note scoped to what was accepted.
    `doctor` shows both drivers and the hold per class.
  - **A create call that succeeded is a send.** Once a Composio write tool
    answers `successful: true`, a result whose post id or urn cannot be read is
    recorded as sent with an unknown url and a warning on the run log, never as
    failed, so the ledger leaves no row a later run could send again.

### D: what a person controls from the dashboard (owner, 2026-11-10)

- **D1. Posts go out on their scheduled date.** Approving on the dashboard
  sets `scheduled`, and the sender sends at that time, through
  `channels.send`. Approving never sends at once.
- **D2. Replies and comments.**
  - **Now:** the dashboard shows each drafted reply or comment with the
    post it answers. "Approve and send" sends it at once, through
    `channels.send` (quiet hours and caps still apply, and a refusal shows
    its reason).
  - **The switch:** one auto-reply switch per stream and channel, `off`
    until the owner turns it on. With it on, `engage.py` sends the replies
    and comments it drafts, through the same gate, with no person in the
    loop.
  - The switch is a dashboard act (`switch`), kept in
    `state/switches.json` with who changed it (a role) and when. The switch
    can only tighten what `streams.md` allows.
  - Turning it off takes effect on the next send.
- **D3. The hold is a dashboard switch** (owner, 2026-11-13, replacing "the
  hold stays for now"; `PLAN-autonomy.md` section A). Check 4 of C0
  (statistics, named counterparties, partners) is the kind `hold` of the
  review switch, per stream and channel. On `review`, the default, it waits
  for a person on the dashboard. On `auto`, turned on by a person as a recorded
  act, the check passes without a release. It is a switch, never a code change,
  and every other check of C0 runs in both modes.

### N: Notion out, the dashboard the only surface

_Done 2026-11-13 (`.gg/plans/notion-out.md`): N1 to N4 below, with the control
page as the surface and a JSON feed for the site. N3's last mile, pointing the
site at the feed, waits on the site's owner (Open, 1)._

- **N1. The sender reads the lifecycle.** After `PLAN-workflows.md` step 2:
  - a post is sent when it is `scheduled` with a date that has come;
  - the ledger stays the record of what was sent, with its URL;
  - `autopilot.py snapshot` and `mark_published` stop reading and writing
    Notion;
  - Notion, while it remains, gets a one-way push only.

  Do this together with C2, because both rewrite the sender.
- **N2. The dashboard schedules.** The desk's calendar, queue and item editor
  are ported (already `PLAN-surfaces.md` step 4). The dashboard adds:
  - a `schedule` act (date, channel);
  - "team rows": posts a person writes and marks ready, which today start in
    Notion;
  - the sent URL on every post.
- **N3. The website reads the engine.** A published blog post becomes a view,
  `published_posts` (JSON, served by the API, or committed markdown the site
  builds from). The site's Notion read and its Notion webhook are replaced.
  This step needs the website's owner.
- **N4. Retire Notion.** The following go, and the docs and handover are
  repointed:
  - `Tooling/notion-sync/`;
  - the `notion-database` kind in `publish-targets.example.json`;
  - `NOTION_TOKEN`;
  - the Notion server in `.mcp.json`;
  - the `notion_page_id` carry-forward in `repo.py`;
  - the `notion:*` entries in `score.py`.

  A brand's decision that lets the sender create a Blog row as `Published`
  is restated against the engine's record.

### H: self-hosted

_Amended 2026-11-14 (owner, `decisions/2026-11-14-package-and-host.md`): the
host is a Mac on the office network, the door is Tailscale Serve, and the
engine runs as the `comms-engine` plugin inside one instance repository per
brand. Built as step 19 of `PLAN-autonomy.md`; `docs/07-hosting.md` is the
runbook._

- **H1. One Mac runs the whole instance.** The instance repository, the API,
  the scheduled jobs and Claude Code (`claude -p`) run together on one office
  Mac, under a dedicated macOS user with automatic login (LaunchAgents and the
  login keychain need a GUI session), `pmset` set to no sleep and restart
  after a power failure, and the `nosleep` job. `engine host-check` reports
  one ok/FAIL line for each thing the runbook sets up. Postgres is needed only
  if the screens and the record run on different machines.
- **H2. A fixed path for launchd.** The plugin's root changes on every update,
  so `engine shim --install` writes `~/.local/bin/comms-engine`, which finds
  the current root in `~/.claude/plugins/installed_plugins.json` at each
  start. Every plist runs `comms-engine runjob <label>` with
  `COMMS_ENGINE_INSTANCE` set. systemd timers are not built.
- **H3. The Claude token in the keychain.** `secrets.py` knows
  `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`); `workflow.py` gives
  it to `claude -p` only. `params.host.claude_token_set` records the date and
  `doctor` warns after 330 days. The keychain stays the only backend.
- **H4. The API behind Tailscale Serve.** It keeps binding 127.0.0.1;
  `tailscale serve --bg 4320` puts it on the tailnet. A request for the
  `params.host.serve_name` host must carry `Tailscale-User-Login`, which maps
  to a role through the gitignored `engine.local.json host.roles`; an
  unmapped login is refused and the role becomes each act's `by`, never a
  name. The token check stays.
- **H5. The gate on the host.** `channels.send` runs the same checks wherever
  it runs, and `handles.private.md` is copied to the Mac by hand over
  Tailscale, never through git. `host-check` fails without it.
- **H6. History and backups.** `scripts/backup.py`, a daily job, commits the
  record paths only, pulls with rebase and pushes with the Mac's deploy key,
  only when `params.backup.push` is true. A conflict stops it; nothing is
  forced. Git stays the history.

## Order

C0, C1, L0, then N1, C2 and D1 together, then D2, then L1 to L3 (side by side), N2, N3, N4,
C3, C4, L4 (the driver switch, built with L1), then H1 to H6.

## Done when

- Every post, reply and comment on an official channel goes through
  `channels.send`, which refuses anything that fails a check, whoever calls
  it.
- The auto-reply switch is on the dashboard, off by default, and a send with
  it off and no approval is refused (tested).
- Every read of X goes through `channels.py`: X's own API by default, and
  twitterapi.io when it is chosen or as the logged fallback.
- No script, doc or job reads or writes Notion.
- A person can do every act from the dashboard, from a phone, signed in.
- `engine doctor` and `engine host-check` pass on the office Mac, reached
  from a phone over Tailscale with a mapped identity.

## Open, for the owner

1. The website: who points the site at the published-posts feed (`GET
   /api/published`, or `engine.py export-published` for a build), now that the
   Notion read is gone (N3)?
2. Composio's default apps, or the brand's own X and LinkedIn developer apps
   (principle 3)? Recommended: the brand's own.
3. Answered 2026-11-14: a Mac on the office network behind Tailscale Serve;
   who signs in is the `host.roles` map of that Mac's `engine.local.json` (H4).
4. Answered by N2 (2026-11-13): team posts are written on the control page's
   new-post form.
