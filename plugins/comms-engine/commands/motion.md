---
description: Make the motion for one gated post - a text card (lines lifted from the post, its hashtag and its link, rendered to MP4, GIF and a poster) through the motion-designer agent, or with --film a film from the brand kit through the Motion plugin, its words held to the same rule. Never posts.
argument-hint: <post id> [square|wide] [--film]
allowed-tools: Bash, Read, Write, Edit, Agent, Skill
---

# /motion

For one post, on request. The cycle makes the blog posts' text cards itself
(`/social-cycle` step 7a); this is for a card outside it, a redo, or a film.

Take the post id from `$ARGUMENTS` (a `Q-...` id) and the format if one is
given (`square` by default, `wide` for a link-preview slot). With no id, run
`engine gate_lint` and list the posts whose
verdict is `pass` or `pass-with-edits`, then ask which one.

## the text card (the default)

1. Spawn the `comms-engine:motion-designer` agent with the id and the format.
2. Show the person what it reports: the beats in order (the clip's alt text),
   the length, and the files under `Content/Motion/<id>/`. Say that the clip is
   attached by a person when they post, with the x-post or linkedin-post skill.

## the film (`--film`)

A film is the post made with the Motion plugin (`motion@atelier`) from the
brand kit. It is made here, in a session a person is in, and never in the
cycle: the plugin asks what only a person knows and shows stills before it
renders, and the scheduled runs switch the plugin off. Where a film exists it
is the post's video on every page, ahead of the text card.

1. **The kit.** Without `brand/motion-kit/Motion.md` the plugin stops, so when
   it is missing run `engine motion kit --write`:
   it writes the kit from the brand genome, the look every other visual has,
   and never overwrites one. If it refuses because the genome is still the
   template's placeholder, say so and make the text card instead.
   `/motion:brand-kit` refines a kit (font files, logo rules); it is never
   needed first.
2. **The lines.** `engine motion brief <id>`
   prints the gate's verdict and every sentence the film may lift. With no
   verdict or a block, stop: the post goes back to the gate.
3. **The film.** Invoke the `motion:video` skill (the Skill tool). The plugin
   knows none of this repository's rules, so its brief carries the ones
   `motion.py film` holds the page to:
   - the project is named exactly the post's id: `videos/projects/<id>/`,
     rendered to `videos/finals/<id>-v<N>.mp4`;
   - every visible string sits in an element that carries `data-says` and is
     lifted word for word from one of the brief's sentences: a contiguous run
     of words from one sentence, never two stitched together;
   - the end card may add the post's theme hashtag in an element of class
     `tagline` and the main domain of its CTA, never the full URL, in one of
     class `link`;
   - a voice-over line is an `<audio>` that carries its words in
     `data-says-aloud`, lifted the same way;
   - nothing else is on screen: no caption, label, number, name or date the
     post does not have, no text a script writes into the page or a stylesheet
     draws, no `text:` option, no form field with a value (`motion.py film`
     refuses each), and no text inside an image or in a script file the page
     loads, which it cannot read;
   - the format asked for.
4. **The check, before any render.** `engine motion film <id>`
   until it prints `film words ok`, three tries at most. Fix the page, never
   the post, a teaser or its gate verdict.
5. **The render.** Through the plugin (`motion:render`), then `motion.py film <id>`
   once more: it writes the poster beside the post's storyboard and names the
   final.
6. **The log.** `engine runlog motion "<id>: film, <seconds> s, <format>; videos/finals/<id>-v<N>.mp4" --stream "<the post's stream>"`.
7. Show the person the film's lines in order, its length and the final. It is
   attached by a person when they post, with the x-post or linkedin-post skill.

## never

- Post, stage, schedule or attach the clip or the film. `motion:post`
  (Instagram, a channel `channels.send()` does not know) and `motion:generate`
  (paid calls) are denied in `.claude/settings.json`, and the posting hook
  refuses a `composio execute INSTAGRAM_*` typed by hand.
- Make motion for a post the gate blocked or has not read, or edit a post, a
  teaser or its gate verdict to make a card or a film pass.
