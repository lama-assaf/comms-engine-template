# glossary

The engine's own terms first, then the brand's. Get these exactly right in
every output; the audience notices a wrong definition. The brand's domain terms
are added below by `/corpus-update --apply`, each with the sources that use it
and the forms to avoid. Overrides tool defaults on conflict.

---

## streams (the unit the engine serves)

**stream**: one business the engine serves, with its own narrator, voice,
evidence, themes, handles and channels. The registry is `streams.md`; the
brand's own stream is the first row and its memory is this directory. Settled
2026-10-23 in the plan-v2 grilling.
_Avoid_: business, brand (for the row), tenant, client

**content kind**: facts or themes, the two kinds of content inside one stream.
Facts are announcements and releases, approved as written and released by hand;
themes are the engine's argued posts under a hashtag from `themes.md`.
_Avoid_: stream (in this sense)

**pair rule**: the one way a stream may name or cite another: a row in
`streams.md` from one slug to another with the exact wording allowed. Without a
row, the other stream is not named.

**narrator**: the single register a stream speaks in (an authority, a category
definer, a newsroom). Two narrators are two streams.

## themes and licence

**theme**: a hashtag the brand means to own in public debate, defined as a row
of `themes.md`. A hashtag not in that table is not a theme. The engine never
adds, merges or renames one.

**fact (the fact a theme links back to)**: the evidenced event or artefact a
theme post may link to today, named in the `fact` column of `themes.md` and
graded in `status.md`. A theme with no fact is argued through a logic instead.

**licence grade**: how freely a theme may be argued, read from the licence table
of `themes.md`: `licensed` (argue freely inside the voice),
`licensed-with-hedge` (only with the cleared hedge named in the basis), `held`
(the layer beneath has not shipped; argue the principle only, no capability,
partner or date). A theme is licensed by the stack layer beneath it, and a
layer that has not shipped yields no theme.

**held slot**: a reactive calendar slot kept open under a theme for a regulatory
or standards development, filled only when a listening finding passes the
trigger test, otherwise left empty. Held slots are how the 20% reactive share
of the cadence is reserved without inventing news.

**logic**: a reusable argument shape from `logics.md`, numbered `L<n>`, named
per theme in the `logics` column of `themes.md`.

## knowledge (what may be claimed, what is being watched)

**claims register**: the per-stream list of checkable claims that content may
cite, each with its evidence grade, source, tier, corroboration and what
superseded it (`claims.md`). A claim is citable only as a row here.
_Avoid_: claims store, knowledge graph, claims table

**claim grade**: `evidenced` (a primary artefact shows it true today),
`asserted` (a dated document says it; the brand's own decks are assertions),
`intended` (a plan or an exploration, with its source). A present-tense
capability sentence needs a row at `evidenced`.

**tier**: where a claim's source sits: `primary` (the issuing party's own
executed artefact, a regulator, a standards body, a published release),
`institutional`, `trade`, `social`.

**corroboration**: `primary`, `two-independent`, `single`, `watching`. The gate
treats `single` and `watching` as uncitable.

**supersession**: how a claim changes: a new row plus `superseded_by` on the old
one. Rows are never deleted, never raised by hand. The latest dated source
governs a conflict.

**research store**: the temporal graph of findings, candidate claims, sources
and demand under watch, where duplicates merge and a contradiction invalidates
rather than deletes. Nothing may cite it until promoted into the claims
register. Settled 2026-10-23.
_Avoid_: knowledge graph, memory graph, the graph (as if it held the claims)

**promotion**: the only path from the research store into the claims register,
tighten-only, through the corpus analyse and update steps.
_Avoid_: sync, import, export

**tighten-only**: the rule every write to shared memory obeys: a grade may fall,
a term may be added to a denylist, a hedge may be required; nothing is loosened
except by a decision file.

## gate and release

**Alpha / Beta**: Alpha is the human channel and the human reviewer: the person
who approves, clears a partner and records a decision. Beta is the agentic
channel: the engine's drafting, listening and gating. One narrative, two
grammars; Alpha sets and guards the body of knowledge, Beta systematises its
expression.

**gate**: the deterministic check every draft passes before it enters Alpha's
queue and again before publish (`scripts/gate_lint.py`): stream, status words,
stealth, partner tags, no-claim panel, cites, CTA. It returns pass, edit or
block with the offending line quoted, and it fails closed: a missing denylist
blocks.

**autopilot cell**: the `autopilot` column of a stream's registry row, the only
loosening a stream has. `nothing` means every channel is drafts-only; a rule
names what may leave the queue without a person, per content kind and channel.
Changed only by a decision file.

**hold for review**: the classes of content that wait for Alpha whatever the
autopilot cell says: statistics not in the register, a named counterparty not
on the cleared list, a date `status.md` does not carry, a partner name without
clearance, any certification or accreditation word.

**cleared**: of a partner, named in a published release of the brand's own or
in a decision file, for one role; of a phrasing, published and defensible, so a
draft may reuse it verbatim. Clearance to name is not clearance to tag: the
tag needs a `verified` handle in `handles.md`.

**denylist / stealth**: the terms a draft may not echo, kept in the gitignored
`handles.private.md` and nowhere else. Stealth is stealth until a decision
clears it.

**single-pillar test**: the question asked before any output: which single
stream and theme does it serve. "Both" means split it; "neither" means kill it.

**the no-claim panel**: the "what we do not claim" section a theme post carries,
in the frontmatter, naming the hedge each sentence stands on.

## measurement and learning

**qualified citation**: a third-party reference to the brand by venue tier
(regulator, standards body, institutional press). The authority currency;
scored instead of impressions.

**intent engagement**: saves, quote posts, substantive replies, reposts, link
clicks: the signals that show a reader meant it. An objective for every stream;
reach is an objective only for a stream that opts in.

**vanity metrics**: impressions, follower counts, throughput figures. Recorded
as context, never a goal.

**hypothesis / prediction / test**: every draft names one variable it tests
(`hypothesis`), the planning query it answers (`query`), and a predicted band
(`predicted`: below, baseline, above) before it leaves the queue; the record
lands in `state/predictions.json` and the outcome in `state/tests.json`. A
kept pattern becomes a lesson with `since` and a decay date.

**readout**: the monthly pass that scores the month, promotes kept patterns
into `lessons.md`, decays old ones and freezes the scorer when correlation drops.

**desk**: the local review app over Alpha's decisions, edits, argument lines
and standing reviews. Those four tables exist nowhere else until
`desk_sync.py --pull` writes them to the notes and to `reviews.md`.

**calendar note**: `Content/Calendar/<title>.md`, the record of one item,
written only by `scripts/repo.py`; `state/queue.json` is a derived index.

## the brand's terms

_Added by `/corpus-update --apply`, grouped by domain, each with the forms to
avoid. None yet._
