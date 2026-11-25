# streams - the registry of the businesses the engine serves

One row per **stream** (glossary: one business the engine serves, with its own
narrator, voice, evidence, themes, handles and channels). Every script resolves
a stream's memory from this file through its `memory` column;
`scripts/memory.py` raises on a slug that is not here and
never defaults. The first row is the brand's own stream: its slug is
`brand.json` `brand.slug`, its memory is this directory, and `engine.py init`
renders its cells (slug and name, in all three tables) when the brand is
stamped. Prose in this file is not renamed; keep the brand out of it.

**Rules that bind this file.** The rows of its three tables are rendered from
`brand.json` at the repository root by `engine.py apply`, the one writer: a
person changes the setup (`engine.py init`, the dashboard's Setup page), on a
recorded decision, and never edits a row here. `engine.py doctor` fails when
the two disagree. The prose is a person's. Nothing that varies per cycle
belongs here. **Owners are
never written in this file**: the `owner` column says only whether one is
confirmed; who it is, ask the operator. A stream whose `owner` is `unset`, whose
memory directory has no `voice.md`, or whose `autopilot` is `nothing` drafts
nothing, publishes nothing and posts nothing, by every path. The three tables
are joined by `slug`; a slug missing from any of them is an error, not a skip.

## registry

| slug | name | narrator | owner | objectives | autopilot | channels | memory | corpus root | corpus status |
|---|---|---|---|---|---|---|---|---|---|
| acme | Acme | - (set at onboarding) | unset | intent engagement (saves, quote posts, substantive replies, reposts, link clicks); reach: not opted in; north star: set at onboarding | nothing | - | .atelier/memory | set by `engine.py setup corpus` | candidate |

What each cell holds:

- `narrator`: the one register this stream speaks in (an authority, a category
  definer, a newsroom). A stream has one narrator; two narrators are two streams.
- `owner`: `confirmed` or `unset`, nothing else. Confirmed on a decision file.
- `objectives`: what the stream is scored on. Reach is an objective only for a
  stream that opts in; impressions and follower counts are context, never a goal.
- `autopilot`: the only loosening a stream has. `nothing` means every channel is
  drafts-only. `by switch` means each kind of send follows its review mode
  (`review` or `auto`, per channel), set by a person on the dashboard and off
  by default. A rule names, per content kind and channel, what may leave the
  queue without a person (for example: themes: Blog row created Published after
  audit and gate pass; LinkedIn and X teasers created Ready; facts: manual). It
  changes only by a decision file in that stream's `decisions/` (plan decision 9).
- `channels`: the stream's own handles as prose, mirrored row by row in its
  `handles.md` under `own channels`. `-` until collected.
- `memory`: the stream's memory directory, relative to the repository root. The
  brand's own stream is this root; every other stream lives under `streams/<slug>/`
  (see `streams/README.md`).
- `corpus root`: where the stream's strategy sources live. The path itself is
  written by `engine.py setup corpus` into `engine.local.json`, never here.
- `corpus status`: `candidate` until the corpus has been swept once, then `confirmed`.

## guardrails

Read by `scripts/guardrails.py` before anything leaves:
`publish.py` asks it before writing a Ready row and the autopilot asks it before
sending. A refusal quotes the cell, so a person reads why. The cells are parsed,
so they keep these forms:

- `drafts-only channels`: `all`, `none`, or channel names from Blog, LinkedIn, X;
  `none for themes; all for facts` reads as none for the theme kind.
- `posts per channel per day`: `X 2; LinkedIn 1; Blog 2 per ISO week, at least 3 days apart`.
- `quiet hours`: `weekends; before 08:00 and after 18:00`, judged in
  `engine.json` `autopilot.timezone`; `all hours until onboarded` blocks every send.
- `blocked topics` and `hold for review`: prose the gate and a reviewer read. The
  hold-for-review classes from the build guide are statistics not in `claims.md`,
  a named counterparty not on the cleared list, a date `status.md` does not carry,
  any partner name without clearance, and any certification or accreditation word.

Defaults are revisable at the monthly readout; a change is dated in the log below.

| slug | drafts-only channels | posts per channel per day | quiet hours | blocked topics | hold for review |
|---|---|---|---|---|---|
| acme | all | X 0; LinkedIn 0; Blog 0 per ISO week | all hours until onboarded | everything, until this stream's `instincts.md` never-say lines and its `handles.private.md` denylist are written | everything |

## pair rules

Streams are isolated by default (plan decision 3). A stream may name or cite
another only under a row here; the gate checks the line against the rule.
Cross-stream cites are snapshot rows marked `from: <stream>/<id>` in the citing
stream's `claims.md` (decision 14). Both `from` and `to` must be registry slugs.
The row below is a placeholder showing the shape: a stream to itself, no rule.
Replace it with the first real pair when a second stream is registered, and
write the rule in the words the gate should hold a line to (for example, cite
only as "the flagship deployment of <brand>'s platform"; never an equal narrator).

| from | to | rule | basis |
|---|---|---|---|
| acme | acme | none recorded; a stream names no other stream until a row from it to that stream is written here | plan decision 3 |

## registry log

- 2026-11-13: the tables are rendered from `brand.json` (`engine.py apply`);
  `autopilot` gains the value `by switch`
  (`decisions/2026-11-13-autonomy-variety-engagement.md`).
- 2026-11-05: template created with one placeholder row (`acme`), owner unset,
  autopilot `nothing`, guardrails closed. `engine.py init --slug <slug> --name <Name>`
  renames the slug and name cells; a person then confirms the owner on a decision.
