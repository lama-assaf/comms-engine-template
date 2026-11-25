# gate, on the labelled set

You are reading labelled drafts, not the live queue: this run measures the
reviewers. Read them exactly as you would read the queue, and do not guess at
the labels; a reviewer that blocks everything fails this set as surely as one
that passes everything.

- The items are the JSON list in the file `{cases_file}`. Read every one.
- The stream is the fixture brand {stream_name}. Its memory, and the only
  evidence, is the directory `{memory_dir}`: `claims.md` is the claims
  register, with `themes.md`, `handles.md`, `handles.private.md` and
  `voice.md` beside it. Read no other stream's memory and nothing under
  `.atelier/memory/`.
- Run `engine review sentences --file
  {cases_file}` first: it prints, per item, the sentences code will look for,
  already split, the title's first. Judge every sentence it lists, in that
  order, and copy `field` and `text` as printed; a sentence left out blocks
  the item, however plainly it is not a claim.
- A fact about a third party (another
  body's publication, a regulator's words, a public event) may instead rest on a
  source the item lists under `sources`: its `cite` is that source's id (`S1`)
  and `rests_on` is copied from the source's `quote`. Never a source for a
  sentence about the brand ("we", "our", the brand's name), a statistic or a
  capability: those need a register row.
- For every sentence of an item's `title`, `post`, `teaser_linkedin` and
  `teaser_x`, in order: is it a claim (a checkable fact about the brand, a
  partner, a number or a date), and if so which register row, by id, it rests
  on, which words of that row's `claim` cell, and whether the row supports the
  sentence in the tense it is written in. A claim no row carries is
  `claim: true` with `cite: null`.
- Report house style under the check `register`: a hook outside 6 to 17 words,
  a hashtag or an emoji in a hook, a teaser without the theme hashtag or with a
  second one, a teaser without the link back to the post or a link that does
  not match the item's `slug`, and a draft whose hook form, opening and closing
  repeat the pieces listed under the item's `before`. Quote the line and name
  the fault in `fix`, starting with the rule it breaks: `hook:`, `tag line:`,
  `cta:` or `shape:`.

You write no file. Code checks what you return against the text and the
register.

Return: `items`, a list with one object per item: `{id, sentences, checks,
note}`, as `engine review schema` describes.
