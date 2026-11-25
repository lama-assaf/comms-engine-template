# The social engine

A listening-and-theme loop for one brand's communications, built as a schedule
of Claude Code agents, project skills and scripts, with a desk where a person
decides. The brand's doctrine (what it is, what it may claim, which themes it
leads on, whose handles it may tag) lives in `.atelier/memory/`; this folder is
the machine that reads it.

The vocabulary the engine uses throughout: **Alpha** is the person whose
judgment the loop cannot replace (what may be claimed, and when; which draft
goes out); **Beta** is everything the engine does around that judgment
(listening, drafting, gating, distributing, scoring). A **stream** is one
business the engine serves; the root stream is the brand in `engine.json`'s
`brand` block, and others live under `.atelier/memory/streams/<slug>/`.

## What the loop does, and where each part lives

| the doctrine asks for | implementation |
|---|---|
| *Monitoring themes and mentions detects community signals* | `scripts/listen.py` (X via twitterapi.io's advanced search; LinkedIn via Apify only with `--linkedin`) + the `listener` agent running the `theme-listening` skill, which adds the primary-source sweep and the held-slot trigger test |
| *Relevance and sentiment feed content inspiration, interaction proposals and reach amplification* | `state/signals.json` read by `theme-writer` (content), engagement-manager (interaction proposals), partner tags on every teaser (amplification) |
| *Themes: AI-assisted in sourcing, teasers and distribution; every post claims a hashtag, tags the partner* | `theme-post` skill: full post for the brand's site + LinkedIn teaser + X teaser, `#theme @partners` tag line, CTA to the blog |
| *Zero claims of live or deployed capability ahead of delivery* | `claim-gate` skill and the `gatekeeper` agent: nine checks against `status.md`, `instincts.md`, `claims.md` and the theme licence; quotes the offending line. `scripts/gate_lint.py` runs first and decides the checks that need no judgment, so the model reads for judgment only |
| *A theme is licensed by the layer beneath it; a layer that has not shipped yields no theme* | `.atelier/memory/themes.md`, *licence and layer*: each theme carries `licence` (licensed / licensed-with-hedge / held) graded against `status.md`, and what the cap allows |
| *Alpha: reading listener signals, deciding which fact may be claimed, and when* | The desk's Alpha queue. Decisions are stored in the desk's database and pulled back by `/social-cycle` |
| *Alpha writes the theme insights* | On the desk each item edits the title, post and both teasers in place; "Save edit" stores `edits/<id>` with a `base_hash` of the note as the desk rendered it. `scripts/apply_edits.py` writes that edit into the `Content/Calendar/` note **only while the note still hashes to it** (a desk edit and a vault-side change are reconciled by skipping, never by clobbering) and `publish.py` refuses an edited item until the gatekeeper has re-read it |
| *Website first: everything publishes on the brand's own site before anywhere else* | `publish` skill + `scripts/publish.py`: vault note, then a person marks the article live on the control page (the site reads the published-posts feed and the site webhook rebuilds it), then the teasers, with the link in a first reply. The site's URL shape is `site.post_url` in `engine.json` |
| *Released manually through a dedicated approval flow* | The engine stops one step short of the site and of every handle, by design |
| *A steady release cadence* | `engine.json` `jobs`: the cycle runs every weekday morning so the queue always holds more candidates than the week needs |
| *Content repository as the single source* | `Content/Calendar/` in this vault. `scripts/repo.py` writes a queue item there at **draft** time (`status: Idea`) and rewrites it on approval (`status: Ready`), so the note, not `queue.json`, is where an item lives. `queue.json` is a derived index rebuilt from the notes (`repo.py --index`), and the desk is built from the notes too: delete the index and nothing is lost |
| *Theme, partner and handles inventory kept current* | `.atelier/memory/handles.md`, per row a `verified`/`collect` status, the themes it may be tagged on and a `last_verified` date. No `inventory.json`: this table is the inventory. **Kept current** by `scripts/inventory.py` and the `inventory-refresh` skill, a step in `/social-cycle`: one 30-day threshold governs both the staleness flag and the paid profile call, so a second run inside the window spends nothing. LinkedIn slugs stay manual; blanks and inconclusive checks go to Alpha; the desk's Inventory section renders the same rows with the same flag |

## The learning loop (plan v2)

| what | where it lives |
|---|---|
| the streams the engine serves, with owner state, autopilot rule, guardrails and pair rules | `.atelier/memory/streams.md`, read by `scripts/memory.py` (`--list`); other streams' memory under `streams/<slug>/` |
| `stream` on every record | `repo.py` refuses an item without one; `scripts/state_check.py` checks every state file; `runlog.py --stream` |
| the claims register and cites | `.atelier/memory/claims.md`; `cites` on every note; `gate_lint.py` checks `lint: stream`, `lint: cites`, `lint: hypothesis` |
| supersession and decay | `scripts/claims_check.py` nightly (the `claims-check` job) writes `state/claims-review.json`, shown on the desk and under *Waiting for you* on the dashboard page |
| planning queries, hypothesis, prediction | `scripts/plan_queries.py` writes `state/planning.json`; `query`, `hypothesis`, `predicted`, `test_id` on every draft; `scripts/predictions.py` |
| scoring, the scorecard, live tests | `scripts/score.py` (72 h and 7 d; inputs in `state/metrics-input/<id>.json` until the platform logins exist), `scripts/metrics.py`, `scripts/livetests.py`, nightly through the `score` job |
| the monthly readout | `scripts/readout.py` + salon `campaign-retro` (`/social-cycle --readout`) |
| guardrails and per-stream credentials | `scripts/guardrails.py` (read by `publish.py` and the autopilot); `secrets.get_secret(name, stream=...)` |
| the research store | `scripts/research_store.py` (files mode until Graphiti and FalkorDB run; `research-store/`), the daily watch in `/social-cycle` step 2, the monthly topic map in the campaign file |
| engagement acts | `scripts/engage.py` (shape, tier, outcome at 72 h), partner reposts in `score.py`, the golden-hour checklist on a published card |

How the pieces run together, which job owns what, and the failure modes:
`ORCHESTRATION.md`. The design and what remains: `PLAN.md`. The console that
runs it: `CONSOLE-CONTRACT.md`.

## Where the doctrine lives

`.atelier/memory/` is the single source for theme and handle data, and the
engine reads it through `scripts/memory.py`; nothing keeps a copy.

| what | file |
|---|---|
| the themes, their differentiators, the fact each links back to, cleared partner tags, intro-post state | `.atelier/memory/themes.md` |
| layer, licence grade, logics and licence basis per theme | `.atelier/memory/themes.md`, *licence and layer* |
| own channels, cleared partners, standards bodies, with `status`, `themes` and `last_verified` per row | `.atelier/memory/handles.md` |
| stealth and unsigned-draft parties, and the denylist a draft may not echo | `.atelier/memory/handles.private.md` (gitignored, merged at read time; `handles.private.example.md` is its shape) |
| one checkable claim per row, with grade, source, tier and corroboration | `.atelier/memory/claims.md` |
| one X search term and keyword set per theme | `themes.json`, engine-local, and nothing else |

A hashtag not in `themes.md` is not a theme. The two halves are joined by tag,
and a term with no theme row, or a theme row with no term, is an error rather
than a silent skip.

## The brand block

`engine.json` carries one `brand` block: `slug`, `name`, `label_prefix`,
`env_prefix`, `keychain_service`. It is the only place the business this
checkout serves is named. A fresh clone carries the placeholder `acme` /
`Acme`; `python3 scripts/engine.py init --slug <slug> --name "<Name>"` stamps
the real one, renames the placeholder stream row in `streams.md` and prints the
first commands. Every launchd label (`<label_prefix>.<job name>`), every
environment override (`<env_prefix><SECTION>_<KEY>`), the keychain service and
the root stream derive from it through `scripts/config.py`; nothing else in
code spells a brand. `TEMPLATE-CONTRACT.md` at the repository root is the full
derivation table.

## The loop

```
             ┌──────────────────────────── schedule (launchd, weekday mornings) ───────────────────────────┐
             │                                                                                            │
   listen ──► assess ──► draft ──► gate ──► [ Alpha decides on the desk ] ──► distribute ──► amplify
   Beta       Beta       Beta      Beta                 Alpha                      Beta          Beta
   listen.py  listener   theme-    gate-                 db: decisions/<id>          distributor   teasers,
   + web      agent      writer    keeper                                           publish.py    partner tags,
   sweep                 agent     agent                                            → vault       comment
                                                                                    → (manual)    proposals
                                                                                      the site
```

Every box left of Alpha is *proposal*. Every box right of Alpha acts only on an
`approved` decision, and still stops before the site's `Published` flip and
before any social handle, except where the stream's `autopilot` cell in
`streams.md` says otherwise.

## Files

```

  README.md                 this file
  install.sh                optional: --check (symlinks, plugins, secrets, tools) and --relink
                            (recreate the tracked relative symlinks in .claude/ after adding a
                            file under claude/). A fresh clone needs neither: .claude/ is tracked
  CONSOLE-CONTRACT.md       the console's contract: engine.json's keys and which script reads each, config.py's
                            API, engine.py's subcommands with stdout and exit codes, the TUI, /engine and
                            onboarding. PLAN-engine-console.md is the plan it was built from
  claude/
    settings/hooks.json     the project hooks, documented copy of what .claude/settings.json carries:
                            SessionStart runs scripts/session_brief.py; PreToolUse on Bash runs
                            hooks/guard_posting.py
    hooks/guard_posting.py  refuses a raw platform write that bypasses channels.send() (xurl writes, API writes, composio
                            write slugs, proxy non-GETs, composio run); engine scripts pass
    agents/                 listener · theme-writer · gatekeeper · distributor · motion-designer · storyteller
    skills/                 theme-listening · theme-post · claim-gate · publish · x-post · linkedin-post ·
                            inventory-refresh · engine-console (which engine subcommand answers which
                            question about jobs, schedules and health) · motion-post (a motion card from a
                            gated post's own lines) · story-deck (the run's story as a short deck)
    commands/               /social-cycle · /listen-themes · /alpha-queue · /announce · /motion · /control · /story · /engine (the console in
                            chat: calls engine.py, asks the setup questions with AskUserQuestion, confirms
                            enable, disable and --live once; headless it reads and never writes)
  themes.json               engine-local only: per theme one X search term, one LinkedIn
                            search string and one keyword set
  scripts/
    session_brief.py        the SessionStart brief: latest listening pass, X stream heartbeat,
                            lessons/decisions/reviews new since the last session on this clone
                            (marker .claude/session-brief.json; --dry-run, --reset)
    memory.py               the read path into .atelier/memory/ (streams, themes, handles, claims)
    secrets.py              the one token resolver: environment, then the macOS keychain under
                            brand.keychain_service
    config.py               the one read path into engine.json: cfg("cycle.drafts", 3), layered
                            engine.json < engine.local.json (gitignored, per machine) < <ENV_PREFIX><SECTION>_<KEY>;
                            the brand block and every derivation from it (label, env-name, log-dir).
                            CLI: get, set (writes the local file, refuses jobs and path), show, brand, labels
    engine.py               the engine console: one CLI over the eight jobs, and the only module that
                            calls launchctl, install.sh, runjob.py and the dry runs. init (the brand block),
                            status, run <job> (dry unless --live; --live refused for autopilot, x-stream,
                            nosleep), enable/disable, logs, doctor (every check in CLAUDE.md, one line each),
                            setup <job> (every question a --<key> flag with a default, asked only on a
                            terminal, written to engine.local.json, ending in the job's dry run), secrets,
                            plugins, onboard-stream. Prints `$ <command>` before every act
    engine_tui.py           the console as one curses screen over engine.py (stdlib, no dependency)
    onboard.py              `onboard-stream <slug>`: where a stream stands before it may draft; writes only
                            engine.local.json streams.<slug> and, with --write-voice, a shaped voice.md;
                            prints the streams.md row for a person and never writes it
    listen.py               X listening pass via twitterapi.io (runs without a session);
                            --linkedin adds the two paid Apify actors
    twitterapi.py           the twitterapi.io client (search, public counts, user/info)
    x_stream.py             standing X monitors on twitterapi.io: `rules` keeps the <slug>:* filter
                            rules in step with themes.json and handles.md, `listen` holds the
                            WebSocket and appends matches to state/x-stream/<date>.jsonl, `digest`
                            reads them back
                            `poll [--dry-run]` runs the same rules as the scheduled x-poll search
                            (optional job, every 30 min in working hours, since_id in
                            state/x-stream/poll.json, params.x_stream.mode `poll` by default);
                            `rules --apply` is refused unless mode is `websocket` and the
                            effective X read driver is twitterapi
    inbound.py              the scheduled inbound poll (optional job, every 20 min in working hours):
                            `poll [--dry-run]` runs channels.inbound for X (mentions rule + replies in
                            our recent posts' conversations; held until params.listen.x_own_price_signoff and channels.x_own.<stream> composio)
                            and LinkedIn (comments via a `composio proxy` GET; needs a linked account),
                            cursor per channel in state/inbound.json, counts merged into
                            engagement.json `inbound` as patterns only, no handle; `status` says on/held/off
    x_metrics.py            public counts for our own X posts, before score.py
    story.py                the story of each run: facts (gathered), check (no invented number, nothing on
                            the denylist, big and short), publish (latest.json, questions kept), answers
    genome.py               the brand genome (.atelier/memory/brand-genome.json): the look every visual reads
    views.py                every view of the engine, computed once from the record (posts, calendar, themes,
                            accounts, suggested, listening, replies, claims, learning, engine, story, genome);
                            writes nothing. `views.py` lists them, `views.py <name>` prints one, `--all --out F`
                            writes what the control page reads
    theme_words.py          each theme's licence in plain words (what we may say, what we never say, why, what
                            would move it up) for the Themes page: facts, check, publish, status; the storyteller
                            writes them (theme-words skill) whenever a grade or rule changes
    held_theme.py           the one writer of themes.md besides /corpus-update --apply: a person's new theme
                            (held, in both tables) and a person's licence grade (allow or hold, with the reason;
                            the status log keeps the grade and reason it replaced), read back or put back
    ../ui/                  the control page's web app (Vite, React, TypeScript; see ui/README.md): built into
                            ui/dist, which is committed, so the page runs with plain python3
    control.py              the local control page (ui/dist; control/page.html at /classic) on 127.0.0.1:4320: every view from
                            views.py, explained in plain words; it changes only a theme's search terms
                            (themes.json, logged), adds a theme as held (through held_theme.py, + themes.json),
                            and the watchlist (state/watchlist.json, read by listen.py's @watched pass). start,
                            stop, status, serve; Host, Origin and a per-page token keep it local
    motion.py               a motion card for one gated post: `brief`, `check` (every line word for word
                            from the post, the theme, the CTA, the denylist, the gate verdict), `render`
                            (poster, GIF, and MP4 with ffmpeg; Pillow), `pending` (the blog posts the cycle owes
                            a card, step 7a); params.cycle.motion and motion_per_cycle; never posts
    inventory.py            keeps .atelier/memory/handles.md current: confirms the X handles whose row
                            is past the 30-day window (or whose handle changed since the last run, per
                            state/inventory-ledger.json), stamps last_verified, calls nothing for the rest
    plan_queries.py         the three planning queries per theme (gaps, freshness, depth) into
                            state/planning.json
    research_store.py       the research store: watch, candidates, topic map (files mode until a graph runs)
    repo.py                 the engine's two-way path into Content/Calendar/. write_item(item, status) is
                            the only writer of an engine note; load_items() reads them back; --index
                            rebuilds state/queue.json; <id> --set k=v writes a decision onto a note;
                            post_url(slug) is the article URL from engine.json site.post_url
    gate_lint.py            the deterministic half of the gate: status words (the brand's rules, empty
                            in the template), stealth denylist, partner tags, the "what we do not claim"
                            sentence, tag line, CTA, hook, stream, cites, hypothesis. --write records
                            the results into gate.checks as `lint: <name>` entries. Blocks, never
                            passes, when handles.private.md is missing from the checkout
    announce_check.py       reads a partner-announcement folder (blog and social .docx, banner) for
                            /announce: the claim gate plus placeholders, names spelled two ways, what the
                            autopilot will refuse, status.md claims and partner clearance; writes plan.json
                            and plan.md, nothing else
    apply_edits.py          Alpha's desk edits into the notes, never over them: only while the note still
                            hashes to the base_hash the desk recorded; otherwise flagged and left for a
                            person's `<id> --prefer desk|vault`
    publish.py              approved queue item into the approval path: refusal checks, repo.write_item(item,
                            "Ready"), --webhook site rebuild (site.webhook_url,
                            <ENV_PREFIX>WEBHOOK_SECRET), run log
    runlog.py               one entry in state/runs.json, appended by whoever did the work; the four agents
                            call it as they finish (assess, draft, gate, distribute)
    desk_sync.py            the desk edge: --pull writes Alpha's acts out of state/desk.db (decisions,
                            edits, arguments, standing reviews); --push refreshes the mirror tables and
                            refuses the four decision tables
    build_dashboard.py      inlines the notes (via repo.py) and the state the page reads (signals,
                            decisions, edits, arguments, engagement, claims review, setup) into
                            dashboard/index.html: the posts and what is live (the replies drafted for
                            it, what was heard), the reasons behind Read more, the setup steps until
                            they are walked. No run, job or scorecard on the page; those are the
                            console's and the desk's
    setup_state.py          where the checkout stands between clone and running engine, as ordered
                            steps with the next command; the page shows them until every required
                            one is done
    cycle.sh                headless `claude -p "/social-cycle"` for the schedule: a budget cap, the
                            weekday's flags, the secrets exported for the run
    autopilot.py            the sender: `snapshot` (the notes into state/calendar-snapshot.json and
                            .atelier/memory/calendar.md), `post` (scheduled LinkedIn and X posts due
                            today, after channels.send() and its checks), `links` (article link once a
                            person marked the article live), `commit` (opt in), `status`; --dry from anywhere. Ledger
                            before send, never twice
    guardrails.py           the registry's guardrails (drafts-only channels, caps, quiet hours in
                            autopilot.timezone, blocked topics, hold-for-review classes) as one check
    linkedin_api.py         the brand's page through LinkedIn's Posts API and Social Actions; credentials
                            through secrets.py, refreshed token written back to the keychain
    engage.py               engagement acts: record, outcome, due (drafts only; nothing sends)
    score.py / metrics.py / livetests.py / predictions.py / readout.py / claims_check.py
                            the measurement layer: scoring at 72 h and 7 d, the scorecard rows, live
                            tests, predicted beside actual, the monthly readout, supersession and decay
    state_check.py          every state record names a registered stream
    jobs_status.py          every scheduled job: loaded or not, last run, stale or ok; the job list and
                            each job's `what` come from engine.json
    serve_asset.py          serves one image on localhost for the linkedin-post skill's iframe hand-off
    import_env_secrets.py   one-time: KEY=VALUE secrets from a file into the keychain
  tests/                    the suite (python3 -m unittest discover plugins/comms-engine/tests); every
                            test on fixtures under tests/, none on live state
  engine.json               the engine in one file: `brand`, `jobs` (eight scheduled jobs: name, program,
                            calendar, log; __REPO__ in place of a path), `params` per job (what the scripts
                            read through scripts/config.py, plus `site` and `secrets`), `streams` (per-slug
                            overrides). engine.local.json beside it (gitignored) overrides params and streams
                            per machine; <ENV_PREFIX><SECTION>_<KEY> wins. See CONSOLE-CONTRACT.md
  schedule/
    render.py               engine.json `jobs` into launchd plists for this checkout
    runjob.py               the launcher every plist calls: reads the job's program from engine.json and
                            hands it to zsh with <ENV_PREFIX>REPO set, so launchd never opens a script under
                            a protected folder itself; --show <job> prints the command, runs nothing
    install.sh              --dry-run | (install) | --with-optional | --only <label> | --uninstall | --status
                            reads engine.json; `engine enable <job>` wraps --only <label>, `disable` boots out
  mcp/
    push-servers.json       the scheduler / X MCPs to add when pushing is switched on (from salon's catalog)
  research-store/           the FalkorDB compose file and README for the research store, when a host is named
  dashboard/
    template.html           the page
    index.html              built page, opened locally in a browser; a build artefact, not a source
  desk/                     the Next.js desk over Drizzle and SQLite (state/desk.db): Alpha's surface
  state/                    run state, all derived or appended; README.md explains each file. Empty in the
                            template except the two READMEs

.claude/settings.json, .claude/agents, .claude/skills, .claude/commands   tracked: settings with the hooks and
                            plugin enablement; relative symlinks to the above (no install step)
```

Salon agents (`campaign-strategist`, `engagement-manager`, `community-manager`)
and atelier's `copywriter` / `brand-voice-keeper` are used as written in the
plugin cache; the four project agents above wrap them with the stream's rules.
The shared memory in `.atelier/memory/` (voice, instincts, status, logics,
campaigns) is read by every step exactly as the plugins' memory contract
specifies.

## MCPs and paid readers

| need | server | status |
|---|---|---|
| Listen on X | twitterapi.io through `scripts/twitterapi.py` (search, public counts) and `scripts/x_stream.py` (stream); not an MCP | key `TWITTERAPI_IO_API_KEY` through `scripts/secrets.py` |
| Listen on LinkedIn | `listen.py --linkedin` over REST (Apify actors) | key `APIFY_TOKEN` through `scripts/secrets.py`; the in-session MCP form is optional, catalogued in `mcp/push-servers.json`, and not in `.mcp.json` so a plain `claude` needs no environment variable |
| Content the site reads | not an MCP: the published-posts feed (`GET /api/published`, `engine export-published`) | built from the notes |
| Push teasers to LinkedIn and X | typefully / buffer / postiz | catalogued in `mcp/push-servers.json`, not enabled |
| Read replies and mentions on our own handle | official X MCP (xurl) | catalogued, not enabled, paid plan |
| Rebuild the website | not an MCP: marking the article live on the control page, or `publish.py --webhook` | needs `site.webhook_url` and `<ENV_PREFIX>WEBHOOK_SECRET` |

The listening script calls twitterapi.io over REST for X, and Apify over REST for
LinkedIn when `--linkedin` is given, so the schedule runs with no interactive
session. The Apify MCP carries the LinkedIn actors for in-session work only.

It does not trust a reader to honour the look-back window: `listen.py` parses
every timestamp itself and drops anything outside `--days`, or with a timestamp
it cannot read at all. The count is reported as `dropped_stale` in
`listening-<run>.json` and in the run log.

## Secrets

No token lives in a file. `scripts/secrets.py` is the only place one is
resolved, through an ordered chain (the process environment first, then the
macOS login keychain, service `brand.keychain_service`, account = the token's
name), so a later store is a change there and nowhere else. `listen.py` and
`channels.py` both ask it; neither knows where a token is kept.

Seed the required items once per machine:

```bash
engine secrets            # what is present, what is missing
engine secrets --set TWITTERAPI_IO_API_KEY
engine secrets --check            # resolve?
```

`secrets --set` writes the keychain item with `-T /usr/bin/security` on its
ACL. Without that, macOS raises an "allow access?" GUI prompt on first read,
which the unattended launchd run has nobody to answer and would sit on until
the next cycle was due. `security add-generic-password -U` updates a value but
not an ACL, so an item created without `-T` must be deleted and re-added
rather than updated.

The sender (`autopilot.py`) needs, in addition, the LinkedIn set for the page
(`LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, `LINKEDIN_ORG_ID`,
`LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_REFRESH_TOKEN`, `LINKEDIN_TOKEN_EXPIRES_AT`)
and the X login for the xurl app named after the brand's slug. From a
`KEY=VALUE` file they move in once:

```bash
engine import_env_secrets <file> --dry-run
engine import_env_secrets <file> LINKEDIN_CLIENT_ID LINKEDIN_CLIENT_SECRET ...
engine linkedin_api status
```

Nothing in `.mcp.json` needs an environment variable, so plain `claude` in the
repo is the whole start-up. `cycle.sh` and the plists export what the scripts
need for a run with `secrets.py --export NAME ...`.

## Running it

```bash
# a fresh clone: stamp the brand, then check the machine
engine init --slug <slug> --name "<Name>"
engine doctor        # every check CLAUDE.md lists, one ok/FAIL line each
install.sh --check                      # symlinks, plugins, secrets, tools

# the console: what is loaded, what ran, what is stale
engine status        # the jobs table, then secrets, plugins, the last cycle
engine run cycle     # a job's dry form; --live runs it as the schedule would
engine setup corpus  # the questionnaire; headless, every answer is a --<key> flag
engine logs corpus   # the job's own log, then launchd's
engine engine_tui           # the same as one screen; in Claude Code, /engine

# one listening pass (about USD 0.07 at default caps; X only)
engine listen --max 10 --days 7

# the same pass with LinkedIn: USD 0.0015-0.002 per post and again for each
# author profile, against USD 0.00018-0.00025 per tweet, about 16x per item
engine listen --max 10 --days 7 --linkedin

# rebuild the dashboard page (the posts and what is live) from the notes and state
engine build_dashboard

# a full cycle, interactively
/social-cycle --drafts 3

# a full cycle, headless (what the schedule runs)
scripts/cycle.sh

# the schedules (engine.json `jobs` into launchd for this checkout; engine enable/disable wrap these)
schedule/install.sh --dry-run    # render, load nothing
schedule/install.sh              # load every job but the optional x-stream
schedule/install.sh --status     # what is loaded, when each last ran

# the sender, against the live calendar, sending nothing
engine autopilot run --dry
engine autopilot snapshot   # calendar.md and the snapshot, no send

# standing X monitors (twitterapi.io). Start the listener first: an active rule is
# billed per matched post (USD 0.15 per 1,000) whether or not anything is connected.
engine enable x-stream
engine x_stream rules            # the plan, changes nothing
engine x_stream rules --apply    # set and activate the rules
engine x_stream digest --hours 24
engine x_stream rules --off      # stop billing

# ingest new drafts into the content repository (status: Idea), then rebuild the index
engine repo --all

# rebuild state/queue.json from the notes on its own (the index is derived)
engine repo --index

# record a decision on an item's note (the index follows)
engine repo Q-<id> --set alpha_status=approved

# what the inventory refresh would cost this cycle, calling nothing
engine inventory --dry-run

# the refresh itself: only the rows past the 30-day window are paid for
engine inventory

# a deliberate full sweep of every recorded X handle (never on the schedule)
engine inventory --force-all

# the deterministic gate checks, over every item (--write records them)
engine gate_lint
engine gate_lint Q-<id> --write

# the suite
python3 -m unittest discover plugins/comms-engine/tests

# apply Alpha's desk edits to the notes (conflicts are skipped, never clobbered)
engine apply_edits
engine apply_edits Q-<id> --prefer desk   # resolve: Alpha's text wins
engine apply_edits Q-<id> --prefer vault  # resolve: the note stands

# a step's own row in the run log (this is how the four agents log themselves)
engine runlog gate "gatekeeper: 2 pass-with-edits, 1 block" --stream "<Name>"

# act on an approval (after Alpha decides on the desk)
engine publish Q-<id>
```

## What a fresh clone has, and what it does not

Has: the whole loop as code, the console, the desk, the corpus reader, the
tests on fixtures, and `.atelier/memory/` as templates with
every file's shape and rules.

Does not have, until the brand supplies it: a corpus root (`setup corpus`), the
brand block (`engine init`), any handle (`handles.md` rows are blank; the
X stream's `own` and `mentions` rules need the own X handle), the gitignored
`handles.private.md` (the gate blocks every item until it exists, which is
correct), the status-word rules of the gate and the announcement checker
(`gate_lint.STATUS_WORDS`, `CLEARED_HEDGES`; `announce_check.STATUS_FLAGS`,
`CLEARED_PHRASES`, `VOICE_FLAGS` ship empty, so `lint: status words` passes
everything until the brand writes them from its `status.md`), the secrets, the
LinkedIn and X logins for the sender,
and any loaded schedule: nothing is loaded by a clone, `engine enable
<job>` is a person's act.

## What the doctrine leaves open, and how the engine treats it

- **No owner for Alpha.** The desk records who decided (`by`), so the first
  cycle produces the name the doctrine lacks; `streams.md` records only
  whether an owner is confirmed, never who.
- **A paired stream has no narrator here.** `handles.md` may carry another
  stream's own channels for listening; the engine drafts nothing in its voice
  unless that stream is onboarded with its own memory and owner.
- **A listening loop with no response commitment.** Every finding carries a
  content or conversation opportunity or an explicit `none`, and the queue is
  the response.
- **Proof points that cannot be shown.** The licence field in `themes.md` is
  `held` for exactly this reason, and a held theme yields the standards
  argument only.
