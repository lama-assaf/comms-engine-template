# Plan: the fresh shape, one setup file, plugins by role, varied output, a review switch, reactions

Written 2026-11-13, revised twice the same day. It comes after the three fixes
from the evaluation, which it assumes are done: each claim sentence tied to its
own cite, the claim text shown where a person approves, and one dashboard
(`ui/` over `control.py`, the Next desk retired).

Owner answers, 2026-11-13, that this plan is built on:

- "Less deterministic" means both: posts read too alike, and the checks are too
  rigid.
- Migrate this repository in steps. No new codebase.
- With review switched off for a stream, nothing waits for a person. Whatever
  passes the automatic checks goes out; whatever fails stays in the queue.
- Likes and reposts run automatically, within limits, behind a switch.
- Setup should be easy for a new project. The owner asked whether YAML has
  value for that. Little: see section F, which drops it.

Two of these change standing rules 1 and 4 of `CLAUDE.md` and step D3 of
`PLAN-channels-hosting.md`. Step 1 records that before any code moves.

## The fresh shape (the target the steps migrate to)

If this were started today it would have six parts, and the migration ends
there:

1. **Code runs the cycle, the model does bounded jobs.** Today `/social-cycle`
   is a 240-line prompt in which a model orchestrates twelve steps. Fresh, a
   runner (`scripts/workflow.py`, `PLAN-workflows.md` step 1) runs each
   workflow as one `claude -p` call with a narrow tool list, a budget and JSON
   out that code validates before anything is written.
2. **One policy answers "may this go without a person".** Today the answer is
   spread over the `autopilot` cell, `switches.py`, `standing_rules.py` and the
   hold check in `channels.py`. Fresh, one function answers per stream, channel
   and kind, and every caller asks it.
3. **Rules are data.** Status words, capability verbs and house style live in
   one memory file, not in regexes in `gate_lint.py` (`PLAN-workflows.md`
   step 5).
4. **Hard limits in code, judgment in a reviewer whose output code checks.**
   The code keeps what must never fail. The reviewer returns structured
   findings and code verifies them, then code stamps the verdict.
5. **The engine is a plugin, the brand is an instance.** `comms-engine` beside
   atelier, salon and motion; one instance repository per brand
   (`PLAN-workflows.md` step 6), on one server (`PLAN-channels-hosting.md` H).
6. **One small setup file, filled in by a guided setup.** A new project is one
   `brand.json` of about forty lines that a wizard or the dashboard writes, not
   cells in markdown tables plus a 1,782-line `engine.json` (section F).

Kept as they are, because they are right: the claims register, `channels.send()`
as the only sender, `lifecycle.py`, `acts.py`, the memory layout, the tests.

## A. The review switch

- `scripts/switches.py` grows from the auto-reply switch to a **mode per
  stream, channel and kind**: `review` (the default) or `auto`. Kinds: `post`,
  `reply`, `comment`, `like`, `repost`, `quote`, and `hold` (the
  statistics, partner and certification class). New `mode(stream, channel,
  kind, state)`; `auto_reply_on` stays as a wrapper over it.
- A **pause** per stream, read by `channels.send()` at every send, stops
  everything at once. New act kinds `pause` and `takedown` in `acts.py`.
- The stream's `autopilot` setting (in `brand.json`, section F) gains the value
  `by switch`, set once by a person at onboarding. `nothing` stays the hard
  off, and an unset owner still blocks. `switches.streams_allow` reads it.
- Turning a mode to `auto` takes one confirmation; the written reason becomes
  optional, as approvals did on 2026-11-11.
- `desk_acts.approve_post` gains an engine caller: when the mode for `post` is
  `auto` and the verdict is pass, a new step `autopilot.py approve` records a
  `decision` act with `by: engine` and the id of the switch act that allowed
  it, then schedules through the same applier. `standing_rules.refusal` skips
  the argument line for that role only.
- `channels._evaluate`: the hold check passes without a release act when the
  `hold` mode is `auto`. Every other check is untouched and runs in both modes.
- A `delete` kind in `channels.py` (already in the hosting plan's connector
  list) backs a "take down" button, because with nobody reviewing, undo has to
  be one click.
- Dashboard: an Autonomy page in `ui/src/pages/` with three presets (review
  everything, review posts only, fully automatic), the per-row toggles, the
  pause, and a "sent without review" list with take down. `control.py`
  `/api/switch` takes the kind; `/api/pause` and `/api/takedown` are new.
  `views.py` gains the `policy` view.

## B. Less rigid checks

- `.atelier/memory/gate-rules.json` holds the brand's status words, cleared
  hedges, capability verbs and house-style switches. `gate_lint.py`
  (`STATUS_WORDS`, `CLEARED_HEDGES`, `capability_pattern`, `HOOK_MIN/MAX`,
  `check_no_claim`, `check_tag_line`) reads it through `memory.py`.
- **Hard limits stay code and run in every mode:** stream, stealth denylist,
  cites current and bound to their sentence, pair rules, account, dedupe, caps,
  quiet hours.
- **House style becomes the reviewer's:** hook length, tag line, CTA wording,
  shape, the fixed "what we do not claim" form. They leave the blocking path.
- The reviewer (`gatekeeper`) returns JSON per sentence: is it a claim, which
  cite, the row's words it rests on, supported or not. New `scripts/review.py`
  checks that the quoted words are in that row of `claims.md`, that every
  claim sentence has a cite, and writes the verdict and its stamp itself, keyed
  by text hash. The model no longer stamps its own review.
- Two reviewer passes with different briefs (the second is
  `salon:adversarial-refinement`). Disagreement is a block.
- `scripts/gate_eval.py` (`engine.py eval gate`) runs the reviewer over
  labelled drafts in `tests/fixtures/gate_cases/`. A code rule is retired only
  after the reviewer catches every should-block case in the set. It makes paid
  model calls, so it is not part of the unit suite.

## C. More varied writing

- `.atelier/memory/formats.json`: the formats a stream may use (theme post with
  teasers, X thread, short take, quote commentary, question, data note, motion
  card, case story), each with its own structure and which channels it fits.
  The five-part structure in `claude/skills/theme-post/SKILL.md` becomes one
  format, not the only one.
- `plan_queries.py` picks a format and a logic per draft by weighted draw over
  past bands in `state/predictions.json`, inside the existing 60/25/15 budget
  of `livetests.py`. The seed and the draw are written on the note.
- `theme-writer` writes three candidates per finding that differ in one named
  variable. `salon:post-audit` ranks them; the first goes to the gate, the
  others stay on the note as alternatives a person can swap in.
- `gate_lint.check_shape` widens from three fields to format, logic and opener,
  and stays an edit, never a block.

## D. Plugins by role

- A `plugins.roles` section in `brand.json` (defaults in `engine.json`): role,
  plugin agent or skill, pinned version, and a brief file under
  `Tooling/social-engine/claude/briefs/`. The brief carries this repository's
  rules, since a plugin agent knows none. `engine.py doctor` fails on a
  version mismatch; `test_plugin_wiring.py` checks every role resolves or has
  a fallback.
- Roles added. salon: `adversarial-refinement` and `post-audit` (B and C),
  `x-thread` (a format), `comment-strategy` and `reply-playbook` (engagement
  drafts), `launch-window` (send timing), `community-manager` (when Telegram
  or Discord is listed). atelier: `copywriter` and `narrative-architect` (the
  candidates), `ab-test-design` (the hypothesis), `release-narrator` (staging
  for `/announce`), `motion-direction` (the motion-designer's brief).
- motion: a card or film becomes media on a post, attached through
  `channels.send()` with the file hash in the approval. `motion:post` stays
  denied. `motion:generate` opens only behind a recorded cost sign-off, the
  pattern `listen.x_price_signoff` already uses.
- The plugin prompt hooks inject the root `instincts.md` whatever the stream.
  Headless runs switch that injection off until it is stream-aware upstream.

## E. Reactions: like, repost, quote

- `channels.py`: `KINDS` gains `like`, `repost`, `quote`. Composio drivers for
  each on X, reaction and reshare on LinkedIn. The slugs are looked up from
  Composio's tool list, not guessed. `guard_posting.py` already refuses any
  write slug outside `channels.send()`; a test pins that for the new ones.
- `_evaluate` for a like or repost (no text of ours): account, switch mode,
  one reaction per target ever (ledger id `like:<post id>`), caps, quiet hours,
  and **the target is eligible**: its author is a `verified` cleared row of
  `handles.md`, on the watchlist, or replying to our own post; its text passes
  the stealth, status-word and pair checks. A quote is a post with a target and
  takes the full text gate.
- `guardrails.parse_guardrails` reads a new `reactions_per_day` setting of the
  stream in `brand.json` (for example `{"x": {"like": 20, "repost": 3}}`).
- New `scripts/reactions.py`: `plan` (candidates from `signals.json`, the
  watchlist pass and `inbound.py`, ranked by tier and theme, written to
  `state/reactions.json` as post id, tier and theme, never a handle) and
  `send-due` (dry by default, `--live` through `channels.send()`, spaced
  out, a per-run limit). The `engagement` job runs it.
- `engage.py record` takes the new shapes, so the 72-hour ledger shows which
  reactions earn a reply or a follow.
- Dashboard: an Engagement page with done, queued and refused, each refusal
  with its reason, and undo.

## F. Easy setup: one small file and a guided setup, no YAML

**Is there value in YAML? Little here, so this plan does not use it.** What
makes setup easy is how much a person has to fill in and whether mistakes are
caught, not the file format.

- What YAML would add: comments in the file and less punctuation.
- What it would cost: a second config format beside the JSON every script and
  test already reads through `config.py`; a second code path to test; and a
  real trap, because YAML reads a bare `off`, `no` or `on` as true or false,
  which are the words the switches use.
- What matters more: today a new project edits cells in three markdown tables
  of `streams.md` and finds its way around a 1,782-line `engine.json`. That is
  the hard part, and YAML would not change it.

So the setup work is this instead:

- **`brand.json` at the root**, about forty lines: the brand block (slug,
  name), each stream (narrator, owner `confirmed` or `unset`, channels and
  handles, autopilot, default review modes, posts and reactions per day, quiet
  hours, pair rules), the drivers, which jobs are on, the plugin roles.
  `brand.example.json` ships with it, explained by `_about` keys as
  `engine.json` and `.claude/settings.json` already are.
- **`engine.json` stays, as shipped defaults nobody edits.** `config.load`
  merges `engine.json`, then `brand.json`, then `engine.local.json` (per
  machine, gitignored), then the environment. `config.set_local` is unchanged.
- **Nobody has to open the file.** `engine.py init` asks the few questions and
  writes it; `engine.py init --from brand.json` sets up a clone with no
  questions; a Setup page on the dashboard edits the same file through
  `control.py` (`/api/setup`, a new `setup` act with the role and time).
- **`streams.md` tables are rendered from `brand.json`** by one writer
  (`engine.py apply`), so agents still read markdown and `memory.py` keeps its
  parser. `doctor` fails when they disagree. This replaces "a person edits
  `streams.md`": the person changes the setup, on a decision.
- **Checked on load.** `config.validate` (and `engine.py validate`) names the
  key and the fix for an unknown key, a wrong type or a missing stream.
- Unchanged: prose memory stays markdown, the claims register stays a markdown
  table with one writer, state stays JSON written by code, secrets stay out of
  files.

If the owner still prefers YAML later, it is one reader in `config.load`
(PyYAML is already pinned), with nothing else in this plan depending on it.

## Risks

- **X has restricted automated likes.** Step 12 reads the current X automation
  rules and LinkedIn API terms and records them. Automatic likes on X run only
  with a dated owner sign-off (`channels.reactions_signoff.<stream>`); without
  it X likes stay one click and the rest stays automatic. The account is what
  is at stake.
- **No person and more model judgment** means a wrong claim can ship. Held
  down by: sentence-level cites in code, two reviewers that must agree, the
  labelled set before any rule is retired, the pause, the sent-without-review
  list and take down.
- **Two places for the same setting** while `streams.md` is rendered from
  `brand.json`. Held down by one writer and the `doctor` check.
- **Cost.** Three candidates and two reviewers per draft is about five times
  the model calls. Each workflow carries its own budget and `engine.py status`
  shows the day's spend.

## Verification

```bash
python3 -m unittest discover Tooling/social-engine/tests
ruff check Tooling
python3 Tooling/social-engine/scripts/engine.py validate
python3 Tooling/social-engine/scripts/engine.py doctor
python3 Tooling/social-engine/scripts/config.py show
python3 Tooling/social-engine/scripts/gate_lint.py
python3 Tooling/social-engine/scripts/autopilot.py run --dry
python3 Tooling/social-engine/scripts/engage.py send-due
python3 Tooling/social-engine/scripts/reactions.py send-due
python3 Tooling/social-engine/scripts/parity.py --dry
python3 Tooling/social-engine/scripts/state_check.py
cd Tooling/social-engine/ui && npm run build
```

## Steps

1. Record the owner answers as a dated decision file under `.atelier/memory/decisions/`, reword standing rules 1 and 4 in `CLAUDE.md` and step D3 of `PLAN-channels-hosting.md`, and copy this plan to `PLAN-autonomy.md` at the root.
2. Add `brand.json` and `brand.example.json` with `_about` keys, make `config.load` merge it between `engine.json` and `engine.local.json`, add `config.validate` and `engine.py validate`, and extend `tests/test_config.py` and `tests/test_brand.py`.
3. Add `engine.py apply` to render the three `streams.md` tables from `brand.json`, make `engine.py init` write `brand.json` and accept `--from`, add the out-of-date line to `doctor`, and extend `tests/test_streams.py`, `tests/test_onboard.py` and `tests/test_fresh_clone.py`.
4. Build `scripts/workflow.py` with run records under `state/runs/<workflow>/`, add the weekday chain to `engine.json`, and make `/social-cycle` call the runner; add `tests/test_workflow.py`.
5. Create `.atelier/memory/gate-rules.json` in template shape and make `gate_lint.py` and `announce_check.py` read their brand rules from it through `memory.py`; extend `tests/test_gate_lint.py`.
6. Generalise `switches.py` to `mode(stream, channel, kind)`, add the `by switch` autopilot value and the per-stream pause, and add `pause`, `takedown` and `setup` to `acts.KINDS`; extend `tests/test_switches.py`.
7. Add `autopilot.py approve` and the engine caller in `desk_acts.approve_post`, relax `standing_rules.refusal` for the engine role, and make the hold check in `channels._evaluate` read the `hold` mode; test that review mode still refuses a post with no person's approval.
8. Add the `delete` kind and its Composio drivers to `channels.py`, with `/api/takedown` in `control.py`; extend `tests/test_channels_send.py`.
9. Build the Autonomy page and the Setup page in `ui/`, the `policy` and `setup` views in `views.py`, and `/api/pause`, `/api/setup` and the kind on `/api/switch` in `control.py`; rebuild and commit `ui/dist`.
10. Write `scripts/review.py` and the reviewer's JSON schema, change `gatekeeper.md` and `claim-gate/SKILL.md` to return findings instead of writing the verdict, add the second reviewer pass, and add `tests/test_review.py`.
11. Add `scripts/gate_eval.py` with labelled cases under `tests/fixtures/gate_cases/`, then move hook length, tag line, CTA wording and shape from blocking code checks to reviewer checks once the set passes.
12. Read the current X automation rules, LinkedIn API terms and Composio tool list for like, repost, quote, reaction and reshare, and record the findings and the owner's sign-off in a decision file.
13. Add `.atelier/memory/formats.json`, the weighted format and logic draw in `plan_queries.py`, three candidates with a `salon:post-audit` ranking in `theme-writer.md` and `theme-post/SKILL.md`, alternatives on the note through `repo.py`, and the wider `check_shape`.
14. Add the `like`, `repost` and `quote` kinds, their drivers, target eligibility and dedupe to `channels.py`, the `reactions_per_day` setting to `brand.json` and `guardrails.parse_guardrails`, and `tests/test_reactions_send.py`.
15. Write `scripts/reactions.py` (`plan`, `send-due`), add it to the `engagement` job in `engine.json`, extend `engage.py record`, and add `tests/test_reactions.py` and a `guard_posting` test for the new slugs.
16. Build the Engagement page in `ui/` and the `reactions` view in `views.py`; rebuild and commit `ui/dist`.
17. Add the `plugins.roles` section with pinned versions and the brief files under `claude/briefs/`, wire the new salon and atelier roles into the workflows, update the deny list in `.claude/settings.json`, and extend `tests/test_plugin_wiring.py` and the doctor line.
18. Attach motion cards and films as post media through `channels.send()` with the file hash in the approval, and put `motion:generate` behind a recorded cost sign-off.
19. Package the engine as the `comms-engine` plugin with an instance repository per brand (`PLAN-workflows.md` step 6), then carry out H1 to H6 of `PLAN-channels-hosting.md`.
20. Rewrite `docs/01-setup.md` around `brand.json` and the guided setup, update `docs/02-method.md`, `docs/04-runtime.md`, `docs/05-console.md`, `docs/06-streams.md` and `TEMPLATE-CONTRACT.md` to the new shape, and run every command in the Verification section.

## Where the build stands (2026-11-14)

Every step is built in this repository. The paths and commands in the plan
above are as they were written; since step 19 the engine is
`plugins/comms-engine/` and every script is `engine <name>`. What is open:

- **Step 19 is built, not deployed** (2026-11-14, the owner's answers in
  `.atelier/memory/decisions/2026-11-14-package-and-host.md`; the build plan
  was `.gg/plans/step19-package-and-host.md`). The engine is the
  `comms-engine` plugin, 1.0.0, from this repository's own marketplace; the
  root is the instance template and `engine new-instance` writes a brand's
  own; H1 to H6 are built for an office Mac behind Tailscale Serve, with
  `docs/07-hosting.md` as the runbook and `engine host-check` as its test.
  Left to the owner: provisioning the Mac, the FileVault choice, the first
  brand instance, and pushing this repository so an instance can install the
  plugin from GitHub.
- **Step 11, second half.** The labelled set and `gate_eval.py` are built and
  the paid run was made on 2026-11-13 (`engine.py eval gate --live`, 19
  cases, 1.87 USD). The reviewers caught every case they had to, but two
  drafts labelled pass were blocked: the second reviewer left a title
  sentence unjudged. The reviewers now copy the sentences to judge from
  `review.py sentences`, which splits them exactly as `review.py` checks
  them, and the second run the same day passed: 19 of 19, no draft labelled
  pass blocked, 1.53 USD. The template ships no state record, so a brand runs
  the evaluation once in its own checkout. No house-style rule has been
  moved: that still needs a person to list it under `house_style.retired`.
- **Step 12, the sign-off.** The findings are recorded in
  `.atelier/memory/decisions/2026-11-13-reactions-platform-rules.md`, status
  `proposed`. The owner's sign-off is not: likes on X stay one click.
- **Assumed before step 1 and found missing:** sentence-level cites. They are
  now enforced by `review.py` (step 10) rather than by an earlier fix, and
  the Next desk is not retired.

`TEMPLATE-CONTRACT.md` section 10 has the API and the full list.
