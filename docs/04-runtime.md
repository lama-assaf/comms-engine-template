# 4. The engine: what exists and what runs

One runtime: the `comms-engine` plugin (`plugins/comms-engine/`) on Claude
Code, run inside a brand's instance repository and scheduled by launchd.
Nothing else runs. The engine's code is the plugin's; the instance holds what
the brand owns: `brand.json`, `.atelier/memory/`, `Content/`, `state/`,
`streams/`, `themes.json` and its gitignored `engine.local.json`.
`scripts/paths.py` is the one place that finds each: the instance from
`COMMS_ENGINE_INSTANCE`, then `CLAUDE_PROJECT_DIR`, then the nearest parent of
the working directory holding `brand.json`, then the development layout; the
engine from its own location.

## 4.1 The loop

```
listen ──► assess ──► plan ──► draft ──► gate ──► [ a person decides, or the review mode does ] ──► distribute ──► send ──► score
listen.py  listener   plan_     theme-   gate_lint    control page, desk                              distributor    autopilot   score.py
+ sweep    agent      queries   writer   + 2 reviewers  switches.py (review | auto)                   publish.py     reactions   metrics.py
                      .py       agent    + review.py                                                  → note         .py         livetests.py
```

Code runs the loop and the model does bounded jobs inside it: each box is a
workflow that `scripts/workflow.py` runs (4.3), not a step of one long prompt.

Every box left of the decision is proposal. Approval writes the vault note
and schedules its X and LinkedIn posts for their day. Who approves is the
stream's setting: with `autopilot` at `nothing` (the default) nothing leaves
and a person posts from staged drafts; with `by switch`, each kind of send
follows its review mode for that stream and channel. On `review` a person
decides; on `auto` the engine records the approval itself (`by: engine`, with
the id of the switch act that allowed it) for a post whose verdict is pass,
and whatever fails stays in the queue. Marking an article live on the site
stays a person's act, except where a dated decision lets `publish.py` create
a gated Blog row as Published. Set `autopilot` back to `nothing`, or press
pause, and every send stops with the rule quoted.

One function answers "may this go without a person":
`switches.mode(stream, channel, kind)`, with the kinds `post`, `reply`,
`comment`, `like`, `repost`, `quote` and `hold`. `channels.send()`, the
engine's approval (`autopilot.py approve`), the reactions sender and the
dashboard all ask it. A switch turned to `auto`, a pause, a take down and a
change to the setup are acts in `acts.py` with the role and the time.

The vault note is the record: `Content/Calendar/<title>.md`, written only by
`scripts/repo.py` at draft time (`status: Idea`) and rewritten on approval
(`status: Ready`); `state/queue.json` and the desk database are derived
indexes, rebuilt from the notes. Conflicts between desk and vault skip and
report, never clobber. Every send goes through
`channels.send()` and its checks, whoever calls it; the `PreToolUse` hook
refuses a raw platform write that would bypass it.

## 4.2 Where things are

| piece | path |
|---|---|
| the plugin | `plugins/comms-engine/`: `.claude-plugin/plugin.json` (name, version), `agents/`, `skills/`, `commands/`, `hooks/hooks.json` (under `${CLAUDE_PLUGIN_ROOT}`), `bin/engine`, `briefs/`; listed by `.claude-plugin/marketplace.json` at the root. An instance's `.claude/settings.json` enables `comms-engine@comms-engine`, and `brand.json` `engine.version` pins it |
| the one command | `bin/engine <name>`: a console command of `scripts/engine.py` (`doctor`, `install`, `run`, `host-check`, ...) or `scripts/<name>.py`, run with the instance as working directory; on the Bash tool's PATH while the plugin is enabled, and on every `claude -p` the runner starts |
| a new instance | `engine new-instance <dir> [--from <brand.json>]` (`scripts/instance.py`): the instance files from the template, the marketplace named, the engine pinned, `git init` |
| scripts | `plugins/comms-engine/scripts/`; each opens with a docstring saying what it is, why, and its command lines |
| the cycle entry points | `scripts/workflow.py` (`list`, `run <workflow>`, `chain <chain>`, `status`; `--dry`), called by `/social-cycle` (interactive), `scripts/cycle.sh` (headless, for launchd) and `engine run <workflow or chain>` |
| workflows and chains | `params.workflows` and `params.chains` in `engine.json`; the model briefs under `briefs/workflows/`, the shared rules in `briefs/workflows/_rules.md`; run records under `state/runs/<workflow>/` |
| the sender | `scripts/autopilot.py` (`snapshot`, `approve`, `post`, `links`, `commit`, `status`; `--dry`), `scripts/linkedin_api.py`; it reads the notes and the lifecycle, so it needs no calendar service |
| the one sender underneath | `scripts/channels.py` `send()`: kinds `post`, `reply`, `comment`, `like`, `repost`, `quote`, `delete`; native and Composio drivers; media staged and re-hashed at send |
| the review switch | `scripts/switches.py` (`mode`, `set_mode`, `preset`, `set_pause`, `policy`), state in `state/switches.json`, changed only by acts |
| the reviewers' verdict | `scripts/review.py` (`schema`, `apply --first A --second B`, `check <id>`); `scripts/gate_eval.py` and `tests/fixtures/gate_cases/` (the labelled set; `engine eval gate`) |
| reactions | `scripts/reactions.py` (`plan`, `send-due` dry unless `--live`, `status`), `state/reactions.json` |
| rules and formats as data | `.atelier/memory/gate-rules.json`, `.atelier/memory/formats.json`, read through `memory.py` |
| plugin roles | `params.plugins.roles` (overridable in `brand.json`), `scripts/roles.py`, the briefs under `briefs/` |
| schedules | `engine.json` `jobs`, `schedule/render.py`, `schedule/install.sh` (`engine install`); every plist runs `~/.local/bin/comms-engine runjob <label>`, the shim `engine shim --install` copies from `schedule/comms_engine_shim.py`, which finds the installed engine's root at each start and runs `schedule/runjob.py`; `scripts/jobs_status.py` |
| the hosted Mac | `docs/07-hosting.md`; `engine host-check`; the door in `scripts/control.py` (`door`: the Tailscale Serve name and a mapped login); `scripts/backup.py` and the `backup` job |
| the console | `scripts/engine.py`, `scripts/engine_tui.py`, the `/engine` command and `engine-console` skill; chapter 5 is the contract |
| configuration | `engine.json` (tracked, shipped defaults nobody edits: `jobs`, `params`, `streams`; no machine named, `__HOME__`, `__REPO__` (the instance) and `__ENGINE__` (the engine's root) stand in), `brand.json` at the root (tracked, the project's one setup file; `scripts/brandfile.py` writes it and renders `streams.md` from it), `engine.local.json` (gitignored, per machine), `scripts/config.py` (`cfg`, `get`, `set`, `show`, `validate`, `brand`, `labels`); `<env_prefix><SECTION>_<KEY>` in the environment outranks every file |
| stream onboarding | `scripts/onboard.py` over `brand.json`, the rendered `streams.md` and `.atelier/memory/streams/<slug>/`; `.atelier/memory/templates/voice.md` is the shape it writes from |
| tests | `plugins/comms-engine/tests/`, every one on fixtures under `tests/fixtures/`; `python3 -m unittest discover plugins/comms-engine/tests` |
| state | `state/`, empty in the template but for its READMEs; the first cycle creates `signals.json`, `queue.json`, `runs.json`, `decisions.json`, `edits.json`, `predictions.json`, `engagement.json`, `metrics.json`, `planning.json`, `claims-review.json`, `calendar-snapshot.json`, `send-ledger.json`, `publish-log.json`; `desk.db`, `raw/`, `listening-*.json`, `x-stream/` and the logs are gitignored |
| per-stream search terms | `themes.json` (the root stream), `streams/<slug>/themes.json` |
| the desk | `Tooling/desk/` in the instance, optional (Next.js over Drizzle and SQLite), port 4310 |
| the read-only dashboard | `state/dashboard.html` built by `build_dashboard.py` from the engine's `dashboard/template.html` (gitignored: it inlines the brand's state): the posts, then what is live: the replies drafted for it and what was heard; each card shows the content and the reasons sit behind Read more; the setup steps until they are walked (`setup_state.py`); no runs, jobs or engine words on the page; a local page opened in a browser, never published |
| research store | `plugins/comms-engine/research-store/` (files mode by default; a graph store is optional) |
| the story (landing page) | the `story` workflow, or `/story`: `scripts/story.py facts` gathers the run's facts, the `storyteller` agent (`story-deck` skill) writes a short deck in plain words, `story.py check` refuses an invented number or a denylist term, `story.py publish` writes `state/story/latest.json`; the control page opens on it, in the brand genome's flat colours, and a person's answers to its questions (`state/story/questions.json`) are read by the next story |
| the theme words | the `storyteller` (`theme-words` skill) whenever `scripts/theme_words.py status` names a theme whose plain words are missing or out of date: what we may say about it now, what we never say, why, what would move it up; `theme_words.py publish` checks them (no file names or codes, the denylist, status words) into `state/theme-words/latest.json`, which the Themes drawer shows before the exact rule |
| the control page | `/control` → `scripts/control.py start`: the web app (`ui/`, React; its build `ui/dist` is committed, so no Node is needed to run it) on `127.0.0.1:4320`, every view from `scripts/views.py`, in the genome's palette (`palette`, `shape.ui_radius`); the first page stays at `/classic` until the app matches it. It writes a theme's search terms (`themes.json`), a new theme added as held (`themes.md` and `themes.json`), `state/watchlist.json` (the `@watched` pass of `listen.py`), and a person's acts: approve, schedule, the review switches and the pause (Autonomy page, `/api/switch`, `/api/pause`), take down (`/api/takedown`), a like or repost by one click (Engagement page, `/api/react`), and the setup file (Setup page, `/api/setup`) |
| motion cards | in the cycle, the `motion` workflow: `motion.py pending --render`, then the `motion-designer` per blog post owed a card (at most `params.cycle.motion_per_cycle`, default 3; `params.cycle.motion` false turns it off); on request, `/motion <id>` → the `motion-designer` agent and the `motion-post` skill → `scripts/motion.py` (`brief`, `check`, `render`); the storyboard is `Content/Motion/<id>/storyboard.json`, the MP4, GIF and poster beside it are gitignored; every line word for word from the gated post. A card or a film becomes media on a post only through `channels.send()`: the file's hash is recorded in the approval and the file is hashed again at send, so a file that changed is refused. The paid `motion:generate` runs only behind a recorded cost sign-off (`motion.py generate-signoff`; the Skill hook refuses without it) |
| posting by a person | `x-post` and `linkedin-post` skills stage browser drafts and record the permalink on the post's note |
| corpus memory | `plugins/comms-engine/skills/deck-reader/` (skill, `/corpus-*` commands, `scripts/corpus_cycle_daily.sh`) |
| the site feed | `views.published_posts`: `GET /api/published` on the control page, `engine export-published <file>` |

Each store has one writer: `repo.py` the notes, `desk_sync.py --pull` the
decisions and `reviews.md`, `autopilot.py snapshot` the calendar digest,
`/corpus-update --apply` the memory, `runlog.py` the run log. A step that
needs another store's content reads it; it never writes it. The scripts'
docstrings say which files each one reads and writes; read them before
changing anything.

## 4.3 What runs

`engine jobs_status` prints the table live;
`engine status` adds the secrets, the plugins and the last cycle, and exits
1 when a job is stale or not loaded.

| job | when (local) | what it does |
|---|---|---|
| `com.<slug>.corpus-cycle` | weekdays 06:30 | `corpus_cycle_daily.sh`: sweep the corpus root; only when something changed, a headless `/corpus-cycle --apply --max 8` under `corpus.budget_usd` |
| `com.<slug>.social-engine` | weekdays 07:15 | `cycle.sh`: the `weekday` chain: `pull`, `listen`, `plan`, `draft`, `voice`, `gate`, `distribute`, `push`, then `editor` on Monday, `slots` on Friday, `readout` on the first weekday of the month, `motion` and `story` |
| `com.<slug>.autopilot` | weekdays 09:05, 13:35 | `autopilot.py run`: calendar snapshot into `state/` and `calendar.md`, then the engine's approvals where the post mode is `auto`, then the Ready rows due today within the guardrails, then link replies |
| `com.<slug>.engagement` | weekdays 15:30 | `cycle.sh --only engage`: the `engagement` chain: `engage` (comment and reply drafts, outcomes due at `engagement.window_days`), `community` (drafts for a stream that lists Telegram or Discord), `react` (`reactions.py plan`, then `send-due`, dry until `reactions.live` is set) |
| `com.<slug>.score` | daily 22:00 | `x_metrics.py`, `score.py --demand`, `metrics.py`, `livetests.py close` |
| `com.<slug>.claims-check` | daily 22:15 | `claims_check.py` (supersession and decay), `state_check.py` (every record names its stream), `build_dashboard.py` |
| `com.<slug>.x-stream` | always, optional | the twitterapi.io WebSocket on the `<slug>:*` rules; billed per matched post |
| `com.<slug>.nosleep` | always | `caffeinate` |

**A workflow** is a named unit that code runs: script steps as subprocesses
and at most a few model steps. Each model step is one plain `claude -p` with
one agent, its own `--max-budget-usd`, a narrow `--allowedTools` list,
`--permission-prompts none` (a call outside the list is denied at once
instead of waiting for a person who is not there), no `acceptEdits`, and
`--output-format json` with a schema: code checks the reply before it
believes it, and where something must be written, the model returns and code
writes. Each run writes `state/runs/<workflow>/<UTC stamp>.json` (result
`ok`, `nothing`, `needs-person` or `failed`, counts, cost, error), a chain
stops at the first workflow that fails and stays inside `cycle.budget_usd`,
and `workflow.py status` (also in `engine status`) shows each workflow's
last run, what waits for a person and the day's spend. A failure reads
`gate failed`, not an exit code.

The corpus run (`corpus_cycle_daily.sh`) is still one `claude -p` with
`--permission-mode acceptEdits`, an explicit `--allowedTools` and
`corpus.budget_usd`. Never `--bare` anywhere: a bare run skips hooks, skills,
commands, plugins, `CLAUDE.md` and the keychain login. Both shell scripts
export `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0`, because a headless run
otherwise stops its background subagents ten minutes after the orchestrator's
last turn, and the listener and the deck reader take longer.

### X reads: two classes, one price hold each

Listening and the standing monitors read through `channels.x_read.<slug>`
(`listen.x_price_signoff`); our own accounts, that is own-post numbers and
inbound mentions and replies, read through `channels.x_own.<slug>`
(`listen.x_own_price_signoff`). Both default to `twitterapi`. `composio` takes
effect for a class only once that class's sign-off is recorded; the other
class is unaffected. `engine doctor` shows both drivers and which one is held.

## 4.4 The sender

`scripts/autopilot.py` keeps these rules: the ledger (`state/send-ledger.json`)
is written before a send and a text is never sent twice; a row is looked up
by its own id and by the hash of its text; a failed send is recorded and the
next row still goes; a post past `autopilot.grace_days` stays Ready and is
logged as stale; a row with a link in the body or editorial voice is held;
another stream's rows are never touched. Every send goes through
`channels.send()`, whose checks run in one order (`channels.CHECK_ORDER`):
the stream's pause, the kind, the driver, the account, dedupe, the target of
a reaction, the cites, the gate, the stealth list, the hold class, the pair
rules, the guardrails (quiet hours and caps, `guardrails.check`, judged in
`params.autopilot.timezone`), the rule of the kind with its review mode, and
last the media hash. Each send and each refusal is recorded with the rule
quoted. `autopilot.py status` shows whether the brand may send on each
channel right now; `autopilot.py run --dry` reads the whole calendar and
sends nothing.

`autopilot.py approve` is the engine's approval. It acts only where the
stream's mode for `post` on that channel is `auto`, the gate verdict is
exactly pass, and `review.py`'s stamp is current for the text as it stands;
it records a `decision` act with `by: engine` and the switch act that allowed
it, then schedules through the same applier a person's approval uses. A post
a person said no to is never approved by the engine, and an engine-approved
post is refused at send if the mode has since gone back to `review`.

With nobody reviewing, undo is one click: the `delete` kind of
`channels.send()` takes a post, reply or comment down on a person's
`takedown` act, and it works while the stream is paused.

Whether anything goes out automatically is therefore one setting of the
stream and its switches, not a build. Leave `autopilot` at `nothing` and the
sender still takes the snapshot, refuses every post with the rule quoted, and
a person posts from the drafts the `x-post` and `linkedin-post` skills stage.

### Reactions

`reactions.py plan` ranks candidates from `signals.json`, the watchlist pass
and `inbound.py` by tier and theme into `state/reactions.json` (post id, tier
and theme, never a handle). `reactions.py send-due` is dry by default; with
`--live` it sends through `channels.send()`, a few per run
(`reactions.per_run`), spaced out (`reactions.spacing_seconds`). The gate for
a like or a repost is in 2.7 of the method chapter. A like on X is not sent
by the engine without the owner's dated sign-off
(`channels.reactions_signoff.<stream>`); it waits on the Engagement page as
one click. `engage.py record` takes the new shapes, so the 72-hour ledger
shows which reactions earned a reply or a follow.

## 4.5 Hooks

Built: `SessionStart` (the brief), `PreToolUse` on Bash (the posting guard;
tests in `tests/test_guard_posting.py`, including the case that a script
writing documentation about the sender is not a send, and that the like,
repost and delete slugs are refused outside `channels.send()`), and
`PreToolUse` on Skill (`guard_skills.py`: `motion:generate` only behind its
recorded cost sign-off, refused when the setting cannot be read).

Considered and not built: a guard on `Write`/`Edit` under `Content/Calendar/`,
because the distributor and `repo.py` legitimately rewrite a note; a
`Stop` hook checking `runs.json` gained an entry per step, because it would
fire on every interactive turn too. Both are a few lines in
`hooks/hooks.json` if wanted later.

## 4.6 Which native mechanism carries what

| mechanism | used for | why |
|---|---|---|
| **launchd + `claude -p`** (`engine.json` jobs, `engine install`) | every scheduled job | the jobs need the vault, `state/`, the desk database, `handles.private.md` and the corpus, all on this Mac |
| **hooks** (the plugin's `hooks/hooks.json`) | the session brief; the posting guard; the paid-skill guard | the rules that must hold in every session of every instance, headless or not |
| **the comms-engine plugin** (agents, skills, commands, `bin/`) | the loop's steps and the `engine` command | one versioned engine for every instance; enabled by the instance's tracked settings, pinned by its `brand.json` |
| **plugins** (atelier, salon, motion) | the generic brand, social and motion skills, each bound to a role with a pinned version and a brief (`params.plugins.roles`) | enabled in the tracked settings, installed per machine; `doctor` fails on a version that is not the pinned one |
| **cloud scheduled tasks** | not used | a fresh clone in a VM has no Mac files; the gate blocks without the gitignored denylist |
