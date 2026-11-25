# decision: review becomes a switch, output varies, reactions run within limits

date: 2026-11-13
status: accepted

## context

The engine drafted, gated and then waited for a person on every send, its posts
read too alike, and its checks were rigid: house style blocked in code beside
the limits that must never fail. Setting up a new project meant editing cells
in three markdown tables and finding the way around a long `engine.json`. The
owner asked for less waiting, more variety, likes and reposts, and an easier
setup. `PLAN-autonomy.md` at the root is the plan built on the answers below.

## decision

The owner's answers, 2026-11-13:

1. **"Less deterministic" means both.** Posts read too alike, and the checks
   are too rigid. Writing gains formats, a weighted draw and candidates; house
   style moves from blocking code to a reviewer whose output code verifies.
2. **This repository migrates in steps.** No new codebase.
3. **Review is a switch per stream, channel and kind.** `review` is the
   default. With a kind switched to `auto`, nothing of that kind waits for a
   person: whatever passes the automatic checks goes out, and whatever fails
   stays in the queue. This rewords standing rule 1.
4. **The hold for review becomes a switch too.** The statistics, partner and
   certification class is the kind `hold`; with it on `auto` the hold check
   passes without a release act. Every other check runs in both modes. This
   rewords standing rule 4 and step D3 of `PLAN-channels-hosting.md`, which
   said the hold would become a dashboard switch when the owner relaxed it.
5. **Likes and reposts run automatically, within limits, behind a switch.**
   Per-day caps, one reaction per target ever, quiet hours and an eligible
   target. Automatic likes on X additionally wait for a dated owner sign-off
   (`channels.reactions_signoff.<stream>`), because X has restricted them.
6. **Setup is one small file and a guided setup.** `brand.json` at the root,
   written by `engine.py init` or the dashboard's Setup page; `engine.json`
   stays as shipped defaults; the `streams.md` tables are rendered from
   `brand.json` by one writer. No YAML.

What does not change: a stream whose owner is `unset` or whose `autopilot` is
`nothing` sends nothing by any path; a mode is turned to `auto` by a person, as
a recorded act with a role and a time; every send goes through
`channels.send()`; the stream check, the stealth denylist, current cites bound
to their sentence, pair rules, account, dedupe, caps and quiet hours are code
and run in every mode; a per-stream pause stops everything at once.

## alternatives considered

- **A new codebase in the fresh shape.** Rejected: the claims register, the
  one sender, the lifecycle, the acts and the tests are right and would be
  rebuilt for nothing.
- **Keep a person on every send and only widen the writing.** Rejected: the
  waiting was half of the complaint.
- **YAML for the setup file.** Rejected: a second config format beside the
  JSON every script reads, and YAML reads a bare `off`, `no` or `on` as true
  or false, which are the words the switches use.
- **Automatic likes on X without a sign-off.** Rejected: the account is what is
  at stake.

## consequences

We gain posts that leave without a person where the owner chose that, more
varied writing, reactions, and a setup a new project can finish in one sitting.

We give up the guarantee that a person read every send. With review off and
more model judgment, a wrong claim can ship. Held down by sentence-level cites
in code, two reviewers that must agree, a labelled set before any code rule is
retired, the pause, the sent-without-review list and one-click take down.

We watch for: a take down of something sent without review, a reviewer that
misses a should-block case in the labelled set, a platform notice about
automated reactions, and the day's model spend.

## review

At the first monthly readout after a stream runs a kind on `auto`, and at once
on any take down of an unreviewed send or any platform notice about automation.
