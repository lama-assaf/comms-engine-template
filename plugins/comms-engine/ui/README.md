# The control page's web app

The control page (`/control`, `scripts/control.py`) is this app: Vite, React and
TypeScript over one read, `GET /api/state`, which is every view
`scripts/views.py` computes, and the few changes `control.py` allows (`POST
/api/<change>`, with the token written into the page). It never reads a file
itself and never posts anything.

`dist/` is the built app and is committed, so a fresh clone runs the page with
plain `python3`. Node is needed only to change the app.

```bash
cd ui
npm ci                 # once: the exact versions in package-lock.json
npm run dev            # http://127.0.0.1:5173, reading the running control page (control.py start)
npm run build          # type-check, then write dist/; commit dist/ with the change
```

The dev server reads the engine through the running control page and has no
token, so it shows everything and changes nothing. Make changes on the built
page at http://127.0.0.1:4320/.

## The look

Everything comes from `.atelier/memory/brand-genome.json` through
`src/genome.ts`:

- **The neutrals** are the genome's `colors`: white, the greys and the ink.
- **The colours** come from `palette`, in its `style`:
  - `pastel` (the default) shows each colour as a tone: a soft fill, a deep
    shade of the same hue for the text on it (WCAG 4.5:1 or better), and the
    colour itself for small marks such as icon circles and dots;
  - `solid` shows the colour itself, with white or ink text.
- **Roles:** `roles` names what critical (stopped), warning (small fixes),
  good (ready), action and info look like. Those status colours are never
  used for a page or a theme.
- **Pages, themes and the story's beats** take a colour by position, strided
  through the list so neighbours differ. A colour follows its page or theme.
- **The strong anchor** is `colors.primary`: the big tile on Today, the
  story's cover and closing slide, the main buttons and the phone tab bar.
- **Corners** come from `shape.ui_radius`. `shape.radius` stays the rule for
  what the brand publishes.
- **The type** is Inter, bundled into the page (`@fontsource-variable/inter`),
  so no font is fetched from the web.
- **Text on a coloured fill** is white or the ink, whichever passes WCAG
  contrast on that fill.

## Where things are

| path | what it is |
|---|---|
| `src/App.tsx` | the frame: the rail, the phone tab bar and More sheet, the drawers, the toast, navigation by `#/<page>` |
| `src/nav.ts` | the pages, their words and icons, in menu order |
| `src/pages/*.tsx` | one file per page; `Story.tsx` is the deck, the landing page |
| `src/drawers/Drawers.tsx` | a post in full, a theme to edit or add, a suggested account, a finding |
| `src/components/DataTable.tsx` | the database table: search, filters, sorting remembered per table in this browser |
| `src/components/ui.tsx` | chips, the plain-words box on every page, the page head, the drawer |
| `src/genome.ts`, `src/styles.css`, `src/deck.css` | the look |
| `src/types.ts` | the shapes `views.py` returns, by hand until `PLAN-surfaces.md` step 3 generates them |

`control/page.html`, the first page, answers at `/classic` until this app
matches it. Then it goes (`PLAN-surfaces.md`, step 5).
