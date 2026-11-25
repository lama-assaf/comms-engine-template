# 5. The console

One CLI over the scheduled jobs and the setup, `plugins/comms-engine/scripts/engine.py`,
with a curses screen and a Claude Code command as its two faces. It is reached
as `engine <command>`: the plugin's `bin/engine` runs a console command of
`engine.py` when the name is one (`doctor`, `run`, `host-check`, ...) and
`scripts/<name>.py` otherwise, always with the instance as its working
directory. It is the only module that calls `launchctl`, `schedule/install.sh`,
`schedule/runjob.py` and the dry runs; the screen and the command import its functions or call its
CLI, so each behaviour exists once. Every action prints the exact command it
runs (`$ ...`) first, so the console teaches the CLI. This chapter is the
contract every piece was built against.

Nothing here posts, publishes or loads a job on its own: `run` is a dry run
unless `--live` is given, `--live` is refused outright for the autopilot, the
X stream, the control page and caffeinate, `enable` goes through `install.sh`, and `setup`
writes `engine.local.json` and ends with a dry run, never with a load. The
project's setup file, `brand.json`, is written by `init` and by the Setup
page of the control page; `engine.json` is shipped defaults and no command
edits it.

## 5.1 `engine.py`

`<job>` is a console alias (`corpus`, `cycle`, `autopilot`, `engagement`,
`score`, `claims-check`, `x-stream`, `x-poll`, `inbound`, `control`, `backup`,
`nosleep`), the job's name in
`engine.json` (`corpus-cycle`, `social-engine`, ...) or its launchd label
(`com.<slug>.<name>`).

| subcommand | what it does | exit |
|---|---|---|
| `init [--slug <slug> --name "<Name>"] [--narrator] [--x] [--linkedin] [--label-prefix] [--env-prefix] [--keychain-service]` | the guided setup: on a terminal it asks the few questions (slug, name, narrator, X handle, LinkedIn page), headless every one is a flag; writes `brand.json` at the root, renders the three tables of `streams.md` from it, renames the brand cells of `handles.md`, prints the first commands; never edits `engine.json`; a registry kept by hand is imported cell for cell when there is no `brand.json`; idempotent | 0; refuses a slug outside `[a-z][a-z0-9-]{1,23}`, and a headless run with no slug |
| `init --from <brand.json>` | sets a clone up from a setup file with no questions; the file is validated first and takes no other flag | 0; 1 with the key and the fix when the file does not validate |
| `validate` | checks `brand.json`: an unknown key, a wrong type, a missing stream, each as `brand.json: <key>: <problem>. Fix: <fix>` | 1 when there is a problem |
| `apply [--check]` | renders the registry, guardrails and pair-rule tables of `streams.md` from `brand.json`, the one writer of those tables; `--check` writes nothing | `--check`: 1 when the tables and the file disagree |
| `status [--json]` | the jobs table (loaded, last run, stale), then `secrets N/M present`, `plugins N/M installed`, `last cycle <time> budget <usd> exit <n>`, then each workflow that has run: its last run, result, what waits for a person and the day's spend | 1 when any job is stale or not loaded (optional jobs and caffeinate excluded) |
| `run <job> [--dry\|--live]` | the job's dry form by default (the sweep's to-do, the planner and listener dry runs, `autopilot.py run --dry`, `engage.py due`, the scorer and metrics dry runs, `claims_check.py --dry-run`, `x_stream.py rules`); `--live` runs it through `runjob.py` as the schedule would | the job's; 2 unknown; 3 `--live` refused |
| `run <workflow or chain> [--live]` | a workflow (`gate`, `draft`, `react`, ...) or a chain (`weekday`, `engagement`) through `scripts/workflow.py`: dry prints every command and model call it would make and calls nothing; `--live` runs it and writes the run records | the runner's; 1 when a workflow failed |
| `eval gate [--live \| --status]` | the two reviewers over the labelled drafts in `tests/fixtures/gate_cases/`: dry lists the cases and what code alone decides; `--live` makes paid model calls and writes `state/gate-eval.json`; `--status` says which house-style rules the set has cleared for retirement | 1 when a should-block case was missed |
| `enable <job>` | `schedule/install.sh --only <label>`: render and load one job; keeps the installed plist's `CLAUDE_CONFIG_DIR`; refuses a calendar job with a live PID | install.sh's; 1 running; 2 unknown |
| `disable <job>` | `launchctl bootout gui/<uid>/<label>`; the plist stays | 0; 2 unknown |
| `results [--since 36h\|7d\|ISO] [--json]` | what each job produced since the session brief's marker: drafts and verdicts, the listening pass, comment drafts for Alpha, scorecard, claims check, corpus runs and memory commits, autopilot sends and refusals, each with where to act; the digest is the console's alone, the dashboard page shows the posts and what is live | 0 |
| `logs <job> [-n N]` | the job's own log under `state/` and launchd's under `~/Library/Logs/<slug>-comms/<label>.log`, both tails | 1 when neither exists |
| `doctor` | the engine version line (`brand.json` `engine.version` against the loaded plugin's `plugin.json`: FAIL on another, reported when nothing is pinned), the Claude token line (`params.host.claude_token_set`: a warning from day 330, FAIL after a year), and every command in `CLAUDE.md` "How work is verified", in order, plus `config.py show`, `engine validate`, `engine apply --check` (the `streams.md` tables against `brand.json`), `engine runtime` (the `python3` first on the jobs' `path` imports every package `requirements.txt` pins), `secrets.py --check <required>` and the plugin roles (each role resolves to a brief and a fallback, each installed plugin is the pinned version); one `ok`/`FAIL` line each with its seconds and last line; three checks are answers rather than faults when they exit 1 and stay `ok` with their last line shown: a missing secret (`missing: NAME, ...`), `guardrails.py` outside the sending window, and `x_stream.py rules` without an own X handle or a key | 1 when any check failed |
| `setup <job> [--<key> <value>]...` | the job's questions (below); asked on a terminal, flags headless; writes `engine.local.json`; ends with the dry run and `not loaded; enable with: ...` when the job is not loaded | 1 a refused value, nothing written; 2 unknown job |
| `onboard-stream <slug> [...]` | forwards to `scripts/onboard.py` (chapter 6) | onboard.py's |
| `secrets [--set NAME] [--export NAME... \| --check NAME...]` | present or missing by name, required first, never a value; `--set` prompts hidden and writes the keychain (for `CLAUDE_CODE_OAUTH_TOKEN` it also records the date as `host.claude_token_set`); `--export` and `--check` are `secrets.py`'s own | 1 when a required one is missing |
| `plugins` | installed or not, with the install line for each missing one | 1 when one is missing |
| `new-instance <dir> [--from <brand.json>] [--marketplace owner/repo]` | a brand's own instance repository (`scripts/instance.py`): the instance files from the template (the memory as shapes, no engine code), the marketplace named and `comms-engine@comms-engine` enabled in its `.claude/settings.json`, `brand.json` pinned to this engine, `git init`, nothing committed | 1 when the directory is not empty or the setup file is refused |
| `shim [--install]` | `~/.local/bin/comms-engine`, the fixed path every plist runs: `current`, `missing` or `out of date`; `--install` writes it | 1 when it is not current (without `--install`) |
| `host-check` | the office Mac (`docs/07-hosting.md`): the instance outside the protected folders, `pmset` (never sleep, restart after a power failure), automatic login (and FileVault), Tailscale Serve to the control page with a role map, the Claude token kept and dated, `handles.private.md` present, the backup remote reachable with push on; one `ok`/`FAIL` line each, reads only | 1 when any line failed |

### Setup questions

Every question is a `--<key>` flag with a default (the current value through
`config.cfg`, so the questionnaire always shows what the job reads now), asked
only when `sys.stdin.isatty()` and the flag was not given. A key no script
reads yet is written and marked `recorded, not read by any script yet`.

| job | keys |
|---|---|
| `corpus` | `root` (must exist; `~` written as `__HOME__`), `include`, `exclude`, `extra-roots`, `max`, `apply`, `budget-usd` |
| `cycle` | `drafts`, `listen`, `max-per-term` (above 12 refused), `linkedin` (paid; `yes` needs `--linkedin-reason`), `budget-usd`, `editor`, `slots`, `readout` |
| `autopilot` | `grace-days`, `commit`; the stream's autopilot setting is printed, not asked: it is a key of `brand.json`, changed on the Setup page or by `init`, on a decision |
| `engagement` | `window-days`; `dry_run` is shown, not asked |
| `score` | `x-metrics`, `demand`, `close-livetests`; the reads under `state/metrics-input/` are shown first |
| `claims-check` | `state-check`, `dashboard` |
| `x-stream` | `rules-file`, `max-rules`; an active rule is billed per matched post |

Not a setup question, set with `config.py set`: `autopilot.timezone` (the
IANA zone the guardrails are judged in), `site.post_url` and
`site.webhook_url` (where a published piece lives on the brand's site, and
the rebuild hook `publish.py --webhook` posts to with `<env_prefix>WEBHOOK_SECRET`).

## 5.2 Configuration layering

```
engine.json  (tracked: shipped defaults nobody edits; jobs, params, workflows, plugin roles; __HOME__ and __REPO__ placeholders)
  < brand.json  (tracked, at the root: the brand, its streams, drivers, which jobs are on, plugin roles; written by init and the Setup page)
    < engine.local.json  (gitignored: per-machine brand, params and streams; never jobs or path)
      < <env_prefix><SECTION>_<KEY>  (dotted path upper-cased, leading `params` dropped; typed by the value it overrides)
```

`brand.json` is small on purpose and uses its own short keys; `config.py`
translates them on load (`drivers` to `params.channels.write_driver`,
`x_read` and `x_own` per stream, `jobs` to which jobs the all-jobs install
loads, `plugins` to `params.plugins`), so every script keeps reading
`config.cfg` and none reads the file itself. `config.py validate` (the same
check as `engine validate`) runs on it.

`config.py get <path>` prints a scalar (`true`/`false` for a bool) or JSON;
`config.py set <path> <value>` writes `engine.local.json`; `config.py show`
prints the merged document; `config.py validate` checks `brand.json`; `config.py brand [key]`, `labels
[--optional|--required]`, `label <job>`, `env-name <path>`, `log-dir` print
the brand's derived names. The brand itself is never read from the
environment. Shell scripts ask `config.py brand env_prefix` once and read the
prefixed variables indirectly, so an exported `<PREFIX>CYCLE_BUDGET_USD`
still wins; when `config.py` cannot run they read the prefix from
`engine.json` with a one-line JSON read, and only when that file is unreadable
too do they fall back to the placeholder prefix `ACME_`.

## 5.3 The screen: `engine_tui.py`

```bash
engine engine_tui
```

curses from the standard library, no dependency, 80x24 at least. Left pane:
the jobs with their state and last run, the streams with owner state, the
secrets, the plugins. Right pane: the selected item (what, schedule, loaded or
not, its parameters, the last log lines). Bottom line: the exact command the
last action ran, and its exit.

Keys: `j`/`k` or arrows move, `tab` next section, `r` run dry, `R` run live
(asks `y`; refused for autopilot, x-stream, nosleep), `e` enable (asks `y`),
`d` disable (asks `y`), `s` setup (suspends the screen and asks on the
terminal), `l` logs, `o` onboard a stream, `g` refresh, `?` help, `q` quit.
Headless it says so and exits 2: use `engine status`.

## 5.4 In Claude Code: `/engine`

`/engine` with no argument runs `engine status` and shows the table; `setup
<job>` asks each question in chat and runs the CLI with every answer as a
flag; `run`, `logs`, `doctor`, `secrets`, `plugins` show the CLI's output;
`run --live`, `enable` and `disable` confirm first. In a headless run the
command only reads (`status`, `doctor`, `logs`) and says which write it
skipped. The `engine-console` skill is the same knowledge for an agent that
needs it mid-task.
