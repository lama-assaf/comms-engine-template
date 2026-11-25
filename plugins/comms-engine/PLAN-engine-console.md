# Plan: the engine console (onboarding, launching and setting up each job)

_Written 2026-11-05. Status: **built 2026-11-05** (steps 1 to 5 the same
evening, orchestrated as a workflow: contract, core, three surfaces in
parallel, verify, docs; step 6, the plugin manifest, is open). Companion to
`PLAN.md` (the loop) and `ORCHESTRATION.md` (what runs); the contract the
builders coded against is `CONSOLE-CONTRACT.md`. Rewritten for the template the
same day: the brand block (`engine init`) joined the console after the
first build._

## What was built

- `engine.json` (tracked) with `brand`, `jobs` (eight scheduled jobs), `params`
  per job and `streams`; `engine.local.json` (gitignored) for per-machine
  values; `scripts/config.py` as the one read path (`cfg`, `get`, `set`,
  `show`, `brand`, `label`, `labels`, `env-name`, `log-dir`), environment
  first. `render.py`, `runjob.py`, `install.sh`, `jobs_status.py`, `cycle.sh`
  and `corpus_cycle_daily.sh` read it; every command line keeps working.
- `scripts/engine.py`: `init`, `status`, `run`, `enable`, `disable`, `logs`,
  `doctor`, `setup` for all seven jobs, `secrets`, `plugins`, `onboard-stream`;
  one subprocess seam, one `launchctl` seam, `$ <command>` before every act.
- `scripts/engine_tui.py`: the two-pane curses screen over `engine.py`.
- `/engine` (`commands/engine.md`) and the `engine-console` skill; one
  line in the session brief from `engine.status_rows()`.
- `scripts/onboard.py` and `.atelier/memory/templates/voice.md`.
- Tests: `test_config`, `test_engine`, `test_engine_tui`, `test_engine_command`,
  `test_onboard`, `test_brand`.

Deviations from the plan below, all recorded in `CONSOLE-CONTRACT.md`:

- `setup` writes `engine.local.json`, not `engine.json`: a schedule or a default
  is a tracked edit, a machine's value is not. `install.sh` did not become a
  wrapper over `engine.py`; the direction is the reverse (`engine enable`
  wraps `install.sh --only <label>`, and refuses while the job has a live PID;
  `disable` is `launchctl bootout`, the plist stays).
- `cycle.sh` has no `--dry-run`, so the cycle's dry form is
  `plan_queries.py --dry-run` then `listen.py --dry-run`; `engage.py` has no
  `--dry-run`, so the engagement's is `engage.py due`. `cycle.sh` writes
  `=== social-cycle exit N ===`, which `status` reads for the last cycle.
- No `on` question for score, claims-check or x-stream: a loaded job runs, and
  `enable`/`disable` switch it. Thirteen `params` keys have no reader yet
  (`engine.INERT`: corpus include/exclude/extra_roots, cycle max_per_term and
  linkedin, autopilot.commit, the score and claims-check sub-flags, the x-stream
  rules file and cap); `setup` records them and says so beside each.
- `autopilot.py` and `engage.py` read `autopilot.grace_days` and
  `engagement.window_days` through `config.cfg`, the old constants as defaults.
- The TUI's `l` shows the log tail in the right pane, not a full-screen pager.
- Onboarding never writes `streams.md` (the row, owner cell and channels are
  printed for a person); `gate_lint.py` has no `--stream`, so the closing gate
  check lints a fixture in-process as the stream. Exit 1 is a refused value,
  2 an unknown slug or usage.
- The session brief line uses `status_rows()` (jobs only) so the SessionStart
  hook never spawns `secrets.py` or `claude plugin list`.
- `autopilot.timezone` is set with `config.py set`, not asked by `setup
  autopilot`: the `/engine` command's setup table is checked against
  `engine.QUESTIONS` by a test, so the question and the table row land
  together or not at all.

## Why

The engine has eight scheduled jobs, two install scripts, a dozen dry-run
commands and a handful of per-job parameters that used to live in four places
(a schedule file, `cycle.sh` environment variables, `corpus_cycle_daily.sh`,
`themes.json`). A new operator had to read three chapters to know which command
to run. The console puts that behind one surface, with a setup conversation per
job ("what should the corpus job read?", "how many drafts a day?", "may the
brand post on its own?") and one screen that shows what is loaded, what ran,
what is stale, and lets a person run, enable or disable a job without
remembering `launchctl`.

## Shape: one CLI, two faces, one config

```
                 ┌──────────── engine.json (one file: brand + jobs + parameters) ────────────┐
                 │ brand: slug, name, prefixes · corpus: root, include, exclude, max, apply ·  │
                 │ cycle: drafts, budget, listen · autopilot · engagement · score · x-stream  │
                 └───────────────▲──────────────────────────────▲────────────────────────────┘
                                 │ read/write                    │ read
        ┌─────────── engine.py (stdlib CLI) ────────────┐   ┌── scripts/* (cycle.sh, autopilot.py, ...) ──┐
        │ init · status · setup <job> · run <job> [--dry]│   │ read their parameters from engine.json       │
        │ enable/disable <job> · logs <job> · doctor     │   │ through config.py, env overrides kept        │
        │ onboard-stream <slug> · secrets · plugins      │   └──────────────────────────────────────────────┘
        └──────▲──────────────────────────▲──────────────┘
               │                          │
   engine_tui.py (curses, no deps)   /engine (Claude Code command + skill, AskUserQuestion)
   the screen for a terminal         the same flows in chat; used by a person or a headless run
```

- **`engine.json`** holds the brand block and replaces the scattered
  variables. One object per job: `name`, `what`, `program`, `calendar`,
  `log`, `optional`, plus a `params` block the job's script reads. A `streams`
  block carries per-stream overrides (corpus root, listening terms file).
  `render.py` reads the schedule half; `config.py` gives every script
  `cfg("cycle.drafts", default=3)` with the environment variable
  (`<ENV_PREFIX>CYCLE_DRAFTS`) winning.
- **`engine.py`** is the only thing that calls `launchctl`, `render.py`, the
  job scripts and the dry runs. The TUI and the Claude command are both thin
  layers over it, so a behaviour exists once.
- **`engine_tui.py`** is `curses` from the standard library, so a fresh clone
  needs no package. Left pane: the jobs with state (loaded, last run, stale),
  the streams, secrets, plugins. Right pane: the selected item's detail, its
  last log lines, its parameters. Keys: `r` run now (dry), `R` run now (live),
  `e` enable, `d` disable, `s` setup, `l` logs, `o` onboard a stream, `?` help.
  Every action prints the exact command it ran, so the screen teaches the CLI.
- **`/engine`** is a command file under `commands/` plus a short skill:
  it calls `engine.py` and asks the same setup questions with
  `AskUserQuestion`, so an operator in Claude Code gets the console without
  leaving the chat, and a headless run can read the config but never change it.

## The setup conversations

Each `setup <job>` is a short, resumable questionnaire that writes
`engine.local.json` and ends with a dry run whose output is shown. The
questions, per job:

| job | questions | ends with |
|---|---|---|
| **corpus** (what to read) | the corpus root (checked for existence; the template ships a placeholder); the folders to include or exclude, shown as the sweep's folder list with file counts and the current stage per file; `--max` sources per run; plan only or `--apply`; which blind-spot folders (a folder outside the root, a repository) to add as extra roots | `corpus_sweep.py --only-todo` and the three to-do tables |
| **cycle** | drafts per run; listening on or off and `--max` per term; LinkedIn listening (paid) on or off; budget cap; weekday flags (editor, slots, readout) on or off; the time shown | `plan_queries.py --dry-run` and `listen.py --dry-run` |
| **autopilot** | grace days; the channel rule shown from `streams.md` (drafts-only or posting) with the decision file it would take to change it; the timezone shown; whether `commit` runs | `autopilot.py run --dry` |
| **engagement** | the three-day window; dry-run (always, until a decision file says otherwise) | `engage.py due` |
| **score** | which reads exist (`metrics-input/`); the baseline rule; the sub-flags | `score.py --dry-run`, `metrics.py --dry-run` |
| **claims-check** | the sub-flags | `claims_check.py --dry-run` |
| **x-stream** | the rule plan from `themes.json`; the cost note | `x_stream.py rules` |
| **secrets** | each required name, present or missing, `--set` for the missing ones | `secrets.py --check` |
| **plugins** | marketplace and the two plugins, installed or not | `claude plugin list` |
| **stream onboarding** (`onboard-stream <slug>`) | owner confirmed (yes/no, never a name); the corpus root; the channels; a `voice.md` written from the stream's briefs or the template; the themes file; autopilot stays `nothing` | `memory.py --stream <slug>`, a gate check on a fixture |

A setup never loads a job; `enable` does, and says what it loaded.

## Health and the first week

`status` is `jobs_status.py` plus three lines: secrets present, plugins
installed, the last cycle's budget and its exit. `doctor` runs every dry-run
command `CLAUDE.md` lists and the test suite, and prints one line per check.
The session brief gains one line from `status` so a stale job is seen the next
morning without opening anything.

## Packaging

Once `/engine` exists, the whole `claude/` directory plus `engine.py` is the
natural unit for a repo-shipped plugin (`.claude-plugin/plugin.json`), so a
second brand's repository installs the same console and onboards its stream
with `onboard-stream <slug>`. The template repository is the other answer to
the same need: clone, `engine init`, and the console is there.

## Work, in order

1. **`config.py` and `engine.json`** (half a day): the schedule file merged
   in; the parameters moved out of `cycle.sh`, `corpus_cycle_daily.sh` and the
   plists; environment overrides kept; tests for the merge and the overrides.
2. **`engine.py`** (one day): `status`, `run`, `enable`, `disable`, `logs`,
   `doctor`, `setup` for corpus, cycle and autopilot; the other setups are
   one table each.
3. **`engine_tui.py`** (one day): the two-pane screen over `engine.py`.
4. **`/engine`** (half a day): the command file and the skill; the session
   brief line.
5. **`onboard-stream`** (half a day): the questionnaire over the per-stream
   directories; the `voice.md` template.
6. **Plugin manifest** (half a day, after the marketplace schema is verified).
7. **The brand block** (half a day, done for the template): `engine init`,
   `config.brand()` and the derivations; see `TEMPLATE-CONTRACT.md`.

## Examples consulted

Shapes, not code, from open-source repositories:

- a stdlib `curses` picker and screen (`curses.wrapper`, a result holder,
  stdin flushed after the wrapper returns, `KeyboardInterrupt` as cancel), and
  how a CLI talks about launchd-supervised processes (name the `launchctl
  bootout` target in the hint).
- the Claude Code PreToolUse validator shape (rules as regex and message, exit
  2 with the reason on stderr), which `hooks/guard_posting.py` follows.
- Textual two-pane viewers (Header, Footer, Tree, ListView), the richer
  alternative if a dependency is ever accepted.
- a setup questionnaire with `.skip_if(no_prompt, default=...)`, the pattern
  for every setup here: each question has a flag and a default so a headless
  run never waits.

## Decisions taken before step 1

- `curses` (stdlib, no dependency). Textual stays an option in the plan, not
  the build.
- The desk stays Alpha's surface; the console is the operator's. No jobs page
  in the desk.
- `engine.json` is tracked (the template's defaults); `engine.local.json`
  (gitignored) overrides per machine, for paths such as the corpus root; the
  environment variable `<ENV_PREFIX><SECTION>_<KEY>` outranks both.
- The schedule file merged into `engine.json` under `jobs`; `render.py`,
  `runjob.py`, `install.sh` and `jobs_status.py` read it there.
- Every setup question has a `--<key>` flag and a default, so `setup` runs
  headless; the questionnaire only asks when stdin is a terminal.

## Verification

`engine doctor` green on a fresh clone with the secrets set; every job
runnable with `run <job> --dry` from the TUI and from `/engine`; a stream
onboarded with `onboard-stream` drafts nothing until its owner is confirmed;
`engine init --slug demo --name Demo` on a temporary clone stamps the block
and renames the placeholder row; the suite grows by one test file per step.
