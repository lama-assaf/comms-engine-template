# tests/fixtures: the invented brand the suite runs against

Written 2026-11-05. Everything under this directory is made up: the brand is
`Acme`, the second stream is `Beta`, the themes are `#ExampleTheme` to
`#EighthTheme`, the partners are `Beta Labs`, `Gamma Bank`, `Delta Co` and
`Epsilon Trust`, the standards body is `Example Standards Body`, and the
denylist terms are `Umbra`, `Ruritania`, `Project Nightjar` and `relay nodes`.
Nothing here names a real business, a real handle or a real person, so the
suite is green on a fresh clone with no `handles.private.md` of its own, no
state records and no memory written yet.

The tests never read `.atelier/memory/`, `state/` or `Content/Calendar/`.
`tests/fixture_memory.py` copies `memory/` to a temp directory and points
`scripts/memory.py` at the copy for the length of a test; a test that needs
the companion absent asks for `private=False` and the copy is made without
it. The same fixture writes an `engine.json` beside the copy, the tracked one
with its `brand` replaced by the placeholder (`acme`) and its `streams` key
renamed, and points `scripts/config.py` at it, rebinding the constants the
scripts derived from the brand at import (`fixture_memory.BRAND_BOUND`); so the
suite is green on a checkout `engine init` has stamped with any brand, and
only `test_brand`'s placeholder check skips there. The dates inside are frozen on purpose: `test_inventory` pins 2026-09-08
and asserts which rows are stale on it, and `test_planning` counts register
rows inside a 28-day window ending 2026-10-26. Move a date and the test that
leans on it says so.

| path | shape it carries | read by |
|---|---|---|
| `memory/streams.md` | the registry, guardrails and pair rules; `acme` first, `beta` unset | every test that resolves a stream |
| `memory/themes.md` | eight themes in the two tables `memory.load_themes` joins | gate, planning, listening, desk |
| `memory/handles.md` | own channels, cleared partners, standards bodies, the companion declared | gate, inventory, x-stream, desk |
| `memory/handles.private.md` | the stealth parties and the denylist | gate stealth check, desk boundary test |
| `memory/claims.md` | ten rows: evidenced, asserted, intended, one supersession, one watching, one single | gate cites, claims, planning, research store |
| `memory/voice.md` | a written voice, so `acme` may draft | `memory.may_draft` |
| `memory/templates/voice.md` | the shaped-empty voice onboarding writes for a new stream | `test_onboard` |
| `memory/streams/beta/` | a registered stream with headings and no rows, no voice, no companion | per-stream gate, onboarding |
| `themes.json` | the engine-local search terms for the eight themes | `test_x_stream` |
| `streams/beta/themes.json` | the empty search file a new stream starts with | `test_onboard` |
| `queue.json` | three drafts with the verdicts the model recorded | `test_gate_lint.QueuedDrafts` |
| `../fixtures.json` | the gate's clean item and its mutations | `test_gate_lint`, the rehearsal |

Refresh a file here only when a test needs a shape the engine reads and this
one lacks (a new column, a new table), and change the assertions with it.
