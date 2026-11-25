# decision: a fact about a third party may rest on a source listening read

date: 2026-11-14
status: accepted

## context

Standing rule 5 says a claim comes only from `claims.md` or a primary source
cited in the piece, and the theme-post skill anchors a post on an external,
dated, primary-source event. The gate built on 2026-11-13 (`scripts/review.py`)
let a claim rest on a register row only, so a live run on 2026-11-14 blocked
every draft that answered what listening had found: the consultation a body
opened, the words a regulator used.

## decision

The owner, 2026-11-14: a fact about a third party may rest on a source the
draft lists under `sources` and links in the text that ships. Code checks that
listening read it (`state/signals.json`, or the ledger `state/evidence.json`
kept by `review.py evidence` after each pass) and that the words the claim
rests on are in what listening quoted. A sentence about the brand ("we",
"our", its name), a statistic or a capability still needs a register row. Both
reviewers still judge every sentence, and hold for review (rule 4) stands.
