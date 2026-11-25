# handles — the fixture brand's company and partner handles inventory

The inventory the test engine tags from and listens for. The shape is the one
`scripts/memory.py` and `scripts/inventory.py` read from
`.atelier/memory/handles.md`. Written 2026-11-05 as a fixture; every handle
is invented and the dates are frozen on purpose: `test_inventory` pins
2026-09-08 and asserts which rows are stale on it, so a refresh that stamped
today's date here would break the test because it worked.

**Rule:** a handle is tagged only if its owner is on the cleared public list
*and* the handle below is marked `verified`. Anything `collect` is a placeholder
for the team to fill in, never a tag the engine may use.

## how to read a row

- **status** — exactly one of `verified` or `collect`.
- **themes** — the theme hashtags from `themes.md` on which this party may be
  tagged, or `none cleared`; `n/a — own channel` on a row that is not a tag
  target; a hashtag qualified `(cite only)` on a standards body.
- **last_verified** — the date **status** was last established, or `—`.

## the private companion

Stealth counterparties and unsigned-draft parties never enter this repository.
They live in `.atelier/memory/handles.private.md`, which is gitignored and
merged on top of this file at read time; the denylist of terms a draft may not
echo lives there too. A checkout without that companion is an incomplete read,
not a clean one: `gate_lint` blocks rather than passes when the companion is
expected and absent.

## own channels

| brand | platform | handle | status | themes | last_verified | note |
|---|---|---|---|---|---|---|
| Acme | X | @acme_hq | collect | n/a — own channel | — | confirm against the live profile before the first teaser |
| Acme | LinkedIn |  | collect | n/a — own channel | — | slug unknown, and not a fact the engine has the authority to establish; left blank on purpose |
| Acme | website | https://www.example.com | verified | n/a — own channel | 2026-09-07 | published posts live here |

## cleared partners (public via Acme's own releases)

| partner | X | LinkedIn | scope on record | clearance | status | themes | last_verified |
|---|---|---|---|---|---|---|---|
| Beta Labs | @betalabs | company/betalabs | first deployment | cleared — subordinate cross-reference only | verified | #SecondTheme | 2026-09-07 |
| Gamma Bank | collect | collect | named in releases; graded "in discussion" | cleared to name, tag only with the in-discussion footer | collect | none cleared | — |
| Delta Co | @deltaco | collect | validator co-name | cleared | verified | #SecondTheme | 2026-09-07 |
| Epsilon Trust | collect | collect | validator co-name | cleared | collect | #SecondTheme | — |

Anything not on this list carries the "in discussion — participation not
confirmed" footer, and is named only with Alpha's approval.

## standards bodies (cite, never claim)

| body | X | status | themes | last_verified | note |
|---|---|---|---|---|---|
| Example Standards Body | @examplestandards | collect | #ExampleTheme (cite only) | — | cite the standard; never a partner, never an endorsement |

## not to be tagged

Every counterparty carried in the private companion, and any personal handle
not collected through a partner introduction. When in doubt, cut the tag.

## inventory log

- 2026-11-05 — fixture written.
