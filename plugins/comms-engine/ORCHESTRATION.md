# Orchestration: how the engine runs, end to end

Companion to `PLAN.md` (v2). The plan says **what is built**; this file says
**what runs, where, when, on which files, and who is allowed to write what**.
Nothing here changes doctrine: the claim gate fails closed, nothing publishes
itself except where a stream's `autopilot` cell in `streams.md` says the
autopilot may, the vault note is the record, conflicts skip.

Written 2026-10-26; rewritten for the template on 2026-11-05.

## History

Built 2026-09 to 2026-11. The loop first ran across two runtimes
(this engine and a second automation platform sharing the same memory files);
on 2026-11-05 the second runtime was left for good, every step moved here, the
schedules became `engine.json` `jobs`, the sender became `scripts/autopilot.py`
and the posting guard became a PreToolUse hook. Nothing in this file depends on
that history; a new brand starts from the state §2 describes.

## 1. The shape in one picture

```
                 ┌────────────────────── shared memory: .atelier/memory/ ──────────────────────┐
                 │ streams.md · claims.md · themes.md · handles.md · status.md · voice.md ·     │
                 │ instincts.md · lessons.md · reviews.md · calendar.md · campaigns/ · decisions/│
                 └──────────▲───────────────────────────────▲──────────────────────────▲────────┘
                            │ tighten-only                   │ read every run           │ read every run
   the strategy corpus ───► /corpus-cycle ─────────┐         │                          │
   primary-source watch ──► research store ─────► promotion  │                          │
   (files mode until hosted)       (corpus-analyse / corpus-update)                     │
                                                              │                          │
        ┌──────────────────────── the engine (, launchd jobs) ──────┴────────────────────┐
        │ /social-cycle (listen · plan · draft · gate · distribute) · weekly editor · blog slots · engagement  │
        │ pass · score.py · claims_check.py · livetests.py · readout · desk_sync · dashboard · corpus memory   │
        └───────────────▲──────────────────────────────────────┬──────────────────────────────────────────────┘
                        │ decisions, edits, reviews              │ notes, state/, lifecycle  
                        │                                        ▼
        autopilot (launchd) ── the calendar notes + lifecycle ── the brand's site ── X / LinkedIn (teasers)
        (snapshot · post · link replies, within streams.md's guardrails)
                                           │
                                           ▼
                             Content/Calendar/<title>.md  (the record; desk edits skip on conflict)
                                           │
                                           ▼
                             desk (Next.js, state/desk.db) ── a person decides, edits, reviews, holds
```

Three cadences run over that picture: **daily** (listen, watch, draft, gate,
publish, engage, score), **weekly** (editor, blog slots, tests budget), and
**monthly** (topic map, readout, recalibration). A **reactive** path exists for a
held slot triggered by a primary-tier claim.

## 2. What runs

Every job is a launchd agent rendered from `engine.json` `jobs` by
`schedule/install.sh` (no path in the repo names a machine); its label is
`<brand.label_prefix>.<name>`, so `python3 scripts/config.py labels` prints
the real ones. `scripts/jobs_status.py` prints this table live from the files
the jobs write; `engine status` wraps it. Times are the Mac's local time.
Nothing is loaded by a clone: `engine enable <job>` is a person's act.

| job (name) | schedule | what |
|---|---|---|
| `corpus-cycle` | weekdays 06:30 | `corpus_cycle_daily.sh`: sweep; a headless `/corpus-cycle --apply --max 8` only when something changed |
| `social-engine` | weekdays 07:15 | `cycle.sh`, a headless `/social-cycle`; `--editor` Mon, `--slots` Fri, `--readout` first weekday of the month |
| `autopilot` | weekdays 09:05, 13:35 | `autopilot.py run`: snapshot into `calendar.md`, post due Ready rows within guardrails, link replies |
| `engagement` | weekdays 15:30 | `cycle.sh --only engage`, drafts only |
| `score` | daily 22:00 | `x_metrics.py`, `score.py --demand`, `metrics.py`, `livetests.py close` |
| `claims-check` | daily 22:15 | `claims_check.py`, `state_check.py`, `build_dashboard.py` |
| `x-stream` | always (optional) | twitterapi.io WebSocket on the `<slug>:*` rules; `enable x-stream` by name |
| `nosleep` | always | `caffeinate` |

Install: `engine enable <job>` per job, or
`schedule/install.sh` (`--dry-run` first) for every job
but the optional stream.

## 3. Principles that bind the orchestration

1. **One owner per step.** Every step in §5 is run by exactly one job. Another
   job may read its output, never redo it. Listening in particular runs once a
   day per stream, not twice.
2. **Files are the handoff.** A step consumes files the previous step wrote and
   writes files the next step reads. No step calls another's API.
3. **Single writer per file.** The table in §7 names the only writer of each
   store. A step that needs to change a file it does not own proposes the change
   to the owner (a review on the desk, a brief in `Docs/Research/`, a row in
   `state/claims-review.json`).
4. **Every step logs itself as it finishes**: scripts through their own code,
   agents through `runlog.py`. A step with no log entry is a step the desk
   cannot see.
5. **Fail closed, continue around.** A step that cannot verify blocks its own
   item and says why; the cycle continues with the rest. Missing
   `handles.private.md`, missing stream memory, a superseded cite, a research
   store that is down: each has a named outcome in §9, none of them is "pass".
6. **Prediction before optimisation.** Nothing tunes a prompt, template or
   schedule automatically until the monthly readout shows four weeks of
   predicted-versus-actual correlation for that stream (plan decision 5).
7. **A person decides on the desk and the control page, nowhere else.** The
   desk owns decisions, edits, argument lines and reviews; the control page
   owns the approve, schedule, new-post and blog-live acts the engine may not
   make. Chat is for instructions to the
   operator, not a record.

## 4. Actors

**Runtimes**

- **launchd** (`engine.json` `jobs`): every scheduled job, including the
  **autopilot** (`scripts/autopilot.py`), the process that writes a row
  `Published` and posts on the scheduled date, under the registry's rules, every
  send through `channels.send()`.
- **the Claude Code engine** (`plugins/comms-engine/`): `/social-cycle`
  headless through `scripts/cycle.sh`, or interactive; agents `listener`,
  `theme-writer`, `gatekeeper`, `distributor`; scripts under `scripts/`.
- **the desk** (`Tooling/desk/`, port 4310): where a person acts.
- **the research store**: Graphiti over FalkorDB when a host is named, files
  mode until then; read by the planning queries and the watch, written by
  `research_store.py` only.

**People** (never named in files; the registry row says only whether an owner
is confirmed)

- the owner of the stream: decides on the desk, approves and marks articles live on the control page, clears
  partner names, answers the questions the engine raises.
- the operator: runs commands by hand when a schedule missed, resolves
  `--prefer desk|vault` conflicts when told to, enables jobs, holds keys.

## 5. The steps, their owner and their cadence

Times are the Mac's local time (the job calendars in `engine.json`); the
guardrails judge quiet hours and slots in `autopilot.timezone`.

### Daily, weekdays

| time | step | owner | reads | writes | next consumer |
|---|---|---|---|---|---|
| 06:30 | **corpus memory**: sweep, read, analyse, update (tighten-only) | the `corpus-cycle` job; `/corpus-cycle --apply` by hand when it misses | the corpus root, `Docs/Research/_corpus/manifest.json`, research-store candidates whose corroboration changed | `Docs/Research/*.md` briefs; with `--apply`: `.atelier/memory/*` incl. `claims.md` | every later step reads memory |
| 07:15 (step 2) | **research watch**: the listener's primary-source sweep, then `research_store.py watch`: claim candidates, merged and corroborated across days | inside `/social-cycle` | issuing bodies, regulators, standards bodies, institutional press; `themes.md` | `state/watch-candidates.json`, `Docs/Research/watch/<date>.md`; episodes when the store runs | corpus-analyse (`research_store.py candidates`), planning queries |
| 07:15 | **the cycle**: pull desk acts; listen (X search, x-stream digest, primary sources); refresh inventory; planning queries; draft with `cites`, `hypothesis`, `predicted`, `test_id`; gate; distribute approved items to the vault; ingest notes; push desk; dashboard; motion cards for the upcoming blog posts the gate let through (step 7a, last) | the `social-engine` job through `cycle.sh` | `state/decisions.json` etc. from the desk, `claims.md`, research store, `themes.md`, `calendar.md`, `lessons.md` by recency, `reviews.md` | `state/signals.json`, `Content/Calendar/*.md` (via `repo.py`), `state/queue.json`, `state/predictions.json`, `state/runs.json`, approved posts scheduled in `state/lifecycle.jsonl`, `state/desk.db` mirror tables, dashboard | the autopilot (post), the desk (a person) |
| 09:05 | **autopilot run 1**: snapshot, post due scheduled posts within guardrails, link replies | the `autopilot` job | the calendar notes, `state/lifecycle.jsonl`, `streams.md` guardrails, `state/send-ledger.json` | posts on their date, `state/publish-log.json`, `state/send-ledger.json`, `state/calendar-snapshot.json`, `.atelier/memory/calendar.md`; git commits only with `autopilot.commit` | score.py, the engagement step, the desk |
| 13:35 | **autopilot run 2**: same, catches afternoon approvals and the day's second slot | the `autopilot` job | as above | as above | as above |
| 15:30 | **engagement pass**: inbound replies on the last three days' posts, comment drafts on others' posts with shape and target tier, engager ledger; drafts only | the `engagement` job (`/social-cycle --only engage`, the salon engagement-manager) | `state/publish-log.json`, `state/send-ledger.json`, `voice.md`, `instincts.md`, `handles.md`, `themes.md` | `state/engagement.json` (proposals and acts, never sent), run entry | the qualitative pass of scoring reads the inbound |
| 22:00 | **scoring**, after `x_metrics.py` reads our own X posts' public counts: every published item at 72 h and 7 days, weighted by intent, baseline per platform and format, identifiers stripped; `actual` beside `predicted`; `demand` per theme; live tests closed | the `score` job | `state/publish-log.json`, `state/send-ledger.json`, x-stream digest, `state/metrics-input/`, `state/predictions.json` | `state/engagement.json` (partial until the logins exist), `state/predictions.json`, `signals.json.demand`, `state/metrics.json`, `state/tests.json` | weekly editor, tests, the readout |
| 22:15 | **supersession and decay check**: notes whose cited claim was superseded or downgraded, pieces whose engagement decayed below baseline; the state check; the dashboard rebuild | the `claims-check` job | `claims.md`, `Content/Calendar/*.md` (`cites`, `gate_at`), `state/engagement.json` | `state/claims-review.json`; desk shows *review: update, annotate or retire* | a person on the desk |
| always | **x-stream**: twitterapi.io WebSocket on the `<slug>:*` rules | the optional `x-stream` job | rule plan from `x_stream.py rules` | `state/x-stream/<date>.jsonl` | score.py, listener digest |

### Weekly

| when | step | owner | reads | writes |
|---|---|---|---|---|
| Mon 07:15 | **weekly editor**: the coming seven days as a whole; applies the 60/25/15 test budget and the one-or-two-tests-per-channel rule; holds collisions | `/social-cycle --editor` on Mondays | the calendar notes of the week, `state/queue.json`, `state/tests.json`, `state/planning.json`, `voice.md`, `instincts.md` | reviews on the desk (holds), `state/tests.json` (slot assignments), run entry |
| Fri 07:15 | **blog slots**: two blogs per ISO week, at least three days apart, social-only for the rest; names which planning query each pick answers | `/social-cycle --slots` on Fridays (the salon campaign-strategist) | `themes.md` licence table, `status.md`, campaign file, `state/signals.json`, `state/queue.json`, topic map | `state/strategy.json`, run entry |
| nightly, in the score job | **tests close-out**: outcomes keep, discard, trending, inconclusive for tests past their maturation window; two wins in separate periods append a lesson | `livetests.py close` | `state/tests.json`, `state/predictions.json`, `state/engagement.json` | `state/tests.json`, `.atelier/memory/lessons.md` (`evidence`, `confidence`, `since`) |
| every cycle | **inventory refresh**: handles past the 30-day window | inside `/social-cycle` | `handles.md`, `state/inventory-ledger.json` | `handles.md` (`last_verified`, two cells only), the ledger |

### Monthly, first cycle of the month

| step | owner | reads | writes |
|---|---|---|---|
| **topic map**: per theme, sub-topics covered, perspectives, open questions from replies, claims changed | `research_store.py topic-map` inside the first `/social-cycle --readout` | research store | `## topic map` in the stream's campaign file |
| **readout**: `campaign-retro` per stream; correlation on the scorecard, lessons promoted or decayed, checklist items that predicted nothing, platform changes as dated events, the stream's stage (explore, exploit, deepen); freezes the scorer if the correlation falls | `/social-cycle --readout` | `state/metrics.json`, `state/tests.json`, `state/predictions.json`, `lessons.md` | `state/runs.json` entry, `lessons.md`, `state/metrics.json` (`scorer_frozen`), a decision file only when a person agrees |
| **recalibration**: lesson decay applied; the inner-loop gate checked: enabled only by a decision file citing four weeks of correlation | the readout | the readout | nothing automatic beyond decay |

### Reactive

| trigger | step | owner |
|---|---|---|
| a watch finding promoted at tier `primary` under a held theme | the held-slot test in `theme-listening`; a reactive draft enters the morning cycle, same gate, no shortcut | the cycle |
| a published piece's cited claim is superseded | `claims-review.json` row; a person updates, annotates or retires the piece on the site; the engine never edits a published piece | a person |
| a desk edit with a stale `base_hash` | both versions kept, item flagged, `apply_edits.py <id> --prefer desk\|vault` by a person | a person |
| a facts release (Block B) | manual by rule; on release the fact becomes a `claims.md` row at grade evidenced through `/corpus-update` | a person, then corpus-update |

## 6. One runtime

Everything runs here, in Claude Code and launchd:

- **The engine owns every step**: listening, planning, drafting with cites and
  a hypothesis, the gate, distribution to the vault, the weekly editor
  and blog slots as cycle flags, the engagement pass in dry-run, scoring, the
  claims check, tests, the readout, the desk, the dashboard, the corpus memory.
- **The sender is `scripts/autopilot.py`**, a script under launchd (the
  `autopilot` job): `snapshot` writes `state/calendar-snapshot.json` and
  `.atelier/memory/calendar.md`; `post` sends the Ready LinkedIn and X rows due
  today for the root stream, after `guardrails.check` says the registry allows
  it; `links` adds the article link once the Blog row is Published. Ledger
  before send, never twice. Whether the stream posts automatically at all is
  the `autopilot` cell of its row in `streams.md`: drafts-only is a one-cell
  change.
- **Every send goes through `channels.send()`**, which refuses unless every
  check passes (gate, cites, stealth list, hold for review, account and pair
  rules, quiet hours and caps, the kind of send). `hooks/guard_posting.py`
  (PreToolUse on Bash) refuses a raw platform write that bypasses it; it does
  not ask who runs a command.
- **The repo is a template.** `.claude/` is tracked; a clone runs with plain
  `claude`. Schedules are `engine.json` `jobs`, rendered per machine.
- **Listening runs once a day**, in the morning cycle.

Why not a hosted scheduler: a cloud scheduled task runs in a fresh clone with no
access to the machine's files, and the gate blocks without the gitignored
`handles.private.md`; launchd on the operator's Mac stays the scheduler.

## 7. Stores and their single writer

| store | writer | readers | notes |
|---|---|---|---|
| `.atelier/memory/*.md` (doctrine, `status.md`, `themes.md`, `handles.md`, `claims.md`) | `/corpus-update --apply` only | every step | tighten-only; `status.md` outranks `project.md`; `reviews.md` is appended by `desk_sync.py --pull` only; `calendar.md` by `autopilot.py snapshot` only; `lessons.md` by `livetests.py` and the readout; `handles.md`'s two inventory cells by `inventory.py`; a person's new theme (added at `held`) and a person's licence grade (with its reason; the status log keeps the one it replaced), by `held_theme.py` (the control page) |
| `.atelier/memory/streams.md` | a person, by hand, on an owner decision; `engine init` renames the placeholder cells once | `memory.py`, `publish.py`, autopilot, gate | guardrails, pair rules, autopilot rule per channel, owner state |
| `.atelier/memory/streams/<slug>/` | `/corpus-update --apply --stream <slug>` | that stream's steps only | the root stream stays at the root |
| research store | `research_store.py` | planning queries, corpus-analyse, topic map | nothing cites it; it mirrors `claims.md`, notes and signals as episodes, never the reverse |
| `Docs/Research/` (gitignored) | corpus-analyse (briefs), the watch (daily log) | corpus-update | a report is a source, not memory |
| `Content/Calendar/<title>.md` | `scripts/repo.py` only | everything | the record; never hand-edited to move an item along |
| `state/lifecycle.jsonl`, `state/acts.jsonl` | `lifecycle.py` and `acts.py` only, through a person's acts (approve, schedule, new-post, blog-live) on the control page or the desk pull | the sender, the views, the site feed | a post goes out only from `scheduled`; a team post is gated and approved like any draft; no note is flipped to Published |
| `state/publish-log.json`, `state/send-ledger.json` | `scripts/autopilot.py` only | score.py, engagement pass | the ledger is written before a send and never twice |
| `state/queue.json`, `state/desk.db` mirror tables, dashboard | `repo.py --index`, `desk_sync.py --push`, `build_dashboard.py` | the desk, a person | derived; delete and rebuild loses nothing |
| `state/desk.db` decision tables (`decisions`, `edits`, `argument_lines`, `reviews`) | the desk app only | `desk_sync.py --pull` | `--push` refuses these four |
| `state/signals.json`, `state/raw/<slug>/` | `listener` / `listen.py` | `theme-writer`, score.py | per stream |
| `state/predictions.json`, `state/engagement.json`, `state/metrics.json`, `state/tests.json`, `state/claims-review.json` | `repo.py --all` (predicted), `score.py`, `engage.py`, `livetests.py`, `claims_check.py` | the desk scorecard, the readout | identifiers never stored |
| `state/theme-words/latest.json` | `theme_words.py publish`, from the `storyteller`'s draft (`theme-words` skill) | the control page's Themes drawer | each theme's licence in plain words for the people who decide; derived from `themes.md`, shown as out of date once its rule's hash moves; checked for file names, codes, the denylist and status words |
| `state/runs.json` | each step for itself via `runlog.py` | the desk | never typed afterwards |
| `engine.json` | a person (schedules, defaults); `engine init` (the brand block) | `config.py`, every job | tracked; `engine.local.json` (gitignored) holds per-machine values through `config.py set` and `engine setup` |
| secrets | macOS keychain via `secrets.py`, service `brand.keychain_service`; per-stream items | cycle.sh and the plists export for the run; `linkedin_api.py` writes a refreshed token back | no token in a file |

## 8. People in the loop, unnamed

The registry row for each stream says whether an owner is confirmed; the
operator knows who. The engine raises; it does not wait. What it raises, and
where:

| what | where it appears | what the person does |
|---|---|---|
| a gate block with the offending line | desk card, run report | rewrites or retires the item; the engine never loosens |
| a blank or inconclusive handle | desk Inventory section | collects the handle; the engine fills nothing |
| an edit conflict (`base_hash` stale) | desk card flagged, cycle report | `apply_edits.py <id> --prefer desk\|vault` |
| a claims review (superseded cite, decayed piece) | `state/claims-review.json`, desk | update, annotate or retire the piece on the site |
| a `watching` claim the gate refused to cite | run report, claims register row | finds a primary or second source, or lets it stay uncitable |
| a team post | the control page's new-post form | writes it; approves it once gated; the sender posts it on its day within `autopilot.grace_days` |
| a partner name in a draft | gate verdict | clears it or the line is cut |
| a Blog row the autopilot held (duplicate slug, title overlap) | `autopilot.py status`, the autopilot log | moves or drops it on the control page |
| the monthly readout and a proposed decision file | run report | agrees or not; only then is the decision file written |
| a missing schedule (a job not seen for days) | `engine status` (`stale`), the session brief's console line | `engine logs <job>`, then `run <job>` dry, then `enable` |

Nothing in that table sends a message to anyone; the person reads the desk,
the console and the run reports. Alerts beyond that are an owner decision.

## 9. Failure handling

| condition | outcome | continues? |
|---|---|---|
| `handles.private.md` missing | gate blocks every item of that stream, reason named | yes, with blocks |
| stream memory missing or wrong stream | gate blocks for that stream | yes |
| cited claim id unknown or superseded | that draft blocks | yes |
| present-tense capability sentence without an evidenced cite | that draft blocks | yes |
| research store unreachable | watch writes the day's log only; planning queries fall back to files and the draft records `queries: files`; gate unaffected | yes |
| corpus root not mounted or not set | corpus memory stops at the gate, reports `root not found` (exit 2) | yes |
| twitterapi.io key missing or a call failing | the X pass and public counts stop with the seeding command or the error; the cycle continues on the primary-source sweep; scoring keeps listening-only records partial | yes |
| Apify budget or actor failure (LinkedIn, only with `--linkedin`) | listener reports partial; `--max` never raised on the schedule | yes |
| twitterapi.io stream dropped | launchd restarts after 90 s; gap visible in the digest | yes |
| platform logins absent | index marked partial from listening; rows render "partial" on the scorecard | yes |
| desk database missing | `desk_sync.py --pull` creates it empty; cycle runs with no decisions, says so | yes |
| note and desk both edited | skip, both kept, flagged | yes |
| a duplicate slug or an overlapping team title | autopilot holds the row | yes |
| a post past `autopilot.grace_days` | not posted; stays `scheduled`, visible in `autopilot.py status` | yes |
| correlation falls at the readout | scorer frozen (`scorer_frozen`), predictions still recorded, no optimisation | yes |
| a step reported but did not log | named in the cycle report as missing | yes |
| anything that would publish for another stream than its own | refused, rule quoted | yes |

The only conditions that stop a cycle are a failed secret resolve in
`cycle.sh` (by design, so nothing runs with an unset token) and a failed
`git` commit in the autopilot when `autopilot.commit` is on (so a run never
sees half-written files).

## 10. Observability, and the one number

- `state/runs.json` and the desk's Runs view: every step, every cycle.
- `engine status` and the session brief's console line: every job, loaded
  or not, last run, stale or ok.
- `state/send-ledger.json` and the autopilot log: every send, before it
  happens.
- the desk scorecard (the dashboard page shows no scorecard since 2026-11-06): the engagement index,
  the negatives guardrail, reach as context, variety, and
  **predicted-versus-actual correlation**, the one number the monthly readout
  is judged on.
- a staleness rule per job (`jobs_status.HOW`), re-checked at every readout.

## 11. Budgets and limits

| what | limit | where enforced |
|---|---|---|
| twitterapi.io (X search, public counts) | USD 0.15 per 1,000 tweets, a page of up to 20 billed for what it returns, at least one tweet a call; `--max` at most 12 per term | `listen.py`, `x_metrics.py` |
| Apify (LinkedIn only) | only with `--linkedin`, never on the schedule | `listen.py` |
| twitterapi.io rules | billed per matched post whether or not connected; start the stream before `rules --apply` | `x_stream.py`, the job's `what` |
| handle checks | one profile lookup per handle per 30 days; never `--force-all` on the schedule | `inventory.py` |
| posts per day per stream, quiet hours | registry guardrails | `guardrails.py` for `publish.py` and the autopilot |
| blogs | two per ISO week, three days apart | blog slots, the weekly editor |
| tests | 60/25/15 budget; one or two per channel | weekly editor |
| headless runs | `cycle.budget_usd`, `corpus.budget_usd` | `cycle.sh`, `corpus_cycle_daily.sh` |
| research store | one model call and one embedding per episode; episodes batched per day | `research_store.py` |
| a scheduler, if adopted later | its public API's rate limit | deferred decision |

## 12. Multi-stream orchestration

- The registry row is the schedule's source: a stream with no confirmed owner,
  no `voice.md`, or autopilot rule "nothing" is read by every step and drafts
  nothing, publishes nothing, posts nothing.
- Each stream has its own listening terms (`themes.json` in its directory), its
  own `signals.json` and raw folder, its own gate memory, its own credentials
  in the keychain, and its own rows on the desk behind the switcher.
- Pair rules are a gate check, not a scheduling rule: an item of one stream
  that mentions a paired stream is checked against the pair rule's wording,
  and vice versa; a `Both` item is split before it is drafted.
- Cross-stream cites are snapshot rows with `from`; a stream never reads
  another's `claims.md` directly.
- `engine onboard-stream <slug>` is the console's path to a second stream;
  it never writes the registry, a decision file does.

## 13. Rollout: what turns on when, for a new brand

| after | orchestration change |
|---|---|
| `engine init`, memory templates filled from the brand's first corpus cycle | `memory.py --list` prints the registry; `claims.md` holds the first graded claims; the gate reads them |
| `setup corpus`, `enable corpus` | the 06:30 corpus job keeps memory current, tighten-only |
| `handles.md` own channels and `handles.private.md` in place, secrets seeded | the gate can pass an item; the X stream's rules can be built |
| `setup cycle`, `enable cycle` | the 07:15 cycle drafts, gates and ingests; the desk fills |
| the first approved publication | the checkpoint: one article and its teasers with a hypothesis and a predicted band, scored at 72 h |
| `enable score`, `enable claims-check` | the nightly measurement and supersession jobs |
| a decision file loosening the stream's autopilot rule per channel | `enable autopilot`: the sender posts Ready rows within the guardrails |
| the first cycle of a month | the first readout; the correlation row appears after five records |
| four weeks of correlation | the inner-loop gate may be opened by a decision file |

## 13b. Hazards found while building, and what now stops them

- **A desk approval can outlive the piece.** An item approved on the desk and
  published by another path would have been written Ready again by the next
  cycle. `publish.py` refuses any item whose title or slug is already a
  Published row in `state/calendar-snapshot.json`.
- **Row creations are not publications.** The publish log records calendar rows
  created at Idea or Ready beside real posts; `score.py` counts only posts on a
  handle and Blog rows set Published.
- **Guardrails are judged at the slot's send time**, 09:00 in
  `autopilot.timezone` on the note's date, not when someone runs the script.
- **Pieces scored first in a batch never got a baseline** until the checkpoint
  rehearsal caught it; the baseline is now computed before the batch.
- **A stale or missing timezone silently moves quiet hours.** `autopilot.timezone`
  ships as `UTC`; a brand sets it once with `config.py set`.

## 14. Decisions this file still needs from the owner

1. **A host for the research store**, or files mode for now.
2. **Whether any condition in §8 should notify anyone**, and how. Today
   nothing does.
3. **The stream's timezone** (`autopilot.timezone`) and its quiet hours in
   `streams.md`, before the autopilot is enabled.
