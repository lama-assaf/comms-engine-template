# The desk

Alpha's working surface for the social engine: a content calendar over the
`Content/Calendar/` notes, the quick actions that record a decision, and the
reviews that carry Alpha's reasoning into the agents' memory.

Next.js (App Router) over Drizzle, against one SQLite file at
`../state/desk.db`. It replaces the claude.ai artifact desk, which only worked
while the page was open on claude.ai — opened anywhere else it was read-only and
every button was inert. `../dashboard/index.html` still builds, now as a
read-only mirror of the same state.

## Run it

```bash
npm install          # once
npm run dev          # http://localhost:4310
npm run build && npm start
```

Before the first run — and after every cycle — fill the database from the
engine:

```bash
python3 ../scripts/desk_sync.py --push
```

And to carry what you did back out to the engine:

```bash
python3 ../scripts/desk_sync.py --pull
```

`/social-cycle` runs the pull as its first step and the push as its last, so in
normal use you never type either.

## What this is, and what it is not

**The database is a derived index and a decision store. It is never the
record.** `Content/Calendar/<title>.md` is the record and `../scripts/repo.py`
is its only writer. Nothing in this application writes a note or
writes `.atelier/memory/` — it writes four tables, and
`desk_sync.py --pull` is what turns those rows into something the engine acts
on. Delete `state/desk.db` and you lose nothing that has been pulled; `--push`
rebuilds the rest from the notes.

| table | direction | |
|---|---|---|
| `items` `findings` `proposals` `runs` `themes` `inventory` | engine → desk | replaced wholesale on every `--push`; read-only here |
| `decisions` `edits` `argument_lines` `reviews` | desk → engine | the only rows that exist nowhere else until `--pull` runs |

A `--push` is built to refuse the second group by name. That is the one mistake
that would lose real work: a decision Alpha made and had not pulled yet must
survive a routine refresh.

## The rules the interface enforces

- **Nothing publishes itself.** There is no publish action anywhere in this
  application, and there is no button that reaches a social handle or the site.
  Approving schedules the post for its day once `--pull` runs; marking its
  article live on the site stays a person's act on the control page.
- **The argument line is Alpha's.** Approve stays closed until the hook and the
  claim are confirmed or rewritten. Rewriting the hook later reopens it, because
  the act is only current while it still names the hook on the card.
- **A hold, a rejection and a rewrite carry a reason.** They cannot be recorded
  without one; an approval may go without (owner decision, 2026-11-11), and with
  none it records no review. A reason typed with any decision is stored, and one
  marked *standing* is appended to `.atelier/memory/reviews.md` by `--pull`, and
  `theme-writer` reads it before drafting and `gatekeeper` before gating — so a
  judgement made once does not have to be made again on the next draft of the
  same shape.
- **Edits reconcile by skipping, never by clobbering.** An edit is stamped with
  the hash of the note as this page rendered it (`lib/hash.ts`, which must agree
  with `repo.base_hash()` byte for byte — `tests/test_desk_sync.py` runs both).
  `../scripts/apply_edits.py` writes it only while the note still hashes to
  that value; where the note has moved, nothing is written either way and a
  person picks a side with `--prefer desk|vault`.
- **The stealth list never reaches the database.** `handles.private.md` is not
  read by the sync. The desk is told whether the companion file is present and
  is never given its contents.

## Layout

```
db/schema.ts          the 11 tables, and the source of the DDL
db/index.ts           one libSQL connection per process
drizzle/              generated migrations — `npm run generate` after a schema change,
                      then `desk_sync.py` applies the same file
lib/desk.ts           the derived reading: edit state, argument currency, what is waiting
lib/hash.ts           repo.base_hash(), in TypeScript
app/page.tsx          the calendar
app/queue/            what is waiting on Alpha, most urgent first
app/item/[id]/        one item: the post, the gate's checks, the acts
app/reviews/          every reason given, and which have reached memory
app/actions.ts        the server actions — the only writes
```

The driver is `@libsql/client` in local-file mode rather than `better-sqlite3`,
which segfaults on the Node 23 build this machine runs. Both write an ordinary
SQLite file; Python's stdlib `sqlite3` reads it either way, which is the whole
integration between the two runtimes. Switching back is a two-line change in
`db/index.ts`.

## Deploying it

It is a standard Next.js server: `npm run build && npm start` behind whatever
reverse proxy the operator runs. It needs the repository on the same filesystem,
because `desk_sync.py` reads the vault notes — the app itself only needs
`state/desk.db`. Set `DESK_DB` to point elsewhere and `DESK_USER` to name who is
deciding (it defaults to `Alpha`).

There is no authentication in front of it, so `npm run dev` and `npm start` listen
on 127.0.0.1 only: without `-H` Next.js listens on every interface, and anyone on
the same network could record a decision. A reverse proxy on the same machine
reaches it as it is. Only when the server must answer on another interface (a
container, a separate host) run `npx next start -H 0.0.0.0 -p 4310`, and put
authentication in front of it first: the drafts are unpublished and the decisions
are Alpha's.
