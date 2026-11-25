# 2. The communications method

The engine implements a method, and the method is written down in memory
before anything is drafted. This chapter is the short form; the operative
rules live in `.atelier/memory/` (`instincts.md`, `voice.md`, `status.md`,
`logics.md`, `themes.md`) and every draft is checked against them, not against
this page.

## 2.1 One business, one voice; a second business is a second stream

Every output serves one business and speaks in that business's voice. If two
businesses share an owner, a technology or a story, they are two **streams**
on the same engine, each with its own memory, themes, handles and channels,
and a **pair rule** in `streams.md` governs every cross-mention: how one may
cite the other, and in which words. "Both" means two outputs; "neither" means
kill it. Chapter 6 is the onboarding of a second stream.

## 2.2 Two content kinds

- **Facts**: launches, qualifications, partners joining. Jointly authored with
  the partner, a dedicated approval flow, **manual release only**, website
  first, then teasers. The engine never automates facts. `/announce` is the
  assisted path: it checks copy against the gate, clears the partner, writes
  the announcement as one calendar item and stages the posts; a person
  approves it, marks the article live and publishes.
- **Themes**: insight posts that claim one of the business's theme hashtags
  and link back to a fact. AI-assisted sourcing, drafting and distribution. A
  theme post is a full piece on the business's own site plus a LinkedIn
  teaser and an X teaser, each carrying the hashtag, cleared partner tags and
  a CTA back to the piece (`params.site.post_url` in `engine.json`).

## 2.3 Alpha and Beta

Alpha is the irreducible human judgement; Beta is what can be systematised.
Alpha owns the narratives, decides which fact may be claimed and when, writes
the theme insight, runs the partner approval flow, reads the listener's
signals into decisions, decides when a theme changes. Beta keeps the content
repository, the theme and handle inventory, sources and drafts, tags and
CTAs, and listens. The engine industrialises Beta so Alpha only decides.

By default every channel is drafts-only: the engine proposes, a person acts.
A business that wants more sets the stream's `autopilot` to `by switch` in its
setup (`brand.json`, chapter 1), once, on a dated decision file. From then on
each kind of send (post, reply, comment, like, repost, quote) follows its
**review mode** for that stream and channel: `review`, the default, waits for
a person; `auto`, turned on by a person as a recorded act on the dashboard's
Autonomy page, lets whatever passes the automatic checks go out and leaves
whatever fails in the queue. Nothing in `auto` waits for anyone, which is why
the same page has a pause for the whole stream, the list of what was sent
without review and a take down on each. Facts stay manual whatever the mode.

## 2.4 Themes and their licence

A theme is a hashtag the business wants to lead the debate under, with a
differentiator (what the business says that nobody else does) and the fact
it may link back to. `themes.md` holds the register: eight rows in the shape
the scripts parse, and no hashtags until the business writes its own.

A theme is **licensed by the layer beneath it**: a layer that has not shipped
yields no theme. Each hashtag is graded against `status.md` as `licensed`,
`licensed-with-hedge` or `held`, and the register says what a held theme may
still argue (the standards argument, the coordination problem, never a
capability). A hashtag not in `themes.md` is not a theme; a term in the
engine's search file (`themes.json`) with no theme row, or a row with no term,
is an error rather than a silent skip.

## 2.5 The claim gate

"Zero claims of live or deployed capability ahead of delivery." Every draft
passes the gate before it enters the queue and again before publish, and the
gate returns pass, pass-with-edits or block with the offending line quoted.
The gate is three layers, and only code writes a verdict:

- **Hard limits, in code, in every mode.** `scripts/gate_lint.py` and
  `channels.send()` decide what must never fail: the stream, the stealth
  denylist, status words, partner tags, cites that are current and bound to
  their sentence, pair rules, the account, dedupe, caps and quiet hours. No
  switch and no reviewer turns one off.
- **Judgement, by two reviewers whose output code checks.** The `gatekeeper`
  agent and a second reviewer with a different brief
  (`salon:adversarial-refinement`) each return findings per sentence: is it a
  claim, which row of `claims.md` it cites, the words of that row it rests
  on, supported or not. They write nothing. `scripts/review.py` checks that
  the quoted words are in that row, that every claim sentence has its own
  cite, that a present-tense capability sentence cites a row at grade
  evidenced, and then writes the verdict and its stamp itself, keyed by the
  hash of the text. Two reviewers who disagree are a block. The engine
  approves a post on its own only on a verdict of pass with a current stamp.
- **House style, as advice.** Hook length, the tag line, CTA wording, shape
  and the fixed "what we do not claim" form are the reviewers' to judge.
  Each stays a code check, whose finding keeps a draft from a clean pass,
  until a person lists it under `house_style.retired` in the stream's
  `gate-rules.json` **and** the reviewers have caught every case of the
  labelled set that the rule should flag
  (`engine eval gate --live`, paid; `--status` shows where each rule
  stands). The template ships with none retired.

The rules the gate enforces come from memory, as data rather than code:

- a status word the business has not earned is never used: the words, the
  cleared hedges and the capability verbs are the business's own, written
  from its `status.md` into `.atelier/memory/gate-rules.json` (the template
  ships the lists empty; a rules file that does not read blocks);
- specifies versus implements: a design property never wears the present
  tense; what is specified is not what is deployed;
- a pitch is not a partner: every partner name needs clearance; unsigned
  parties carry "in discussion, participation not confirmed";
- no date we cannot source; `status.md` outranks `project.md`;
- a claim comes only from `claims.md` (grade `evidenced` for a present-tense
  capability sentence) or a primary source cited in the piece;
- statistics and named counterparties hold for human review: the kind `hold`
  of the review switch, which waits for a person's release on `review` and
  passes without one only where a person turned it to `auto`;
- stealth is stealth: the parties in `handles.private.md` are never named,
  and a checkout without that file blocks everything.

## 2.6 Voice, logic, proof

Sober beats hype: if a regulator would wince, rewrite it. Banned:
"revolutionary", "game-changing", committee-speak, unverified statistics. A
flat draft is usually missing an argument structure, not an adjective:
`logics.md` holds the argument shapes that work for the business, and names
which of them need nothing shipped and so are the evergreen floor. Every
output sits on an evidence chain (ship, benchmark, certify, publish, cite,
compound), and proposed must look proposed in any picture we publish.

Posts that all read alike are a fault too. `.atelier/memory/formats.json`
lists the formats a stream may use (theme post with teasers, X thread, short
take, quote commentary, question, data note, motion card, case story), each
with its own structure and the channels it fits; the five-part theme post is
one of them, not the only one. For every draft `plan_queries.py` draws a
format and a logic, weighted by how past posts of that kind scored and inside
the 60/25/15 budget of proven, variation and experiment, and writes the seed
and the draw on the note so the choice can be replayed. The writer then
produces three candidates that differ in one named variable; a ranking picks
the one that goes to the gate, and the other two stay on the note as
alternatives a person can swap in (`repo.py --swap N`). Sharing a format,
logic and opener with recent posts is an edit the gate asks for, never a
block.

## 2.7 Cadence and channels

- 70% evergreen, 20% reactive, 10% milestone; no evergreen post repeats
  within a quarter; platform-native re-cuts, never identical text in three
  places.
- Two engine blogs per ISO week, at least three days apart; everything else
  is social only. Teasers go out on their date; the article link is a first
  reply on X and a first comment on LinkedIn, never in the LinkedIn body.
  Answer "Link?" with the link alone.
- Posts per channel per day, the sending window and the quiet hours are the
  guardrails row of `streams.md`, judged in `params.autopilot.timezone`
  (`config.py set autopilot.timezone <zone>`; UTC until set).
- Website first: a piece is live on the business's site before any teaser.
  The site reads the published-posts feed built from the notes; marking the
  article live on the control page is what publishes, and a person makes it.
- Approved announcement copy is final: fix the rules, not the copy.
- Every post has a golden-hour engagement plan; replies and comments are
  drafted in dry-run and sent by a person's approve-and-send, or by the
  stream's review mode where it is `auto`; replies are summarised as
  patterns, never stored per person.
- Reactions are sends like any other. A like, a repost or a quote goes
  through `channels.send()`: one reaction per target ever, inside the
  stream's `reactions_per_day` and its quiet hours, and only on an eligible
  target (its author a verified cleared handle, on the watchlist, or replying
  to our own post; its text clear of the stealth list, status words and pair
  rules). A quote carries our words and takes the full text gate. A like on X
  stays one click by a person unless a dated owner sign-off is recorded,
  because X's rules require a like to be initiated by the user. The plan and
  the record (`state/reactions.json`) hold a post id, a tier and a theme,
  never a handle.

## 2.8 Learning loop

The engine learns: one variable per hypothesis on every draft, a predicted
band before it leaves the queue, scoring at 72 hours and 7 days, live tests
closed on Fridays, a monthly readout judged on one number (predicted versus
actual correlation), and lessons promoted to `lessons.md` only after two wins
in separate periods. Nothing tunes itself until four weeks of correlation
exist. The six standing rules are in `CLAUDE.md`.

## 2.9 What the listener does

The `listener` runs X search on one term per theme (twitterapi.io, at most 12
results per term, a few cents a pass) and a primary-source sweep of the
issuing bodies, regulators and standards bodies the business's themes depend
on. Findings are graded per theme, with a content or conversation route or an
explicit `none`, and a held-slot test asks whether a document read in full
within 48 hours changes what an organisation must prove. Statistics and
third-party claims are held for a person. The result is `state/signals.json`,
and the session brief opens with it.
