# handles - company and partner handles inventory

The inventory the engine tags from and listens for: the brand's own channels,
the partners cleared to be named and tagged, and the standards bodies it may
cite. Every script resolves its `handles` pointer to this file and none keeps a
copy of it. No `inventory.json` exists; these tables are the inventory.

**Rule:** a handle is tagged only if its owner is on the cleared public list
*and* the handle below is marked `verified`. Anything `collect` is a placeholder
for the team to fill in, never a tag the engine may use. Personal handles are
collected per partner introduction, by a person, not by the engine. A partner
is never added without Alpha, and the decision that clears it is a file in
`decisions/`.

## how to read a row

Every table below carries the same three machine-read fields, in the same order:

- **status**: exactly one of `verified` or `collect`. `verified` means the
  handle was checked against the live profile; `collect` means it is a
  placeholder awaiting collection. No third value is valid, and only a
  `verified` handle may ever be tagged.
- **themes**: the theme hashtags from `themes.md` on which this party may be
  tagged, or `none cleared` where `themes.md` clears it for no theme. Naming a
  party in prose is governed by the **clearance** column; tagging its handle is
  governed by this column together with **status**. A party can be cleared to
  name and cleared for no theme tag at all; that combination is normal, not an
  omission. Two further values are valid: `n/a: own channel` on a row that is
  not a tag target at all, and a hashtag qualified `(cite only)` on a standards
  body, which licenses a citation rather than a tag.
- **last_verified**: the date **status** was last established, as `YYYY-MM-DD`,
  or `-` where it never was. `inventory-refresh` flags any row whose date is
  more than 30 days old, treats `-` as always stale, and calls the paid profile
  actor only for those rows.

A blank handle cell is deliberate: the value is not known and the engine has no
authority to establish one. An obvious blank cannot be tagged by mistake the way
a plausible-looking placeholder can.

## the private companion

Stealth counterparties and unsigned-draft parties never enter this repository.
They live in `.atelier/memory/handles.private.md`, which is gitignored and which
the engine merges on top of this file at read time; the denylist of terms a
draft may not echo lives there too. A checkout without that companion is an
incomplete read, not a clean one: `gate_lint` blocks rather than passes when the
companion is expected and absent, so the stealth check can never pass vacuously.
`handles.private.example.md` beside this file shows the shape; copy it to
`handles.private.md` and fill it before the first draft.

## own channels

One row per platform the brand posts from. The `brand` cell is the registry
name (`streams.md`); the X row is what `x_stream.py` builds the `own` and
`mentions` rules from, and it builds neither until that handle is `verified`.

| brand | platform | handle | status | themes | last_verified | note |
|---|---|---|---|---|---|---|
| Acme | X |  | collect | n/a: own channel | - | left blank on purpose; confirm against the live profile before the first teaser |
| Acme | LinkedIn |  | collect | n/a: own channel | - | the company page slug; `inventory-refresh` flags it and routes the real value to Alpha |
| Acme | website |  | collect | n/a: own channel | - | the site the Blog rows publish to (`engine.json` `site.post_url`) |

## cleared partners (public via the brand's own releases)

A partner is cleared by a published release of the brand's own or by a decision
file in `decisions/`, for the role the record gives it and no other. `scope on
record` is that role; `clearance` is the exact wording a draft may use, with its
tense and footer.

| partner | X | LinkedIn | scope on record | clearance | status | themes | last_verified |
|---|---|---|---|---|---|---|---|

Anything not on this list carries the "in discussion, participation not
confirmed" footer, and is named only with Alpha's approval. When in doubt, cut
the tag.

## standards bodies (cite, never claim)

| body | X | status | themes | last_verified | note |
|---|---|---|---|---|---|

## not to be tagged

Every counterparty carried in the private companion, every party whose row
reads `collect`, and any personal handle not collected through a partner
introduction. When in doubt, cut the tag.

## inventory log

- 2026-11-05: template created. Own channels blank at `collect`; no partner, no
  standards body. Rows arrive by decision, and the private companion is copied
  from `handles.private.example.md` before the gate can pass anything.
