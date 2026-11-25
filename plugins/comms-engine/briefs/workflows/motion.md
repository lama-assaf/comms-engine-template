# motion

`scripts/motion.py pending --render` has already rendered every card whose
storyboard still passes. Run `engine motion
pending --json` and, for each post id it lists as needing a storyboard, make
the card as your definition describes (format `square`), with
`atelier:motion-direction` for the timing under the brief
`briefs/motion-direction.md`: write the storyboard,
check it, render it and log your own `motion` entry. A card that will not pass
its check after three tries, or a render that fails, is reported and left:
motion never holds a post back.

Return: `made` (cards rendered), `refused` (cards that would not pass) and
`ids_refused` (their ids).
