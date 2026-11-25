---
name: engine-console
description: The operator's view of the engine - which launchd jobs exist, what runs when, what is stale or not loaded, how to run a job dry, enable or disable it, read its logs, set up its parameters, check secrets and plugins, or onboard a stream. Use when the user asks about jobs, schedules, "what runs", "is the engine healthy", "set up the corpus job", "onboard a stream", or anything about engine.json, engine.local.json or the console; the answer is a subcommand of scripts/engine.py, run through /engine.
---

# engine-console

The engine is eight launchd jobs on this Mac (`engine.json`
`jobs`) with their parameters beside them (`params`), per-machine overrides in
the gitignored `engine.local.json`, and the environment
(`<ENV_PREFIX><SECTION>_<KEY>`, the prefix from `brand.env_prefix`, `ACME_` in
a fresh clone) outranking both. One CLI,
`engine`, is the only module that
calls `launchctl`, `schedule/install.sh`, `runjob.py` and the dry runs; the
curses screen `engine_tui.py` and the `/engine` command are faces over it. In
Claude Code the face is `/engine` (`commands/engine.md`); this skill
says which subcommand answers which question. The contract is
`CONSOLE-CONTRACT.md`.

## which call answers which question

| the person asks | run | what comes back |
|---|---|---|
| what runs, what is scheduled, is the engine healthy, is anything stale | `/engine status` | the `jobs_status.py` table (label, last run, state, what), then `secrets n/m present`, `plugins n/m installed`, `last cycle <at> budget <usd> exit <code>`; exit 1 when a job is `stale` or `not loaded` (nosleep and the optional x-stream excluded) |
| what did the engine produce since I last looked | `/engine results [--since 36h]` | per job: drafts and verdicts, the listening pass, comment drafts for Alpha, scorecard, claims check, corpus runs and memory commits, autopilot sends and refusals; the digest is the console's alone, the dashboard page shows the posts and what is live |
| why did a job fail, what did it do last | `/engine logs <job> [-n N]` | the job's own log under `state/` and launchd's `~/Library/Logs/<slug>-comms/<label>.log` (`config.py log-dir`), the repo one first |
| does everything still work, is the clone healthy | `/engine doctor` | one `ok`/`FAIL` line per check in CLAUDE.md "How work is verified", plus `config.py show` and `secrets.py --check`; a missing secret, the guardrails' refusal and `x_stream.py rules` without a handle or key are reported on an `ok` line, not failed; `doctor: N ok, M failed` last |
| what would the job do, try it without sending | `/engine run <job>` (dry) | `$ <command>` then the dry form's output; corpus `corpus_sweep.py --only-todo`, cycle `plan_queries.py` and `listen.py --dry-run`, autopilot `autopilot.py run --dry`, engagement `engage.py due`, score `score.py` and `metrics.py --dry-run`, claims-check `claims_check.py --dry-run`, x-stream `x_stream.py rules` |
| run it for real, now | `/engine run <job> --live` after one confirmation | `runjob.py <job>`; refused (exit 3) for `autopilot`, `x-stream`, `nosleep` |
| how many drafts a day, what does the corpus job read, the budget, the window | `/engine setup <job>` | the questionnaire from the command file, written to `engine.local.json`, ending in the job's dry run; a key no script reads yet is printed `(recorded, not read by any script yet)` |
| start or stop a job on this machine | `/engine enable <job>` / `/engine disable <job>` after one confirmation | `install.sh --only <label>` renders and bootstraps; `disable` boots out and leaves the plist |
| are the tokens there | `/engine secrets` | `NAME: present (backend)` / `NAME: MISSING -> engine secrets --set NAME`; never a value |
| are the plugins installed | `/engine plugins` | `marketplace: <url>` then one line per plugin |
| add a second stream | `/engine onboard-stream <slug>` | `scripts/onboard.py`; the slug needs a row in `streams.md` first (a decision file), and the stream drafts nothing until its owner is confirmed and `voice.md` exists |
| which business does this checkout serve | `engine config brand` | the brand block: slug, name, label prefix, environment prefix, keychain service. `engine init --slug <slug> --name "<Name>"` stamps it once on a fresh clone |

Short names and labels are interchangeable: the label is
`<label_prefix>.<name>`, so with the shipped placeholder `cycle` is
`com.acme.social-engine`, `corpus` is `com.acme.corpus-cycle`, and
`autopilot`, `engagement`, `score`, `claims-check`, `x-stream`, `nosleep` are
`com.acme.<name>`. `engine config labels`
prints the real ones.

## three rules

1. **A headless run reads and never writes.** With no person in the session
   (`claude -p`, a scheduled job, a subagent) the console answers `status`,
   `doctor`, `logs`, `secrets`, `plugins` and dry `run`, and skips `setup`,
   `onboard-stream`, `enable`, `disable`, `run --live` and `secrets --set`,
   saying which call it skipped and why. Configuration is read through
   `config.py get`; nothing writes `engine.local.json` without a person
   answering the questions.
2. **Enable and disable are a person's act.** Loading a job means it runs on
   its schedule from then on, unattended; unloading one means a step of the
   loop stops. Both are asked once, with the exact command, and run on `yes`.
   A `setup` never loads a job: it ends with `not loaded; enable with:
   engine enable <job>` when the job is not in `launchctl list`, and the
   person decides.
3. **Every send goes through `channels.send()`, here as everywhere.** `run` is dry by default;
   `--live` is refused for the autopilot (it sends), the stream (billed per
   match) and caffeinate (launchd's). The PreToolUse hook refuses a raw
   platform write that would bypass `channels.send()` regardless. The autopilot's
   channel rule is read from `streams.md` and changes only through a decision
   file under `.atelier/memory/decisions/`, never through a setup answer.

## reading a status

- `ok` is loaded and ran inside its staleness window (`jobs_status.HOW`:
  weekday jobs 30 h, nightly 26 h, the autopilot 8 h).
- `stale (N d)` is loaded but silent longer than that: read `/engine logs
  <job>`, then `/engine run <job>` dry to see whether the script still works,
  before anything is re-enabled.
- `not loaded` means launchd does not have it: `/engine enable <job>` after
  the person says yes. `x-stream` is optional and `not loaded` by design until
  someone enables it by name (`/engine enable x-stream`); the all-jobs
  `install.sh` skips it. `enable` carries the installed plist's
  `CLAUDE_CONFIG_DIR` when the shell has none, and refuses a job that is
  running right now (install.sh would boot it out mid-run).
- `last cycle ... exit N` is the `=== social-cycle exit N ===` line cycle.sh
  writes at the end of the last block of `state/schedule.log`; a block without
  one (older, or still running) counts as 1 when it carries an `Error:` or
  `Traceback` line; `/engine logs cycle` shows it.
- `/engine run corpus` prints `pending work found` and exits 0 when the sweep
  has sources waiting (corpus_sweep.py itself exits 1 then); exit 2 is the
  root not found, which is what a fresh clone says until `setup corpus --root`
  points at a real folder.
- The session brief carries one line from the same reading every morning
  (`engine console: ...`), so a stale job is seen without opening anything.

## what lives where

- `engine.json` (tracked): the brand block, the jobs and the parameter
  defaults; a schedule change is an edit here, then `/engine enable <job>`
  re-renders the plist.
- `engine.local.json` (gitignored): what `setup` writes, per machine; paths and
  budgets belong here, never a secret.
- `.atelier/memory/streams.md`: the stream registry, owner state and the
  autopilot rule; the console reads it and never writes it.
- `~/Library/LaunchAgents/<label_prefix>.*.plist`: rendered by
  `schedule/render.py` through `install.sh`; `disable` leaves the file,
  `enable` rewrites it.
