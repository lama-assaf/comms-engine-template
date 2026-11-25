# The engine console: contract

_Written 2026-11-05 by the first builder of `PLAN-engine-console.md`, revised
the same day for the template's brand block. Every later builder codes
against this file, not against each other's work in progress. Where this file
and the plan disagree, this file wins for the build; change it here first.
`TEMPLATE-CONTRACT.md` at the repository root is the companion for the brand
block itself (its derivation table and the placeholder token)._

What exists: `engine.json` (one file: brand, jobs and parameters),
`scripts/config.py` (the read path), and the schedule scripts, `cycle.sh` and
`corpus_cycle_daily.sh` reading from it with the environment still winning.

Hard rules for every builder: stdlib only; never
`launchctl bootstrap|bootout|kickstart`, never `autopilot.py post|links|run`
without `--dry`, never post, never edit `.claude/settings.json`, never commit;
every existing command line keeps working; every setup question has a
`--<key>` flag and a default and is asked only when `sys.stdin.isatty()`; each
script opens with a docstring saying what it is, why, and its command lines.

## (a) `engine.json`

Path: `engine.json`, tracked. `engine.local.json` beside
it, gitignored, overrides `brand`, `params` and `streams` per machine (never
`jobs` or `path`). `__HOME__` and `__REPO__` in a string stand for the home
directory and this checkout; `config.py` expands them on read, `render.py`
substitutes them itself. `__ENV_PREFIX__` in an `env` key stands for
`brand.env_prefix`. No value here is a secret; `params.secrets` holds names.

```
_about, _brand_about, _jobs_about, _streams_about   prose, ignored by code
brand                object    the business this checkout serves; written by `engine init`
  slug               string    [a-z][a-z0-9-]{1,23}; the root stream; "acme" in a fresh clone
  name               string    the display name on records; "Acme" in a fresh clone
  label_prefix       string    launchd label prefix, no trailing dot; default "com.<slug>"
  env_prefix         string    environment prefix, ends with "_"; default "<SLUG>_"
  keychain_service   string    macOS keychain service; default "<slug>-comms"
path                 string    PATH for every launchd job; __HOME__ allowed
jobs                 list      the eight scheduled jobs
  name               string    unique; the launchd label is <label_prefix>.<name>, derived, never written here
  what               string    one line, shown by status and the TUI
  program            list      argv; a `/bin/zsh <script>.sh [args]` program runs through runjob.py
  calendar           list      launchd StartCalendarInterval dicts (Weekday, Hour, Minute); absent for keep_alive jobs
  keep_alive         bool      default false; KeepAlive + RunAtLoad
  throttle           int       ThrottleInterval seconds; default none
  env                object    extra EnvironmentVariables; default {}; no shipped job sets one
  log                string|null repo-relative file the script itself writes; launchd's own stdout is
                               ~/Library/Logs/<slug>-comms/<label>.log regardless (config.log_dir())
  optional           bool      default false; install.sh skips it without --with-optional
params               object    one block per job; `job` names the job the block belongs to, by name
  corpus             job corpus-cycle
    root             string    "__HOME__/Documents/Strategy", a placeholder; `setup corpus --root` writes the real one
    include          list      folders under root to read; [] means all        INERT
    exclude          list      folders under root to skip; []                   INERT
    extra_roots      list      blind-spot roots added to the sweep; []          INERT
    max              int       8   sources per /corpus-cycle run               corpus_cycle_daily.sh
    apply            bool      true  --apply (false: plan only)                 corpus_cycle_daily.sh
    budget_usd       number    10  --max-budget-usd of the headless run        corpus_cycle_daily.sh
  cycle              job social-engine
    drafts           int       3                                                cycle.sh
    budget_usd       number    20                                               cycle.sh
    listen           bool      true  false adds --no-listen                     cycle.sh
    max_per_term     int       12  listen.py --max; never above 12 (CLAUDE.md)  INERT
    linkedin         bool      false (paid; never on without a reason)          INERT
    voice_pass       bool      true                                             cycle.sh passes --no-voice when false (step 4b)
    weekday_flags    object    {editor: true, slots: true, readout: true}       cycle.sh honours each
  autopilot          job autopilot
    grace_days       int       2   autopilot.py GRACE_DAYS                      autopilot.py
    timezone         string    "UTC"  the IANA zone guardrails judge in         guardrails.py (set with config.py set; not a setup question)
    commit           bool      false  whether `autopilot.py commit` runs after `run`   INERT
  engagement         job engagement
    window_days      int       3   engage.py OUTCOME_WINDOW (72 h)              engage.py
    dry_run          bool      true  always, until a decision file says otherwise; shown, never asked
  score              job score
    on               bool      true   not asked by setup: a loaded job runs; enable/disable switch it
    x_metrics        bool      true   x_metrics.py before score.py              INERT
    demand           bool      true   score.py --demand                         INERT
    close_livetests  bool      true   livetests.py close                        INERT
  claims_check       job claims-check
    on               bool      true   not asked by setup (as score.on)
    state_check      bool      true                                             INERT
    dashboard        bool      true   build_dashboard.py                        INERT
  x_stream           job x-stream
    on               bool      false  not asked by setup: `enable x-stream` loads the optional job by name
    rules_file       string    "themes.json"              INERT
    max_rules        int       10                                               INERT
  site               (no job)
    post_url         string    "https://www.example.com/insights/{slug}"        repo.post_url, autopilot, gate_lint cta, announce_check
    webhook_url      string    "" (empty = no webhook)                          publish.py --webhook, with <env_prefix>WEBHOOK_SECRET
  secrets            (no job)
    required         list      ["TWITTERAPI_IO_API_KEY"]
    optional         list      ["APIFY_TOKEN", "LINKEDIN_ACCESS_TOKEN", "LINKEDIN_REFRESH_TOKEN",
                                "LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET", "LINKEDIN_ORG_ID", "LINKEDIN_MEMBER_ID"]
  plugins            (no job)
    marketplace      string    the atelier marketplace's git URL
    marketplace_name string    "atelier"
    names            list      ["atelier@atelier", "salon@atelier", "motion@atelier"]
    interactive_only list      ["motion@atelier"]                               switched off in the headless runs (`plugins --headless-settings`)
    scope            string    "project"
streams              object    per slug; seeded for the root stream only, keyed brand.slug ("acme"); `engine init` renames the key
  <slug>.corpus_root string    the stream's corpus root (the root stream: same as params.corpus.root)
  <slug>.themes_file string    repo-relative themes.json for the stream (the root stream: "themes.json")
```

The last column names the script that reads the key. **INERT** means no script
reads it yet (the score and claims-check programs are fixed strings in `jobs`,
the sweep takes no include/exclude, listen.py's `--max` and `--linkedin` come
from the /social-cycle command): `engine setup` writes it and prints
`(recorded, not read by any script yet)` beside it, `engine.INERT` is the set,
and a key leaves the set when its reader lands. The `job` key of a block is
metadata and is never overridden from the environment; no job
carries a sender marker (the old `<env_prefix>AUTOPILOT_JOB` retired with the posting guard's who-runs-it test).

Rules: a new job is a new `jobs` entry plus a `params` block whose `job` names
it (test `RealFile.test_engine_json_shape` checks the names agree). A new
parameter gets a default here, never only in a script. A per-machine value
(paths, budgets) goes to `engine.local.json` through `config.py set`; a
schedule change edits `engine.json` and is followed by `install.sh --only
<label>` (which `engine enable` wraps). The brand block is written by
`engine init` alone; nothing else in code spells a brand.

## (b) `scripts/config.py`

```python
import config                                   # from scripts/ on sys.path
config.cfg(path, default=None, env=None, base=ENGINE_JSON, local=LOCAL_JSON, home=None)
config.brand(base=..., local=...)        -> dict   {"slug","name","label_prefix","env_prefix","keychain_service"}
config.DEFAULT_BRAND, config.BRAND_KEYS, config.SLUG_RE
config.derive_brand(slug, name=None, label_prefix=None, env_prefix=None, keychain_service=None)
config.ENV_PREFIX                        -> str    module constant, from the file at import
config.label(name)                       -> str    "<label_prefix>.<name>"
config.job_name(label)                   -> str    the name a label stands for
config.jobs(base=ENGINE_JSON)            -> list   entries with `label` derived and __ENV_PREFIX__ resolved
config.job(name_or_label, base=...)      -> dict   raises ConfigError on an unknown job
config.labels(optional=None)             -> list   every label; optional=True/False filters
config.streams(...)                      -> dict   {slug: {...}}, overrides applied, placeholders expanded
config.params(section, ...)              -> dict   one job's block, overrides applied
config.set_local(path, value, local=LOCAL_JSON) -> dict  writes engine.local.json; refuses jobs/path
config.show(...)                         -> dict   the merged document, `_`-keys dropped
config.keys_for(path)                    -> list   "cycle.drafts" -> ["params","cycle","drafts"]
config.env_name(path)                    -> str    "cycle.budget_usd" -> "<ENV_PREFIX>CYCLE_BUDGET_USD"
config.env_name_for("REPO")              -> str    "<ENV_PREFIX>REPO" (also WEBHOOK_SECRET)
config.log_dir(home=None)                -> str    ~/Library/Logs/<slug>-comms
config.load(base, local)                 -> dict   the two files merged, no environment
config.ENGINE_JSON, config.LOCAL_JSON, config.ROOTS, config.LOCAL_FROZEN, config.ConfigError
```

- Dotted paths: a first segment that is not one of `brand`, `jobs`, `params`,
  `streams`, `path` is read under `params`; `cycle.drafts` and
  `params.cycle.drafts` are one key.
- Layering: `engine.json` < `engine.local.json` (dict-merge; `jobs` and `path`
  in the local file are ignored) < environment `<ENV_PREFIX><SECTION>_<KEY>`
  (dotted path upper-cased, `_` between segments, leading `params` dropped).
  The environment is typed by the value it overrides: bool from
  `1/true/yes/on`, int, float, list from a comma-separated string, dict from
  JSON; by the default when the file has no key. A dict read (`cfg("cycle")`,
  `streams()`) applies the environment to every leaf. `brand.*` and `jobs` are
  never read from the environment.
- `cfg` never raises for a missing key; it returns `default`. Tests pass
  `env={}` and temp `base`/`local` paths; `home=` pins `__HOME__`. A file with
  no `brand` block resolves to `DEFAULT_BRAND`, the placeholder.
- CLI (exit codes: 0, 1 missing key or refused write, 2 usage):
  `config.py get <path>` prints a scalar (bools as `true`/`false`, so a shell can
  test it), JSON for a list or dict; `config.py set <path> <value>` parses the
  value as JSON when it is one, else a string, writes `engine.local.json` and
  prints `<path> = <value>  (engine.local.json)`;
  `config.py show` prints the merged document as JSON; `config.py brand [key]`,
  `env-name <path>`, `label <job>`, `labels [--optional|--required]`,
  `log-dir` print the derivations.
- Shell callers ask the prefix once and read the variable indirectly, the
  pattern in `cycle.sh` and `corpus_cycle_daily.sh`:
  `PREFIX="$(engine config brand env_prefix)"`,
  `cfg() { engine config get "$1" 2>/dev/null || echo "$2"; }`,
  then `v="${PREFIX}CYCLE_BUDGET_USD"; "${(P)v:-$(cfg cycle.budget_usd 20)}"`,
  so the variable wins and a missing config.py falls back to the shipped value.

## (c) `scripts/engine.py` (Core builder)

One stdlib CLI; the only module that calls `launchctl`, `render.py`,
`install.sh`, `runjob.py` and the dry runs. The TUI and `/engine` call its
functions (import) or its CLI; neither calls `launchctl` itself.

Module shape the other builders may rely on:

```python
import engine
engine.run_launchctl(args: list[str], timeout=20) -> subprocess.CompletedProcess
    # the ONE function that spawns launchctl; tests monkeypatch it:
    # engine.run_launchctl = lambda args, timeout=20: FakeProc(...)
    # bootstrap/bootout/kickstart NEVER run in a test; enable/disable in tests assert the args only
engine.status(now=None) -> dict      {"jobs": jobs_status.rows(), "secrets": [{"name","present"}],
                                      "plugins": [{"name","installed"}], "last_cycle": {"at","budget_usd","exit"}}
engine.run(label, live=False, timeout=None) -> int   exit code of the job (or of its dry-run form)
engine.enable(label) -> int;  engine.disable(label) -> int
engine.logs(label, n=40) -> list[str]
engine.doctor() -> list[dict]        [{"check": "<command line>", "ok": bool, "seconds": float, "tail": "<last line>"}]
engine.setup(job, answers: dict, interactive=None) -> dict   the block written (interactive defaults to sys.stdin.isatty())
engine.secrets_status() -> list[dict];  engine.plugins_status() -> list[dict]
engine.init(slug, name, label_prefix=None, env_prefix=None, keychain_service=None,
            engine_json=None, streams_md=None, local=None) -> dict   the brand block written, the cells renamed
engine.init_lines(result) -> list[str]   the printed lines; engine.STREAMS_MD is the file init renames cells in
engine.JOB_NAMES                      the console's short names (corpus, cycle, autopilot, engagement, score,
                                      claims-check, x-stream, nosleep) -> job names
engine.SHORT                          short name -> label, built at import from config.label; every subcommand takes either form
engine.label_for(x); engine.short_for(label)
engine.main(argv=None) -> int
```

Subcommands, delegation, stdout, exit codes:

| subcommand | delegates to | stdout | exit |
|---|---|---|---|
| `init --slug S --name N [--label-prefix P] [--env-prefix E] [--keychain-service K]` | `config.derive_brand`, a rewrite of `engine.json`'s `brand` and `streams` key, `engine._rename_cells` on `.atelier/memory/streams.md` (table cells equal to the old slug or name; prose untouched) | the block written, the cells renamed, then the first commands (`doctor`, `setup corpus`, `setup cycle`, `secrets`, `enable cycle`); `nothing to write` when idempotent | 0; 1 a refused slug (outside `[a-z][a-z0-9-]{1,23}`), nothing written |
| `status [--json]` | `jobs_status.rows()`; `secrets.py` backends (`--check` logic, names from `params.secrets.required`, never values); `claude plugin list --json` (missing `claude` = "unknown", not an error); `state/runs.json` / `state/schedule.log` for the last cycle | the `jobs_status.py` table, then three lines: `secrets   1/1 present (TWITTERAPI_IO_API_KEY)`, `plugins   3/3 installed (atelier@atelier, salon@atelier, motion@atelier)`, `last cycle 2026-11-05T07:15Z  budget 20 USD  exit 0`. `--json` prints the `status()` dict | 0; 1 when any job is `stale` or `not loaded` (nosleep and optional jobs excluded) |
| `run <job> [--dry\|--live]` | `runjob.py <job>` for `--live`; for `--dry` (the default) the job's dry form: corpus `corpus_sweep.py --root <corpus.root> --only-todo` (its exit 1, sources waiting, is printed as `pending work found` and returned as 0; exit 2 is the root not found); cycle `plan_queries.py --dry-run` and `listen.py --dry-run`; autopilot `autopilot.py run --dry`; engagement `engage.py due`; score `score.py --dry-run` + `metrics.py --dry-run`; claims-check `claims_check.py --dry-run`; x-stream `x_stream.py rules`; nosleep prints `nothing to dry-run` | first line `$ <exact command>`, then the job's output streamed | the job's exit code; 2 unknown job; `--live` on autopilot/x-stream/nosleep refused with 3 (the PreToolUse hook would refuse anyway; say so in one line) |
| `enable <job>` | `schedule/install.sh --only <label>` (which renders and bootstraps, the optional x-stream included when named); never `launchctl bootstrap` directly. One `launchctl list` read first: a calendar job with a live PID is refused (install.sh would boot it out mid-run). When the shell lacks `CLAUDE_CONFIG_DIR` and the installed plist has one, install.sh runs with it, so the job keeps its login | `$ schedule/install.sh --only <label>  (CLAUDE_CONFIG_DIR=<dir>` or `unset ...)` then install.sh's lines (`loaded    <label>`) | install.sh's exit; 1 job running; 2 unknown job |
| `disable <job>` | `run_launchctl(["bootout", f"gui/{uid}/{label}"])`; the plist stays under `~/Library/LaunchAgents` | `$ launchctl bootout gui/<uid>/<label>` then `booted out <label>` or `not loaded <label>` | 0 either way; 2 unknown job |
| `logs <job> [-n N]` | the job's `log` in `engine.json` (repo-relative) and `<config.log_dir()>/<label>.log`; both tails, the repo one first | `== <path> (last N) ==` headers, then lines; N default 40 | 0; 1 when neither file exists |
| `doctor` | every command in CLAUDE.md "How work is verified", in that order, plus `config.py show` and `secrets.py --check <required...>`; each with a timeout (default 300 s; the suite 600 s) and stdin closed; `engine.is_informational(cmd)` names the checks whose exit 1 is an answer (`guardrails.py`, `x_stream.py rules`, `secrets.py --check`): they stay `ok` with the last line shown | one line per check: `ok    3.2s  python3 -m unittest discover plugins/comms-engine/tests` / `FAIL  0.4s  <cmd>  -- <last stderr line>` ; last line `doctor: N ok, M failed` | 0 all ok; 1 any failed |
| `setup <job> [--<key> <value>]...` | `config.set_local()` for every answer; ends with the job's `run --dry` | each question as `key [default]: ` on a terminal; headless prints `key = value (default|flag)`, with `; recorded, not read by any script yet` inside the parentheses for an INERT key; then `wrote engine.local.json: <keys>`; then the dry run. A path key (`corpus.root`, `x_stream.rules_file`) is `~`-expanded and written with the home prefix as `__HOME__` | 0; 1 a value refused (non-existent corpus root, max_per_term > 12, linkedin true without `--linkedin-reason`, an unknown key: nothing is written); 2 unknown job |
| `onboard-stream <slug> [--flags]` | `scripts/onboard.py` (onboarding builder); engine only forwards argv | onboard.py's | onboard.py's |
| `secrets [--set NAME]` | `secrets.py --check <required + optional>`; `--set` forwards to `secrets.py --set NAME` (terminal only) | `NAME: present (keychain)` / `NAME: MISSING  -> engine secrets --set NAME` per name; required first | 0 all required present; 1 otherwise |
| `plugins [--prepare \| --headless-settings]` | `claude plugin list --json` (a name counts when it is enabled, carries no load error and is installed for this checkout or the machine; `claude` missing = every name `unknown`) and `params.plugins`; `--headless-settings` prints the `--settings` JSON that switches off `plugins.interactive_only`, exit 0; `--prepare` writes `env.ATELIER_LOG_DIR` (`<log-dir>/atelier`) into the gitignored `.claude/settings.local.json`, keeping every other key, exit 0 | one line per name: `atelier@atelier: installed` / `salon@atelier: not installed  -> claude plugin install salon@atelier --scope project`, after `marketplace: <url>` | 0 all installed; 1 otherwise; 0 with a note when `claude` is absent |

Setup questions (every one a `--<key>` flag with a default; asked only when
`sys.stdin.isatty()` and the flag was not given; the authoritative list is
`engine.QUESTIONS`, mirrored in `commands/engine.md` and checked by
`tests/test_engine_command.py`):

- `corpus`: `--root` (exists check), `--include`, `--exclude` (shown against
  `corpus_sweep.py --json` folder list with counts and stage when the root is
  mounted), `--extra-roots`, `--max`, `--apply`, `--budget-usd`.
- `cycle`: `--drafts`, `--listen`, `--max-per-term`, `--linkedin`
  (`--linkedin-reason` with it), `--budget-usd`, `--editor`, `--slots`,
  `--readout`. The time is shown from `jobs[].calendar`, not asked: a schedule
  changes in `engine.json`.
- `autopilot`: `--grace-days`, `--commit`; the channel rule is printed from
  `memory.load_streams()[brand.slug]["autopilot"]` with the sentence "to
  change it, add a decision under .atelier/memory/decisions/ and edit
  streams.md"; the timezone is shown from `autopilot.timezone` and set with
  `config.py set`.
- `engagement`: `--window-days` (`dry_run` is shown, not asked).
- `score` (the reads under `state/metrics-input/` and the baseline rule are
  shown first), `claims-check`, `x-stream`: their sub-flags as one table each;
  no `on` flag: a loaded job runs, `enable`/`disable` switch it.
- `secrets`, `plugins`: the tables above; `setup secrets` is `secrets`.

A setup never loads a job; it ends `not loaded; enable with: engine enable <job>`
when the label is not in `launchctl list`.

Tests (`tests/test_engine.py`, `tests/test_brand.py`): monkeypatch
`run_launchctl` and `subprocess.run` through one seam (`engine.run_cmd`) so no
test spawns a job; assert argv for enable/disable/run; `status()` shape;
`doctor()` over a fake command list; `setup` headless with flags writes only
the keys given, into a temp local file (`config.LOCAL_JSON` patched); `--live`
refused for the three labels; `init` on temp copies of `engine.json` and
`streams.md`.

## (d) `scripts/engine_tui.py` (TUI builder)

`curses` from the standard library, `curses.wrapper(main)`, no dependency.
Imports `engine` and calls its functions; never `launchctl`, never
`subprocess` of its own. A result holder, stdin flushed after the wrapper
returns, `KeyboardInterrupt` and `q` as quit.

Panes:

- Left (fixed width 34): sections `jobs` (one row per `engine.json` job:
  short name, state from `status()` as `ok`/`stale`/`off`, last run hh:mm),
  `streams` (slugs from `memory.streams()`, owner state), `secrets`
  (present/missing count), `plugins` (installed count). `j`/`k` or arrows move;
  `tab` jumps section.
- Right: the selected item's detail: `what`, calendar as `Mon-Fri 07:15`,
  loaded or not, the params block (from `config.params()`), then the last 15
  log lines from `engine.logs()`.
- Bottom line: the exact command the last action ran (`$ ...`), then its exit;
  the screen teaches the CLI.

Keys: `r` run (dry) · `R` run (live; confirm `y`; refused labels show the refusal) ·
`e` enable (confirm `y`) · `d` disable (confirm `y`) · `s` setup (suspends curses, runs `engine.setup(job,
{}, interactive=True)` on the terminal, resumes) · `l` logs (the job's last 200
lines in the right pane, tail kept; `l` again returns to the detail) · `o` onboard a stream (prompts the slug, suspends curses, calls
`engine.main(["onboard-stream", slug])`) · `?` help · `g` refresh · `q` quit.
Every action re-reads `status()` afterwards. Headless (no tty): prints
`engine_tui: needs a terminal; use engine status` and exits 2.

Tests (`tests/test_engine_tui.py`): the pane model only (rows built from a fake
`status()`), no curses screen; the key map table is a dict the test reads.

## (e) `/engine` (command builder)

`commands/engine.md` (symlinked into `.claude/commands/`; frontmatter
`description`, `argument-hint: [status|run <job> [--dry]|enable <job>|disable <job>|logs <job>|doctor|setup <job>|onboard-stream <slug>|secrets|plugins]`)
plus `skills/engine-console/SKILL.md`.

- No argument or `status`: run `engine status`
  and show the table verbatim; one sentence on anything `stale` or `not loaded`.
- `setup <job>`: read the job's questions from (c); ask each with
  `AskUserQuestion` (default shown, the current value from `config.py get`
  pre-selected), then run `engine setup <job> --<key> <value>...` with every
  answer as a flag (so the questionnaire never prompts on the terminal), then
  show the dry run.
- `run`, `logs`, `doctor`, `secrets`, `plugins`: run the CLI, show the output.
  `run --live` and `enable`/`disable` ask one `AskUserQuestion` confirmation
  first; `--live` on autopilot is refused as in (c).
- Headless (`claude -p`, no person): the command reads (`status`, `doctor`,
  `logs`) and never writes (`setup`, `enable`, `disable`, `run --live`,
  `secrets --set`); it says which call it skipped and why.
- The session brief carries one line from `engine.status_rows()` (the count
  of stale/not-loaded jobs), behind a try/except so a missing engine never
  breaks the brief.
- The setup table in the command file must match `engine.QUESTIONS` plus
  `engine.EXTRA_FLAGS` (job, key and path); `tests/test_engine_command.py`
  checks it. A new question lands in both files in one change.

## (f) `onboard-stream` (onboarding builder)

`scripts/onboard.py <slug> [--owner-confirmed yes|no] [--corpus-root PATH]
[--channels "X @handle; LinkedIn slug"] [--voice-from BRIEF|template]
[--write-voice] [--themes-file PATH] [--dry-run]`, over the
`.atelier/memory/streams/<slug>/` directories and `streams.md`. Writes:
`streams.<slug>.corpus_root` and `.themes_file` into `engine.local.json`
through `config.set_local`; with `--write-voice`,
`.atelier/memory/streams/<slug>/voice.md` shaped from
`.atelier/memory/templates/voice.md` (headings only, never over an existing
file); `--voice-from BRIEF` names the brief in the shaped `voice.md` as the
source to fill from and copies nothing (memory content arrives through
`/corpus-update --apply --stream <slug>` only). Onboarding never writes
`streams.md`: the registry row with its owner cell set to `confirmed` (on an
explicit `--owner-confirmed yes`; never a name) and its channels cell is
printed as the exact `| ... |` line for a person's edit, and `autopilot` stays
`nothing`. Ends with `memory.py --stream <slug>` and a gate check on a fixture
as the stream. Exit 0; 1 a refused value (a corpus root or a brief that does
not exist); 2 an unknown slug (onboarding never adds a stream to the registry;
that is a decision file) or a usage error. `memory.may_draft(slug)` stays
false until owner confirmed and `voice.md` exists, so a stream onboarded today
drafts nothing.

## File ownership

| files | builder |
|---|---|
| `engine.json`, `scripts/config.py`, `tests/test_config.py`, `CONSOLE-CONTRACT.md`, the schedule pointers | done (step 1) |
| `scripts/engine.py`, `tests/test_engine.py` | Core |
| `scripts/engine_tui.py`, `tests/test_engine_tui.py` | TUI |
| `commands/engine.md`, `skills/engine-console/SKILL.md`, the one line in `scripts/session_brief.py` | command |
| `scripts/onboard.py`, `.atelier/memory/templates/voice.md`, `tests/test_onboard.py` | onboarding |
| the brand block across `engine.json`, `config.py`, `engine init`, the hook, the shell scripts, `tests/test_brand.py` | brand (see `TEMPLATE-CONTRACT.md`) |

Nobody touches another builder's files. A need in another builder's file is
written into this contract as a request, and the owner makes the change.
`engine.json` gains a key only through this file's table (a): add the row, add
the default, then use it.

## Open

- `autopilot.timezone` is set with `config.py set`, not asked by `setup
  autopilot`; adding the question means one row in `engine.QUESTIONS` and one
  in the command file's table, together.
- The per-brand gate rules (`gate_lint.STATUS_WORDS`, `CLEARED_HEDGES`;
  `announce_check.STATUS_FLAGS`, `CLEARED_PHRASES`, `VOICE_FLAGS`) have no home
  outside code; a `params` block or a memory file could carry them so a brand
  fills them without editing a script.
- `engine init` does not yet write `voice.md` from the template;
  `onboard.write_voice` already shapes one for a stream and init should call
  it once for the root.
