# streams — the registry fixture

One row per stream the test engine serves. The shape is the one
`scripts/memory.py` reads from `.atelier/memory/streams.md`: three tables
joined by `slug`, a slug missing from any of them is an error. Owners are never
named; the `owner` column says only whether one is confirmed. Written
2026-11-05 as a fixture; nothing here is a real business.

## registry

| slug | name | narrator | owner | objectives | autopilot | channels | memory | corpus root | corpus status |
|---|---|---|---|---|---|---|---|---|---|
| acme | Acme | authority: standards, identity, governance | confirmed | qualified citations (north star); intent engagement; reach as context only | themes: Blog row created Published after audit and gate pass; LinkedIn and X teasers created Ready and posted on their date; facts: manual | X @acme_hq; LinkedIn (slug to collect); website https://www.example.com | .atelier/memory | `~/Documents/Strategy` | confirmed |
| beta | Beta | — (set at onboarding) | unset | intent engagement; reach: not opted in; north star: set at onboarding | nothing | X @betalabs | .atelier/memory/streams/beta | `~/Documents/Beta` | candidate |

`autopilot` is the only loosening a stream has: `nothing` means every channel
is drafts-only.

## guardrails

| slug | drafts-only channels | posts per channel per day | quiet hours | blocked topics | hold for review |
|---|---|---|---|---|---|
| acme | none for themes (see autopilot); all for facts | X 2; LinkedIn 1; Blog 2 per ISO week, at least 3 days apart | weekends; before 08:00 and after 18:00 local time | every term in `handles.private.md`; the never-say lines in `instincts.md` | statistics not in `claims.md`; a named counterparty not on the cleared list; a certification or accreditation word |
| beta | all | 0 | all hours until onboarded | as its own `instincts.md` once written; until then everything | everything |

## pair rules

| from | to | rule | basis |
|---|---|---|---|
| acme | beta | cite only as "the first deployment of Acme's platform"; never an equal narrator | `instincts.md` subordinate cross-reference |
| beta | acme | cite only as "the platform Beta runs on" | `instincts.md` never-say (Beta) |

## registry log

- 2026-11-05: fixture written with two rows; only `acme` complete.
