# gate

Review for the stream {stream_name}, as your definition describes: the
claim-gate skill over the queue{ids_clause}. `scripts/gate_lint.py --write` has
already run in this workflow; read its verdicts, do not repeat its checks by
eye.

You return findings and write nothing: no `gate`, no verdict, no stamp, no edit
to a draft, no line in the run log. `scripts/review.py` runs after you. It
looks up every sentence you quote in the text and every `rests_on` in the row
you cite, compares your findings with a second reviewer's, and stamps the
verdict itself.

For each item, run `engine review
sentences{ids_arg}` first: it prints, per item, the sentences code will
look for, already split, the title's first. Return one finding for every
sentence it lists, in that order, with `field` and `text` copied as printed.
A sentence left out blocks the item, however plainly it is not a claim.

Return: `items`, a list with one object per item you read:
`{id, sentences, checks, note}`. `sentences` holds every sentence of the title,
the post and both teasers, in order: `{field, text, claim}` and, for a claim,
`{cite, rests_on, supported, why}`. `field` is `title`, `post`,
`teaser_linkedin` or `teaser_x`; `text` is the sentence word for word;
`rests_on` is copied from the cited row's `claim` cell.
A fact about a third party (another
body's publication, a regulator's words, a public event) may instead rest on a
source the item lists under `sources`: its `cite` is that source's id (`S1`)
and `rests_on` is copied from the source's `quote`. Never a source for a
sentence about the brand ("we", "our", the brand's name), a statistic or a
capability: those need a register row. `checks` holds the
judgment checks that are not about one sentence (`dates`, `names`, `stats`,
`single-pillar`, `licence`, `register`, `status words`, `present-tense spec`,
`stealth`), each `{check, result, line, fix}` with `result` `pass`, `edit` or
`block`. An empty `items` list when there is nothing to read.
