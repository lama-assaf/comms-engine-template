# Template contract: the brand block and who owns what

_Written 2026-11-05 by the brand-block builder (step 1 of the template build), for
the four builders that followed in parallel, and brought up to date the same
night by the fix step after two reviews. It says what the brand block is, what
every file may derive from it, which files each builder owned, what the build
changed and why, and what it deliberately left undone (section 8)._

_Brought up to date on 2026-11-13 for `PLAN-autonomy.md`: sections 1, 3, 4 and
8 are corrected where the new shape replaced them, and section 10 says what
that plan added, which API it exposes and what it left undone._

## 1. The brand block

`brand.json` at the repository root carries the `brand` block of this
project (`slug` and `name`; the other three follow the slug unless named). It
is the only place the business this checkout serves is named; nothing else in
code spells a brand. `plugins/comms-engine/engine.json` keeps the placeholder
block as a shipped default, and `config.brand()` reads the merged result:

```json
"brand": {
  "slug": "acme",
  "name": "Acme",
  "label_prefix": "com.acme",
  "env_prefix": "ACME_",
  "keychain_service": "acme-comms"
}
```

**The placeholder token.** A fresh clone carries `acme` / `Acme` everywhere
the brand appears: the block above, `brand.json` and its `streams` key, the
`streams` key in engine.json, the first row of `.atelier/memory/streams.md`
(slug cell `acme`, name cell `Acme`), and the examples in docstrings. Use exactly these two spellings
(`acme` where a slug goes, `Acme` where a display name goes) in any template
file you write, so that `engine init` can rename them. Derived forms are
`com.acme` (labels), `ACME_` (environment), `acme-comms` (keychain service and
the launchd log directory `~/Library/Logs/acme-comms`). Never write
another brand's slug, name, label prefix, environment prefix or keychain
service anywhere: `tests/test_fresh_clone.py` greps the tree for them.

**`engine init`** is the guided setup. It writes `brand.json` and never
edits engine.json, which is shipped defaults:

```
engine init                      # a terminal is asked the few questions
engine init --slug <slug> --name "<Name>" \
    [--narrator ..] [--x @handle] [--linkedin ..] [--label-prefix com.x] [--env-prefix X] [--keychain-service x-comms]
engine init --from <brand.json>  # no questions
```

It writes the block (the three optional fields follow the slug when omitted),
renames the root stream's key and every pair rule that points at it, renders
the three tables of `.atelier/memory/streams.md` from the file
(`brandfile.apply`; prose is left alone), and prints the first commands
(`doctor`, `setup corpus`, `setup cycle`, `secrets`, `enable cycle`). A
checkout with a registry kept by hand and no `brand.json` gets one imported
from it, cell for cell (`brandfile.from_streams_md`). It is idempotent (same
flags twice: "nothing to write") and re-stampable (new flags rename from what
the files hold now). A slug outside `[a-z][a-z0-9-]{1,23}` is refused and
nothing is written.

## 2. Derivations

| what | derived as | read through |
|---|---|---|
| launchd label of a job | `<label_prefix>.<job name>` | `config.label(name)`, `config.jobs()[i]["label"]`, `config.py label <job>`, `config.py labels [--optional|--required]` |
| job name from a label | strip `<label_prefix>.` | `config.job_name(label)` |
| environment override of a parameter | `<env_prefix><SECTION>_<KEY>` (leading `params.` dropped) | `config.env_name("cycle.budget_usd")`, `config.py env-name <path>` |
| the repo marker launchd sets | `<env_prefix>REPO` | `config.env_name_for("REPO")`; render.py and runjob.py set it |
| the webhook secret | `<env_prefix>WEBHOOK_SECRET` | `publish.py --webhook` |
| keychain service | `brand.keychain_service` | `secrets.KEYCHAIN_SERVICE`, `config.py brand keychain_service` |
| root stream (memory at `.atelier/memory/`) | `brand.slug` | `memory.DEFAULT_STREAM`; `secrets.ROOT_STREAM` (its secrets keep bare names) |
| root stream's display name on records | `brand.name` | `memory.DEFAULT_STREAM_NAME`; every `--stream` default, every `"stream":` record field, `autopilot.STREAM_NAME`, `gate_lint.BRAND_NAME`, `x_stream.BRAND_NAME` |
| launchd stdout directory | `~/Library/Logs/<slug>-comms` | `config.log_dir()`, `config.py log-dir`, `engine.LAUNCHD_LOGS` |
| the X stream's rule tags | `<slug>:mentions`, `<slug>:own`, `<slug>:partners`, `<slug>:hashtags`, `<slug>:theme:<Tag>` | `x_stream.PREFIX` |
| the xurl OAuth app name | `brand.slug` | `autopilot.X_APP` |
| the dashboard's brand, own handle, site host | `brand.name`, handles.md own channels, `params.site.post_url` | `build_dashboard.brand()`, the `__BRAND_NAME__` / `__OWN_X__` tokens of `dashboard/template.html` and `STATE.brand` |
| the plugin marketplace | `params.plugins.marketplace`, empty in the template | `engine plugins`, `install.sh --check` |
| a Blog row's URL on the brand's site | `params.site.post_url` with `{slug}` | `repo.post_url(slug)`, `autopilot.SITE_POST_URL`, gate `lint: cta` |
| the capability-sentence subject in the gate | `\b(?:<brand.name>|we)\s+...`, the verbs from the stream's `gate-rules.json` | `gate_lint.capability_for(slug)`, `gate_lint.capability_pattern(name, verbs)` |
| the shell scripts' prefix | asked once: `engine config brand env_prefix` | `cycle.sh`, `corpus_cycle_daily.sh` (`v="${PREFIX}CYCLE_BUDGET_USD"; "${(P)v:-...}"`) |

`config.brand()` merges `config.DEFAULT_BRAND` (the placeholder) under
engine.json's block under brand.json's under engine.local.json's; a file with no block resolves
to the placeholder, which is what the test fixtures rely on. `env_prefix` is
stripped, upper-cased and normalised to end with `_` and must then match
`config.ENV_PREFIX_RE` (`^[A-Z][A-Z0-9_]*_$`, a shell identifier prefix);
`label_prefix` loses a trailing dot and must match `config.LABEL_PREFIX_RE`
(reverse-DNS, lower-case). Both `brand()` and `derive_brand()` refuse a value
outside those with `ConfigError`, so `init --env-prefix my-brand` is refused
rather than written. The brand is never read from the environment (`brand.*`
and `jobs` are the two sections `_env_applies` refuses). `config.env_name(path,
base, local)` names the variable for the files given, so a read against
another engine.json (a fixture) names that file's variables.

## 3. engine.json's shape after this step

- `brand` (above) with a `_brand_about` line.
- `jobs[]`: every job has a **`name`** and no `label`; the label is derived.
  No shipped job sets an `env` (the autopilot marker retired); a job's `env` keys may still
  carry `__ENV_PREFIX__`, which `config.jobs()` resolves.
- `params.<section>.job` names the job **by name** (`"corpus-cycle"`, not a
  label). `config.py`, `engine.py`, `jobs_status.py` and `engine_tui.py` all
  key on names; `engine.py`'s console aliases (`corpus`, `cycle`, ...) are in
  `engine.JOB_NAMES` and `engine.SHORT` (alias -> label, built at import).
- `params.corpus.root` is the placeholder `__HOME__/Documents/Strategy`
  (`setup corpus --root` writes the real one into engine.local.json).
- New `params.site`: `post_url` (`https://www.example.com/insights/{slug}`),
  `webhook_url` (empty = no webhook). A brand's site
  URL goes here.
- New `params.autopilot.timezone` (`UTC`): the IANA zone `guardrails.TZ` judges
  quiet hours, caps and the 09:00 slot in. Set with
  `config.py set autopilot.timezone <zone>`; it is not a `setup autopilot`
  question yet (see "Not done").
- `streams` is keyed `acme` in engine.json and stays so; the root stream's
  key follows `brand.json`'s slug when the files are merged.
- Since 2026-11-13 the file is shipped defaults nobody edits, and it also
  carries `params.workflows`, `params.chains`, `params.plugins.roles`,
  `params.reactions`, `params.channels.reactions_signoff` and
  `params.motion.generate_signoff` (section 10). The file is formatted by
  hand: change it with a textual edit, never by dumping the whole document.
- `_about` lines are prose and may be edited by builder D if they wish; keep
  them one line each.

## 4. The API the other builders can rely on

```python
import config
config.brand()                  # {"slug","name","label_prefix","env_prefix","keychain_service"}
config.DEFAULT_BRAND, config.BRAND_KEYS, config.SLUG_RE
config.derive_brand(slug, name=None, label_prefix=None, env_prefix=None, keychain_service=None)
config.ENV_PREFIX               # module constant, from the file at import
config.env_name(path); config.env_name_for("REPO")
config.label(name); config.job_name(label); config.jobs(); config.job(name_or_label); config.labels(optional=None)
config.log_dir(home=None)
config.cfg(path, default)       # unchanged; `brand.*` readable, never env-overridden

import memory
memory.DEFAULT_STREAM, memory.DEFAULT_STREAM_NAME

import repo
repo.post_url(slug)             # engine.json site.post_url with the slug filled

import engine
engine.JOB_NAMES, engine.SHORT, engine.label_for(x), engine.short_for(label)
engine.init(slug=None, name=None, label_prefix=None, env_prefix=None, keychain_service=None, engine_json=None,
            streams_md=None, local=None, handles_md=None, claims_md=None, from_file=None, narrator=None, x=None, linkedin=None)
engine.init_lines(result)       # the printed lines; engine.STREAMS_MD is the file init renders the tables of

guard_posting.verdict(command, env=None), guard_posting.COMPOSIO_READ_SLUGS   # no MARKER: the hook does not ask who runs a command
secrets.KEYCHAIN_SERVICE, secrets.ROOT_STREAM
x_stream.PREFIX, x_stream.BRAND_NAME, x_stream.own_x_handle(), x_stream.about_pattern()   # built on demand, never at import
gate_lint.BRAND_NAME, gate_lint.capability_pattern(name, verbs=None), gate_lint.capability_for(slug), gate_lint.rules(slug)
engine.doctor_checks(slug), engine.is_informational(cmd)

# the suite
fixture_memory.FixtureMemory / FixtureMemoryCase / install()   # fixture memory AND a fixture engine.json with the placeholder brand
fixture_memory.LIVE_ENGINE_JSON, fixture_memory.BRAND_BOUND     # the tracked file; the constants the fixture rebinds
```

CLI: `config.py brand [key] | env-name <path> | label <job> | labels [--optional|--required] | log-dir`,
`engine init ...`, `state_check.py --stamp [NAME]` (NAME defaults to the
brand's name). `schedule/install.sh` takes labels from `config.py labels`
and the log directory from `config.py log-dir`. `runjob.py` accepts a job name or a label.

Rules that bind what the brand block does **not** do:

- The gate's status rules and the announcement checker's **ship empty**, and
  since 2026-11-13 they are data: `.atelier/memory/gate-rules.json`
  (`status_words`, `cleared_hedges`, `capability_verbs`, `house_style`,
  `announce`), read through `memory.load_gate_rules(stream)`. The module
  constants (`gate_lint.STATUS_WORDS`, `CLEARED_HEDGES`,
  `announce_check.STATUS_FLAGS`, `CLEARED_PHRASES`, `VOICE_FLAGS`) are gone.
  `lint: status words` passes every item until a brand writes its rules from
  its status.md; a rules file that does not read blocks.
- `x_stream.own_x_handle()` reads the brand's own X handle from
  `handles.md`'s `own channels` table (platform `X`); without a row it raises
  `RuleError` and the `own` and `mentions` rules are not built. Builder A's
  `handles.md` template needs that table with its columns (`brand`,
  `platform`, `handle`, `status`, `themes`, `last_verified`) even when the
  handle cell is blank.
- `inventory.TABLES` matches the `cleared partners` heading as a **prefix**
  (`memory.table_in(..., prefix=True)`), so A's template heading may be plain
  `## cleared partners` or qualified `## cleared partners (public via Acme's own releases)`.

## 5. File ownership, as built

**Brand-block builder (step 1):** `Tooling/social-engine/engine.json`;
`Tooling/social-engine/scripts/*.py` (brand constants, defaults, docstrings,
the `site` and timezone parameters); `scripts/cycle.sh`;
`schedule/{render.py,runjob.py,install.sh}`; `claude/hooks/guard_posting.py`;
`Tooling/deck-reader/scripts/{corpus_cycle_daily.sh,corpus_sweep.py}`;
`Tooling/social-engine/install.sh`; `state/README.md`; `tests/test_brand.py`;
this file.

**Builder A, memory templates and onboarding:** everything under
`.atelier/memory/`, `scripts/onboard.py` (questionnaire and prose),
`Tooling/social-engine/themes.json` and `streams/*/themes.json`.

**Builder B, tests and fixtures:** everything under `Tooling/social-engine/tests/`
except `test_brand.py`, plus `tests/fixtures/`.

**Builder C, prose:** `Tooling/social-engine/claude/**` except the hook,
`Tooling/deck-reader/commands/**`, the deck reader's README, SKILL and
references, `.claude/` symlinks and settings.

**Builder D, docs:** `README.md`, `docs/`, `CLAUDE.md`, the engine's own prose
files (`Tooling/social-engine/README.md`, `PLAN*.md`, `ORCHESTRATION.md`,
`CONSOLE-CONTRACT.md`, `research-store/README.md`, `Tooling/notion-sync/README.md`,
`Tooling/deck-reader/README.md`, `state/metrics-input/README.md`).

**The fix step (after the two reviews), which took the unassigned files:**
`dashboard/template.html` and `scripts/build_dashboard.py` (the brand, own
handle and site host come from the build; the schedule from engine.json;
`dashboard/index.html` deleted and gitignored), `DASHBOARD_URL` (empty),
`publish-targets.example.json` (ids empty, theme maps as a `_shape`;
`publish-targets.json` gitignored, `autopilot.py` stops while the ids are
empty), `mcp/push-servers.json` (the site entry reads `params.site`),
`research-store/docker-compose.yml` (`comms-research-store`),
`Tooling/notion-sync/sync.py` (root by position, `--dry-run` without
`config.json` exits 0 with "not configured", the brand's service),
`desk/{package.json,package-lock.json,app/layout.tsx,lib/paths.ts,db/schema.ts,lib/desk.ts,app/queue/page.tsx}`
(the desk reads `brand.name` from engine.json per request; package
`comms-desk`), `.mcp.json` (the `notion` HTTP server, tracked), and the
plugin marketplace made a parameter (`params.plugins.marketplace`, empty).

## 6. What the build changed outside the brand block, and why

- `config.py`: `env_name(path, base, local)` reads the prefix from the files
  named, so the suite's fixture engine.json answers for the placeholder prefix
  whatever brand the checkout carries; `brand()` and `derive_brand()` validate
  `env_prefix` and `label_prefix` (section 2).
- `engine.py`: `doctor` reports `secrets.py --check` and `x_stream.py rules`
  the way it reports `guardrails.py` (exit 1 is an answer, shown on the `ok`
  line as `missing: NAME, ...`), so a fresh clone with no keys is green;
  `doctor_checks(slug)` builds the list; `init` also renames the brand cells
  of handles.md's own channels and the example claim id `C-<slug>-0`.
- `x_stream.py`: `RuleError` is defined before its first use and the brand
  pattern is built on demand (`about_pattern()`), so `import x_stream` works
  on a checkout whose handles.md has no own X handle; `rules` without a key
  prints the desired rules and exits 1, and any `RuleError` is one line on
  stderr, never a traceback.
- `gate_lint.py`: with nothing to lint it prints one line naming the empty
  queue and whether the denylist is present; `capability_pattern(name)`.
- `guard_posting.py`: judges each `;`, `&&`, `||`, `|` and newline segment on
  its own, accepts a quoted subcommand, refuses only a raw platform write
  that bypasses `channels.send()` (xurl writes, curl/wget/http writes to the
  LinkedIn and X APIs, `publish.py ... --webhook`, `composio execute` of a
  channel-toolkit slug outside `COMPOSIO_READ_SLUGS`, a `composio proxy` that
  is not a GET to a channel host, `composio run`); it reads no engine.json and
  has no job marker. The `python -c` limit is documented in its docstring.
- `cycle.sh`, `corpus_cycle_daily.sh`: when `config.py` cannot run, the prefix
  is read from engine.json with a one-line JSON read; the placeholder prefix
  is the last resort.
- `tests/fixture_memory.py`: a fixture installs a fixture engine.json (the
  tracked one with the placeholder brand and `streams` key) beside the fixture
  memory and rebinds every import-time brand constant it knows
  (`BRAND_BOUND`), so the whole suite runs on the placeholder brand after
  `engine init` has stamped a real one. `test_engine`, `test_engine_tui`,
  `test_schedule` and `test_session_brief` install it per module;
  `test_fresh_clone` reads the clone's own engine.json for the brand it
  expects; `test_brand`'s placeholder check skips once `init` has run.
- `.atelier/memory/streams.md`: the registry row, the guardrails row and the
  pair-rule rows were renamed to the placeholder by `engine._rename_cells`,
  the function `init` uses; A reshaped the rest.
- `state/`: every record removed; `README.md` added.
- Example hashtags, the second example stream and an invented person's name
  in docstrings and tests now use the fixture register (`#ExampleTheme`,
  `beta` / `Beta`, `Firstname Lastname`).

## 7. What a grep over the template finds

`tests/test_fresh_clone.py` copies the tree the way a clone arrives and greps
it: no machine home path may appear anywhere, none of the terms in the
maintainer's gitignored `.leak-terms` (the template ships no terms; that check
skips without the file, and a failure names a line of it, never a term), and no file that names another brand or the runtime the engine came from
(`ALLOWED` is empty since 2026-11-13; `test_brand.py` builds the words it
forbids from pieces, so it spells none of them). The template names no brand
but the placeholder. The code that read that earlier runtime's files
is gone: `scripts/score.py` reads the engine's own ledgers and
queue under `state/`, and `scripts/publish.py` its own calendar snapshot.

## 8. Not done

- Done since (2026-11-13): the per-brand gate rules have a home outside code,
  `.atelier/memory/gate-rules.json` (section 4).
- `autopilot.timezone` is set with `config.py set`, not asked by
  `setup autopilot` (the `/engine` command's setup table and
  `engine.QUESTIONS` must change together; `test_engine_command` checks it).
- `engine init` does not write `voice.md` from the template
  (`onboard.write_voice` already shapes a stream's voice; `init` could call it).
- `engine init` writes `brand.json`, renders `streams.md` and renames
  `handles.md` own-channel cells and the example claim id only; `docker-compose.yml`'s `comms-research-store`,
  the desk package name `comms-desk` and `research-store/` prose stay generic
  rather than brand-stamped.
- The empty `LEGACY` map in `autopilot.py` could be removed outright.
- The desk's `package-lock.json` was renamed by hand (`name` fields only);
  `npm install` on a machine with network refreshes it properly.
- `plugins.marketplace` ships empty; the operator records the marketplace the
  two plugins come from (`config.py set plugins.marketplace <git url>`).
- `x_stream.record()` takes the brand pattern from its caller; `digest` and
  `listen` build it once. A function default such as
  `stream=memory.DEFAULT_STREAM` is still fixed at import, which only the test
  fixture notices (it passes the stream explicitly).
- Whether the desk ships in the template or stays an optional module is still
  the owner's decision.

## 9. Test counts

Baseline on the raw copy: 396 tests, 36 failures, 21
errors, 4 skipped. After the brand block: 418 tests, 29 failures, 22 errors,
11 skipped. After the fixtures, prose and docs: 437 tests, 2 failures (the
fresh-clone greps naming the shipped leaks), 2 skipped. After the fix step: 445
tests, every one green on the placeholder brand (one skip: the gate's
status-word coverage, waived while `STATUS_WORDS` ships empty) and, in a copy
stamped `engine init --slug demo --name Demo`, green again with two skips
(that one and the placeholder check); `engine doctor` there: 17 ok, 0
failed, with no key in the keychain. Run:

```
cd <template> && python3 -m unittest discover plugins/comms-engine/tests
python3 plugins/comms-engine/tests/test_brand.py -v      # the brand block alone
```

2026-11-13, Notion retired (`PLAN-channels-hosting.md` N1 to N4). Gone since
the build above: `Tooling/notion-sync/`, `publish-targets.example.json`,
`NOTION_TOKEN`, the `notion` server in `.mcp.json`, `publish.py --sync` and the
`requests` pin. The calendar is the notes plus the lifecycle; the control page
holds the approve, schedule, new-post and blog-live acts; the site reads the
published-posts feed (`GET /api/published`, `engine export-published`). The
lines above that name Notion record the build as it was.

## 10. 2026-11-13, the autonomy plan (`PLAN-autonomy.md`)

Decision: `.atelier/memory/decisions/2026-11-13-autonomy-variety-engagement.md`.
Every step of that plan is built here; step 19 (the plugin, the instance and
the hosted Mac) on 2026-11-14, under
`.atelier/memory/decisions/2026-11-14-package-and-host.md`.

**The shape now.**

- **One setup file.** `brand.json` at the root, about forty lines, written by
  `engine init` and by the Setup page; `brand.example.json` beside it.
  `config.load` merges engine.json, then brand.json (translated by
  `config.brand_overlay`), then engine.local.json, then the environment.
  `config.validate` names the key and the fix per problem. The three tables
  of `streams.md` are rendered from it by `brandfile.apply`, their one
  writer; `doctor` fails when they disagree.
- **Code runs the cycle.** `scripts/workflow.py` runs `params.workflows` in
  the order of `params.chains` (`weekday`, `engagement`): each model step is
  one `claude -p` with one agent, a budget, a narrow tool list and a JSON
  reply checked against a schema; run records under `state/runs/<workflow>/`.
  `cycle.sh` and `/social-cycle` call the runner.
- **One policy.** `switches.mode(stream, channel, kind)` answers "may this go
  without a person" for `post`, `reply`, `comment`, `like`, `repost`, `quote`
  and `hold`: `review` (default) or `auto`. A pause per stream is read first
  by `channels.send()`. The autopilot value `by switch` hands a stream to its
  modes; `nothing` is the hard off; an unset owner blocks.
- **Rules and formats are data.** `gate-rules.json` and `formats.json` in the
  stream's memory, read through `memory.py`.
- **Code stamps the verdict.** The gatekeeper and a second reviewer return
  findings per sentence; `review.py` verifies them against `claims.md`,
  writes the verdict and its stamp keyed by text hash. Disagreement blocks.
  A house-style check leaves the code path only when a person lists it under
  `house_style.retired` and `gate_eval.py --live` has cleared it on the
  labelled set (`tests/fixtures/gate_cases/`).
- **The engine may approve.** `desk_acts.engine_approve` and
  `autopilot.py approve`: mode `auto`, verdict exactly pass, a current review
  stamp; the act is `by: engine` with the switch act that allowed it.
- **More kinds of send.** `channels.KINDS` gains `delete` (take down, on a
  person's `takedown` act), `like`, `repost` and `quote`, with target
  eligibility, one reaction per target ever and `reactions_per_day` caps;
  `scripts/reactions.py` plans and sends them. Media on a post carries its
  hash in the approval and is hashed again at send.
- **Plugins by role.** `params.plugins.roles` (role, agent or skill, pinned
  version, brief, fallback), `scripts/roles.py`, the briefs under
  `briefs/`.
- **The dashboard.** Autonomy, Setup and Engagement pages in `ui/` over
  `control.py` (`/api/switch` with a kind, `/api/pause`, `/api/takedown`,
  `/api/setup`, `/api/react`) and the `policy`, `setup` and `reactions`
  views of `views.py`.
- **The engine is a plugin; a brand runs an instance** (step 19). The engine
  is `plugins/comms-engine/` (`comms-engine` 1.0.0), and this repository its
  marketplace. The root keeps what a brand owns, and is the first instance;
  `engine new-instance` writes another, whose `brand.json` pins
  `engine.version` (`doctor` fails on another). Every script is `engine
  <name>` (`bin/engine`); `scripts/paths.py` finds the instance
  (`COMMS_ENGINE_INSTANCE`, `CLAUDE_PROJECT_DIR`, the nearest parent holding
  `brand.json`, the development layout) and its `state/`. The hooks are the
  plugin's, under `${CLAUDE_PLUGIN_ROOT}`; `.claude/` keeps `settings.json`
  alone; the engine's agents are `comms-engine:<name>`.
- **The hosted Mac** (H1 to H6, `docs/07-hosting.md`). Every plist runs
  `~/.local/bin/comms-engine runjob <label>`, the shim `engine shim
  --install` writes, which finds the installed engine at each start. The
  Claude token (`CLAUDE_CODE_OAUTH_TOKEN`) reaches `claude -p` alone; its
  date is recorded and `doctor` warns from day 330. The control page answers
  its Tailscale Serve name only for a login `engine.local.json host.roles`
  maps to a role, which becomes the act's `by`. `backup.py` commits the
  record and, when `backup.push` is true, pulls with rebase and pushes;
  `engine host-check` checks the lot.

**The API added.**

```python
config.brand_path(base), config.read_brand_file(base), config.brand_overlay(bdoc, doc)
config.brand_problems(bdoc, doc), config.validate(base, local)      # lines "brand.json: <key>: <problem>. Fix: <fix>"
brandfile.read(), brandfile.write(doc), brandfile.render(text, bdoc), brandfile.apply(streams_md, base=None, check=False)
brandfile.from_streams_md(text, brand), brandfile.rename(bdoc, old, new)
workflow.specs(), workflow.chains(), workflow.run(name, ...), workflow.run_chain(name, ...), workflow.status_rows()
switches.mode(stream, channel, kind, state), switches.set_mode(...), switches.preset(...), switches.set_pause(...), switches.policy()
switches.KINDS, switches.MODES, switches.PRESETS, switches.BY_SWITCH
acts.KINDS                      # gains pause, takedown, setup
standing_rules.ENGINE_ROLE, standing_rules.refusal(..., role=None)
desk_acts.engine_allowed(item, state_dir), desk_acts.engine_approve(post_id, items, state_dir, ...)
review.SCHEMA, review.review(item, first, second), review.apply(first_path, second_path), review.approvable(item)
gate_lint.write_gate(item_id, gate), gate_lint.retired(name, slug), gate_lint.shape_of(item)
gate_eval.load_cases(), gate_eval.evaluate(...), gate_eval.cleared(rule, state, cases)
memory.load_gate_rules(stream), memory.load_formats(stream), memory.RETIRABLE_RULES
plan_queries.draw(formats, logics, records, stream_name, seed, licence=""), plan_queries.draw_for(...)
repo.swap_alternative(engine_id, n)
channels.KINDS, channels.REACTIONS, channels.CHECK_ORDER, channels.target_refusal(...), channels.reactions_signoff(stream)
channels.media_refusal(...), channels.file_sha256(path)
guardrails.reaction_caps(stream), guardrails.reaction_cap(stream, channel, kind), guardrails.check_hours(...)
reactions.plan(...), reactions.send_due(state, live, driver, at, limit, sleep, only)
roles.roles(), roles.problems(), roles.pinned(), roles.doctor_lines(rows)
motion.media_for(item, channel_key), motion.generate_signoff()
control.set_switch(..., kind, mode, preset), control.set_pause(...), control.takedown(...), control.change_setup(...), control.react(...)
views.policy(), views.setup(), views.reactions()
guard_skills.verdict(...)        # the Skill hook: motion:generate behind its cost sign-off
paths.instance(environ, cwd), paths.state(), paths.engine_home(), paths.local_json(), paths.script(name), paths.expand(argv)
config.SHIPPED_ENGINE_JSON, config.VERSION_RE                       # brand.json `engine.version`
instance.new_instance(target, from_file, marketplace), instance.template_root(), instance.instance_files(template)
engine.engine_version(), engine.engine_version_result(), engine.claude_token_result(), engine.host_checks(...), engine.shim(install)
workflow.claude_token(), workflow._model_env(), workflow._run_env()  # the token reaches claude -p alone
control.door(headers, port, token, method, serve_name, roles), control.door_settings()
backup.run(root, push, dry), backup.pending(root)
comms_engine_shim.resolve(environ, installed)                        # schedule/comms_engine_shim.py
```

CLI: `engine init [--from]`, `validate`, `apply [--check]`,
`run <workflow or chain> [--live]`, `eval gate [--live | --status]`;
`workflow.py list | run | chain | status`; `review.py schema | apply | check`;
`reactions.py plan | send-due [--live] | status`; `autopilot.py approve`;
`plan_queries.py --draw THEME --slot N`; `repo.py --swap N`;
`motion.py generate-signoff`; `config.py validate`; and from step 19,
`engine <name>` for every one of them, `engine new-instance <dir> [--from]`,
`engine shim [--install]`, `engine host-check`, `engine backup [--dry]`,
`engine secrets --set CLAUDE_CODE_OAUTH_TOKEN`, `comms-engine runjob <label> |
--where`.

**Not done, and why.**

- **Step 19 is built, not deployed.** No office Mac has been provisioned:
  that is the owner's, with `docs/07-hosting.md` and `engine host-check`. No
  instance repository exists beyond this one. Automatic login against
  FileVault is the owner's choice. The plugin is validated
  (`claude plugin validate --strict`) and runs from this directory's
  marketplace; it has not been installed from the GitHub marketplace, which
  needs this repository pushed. systemd timers, a Linux secrets backend and
  Postgres are out of scope.
- **Automatic likes on X are off.** X's developer guidelines require a like
  to be initiated by the authenticated user. `channels.reactions_signoff`
  ships empty, a like on X is one click on the Engagement page, and the
  decision file `2026-11-13-reactions-platform-rules.md` is `proposed` until
  the owner signs it. LinkedIn has no reaction tool in the Composio toolkit,
  so a LinkedIn like is not built; reshare and quote are.
- **No house-style rule is retired.** The mechanism of plan step 11 is built
  and `engine eval gate --live` passed on 2026-11-13 (19 cases: claims 7
  of 7, hook 4 of 4, tag line 2 of 2, CTA 3 of 3, shape 1 of 1, no draft
  labelled pass blocked), after a first run that day failed on a title
  sentence the second reviewer left unjudged; reviewers now copy the
  sentences from `review.py sentences`. The result is a state record, which
  the template does not ship, so a brand runs the evaluation in its own
  checkout. Hook length, the tag line, CTA wording and shape stay code checks
  until a person lists them under `house_style.retired`.
- **Only the two reviewer calls have run against a live `claude`**, through
  the runner's own command line, in that evaluation. It found one fault,
  fixed since: a reply that closed its JSON inside a code fence was not read
  (`workflow._json_object`). Every other workflow has run only against a
  fake `claude` in the suite, so the first live chain should be watched: the
  per-workflow tool lists are narrower than the old cycle's and there is no
  `acceptEdits`.
- **The plugins' session hook still injects the root `instincts.md`**
  whatever the stream; there is no switch for it upstream. The runner tells
  a run for another stream so in its prompt instead.
- **`motion:generate` is no longer on the deny list**: the Skill hook holds
  it until `params.motion.generate_signoff` is recorded, and refuses when the
  setting cannot be read.
- **The Next desk is not retired.** The control page carries the new acts;
  the desk keeps edits, reviews and its own approve path.
