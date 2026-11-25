# brief: directing a motion card (atelier:motion-direction)

Use the skill for timing and movement: how long a line holds, what enters
first, where the eye rests. The card's words and its look are fixed by this
engine and are not the skill's to choose:

- Every line on a card is lifted word for word from the gated post. A lifted
  line stays as the post has it; nothing is paraphrased, shortened inside a
  sentence, or added. `scripts/motion.py check` refuses a line the post does
  not carry.
- The colours, the type and the logo come from the brand genome
  (`.atelier/memory/brand-genome.json`). No other palette, no stock footage,
  no generated image, voice or music: `motion:generate` makes paid calls and
  stays closed unless a person recorded a cost sign-off.
- A card carries the theme hashtag and the link, once each.
- No motion that would trigger a seizure warning: no flash above three a
  second, no full-frame strobe.

You write only the storyboard under `Content/Motion/<id>/`. Nothing is posted.
