# Plan: one data core, one contract, any UI, any database

Written 2026-11-06 after the owner asked to rethink the dashboard setup and
its tech stack "to have also ui and database flexibility". It extends to data
what `scripts/engine.py` already does for jobs: one module owns the work, and
every screen is a face over it (`CONSOLE-CONTRACT.md`). It builds on
`PLAN-workflows.md` step 2 (the post lifecycle), which it needs.

## Why

The engine has four surfaces, and each reads and writes the data its own way:

| surface | stack | reads | writes a person's act |
|---|---|---|---|
| the desk (calendar, queue, item edit, reviews) | Next.js 16, React 19, Drizzle, SQLite `state/desk.db`; about 1,360 lines of TS | a mirror pushed by `desk_sync.py --push` | into four SQLite tables; applied at the next cycle's `--pull` |
| the control page (story, themes, accounts, suggestions, heard, replies, claims, results, system) | stdlib Python server and one 1,000-line vanilla page | the files, live, through its own readers in `control.py` | straight into the files, at once |
| the dashboard | `build_dashboard.py` and an HTML template | its own loads, baked into a page | nothing |
| the console | curses `engine_tui.py`, `/engine` | `engine.py` | jobs only |

What that costs:

- **The same view is computed three times.** "The posts coming up" exists in
  `control.py`, in `desk_sync.py`'s push mapping and in `build_dashboard.py`,
  and the desk's schema is written twice, once in Drizzle (TS) and once in
  `desk_sync.py` (Python).
- **Acts follow two rules.** An approval on the desk waits for the next cycle;
  a watch on the control page is written at once. A person cannot tell which
  applies when.
- **A writer outside its lane.** The control page's "add a theme" writes
  `.atelier/memory/themes.md`, which `ORCHESTRATION.md` §7 gives to
  `/corpus-update --apply` alone. The docstring at the top of `control.py`
  still says that file is "shown, never written, here".
- **The UI cannot grow.** The vanilla page builds everything from string
  templates, with no components, no types and no UI tests (fixing the deck
  layout took several rounds). The desk is a second UI stack beside it.
- **The database is fixed.** SQLite is wired into the desk alone. A hosted
  store (a phone away from the laptop, a second person) would mean a rewrite.

## Principles

1. **The files stay the record.** The notes, `.atelier/memory/` and `state/`
   JSON stay in git, each with its single writer (§7). No database becomes the
   record: agents read files, git keeps the history, a person can review a diff.
2. **One core computes every view.** A view is computed once, in Python, from
   the record.
3. **A person's act is a row in one log.** Every surface writes the same act
   shape. One applier per kind of act calls the single writer of the store
   that act touches, with a base check: conflicts skip, never clobber.
4. **A contract between core and screens.** Views and acts are JSON Schemas,
   versioned. A screen knows the contract, never a file format.
5. **The database is a driver.** Views and acts live wherever the driver puts
   them: files, SQLite, later Postgres. It is one setting in `engine.json`.
6. **Local by default.** Nothing leaves the machine unless the owner decides,
   per stream, that it may. The private denylist never syncs anywhere.

## The shape

```
 record (git)                core (Python)                     drivers              screens
 ─────────────               ──────────────                    ───────              ───────
 Content/Calendar/*.md ─┐    views.py   one function a view ─► put_view ─► files  ┐  web app (story, today, posts,
 .atelier/memory/*     ─┼──► (posts, calendar, themes, ...)         │       sqlite ├─ themes, accounts, ...)
 state/*.json          ─┘                                           │       pg*    │  read-only snapshot (no server)
        ▲                    acts.py    append, list, mark ◄── append_act ◄────────┘  TUI · /control · /story
        └──── single writers ◄── appliers (lifecycle, memory, story, watch)           * on an owner decision
```

### The core: flat modules in `scripts/`, like every other engine module

- **`views.py`** (built in step 1): one function per view, by name in
  `views.VIEWS`: `genome`, `story`, `posts`, `calendar`, `themes`,
  `accounts`, `suggested`, `listening`, `replies`, `claims`, `learning`,
  `engine`. Each returns plain rows; `views.snapshot()` is what the page reads
  and `views.py --all --out F` writes it for a read-only build. `control.py`
  and `story.py facts` take their data from here and keep no readers of their
  own.
- **`acts.py`**: the log of what a person did. One shape:
  `{id, at, stream, kind, target, payload, base, by}` (`by` is a role, never a
  name). The kinds: `decision`, `edit`, `review`, `argument_line`, `answer`,
  `slide_response`, `story_feedback`, `watch`, `unwatch`, `dismiss`, `terms`,
  `theme`, `grade`. Each act ends with one outcome: `applied`, `skipped: moved` or
  `refused: <reason>`, which every screen shows.
- **Appliers**: one per kind, each calling the store's own writer:
  - `decision` and `edit` go to `lifecycle.py` (`PLAN-workflows.md` step 2);
  - `answer`, `slide_response` and `story_feedback` go to `story.py`;
  - `watch`, `dismiss` and `terms` go to the watch list and `themes.json`;
  - `theme` and `grade` go to `held_theme.py` (built in step 0), recorded in
    §7 as that file's second writer: a new theme only ever enters at `held`,
    and a person's grade (allow or hold, added 2026-11-07) carries its reason,
    with the status log keeping the grade and reason it replaced.
- **When acts apply.** At once when the API runs beside the record (the local
  case, today's control page). At the next cycle's pull when it does not (a
  hosted driver). It is the same code either way.

### The drivers: `scripts/store.py`

The interface: `put_view`, `get_view`, `append_act`, `acts(since, status)` and
`mark(id, outcome)`.

- **`files`**: `state/views/*.json` and `state/acts.jsonl`. Nothing to
  install; the template's default.
- **`sqlite`**: one file. The default for a brand already running the desk,
  replacing `desk.db`'s eleven tables
  with two (`views`, `acts`) plus saved table views.
- **`postgres`**: Supabase, Neon or any Postgres, only on an owner decision.
  It needs auth, and a rule for what may sync (never `handles.private.md`).

Set by `params.store.driver` in `engine.json`; a URL resolves through
`secrets.py`.

### The contract: `contract/v1/`

- One JSON Schema per view and per kind of act. Python validates against them
  in tests and at the API.
- `scripts/contract_types.py` writes the TypeScript types the web app imports.
- The API is small, because everything else is data:
  - `GET /api/v1/meta`: the stream, the genome, the token;
  - `GET /api/v1/views/<name>`;
  - `POST /api/v1/acts`;
  - `GET /api/v1/acts?since=`.
- The server stays stdlib Python (`control.py`, renamed `api.py`), with
  today's Host, Origin and token checks.

### One web app: `ui/`

- **Stack:** Vite, React and TypeScript, TanStack Table for the database-style
  tables (sort, filter, group, saved views), and the brand genome as CSS
  tokens.
- **The build is committed** (`ui/dist`) and served by the Python API, so a
  fresh clone runs with plain `python3`. Node is needed only to change the UI.
- **Modules:**
  - the story deck, which stays the landing page;
  - the control pages: today, themes, accounts, suggestions, heard, replies,
    claims, results and system;
  - posts, which take over the desk's calendar, queue, item editor and
    reviews.
- **Read-only mode** is the same app reading a baked `views.json`, with no
  server. It replaces the `build_dashboard.py` template.
- **Why not the others:**
  - Next.js wants a Node server holding the database; here the Python core
    owns reads and writes.
  - htmx needs no build at all, but the deck and the editable tables are
    exactly where it gets hard.
  - React carries the desk's components over.

### What stays as it is

- **The console** (`engine.py`, the TUI, `/engine`) is about jobs, not data;
  later it can read `views.py`.
- **Notion** stays a publish target, neither a store nor one of our screens.

## Steps (each ships alone, both repos, tests green)

0. **Writer fix.** Done 2026-11-07. Add-a-theme goes through
   `held_theme.py`, which only adds a `held` row. It is recorded in §7, and
   `control.py`'s docstring says so; `memory.py` still writes nothing.
1. **Views.** Done 2026-11-07. Every reader in `control.py` moved to
   `views.py` unchanged, and `story.py facts` reads from there. Every view's
   output was compared before and after the move, in both repositories, and
   matched. `desk_sync.py --push` and `build_dashboard.py` keep their own raw
   reads until their screens retire (steps 4 and 5), because the desk and the
   dashboard template both go.
   **Moved ahead, 2026-11-07:** step 4 began before steps 2 and 3, because
   the owner saw no visible change ("why does it still look like this") and
   `views.py` already gives the app one read. The app reads `GET /api/state`
   and posts the same changes the first page did; step 2 swaps those for
   `POST /api/v1/acts` underneath it.
2. **Acts.**
   - Write `acts.py`, the appliers, and the `files` and `sqlite` drivers.
   - The control page's nine POST routes become `POST /api/v1/acts`.
   - `desk_sync.py --pull` turns the desk's four tables into acts until the
     desk retires.
   - This needs `PLAN-workflows.md` step 2 (lifecycle) first, or together.
3. **Contract.** Write the schemas for every view and act and validate them
   in tests; generate the TS types.
4. **The web app.** This is the largest step.
   - Started 2026-11-07: `Tooling/social-engine/ui/` (Vite, React,
     TypeScript, TanStack Table, lucide icons, Inter bundled). The story deck
     and every page of the first page are ported, and the build in `ui/dist`
     is committed. `control.py` serves it at `/` and the first page at
     `/classic` until the owner confirms they match.
   - The look follows the owner's direction of 2026-11-07:
     - solid colours from one palette, kept in the genome's `palette`, with
       its roles for critical, warning, good, action and info;
     - white and greys for everything else;
     - rounded and soft, not boxy (the genome's `shape.ui_radius`).
   - Still to do: the desk's pages (the calendar, the queue, the item editor
     and the reviews), then the read-only build.
5. **Retire**, once the owner confirms parity:
   - `control/page.html`, the Next desk, and `dashboard/template.html`;
   - `desk_sync.py` shrinks to "push views, pull acts" for non-file drivers.
6. **Hosted (optional, owner decision).** The `postgres` driver, auth, and
   the sync rule per stream, for the phone and a second person.

## Done when

- Every screen reads only `GET /api/v1/views/*` and writes only
  `POST /api/v1/acts`.
- Switching `params.store.driver` from `files` to `sqlite` changes no screen
  and no test.
- Every act shows its outcome.
- No file in `.atelier/memory/` has a writer that §7 does not name.

## Decisions

Recorded 2026-11-07, owner: the control page and the deck take their colours
from a palette in the genome, keep white and greys, and are rounded rather than
boxy. First solid, then pastel variants, with blue shades for the first
brand:
- the colours are pastel tones (`palette.style: pastel`);
- the default palette is ten blue shades, with its navy
  (`colors.primary`) as the strong anchor;
- status keeps a soft red, yellow and green;
- the template keeps the owner's ten-colour palette, in pastel.

Motion cards for posts keep the brand's own colours.

Recorded 2026-11-07, owner ("ok go" to the five recommendations):

- **UI stack:** Vite + React + TypeScript.
- **The built UI is committed**, so Node is needed only to change it.
- **Default driver:** `files` in the template, `sqlite` where a brand runs the
  desk today. Hosted Postgres only on an explicit go.
- **Acts apply at once when local**, at the next cycle when not.
- **The Next desk retires after parity.** This closes the open question in
  `PLAN-workflows.md`.

Recorded 2026-11-10, owner ("run everything through dashboard and self host
in the future"), planned in `PLAN-channels-hosting.md`:

- **Notion is no longer a publish target.** This supersedes "Notion stays a
  publish target" above. Notion is a one-way mirror until step N4 retires it.
- **Step 6 (hosted) becomes a goal.** It stays last in the order.
- **One server runs the whole instance**, so the `files` driver still works.
  Postgres is needed only if the screens and the record run on different
  machines.
