# Plan v2: one engine, many streams

_Written 2026-10-23 and revised the same day; rewritten for the template on
2026-11-05 with the first stream's specifics removed. `ORCHESTRATION.md` beside
this file says how the steps run: owner per step, cadence, stores and their
single writer, failure handling, rollout. `PLAN-engine-console.md` is the plan
for the console that operates it._

_2026-11-13: Notion is retired (`PLAN-channels-hosting.md` N1 to N4). Where
this plan says Notion row, Notion calendar or notion-sync, read the calendar
notes in `Content/Calendar/`, the lifecycle, and the control page's acts
(approve, schedule, new-post, blog-live); the site reads the published-posts
feed. The text below is kept as written._

## History

Built 2026-09 to 2026-11: a September proof of concept covered the
listening pass, the theme drafts, the gate and a dashboard with a decision
store; an October revision (this plan) added the knowledge layer (claims
register, cites, supersession), the measurement layer (hypothesis, prediction,
scoring, live tests, the monthly readout), the stream registry and the desk;
on 2026-11-05 the second runtime the engine had been paired with was left, the
schedules became `engine.json` `jobs`, the sender became `scripts/autopilot.py`
and the posting guard became a PreToolUse hook, and the repository was turned
into this template with a brand block in place of a brand's name. The
September facts pipeline and partner-amplification phases are carried forward
as Blocks B and C below; nothing else of that history binds a new brand.

## Why this design

Two things shaped it.

1. The engine stopped being a proposal machine. Once a stream's owner removes
   the per-item approval for the theme content kind, the engine approves its
   own theme proposals, the autopilot creates the blog row as Published and
   posts teasers on their dates, and the claim gate plus post-audit are the
   only brake. Facts stay manual; whether a stream posts automatically at all
   is one cell of its row in `streams.md`.
2. A research thread on autonomous content systems laid out what such a
   system looks like when it is built to *learn*: three loops at three speeds,
   a store of atomic dated claims that published content cites, audience
   signals weighted by intent and stored as lessons rather than events, live
   tests with a hypothesis per post, a publishing layer with drafts by
   default, and a compliance layer whose policies sit outside the model. It
   also carried the cautions that matter most here: LLM judges get gamed by
   the loop they score, simulated audiences predict little better than a
   majority guess, and optimising for engagement pulls every post toward the
   same hook.

The plan takes that architecture and fits it to a doctrine that never loosens.
The engine serves **streams**: one business each, with its own memory, voice,
evidence, themes, handles and channels. The root stream is the brand in
`engine.json`; every other stream is registered and drafts nothing until it has
an owner and a voice.

## What the research thread says, and what the engine has

| thread concept | what it means | what the engine has |
|---|---|---|
| Domain knowledge as atomic, dated, sourced claims | A claim with source, date, tier, confidence, topic; superseded by invalidation, never deletion | `status.md` grades every load-bearing claim as evidenced / asserted / intended; `claims.md` is one row per checkable claim with id, grade, source, date, tier, themes, supersession and corroboration; `/corpus-cycle` is the research-to-memory path and is tighten-only |
| Content cites claims | The content-cites-claim edge, filled at draft time | `cites` on every note; `gate_lint` checks each id exists, is not superseded and is corroborated; `claims_check.py` finds the notes whose claim moved |
| Audience knowledge, weighted by intent | Saves, quote posts and substantive replies high; likes low; impressions context only; negatives logged; questions and objections extracted as demand | `listen.py`, `x_stream.py`, `signals.json` (relevance, sentiment and `demand` per theme), `score.py` (weights, negatives, baseline per platform and format, identifiers stripped) |
| Self-knowledge | What the system tried and how it turned out, timestamped and decaying | `lessons.md` with `evidence`, `confidence`, `since`; `reviews.md` (Alpha's standing reviews); `runs.json`; `predictions.json` (predicted beside actual) |
| A combined scorer | Deterministic checks first, a classifier trained on own history, an LLM judge that commits before it sees the candidate; never the judge alone | `gate_lint.py` (deterministic, pinned by fixtures) runs before the model's reading in `claim-gate`; `reviews.md` can only tighten. The gate scores *admissibility*; the second stage (expected performance) is Block C |
| Inner loop (overnight optimisation of prompts and templates) | Evolve skill files and drafts against the scorer; reserve an exploration share | None, by design: gated per stream on four weeks of predicted-versus-actual correlation |
| Middle loop (live tests) | 2 to 5 candidates a week, one variable each, matched sequential slots on organic channels, scored after 72 h, four outcomes, a 60/25/15 budget | `livetests.py`, `tests.json`, the weekly editor step in `/social-cycle --editor` |
| Outer loop (monthly) | Compare predicted with actual; retrain the scorer; rewrite the checklist; decay old lessons | `readout.py` + salon `campaign-retro` on the first cycle of the month; freezes the scorer if the correlation falls |
| Publishing through an MCP, drafts by default, caps outside the agent | A scheduler MCP; a separate scheduled script reads analytics; comments from a third path | Notion row to the brand's site; teasers by the autopilot under the registry's guardrails; the scheduler choice is deferred (open-source constraint) |
| Compliance layer | Pre-call hooks enforce drafts-only, caps, quiet hours, blocked topics; one audit record per action | `guardrails.py` read by `publish.py` and the autopilot; the gate failing closed; `handles.private.md` blocking when absent; the PreToolUse hook refusing any posting command outside the autopilot's job; every run entry names its stream |
| Many brands | Separate scopes per client | `stream` on every record; the registry; per-stream memory, credentials and gate; the brand block for the root stream |

## Decisions that bind the design

Recorded as decision files in the first stream's memory on 2026-10-23 and
2026-10-26; restated here as the engine's rules.

1. **The term is stream.** A stream is one business the engine serves. The
   facts-versus-themes split inside a stream is a *content kind*.
2. **The root stream first.** The brand in `engine.json` is built fully; any
   other stream is registered with an empty memory directory, a candidate
   corpus root, no narrator, no owner, autopilot "nothing", and onboards in
   its own block of work.
3. **Independent but linked.** Streams are isolated by default. A stream may
   name or cite another only under a recorded pair rule in the registry.
4. **One runtime: Claude Code.** `plugins/comms-engine/` is the engine; the
   schedules are `engine.json` `jobs` rendered to launchd per machine.
5. **Loop order: prediction before optimisation.** Live tests and the monthly
   readout come first; the inner loop is gated per stream on four weeks of
   predicted-versus-actual correlation.
6. **Files are the source of what may be claimed; a graph is the store of what
   is being watched.** Claims that content may cite are rows in a markdown
   register. Research findings, candidate claims, sources and demand per theme
   are episodes in a research store (Graphiti, open source, self-hosted; files
   mode until a host is named). A candidate becomes citable only when promoted
   into the register through `/corpus-analyse` and `/corpus-update`,
   tighten-only. The gate and the supersession check read files and never the
   graph.
7. **Objectives.** Engagement signals that show intent (saves, quote posts,
   substantive replies, reposts, link clicks) are an objective for every
   stream. Reach (impressions, followers) is recorded as context and is an
   objective only for a stream that opts in. The north star is a registry
   cell per stream.
8. **Scheduler and compliance layer deferred.** Any choice must be open source.
   Until chosen, `publish.py` and the autopilot enforce the registry's
   guardrails and are the policy layer.
9. **Drafts only for a new stream**, every channel, loosened per channel by a
   recorded decision.
10. **The root stream's memory stays at the root** of `.atelier/memory/`; other
    streams live under `.atelier/memory/streams/<slug>/`.
11. **No stream drafts without a confirmed owner and a `voice.md`.** Owners
    are never named in files; the registry says only whether one is confirmed.
12. **One desk**, with a stream switcher and a `stream` column on the decision
    tables.
13. **Own versus partner handle.** Each stream's `handles.md` lists its own
    handles as own and other streams' handles as partners under the pair rule.
    No shared handles file.
14. **Cross-stream cites are snapshots.** When a pair rule allows it, the citing
    stream copies the claim into its own register as a row marked `from:
    <stream>/<id>`. The supersession check compares the snapshot to the source.
15. **Engagement data starts partial.** Until the LinkedIn and X logins exist,
    the index is computed from what listening captures and marked partial.
16. **The knowledge layer is built strong and the measurement layer thin**, and
    both are complete end to end before anything is deepened.
17. **Test defaults**, revisable at the monthly readout: score at 72 h and 7
    days; weekly slot budget 60 % proven, 25 % structured tests, 15 %
    exploration; a pattern becomes a lesson after two wins in separate periods;
    one or two tests per channel at a time.
18. **Corpus roots are confirmed before they are swept.** A candidate root in
    the registry is never read until its status cell says `confirmed`.

## Principles that bind the generalisation

1. **One stream per output.** Every note, finding, proposal, decision and run
   entry names exactly one `stream`. `stream: Both` fails the single-pillar
   test and is split or killed, never processed.
2. **Each stream has its own memory, and nothing merges.** Voice, status,
   themes, handles, instincts, reviews, lessons and claims are per stream. A
   shared file holds only the registry.
3. **Claims outrank engagement.** The scorer's first stage is the claim gate and
   it is a filter, not a weight. No engagement result, test outcome or lesson
   may loosen what `status.md` allows. Only `/corpus-update --apply` edits it,
   tighten-only.
4. **The objective per stream is a registry row**, never a default.
5. **Nothing publishes beyond the autopilot rule the stream's owner wrote.**
6. **Prediction before optimisation.**
7. **Aggregate audience signals.** Patterns and summaries enter memory; profiles
   of named commenters do not. Identifiers are dropped before anything is
   written.
8. **Files are the source of what may be claimed; the graph is the source of
   what is being watched.** Nothing that gates or publishes depends on a
   service being up.

## Target shape

### The registry

`.atelier/memory/streams.md`, one row per stream, columns: slug, name,
narrator, owner (confirmed or unset, never a name), objectives, autopilot rule,
channels, memory path, corpus root with status (confirmed / candidate), the
five guardrails (drafts-only channels, posts per channel per day, quiet hours,
blocked topics, hold-for-review classes), and pair rules. Nothing that varies
per cycle belongs here. `scripts/memory.py` resolves a stream's directory from
it; an unknown slug raises, never defaults. The first row's slug and name are
the brand block's; `engine init` renames them.

### Per-stream memory

The root stream at the root of `.atelier/memory/`; every other stream at
`.atelier/memory/streams/<slug>/` with the same file set (`voice.md`,
`status.md`, `instincts.md`, `themes.md`, `handles.md` plus a gitignored
`handles.private.md`, `claims.md`, `reviews.md`, `lessons.md`, `calendar.md`,
`campaigns/`, `decisions/`) and an engine-local `themes.json`. `/corpus-cycle`
takes `--stream <slug>` and reads the root from the registry; tighten-only
holds per stream.

### Stream on every record

Notes carry `stream`; `repo.py` refuses to write one without it and flags
`Both`. Every entry in `signals.json`, `queue.json`, `decisions.json`,
`edits.json`, `arguments.json`, `runs.json`, `engagement.json` and the
measurement files carries `stream`; raw listening lands under
`state/raw/<slug>/`. The desk has a switcher and the column. The gate loads the
memory of the item's stream and blocks when it is missing.

### The knowledge layer

- **Claims register.** `.atelier/memory/claims.md` per stream: one row per
  checkable claim with `id` (`C-<slug>-<n>`), the claim, evidence grade
  (evidenced / asserted / intended), source and date, tier (primary,
  institutional, trade, social), `themes`, `supersedes`, `superseded_by`,
  `from` for a snapshot copied from another stream, and `corroboration`
  (primary | two-independent | single | watching). A claim enters content only
  from a primary source or with two independent sources; a single trade or
  social source stays `watching` and the gate treats it as uncitable. Written
  only by `/corpus-update --apply`; a row is never deleted, only superseded.
- **Research store.** A graph per engine, stream on every node, with the
  entity types Claim (candidate; grade, tier, corroboration), Source (tier,
  date), Topic (hashtag; demand), Content (published and queued notes with
  their cites, ingested from the files). The daily watch and the monthly topic
  map write episodes; duplicates across sources merge, a contradicting finding
  invalidates the older edge with its date and never deletes it, and "what did
  we hold on that date" is a query. Promotion into `claims.md` is the only path
  to citability; nothing cites a graph node. Files mode until a host runs.
- **Cites on notes.** `theme-post` writes `cites: [C-...]` for every claim a
  post leans on; `gate_lint` checks each cited id exists and is not superseded,
  and that no present-tense capability sentence lacks a cite at grade
  evidenced. A released fact (Block B) becomes a claim row at grade evidenced.
- **Supersession review.** `scripts/claims_check.py` lists every published or
  queued note whose cited claim was superseded or downgraded since it was
  written, and raises each on the desk as *review: update, annotate or
  retire*. The engine never edits a published piece; a person does.
- **Lessons tied to outcomes.** A lesson in `lessons.md` carries `evidence`
  (item ids), `confidence`, `since` and a decay note; `theme-writer` reads
  lessons by recency weight.

### The measurement layer

- **Hypothesis and prediction on every draft.** Each engine item carries a
  `hypothesis` with one variable (hook form, format, length, angle), a
  `predicted` band (today: the gate's verdict plus the writer's expected
  band), a `test_id` and the planning `query` it answers. `state/predictions.json`
  holds predicted beside actual per item.
- **Scoring.** `engagement.json` grows a record per published item at 72 h and
  7 days: saves, quote posts, substantive replies, profile and link clicks
  high; dwell and plain reposts medium; likes low; impressions as context;
  unfollows, hides and correction-type replies as negatives. Against the
  stream's own baseline for that platform and format. From listening alone
  until the platform logins exist, marked partial. Identifiers stripped before
  the write. A qualitative pass extracts questions, objections, confusion and
  requests into a `demand` score per theme in `signals.json`.
- **The index and the scorecard.** One normalised engagement index per stream
  and one guardrail row for negatives, beside the stream's key results; reach
  as a context column; predicted-versus-actual correlation as a row; a variety
  row (share of distinct hook forms, formats and logics over the last twelve
  posts, the homogenisation guard).
- **Live tests.** Organic channels use matched sequential slots over several
  weeks; each test records its primary metric, guardrails, minimum sample and
  maturation window before the first post. Outcomes: keep, discard, trending,
  inconclusive, in `state/tests.json`. The weekly editor applies the 60/25/15
  budget and holds collisions.
- **Monthly readout.** `campaign-retro` on the first cycle of the month, per
  stream: correlation on the scorecard, lessons promoted or decayed, checklist
  items that predicted nothing rewritten, platform changes logged as dated
  events, the stream's stage (explore, exploit, deepen). If the correlation
  falls, the stream's scorer is frozen until recalibrated.
- **Inner loop, later and gated.** Only on skill files, hooks and templates,
  never on claims; scorer = gate (hard filter) + a classifier on the stream's
  own history + an LLM judge that writes its own answer first; a fixed
  exploration share; a variety measure beside the score. Enabled per stream by
  a decision file citing four weeks of correlation.

### Publishing and compliance

The Notion-to-site path is the website-first release. The registry's
guardrails are enforced by `publish.py` and the autopilot before any call;
every run entry names `stream`, `agent`, `action` and `target`. The scheduler
(open source, one workspace per stream, drafts only) and the compliance layer
are one later decision; the policy table is written so it moves unchanged into
whichever is chosen. Analytics, when the logins exist, are collected by a
separate scheduled script, never by the agent.

## Tools and repos

What runs here: standard-library Python scripts under
`scripts/`, Claude Code agents and skills (this engine's
own plus salon's `campaign-retro`, `hook-writing`, `post-audit` and atelier's
`copywriter`, `brand-voice-keeper`), two MCP servers (Apify for paid listening,
Notion for the calendar), twitterapi.io for X, the Next.js desk over Drizzle
and SQLite, and the deck-reader corpus cycle. The rule for adding a tool: it
must be open source, it must read and write the markdown memory rather than
own a store of its own, and the claim gate must sit above it.

| repo or tool | thread's role | call | why |
|---|---|---|---|
| In-house scripts (stdlib Python) | | **keep, extend** | the loop is small enough that no framework earns its place |
| salon `campaign-retro`, `hook-writing`, `post-audit`; atelier `copywriter` | | **keep** | the monthly readout and the hypothesis writing already have skills |
| twitterapi.io (X), Apify (LinkedIn only) | listening, public counts, comment collection | **keep; X through twitterapi.io only** | X search, our own posts' public counts and the standing stream all go through twitterapi.io; the LinkedIn actors stay behind `--linkedin`. Pay-per-result stays capped at 12 per term |
| marketing skill packs as agent skills | frameworks for hook forms and test design | **adapt, optional** | install into the gitignored `.claude/skills/` as reference; where a framework conflicts with `voice.md` or `instincts.md`, memory wins |
| non-parametric statistics for live tests, keep / discard / trending states | the test-state model | **adapt the method, not the dependency** | ported into `tests.json` and `score.py`. An LLM panel scoring dozens of variants is rejected: that is the judge-gaming the thread warns about |
| autoresearch-style overnight loops | the inner loop | **defer** | gated per stream on four weeks of correlation; runs on skill files, hooks and templates only, never on claims, with the gate as a hard filter in its scorer |
| GEPA (Pareto optimiser) | in place of a plain keep-or-revert ratchet | **defer, preferred over a ratchet** | keeps diverse strategies alive, which is the homogenisation guard the thread asks for |
| cited research-report generators | the daily watch feeder | **adapt, optional** | a report is a *source*, not memory: it lands in the gitignored `Docs/Research/` and goes through `/corpus-analyse` with its tier, never straight into `claims.md` |
| outline-first topic mapping | monthly topic maps | **defer** | the corpus and the themes already give a stream its topic map; revisit when a stream lacks one |
| Graphiti | temporal knowledge graph: the research store | **adopt, as the research store only** | Apache-2.0, self-hosted on FalkorDB or Neo4j, incremental episodes, two timestamps per fact, invalidation instead of deletion. Never the citable store |
| other memory layers | | **reject for now** | none keeps the bi-temporal invalidation the corroboration rule needs |
| Postiz, Mixpost | scheduler MCP, one workspace per stream | **candidate, decision deferred** | open source, self-hostable; known limits: no analytics or comment reading in the MCP, rate-limited public API |
| URL-to-post agents with human review | | **reject** | the engine already has drafting with a decision store and a gate |
| the open X ranking model | engagement sanity check for X | **adapt, optional** | offline; a sanity check on X teasers, never a scorer of record |
| simulated audiences | | **reject for now** | persona agents barely beat a majority guess; at most a filter inside a future inner loop |
| a classifier on own post history | the cheapest honest scorer | **build in-house** | needs scored records first; until it exists the predicted band comes from the gate verdict and the writer |
| an LLM judge that commits before it reads the candidate | second stage of the scorer | **build in-house as a skill** | a `perf-judge` skill that writes its own answer first, then scores; used beside the classifier, never alone |
| hosted compliance platforms | pre-call hooks and an audit log | **defer; conflicts with the open-source rule** | the registry's guardrails enforced by `publish.py` and the autopilot are the policy layer until a trigger fires (a third active stream, accounts the brand does not own, an audit requirement) |

Decided differently from the build guide the thread pointed at, on purpose:

- **Web articles go through Notion to the brand's site, not through pull
  requests and preview deployments.** The site reads the Notion calendar; the
  vault note in `Content/Calendar/` is committed to git, so git is still the
  audit trail. The fix for an invalidated claim is a person editing the Notion
  row, recorded on the note, not a pull request.
- **No paid boost for split tests.** Paid amplification would need an owner
  decision and is not in the plan.
- **The citable claims store is a markdown register; the graph holds the
  research.** Promotion from the graph into the register through
  `/corpus-analyse` and `/corpus-update` is the quality gate the guide puts
  inside the graph.
- **Memory and knowledge are the foundation**, so the register and the cites
  precede the log and the metrics collector.

## The work

Four blocks, in order; inside a block the items are ordered and each names its
acceptance check. Block A is the whole loop for the root stream; B and C follow
it; D onboards one stream at a time and can start any time after A.

### Block A: the full learning loop for the root stream (built)

Every item below is built and tested on fixtures; the dates are in the history
paragraph above.

- **A1. The registry and the term.** `streams.md`; `memory.py` `streams()` and
  `stream_dir(slug)`; `memory.py --list`. An unknown slug raises, never defaults.
- **A2. Per-stream memory directories** under `streams/<slug>/` with the file
  set present and empty; `memory.py --stream <slug>` returns empty rosters,
  never the root's.
- **A3. `stream` on every record.** `repo.py` refuses an item without one;
  `state_check.py` checks every state file; `runlog.py` requires it.
- **A4. The claims register.** `claims.md`, parsed and validated by
  `memory.load_claims`; `/corpus-update` carries the claims actions
  (`add`, `tighten`, `supersede`, `corroborate`), tighten-only.
- **A5. Cites on drafts and in the gate.** `lint: cites`; a draft citing a
  superseded or uncorroborated id blocks.
- **A6. The supersession and decay check.** `claims_check.py` keeps a register
  snapshot and change log in `state/`, writes `claims-review.json`; the
  dashboard's to-do list shows each review.
- **A7. The gate per stream.** `lint: stream` first; every check reads the
  item's stream memory; a missing directory or companion blocks with the path
  named.
- **A8. Planning queries, then hypothesis, prediction and test id on every
  draft.** `plan_queries.py` writes `state/planning.json`; `lint: hypothesis`
  marks a draft without the four fields pass-with-edits; `repo.py --all`
  appends to `state/predictions.json`.
- **A9. Scoring at 72 h and 7 days.** `score.py` reads platform counts typed
  into `state/metrics-input/<id>.json`, the x-stream and the listening files;
  weights by intent; baseline after three records per platform and format;
  `--demand` writes demand per theme.
- **Checkpoint.** `tests/test_checkpoint_rehearsal.py` runs one month of the
  loop through the real scripts on fixtures (plan, drafts, gate, ingest,
  predictions, publish record, scoring, actual beside predicted, a live test
  closing, a superseded cite raising its notes, the readout). The real
  checkpoint for a new brand is one approved publication and 72 hours.
- **A10. The index and the scorecard rows.** `metrics.json`: engagement index,
  negatives guardrail, reach context, correlation, variety; rows render
  "partial" where the source is listening only; the correlation is blank, not
  zero, before five records.
- **A11. Tests and outcomes.** `livetests.py` (new, assign, close, budget);
  the weekly editor applies the budget; two wins in separate periods write a
  lesson, one win writes "trending".
- **A12. The monthly readout.** `readout.py` computes the data and freezes the
  scorer; the prose readout is `/social-cycle --readout` running salon's
  `campaign-retro`.
- **A13. Guardrails read from the registry.** `guardrails.py` for `publish.py`
  and the autopilot; `secrets.get_secret(name, stream=...)` scopes
  credentials per stream so one stream's token can never post for another.
- **A14. The desk switcher and column.** `stream` on the mirror tables and the
  views; `desk_sync.py --pull` routes a standing review to its stream's own
  `reviews.md`.
- **A15. Record and document.** The six standing rules in `CLAUDE.md`, this
  file, `ORCHESTRATION.md`, the README's coverage table.
- **A16. Research watch, the research store and the monthly topic map.**
  `research_store.py` in files mode: the watch log, candidate merging and
  corroboration, the topic map; `research-store/` holds the compose file and
  the README naming the two owner decisions (a host; an embedder).
- **A17. Engagement acts in the loop.** `engage.py` acts with shape, tier and
  outcome; partner reposts in `score.py`; the golden-hour checklist on a
  published card; the engagement job runs the pass in dry-run.

### Block B: facts pipeline

Intake for a shipped component, newsroom register, certification sweep, release
counter, with one addition: a released fact becomes a `claims.md` row at grade
evidenced, so the register's primary feed is the facts pipeline. `/announce` is
the assisted path that exists today for a partner announcement's checks, rows
and record. Acceptance: the new row appearing on release.

### Block C: analytics and depth

Needs the LinkedIn and X logins. The separate analytics collector at 24 h, 72 h
and 7 days under the API rate limit, turning the partial index full; site
analytics per theme from the website's own analytics layer, as a scheduled
script joined to the calendar by slug, which is the only channel with a true
split test (headline variants, scored after weeks); the full signal set; desk
views per loop; partners amplify; the website webhook; Alpha controls; the
inner-loop gate (a decision file citing four weeks of correlation before any
stream's inner loop is enabled); the second scorer stage (the classifier and
the commit-first judge).

### Block D: one stream at a time

For each: the owner confirms the stream (the registry says `confirmed`, never
who); the corpus root is confirmed and swept with `/corpus-cycle --stream
<slug>`; `voice.md`, `status.md`, `themes.md`, `handles.md` and `claims.md` are
filled from its briefs, tighten-only; listening and the gate run for it;
autopilot stays "nothing" until a decision loosens it per channel.
`engine onboard-stream <slug>` is the console's path. Acceptance: the
stream drafts nothing until its registry row says `confirmed` and its
`voice.md` exists; its gate reads only its own memory; a cross-stream cite is a
snapshot row with `from`.

### Deferred: one later decision

The scheduler (open source, one workspace per stream, drafts only), the
compliance layer, and the inner loop itself. Opened after Block C and four
weeks of correlation.

## What the owner supplies, when asked

- A confirmed owner and a `voice.md` for each stream before it drafts
  (decision 11).
- The `Stream` select on the Notion Social Content Calendar, with the stream
  names as `streams.md` spells them.
- The LinkedIn and X OAuth logins for the autopilot, which turn the partial
  index into a full one.
- Confirmation of each candidate corpus root before that stream's first sweep.
- A host for the research store's database (FalkorDB or Neo4j); it runs in
  files mode until one is named.
- The scheduler and compliance-layer choice, when the deferred decision opens.

## Verification

- **Block A.** The test suite passes on fixtures; a note without `stream` is
  refused; an item gated against another stream's memory blocks with the
  reason named; every claim quoted in the gate fixtures resolves to a register
  row; every new draft carries `cites`, `hypothesis` and `predicted`;
  downgrading a fixture claim makes `claims_check.py` raise the notes that cite
  it; a scored item shows weighted signals, negatives and no identifier; the
  scorecard shows the index, the guardrail row and the correlation row; a
  sweep finding becomes a `watching` claim the gate refuses to cite until
  corroborated; a placed comment carries shape, tier and outcome and nothing
  in the engagement pass can send.
- **Block B.** A released fact appears as an evidenced row in `claims.md`.
- **Block C.** The index is no longer marked partial; the analytics job runs on
  its own schedule and the agent never calls it; the inner loop is enabled for a
  stream only by a decision file citing four weeks of correlation.
- **Block D.** A stream drafts nothing until its registry row says `confirmed`
  and its `voice.md` exists; its gate reads only its own memory; a cross-stream
  cite is a snapshot row with `from`.
