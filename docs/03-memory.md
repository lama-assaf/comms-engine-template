# 3. Memory

Everything the engine knows about the business lives in one place, in the
repository, and every tool reads it there. Nothing keeps a copy.

## 3.1 Shared memory: `.atelier/memory/`

Committed on purpose (`.gitignore` keeps `.atelier/*` out and lets `memory/`
back in). Every tool reads it: the four project agents, the salon and atelier
plugins through their memory hooks (which inject `instincts.md` and `voice.md`
into every prompt), and the engine scripts through `scripts/memory.py`. The
root stream's memory (the brand's) is this directory; a second stream lives
under `streams/<slug>/` with the same file set, resolved from `streams.md`
and never defaulted.

In a fresh clone the files are **shapes**: every heading and every table
column the scripts parse, the rules that bind the file, and no content. The
memory directory's own `README.md` explains each file in two lines.
`engine init` renames the placeholder row of `streams.md`; `/corpus-cycle`
fills the rest from the business's own documents.

| file | what it holds | writer | read before |
|---|---|---|---|
| `streams.md` | the registry: one row per stream, owner state (never a name), autopilot rule, channels, memory path, corpus root; guardrails; pair rules | a person, on a recorded decision; `engine init` renames cells | every step; `memory.py --list` |
| `status.md` | what is **evidenced**, graded, with sources; outranks `project.md` | `/corpus-update --apply`, tighten-only | any claim |
| `project.md` | the strategy as the business's documents state it | corpus-update | context only |
| `claims.md` | the claims register: id, claim, grade, source, date, tier, themes, supersession, corroboration; drafts cite rows by id | `/corpus-update --apply`; never deleted, only superseded | the gate (`lint: cites`) |
| `themes.md` | the theme hashtags, differentiators, the fact each links to, licence grade, taggable partners, intro-post state | corpus-update; a person's new theme at `held`, and a person's licence grade with its reason, through `held_theme.py` | drafting |
| `handles.md` | own channels and partner handles, `verified`/`collect`, taggable themes, `last_verified` | corpus-update for rows; `inventory.py` for two cells (`last_verified`, status) | tagging; `x_stream.py` reads the own X handle here |
| `handles.private.md` | **gitignored**: stealth parties, unsigned-draft parties, the denylist; merged on top of `handles.md` at read time; missing file means the gate blocks. Start from `handles.private.example.md` | a person / corpus-update | the gate |
| `voice.md` | the voice: sliders, vocabulary, headline patterns, hedge forms, banned words | corpus-update; `onboard.py --write-voice` shapes a stream's from `templates/voice.md` | drafting, gating |
| `brand-genome.json` | the brand's look: flat colours, typeface, corner radius, logo (inline SVG) | a person, from the brand's website or guide | `scripts/genome.py`: the story deck, the control page, the motion cards |
| `instincts.md` | the standing rules, short, injected into every prompt | corpus-update; `/atelier:remember --instinct` | everything |
| `logics.md` | the argument shapes | corpus-update | drafting |
| `glossary.md` | terms with exact definitions: stream, content kind, claims register, promotion | corpus-update | writing anything technical |
| `lessons.md` | dated takeaways under `## YYYY-MM-DD` headings (keep the shape: the session brief parses it) | the readout, `livetests.py` after two wins, a person | drafting |
| `reviews.md` | a person's standing reviews pulled from desk decisions marked *standing*; append-only; tightens, never loosens | `desk_sync.py --pull` only | `theme-writer`, `gatekeeper` |
| `decisions/YYYY-MM-DD-slug.md` | one file per owner decision, ADR shape, dated filename (the brief parses it) | a person | before changing a rule |
| `calendar.md` | the agent-readable digest of the calendar notes | `autopilot.py snapshot` only | drafting (never propose what is already there) |
| `campaigns/<q>.md` | the active campaign: slots, engager ledger, topic map, retro | strategist steps, the readout | planning |
| `initiatives.md`, `partners.md`, `open-conflicts.md` | not in the template; created by corpus-update when the corpus carries a pipeline, a partner portfolio or conflicts of interest | corpus-update | partner clearance |
| `templates/voice.md` | the shape a new stream's `voice.md` is written from | the template | onboarding |

The rules that bind every write:

1. **One path in.** New strategy material reaches memory only through
   `/corpus-cycle` (`/corpus-sweep`, `/corpus-read`, `/corpus-analyse`,
   `/corpus-update --apply`). The cycle sweeps every folder of the corpus root
   (`params.corpus.root`, set per machine with `engine setup corpus`), reads
   what changed (decks through the four-pass deck reader, prose through
   `extract_doc.py`), writes a brief into the gitignored `Docs/Research/` that
   separates asserted from evidenced and ends with proposed edits, and only
   the last step writes memory. Do not update memory from a document by hand.
2. **Tighten only.** A grade may fall, a row may be superseded, a name may
   move to the denylist; nothing is raised or deleted by a document. Loosening
   needs evidence and a decision file. Where a dated source disagrees with an
   older one, the latest governs the reading but clears no name.
3. **`status.md` outranks `project.md`**; a review in `reviews.md` can
   tighten what may be claimed, never loosen it, and `status.md` still
   outranks it.
4. **Keep the shapes.** The scripts parse `themes.md`, `handles.md`,
   `claims.md` and `streams.md` by heading and column; the test suite checks
   them and is run after every `--apply`.
5. **No owner names, no handles per person.** `streams.md` says only whether
   an owner is confirmed. Replies are summarised as patterns.

Useful commands:

```bash
engine memory --list           # the registry
engine memory --stream <slug>  # one stream's memory, summarised
engine corpus_sweep              # where every source stands
/corpus-cycle                                                    # plan; --apply to write
engine claims_check --dry-run  # notes whose cited claim moved
/atelier:remember <note>            # a dated lesson
/atelier:remember --instinct <rule> # a standing rule
```

## 3.2 Claude Code's own memory

Claude Code also keeps a per-user, per-project auto-memory outside the repo,
indexed by its `MEMORY.md`. It holds the operator's working notes and does
**not** travel with the repo. Anything that is doctrine belongs in
`.atelier/memory/`; anything that is operator convenience belongs in `docs/`.
A new person starts with an empty auto-memory and loses nothing.
