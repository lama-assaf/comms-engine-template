# 1. Setup: a new machine, a new business

The engine is the `comms-engine` Claude Code plugin; a business runs it from
an **instance repository**: its `brand.json`, its memory, its content and its
records. This repository is both the plugin's home (and marketplace) and the
instance template, itself the first instance. Clone it, register the plugin
once, open Claude Code in it, and the agents, skills, commands, hooks and
plugin enablement are there. A new business is **one small file**, `brand.json` at the
root, and nobody has to open it: a guided setup asks the few questions and
writes it, and the Setup page of the dashboard edits the same file afterwards.
What a machine still needs by hand follows in order, and the pieces that are
deliberately **not** in git are at the end. The examples use the placeholder
brand `acme`; yours replaces it in step 1.2.

## 1.1 Clone and start

The guided setup does this section, and the secrets, plugins and schedules
below, in order, asking before each change:

```bash
npx github:lama-assaf/comms-engine-template setup   # Node 20+, a GitHub login that can read the repository
```

It is `cli/setup.mjs` at the root of this repository (the root `package.json`
names it; nothing to install, nothing published to npm). Without `setup` it
opens a menu for the brand's repository it runs in (or `--instance <dir>`, or
the last one used, remembered in `~/.config/comms-engine/setup.json`): set up,
`engine doctor`, `engine status`, and the console screen (`engine engine_tui`).
Its tests are `npm test`. By hand:

```bash
git clone <remote> ~/work/comms-engine-template && cd ~/work/comms-engine-template
claude plugin marketplace add ./ --scope local                   # this directory is the marketplace
claude plugin install comms-engine@comms-engine --scope local    # the engine, loaded in place
claude
```

For a business of its own, make its instance from that clone and work there:

```bash
plugins/comms-engine/bin/engine new-instance ~/work/acme-comms [--from <brand.json>]
cd ~/work/acme-comms && claude      # trust the folder: it offers the marketplace and the plugin
```

`new-instance` copies the instance files only (the memory as shapes,
`themes.json`, the `state/` and `streams/` readmes, `.gitignore`, `.mcp.json`),
names the GitHub marketplace (`params.instance.marketplace`) and enables
`comms-engine@comms-engine` in its `.claude/settings.json`, pins the engine that
wrote it in `brand.json` (`engine.version`, which `engine doctor` checks against
the loaded plugin), and runs `git init`. The first commit is yours.

Clone **outside** `~/Desktop`, `~/Documents` and `~/Downloads`. macOS folder
protection stops launchd from executing or reading a shell script in those
folders (the job exits 126 or 127 before its first line) and from opening a
log file there. The schedules work around the first with a python launcher
(`schedule/runjob.py`, 1.11) and the second by logging under
`~/Library/Logs/`, but a clone elsewhere needs neither grant.

Of `.claude/`, only `settings.json` is tracked; the rest comes from the plugin:

| from | what it gives |
|---|---|
| `.claude/settings.json` | `enabledPlugins` (`comms-engine@comms-engine`, and atelier, salon, motion for the roles), the deny list, MCP approval; in an instance also `extraKnownMarketplaces` |
| the plugin's `agents/` | `comms-engine:listener`, `:theme-writer`, `:gatekeeper`, `:distributor`, `:motion-designer`, `:storyteller` |
| the plugin's `commands/` | `/social-cycle`, `/listen-themes`, `/alpha-queue`, `/announce`, `/control`, `/engine`, `/motion`, `/story`, `/deck-read`, `/corpus-cycle`, `/corpus-sweep`, `/corpus-read`, `/corpus-analyse`, `/corpus-update` |
| the plugin's `skills/` | `theme-listening`, `theme-post`, `claim-gate`, `publish`, `inventory-refresh`, `x-post`, `linkedin-post`, `motion-post`, `story-deck`, `theme-words`, `engine-console`, `deck-reader` |
| the plugin's `hooks/hooks.json` | the three hooks (1.4) |
| the plugin's `bin/engine` | `engine <name>` on the Bash tool's PATH: every script and console command, run against this instance |
| `.mcp.json` | no server by default; no environment variable needed |

Edit the engine under `plugins/comms-engine/`; a plugin loaded from this
directory's marketplace picks the change up at the next session (or
`/reload-plugins`). `claude plugin validate plugins/comms-engine --strict`
checks it. `plugins/comms-engine/install.sh --check` reports what this machine
is missing: plugins, secrets, tools.

Per-machine state stays out of git: `.claude/settings.local.json` (permission
allowlists, MCP OAuth), `.claude/session-brief.json` (the session brief's
marker), third-party skills in `.agents/`.

## 1.2 The guided setup: `brand.json`

```bash
engine init                       # on a terminal: five questions, then brand.json
engine init --slug acme --name "Acme" \
    --narrator "an authority on its category" --x @acme --linkedin linkedin.com/company/acme   # the same, headless
engine init --from brand.json     # a clone set up from a setup file, no questions
```

`init` asks for the slug, the name, the narrator, the X handle and the
LinkedIn page; every one is a flag, and the last three may be left empty and
collected later. It writes `brand.json`, renders the three tables of
`.atelier/memory/streams.md` from it, renames the brand cells of `handles.md`
and prints the first commands. It never edits
`plugins/comms-engine/engine.json`, which stays as shipped defaults nobody
edits. It is idempotent and refuses a slug outside `[a-z][a-z0-9-]{1,23}`. A
checkout that kept its registry by hand and has no `brand.json` gets one
imported from its `streams.md`, cell for cell.

What the file holds, in about forty lines (`brand.example.json` is a
filled-in one, each key explained by an `_about` key beside it):

| key | what it is |
|---|---|
| `brand` | `slug` and `name`; `label_prefix`, `env_prefix` and `keychain_service` follow the slug unless named |
| `streams.<slug>` | one entry per stream, the brand's own first: `narrator`, `owner` (`confirmed` or `unset`, never a name), `channels` and their handles, `autopilot`, `review` (the default mode per kind of send), `posts_per_day`, `reactions_per_day`, `quiet_hours`, `blocked_topics`, `hold_for_review`, `pair_rules` |
| `drivers` | how sends and X reads are carried: `write` (`native` or `composio`), `x_read` and `x_own` (`twitterapi` or `composio`) |
| `jobs` | which scheduled jobs are on |
| `plugins.roles` | which plugin agent or skill plays which role; empty keeps the defaults of `engine.json` |

Never a secret and never a person's name: secrets stay in the keychain (1.6).

**The layers.** `config.py` merges four, the later outranking the earlier:

```
plugins/comms-engine/engine.json     shipped defaults: jobs, params, workflows, plugin roles; nobody edits it
  < brand.json                        this project: the brand, its streams, drivers, jobs on or off, roles
    < engine.local.json               this machine, gitignored: the corpus root, budgets, the timezone
      < <env_prefix><SECTION>_<KEY>   the environment, for one run
```

**Checked on load.** A wrong key does not fail silently:

```bash
engine validate   # an unknown key, a wrong type, a missing stream: the key and the fix, one line each
engine apply      # render the streams.md tables from brand.json
engine apply --check   # exit 1 when streams.md and brand.json disagree
```

`streams.md` is still what the agents and `memory.py` read, but its three
tables are rendered: `engine apply` is their one writer, and `doctor` fails
when the tables and `brand.json` disagree. A person changes the setup (by
`init`, by the Setup page, or by editing `brand.json` and running `apply`), on
a dated decision file, and never edits the tables. The prose of `streams.md`
around the tables is left alone.

**From the dashboard.** `/control` (or `scripts/control.py start`,
`127.0.0.1:4320`) has a **Setup** page over the same file: each stream's
narrator, owner state, channels, autopilot, default review modes, caps and
quiet hours, the drivers and which jobs are on. A change takes one
confirmation, is checked by the same `validate`, re-renders `streams.md` and
is recorded as a `setup` act with the role and the time. The **Autonomy** page
beside it holds the review switches (1.3).

The names derived from the brand:

| what | derived as | example |
|---|---|---|
| launchd label of a job | `<label_prefix>.<job name>` | `com.acme.social-engine` |
| environment override of a parameter | `<env_prefix><SECTION>_<KEY>` | `ACME_CYCLE_BUDGET_USD` |
| the repo marker launchd sets | `<env_prefix>REPO` | `ACME_REPO` |
| keychain service | `brand.keychain_service` | `acme-comms` |
| launchd stdout directory | `~/Library/Logs/<slug>-comms/` | `~/Library/Logs/acme-comms/` |
| the root stream of the memory | `brand.slug`, first row of `streams.md` | `acme` |
| the X stream's rule tags | `<slug>:mentions`, `<slug>:own`, ... | `acme:own` |

Readable at any time: `config.py brand`, `config.py labels`,
`config.py env-name cycle.budget_usd`, `config.py log-dir`, and
`config.py show` for the merged configuration.

Why JSON and not YAML: every script and test already reads JSON through
`config.py`, and YAML reads a bare `off`, `no` or `on` as true or false, which
are the words the switches use. What makes setup easy is how little a person
fills in and that mistakes are caught, not the file format.

## 1.3 What may go out without a person

A fresh clone sends nothing: the stream's `autopilot` is `nothing`, its owner
is `unset` and every review mode is `review`. Three things open it, each a
person's act:

1. **The owner is confirmed and the voice is written** (chapter 6). Until
   then the stream drafts nothing and sends nothing, by every path.
2. **`autopilot` is set to `by switch`**, once, at onboarding, on a dated
   decision file. `nothing` stays the hard off.
3. **A review mode is turned to `auto`** on the Autonomy page, per stream,
   channel and kind (`post`, `reply`, `comment`, `like`, `repost`, `quote`,
   and `hold`, the statistics, partner and certification class). One
   confirmation; a written reason is optional. Three presets set the rows at
   once: review everything, review posts only, fully automatic.

With a kind on `auto`, whatever passes the automatic checks goes out and
whatever fails stays in the queue; with it on `review`, it waits for a person.
The hard limits run in both modes and no switch turns them off: the stream,
the stealth denylist, cites that are current and bound to their sentence, pair
rules, the account, dedupe, caps and quiet hours. The same page has the
**pause** (one click stops every send of a stream, read by `channels.send()`
at each send) and the list of what was **sent without review**, each with a
**take down**.

Likes on X are the exception: X's rules require a like to be initiated by a
person, so a like on X stays one click on the Engagement page unless a dated
owner sign-off is recorded in `channels.reactions_signoff.<stream>`. The
finding and the proposal are in
`.atelier/memory/decisions/2026-11-13-reactions-platform-rules.md`.

## 1.4 Hooks

Three, the plugin's own (`hooks/hooks.json`, each run as
`python3 "${CLAUDE_PLUGIN_ROOT}/..."`), so every instance that enables the
plugin has them:

- **`SessionStart`** runs `scripts/session_brief.py`: the latest listening
  pass and the lessons, decisions and reviews new since the last session on
  this clone land in the first turn, with the console's count of stale or
  unloaded jobs.
- **`PreToolUse` on Bash** runs `hooks/guard_posting.py`: a raw platform
  write that bypasses `channels.send()` (`xurl post|reply|delete`, a write to
  the LinkedIn or X API, `composio execute` of a channel-toolkit slug that is
  not a listed read, a `composio proxy` other than a GET, `composio run`) is
  refused with the rule quoted. Engine scripts pass, because every send they
  make, a like and a take down included, goes through `channels.send()` and
  its checks.
- **`PreToolUse` on Skill** runs `hooks/guard_skills.py`: the paid
  `motion:generate` is refused until a cost sign-off is recorded
  (`motion.py generate-signoff`, read from `params.motion.generate_signoff`),
  and it refuses when the setting cannot be read.

Hooks run in headless `claude -p` runs too (never pass `--bare`).

## 1.5 Plugins

`.claude/settings.json` enables `atelier@atelier`, `salon@atelier` and
`motion@atelier`; enabling does not download, so once per machine, in this
folder (a project install made in another checkout does not count here):

```
claude plugin marketplace add <git url of the marketplace the plugins come from>
claude plugin install atelier@atelier --scope project
claude plugin install salon@atelier --scope project
claude plugin install motion@atelier --scope project
```

The template ships no marketplace URL (`plugins.marketplace` in `engine.json`
is empty): the plugins are published by their author, not by this repository.
Record the URL once with `config.py set plugins.marketplace <git url>`;
`engine plugins` and `install.sh --check` then print it in the install line.

atelier carries the brand and copy skills and the `copywriter`,
`brand-voice-keeper` and `narrative-architect` agents; salon the social ones
(`campaign-strategist`, `engagement-manager`, `community-manager`,
`social-listening`, `trend-to-content`, `hook-writing`, `post-audit`,
`campaign-retro`, `launch-window`); motion the films made from the brand kit
(`motion:video`, `motion:render`, `motion:brand-kit`; Node 22 or later).

Which plugin agent or skill plays which role is data, not prose: the
`plugins.roles` list (defaults in `engine.json`, overridden per brand in
`brand.json`) names for each role the agent or skill, its pinned version, the
brief under `plugins/comms-engine/briefs/` that carries this
repository's rules (a plugin agent knows none of them), and a fallback.
`engine doctor` fails when an installed plugin is not the pinned version or
a role has no brief. The workflows call the roles: `theme-writer` preloads
`salon:trend-to-content`, `salon:hook-writing`, `salon:post-audit`,
`salon:x-thread` and `atelier:ab-test-design`; the draft workflow may call
`atelier:copywriter` and `atelier:narrative-architect` for the candidates; the
voice workflow runs `atelier:brand-voice-keeper` before the gate
(`cycle.voice_pass` false skips it); the gate's second reviewer is
`salon:adversarial-refinement`; `salon:campaign-strategist` and
`salon:launch-window` serve the Friday slots, `salon:engagement-manager`,
`salon:comment-strategy` and `salon:reply-playbook` the engagement drafts,
`salon:community-manager` a stream that lists Telegram or Discord,
`salon:campaign-retro` the monthly readout, `atelier:release-narrator` the
staging of `/announce`, and `atelier:motion-direction` the motion-designer's
brief. `/motion <id> --film` drives `motion:video` and `motion.py film <id>`
holds the film's words to the gated post; the first film's brand kit is
written from the brand genome by `motion.py kit --write`. `engine plugins`
says which load here, read from `claude plugin list --json`: a plugin that
failed to load, or one installed for another checkout, is reported as not
installed.

What installing them brings with it, and what holds it:

- **Look-alikes.** salon ships agents and skills that share a job or a name
  with the project's own (`theme-desk`, `theme-listener`, `claim-gate`,
  `theme-post`, `theme-listening`, `linkedin-post`, `social-listening`,
  `publisher-gates`, `website-publish`, `engine-dashboard`,
  `telegram-broadcast`, `discord-announcement`). The project's are the ones
  tied to the claims register and the scripts, so `.claude/settings.json`
  denies the salon ones, with `motion:post` (Instagram is not a channel
  `channels.send()` knows; the posting hook also refuses
  `composio execute INSTAGRAM_*`). `motion:generate` (paid calls) is held by
  the Skill hook of 1.4 until its cost sign-off is recorded.
- **The copy check.** atelier answers every Write and Edit of prose with a note
  when it finds a banned tone word, flat rhythm or an em-dash. It never blocks
  (do not set `ATELIER_HOOK_STRICT`). The writer acts on it for its own draft;
  the gatekeeper and the motion-designer are told to leave a lifted line, a
  cite and a person's words as they are. It also appends the path and size of
  each write to a log, by default under `~/.claude/atelier/logs/`:
  `engine plugins --prepare`, once per machine, keeps it with the engine's
  own logs (`~/Library/Logs/<slug>-comms/atelier`) by writing `ATELIER_LOG_DIR`
  into the gitignored `.claude/settings.local.json`; `engine plugins` says
  where it goes.
- **Session hooks.** atelier injects the root `.atelier/memory/instincts.md`
  once when a session starts (salon defers to it), whatever the stream, which
  is why that file is kept short; a workflow run for another stream says so in
  its prompt, so the root's lines are not read as that stream's. motion's hook
  installs its npm packages when Claude Code's own install was cut short; the
  scheduled runs never meet it, because the runner and
  `corpus_cycle_daily.sh` switch off `plugins.interactive_only` for the run
  (`engine plugins --headless-settings`, passed as `--settings`).
- **Cost.** Three candidates and two reviewers per draft are about five times
  the model calls of one draft and one review. Each workflow carries its own
  budget, the chain stays inside `cycle.budget_usd`, and `engine status`
  shows what the last runs cost.

## 1.6 Claude Code login

Plain `claude` uses the default configuration directory (`~/.claude`) and its
login. If a machine wants a separate login for this work, export
`CLAUDE_CONFIG_DIR` in the shell before `claude`, and run `engine install`
(or `engine enable`) from a shell that has it set, so the scheduled runs use
the same login. Keep `ANTHROPIC_API_KEY` out of the environment for the
scheduled runs: the runner drops it so the subscription login is used. A
hosted Mac signs the scheduled runs in with a subscription token instead
(`claude setup-token`, kept as `CLAUDE_CODE_OAUTH_TOKEN` through `secrets.py`
and given to each `claude -p` alone): `docs/07-hosting.md`.

## 1.7 Secrets

`plugins/comms-engine/scripts/secrets.py` is the only resolver: the process
environment first, then the macOS login keychain, service
`brand.keychain_service` (`acme-comms`), account = the token's name. Seed once
per machine:

```bash
engine secrets                        # present or missing, by name, never a value
engine secrets --set TWITTERAPI_IO_API_KEY   # prompts, hidden
engine secrets --set APIFY_TOKEN             # only for listen.py --linkedin
```

The required and optional names are `params.secrets` in `engine.json`. For the
sender (`autopilot.py`) to post, the LinkedIn page credentials (`LINKEDIN_*`)
and an X developer app are needed too; `linkedin_api.py status` reports
`authorized: true` once they are in, and
`npx -y @xdevplatform/xurl auth oauth2 --app <slug>` logs the X app in once,
in a browser. A set of values already in a `.env` file moves into the keychain
with `scripts/import_env_secrets.py <file> --dry-run`, then without the flag.

Every item carries the `-T /usr/bin/security` ACL so an unattended read never
raises a GUI prompt. `linkedin_api.py` refreshes the access token and writes it
back to the keychain. No token lives in a file. A second stream's secrets are
scoped (`<slug>/<NAME>` in the keychain, `<SLUG>_<NAME>` in the environment);
see `docs/06-streams.md`.

## 1.8 Dependencies

| need | install | used by |
|---|---|---|
| Python 3 with the packages in `requirements.txt` | `python3 -m pip install -r requirements.txt` | engine scripts, deck reader |
| `pdftoppm` | `brew install poppler` | deck reader renders (required) |
| `soffice` | `brew install --cask libreoffice` | rendering `.pptx` sources |
| `tesseract` | `brew install tesseract` | image-only slides |
| Node 20+ and npm | `brew install node` | the desk; `npx xurl` for X |
| Docker | Docker Desktop | optional: `research-store/docker-compose.yml` |
| the strategy corpus | a folder of decks and prose, local or a synced drive; set per machine with `engine setup corpus --root <path>` | `/corpus-*`; the sweep exits cleanly when it is not mounted |

## 1.9 The desk

The desk is an optional module of the instance, under `Tooling/desk/`:

```bash
cd Tooling/desk && npm install
engine desk_sync --push      # fill state/desk.db from the notes and state/
npm run dev                  # http://localhost:4310
```

The desk is where a person approves, holds, rejects, edits and reviews. Its
database is a derived index plus a decision store; `desk_sync.py --pull`
carries the decisions back out and is the first workflow of every weekday
chain (`pull`). The control page (`/control`) carries the approve and schedule
acts too, and is the only place for the switches, the pause, take down and
the setup (1.2 and 1.3). Rules and layout:
`Tooling/desk/README.md`.

## 1.10 Verify the install

```bash
engine doctor        # all of the below, one ok/FAIL line each
engine validate      # brand.json: the key and the fix per problem
python3 -m unittest discover plugins/comms-engine/tests
plugins/comms-engine/install.sh --check
engine memory --list        # the stream registry
engine state_check
engine gate_lint
engine session_brief --dry-run
engine autopilot run --dry  # the sender against the calendar, sends nothing
engine reactions send-due   # the reactions due, dry: sends nothing
engine workflow chain weekday --dry   # every command and model call of a cycle, none made
```

The full list is in `CLAUDE.md`. `doctor` reports a missing secret as a
result, not a failure, so it is green on a machine with no keys yet; it does
fail on a `brand.json` that does not validate, on `streams.md` tables out of
date with it, and on a plugin that is not the pinned version.

## 1.11 Schedules

The `jobs` list of `plugins/comms-engine/engine.json` describes every
scheduled job and `params` carries each job's parameters; `jobs` in
`brand.json` says which of them are on for this project.
`engine install` (`schedule/install.sh`) renders them into launchd plists for
this instance (no path in the repo names a machine) and loads them for the
logged-in user, after `engine shim --install` has written
`~/.local/bin/comms-engine`, the one path every plist runs. The
console (chapter 5) wraps the day-to-day forms: `engine status`,
`enable <job>`, `disable <job>`, `logs <job>`.

```bash
engine install --dry-run        # render, load nothing
engine install                  # load every job that is on
engine install --status         # loaded or not, last run, stale or ok
engine install --uninstall      # boot out every job of this brand; plists kept
engine enable cycle    # install.sh --only com.acme.social-engine, and says what it loaded
engine disable cycle   # launchctl bootout; the plist stays
```

| job | when (local) | what |
|---|---|---|
| `com.acme.corpus-cycle` | weekdays 06:30 | corpus memory: sweep; headless `/corpus-cycle --apply --max 8` only when something changed |
| `com.acme.social-engine` | weekdays 07:15 | `cycle.sh`: the `weekday` chain of workflows, run by `scripts/workflow.py` |
| `com.acme.autopilot` | weekdays 09:05, 13:35 | `autopilot.py run`: calendar snapshot, the engine's approvals where the mode is `auto`, the due Ready rows within guardrails, link replies |
| `com.acme.engagement` | weekdays 15:30 | `cycle.sh --only engage`: the `engagement` chain (reply and comment drafts, community drafts, the reactions due) |
| `com.acme.score` | daily 22:00 | `x_metrics.py`, `score.py --demand`, `metrics.py`, `livetests.py close` |
| `com.acme.claims-check` | daily 22:15 | `claims_check.py`, `state_check.py`, `build_dashboard.py` |
| `com.acme.x-stream` | always, off by default | twitterapi.io stream; billed per matched post |
| `com.acme.x-poll`, `com.acme.inbound` | weekday working hours, off by default | the standing X monitors and our own accounts' inbound, billed per result |
| `com.acme.control` | always, off by default | the control page kept up on a hosted Mac, for Tailscale Serve (`docs/07-hosting.md`) |
| `com.acme.backup` | daily 23:40, off by default | `backup.py`: the record committed, pulled with rebase and pushed when `backup.push` is true |
| `com.acme.nosleep` | always | `caffeinate`, the Mac stays awake |

Every job but caffeinate runs as `~/.local/bin/comms-engine runjob <label>`,
with `COMMS_ENGINE_INSTANCE` set to the instance. The shim finds the installed
engine at each start (the plugin's root moves on every update; `comms-engine
--where` says which it would use), and `runjob.py` reads the job's program
from `engine.json` and hands it to zsh, so launchd never has to open a script
itself. `engine runjob --show <label>` prints the command without running it;
`engine run <job> --live` runs a job now, exactly as the schedule would,
with the command printed first; `engine run <job>` without `--live` runs
the job's dry form instead.

**Code runs the cycle.** The weekday job is not one long prompt. The runner
(`scripts/workflow.py`) runs the chain named in `params.chains.weekday`, one
workflow after another (`pull`, `listen`, `plan`, `draft`, `voice`, `gate`,
`distribute`, `push`, and on their days `editor`, `slots`, `readout`,
`motion`, `story`). A workflow's script steps are subprocesses; each model
step is one `claude -p` call with one agent, its own `--max-budget-usd`, a
narrow `--allowedTools` list, `--permission-prompts none` (a call outside the
list is denied at once instead of waiting for a person who is not there) and
a JSON reply that code checks against a schema before anything is written.
Every run leaves a record under `state/runs/<workflow>/`, a chain stops at the
first workflow that fails, and a failure reads `gate failed`, not an exit
code. `workflow.py list`, `status` and `chain weekday --dry` show the plan
without a call. `/social-cycle` in a session calls the same runner.

The parameters a job reads (drafts per cycle, budgets, the corpus root,
`--max`, `--apply`, grace days, the engagement window, the timezone the
guardrails are judged in) live in `engine.json` under `params` and are read
through `scripts/config.py`; a per-machine value goes to the gitignored
`engine.local.json` (`engine setup <job>` or `config.py set`), and an
environment variable `<env_prefix><SECTION>_<KEY>` outranks every file.

The corpus run (`corpus_cycle_daily.sh`) is still one plain `claude -p` with
`--permission-mode acceptEdits`, `--permission-prompts none`, an explicit
`--allowedTools` list and `corpus.budget_usd` as its cap. Never `--bare`
anywhere. Logs: each job's own stdout in
`~/Library/Logs/<slug>-comms/<label>.log`; the scripts' state logs in
`state/` (`schedule.log`, `corpus-cycle.log`,
`autopilot.log`).

## 1.12 Not in git, set up by hand

- `.atelier/memory/handles.private.md`, from `handles.private.example.md`:
  the stealth denylist. The gate **blocks every item** when it is missing, so a
  clone without it drafts nothing publishable.
- `Docs/Research/` (gitignored): the research briefs the corpus cycle writes
  and `_corpus/manifest.json`, the sweep's state. The first `/corpus-sweep`
  on a machine sees every source as unread.
- `plugins/comms-engine/dashboard/index.html`: the built dashboard,
  gitignored; `build_dashboard.py` writes it from `template.html`. Built on a
  fresh clone it shows these setup steps in order, with the next command to
  run (`engine setup_state` prints the same).
- `engine.local.json`: the per-machine corpus root,
  budgets, the site URLs (`params.site`), the timezone. `brand.json` is
  tracked: it is the project's setup, not the machine's.
- `state/desk.db` (decisions not yet pulled),
  `state/raw/`, `state/listening-*.json`, `state/x-stream/`, the logs.
- the keychain items, the twitterapi.io account, the
  X developer app, the LinkedIn app and its page admin.

## 1.13 The console

One CLI over the scheduled jobs, `plugins/comms-engine/scripts/engine.py`, with a
curses screen (`engine_tui.py`, standard library, no dependency) and a Claude
Code command (`/engine`, skill `engine-console`) as its two faces. It is the
only thing that calls `launchctl`, `install.sh`, `runjob.py` and the dry runs,
and it prints the exact command before every act. Chapter 5 has the detail.

On a new machine, in this order, after 1.2, 1.5 and 1.7:

```bash
engine doctor         # every check in CLAUDE.md, plus the setup file, config and secrets; green before anything is loaded
engine setup corpus   # the corpus root for this machine, --max, --apply; ends with the sweep's to-do
engine setup cycle    # drafts per run, budget, listening, weekday flags; ends with the dry run
engine enable corpus  # then cycle, autopilot, engagement, score, claims-check, nosleep: a load is a person's act
engine engine_tui            # the screen: what is loaded, what ran, what is stale; r runs dry, l shows the log
```

`setup` asks on a terminal only; headless, every question is a `--<key>` flag
(`setup cycle --drafts 4 --budget-usd 15`) and nothing waits. It writes
`engine.local.json`, never `engine.json` or `brand.json`, and never loads a
job. `status` exits 1 when a job is stale or not loaded; `run <job>` is dry
unless `--live`, and `--live` is refused for the autopilot, the X stream and
caffeinate. `secrets` shows present or missing by name, never a value.
