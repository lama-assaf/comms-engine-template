# CLAUDE.md

This file provides guidance to Claude Code when working in this repository.

## What this repository is

Two things in one repository. The **engine**: the `comms-engine` Claude Code
plugin under `plugins/comms-engine/` (versioned in its
`.claude-plugin/plugin.json`; this repository is its marketplace,
`.claude-plugin/marketplace.json`). It listens to a business's themes, drafts
theme posts against a memory of what the business may claim, gates every draft,
puts the decision in front of a person, distributes what was approved and
learns from what was published; the corpus reader that feeds memory is its
`skills/deck-reader/`. And the **instance template**: the root, which keeps only
what a brand owns (`brand.json`, `.atelier/memory/`, `Content/`, `state/`,
`streams/`, `themes.json`) and is itself the first instance. Each brand runs its
own instance repository, written by `engine new-instance <dir>`, which pins the
engine in `brand.json` (`engine.version`). `README.md` is the first hour,
`docs/` the chapters; `docs/07-hosting.md` runs an instance on an office Mac.

Every script is called as `engine <name>`: `bin/engine` is on the Bash tool's
PATH while the plugin is enabled, finds the instance (`scripts/paths.py`:
`COMMS_ENGINE_INSTANCE`, then `CLAUDE_PROJECT_DIR`, then the nearest parent
holding `brand.json`) and runs `scripts/<name>.py` there; `engine doctor` and
the other console commands are `scripts/engine.py`'s. In a checkout without the
plugin installed, `plugins/comms-engine/bin/engine <name>` is the same command.

## The brand block

The business is named once, in `brand` of `brand.json` at the root (`slug`,
`name`; `label_prefix`, `env_prefix` and `keychain_service` follow the slug
unless named), and nothing else in code spells a brand. `brand.json` is the
project's one setup file (the brand, each stream, the drivers, which jobs are
on, the plugin roles); `plugins/comms-engine/engine.json` is shipped defaults
nobody edits, and `config.py` merges `engine.json`, `brand.json`,
`engine.local.json`, then the environment. Launchd labels are `<label_prefix>.<job name>`,
environment overrides `<env_prefix><SECTION>_<KEY>`, the keychain service
`brand.keychain_service`, the launchd logs `~/Library/Logs/<slug>-comms/`, the
root stream of the memory `brand.slug`. A fresh clone carries the placeholder
`acme` / `Acme`; `engine init` (a few
questions on a terminal, flags headless, `--from <brand.json>` for none)
writes `brand.json` and renders the tables of `streams.md` from it; the Setup
page of the control page edits the same file. `engine validate` names the
key and the fix for anything wrong in it. Read the derived names with `scripts/config.py brand | labels | env-name | log-dir`;
never type a label or a prefix into a file.

## Shared memory is the single source

`.atelier/memory/` holds the doctrine every tool and agent reads, and nothing
duplicates it. In the template the files are shapes, with every heading and
column the scripts parse and no content, until `init` and `/corpus-cycle` fill
them:

- `streams.md`: the registry of the streams the engine serves: memory path,
  owner state (never a name), autopilot rule, guardrails and pair rules. Its
  three tables are rendered from `brand.json` by `engine apply`, their one
  writer; change the setup, never the tables. The
  brand's memory is this root; another stream lives under `streams/<slug>/`,
  resolved by `scripts/memory.py` and never defaulted.
- `themes.md`: the theme hashtags, their differentiators, the fact each may
  link back to, licence grade and taggable partners.
- `handles.md`: own channels and partner handles with `verified` / `collect`
  status, taggable themes and `last_verified`. `handles.private.md` beside it
  is **gitignored** (start from `handles.private.example.md`) and holds the
  stealth denylist; a checkout without it makes the claim gate block, never
  pass.
- `claims.md`: the claims register: one row per checkable claim with grade,
  source, date, tier, themes, supersession and corroboration. A draft cites
  rows by id (`cites`), the gate refuses an unknown, superseded or
  uncorroborated id, and a present-tense capability sentence needs a row at
  grade evidenced. Written only by `/corpus-update --apply`, tighten-only;
  never deleted, only superseded. Other streams keep theirs under
  `streams/<slug>/claims.md`.
- `voice.md`, `instincts.md`, `status.md`, `logics.md`, `glossary.md`,
  `project.md`, `lessons.md`, `campaigns/`, `decisions/`: voice, standing
  rules, what is evidenced, argument shapes, dated lessons and decisions.
- `reviews.md`: a person's standing reviews, appended by
  `plugins/comms-engine/scripts/desk_sync.py --pull` from the decisions
  recorded on the desk. Append-only, written by that script alone;
  `theme-writer` reads it before drafting and `gatekeeper` before gating. A
  review can tighten what may be claimed, never loosen it: `status.md` still
  outranks it.

`status.md` outranks `project.md` wherever they disagree. Read it before
writing any claim.

New strategy material reaches memory through one path: `/corpus-cycle` (or its
steps `/corpus-sweep`, `/corpus-read`, `/corpus-analyse`, `/corpus-update`,
under `commands/`). It sweeps every folder of the corpus
root (`params.corpus.root`, set per machine with `engine setup corpus`),
reads what changed, writes a brief to the gitignored `Docs/Research/`, and
only `/corpus-update --apply` edits `.atelier/memory/`, tighten-only. Do not
update memory from a document by hand.

## One engine runtime, and a repo that runs with plain `claude`

- `.claude/settings.json` is **tracked** and is all of `.claude/` that is: the
  plugin enablement (`comms-engine@comms-engine` and the roles' plugins), the
  deny list and the MCP approval. The engine's agents, skills, commands and
  hooks load from the plugin, so its agents are `comms-engine:<name>`
  (`comms-engine:gatekeeper`) wherever a workflow names one. On a development
  machine the marketplace is this directory, registered once in the gitignored
  `settings.local.json`: `claude plugin marketplace add ./ --scope local`, then
  `claude plugin install comms-engine@comms-engine --scope local`; an instance
  names the GitHub marketplace in its own settings (`extraKnownMarketplaces`).
  `plugins/comms-engine/install.sh` only reports what a machine lacks. The roles'
  plugins (`atelier@atelier`, `salon@atelier`, `motion@atelier`) are enabled
  here but installed per machine (`claude plugin install <name>@atelier --scope
  project`); `engine plugins` says whether each one loads in this checkout.
- Code runs the cycle. `scripts/workflow.py` runs the workflows of
  `params.workflows` in the order of `params.chains` (`weekday`, `engagement`):
  script steps as subprocesses, each model step one `claude -p` with one
  agent, its own budget, a narrow tool list and a JSON reply code checks
  before anything is written; run records under `state/runs/<workflow>/`.
  `cycle.sh`, `/social-cycle` and `engine run <workflow or chain>` call it.
  The briefs are under `briefs/workflows/`.
- The plugins are called, not quoted, and by role: `params.plugins.roles`
  names for each role the plugin agent or skill, its pinned version, a brief
  under `briefs/` and a fallback (`scripts/roles.py`; `doctor` fails on
  a version that is not the pinned one). `theme-writer` preloads its salon and
  atelier skills through its `skills:` line; the workflows call
  `atelier:brand-voice-keeper` (before the gate),
  `salon:adversarial-refinement` (the gate's second reviewer),
  `salon:campaign-strategist` and `salon:launch-window` (the Friday slots),
  `salon:engagement-manager` (the engagement pass) and `salon:campaign-retro`
  (the monthly readout); `/motion <id> --film` drives `motion:video`, its
  words held by `motion.py film`. A plugin agent knows none of this
  repository's rules, so the role's brief carries them, and it holds no Bash,
  so the runner writes the run-log line. `settings.json` denies what must not
  be used: salon's look-alikes of the project's own gate, listening, publish
  and post skills and agents, and `motion:post`. `motion:generate` is held by
  the Skill hook until its cost sign-off is recorded.
  The scheduled runs switch off `plugins.interactive_only` (the Motion plugin)
  through `--settings`, so no plugin installs packages at the start of a job.
  `engine plugins --prepare` keeps atelier's write log with the engine's
  own logs, and `motion.py kit --write` writes the Motion plugin's brand kit
  from the brand genome where there is none.
  atelier's copy check answers a Write or an Edit with a note and never blocks:
  advice for copy the writer authored, never a reason to change a lifted line,
  a cite or a person's words.
- Hooks, the plugin's (`hooks/hooks.json`, under `${CLAUDE_PLUGIN_ROOT}`):
  `SessionStart` runs `scripts/session_brief.py` (the latest listening
  pass and what is new in memory; lessons by their `## YYYY-MM-DD` heading,
  decisions by their dated filename, keep those shapes). `PreToolUse` on Bash
  runs `hooks/guard_posting.py`: it refuses a raw platform write that
  bypasses `channels.send()` (`xurl post|reply|delete`, a curl/wget/http write
  to the LinkedIn or X API, `composio execute` of any channel-toolkit slug that
  is not a listed read, a `composio proxy` other than a GET, `composio run`, the same
  by hand against backend.composio.dev). The engine's own Composio calls are an
  HTTPS client in `channels.py` (project key in `x-api-key`, never the `composio`
  CLI, which ignores the key).
  It no longer asks who runs a command; engine scripts pass, because every send
  they make goes through `channels.send()`. `PreToolUse` on Skill runs
  `hooks/guard_skills.py`: `motion:generate` only behind the recorded
  cost sign-off (`params.motion.generate_signoff`), refused when unreadable.
- Schedules: the `jobs` list of `plugins/comms-engine/engine.json`, rendered
  per machine by `engine install` (`schedule/install.sh`, `--dry-run` first).
  Every plist runs `~/.local/bin/comms-engine runjob <label>` with
  `COMMS_ENGINE_INSTANCE` set: the shim `engine shim --install` writes, which
  finds the installed plugin's root at each start, since that root moves on
  every update. The same file holds
  each job's parameters under `params`, read through `scripts/config.py` with
  `engine.local.json` (gitignored) and `<env_prefix><SECTION>_<KEY>` outranking
  it; `jobs` in `brand.json` says which are on. The sender is
  `scripts/autopilot.py`; whether the brand sends automatically is the
  stream's `autopilot` setting in `brand.json` (`nothing` by default, `by
  switch` to follow the review modes) and then `switches.mode(stream, channel,
  kind)`, the one answer to "may this go without a person", changed only by a
  person's recorded act on the Autonomy page.
- The console: `scripts/engine.py` (`init`, `validate`, `apply`, `status`,
  `run <job, workflow or chain>` dry by default, `enable`, `disable`, `logs`,
  `doctor`, `eval gate`, `setup <job>`, `secrets`, `plugins`,
  `onboard-stream`, `new-instance`, `shim`, `host-check`) is the one module that calls `launchctl`,
  `install.sh` and the dry runs; `scripts/engine_tui.py` and `/engine` are
  faces over it. `docs/05-console.md` is the contract in prose.
  `npx github:lama-assaf/comms-engine-template` (`cli/setup.mjs`, Node, no
  dependency) is the guided setup and a menu over the same `engine` commands;
  it never does what an `engine` command does.
- `.mcp.json` needs no environment variable. Secrets resolve through
  `scripts/secrets.py` only.

## Six standing rules of the learning loop

1. **Drafts only** unless the stream's `autopilot` setting says otherwise.
   Where it says `by switch`, each kind of send (post, reply, comment, like,
   repost, quote) follows its review mode for that stream and channel: `review`,
   the default, waits for a person; `auto`, set by a person as a recorded act,
   lets whatever passes the automatic checks go out and leaves whatever fails in
   the queue. A send still passes `channels.send()` and all its checks in both
   modes, and a stream's pause stops every send at once. The engine never flips
   a row to `Published` except where the autopilot setting, set by a dated
   decision file, lets it create a gated Blog row as Published. (Reworded by
   `decisions/2026-11-13-autonomy-variety-engagement.md`; `PLAN-autonomy.md`
   is the plan.)
2. **One variable per hypothesis**, named on the note (`hypothesis`), with the
   planning query it answers (`query`).
3. **A predicted band on every draft** before it leaves the queue (`predicted`:
   below, baseline, above; `test_id`); the record lands in
   `state/predictions.json`.
4. **Statistics and named counterparties hold for human review**: the
   registry's hold-for-review classes, the gate's partner and stats checks.
   The hold is the kind `hold` of the review switch: on `review`, the default,
   it waits for a person's release; on `auto`, set by a person for that stream
   and channel, it passes without one. Every other check is untouched.
5. **A claim comes only from `claims.md`** or a primary source cited in the
   piece.
6. **Replies and comments are summarised as patterns**, never stored per
   person: counts, tiers and shapes, no handles in any record.

## Working conventions

- **Every send goes through `channels.send()`.** Wherever it is called from (the
  scheduled sender, the dashboard, an agent) it refuses unless every check
  passes: the stream's pause, the deterministic gate, current cites, the
  stealth list, hold for review, the stream's account and pair rules, quiet
  hours and caps, the kind of send with its review mode, and the media hash.
  It records each send and each refusal. The kinds are post, reply, comment,
  like, repost, quote and delete (take down, on a person's act). On `review` a
  send waits for a person; on `auto` what passes goes out. Hold for review
  passes without a release only where the `hold` mode is `auto`. A like on X
  is a person's click unless the owner's sign-off is recorded. Marking an
  article live on the site (the `blog-live` act on the control page) stays a
  person's act.
- **Only code writes a gate verdict.** The gatekeeper and the second reviewer
  return findings; `scripts/review.py` checks them against `claims.md` and
  stamps the verdict by text hash. Brand rules and formats are data
  (`gate-rules.json`, `formats.json` in the stream's memory), never regexes.
- **The vault note is the record.** `Content/Calendar/<title>.md` is written
  only by `plugins/comms-engine/scripts/repo.py`; `state/queue.json` and the
  desk's `state/desk.db` are derived indexes. Never hand-edit an engine note
  to move it along.
- **The desk owns the person's acts, and nothing else.**
  `Tooling/desk/` is a Next.js app over Drizzle; its
  `decisions`, `edits`, `argument_lines` and `reviews` tables are the only rows
  that exist nowhere else until `scripts/desk_sync.py --pull` writes them out.
  `--push` refreshes the mirror tables from the notes and is built to refuse
  those four, so a refresh cannot destroy a decision that has not been pulled.
- **Conflicts skip, never clobber.** That binds desk-to-vault
  (`scripts/apply_edits.py`).
- **Every record names its stream.** `repo.py` refuses an item without one and
  `state_check.py` checks every state file.
- **Secrets** resolve through `plugins/comms-engine/scripts/secrets.py`
  (`get_secret`), environment first then the macOS keychain. No token belongs
  in a file. No person's name and no per-person handle belongs in a record.
- **Prose style.** Comments and docs explain why, in plain prose, no
  em-dashes. Every script opens with a docstring saying what it is, why, and
  its command lines.

## How work is verified

```bash
engine doctor     # every line below, one ok/FAIL line each; secrets reported, not failed
engine validate   # brand.json: the key and the fix per problem
engine apply --check   # the streams.md tables against brand.json
engine runtime   # the python3 the jobs start imports every pinned package
engine workflow chain weekday --dry   # every command and model call of a cycle, none made
engine reactions send-due   # the reactions due, dry: every check, nothing sent
engine status     # the jobs table, secrets, plugins, last cycle; exit 1 if stale or not loaded
engine results --since 7d   # what each job produced, per job, nothing changed
python3 -m unittest discover plugins/comms-engine/tests   # every test on fixtures, none on live state
npm test                                                   # the npx setup command (cli/), on fixtures
engine listen --dry-run  # queries, no paid call
engine x_stream rules    # twitterapi.io rule plan, changes nothing
engine desk_sync --pull --dry-run   # the desk edge
engine memory --list     # the stream registry
engine state_check       # every state record names its stream
engine gate_lint         # the deterministic gate, cites included
engine claims_check --dry-run   # notes whose cited claim moved
engine plan_queries --dry-run   # gaps, freshness, depth per theme
engine x_metrics --dry-run  # which X posts get public counts, calls nothing
engine score --dry-run   # scoring from local files only
engine metrics --dry-run # the scorecard rows
engine guardrails --stream acme --channel X   # may the brand send now (its slug)
engine session_brief --dry-run   # the SessionStart brief, marker untouched
engine autopilot run --dry       # the sender against the calendar, sends nothing
engine parity --dry               # native vs composio write drivers over the same due rows, platform layer faked, nothing sent
engine jobs_status               # every scheduled job, loaded or not, last run
engine config show               # the merged configuration, placeholders expanded
engine install --dry-run         # the launchd plists for this instance, each `comms-engine runjob <label>`, loads nothing
engine shim                      # ~/.local/bin/comms-engine, the path the plists run: current or not
engine backup --dry              # what the backup job would commit, nothing changed
engine host-check                # a hosted Mac only: path, pmset, auto login, Tailscale Serve, token, denylist, backup remote
plugins/comms-engine/install.sh --check   # plugins, secrets, tools
claude plugin validate plugins/comms-engine --strict   # the plugin's manifest, hooks, agents and skills
```

CI (`.github/workflows/ci.yml`) runs on every push to main and every pull
request: `ruff check plugins Tooling` (the rules are `ruff.toml`; the linter is pinned
in `requirements-dev.txt`), the suite on macOS with the packages pinned in
`requirements.txt`, the desk's typecheck, the control page's build (which must
leave the committed `ui/dist` unchanged) and `npm audit` on both lockfiles. A
new Python import needs its pin in `requirements.txt`; `test_repo_standards.py`
fails without it.

The desk itself, an optional module of the instance: `cd Tooling/desk && npm
run dev` (port 4310), after one `engine desk_sync --push`. See its `README.md`.

X is read through twitterapi.io only: search, our own posts' public counts and
the stream; LinkedIn through Apify only with `--linkedin`. Both are
pay-per-result; keep `--max` at or under 12 per term and never add
`--linkedin` without a reason.

## Records

`TEMPLATE-CONTRACT.md` at the root says what the brand block derives, which
API the scripts expose and what the build left undone. Every script's docstring says what it is, why, and its command
lines; read it before changing the script.
