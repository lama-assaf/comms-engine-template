# x-post: browser mechanics

What worked on x.com through Claude in Chrome, as of 2026-11-05. Selectors
change; when one fails, take a screenshot and find the element, then update
this file. "The own handle" below is the `X` row under `own channels` in
`.atelier/memory/handles.md`.

## session

- `tabs_context_mcp` first; create a tab rather than reusing one. The headless
  DevTools Chrome is not signed in, so only the extension's Chrome works.
- `https://x.com/compose/post` opens the composer over the home feed. The side
  bar's account card must read the own handle.
- Wait about three seconds after navigation; the first screenshot is the X
  logo on black.

## typing

- Click the "What's happening?" area, then `type` the whole text. Newlines in
  the typed string arrive as Return, which is what a blank line needs.
  **cmd+Return posts.**
- Read back: `[data-testid="tweetTextarea_0"] [data-block]` elements, one per
  paragraph (the editor keeps an empty last block that X trims on posting).
  The character counter sits left of Post; "20" means twenty left.
- Mentions render blue as you type when the handle exists. A blue mention is
  not proof it is the right account; `handles.md` is.

## thread (link as the second post)

- The Add post button (`[data-testid="addButton"]`) has ignored mouse clicks.
  Call `.click()` on it from `javascript_tool`, then check that
  `[data-testid="tweetTextarea_1"]` exists and has focus before typing.
- The composer's button becomes **Post all**. Never click it.

## image

- `find` "file input for media upload in the compose dialog" returns a
  `button (file)` ref inside the dialog (a second one belongs to the home
  timeline's box; use the dialog's).
- `file_upload` with that ref and an absolute path under the working directory.
  Paths under `~/Downloads` are refused; copy into
  `Content/Calendar/attachments/<campaign>/` first.
- The preview shows Edit (alt text lives under it) and a remove cross. 4:5
  cards and 4:3 photos both upload at full size.

## save

- The Close cross (`[data-testid="app-bar-close"]`, top left of the dialog)
  needs two clicks: the first shows its tooltip. "Save post?" then offers Save
  and Discard. Choose **Save**.
- Drafts: `https://x.com/compose/post/unsent/drafts`, "Unsent posts" tab. A
  thread shows "1 more post". A draft saved here is visible in the X app on the
  person's phone.
- Navigating away while a composer is open may be blocked by a "Leave site?"
  dialog; save first, or open a new tab.

## finding the permalink after posting

From `https://x.com/<own handle>`, `javascript_tool`, with the handle (no `@`)
in place of `HANDLE`:

```js
[...document.querySelectorAll('article')].slice(0,4).map(a=>({
  text: a.querySelector('[data-testid=tweetText]')?.innerText.slice(0,90),
  link: [...a.querySelectorAll('a[href*="/status/"]')].map(l=>l.getAttribute('href'))
          .find(h=>new RegExp('^/HANDLE/status/\\d+$').test(h)),
  time: a.querySelector('time')?.getAttribute('datetime')}))
```

The permalink is `https://x.com/<own handle>/status/<id>`; `time` is UTC, so
convert to the stream's timezone (`autopilot.timezone` in `engine.json`)
before writing it on a row. A pinned post sits first whatever its date.
