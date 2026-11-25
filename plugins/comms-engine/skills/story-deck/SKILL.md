---
name: story-deck
description: Write the story of a run as a short slide deck - where we stand, what we found, the big questions, what is worth exploring and what is worth adding - from the facts scripts/story.py gathered, for the control page's landing page. Use at the end of every cycle (/social-cycle step 7b), or when a person asks for the story, a recap or "what do I need to know". Writes only the draft; story.py checks and publishes it.
---

# story-deck

The story is how a person catches up in two minutes on a phone. It is a deck,
not a report: one idea per slide, said big, in plain words. The control page
opens on it, in the brand genome's flat colours. You write the words;
`scripts/story.py` checks them and publishes them; nothing is posted.

## the arc

Every story runs the same five beats, in this order, so a reader always knows
where they are:

1. **cover**: the one-line headline of this run. What changed since last
   time, said as a plain sentence ("Four posts are ready; the listener found
   the banks moving first").
2. **state**: where we stand. One big number from the facts (`figure`) and up
   to three short points. Lead with what a person must act on.
3. **discoveries**: what the listener and the research found that matters,
   up to three, each with its source id (`F1`, a claim idea's source).
4. **question**: one to three big questions only a person can answer. A
   question is a decision, not a quiz: "Should #ExampleTheme stay held until
   the pilot has run?", with `why` (what changes with the answer) and
   up to four `options` when the choices are clear. Never ask again what is
   still open in `questions.open`, and never ask what was answered: use the
   answers in `questions.answered_since_last_story` and say on the state or
   next slide what they changed ("You said keep it held: it stays held").
5. **explore** and **add**: areas worth looking into (an account the
   suggestions keep showing, a theme the listener hears a lot about but we do
   not hold, a claim idea worth checking), and things worth adding, each with
   a `kind` (theme, account, claim, post, other) and a `why`. An `add` item
   the person can act on carries what the page needs to do it: `handle` (one of
   `accounts.top_suggestions`, exactly; "Watch @x" then watches it) or `tag`
   for a new theme ("Add #X" opens the add-a-theme form, filled in).
6. **next**: what happens before the next story: the posts going out, the
   videos being made, what waits on a person.

5 to 9 slides in all. A beat with nothing to say is left out, except the cover
and the state. The page adds its own closing frame after your last slide (a
rating, what the next story should cover, what to always remember); never
write one.

## every slide is answered

Every slide gets buttons and a note box on the page, so the person replies as
they read. The defaults ("Looks right" / "Something is off", "Useful" / "Not
useful", "Look into it" / "Not now") fit most slides; give a slide its own
`actions` (up to 3, at most 5 words each) when a clearer choice exists:
`"actions": ["Write the post", "Hold it"]`.

Read what came back before you write: `responses_to_last_story` (each slide's
action and note), `feedback_on_last_story` (the rating, what to cover next)
and `always_remember` (standing notes: follow every one). Say on the cover or
the state slide what you changed because of them ("You asked for less on
accounts: one slide, not two"). A slide marked "Not useful" twice in a row is
a beat to drop or rethink.

## the words

- **Name the top three, never just a count.** "Watch @bank, @registry or
  @weekly" beats "watch one or two of the 16 suggested accounts"; "the Hong
  Kong bank, the US exchange, the residency pitch" beats "three findings". Take
  them from the facts (`top_suggestions`, `posts.next`, `listening.loudest`,
  `findings`), and give each `add` account item its own `handle`. The page also
  shows the top three of the engine's own data under each slide, so your words
  lead and its list proves them.
- **Write references the page can open.** On the page, a theme written as its
  hashtag (`#ExampleTheme`) opens the theme. An `@handle` opens the
  account. A day written like `17 Nov` opens the post planned for it. An
  item's `source` (`F1`) opens what was heard, with its posts. So name them
  that way, exactly as the facts carry them, and a reader can check every
  line with one tap.

- **Plain words.** Write for someone who has never seen the engine: "the
  check" not "the gate", "approve" not "Alpha decision", "not yet allowed" not
  "held licence", "what we heard" not "findings".
- **Big and short.** Titles at most 12 words; points at most 22; a question
  at most 25. Three points at most on a slide. If it does not fit, it is two
  slides or it is cut.
- **Only the facts.** Every number on a slide must be in `facts.json`; the
  check refuses an invented one. Name only what the facts name. Nothing on the
  private denylist, no status word the brand has not earned, nothing claimed as
  done that the facts call planned: the same rules as every post.
- **Lead with the change.** A story that says the same as last time says so
  in its cover and is short.

## steps

1. `engine story facts`, then read
   `state/story/facts.json`, with what came back from
   the person (above). Read `.atelier/memory/voice.md` for the voice.
2. Write `state/story/draft.json`:

   ```json
   {"slides": [
     {"kind": "cover", "title": "...", "subtitle": "..."},
     {"kind": "state", "title": "...", "figure": {"value": "4", "label": "posts in the next two weeks"}, "points": ["...", "..."]},
     {"kind": "discoveries", "title": "...", "items": [{"text": "...", "source": "F1"}]},
     {"kind": "question", "question": "...", "why": "...", "options": ["...", "..."]},
     {"kind": "explore", "title": "...", "items": [{"text": "...", "why": "..."}]},
     {"kind": "add", "title": "...", "items": [{"text": "...", "kind": "theme", "why": "..."}]},
     {"kind": "next", "title": "...", "points": ["...", "..."]}]}
   ```

3. `engine story check`. Fix what it names
   and check again; after three failed checks, stop and report the problems.
4. `engine story publish`. It gives each
   question its id and keeps it in `state/story/questions.json`, where the
   control page records the person's answer.

## never

- Never write anything but `state/story/draft.json`.
- Never invent a number, a name, a date or a partner.
- Never answer a question yourself, or treat an option as chosen.
