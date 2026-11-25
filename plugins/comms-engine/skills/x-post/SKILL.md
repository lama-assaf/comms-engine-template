---
name: x-post
description: Stage an X post or thread from the brand's own X handle as a draft in the user's Chrome, then record the permalink once a person has posted it. Use when asked to post, tweet, draft or stage anything on X, or to record an X post that went out.
---

# x-post

A person presses Post. This skill does everything either side of that press:
it stages the post as a draft the person can open from their phone, and it
records the post once it is out. Nothing is sent from here (CLAUDE.md, "Every send goes
through `channels.send()`"), and `Published` on a calendar row only ever
records a post a person already made.

Why the browser and not the API: X has no draft endpoint, and a post sent
through the API is a post sent. A draft saved in the person's own signed-in
composer is visible in their X app and is theirs to send.

The own handle is the `X` row under `own channels` in
`.atelier/memory/handles.md`. Every place below that says "the own handle"
means that cell; nothing here hard-codes one.

## inputs

1. **Text.** Approved copy goes out as approved: a check that fails on it is a
   question for the user, never an edit. The user's own words from the room
   are the copy, with spelling and names fixed. Fill a name from the previous
   copy on the same campaign before asking.
2. **Image.** `file_upload` accepts only files under the working directory, so
   copy a Downloads file into `Content/Calendar/attachments/<campaign>/` first,
   named for what it shows. That folder is the record of what went out.
   A motion card made with `/motion` is already in place: attach
   `Content/Motion/<id>/<id>-<format>.mp4` instead of an image, and give its
   beats as the alt text.
3. **Calendar note.** The post's note in `Content/Calendar/`. When none
   exists, write it through the control page's new-post form (channel X, its
   day), which makes it a draft like any other; the staging facts go in the
   run report, never into the note by hand.

## checks before typing

Run every one; quote the line that fails. Fix the rule, not approved copy: a
failing check on approved copy is a question for the user, not an edit, and
once the user clears the wording it becomes a rule (a decision file, a line in
`status.md` or `voice.md`, a pattern in the checker).

- **Weighted length.** 280 weighted, by X's own rules: every URL counts 23
  whatever its length, emoji and most non-Latin characters count 2, mentions
  count in full. Count before typing, because the composer truncates instead
  of refusing; then read the counter off the composer before saving.
- **Handles.** Every `@` in the text is in `.atelier/memory/handles.md` as
  `verified`, or the user supplied it in this session. A handle the copy marks
  `[@handle]` and nobody has confirmed comes out, and the person is named as
  text; `handles.private.md` is the stealth denylist and must be present
  (its absence blocks). When the user tags a handle at posting time that memory
  lacks, open the profile, check it is the person, and add the row.
- **Link.** In the body or as the second post of the same thread, published
  together, never a reply added later. Engine teasers carry the UTM tag the
  stream's link rule names. A post with no article (an event post) has no link.
- **Status words and stealth.** No "certified", "accredited", "live",
  "deployed", "launched" about anything `status.md` does not evidence; nothing
  from the stealth list in `instincts.md`; no `[placeholder]` left. A
  present-tense capability sentence needs a `claims.md` row at grade evidenced,
  so run `claim-gate` on anything that is not a plain event or photo post.
- **Single pillar.** The brand's voice from the own handle; a line in a paired
  stream's voice goes through that stream's own handle and skill run, never
  from here.

## stage the draft

Browser mechanics, selectors and the things that bit us are in
[`reference.md`](reference.md). The shape:

1. Confirm the Chrome extension is connected and the composer shows the own
   handle. A login page means stop and ask; never type a password.
2. Type the text with Return for blank lines. For a thread, add the second
   post through the Add post button and confirm the focus moved before typing.
3. Attach the image through the compose dialog's file input, with
   `file_upload`, never by clicking the media icon (that opens the Mac picker).
4. Read the text back from the composer and compare it to the intended text,
   character for character; check the counter.
5. Close the composer and choose **Save**. Confirm the draft is listed at
   `https://x.com/compose/post/unsent/drafts`. The only buttons ever clicked
   are Close and Save: not Post, not Post all, not cmd+Return.
6. Note "draft saved on X, <time> <zone>, read back from the composer" on the
   row's Notes, the time in the stream's timezone (`autopilot.timezone`). The
   row stays `Drafting` so the autopilot never takes it: pending until a person
   posts and the permalink is recorded.

If the browser path fails (extension disconnected, a 403 or "something went
wrong" on the image upload, a login page), stop and hand the user a **paste
kit**: the final text, the image path and what to attach. A 403 on media is
how X signals it has noticed automation; do not retry it.

Done when: the drafts page lists the post with its image, the read-back
matches, and the row's Notes say so. Then tell the user where the draft is.

## record the post

When the user says it is posted (or on request later):

1. Open `https://x.com/<own handle>` and read the newest posts' text, permalink
   and time; match on the text, never on position alone.
2. Set the row `Published`, with the permalink and the posting time (in the
   stream's timezone) in Notes. Do the same for any older row of the campaign
   whose post is live but whose row still says Drafting or Ready.
3. Append the URL to the campaign's decision file under a dated "posted"
   heading, and add the post to the engagement sheet as "our post" (the sheet
   lists decisions and acts only, no self-replies).
4. If the live post carries a handle memory lacked, record it in `handles.md`
   with a log line saying who supplied it and how it was checked.

Done when: every live post of the campaign has a `Published` row with its URL.
