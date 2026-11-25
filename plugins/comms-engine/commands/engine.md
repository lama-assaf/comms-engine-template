---
description: The engine console in chat - what runs, what is stale, run a job dry, enable or disable it, read its logs, set up its parameters, onboard a stream. A thin face over scripts/engine.py; nothing here calls launchctl or posts.
argument-hint: [status|results [--since 36h]|run <job> [--dry|--live]|enable <job>|disable <job>|logs <job> [-n N]|doctor|setup <job>|onboard-stream <slug>|secrets|plugins]
allowed-tools: Bash, AskUserQuestion, Read
---

# /engine

The console is `engine` and this
command is its chat face: it runs the CLI, shows the output, and asks the setup
questions here instead of on a terminal. Every behaviour exists once, in
`engine.py`; do not reimplement a subcommand, call it. The contract is
`CONSOLE-CONTRACT.md` (c) and (e).

`<job>` is a short name (`corpus`, `cycle`, `autopilot`, `engagement`, `score`,
`claims-check`, `x-stream`, `nosleep`) or its launchd label
`<label_prefix>.<name>`, where the prefix is `brand.label_prefix` in
`engine.json` (`com.acme` until `engine init` runs;
`engine config labels` prints them).

## the default: run the CLI and show what it says

For `$ARGUMENTS` empty or `status`, and for `results`, `run`, `logs`, `doctor`,
`secrets`, `plugins`, run exactly

    engine $ARGUMENTS

through Bash and show the output verbatim, the `$ <command>` line included: the
screen teaches the CLI. Then, in one sentence, say what is `stale` or `not
loaded` (a `status` exit of 1 means at least one job is) and what the owner
could do about it: `/engine logs <job>` to read why, `/engine enable <job>` to
load it. The exit codes are the CLI's: 2 an unknown job, 1 a refusal or an
unhealthy status, 3 a `--live` refused.

`run <job>` without a flag is the dry form and needs no confirmation: a dry
run reads and changes nothing.

`results` answers "what did the engine produce since I last looked": per job,
the drafts and their gate verdicts, the listening pass, comment drafts waiting
for Alpha, the scorecard, the claims check, the corpus runs and memory
commits, the autopilot's sends and refusals, each with the file or command
that acts on it. The window is the session brief's marker, or `--since 36h`,
`7d`, an ISO stamp. This digest is the console's alone: since 2026-11-06 the
dashboard (`build_dashboard.py`, rebuilt by the cycle and the nightly claims
check) carries only the posts and what is live, with no run or job on the page.
Point the owner at `/alpha-queue` for the drafts `results` lists.

## acts that need a person: confirm first, once

`run <job> --live`, `enable <job>` and `disable <job>` change what runs on
this machine. Before each, ask one `AskUserQuestion` with the exact command
that will run and the options `yes` / `no`, and run it only on `yes`. The
console refuses `--live` for `autopilot`, `x-stream` and `nosleep` with exit 3
(the autopilot sends, the stream is billed per match, caffeinate is launchd's);
do not ask for those, say the refusal and stop. `secrets --set NAME` types a
value at a hidden prompt, which only a terminal has: say so and point to
`engine secrets --set NAME`.

## setup <job>: the questionnaire, asked here

`engine setup` asks on a terminal only; in chat the questions are asked
with `AskUserQuestion`, one question per screen, and the answers are handed to
the CLI as flags so it never prompts. Steps:

1. Read the current values first, one
   `engine config get <path>` per path below
   (the merged value: `engine.json` < `engine.local.json` < environment), and
   show them as a short table before the first question, with the schedule
   from `engine config get jobs` for the job.
2. Ask each question with `AskUserQuestion`: the header is the key, the
   question is the prompt below, the options carry the default from
   `engine.json` (the second column) and the current value when it differs,
   current first (pre-selected). A free-text answer is allowed where the
   value is a path, a list or a number. An answer of "keep" means no flag.
3. Run the CLI with every answer as a flag, dashes for underscores, booleans
   as `yes`/`no`, lists comma-separated:

       engine setup <job> --<key> <value> ...

   and show its output: the `key = value (flag)` lines, `wrote
   engine.local.json: ...`, the dry run, and the `not loaded; enable with`
   hint when the job is not loaded. A setup never loads a job; `enable` does.
   A key no job script reads yet is printed as `key = value (flag; recorded,
   not read by any script yet)` and is marked the same way in the table
   below: the file changes, the job does not, until its reader lands. An
   unknown key (`--draft` for `--drafts`) is refused with exit 1 before
   anything is written. A path answered with `~` is written as `__HOME__`.

The questions, with the shipped default and the config path:

| job | key | default | path | prompt |
|---|---|---|---|---|
| corpus | `root` | the placeholder `__HOME__/Documents/Strategy` (a fresh clone has no corpus; `setup corpus --root` writes the real one into `engine.local.json`) | `corpus.root` | the corpus root (checked for existence; a missing folder is refused) |
| corpus | `include` | `[]` (all) | `corpus.include` | folders under the root to read, comma-separated (recorded, not read by any script yet) |
| corpus | `exclude` | `[]` | `corpus.exclude` | folders under the root to skip (recorded, not read by any script yet) |
| corpus | `extra-roots` | `[]` | `corpus.extra_roots` | blind-spot roots added to the sweep (a folder outside the root, a repository) (recorded, not read by any script yet) |
| corpus | `max` | `8` | `corpus.max` | sources per run (options: 4, 8, 12) |
| corpus | `apply` | `yes` | `corpus.apply` | apply memory edits, or plan only |
| corpus | `budget-usd` | `10` | `corpus.budget_usd` | budget cap of the headless run, USD (options: 5, 10, 20) |
| cycle | `drafts` | `3` | `cycle.drafts` | drafts per run (options: 2, 3, 4) |
| cycle | `listen` | `yes` | `cycle.listen` | listening on (`no` makes cycle.sh pass `--no-listen`) |
| cycle | `max-per-term` | `12` | `cycle.max_per_term` | `listen.py --max` per term; above 12 is refused (options: 6, 8, 12) (recorded, not read by any script yet) |
| cycle | `linkedin` | `no` | `cycle.linkedin` | LinkedIn listening through Apify, paid; `yes` needs a reason (recorded, not read by any script yet) |
| cycle | `linkedin-reason` | none | (not written) | asked only when `linkedin` is `yes`; free text, passed as `--linkedin-reason "..."` |
| cycle | `budget-usd` | `20` | `cycle.budget_usd` | budget cap per cycle, USD (options: 10, 20, 30) |
| cycle | `editor` | `yes` | `cycle.weekday_flags.editor` | the weekly editor on Monday |
| cycle | `slots` | `yes` | `cycle.weekday_flags.slots` | the blog slots on Friday |
| cycle | `readout` | `yes` | `cycle.weekday_flags.readout` | the monthly readout on the first weekday |
| autopilot | `grace-days` | `2` | `autopilot.grace_days` | days a Ready row may be late and still go (options: 1, 2, 3) |
| autopilot | `commit` | `no` | `autopilot.commit` | run `autopilot.py commit` after `run` (recorded, not read by any script yet) |
| engagement | `window-days` | `3` | `engagement.window_days` | days after which an act's outcome is due (options: 2, 3, 5) |
| score | `x-metrics` | `yes` | `score.x_metrics` | `x_metrics.py` before `score.py` (recorded, not read by any script yet) |
| score | `demand` | `yes` | `score.demand` | `score.py --demand` (recorded, not read by any script yet) |
| score | `close-livetests` | `yes` | `score.close_livetests` | `livetests.py close` (recorded, not read by any script yet) |
| claims-check | `state-check` | `yes` | `claims_check.state_check` | `state_check.py` (recorded, not read by any script yet) |
| claims-check | `dashboard` | `yes` | `claims_check.dashboard` | `build_dashboard.py` (recorded, not read by any script yet) |
| x-stream | `rules-file` | `themes.json` | `x_stream.rules_file` | the themes file the rule plan is built from (recorded, not read by any script yet) |
| x-stream | `max-rules` | `10` | `x_stream.max_rules` | rules at most (options: 5, 10) (recorded, not read by any script yet) |

No setup has an `on` switch: a loaded job runs on its schedule, and only
`enable` / `disable` change that (the stream included: `x-stream` is loaded
by `enable x-stream` alone, never by a setup answer).

What a setup shows and never asks: the schedule (from `jobs[].calendar`; a
time changes in `engine.json`, then `enable`), the autopilot's channel rule
(from `streams.md`; it changes through a decision file under
`.atelier/memory/decisions/`, never here), the autopilot's timezone
(`autopilot.timezone`, `UTC` until
`engine config set autopilot.timezone <IANA zone>`
writes the brand's into `engine.local.json`; quiet hours, caps and the 09:00
slot are judged in it), `engagement.dry_run` (always `true` until a decision
file says otherwise), the score job's reads (`state/metrics-input/` count and
newest) and its baseline rule. `setup secrets` is `secrets`; `setup plugins`
is `plugins`; `setup nosleep` has nothing to set.

Before the corpus `include`/`exclude` questions, when the root is mounted,
run `engine corpus_sweep --root <root> --json`
and offer the top-level folders it lists as options, with their file counts.

## onboard-stream <slug>: the same shape

The onboarding is `scripts/onboard.py`, forwarded by `engine.py
onboard-stream`. Ask its questions here, then run the CLI with flags, never
interactively:

| key | default | prompt |
|---|---|---|
| `owner-confirmed` | `no` | has the stream's owner confirmed it (yes/no; never a name) |
| `corpus-root` | none | the stream's corpus root, a path |
| `channels` | none | the channels as `X @handle; LinkedIn slug` |
| `write-voice` | `no` | shape `voice.md` from the template (headings only; never overwrites one that exists) |
| `voice-from` | `template` | with `write-voice`: `template`, or the brief under `.atelier/memory/streams/<slug>/` named in the shaped `voice.md` as the source to fill from (nothing is copied) |
| `themes-file` | none | the stream's `themes.json`, repo-relative |

Then

    engine onboard-stream <slug> --owner-confirmed <yes|no> [--corpus-root PATH] [--channels "..."] [--write-voice] [--voice-from ...] [--themes-file PATH]

and show the output. The slug must already have a row in
`.atelier/memory/streams.md` (exit 2 otherwise, unknown slug or usage; exit 1
is a refused value, a corpus root or brief that does not exist): onboarding
never adds a stream to the registry, a decision file does, and it never
writes `streams.md` either: the owner and channels cells come back as the
exact `| ... |` line for a person to paste. `autopilot` stays `nothing`, and the
stream drafts nothing until its owner is confirmed and `voice.md` exists. When
the CLI says `onboard.py is not in this checkout yet`, say so and stop.

## headless: read, never write

With no person present (`claude -p`, a scheduled run, a subagent), only
`status`, `doctor`, `logs`, `secrets` (the check), `plugins` and `run <job>`
dry run. `setup`, `onboard-stream`, `enable`, `disable`, `run --live` and
`secrets --set` are a person's acts: do not run them, say which call was
skipped and why in one line (`skipped: engine enable cycle; loading a job is a
person's act, run /engine enable cycle in a session`). A headless run may read
the configuration and never changes it.

## never

No `launchctl` from here (`engine enable` goes through
`schedule/install.sh`, `disable` through its one seam). No
`autopilot.py post|links|run` without `--dry` (the PreToolUse hook refuses it
anyway). Nothing posts, nothing sets a row to `Published`, and nothing here
edits `engine.json`: `setup` writes `engine.local.json` only, `engine init`
is the one command that stamps the brand block, and a schedule change is an
edit to `engine.json` by hand followed by `/engine enable <job>`.
