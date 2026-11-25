# linkedin-post: browser mechanics

What worked on a company page through Claude in Chrome, as of 2026-11-05.
When a selector fails, screenshot, find the element, update this file. The
page's numeric id is the `LinkedIn` row under `own channels` in
`.atelier/memory/handles.md`; `<page id>` below stands for it.

## session

- `tabs_context_mcp`, then a new tab. Only the extension's Chrome is signed in.
- Admin: `https://www.linkedin.com/company/<page id>/admin/page-posts/published/`.
  The share box ("Start a post") sits above the published list; a waiting
  draft shows there as "Draft: <first words>". The dashboard's **Create, then
  Start a post** opens the same composer.
- After LinkedIn's in-page navigation the extension's accessibility tree goes
  stale: `find` and `read_page` describe the previous page or return nothing.
  Read the live DOM with `javascript_tool` instead, or reload the tab.
- A composer or Editor left open blocks navigation with a "Leave site?"
  dialog even after the draft is saved. Open a new tab, or pass `force: true`
  to `navigate` once the draft is confirmed saved.

## typing and mentions

- Click the editor ("What do you want to talk about?") and `type`. Newlines
  arrive as Return.
- Mentions: type `@` plus the name, wait about two seconds, screenshot, click
  the entry. Companies show "Company, <industry>"; people show degree and
  headline. Pick by photo and headline, never by position in the list. The
  mention renders bold.
- The saved draft reopens with `(` `)` around a mention turned into commas.
  Put the caret right after the mention (click between it and the next word,
  check with a zoom) and type the missing comma; read back before saving.
- Read back:

```js
[...document.querySelectorAll('[contenteditable=true]')].map(e=>e.innerText).filter(t=>t.trim())[0]
```

  and the mentions from `a.ql-mention` (`data-entity-urn` tells person
  `fsd_profile` from company `fsd_company`). Trailing blank lines in the
  editor are trimmed on posting.

## link preview

A URL in the text loads a preview card that hides the media buttons. Remove it
with its cross ("Remove media"); the URL stays in the text and our image becomes
the visual.

## image

The composer's image icon (bottom left of the dialog, not the page's Photo
button, which closes the composer and saves the draft) opens an **Editor**
modal that lives in an iframe, `iframe[src*="/preload/"]`, with the file input
`#media-editor-file-selector__file-input`. The extension's `find` cannot
return a ref inside that iframe, so `file_upload` has nothing to target. Two
paths that worked:

1. **Input in the top document**: patch `HTMLInputElement.prototype.click`
   (and `showPicker`) to keep `type=file` inputs in the page instead of
   opening the Mac picker, click Add media, `file_upload` to the input the
   patch kept, restore both functions.
2. **Input inside the iframe**: serve the image locally and set the input's
   files from page script. `fetch` to localhost is blocked by LinkedIn's
   `connect-src`, but `img-src` allows `*`, so load it as an image:

   ```bash
   engine serve_asset "<absolute path under Content/Calendar/attachments>"
   # serves it at http://127.0.0.1:8765/asset with a CORS header; Ctrl-C or pkill when done
   ```

   ```js
   const img=new Image(); img.crossOrigin='anonymous';
   const ok=new Promise((r,j)=>{img.onload=()=>r(1); img.onerror=()=>j(new Error('img'))});
   img.src='http://127.0.0.1:8765/asset?'+Date.now(); await ok;
   const c=document.createElement('canvas'); c.width=img.naturalWidth; c.height=img.naturalHeight;
   c.getContext('2d').drawImage(img,0,0);
   const blob=await new Promise(r=>c.toBlob(r,'image/jpeg',0.95));
   const d=[...document.querySelectorAll('iframe')].find(f=>f.src.includes('preload')).contentDocument;
   const inp=d.getElementById('media-editor-file-selector__file-input');
   const dt=new DataTransfer(); dt.items.add(new File([blob],'<name>.jpg',{type:'image/jpeg'})); inp.files=dt.files;
   inp.dispatchEvent(new Event('change',{bubbles:true}));
   ```

   The first image load may sit on Chrome's local-network permission and the
   call can time out at 45 s; the upload still lands. Screenshot to confirm the
   Editor shows the photo before doing anything else. Canvas re-encodes the
   JPEG at the same pixel size; for a PNG card use `'image/png'`.

In the Editor: **ALT** opens alt text (write what the image shows, in the
copy's own words); the person icon tags people on the image; **Next** returns
to the composer with the image attached.

## save

Close cross at the top right of the composer, then "Save this post as a
draft?", then **Save as draft**. The notice "Draft successfully saved" appears
and the share box reads "Draft: ...". Check the newest published post has not
changed.

## finding the activity URL after posting

On the admin Page posts view:

```js
[...document.querySelectorAll('[data-urn*="activity"],[data-id*="activity"]')]
  .map(el=>({urn:(el.getAttribute('data-urn')||el.getAttribute('data-id')).match(/urn:li:activity:\d+/)?.[0],
             text:el.innerText.replace(/\s+/g,' ').slice(0,120)}))
  .filter(o=>o.urn)
```

URL: `https://www.linkedin.com/feed/update/<urn>`. The admin view shows
relative times ("1m", "1d"); the post page shows the absolute time.
