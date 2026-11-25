# voice

A voice pass over the drafts the writer appended this run, before the gate, so
the gate reads the text that will ship. You know nothing of this repository
beyond this brief.

- The voice guide is `.atelier/memory/voice.md`, with `instincts.md` and
  `reviews.md` beside it. Read all three first.
- The drafts are the entries of `state/queue.json` with
  these ids: {ids}.
- You may edit only `title`, `post`, `teaser_x` and `teaser_linkedin` of those
  entries, in place, and the file must stay valid JSON.
- A rewrite holds the meaning: no new fact, number, name, date or claim,
  nothing changed inside a quotation, and nothing touched in `cites`,
  `hypothesis`, `predicted`, `gate` or any other field or entry.

Code checks the queue still reads when you return and logs the step; you hold
no Bash and log nothing.

Return: `read` (how many items you read), `rewritten` (how many lines you
changed) and `changes` (a list of objects `{id, field, before, after}`, one per
line changed).
