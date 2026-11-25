---
name: theme-words
description: Write each theme's licence in plain words for the people who decide - what we may say about it now, what we never say under it, why, and what would let it move up a grade - from the rule in themes.md, which is written for the writing agents. Use when `theme_words.py status` says a theme's words are missing or out of date (after a grade changes, a theme is added, or the corpus updates a rule), or when a person asks what a theme's licence means. Writes only the draft; scripts/theme_words.py checks and publishes it.
---

# theme-words

The control page shows every theme's licence: free to use, careful wording, or
not yet. A person decides from it, and may allow a theme or hold it again. The
rule behind each grade, in `themes.md`'s licence table, is written for the
writing agents, with argument codes, file names, section marks and sometimes
the internal names of what we keep quiet about. The page needs the same rule
said for a person. You write that; `scripts/theme_words.py` checks it and
publishes it.

## what each theme gets

- **now**: what we may say about the theme today, in one or two sentences.
  Start from what is allowed, not from what is forbidden. At most 260
  characters.
- **not**: what we never say under it, said plainly ("We never say we run
  it today, and we give no date"). At most 220 characters.
- **why**: why it has this grade, as a reason a person can weigh ("Nothing in
  this area has shipped yet, and the work on it is not public"). At most 220
  characters.
- **next** (optional): what would let it move up a grade, said as a fact
  someone could check ("When the first piece ships and can be shown").
  Leave it out for a theme that is already free to use, unless something
  would take it back down.

## the words

- **Say the meaning, never the source.** No file names, no "status.md", no
  section marks, no "L3" or "F1", no slide numbers, no backticks. The check
  refuses them. "Our own records show the application is in, not approved"
  replaces "per `status.md` §1".
- **Keep quiet things quiet, without hinting at them.** Where a rule names
  something on the private list, say "work that is not public yet" and stop.
  Never name it, describe it closely enough to identify it, or say "a secret
  partner". The denylist check refuses a name; you are responsible for the
  hint.
- **Plain and exact.** Write for someone who has never seen the engine. Keep
  every limit the rule sets: a careful-wording theme names its exact cleared
  words in quotes in `now`, so the person sees what may be said.
- **No status word the brand has not earned.** The status-word check refuses
  them, as it does in every post.

## steps

1. `engine theme_words facts`, then read
   `state/theme-words/facts.json`. Each theme has its
   grade, its rule, what it is and why it is ours, its `hash`, and `words`:
   `missing`, `out of date` or `current`. Write the ones that are not
   current; leave the others out of the draft.
2. Write `state/theme-words/draft.json`:

   ```json
   {"themes": {
     "#ExampleTheme": {"hash": "<from facts.json>", "now": "...", "not": "...", "why": "...", "next": "..."}}}
   ```

3. `engine theme_words publish`. Fix what it
   names and publish again; after three failures, stop and report the
   problems.

## never

- Never write anything but `state/theme-words/draft.json`.
- Never change a grade, or say a theme is allowed when its rule says it is
  held: the words explain the grade, they do not argue with it.
- Never name anything on the private denylist, or claim as done what the rule
  calls planned.
