---
description: Show the Alpha queue - every proposed theme post with its gate verdict and the decision recorded on the desk - and apply decisions locally.
argument-hint: [approve|hold|reject <id> "note"]
allowed-tools: Bash, Read, Write, Edit
---

# /alpha-queue

Alpha is *the irreducible human judgment* in the loop: the person who decides
what may be claimed, and when. The desk is where that judgment is
recorded (the dashboard page mirrors it read-only); this command is the
terminal view of the same queue.

- With no arguments: run `engine desk_sync --pull`
  to bring the desk's decisions into `state/decisions.json`, merge with
  `state/queue.json` (the index derived from the `Content/Calendar/` notes;
  `engine repo --index` refreshes it) and
  print a table: id, theme, title, gate verdict, alpha_status, note.
- With `approve|hold|reject <id> "note"`: write the decision into the desk's
  database, which is where the decision store lives:

      sqlite3 state/desk.db "INSERT INTO decisions
        (id, kind, status, note, by, at) VALUES (...)
        ON CONFLICT(id) DO UPDATE SET status=excluded.status, note=excluded.note, at=excluded.at"

  with `by: "terminal"`, and record the same reason in `reviews` (`scope:
  'item'` unless the note is a judgement the next draft should inherit, in
  which case `'standing'`, and `--pull` carries it to
  `.atelier/memory/reviews.md`). Then `--pull` it out and write it to the
  item's calendar note:
  `engine repo <id> --set alpha_status=approved`,
  which rebuilds the index too. Never edit `queue.json` by hand: it is a
  derivation and the next rebuild overwrites it.

  The **argument line** is Alpha's act and the desk enforces it before an
  approval. A terminal approval that skips it is the one way round that rule;
  do not use it to avoid the question. Confirm the hook on the desk, or record
  the argument line here too.

Never publish from here. Approval only changes state; `/social-cycle` or the
`distributor` agent acts on it.
