# 6. Streams: a second business on the same engine

A **stream** is one business the engine serves, with its own narrator, voice,
evidence, themes, handles, channels and corpus. The brand of this checkout is
the root stream (`brand.slug`, memory at `.atelier/memory/`); every other
stream lives under `.atelier/memory/streams/<slug>/` with the same file set.
Streams are isolated by default: one stream's drafts never read another's
memory, its secrets never act for another, and a cross-mention needs a pair
rule. The example below onboards a stream called `beacon`.

## 6.1 What the registry holds

A stream is one entry under `streams` in `brand.json` at the root, keyed by
its slug. `.atelier/memory/streams.md` is what the agents and
`scripts/memory.py` read: three tables joined by `slug`, **rendered** from
`brand.json` by `engine apply`, their one writer. A slug missing from any
table is an error, not a skip; `memory.py` raises on a slug that is not here
and never defaults; `engine doctor` fails when the tables and the file
disagree.

- **registry**: `slug`, `name`, `narrator`, `owner` (only `confirmed` or
  `unset`; never a name), `objectives`, `autopilot` (`nothing` means every
  channel is drafts-only; `by switch` means each kind of send follows its
  review mode), `channels`, `memory`, `corpus root`, `corpus status`.
- **guardrails**: `drafts-only channels`, `posts per channel per day`, `quiet
  hours`, `blocked topics`, `hold for review`. A stream not yet onboarded has
  `all`, `0`, `all hours`, `everything`, `everything`.
- **in `brand.json` only**, because no agent needs them as prose: `review`
  (the default mode per kind of send: `post`, `reply`, `comment`, `like`,
  `repost`, `quote`, `hold`; each `review` or `auto`), `reactions_per_day`
  (for example `{"x": {"like": 20, "repost": 3}}`; 0 or a kind left out sends
  none), and a stream's own `drivers` where it differs from the project's.
- **pair rules**: `from`, `to`, `rule`, `basis`. A stream may name or cite
  another only under a row here, in the words the row gives; the gate checks
  the line against the rule.

A person changes the setup, on a recorded decision: on the Setup page of the
control page, or in `brand.json` followed by `engine validate` and
`engine apply`. Nobody edits the tables, and no scheduled step writes
either file. The prose of `streams.md` around the tables is a person's.

## 6.2 Onboarding, in order

1. **Decide it.** Write `.atelier/memory/decisions/<date>-beacon-stream.md`
   (ADR shape) saying the engine serves a second business and under which
   objectives.
2. **Add the entry.** `streams.beacon` in `brand.json`, shaped like the
   brand's own entry (`brand.example.json` explains each key): `owner`
   `unset`, `autopilot` `nothing`, every `review` mode `review`, the
   guardrails closed (`drafts_only` `all`, `posts_per_day` zeros,
   `quiet_hours` `all hours until onboarded`, `hold_for_review`
   `everything`), and a `pair_rules` entry for each direction the two
   businesses may mention each other, or an empty list. Then
   `engine validate` and `engine apply`, which writes the stream's row
   into each of the three tables.
3. **Make the memory directory.** `.atelier/memory/streams/beacon/` with the
   file set `onboard.py` checks (`onboard.FILE_SET`: `voice.md`, `status.md`,
   `instincts.md`, `themes.md`, `handles.md`, `claims.md`, `reviews.md`,
   `lessons.md`, `calendar.md`, `campaigns/`, `decisions/`), shapes only;
   `reviews.md` is created on first use by `desk_sync.py --pull`, and
   `.atelier/memory/streams/README.md` shows the layout. Its
   `handles.private.md` is gitignored like the root's.
4. **Run the onboarding.** It reads everything, prints one line per thing
   checked and ends with whether the stream may draft and why not:

   ```bash
   engine onboard-stream beacon --dry-run
   engine onboard-stream beacon \
       --corpus-root ~/work/beacon-strategy \
       --themes-file streams/beacon/themes.json \
       --channels "X @handle; LinkedIn slug" --owner-confirmed yes --write-voice
   ```

   It writes `streams.beacon.corpus_root` and `.themes_file` into
   `engine.local.json`, and with `--write-voice` an empty-but-shaped
   `voice.md` from `.atelier/memory/templates/voice.md` (never over an
   existing file). It never writes `brand.json` or `streams.md`: the keys to
   set (`streams.beacon.owner = "confirmed"`, the channels) and the row they
   render to are printed, for a person's change to the setup.
5. **Search terms.** `streams/beacon/themes.json`: one X
   search term and keyword set per theme, joined to the stream's `themes.md`
   by tag. A term with no theme row, or a row with no term, is an error.
6. **Fill the memory through the one path.** `/corpus-cycle --stream beacon`
   over the stream's corpus root; `/corpus-update --apply --stream beacon`
   writes `streams/beacon/*.md`, tighten-only. Nothing is copied from the root
   stream's memory.
7. **Secrets.** A stream's tokens are scoped: `beacon/APIFY_TOKEN` in the
   keychain, `BEACON_APIFY_TOKEN` in the environment. `secrets.get_secret(name,
   stream="beacon")` resolves only those, never the bare name, so one stream's
   token can never act for another.
8. **Check.** `memory.py --stream beacon`, `gate_lint.py` on a fixture item
   with `stream: Beacon`, `state_check.py`. `memory.may_draft("beacon")` is
   false until the owner cell reads `confirmed` and `voice.md` exists; until
   then the stream drafts nothing, publishes nothing and posts nothing, by
   every path.

## 6.3 What a stream shares and what it does not

| shared | per stream |
|---|---|
| the scripts, agents, skills, commands, hooks, tests | memory files, themes, handles, denylist |
| the schedules (one cycle serves every stream that may draft) | search terms (`streams/<slug>/themes.json`) |
| the desk and the state files (every record names its stream; `state_check.py` refuses one that does not) | corpus root, voice, guardrails, autopilot setting, review modes, the pause, reaction caps |
| the calendar notes (the `stream` key on every note) | secrets (scoped names) |
| the brand block (labels, environment prefix, keychain service), the workflows and the plugin roles | pair rules with every other stream; gate rules and formats (`gate-rules.json`, `formats.json` in the stream's memory) |

The brand block belongs to the checkout, not to a stream: one engine, one set
of launchd labels, one keychain service, several streams. A business that
wants its own labels and its own machine clones the template again and runs
`engine init` there.

## 6.4 Changing the loosening

A stream loosens in two steps, both a person's.

**`autopilot`** is set once, at onboarding, by a dated decision file in that
stream's `decisions/` followed by the key `streams.<slug>.autopilot` in
`brand.json` (the Setup page, or the file and `engine apply`). `nothing`
is the hard off; `by switch` hands each kind of send to its review mode; an
`unset` owner blocks whatever the value. `engine setup autopilot` prints
the current setting and where to change it; it never writes it.

**The review modes** are then switches on the Autonomy page, per stream,
channel and kind. `review`, the default, waits for a person. Turning one to
`auto` takes one confirmation, a written reason is optional, and the change
is a `switch` act with the role and the time; three presets set the rows at
once (review everything, review posts only, fully automatic). On `auto`
whatever passes the automatic checks goes out and whatever fails stays in the
queue. The kind `hold` is the statistics, partner and certification class: on
`auto` the hold check passes without a person's release, and every other
check is untouched. The **pause** on the same page stops every send of the
stream at once, and everything sent without review is listed there with a
take down.

Another stream's switches, pause and caps never apply to this one: every one
is keyed by the stream's slug. Guardrails (caps, quiet hours, blocked topics)
are revised at the monthly readout, and the change is dated in the registry
log at the foot of `streams.md`.
