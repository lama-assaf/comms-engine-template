---
name: linkedin-post
description: Stage a post on the brand's LinkedIn company page as the page's draft in the user's Chrome, with @mentions resolved and the image attached, then record the activity URL once a person has posted it. Use when asked to post, draft or stage anything on LinkedIn, or to record a LinkedIn post that went out.
---

# linkedin-post

A person presses Post. This skill stages the post as the page's draft and
records it once it is out. Nothing here sends (CLAUDE.md, "Every send goes
through `channels.send()`"); `Published` on a row only records a post a person made.

Why the browser and not the API: LinkedIn's Posts API publishes live and has
no draft state for a page, so a draft saved in the person's own signed-in
composer is the only way to stage a post they still send themselves.

The brand's page is the `LinkedIn` row under `own channels` in
`.atelier/memory/handles.md` (its slug or numeric id); "the page" below means
that row. Nothing here hard-codes one.

## inputs

1. **Text.** Approved copy as approved; the user's own words are the copy, with
   names and spelling fixed from the campaign's previous copy.
2. **Image.** Copy a Downloads file into `Content/Calendar/attachments/<campaign>/`
   first; that folder is the record and the only place `file_upload` and the
   local hand-off can read from. A motion card made with `/motion` is already
   in place: attach `Content/Motion/<id>/<id>-square.mp4` instead of an image,
   and give its beats as the alt text.
3. **Mentions.** Who to tag, by name. The LinkedIn column of
   `.atelier/memory/handles.md` says who is mentionable, who is tagged by their
   office instead, and who cannot be mentioned at all.
4. **Calendar row.** `Stream` the brand's name, `Platform` LinkedIn, `Status`
   Drafting. Create it when none exists, in the shape of the campaign's other
   rows.

## checks before typing

Quote the failing line. Approved copy is not edited; a failing check on it is
a question for the user, and a cleared wording becomes a rule, never a
one-off edit.

- **Length and fold.** 3,000 characters. The feed shows about 210 before "see
  more" on desktop and about 140 on a phone, so the first line carries the
  post; hashtags go last.
- **Mentions.** A person is mentioned only when their profile is the one
  (photo, headline naming the company, degree). An unverified match (a
  no-photo profile under the right name) means the office or company page is
  tagged and the person stays plain text. Someone whose profile blocks
  mentions stays plain text everywhere, image tags included. Mentions insert
  the profile's own name (a short form typed becomes the full name on
  resolve); write around that.
- **Link.** The article URL goes in the text, with our own image and the
  preview card removed. No first-comment link. An event or photo post has no
  link.
- **Status words and stealth.** Same rule as X: no "certified", "accredited",
  "live", "deployed" beyond what `status.md` evidences; nothing from the
  stealth list; no `[placeholder]`. A present-tense capability sentence needs
  a `claims.md` row, so run `claim-gate` on anything beyond an event or photo
  post.
- **One draft per page.** The page's share box holds a single draft, per
  browser, and saving over it is silent. Check the admin Page posts view: a
  "Draft: ..." chip means a post is already waiting. Open it and read it; a
  draft this skill did not write is never overwritten, and the new post stays
  a paste kit on its row until the first is out.
- **Alt text and image.** JPG or PNG. Alt text under 120 characters, saying
  what the image shows in the copy's own words.

## stage the draft

Browser mechanics are in [`reference.md`](reference.md). The shape:

1. Confirm the extension is connected and the composer header reads the
   page's name, **Post to Anyone**. A login page means stop and ask; never
   type a password.
2. Type up to each `@Name`, wait for the dropdown, pick the right entry, then
   continue. Parentheses around a mention become commas on save; punctuate so
   that reads well.
3. Remove any link-preview card so the media buttons return.
4. Attach the image. The file input lives inside LinkedIn's media-editor
   iframe, which the extension cannot see; hand the file over from page
   script as the reference describes. Add alt text in the Editor, then Next.
5. Read the text back from the editor and compare to the intended text, and
   read the mentions as links (`a.ql-mention`): an unresolved mention is plain
   text that looks identical, so the link list is the only proof.
6. Close the composer and choose **Save as draft**. The share box then shows
   "Draft: ...". The only buttons ever clicked are Close and Save as draft:
   never Post, never the clock (schedule).
7. Note "draft saved on LinkedIn, <time> <zone>, mentions resolved: ..." on the
   row's Notes, the time in the stream's timezone (`autopilot.timezone`). The
   row stays `Drafting`: pending until a person posts and the URL is recorded.

If the browser path fails (extension disconnected, the Editor refuses the
image, a login page), stop and hand the user a **paste kit**: the final text,
which @mentions to type and pick, the image path and the alt text.

Done when: the share box shows the draft, the read-back matches with every
intended mention resolved, the image is attached, and the row's Notes say so.
Tell the user the draft is in the page's share box.

## record the post

When the user says it is posted:

1. Open the admin **Page posts** view and read the newest posts' text and
   activity URN; match on the text. The URL is
   `https://www.linkedin.com/feed/update/<urn>`.
2. Set the row `Published` with that URL and the time in Notes; catch up any
   older row of the campaign whose post is live but whose row is not.
3. Append the URL to the campaign's decision file under its dated "posted"
   heading and add the post to the engagement sheet as "our post".
4. Ask the people mentioned to reshare in their own words; that reach is what
   a page post lacks on its own.

Done when: every live post of the campaign has a `Published` row with its URL.
