---
name: motion-post
description: Make a motion card for one gated post - a short animated clip of lines lifted from the post, then its theme hashtag, then its link - rendered to MP4, GIF and a poster frame for X and LinkedIn. Use when a person asks for motion, an animated teaser, a video or a GIF version of a post. Writes only the storyboard; scripts/motion.py checks it against the post and renders it. Never posts.
---

# motion-post

A motion card is the post, moving: three or four of its own lines appear in
turn, then its hashtag, then its link. It is a teaser format, not new copy. The
claim gate has already read every word the card may carry, and the card may
carry nothing else.

You write one file, the storyboard. `scripts/motion.py` decides everything
else: it refuses any line that is not word for word in the gated post, a tag
that is not the post's theme, a link that is not the post's CTA, any denylist
term, and any post the gate blocked or never read. It draws every frame itself,
so the motion is the same on every card.

## when

- In the cycle: step 7a of `/social-cycle` gives every upcoming blog post the
  gate let through (`pass` or `pass-with-edits`) a card, a few per cycle,
  approved posts first, then the soonest slot; it asks `motion.py pending` which ones, and the card is redone when an
  edit moves the post past it.
- On request (`/motion <id>`), for any such post, at any time.
- Not for a film. `/motion <id> --film` makes one with the Motion plugin from
  the brand kit, in the session a person is in; `motion.py film <id>` holds its
  words to the rule this card follows, and a post with a film owes no card.
- Not for a fact (an announcement): its copy is the partner's as much as ours,
  and its visuals are the release's own banner.

## steps

1. `engine motion brief <id>`. It prints the
   post's gate verdict, theme and CTA, every sentence you may lift (numbered,
   with the field it comes from), the limits and the storyboard's shape. If the
   gate has not read the post or blocked it, stop and say so.
2. Choose the beats. One job each (continuity, state, hierarchy, voice); a
   beat that does none of them is cut.
   - **beat 1, the hook**: the post's opening line or its title, as written.
   - **one or two argument lines**: the turn of the post, the sentence a
     reader would quote. A contiguous run of words from one sentence is
     allowed when the whole sentence is too long; never stitch two sentences
     together, never change a word, never add one.
   - **the tag**: the post's theme hashtag, exactly.
   - **the link**: the post's CTA, last, or left out. On screen it is a
     pointer, not a click: the clickable link still goes in the first reply
     on X and the first comment on LinkedIn, as for every teaser.
   - Keep the "what we do not claim" sentence out of the card: it belongs to
     the full piece, where it can be read whole.
3. Time it. `hold_ms` per beat, 800 to 4000: about 1 s per four words, at
   least 1.5 s for any line a reader must finish. The whole card at most 15 s;
   8 to 12 s plays best on both channels.
4. Pick the format: `square` (1080 x 1080) for LinkedIn and the X timeline,
   `wide` (1200 x 675) where the card replaces a link-preview image.
5. Write `Content/Motion/<id>/storyboard.json`:

   ```json
   {"format": "square", "beats": [
     {"role": "line", "text": "<the hook, as written>", "hold_ms": 2200},
     {"role": "line", "text": "<an argument line, as written>", "hold_ms": 2000},
     {"role": "tag",  "text": "#TheTheme", "hold_ms": 1000},
     {"role": "cta",  "text": "<the post's CTA URL>", "hold_ms": 1800}]}
   ```

6. `engine motion check <id>`. Fix what it
   names and run it again; after three failed checks, stop and report the
   problems rather than bending a line to fit.
7. `engine motion render <id> --dry-run`,
   then without `--dry-run`. It writes `<id>-<format>.mp4` (with ffmpeg),
   `.gif` and `-poster.png` beside the storyboard.
8. Report the paths and the beats as plain text. The beats, in order, are
   also the clip's alt text: hand them over with the files.

## what the renderer does, so you never specify it

- A line enters in 300 ms, ease-out, rising 24 px into place; it leaves in
  200 ms, ease-in, as a fade. One beat on screen at a time; the last stays.
- Nothing moves longer than 600 ms, nothing bounces, nothing loops inside the
  card. The one linear motion is the progress line along the bottom.
- The stream's name sits small at the bottom left. Colours come from the brand
  genome (`.atelier/memory/brand-genome.json`: primary behind, on-primary text,
  accent for the tag and the progress line), unless `params.motion`
  (`background`, `text`, `accent`, `font`) overrides them.

## never

- Never write a word into a beat that the gated post does not carry.
- Never render a post the gate blocked, and never re-gate it yourself to get
  a pass.
- Never post, stage or attach the clip: a person does that with the x-post or
  linkedin-post skill.
- Never write anything but the storyboard: the renders come from
  `motion.py`, and the calendar note is written only by `repo.py`.
