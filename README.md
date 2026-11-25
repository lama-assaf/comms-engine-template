# Comms engine template

A communications engine for one business, and the repository a business runs
it from. It listens to the themes the business wants to lead, drafts theme
posts against a memory of what the business may claim, gates every draft, puts
the decision in front of a person, distributes what that person approved, and
learns from what was published.

The engine is the **`comms-engine` Claude Code plugin** (`plugins/comms-engine/`:
the scripts, agents, skills, commands, hooks, schedules, console and tests),
and this repository is its marketplace. The root is the **instance template**:
what one brand owns (`brand.json`, the memory as shapes, `Content/`, `state/`).
Each brand runs its own instance repository, made with `engine new-instance`,
which pins the engine version it runs.

## What this is

**One engine.** `plugins/comms-engine/` holds the loop (scripts, agents,
skills, commands, hooks, tests); its `skills/deck-reader/` reads the business's
strategy corpus into memory; the optional Next desk is `Tooling/desk/`; the
content calendar is the notes in `Content/Calendar/`, acted on from the
control page. The
business is named once, in the `brand` block of `brand.json` at the root (the
one small setup file; `plugins/comms-engine/engine.json` is shipped defaults
nobody edits), and everything else derives from it: launchd labels `com.<slug>.<job>`,
environment names `<PREFIX><SECTION>_<KEY>`, the keychain service
`<slug>-comms`, the root stream of the memory. A fresh clone carries the
placeholder `acme` / `Acme` until `engine init` stamps yours.

**The learning loop, in six rules.**

1. Drafts only, unless the stream's `autopilot` setting says otherwise. Under
   `by switch`, each kind of send follows its review mode: `review` (the
   default) waits for a person, `auto` lets what passes the checks go out.
2. One variable per hypothesis, named on every draft, with the planning query
   it answers.
3. A predicted band on every draft before it leaves the queue (below,
   baseline, above), recorded so it can be scored against what happened.
4. Statistics and named counterparties hold for human review, unless a person
   switched the stream's `hold` mode to `auto`.
5. A claim comes only from the claims register or a primary source cited in
   the piece.
6. Replies and comments are summarised as patterns, never stored per person.

**One command.** Every script is `engine <name>` (`engine doctor`, `engine
listen --dry-run`): the plugin's `bin/engine`, on the Bash tool's PATH while the
plugin is enabled, runs it against the instance it finds (the
`COMMS_ENGINE_INSTANCE` variable, the project Claude Code opened, or the
nearest folder holding `brand.json`). Before the plugin is installed,
`plugins/comms-engine/bin/engine` is the same command.

**Two faces.** The console (`scripts/engine.py`, its curses screen
`scripts/engine_tui.py`) for the operator: what runs, what is stale, run a job
dry, enable it, read its log, set its parameters. Claude Code for the work:
open plain `claude` in the folder and `/social-cycle`, `/engine`,
`/corpus-cycle`, `/announce`, `/motion`, `/story`, `/control` (the local control page, which opens on the story) and the rest are there, with two hooks that hold
in every session, headless or not.

## What it needs

- **macOS.** The schedules are launchd agents and the secrets live in the
  login keychain. The Python scripts run anywhere; the schedules and the
  secret store do not.
- **python3**, 3.11 or later, with the pinned packages of `requirements.txt`
  (`python3 -m pip install -r requirements.txt`: `requests`, `pyyaml`, `pdfplumber`, `python-pptx` and the rest);
  `pdftoppm` (`brew install poppler`) for the deck reader; `soffice` and
  `tesseract` optional; Node 20+ for the desk; `pillow`, and `ffmpeg` for the
  MP4, only for `/motion`.
- **Claude Code**, plain `claude`, logged in. No wrapper, no environment
  variable. The engine plugin comes from this repository's marketplace: in a
  clone of the template, once per machine, `claude plugin marketplace add ./
  --scope local` and `claude plugin install comms-engine@comms-engine --scope
  local`; an instance repository names the GitHub marketplace itself and
  `claude` offers it on first open.
- **The three plugins** `atelier@atelier`, `salon@atelier` and `motion@atelier`, enabled in the
  tracked `.claude/settings.json` and installed once per machine from the
  marketplace they come from (`claude plugin marketplace add <git url>`, then
  `claude plugin install <name>@atelier --scope project`). The template ships
  no marketplace URL: record yours once with
  `config.py set plugins.marketplace <git url>` and `engine plugins` prints it.
- **A twitterapi.io key** in the keychain,
  seeded with `engine secrets --set NAME`. LinkedIn page credentials and an
  Apify token are optional and only for sending and paid LinkedIn listening.

## The first hour

The guided way is one command on the Mac, with Node 20 or later and a GitHub
login that can read this repository:

```bash
npx github:lama-assaf/comms-engine-template          # the menu: set up, doctor, status, the console
npx github:lama-assaf/comms-engine-template setup    # straight into the guided setup
```

It walks the steps below in order: the tools, the comms-engine plugin, the
brand's repository (`engine new-instance`, then `engine init`), the Python
packages, the role plugins, the secrets and, on the office Mac, the shim, the
schedules and `engine host-check`. It skips what is done and asks before each
change; every act is an `engine` or `claude plugin` command, printed before it
runs. Run it again inside a brand's repository for the menu over that one. By
hand, the same steps are:

1. Clone **outside** `~/Desktop`, `~/Documents` and `~/Downloads`. macOS
   folder protection stops launchd from reading a script in those folders.
   For a brand of your own, make its instance from the clone:
   `plugins/comms-engine/bin/engine new-instance ~/work/<brand>-comms`, and
   take the steps below there.
2. Name the business once, with the guided setup:
   `engine init` asks a few questions
   on a terminal (headless: `init --slug yours --name "Yours"`). It writes
   `brand.json`, renders the tables of `streams.md` from it, renames the brand
   cells of `handles.md`'s own channels and the example claim id in
   `claims.md`, and prints the next commands. Run it twice and it says there
   is nothing to write. `engine validate` checks the file, and the Setup
   page of the control page edits it later.
3. `cp .atelier/memory/handles.private.example.md .atelier/memory/handles.private.md`
   and fill the denylist. The file is gitignored; without it the claim gate
   blocks every draft, by design.
4. Point the site at the published-posts feed when it is ready to read it:
   `engine export-published <file>` writes the JSON a site build reads, and
   the control page serves the same at `GET /api/published`.
5. `engine doctor`: every check on one
   line each; a missing secret and a stream without
   its own X handle yet are reported, not failed.
6. `engine secrets`, then
   `engine secrets --set TWITTERAPI_IO_API_KEY`.
7. `engine setup corpus --root <dir>`:
   the folder your strategy documents live in. Then `engine setup cycle`:
   drafts per run, budget, listening. Both end with a dry run and never load a
   job.
8. Install the plugins (above), run `engine plugins --prepare` once, and
   check with `engine plugins`.
9. `engine shim --install` (the fixed path every schedule runs), then
   `engine enable cycle`: the first schedule, loaded by you, after you have
   seen its dry run.
10. Open `engine engine_tui`, or start
   `claude` and type `/engine`.
11. Fill the memory. `voice.md`, `themes.md`, `status.md` and `claims.md` are
    shapes until your corpus has been read: `/corpus-cycle` plans, and
    `/corpus-cycle --apply` writes, tighten-only. Nothing drafts in a voice that
    has not been written.

## What it never does

Out of the box it sends nothing: every stream starts on drafts only and every
review mode on `review`. It sends without a person only where a person turned
that on, per stream, channel and kind of send, as a recorded act, and then
only what passes every automatic check; a pause stops a stream at once and
anything sent without review can be taken down in one click. It never marks an
article live, never loads a launchd job on its own, never writes a person's
name or a per-person handle into a record, and never reads a token from a
file. A `PreToolUse` hook refuses any command that would post around
`channels.send()`, in every Claude Code session.

## Where the docs are

| file | what it answers |
|---|---|
| `CLAUDE.md` | the rules Claude Code works under here, and the verification commands |
| `docs/01-setup.md` | a new machine and a new business: clone, the guided setup and `brand.json`, what may go out without a person, hooks, plugins, secrets, dependencies, schedules |
| `docs/02-method.md` | the communications method the engine implements: facts and themes, Alpha and Beta, the claim gate, cadence |
| `docs/03-memory.md` | the shared memory in `.atelier/memory/`: every file, who writes it, how it changes |
| `docs/04-runtime.md` | what runs, where, on what schedule; the plugin and the instance, the scripts, the state, the desk |
| `docs/05-console.md` | the console: `engine.py`, the screen, `/engine`, the configuration layering |
| `docs/06-streams.md` | onboarding a second business on the same engine |
| `docs/07-hosting.md` | one brand's instance on an office Mac: the user that stays logged in, the Claude token, the schedules, Tailscale Serve, the denylist, backups; `engine host-check` |
| the scripts' docstrings | every script under `plugins/comms-engine/scripts/` opens with what it is, why, and its command lines |
| `TEMPLATE-CONTRACT.md` | the brand block, its derivations, the API the scripts expose, and what the build left undone |
| `PLAN-autonomy.md` | the plan behind the setup file, the workflows, the review switch and reactions, and where its build stands |
| `PLAN-workflows.md` | the next build: smaller workflows that can be monitored, one post lifecycle, lessons that shape the playbook |
| `PLAN-surfaces.md` | one data core and contract behind every screen: views computed once, one log of a person's acts, the database as a driver (files, SQLite, later Postgres), one web app |

## Licence

Apache License 2.0: see `LICENSE`. The plugins the flows call (`atelier`,
`salon`, `motion`) are separate works under their own licences.
