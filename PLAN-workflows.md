# Plan: smaller workflows, one post lifecycle, lessons that shape docs

_Written 2026-11-06 after a whole-project review, on the owner's direction:
the engine is too wide, so split it into smaller workflows that can each be
monitored, and let lessons that are confirmed in use shape the docs we keep.
Status: **proposed**. Step 0's three fixes are applied in the working tree and
not committed; the rest is not started._

## Why

- **One session runs the whole cycle.** The weekday job is a single headless
  `claude -p "/social-cycle"` (`scripts/cycle.sh:87-91`): one budget, one
  `=== social-cycle exit N ===` line, twelve steps read from prose, and the
  steps run as 1–7, 9–12, then 8 (`claude/commands/social-cycle.md`). Every
  incident of the engine's first months happened in a hand-off
  between steps: drafts vanished when the index was rebuilt, decisions were
  rewritten with an empty stream, the listener was cut at the background-wait
  ceiling, and the budget ran out before the desk push.
- **The model moves records.** theme-writer appends to `state/queue.json` by
  editing it (`claude/agents/theme-writer.md:48`); the distributor copies
  decisions onto notes by following a prompt (`claude/agents/distributor.md:34-41`);
  any caller can set `alpha_status` with `repo.py --set`; `publish.py:202-206`
  stamps `published_at` at Ready, and `score.py` reads that as publication.
- **Safety is checked on shell text.** The posting hook is a regex over Bash
  commands. MCP, Write, Edit and the Chrome composer are guarded by prompt
  text alone, and the sending code checks almost nothing itself.
- **Lessons are a diary.** No drafting agent or skill reads
  `.atelier/memory/lessons.md` (only `corpus-analyse` and `corpus-update`
  name it). The live-test path that writes a lesson after two wins has never
  run, and a craft lesson from an editor pass never became a check.

## Principles

1. Code runs the workflows and moves records; the model writes and judges;
   memory holds the rules.
2. One workflow, one job, one trigger, one run record.
3. A post changes state only through the lifecycle module.
4. A lesson changes craft and process, never what may be claimed.
5. Build a layer only when the layer beneath it has data.

## Step 0: safety fixes

Applied in the working tree, uncommitted, suite green (459 tests, 1 skip):

- `scripts/autopilot.py`: `--dry-run` is a dry run too. The hook let
  `autopilot.py run --dry-run` through as dry while the script read only the
  exact `--dry`, so the command really sent.
- `scripts/linkedin_api.py`: refuses `--dry` and `--dry-run` with exit 2.
  It has no dry mode, and the hook let `linkedin_api.py post ... --dry`
  through.
- `claude/hooks/guard_posting.py`: `from __future__ import annotations`, so
  the hook loads under macOS's `/usr/bin/python3` (3.9) instead of failing on
  `str | None` at import. Claude Code does not treat that failure as a block,
  so the hook let every command through.

Done 2026-11-06, on the owner's go: the stealth denylist
`tests/test_fresh_clone.py` carried in clear since the first commit now lives
only in the maintainer's gitignored `.leak-terms` (salted hashes were rejected:
short names fall to a dictionary), and the history was rewritten and
force-pushed so no commit carries it.

Still open:

- An unexpected exception inside the hook should block a command that matches
  a sending shape, not pass it.
- The autopilot marker in Claude Code's own environment turns the hook off
  for every command. The sender's launchd job never runs Claude, so check
  whether any session needs the exemption; if none does, drop it.

## Step 1: the workflow runner and its run records

- `scripts/workflow.py` (reached as `engine.py run <workflow>`) runs one named
  workflow. Each run writes `state/runs/<workflow>/<UTC stamp>.json`:
  `workflow`, `stream`, `started`, `ended`, `result` (`ok`, `nothing`,
  `needs-person`, `failed`), `counts`, `cost_usd`, `inputs`, `outputs`,
  `handed_to`, `error`.
- A chain is a list in `engine.json` (for example
  `chains.weekday: [pull, listen, draft, gate, push]`). The runner stops at
  the first failure and records which workflow failed. A launchd job runs a
  chain, so the job count stays small while each step is visible.
- A model call is `claude -p` with one skill or agent, its own
  `--max-budget-usd`, a narrow `--allowedTools` (no Write unless the workflow
  writes one file the code then checks), and JSON out that the code checks
  before it writes anything.
- `engine.py status` shows one line per workflow: last run, result, what is
  waiting for a person, cost today.

Done when the weekday chain leaves five run records, and a failure in the gate
reads `gate failed`, not `social-cycle exit 1`.

## Step 2: the post lifecycle module

- `scripts/lifecycle.py` owns one post's states: draft → gated → decided →
  scheduled → sent → scored, plus blocked and retired. Each move is one
  function that checks what it needs:
  - **gated**: a gate verdict recorded for this text's hash;
  - **decided**: a desk decision (from `desk_sync.py --pull`) for this text's hash;
  - **scheduled**: guardrails pass, counted on the store the sender sends from;
  - **sent**: the ledger row is written first, as today;
  - **scored**: `published_at` is the sent time from the ledger, never Ready.
- `repo.py --set` refuses the lifecycle fields. The desk, the dashboard and
  Notion are views of this state.

Done when approving a post without a desk decision is impossible from the
command line, and `published_at` comes only from the send ledger.

## Step 3: the cycle as workflows

| workflow | does | model | when |
|---|---|---|---|
| pull | desk decisions → notes | no | before each chain |
| listen | fetch X and sources, then one read | 1 call | weekdays |
| draft | one draft per content finding → note | 1 per draft | after listen |
| gate | lint, then one judgment per draft | 1 per draft | after draft |
| push | notes → desk | no | after gate |
| distribute | approved and gated → Ready, through the lifecycle | no | after pull |
| send | the autopilot, as now | no | 09:05, 13:35 |
| engage | reply drafts for live posts | 1 call | 15:30 |
| score, claims-check | as now | no | nightly |
| corpus | sweep; read and analyse; apply by a person | per source | weekdays |
| inventory | handle checks | no | weekly, not daily |
| editor, slots, readout | as now | 1 call each | weekly, monthly |
| lessons | step 4 | 1 per candidate | Fridays |
| story | the run's story as a short deck: facts by code, words by the storyteller, checked; answers kept for the next one | 1 call | last step of the cycle; `/story` on request |
| motion | a card from each gated blog post's own lines (`motion.py pending`, then the motion-designer) | 1 per card | last step of the cycle; `/motion` on request |

`/social-cycle` stays as a manual command that runs the weekday chain through
the runner, so a person can still run everything at once.

## Step 4: the lessons register and the lessons loop

- **First input.** The story's closing frame already collects a person's
  "always remember" notes (`state/story/feedback.json`); the storyteller follows
  them and the session brief shows them to every session. The lessons workflow
  takes each one as a `proposed` lesson, source `person`.
- **Register.** Lessons get ids (`LS-<n>`) and a status: proposed → in use →
  confirmed → in docs → retired. Each row records its kind (craft, process,
  sourcing), source (editor pass, live test, corpus, person), since, what it
  applies to (channel, theme or workflow), evidence (draft ids, scores) and
  the doc it landed in. The dated prose entries stay as history; a lesson
  about what may be claimed stays on the corpus path and gets no id.
- **Drafts cite the lessons they apply** (`applies: [LS-12]`). The gate
  checks each id exists and is not retired, as it checks `cites`. That is
  what makes "confirmed in use" measurable.
- **Confirmation** (owner decision, 2026-11-06): a person confirms on the
  desk. The evidence path (applied across two separate periods, scores not
  below baseline) switches on once about 30 items carry scores.
- **The `lessons` workflow**, Fridays after scoring:
  1. code finds candidates: newly confirmed, contradicted by scores, unused for
     60 days, past decay;
  2. the model drafts one doc edit per candidate, as JSON (doc, section, old,
     new, lesson id);
  3. code checks the edit: an allowed doc, nothing on the denylist, no claim
     vocabulary, the provenance footer present;
  4. the edit waits on the desk; a person approves; code applies it with a
     footer such as "from LS-12, confirmed 2026-11-20";
  5. a retired lesson gets the reverse proposal: take it out of the doc.
- **Docs it may write** (owner decision, 2026-11-06): only the instance's
  playbook, `.atelier/memory/playbook/` (`writing.md`, `channels.md`,
  `calendar.md`, `sourcing.md`). theme-post, x-post, linkedin-post and
  theme-writer read it explicitly before drafting. It never writes the
  engine's skills, agents or `docs/` (a lesson true for every brand goes
  upstream as a change a person makes), and never `claims.md`, `status.md`
  or `themes.md`. A lesson that implies a new deterministic check becomes a
  code task, not an edit.

Done when one editor-pass lesson reaches a playbook doc through the loop and
the next draft's note cites it.

## Step 5: rules out of the code

- One memory file holds the gate's brand rules: status words, cleared hedges,
  capability verbs, and the house-style checks as switches (the "what we do
  not claim" sentence, hook length, theme count). `gate_lint.py` and
  `announce_check.py` read it; `/corpus-update` may tighten it.
- Context injection that knows the stream. The atelier and salon prompt hooks
  inject the root `instincts.md` into every prompt (atelier
  `scripts/hooks/prompt-context.js:178`) and never a stream's own. Skills read
  their stream's memory explicitly; the plugin injection is made
  stream-aware upstream or left out of engine runs.
- `params.corpus.apply` defaults to `false`: on an empty memory every edit is
  an addition, so a stricter-only rule protects nothing.

## Step 6: the engine as a plugin

_Amended 2026-11-14 (owner, `.atelier/memory/decisions/2026-11-14-package-and-host.md`)._

- A versioned `comms-engine` plugin (skills, agents, commands, hooks, and the
  scripts under `${CLAUDE_PLUGIN_ROOT}`) lives in this repository under
  `plugins/comms-engine/`, and this repository is its marketplace
  (`.claude-plugin/marketplace.json`). One instance repository per brand holds
  `brand.json`, the memory, the content, the state and its `engine.local.json`;
  `engine new-instance` writes one.
- The instance pins `engine.version` in `brand.json`; `engine doctor` fails on
  a mismatch, as it does for the pinned atelier and salon versions. `Skill`
  goes into the allowlist of every workflow that calls them.
- launchd needs a fixed path: `engine shim --install` writes
  `~/.local/bin/comms-engine`, which resolves the current plugin root at each
  start; every plist runs `comms-engine runjob <label>`.
- The template is the first instance, and hand-porting between two copies stops.

## Paused until data asks for it

- Streams beyond brands that share an owner.
- Learning machinery beyond the plain prediction and result record
  (`livetests.py`, `readout.py`, `plan_queries.py`).
- The curses screen. The desk becomes an optional module; the dashboard too.

## Decisions

- **Recorded 2026-11-06 (owner):** smaller workflows that can be monitored; a
  person confirms lessons first; the lessons loop edits only the playbook.
- **Recorded 2026-11-07 (owner):** the Next desk retires once one web app
  matches it (`PLAN-surfaces.md`, Decisions).
- **Done 2026-11-06 (owner, "do it"):** the history rewrite and force-push of
  this repository.
- **Open:** recording the marketplace URL in `params.plugins.marketplace`.
- **Recorded 2026-11-10 (owner):** every official channel through Composio,
  the dashboard as the only surface, self-hosted later
  (`PLAN-channels-hosting.md`). For step 2, the sender reads `scheduled`
  from the lifecycle, not Notion. For step 6, the plugin carries
  `channels.py` and the extended posting guard.
