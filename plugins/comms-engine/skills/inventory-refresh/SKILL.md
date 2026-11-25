---
name: inventory-refresh
description: Keep the partner and handles inventory current on a schedule - confirm recorded X handles that are past the 30-day window, stamp their last_verified, and route blanks, LinkedIn slugs and inconclusive checks to Alpha. Runs as a step in /social-cycle; also use when the user asks whether a handle is still good or why a partner has no tag.
---

# inventory-refresh

The Beta half of *"theme, partner and handles inventory kept current"*. The
inventory is `.atelier/memory/handles.md`, the one table every runtime reads,
and the only one; no `inventory.json` exists. This skill keeps its `status` and
`last_verified` columns honest. Deciding who may be tagged is Alpha's, and
nothing here adds a partner.

## the threshold

One number governs the flag and the spend: a row is stale when its
`last_verified` is more than **30 days** old, or is blank (`-`) because the
status was never established. Stale rows get the paid profile check. Everything else does
not, which is why a second run inside the window costs nothing and the bill
lands at about one twitterapi.io profile lookup per handle per month rather
than one per handle per cycle.

A handle that a person added or edited since the last run is due whatever its
date says: `last_verified` records when a *status* was established, so a date
that predates the handle refers to something else. `state/inventory-ledger.json`
carries the handle each row held at the last run and is what makes that
comparison; it is run state, next to `decisions.json` and `edits.json`, not a
second inventory.

## inputs

1. `.atelier/memory/handles.md`: own channels, cleared partners, standards
   bodies; per row a `verified`/`collect` status, the themes it may be tagged
   on, and a `last_verified` date.
2. `state/inventory-ledger.json`: what the last run saw.
   Absent on a first run, which is not an error: with no previous run, the
   recorded dates are the only authority.
3. `.atelier/memory/handles.private.md`: present or absent only. Stealth and
   unsigned-draft parties are never tag targets and never enter a report.

## workflow

1. `engine inventory`: no flags on the
   schedule. It prints four kinds of line: `fresh` (inside the window, not
   called), `for Alpha` (nothing the engine may check), `due`, and `checked`
   with the result.
2. Read the result of each check:
   - **confirmed**: the script has already written today's date onto the row,
     and flipped `collect` to `verified` where every non-blank handle on that
     row was confirmed. Nothing more to do.
   - **inconclusive**: the handle does not exist, the account is suspended, or
     the profile came back under another name (twitterapi.io `user/info`).
     Nothing was written. Report it; a handle that cannot be shown to resolve
     is not a handle to tag.
   - **error**: the call failed. Report it as an engine problem, not as a
     finding about the partner.
3. Collect the `for Alpha` lines into the cycle report, grouped:
   - blank X handles on cleared partners, the collection work the partners key
     result measures;
   - the brand's own blank **LinkedIn slug**, which is routed to Alpha by
     design: the engine has no authority to establish it and will not guess one;
   - LinkedIn slugs already recorded, which a person confirms once.
4. Say the count plainly in the `/social-cycle` report: rows checked, rows
   confirmed, rows still inside the window, rows waiting on Alpha. The partners
   key result reads *n of m partners with handles* off exactly that.

## flags

- `--dry-run`: print what is due and call nothing. Use it to answer "what would
  this cost" without spending.
- `--force-all`: check every recorded X handle regardless of its date, in the
  spirit of `listen.py --linkedin`: a deliberate full sweep a person asks for.
  Never pass it on the schedule, and never on your own initiative.
- `--window N`: a different staleness window for one run. The desk reads the
  default, so a changed window is a one-off investigation, not a new policy.

## never

- **Add, remove or rename a row.** A partner is never added without Alpha, and
  this skill has no path to it. The script rewrites `status` and `last_verified`
  cells and nothing else.
- **Guess a handle or a slug.** A blank cell is a value the engine has no
  authority to establish. An obvious blank cannot be tagged by mistake the way a
  plausible-looking placeholder can.
- **Call a LinkedIn actor.** LinkedIn slugs stay manual: the actors bill about
  sixteen times the X rate per item, and a company slug is a fact a person
  establishes once, not a thing to poll. `--force-all` does not change this.
- **Downgrade a status.** An inconclusive check writes nothing; `verified` is
  never turned back into `collect` by a machine.
- **Read the private companion into a report.** Its presence is reportable; its
  contents are not, and `dashboard/index.html` is published.
- **Pass `--force-all` unasked.**

## where it shows

`scripts/desk_sync.py --push` carries the rows to the desk's `inventory` table
through the same module, so the staleness flag on the desk is the one the
refresh acts on. Each row shows its party, handles, cleared state, status and
last-verified date, with the rows past the window marked `due`. The dashboard
page does not show the inventory: since 2026-11-06 it carries the posts and
what is live only. The run is appended to `state/runs.json` as step `inventory`
and `engine results` reports it.
