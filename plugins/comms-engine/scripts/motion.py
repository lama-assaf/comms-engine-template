#!/usr/bin/env python3
"""
motion.py - a motion card for one gated post: a storyboard checked against the
post, then rendered to MP4, GIF and a poster frame.

Why: a short moving teaser (lines of the post appearing in turn, then its
hashtag, then its link) gives X and LinkedIn something that plays where a still
banner sits. Motion must not become a way round the claim gate, so the model
writes only the storyboard and this script decides the rest:

- every line is lifted word for word from the gated post (title, post or
  either teaser), so the clip says nothing the gate has not read;
- the tag is the post's own theme, and the link shows only the main domain of
  the post's own CTA (`example.com`, never the full URL: owner, 2026-11-07);
- no denylist term and no unearned status word, through the gate's own checks;
- a post the gate blocked, or never read, gets no motion.

The frames are drawn here, the same way every time, so the storyboard cannot
choose its own motion: a line enters in 300 ms with an ease-out (rising 24 px
into place) and leaves in 200 ms with an ease-in; the last beat stays to the
end; nothing moves for longer than 600 ms and nothing bounces; the only linear
motion is the progress line along the bottom.

Files: the storyboard is `Content/Motion/<id>/storyboard.json`, the record of
what the clip says. The renders beside it (`<id>-<format>.mp4`, `.gif`,
`-poster.png`) are gitignored and rebuilt from it. The MP4 needs ffmpeg;
without it the GIF and the poster are still written. Nothing here posts: a
person attaches the clip when they post (the x-post and linkedin-post skills).

In the cycle (`/social-cycle` step 7a, after the gate): `pending` names the
upcoming blog posts the gate let through that have no card, or whose card no
longer matches the post after an edit, highest first (approved, then the
soonest slot) and at most `params.cycle.motion_per_cycle` of them; a post whose
slot date has passed is skipped, since it went out or waits for a new date; those go to the
motion-designer agent. With `--render` it renders, itself, every card whose
storyboard still passes but has no files on this machine, since that needs no
model. `params.cycle.motion` false turns the cycle's motion off; `/motion`
still works on request.

  engine motion brief <id>      # the post's lines, its gate, the limits
  engine motion check <id>      # the storyboard against the post
  engine motion render <id> [--format square|wide] [--dry-run]
  engine motion pending [--render] [--max N] [--json]   # what the cycle owes
  engine motion film <id>       # a Motion-plugin film: check its words, write its poster
  engine motion kit [--write]   # the Motion plugin's brand kit, from the brand genome

A film (the Motion plugin, `/motion:video`, from the brand kit at
`brand/motion-kit/Motion.md`) is the post's video wherever one exists: its
project is `videos/projects/<id>/` and its renders `videos/finals/<id>-v<N>.mp4`.
`card()` and `pending()` read it ahead of the text card; `film` holds its words
to the same rule as a storyboard, and refuses a page whose script or stylesheet
could put on screen words the markup does not hold (a script that sets text
from a literal or from a value the check cannot read, a `text:` option, the
GSAP text plugins, a CSS `content:` string, a form field's value). Known limit:
a script file or stylesheet the page loads is not read, and neither is text
inside an image; the kit says both stay out of a post's film.

`kit` writes that brand kit from `.atelier/memory/brand-genome.json` when the
project has none, so a first film needs no interview: the look comes from the
genome, the voice stays in `voice.md`, and the two sections the plugin treats as
binding carry this repository's rule (every word lifted from the gated post).
It never overwrites a kit, and it refuses to write one from a genome that is
still the template's placeholder.
"""
import argparse
import datetime as dt
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config  # noqa: E402
import gate_lint  # noqa: E402
import repo  # noqa: E402

MOTION_DIR = os.path.join(repo.REPO, "Content", "Motion")

FORMATS = {"square": (1080, 1080), "wide": (1200, 675)}
FPS, GIF_FPS, GIF_SCALE = 24, 12, 0.5
ENTER_MS, EXIT_MS, RISE_PX = 300, 200, 24
MIN_BEATS, MAX_BEATS, MAX_WORDS = 2, 6, 14
MIN_HOLD_MS, MAX_HOLD_MS, DEFAULT_HOLD_MS = 800, 4000, 1800
MAX_TOTAL_MS = 15000
ROLES = ("line", "tag", "cta")
MATERIAL = ("title", "post", "teaser_x", "teaser_linkedin")

FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


class MotionError(RuntimeError):
    pass


# ------------------------------------------------------------------ the storyboard


def board_path(item_id):
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", item_id)
    return os.path.join(MOTION_DIR, safe, "storyboard.json")


def tokens(text):
    """Words as the lifted-text test compares them: lower case, punctuation dropped."""
    text = str(text).replace("’", "'").replace("‘", "'").lower()
    return re.findall(r"[#@]?[a-z0-9][a-z0-9'\-]*", text)


def _bare_url(url):
    return re.sub(r"^https?://(www\.)?", "", str(url).strip()).rstrip("/").lower()


def domain(url):
    """The main domain a motion piece shows for a link: `https://www.example.com/insights/x`
    is `example.com`. On screen a link is only ever this (owner, 2026-11-07); the full URL
    goes in the first reply on X and the first comment on LinkedIn."""
    return re.sub(r"^www\.", "", re.split(r"[/?#:]", _bare_url(url), maxsplit=1)[0])


def sentences(text):
    """The sentences and lines of one field, as the brief numbers them."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", str(text or "")) if s.strip()]


def lifted(text, item):
    """True when `text` appears word for word, in order, inside one sentence of
    one field the gate read: a beat never stitches two sentences together."""
    words = tokens(text)
    if not words:
        return False
    needle = " " + " ".join(words) + " "
    return any(needle in " " + " ".join(tokens(s)) + " "
               for f in MATERIAL for s in sentences(item.get(f)))


def check_board(item, board):
    """What stops this storyboard from rendering, one line each; empty means it may."""
    problems = _gate_problems(item)
    beats = board.get("beats") if isinstance(board, dict) else None
    if not isinstance(beats, list) or not MIN_BEATS <= len(beats) <= MAX_BEATS:
        problems.append(f"a storyboard has {MIN_BEATS} to {MAX_BEATS} beats in `beats`")
        return problems
    if board.get("format", "square") not in FORMATS:
        problems.append(f"format is one of {', '.join(FORMATS)}")
    theme, cta = str(item.get("theme") or ""), str(item.get("cta") or "")
    total = 0
    for n, beat in enumerate(beats, 1):
        text = str((beat or {}).get("text") or "").strip()
        role = (beat or {}).get("role", "line")
        hold = (beat or {}).get("hold_ms", DEFAULT_HOLD_MS)
        if role not in ROLES:
            problems.append(f"beat {n}: role is one of {', '.join(ROLES)}")
        elif not text:
            problems.append(f"beat {n}: no text")
        elif role == "line":
            if len(tokens(text)) > MAX_WORDS:
                problems.append(f"beat {n}: {len(tokens(text))} words; a line carries at most {MAX_WORDS}")
            if not lifted(text, item):
                problems.append(f"beat {n}: not word for word in the gated post: {text!r}")
        elif role == "tag" and text.lower() != theme.lower():
            problems.append(f"beat {n}: the tag is the post's theme, {theme or '(none recorded)'}")
        elif role == "cta" and (not cta or _bare_url(text) != domain(cta)):
            problems.append(f"beat {n}: the link shows only the main domain of the post's CTA, "
                            f"{domain(cta) if cta else '(no CTA recorded)'}, never the full URL")
        if not isinstance(hold, int) or not MIN_HOLD_MS <= hold <= MAX_HOLD_MS:
            problems.append(f"beat {n}: hold_ms is a whole number from {MIN_HOLD_MS} to {MAX_HOLD_MS}")
            hold = DEFAULT_HOLD_MS
        total += ENTER_MS + hold + EXIT_MS
    if beats and (beats[0] or {}).get("role", "line") != "line":
        problems.append("beat 1 is a line from the post: the hook opens the clip")
    roles = [(b or {}).get("role", "line") for b in beats]
    if "cta" in roles and roles[-1] != "cta":
        problems.append("the link, when there is one, is the last beat")
    if total > MAX_TOTAL_MS:
        problems.append(f"the clip runs {total / 1000:.1f} s; at most {MAX_TOTAL_MS / 1000:.0f} s")
    return problems + _text_checks(item, [str((b or {}).get("text") or "") for b in beats])


def _gate_problems(item):
    verdict = (item.get("gate") or {}).get("verdict")
    if not verdict:
        return ["the gate has not read this post: run gate_lint.py --write and the gatekeeper first"]
    if verdict == "block":
        return ["the gate blocked this post; a blocked post gets no motion"]
    return []


def _text_checks(item, texts):
    """The denylist and the status words, through the gate's own checks, on the
    clip's text alone: a gate verdict can be older than the denylist."""
    problems = []
    pseudo = {"title": "", "post": "\n".join(texts), "teaser_x": "", "teaser_linkedin": "", "stream": item.get("stream")}
    slug = gate_lint.resolve_slug(item)
    for name, fn in (("the denylist check", gate_lint.check_stealth),
                     ("the status-word check", gate_lint.check_status_words)):
        try:
            result = fn(pseudo, slug)
        except Exception as e:  # noqa: BLE001 - a check that cannot run stops the clip
            problems.append(f"{name} could not run ({e})")
            continue
        if result["result"] == "block":
            problems.append(f"{result['check']}: {result['line']} {result['fix']}".strip())
    return problems


# ------------------------------------------------------------------ the film (the Motion plugin)
#
# A film is the post made with the Motion plugin (`/motion:video`) from the brand
# kit (`brand/motion-kit/Motion.md`): its project is `videos/projects/<id>/index.html`
# and its renders `videos/finals/<id>-v<N>.mp4`, named after the post so the engine
# can find them. Where a film exists, it is the post's video on every page, ahead of
# the text card. Its words are held to the same rule as a storyboard: every visible
# string sits in a `[data-says]` element lifted word for word from the gated post,
# except the end card's `.tagline` (the theme) and `.link` (the CTA's main domain only).
# A voice-over is held to the same rule: each `<audio>` line carries the words it speaks
# in `data-says-aloud`, lifted word for word; a file under `assets/vo/` without them is refused.

FILMS = os.path.join(repo.REPO, "videos")


def film_paths(item_id):
    """(project index.html, newest final MP4) for a post, each None when missing."""
    project = os.path.join(FILMS, "projects", item_id, "index.html")
    finals = os.path.join(FILMS, "finals")
    pattern = re.compile(rf"^{re.escape(item_id)}-v(\d+)\.mp4$")
    best = None
    for name in (os.listdir(finals) if os.path.isdir(finals) else []):
        m = pattern.match(name)
        if m and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), os.path.join(finals, name))
    return (project if os.path.isfile(project) else None), (best[1] if best else None)


def read_film(project):
    """What a film's page says: its `[data-says]` lines in page order, the end card's
    tag and link, any visible text outside both (`loose`), its frame and length."""
    from html.parser import HTMLParser

    class Says(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.lines, self.loose, self.tag, self.link, self.skip = [], [], [], None, None, 0
            self.root, self.voice, self.unrecorded = {}, [], []
            self.scripts, self.styles, self.srcs, self.raw = [], [], [], None

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag in ("script", "style", "title"):
                self.skip += 1
            if tag == "script" and a.get("src"):
                self.srcs.append(str(a["src"]))
            elif tag in ("script", "style"):
                self.raw = self.scripts if tag == "script" else self.styles
                self.raw.append("")
            if a.get("style"):
                self.styles.append(str(a["style"]))
            if tag in ("input", "textarea") and a.get("type") not in ("hidden", "checkbox", "radio", "range", "color", "file"):
                self.loose += [" ".join(str(a[k]).split()) for k in ("value", "placeholder") if (a.get(k) or "").strip()]
            if "data-composition-id" in a and not self.root:
                self.root = a
            if "data-says" in a:
                self.lines.append("")
            if tag == "audio" and "data-says-aloud" in a:
                self.voice.append(" ".join(str(a["data-says-aloud"] or "").split()))
            elif tag == "audio" and "/vo/" in "/" + str(a.get("src") or ""):
                self.unrecorded.append(str(a.get("src")))
            if tag not in ("img", "br", "meta", "link", "source", "input", "path", "polyline", "rect", "circle", "line"):
                self.stack.append((tag, "data-says" in a, set((a.get("class") or "").split())))

        def handle_endtag(self, tag):
            if tag in ("script", "style", "title"):
                self.skip -= 1
                self.raw = None
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    break

        def handle_data(self, data):
            if self.raw is not None:
                self.raw[-1] += data
            text = " ".join(data.split())
            if self.skip or not text:
                return
            if any(says for _, says, _ in self.stack):
                self.lines[-1] = f"{self.lines[-1]} {text}".strip()
                return
            classes = self.stack[-1][2] if self.stack else set()
            if "tagline" in classes:
                self.tag = text
            elif "link" in classes:
                self.link = text
            else:
                self.loose.append(text)

    p = Says()
    with open(project, encoding="utf-8") as f:
        p.feed(f.read())
    w, h = (int(float(p.root.get(k) or 0)) for k in ("data-width", "data-height"))
    try:
        seconds = round(float(p.root.get("data-duration")), 1)
    except (TypeError, ValueError):
        seconds = None
    return {"lines": [x for x in p.lines if x], "tag": p.tag, "link": p.link, "loose": p.loose,
            "voice": [x for x in p.voice if x], "unrecorded": p.unrecorded,
            "unread": script_text(p.scripts, p.srcs) + style_text(p.styles),
            "format": "square" if w == h else "wide" if w > h else "tall", "seconds": seconds}


# The parser above reads markup, and a page can show words its markup does not hold: a
# script sets an element's text, a helper is handed a `text:` option, a stylesheet draws a
# `content:` string. Each of those is refused, since nothing has held those words to the
# post. A script may still rearrange the words the markup already has (the usual split of
# a headline into spans reads the element's own text), and may clear an element.
SINK = re.compile(r"\.(?:textContent|innerText|innerHTML|outerHTML|nodeValue)\s*\+?=(?!=)"
                  r"|\b(?:insertAdjacentHTML|insertAdjacentText|createTextNode|fillText|strokeText)\s*\("
                  r"|\bdocument\.write(?:ln)?\s*\("
                  r"|(?P<key>[{,]\s*(?:text|scrambleText)\s*:)")
OWN_TEXT = re.compile(r"\.(?:textContent|innerText|innerHTML)\b")
TEXT_PLUGIN = re.compile(r"\b(?:TextPlugin|ScrambleTextPlugin)\b")
CSS_CONTENT = re.compile(r"(?<![-\w.#])content\s*:\s*([^;}]*)")
CSS_EMPTY = re.compile(r"(?:\"\s*\"|'\s*'|none|normal)(?:\s*!important)?")
IN_PLACE = "the film's words belong in the markup, in a [data-says] element"


def _js_strings(code):
    """(start, end, body) of every string literal of a script, and the script with its
    comments and the insides of its strings blanked, so a search of the code never
    matches prose. A small scanner, not a parser: a template literal runs to its
    closing backtick."""
    spans, masked, i, n = [], list(code), 0, len(code)
    while i < n:
        c = code[i]
        if code[i:i + 2] in ("//", "/*"):
            j = code.find("\n" if code[i + 1] == "/" else "*/", i + 2)
            j = n if j < 0 else j + (0 if code[i + 1] == "/" else 2)
            masked[i:j] = [" " if ch != "\n" else ch for ch in code[i:j]]
            i = j
        elif c in "'\"`":
            j = i + 1
            while j < n and code[j] != c:
                j += 2 if code[j] == "\\" else 1
            spans.append((i, min(j + 1, n), code[i + 1:j]))
            masked[i + 1:j] = [" " if ch != "\n" else ch for ch in code[i + 1:j]]
            i = j + 1
        else:
            i += 1
    return spans, "".join(masked)


def _literal_words(body):
    """The words a string literal would put on screen: markup and `${...}` are not words."""
    text = re.sub(r"\$\{[^}]*\}", " ", body)
    text = re.sub(r"<[^>]*(?:>|$)", " ", re.sub(r"^[^<>]*>", " ", text))
    text = " ".join(html.unescape(text).split())
    return text if tokens(text) else ""


def _value_end(masked, start, key):
    """Where the value written at `start` ends: the statement's `;` or line end, the
    bracket that closes around it, or, for an object key, the next comma."""
    depth, seen, i = 0, False, start
    while i < len(masked):
        c = masked[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth < 0:
                break
        elif depth == 0 and (c == ";" or (key and c == ",")):
            break
        elif depth == 0 and c == "\n" and seen:
            before, after = masked[start:i].rstrip(), masked[i:].lstrip()
            if before[-1:] not in "=+.,(?:&|" and after[:1] not in ".+?:&|,":
                break
        seen = seen or not c.isspace()
        i += 1
    return i


def script_text(scripts, srcs=()):
    """What stops a film because of what its scripts could write on screen, one line each."""
    problems = []
    if any(TEXT_PLUGIN.search(src) for src in srcs):
        problems.append(f"the GSAP text plugins write text into the page; {IN_PLACE}")
    for code in scripts:
        spans, masked = _js_strings(code)
        if TEXT_PLUGIN.search(masked):
            problems.append(f"the GSAP text plugins write text into the page; {IN_PLACE}")
        for m in SINK.finditer(masked):
            end = _value_end(masked, m.end(), bool(m.group("key")))
            words = [w for s, e, body in spans if m.end() <= s < end for w in [_literal_words(body)] if w]
            for w in words:
                problems.append(f"a script writes text into the page: {w!r}; {IN_PLACE}")
            value = masked[m.end():end]
            if not words and not OWN_TEXT.search(value) and re.search(r"[A-Za-z_$]", value):
                shown = " ".join(code[max(code.rfind("\n", 0, m.start()) + 1, m.start() - 40):end].split())[:90]
                problems.append(f"a script sets text from a value the check cannot read: `{shown}`; {IN_PLACE}")
    return problems


def style_text(styles):
    """What stops a film because of what its stylesheets could draw on screen, one line each."""
    problems = []
    for css in styles:
        for m in CSS_CONTENT.finditer(re.sub(r"/\*.*?\*/", " ", css, flags=re.S)):
            value = m.group(1).strip()
            if value and not CSS_EMPTY.fullmatch(value):
                problems.append(f"a stylesheet draws text on screen (content: {value[:60]}); {IN_PLACE}")
    return problems


def check_film(item, film):
    """What stops this film from being the post's video, one line each; empty means it may."""
    problems = _gate_problems(item)
    if not film["lines"]:
        problems.append("the film says nothing in a [data-says] element")
    for line in film["lines"]:
        if not lifted(line, item):
            problems.append(f"not word for word in the gated post: {line!r}")
    for text in film["loose"]:
        problems.append(f"visible text outside a [data-says] element: {text!r}")
    for line in film.get("voice") or []:
        if not lifted(line, item):
            problems.append(f"the voice says what the gated post does not, word for word: {line!r}")
    for src in film.get("unrecorded") or []:
        problems.append(f"a voice line without its words: {src} needs data-says-aloud=\"<the line, from the post>\"")
    problems += film.get("unread") or []
    theme, cta = str(item.get("theme") or ""), str(item.get("cta") or "")
    if film["tag"] is not None and film["tag"].lower() != theme.lower():
        problems.append(f"the end card's tag is the post's theme, {theme or '(none recorded)'}")
    if film["link"] is not None and (not cta or _bare_url(film["link"]) != domain(cta)):
        problems.append(f"the end card's link shows only the main domain of the post's CTA, "
                        f"{domain(cta) if cta else '(no CTA recorded)'}, never the full URL")
    return problems + _text_checks(item, film["lines"] + (film.get("voice") or []) + [film["tag"] or "", film["link"] or ""])


def film_poster(item_id):
    return os.path.join(os.path.dirname(board_path(item_id)), f"{item_id}-film-poster.png")


def register_film(item, at=2.0):
    """Check a film's words against the post (before its render as after it) and, once it
    is rendered and passes, write its poster frame beside the post's storyboard
    (gitignored, rebuilt from the final). Returns (film, final, problems)."""
    project, final = film_paths(item["id"])
    if not project:
        return None, final, [f"no film for {item['id']}: make one with /motion:video as videos/projects/{item['id']}, "
                             f"rendered to videos/finals/{item['id']}-v<N>.mp4"]
    film = read_film(project)
    problems = check_film(item, film)
    ffmpeg = shutil.which("ffmpeg")
    if not problems and final and ffmpeg:
        os.makedirs(os.path.dirname(film_poster(item["id"])), exist_ok=True)
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", str(at), "-i", final, "-frames:v", "1",
                        film_poster(item["id"])], check=True)
    return film, final, problems


# ------------------------------------------------------------------ the brand kit (the Motion plugin)
#
# The Motion plugin stops without `brand/motion-kit/Motion.md`. The look it needs is already
# in the brand genome, which every other visual reads, so the kit is written from it rather
# than gathered again in an interview. The voice stays in voice.md (memory is the single
# source), and the two sections the plugin treats as binding carry this repository's rule.

KIT = os.path.join(repo.REPO, "brand", "motion-kit")
KIT_BODY = """
# {name} motion kit

Written by `engine motion kit --write` from the brand
genome, so a film looks like the story deck, the control page and the motion cards. It is
yours to edit from here on: the command never overwrites it.

## Assets

- Colours and type: the frontmatter above, from `.atelier/memory/brand-genome.json`.
  Corner radius {radius} px; gradients: {gradients}.
- Logo: {logo}
- Fonts: none copied yet. Add the family's files and their licence under `fonts/` (the
  plugin's `fonts.mjs list` and `add`) before the first render.

## Voice

The voice is `.atelier/memory/voice.md`, with `instincts.md` and `reviews.md` beside it.
It is not copied here: memory is the single source. A film adds no words of its own, so
the voice it carries is the gated post's.

## Facts and claims

- Every word on screen and every word spoken is lifted word for word from one gated
  post. `engine motion brief <id>` prints the sentences
  a film of that post may use; a line is one of them, or a contiguous run of words from
  one of them, never two stitched together.
- Nothing comes from a website, a deck, memory or the model: no fact, number, name, date
  or claim the post does not carry, and no status word the post does not use.
- Not allowed: a film of a post the gate blocked or has not read; any party on the
  stealth list.
- `engine motion film <id>` checks all of this before
  the render and again after it. Fix the page, never the post.

## On screen

- Language: the post's.
- The project is named exactly the post's id: `videos/projects/<id>/`, rendered to
  `videos/finals/<id>-v<N>.mp4`.
- Every visible string sits in an element that carries `data-says`. The end card may add
  the post's theme hashtag in an element of class `tagline` and the main domain of its
  link in one of class `link`.
- A voice-over line is an `<audio>` under `assets/vo/` that carries its words in
  `data-says-aloud`.
- Never on screen: a full URL, a handle, or a name, number or date the post does not
  have; text a script writes into the page or a stylesheet draws (`content:`); a `text:`
  option or the GSAP text plugins; a form field with a value; text inside an image.
  Scripts move what the markup holds and write none of it, in the page or in a file it
  loads.
"""


def genome_placeholder(file=None):
    """True while the brand genome is the template's own (its `_source` says Placeholder) or
    cannot be read: a kit written from it would fix a look nobody chose."""
    import genome
    try:
        with open(file or genome.path(), encoding="utf-8") as f:
            return str(json.load(f).get("_source") or "").strip().lower().startswith("placeholder")
    except (OSError, ValueError):
        return True


def kit_files(g=None, slug=None, today=None):
    """{path under brand/motion-kit: text} of the kit the Motion plugin reads, from the genome."""
    import genome
    g = g or genome.load()
    slug = slug or config.brand()["slug"]
    today = today or dt.date.today().isoformat()
    c, t = g["colors"], g["type"]
    q = lambda v: json.dumps(str(v), ensure_ascii=False)  # noqa: E731 - a JSON string is a YAML string
    files = {name: g["logo"][key].strip() + "\n"
             for key, name in (("on_light", "logo/logo.svg"), ("on_dark", "logo/logo-on-dark.svg")) if g["logo"].get(key)}
    light, dark = "logo/logo.svg" in files, "logo/logo-on-dark.svg" in files
    front = ["---", f"name: {q(g['name'])}", f"kit: {slug}", "source: >-",
             f"  .atelier/memory/brand-genome.json, read by motion.py kit on {today}; the voice is",
             "  .atelier/memory/voice.md and is not copied here.",
             "colors:",
             f"  bg: {q(c['surface'])}          # genome surface",
             f"  surface: {q(c['paper'])}     # genome paper",
             f"  text: {q(c['ink'])}        # genome ink",
             f"  text-muted: {q(c['muted'])}  # genome muted",
             f"  primary: {q(c['primary'])}     # genome primary",
             f"  accent: {q(c['accent'])}      # genome accent",
             "typography:",
             "  display:", f"    family: {q(t['family'])}", f"    weight: {int(t['display_weight'])}          # genome type.display_weight",
             "  body:", f"    family: {q(t['family'])}", f"    weight: {int(t['body_weight'])}          # genome type.body_weight",
             "  # mono and each licence: not recorded in the genome; leave unset until the font files are added"]
    if light or dark:
        first = "logo/logo.svg" if light else "logo/logo-on-dark.svg"
        front += ["logo:", f"  primary: {first}"]
        front += ["  on-light: logo/logo.svg"] if light else []
        front += ["  on-dark: logo/logo-on-dark.svg"] if dark else []
        front += ["  # size and clear space: not recorded; keep the whole mark visible and never recolour or redraw it"]
        logo = "the genome's own (`logo/`), drawn as it is."
    else:
        front += ["# logo: none in the genome (logo.on_light, logo.on_dark); the brand's name is set in type, never a drawn mark"]
        logo = "none recorded in the genome. The brand's name is set in type; no mark is drawn or invented."
    front += ["# voice: .atelier/memory/voice.md (see below); no descriptors are copied into this file", "---"]
    files["Motion.md"] = "\n".join(front) + "\n" + KIT_BODY.format(name=g["name"], radius=g["shape"]["radius"],
                                                            gradients=g["shape"].get("gradients", "none"), logo=logo)
    return files


def write_kit(root=None, genome_file=None, **kw):
    """Write the brand kit where there is none; returns the paths written. Refuses an existing
    kit (never overwritten) and a genome that is still the template's placeholder."""
    root = root or KIT
    if os.path.exists(os.path.join(root, "Motion.md")):
        raise MotionError(f"the brand kit exists at {os.path.relpath(root, repo.REPO)}; it is never overwritten "
                          "(edit it by hand or with /motion:brand-kit)")
    if genome_placeholder(genome_file):
        raise MotionError("the brand genome (.atelier/memory/brand-genome.json) is still the template's placeholder: "
                          "set the brand's colours, typeface and logo there and replace its `_source` line, then run this again")
    written = []
    for name, text in sorted(kit_files(**kw).items()):
        path = os.path.join(root, name)
        if os.path.exists(path):
            continue  # a logo someone already placed is theirs
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        written.append(path)
    return written


def load_board(item_id, path=None):
    path = path or board_path(item_id)
    if not os.path.exists(path):
        raise MotionError(f"no storyboard at {os.path.relpath(path, repo.REPO)}; write one (see `motion.py brief {item_id}`)")
    with open(path, encoding="utf-8") as f:
        try:
            return json.load(f)
        except ValueError as e:
            raise MotionError(f"{os.path.relpath(path, repo.REPO)} is not JSON: {e}")


def load_item(item_id):
    item = gate_lint.items_by_id().get(item_id)
    if not item:
        raise MotionError(f"no post {item_id} in the calendar notes or the queue")
    return item


# ------------------------------------------------------------------ the timeline


def ease_out(t):
    return 1 - (1 - t) ** 3


def ease_in(t):
    return t ** 3


def timeline(board):
    """Per beat (start, shown, leaving, end) in ms, and the clip's length. The
    last beat never leaves: it holds to the final frame."""
    beats, t, out = board["beats"], 0, []
    for i, beat in enumerate(beats):
        hold = beat.get("hold_ms", DEFAULT_HOLD_MS)
        start, shown = t, t + ENTER_MS
        leaving = shown + hold
        end = leaving if i == len(beats) - 1 else leaving + EXIT_MS
        out.append((start, shown, leaving, end))
        t = end
    return out, t


def pose(ms, span):
    """(opacity, vertical offset in px at scale 1) of a beat at `ms`, or None off screen."""
    start, shown, leaving, end = span
    if ms < start or (ms >= end and end != leaving):
        return None
    if ms < shown:
        p = ease_out((ms - start) / ENTER_MS)
        return p, (1 - p) * RISE_PX
    if ms < leaving or end == leaving:
        return 1.0, 0.0
    return 1 - ease_in((ms - leaving) / EXIT_MS), 0.0


# ------------------------------------------------------------------ drawing


def _imaging():
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401
    except ImportError as e:
        raise MotionError("rendering needs Pillow: python3 -m pip install pillow") from e
    return Image, ImageDraw, ImageFont


def _font(ImageFont, size):
    path = config.cfg("motion.font", "") or next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _wrap(draw, text, font, width):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and draw.textlength(trial, font=font) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + ([line] if line else [])


def _brand():
    import genome
    return genome.load()["colors"]


def _rgb(value, default):
    value = str(value or default).lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def layers(board, fmt, scale):
    """One transparent layer per beat, drawn once and reused on every frame."""
    Image, ImageDraw, ImageFont = _imaging()
    w, h = (round(v * scale) for v in FORMATS[fmt])
    ink = _rgb(config.cfg("motion.text", "") or _brand()["on_primary"], "F4F1EA")
    accent = _rgb(config.cfg("motion.accent", "") or _brand()["accent"], "C9A227")
    base = min(w, h)
    sizes = {"line": round(base * 0.065), "tag": round(base * 0.06), "cta": round(base * 0.048)}
    out = []
    for beat in board["beats"]:
        role = beat.get("role", "line")
        font = _font(ImageFont, max(sizes[role], 8))
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        text = beat["text"] if role != "cta" else domain(beat["text"])
        rows = _wrap(draw, text, font, w * 0.8)
        lh = round(font.size * 1.25)
        y = (h - lh * len(rows)) / 2
        for row in rows:
            draw.text(((w - draw.textlength(row, font=font)) / 2, y), row, font=font,
                      fill=(accent if role == "tag" else ink) + (255,))
            y += lh
        out.append(layer)
    return out


def frame(ms, spans, total, beat_layers, size, scale, colours, mark):
    Image, ImageDraw, _ = _imaging()
    bg, accent = colours
    img = Image.new("RGBA", size, bg + (255,))
    for span, layer in zip(spans, beat_layers):
        p = pose(ms, span)
        if p is None:
            continue
        opacity, rise = p
        lay = layer
        if opacity < 1:
            lay = layer.copy()
            lay.putalpha(layer.getchannel("A").point(lambda a, o=opacity: round(a * o)))
        img.alpha_composite(lay, (0, round(rise * scale)))
    if mark is not None:
        img.alpha_composite(mark)
    draw = ImageDraw.Draw(img)
    bar = max(2, round(6 * scale))
    draw.rectangle([0, size[1] - bar, round(size[0] * min(ms / total, 1)), size[1]], fill=accent + (160,))
    return img.convert("RGB")


def _mark(item, size, scale):
    """The stream's name, small and quiet, bottom left: who is speaking."""
    Image, ImageDraw, ImageFont = _imaging()
    name = str(item.get("stream") or "")
    if not name:
        return None
    mark = Image.new("RGBA", size, (0, 0, 0, 0))
    font = _font(ImageFont, max(round(min(size) * 0.028), 8))
    ink = _rgb(config.cfg("motion.text", "") or _brand()["on_primary"], "F4F1EA")
    ImageDraw.Draw(mark).text((round(size[0] * 0.06), round(size[1] * 0.9)), name, font=font, fill=ink + (140,))
    return mark


def render(item, board, out_dir, fmt=None, scale=1.0, fps=FPS, gif_fps=GIF_FPS):
    """Write the poster, the GIF and (with ffmpeg) the MP4; return their paths."""
    fmt = fmt or board.get("format", "square")
    Image, _, _ = _imaging()
    spans, total = timeline(board)
    size = tuple(round(v * scale) for v in FORMATS[fmt])
    colours = (_rgb(config.cfg("motion.background", "") or _brand()["primary"], "0E1116"),
               _rgb(config.cfg("motion.accent", "") or _brand()["accent"], "C9A227"))
    beat_layers, mark = layers(board, fmt, scale), _mark(item, size, scale)
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.join(out_dir, f"{item['id']}-{fmt}")  # the name _stem() and card() read back
    n_frames = math.ceil(total / 1000 * fps) + 1
    times = [min(round(i * 1000 / fps), total) for i in range(n_frames)]
    out = {"poster": stem + "-poster.png"}
    frame(spans[0][1], spans, total, beat_layers, size, scale, colours, mark).save(out["poster"])
    step = max(1, round(fps / gif_fps))
    gif = [frame(ms, spans, total, beat_layers, size, scale, colours, mark) for ms in times[::step]]
    gif = [f.resize((max(1, round(f.width * GIF_SCALE)), max(1, round(f.height * GIF_SCALE)))) for f in gif]
    out["gif"] = stem + ".gif"
    gif[0].save(out["gif"], save_all=True, append_images=gif[1:], duration=round(1000 * step / fps), loop=0, optimize=True)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        with tempfile.TemporaryDirectory() as tmp:
            for i, ms in enumerate(times):
                frame(ms, spans, total, beat_layers, size, scale, colours, mark).save(os.path.join(tmp, f"f{i:05d}.png"))
            out["mp4"] = stem + ".mp4"
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", os.path.join(tmp, "f%05d.png"),
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                            "-movflags", "+faststart", out["mp4"]], check=True)
    return out, total, n_frames


# ------------------------------------------------------------------ the cycle


def _stem(item_id, fmt):
    return os.path.join(os.path.dirname(board_path(item_id)), f"{item_id}-{fmt}")


def render_files(item_id, fmt):
    """The files a rendered card leaves beside its storyboard on this machine."""
    stem = _stem(item_id, fmt)
    files = [stem + "-poster.png", stem + ".gif"]
    return files + ([stem + ".mp4"] if shutil.which("ffmpeg") else [])


def card(item_id, item=None):
    """A post's motion card as every page shows it (the control page, the
    dashboard page, the story): whether it has a storyboard, its format, its
    beats in order (the clip's alt text), its length, the absolute paths of
    the poster, GIF and MP4 rendered on this machine (None for a file not
    here), and `current`: True when the storyboard still passes against
    `item` as it stands now, False when the post moved past it (the clip then
    says something the post no longer does and must not be attached), None
    when no item was given or the check could not run. Ready to attach means
    a video and `current` True."""
    out = {"storyboard": False, "format": None, "beats": [], "seconds": None, "voice": [],
           "poster": None, "gif": None, "video": None, "current": None, "source": None}
    project, final = film_paths(item_id)
    if final:
        # A film made with the Motion plugin from the brand kit: the post's video wherever one exists.
        out.update(storyboard=True, source="film", video=final, current=False if not project else None)
        poster = film_poster(item_id)
        out["poster"] = poster if os.path.isfile(poster) else None
        if project:
            film = read_film(project)
            out.update(format=film["format"], seconds=film["seconds"], voice=film["voice"],
                       beats=film["lines"] + [x for x in (film["tag"], film["link"]) if x])
            if item is not None:
                try:
                    out["current"] = not check_film(item, film)
                except Exception:  # noqa: BLE001 - unconfirmed, not ready
                    out["current"] = None
        return out
    out["source"] = "card"
    try:
        board = load_board(item_id)
    except MotionError:
        return out
    out["storyboard"] = True
    if not isinstance(board, dict) or not isinstance(board.get("beats"), list):
        out["current"] = False
        return out
    fmt = board.get("format", "square")
    fmt = fmt if fmt in FORMATS else "square"
    beats = [b for b in board["beats"] if isinstance(b, dict)]
    out.update(format=fmt, beats=[str(b.get("text") or "") for b in beats])
    try:
        out["seconds"] = round(timeline({"beats": beats})[1] / 1000, 1)
    except (TypeError, ValueError):
        pass
    stem = _stem(item_id, fmt)
    for key, path in (("poster", stem + "-poster.png"), ("gif", stem + ".gif"), ("video", stem + ".mp4")):
        out[key] = path if os.path.isfile(path) else None
    if item is not None:
        try:
            out["current"] = not check_board(item, board)
        except Exception:  # noqa: BLE001 - a check that cannot run leaves the card unconfirmed, not ready
            out["current"] = None
    return out


#: which of a card's files a channel takes: X a video (else the GIF), a LinkedIn page the poster,
#: because the one LinkedIn video tool posts as a member and never as the page
MEDIA_PREFERENCE = {"x": ("video", "gif"), "linkedin": ("poster",)}
MEDIA_KIND = {"video": "video", "gif": "gif", "poster": "image"}


def media_for(item, channel_key):
    """The file a post goes out with on a channel, as `{path, sha256, kind, source}`, or None.

    Only a card or film that is `current`: its words are still the post's. `path` is relative to
    the repository; `sha256` is the file's hash now, which the approval records and
    `channels.send()` checks again at the send, so what goes out is what a person saw."""
    import channels
    c = card(item["id"], item)
    if c.get("current") is not True:
        return None
    for which in MEDIA_PREFERENCE.get(channel_key, ()):
        path = c.get(which)
        if path and os.path.isfile(path) and channels.media_path(path):
            return {"path": os.path.relpath(path, repo.REPO), "sha256": channels.file_sha256(path),
                    "kind": MEDIA_KIND[which], "source": c.get("source") or "card"}
    return None


def generate_signoff():
    """The owner's recorded cost sign-off for `motion:generate` (`motion.generate_signoff`), or ''.

    The same shape as the X price sign-offs: a dated note in words, scoped to what was accepted.
    The PreToolUse hook on the Skill tool (hooks/guard_skills.py) reads the same key and
    refuses the paid skill without it."""
    value = str(config.cfg("motion.generate_signoff", "") or "").strip()
    return "" if value.lower() in ("", "0", "false", "no", "off", "none") else value


def _priority(item):
    return (0 if item.get("alpha_status") == "approved" else 1,
            str((item.get("slot") or {}).get("date") or "9999"), item.get("id", ""))


def pending(items=None, limit=None, today=None):
    """What the cycle owes motion, as (id, action, reason): `storyboard` for a
    post that needs the motion-designer (no card, or a card the post has moved
    past), at most `limit` of them; `render` for a card whose storyboard still
    passes and has no files here, which needs no model and is never capped.

    Only blog posts the gate let through (pass or pass-with-edits) that are
    still in play (proposed or approved, not Published) and whose slot date is
    today or later, or not set. A post with a film (the Motion plugin, from the
    brand kit) owes nothing while the film's words still match it; when they do
    not, it is listed as `film`, for a person to remake with /motion:video
    (never capped, never handed to the motion-designer). Empty when
    `params.cycle.motion` is false."""
    if not config.cfg("cycle.motion", True):
        return []
    limit = int(config.cfg("cycle.motion_per_cycle", 3) if limit is None else limit)
    items = gate_lint.items_by_id() if items is None else items
    today = today or dt.date.today().isoformat()
    owed, renders, films = [], [], []
    for item in sorted(items.values(), key=_priority):
        if (item.get("slot") or {}).get("platform", "Blog") != "Blog":
            continue
        if str(item.get("status") or "") == "Published" or item.get("alpha_status") not in ("proposed", "approved"):
            continue
        if (item.get("gate") or {}).get("verdict") not in ("pass", "pass-with-edits"):
            continue
        if str((item.get("slot") or {}).get("date") or "9999") < today:
            continue
        item_id = item["id"]
        project, final = film_paths(item_id)
        if final:
            # A film from the brand kit stands in for the card; it is made by a person
            # with /motion:video, so a film the post moved past is reported, not redone here.
            problems = check_film(item, read_film(project)) if project else ["its project is missing"]
            if problems:
                films.append((item_id, "film", "the film no longer matches the post: " + problems[0]))
            continue
        if not os.path.exists(board_path(item_id)):
            owed.append((item_id, "storyboard", "no card yet"))
            continue
        try:
            board = load_board(item_id)
        except MotionError as e:
            owed.append((item_id, "storyboard", str(e)))
            continue
        problems = check_board(item, board)
        if problems:
            owed.append((item_id, "storyboard", "the card no longer matches the post: " + problems[0]))
        elif not all(os.path.exists(f) for f in render_files(item_id, board.get("format", "square"))):
            renders.append((item_id, "render", "the storyboard passes; no files on this machine"))
    return owed[:max(limit, 0)] + renders + films


# ------------------------------------------------------------------ the command line


def brief(item):
    lines = [f"post     {item['id']}  ({item.get('stream', '')})",
             f"gate     {(item.get('gate') or {}).get('verdict') or 'not read yet'}",
             f"theme    {item.get('theme') or '(none)'}",
             f"cta      {item.get('cta') or '(none)'}" + (f"  (on screen: {domain(item['cta'])} only)" if item.get("cta") else ""),
             f"write    {os.path.relpath(board_path(item['id']), repo.REPO)}",
             "", "lines you may lift (word for word, or a contiguous run of words from one of them):"]
    n = 0
    for field in MATERIAL:
        for sentence in sentences(item.get(field)):
            if not sentence.startswith(("http", "#")):
                n += 1
                lines.append(f"  {n:>2}. [{field}] {sentence}")
    lines += ["", f"limits   {MIN_BEATS}-{MAX_BEATS} beats; a line at most {MAX_WORDS} words; hold_ms "
              f"{MIN_HOLD_MS}-{MAX_HOLD_MS}; at most {MAX_TOTAL_MS // 1000} s in all; beat 1 is a line;",
              "         the tag is the theme; the link is the CTA's main domain only and comes last; format square or wide",
              "", "shape    " + json.dumps({"format": "square", "beats": [
                  {"role": "line", "text": "<the hook, lifted>", "hold_ms": 2000},
                  {"role": "line", "text": "<one argument line, lifted>", "hold_ms": 2200},
                  {"role": "tag", "text": item.get("theme") or "#Theme", "hold_ms": 1000},
                  {"role": "cta", "text": domain(item["cta"]) if item.get("cta") else "example.com", "hold_ms": 1600}]})]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="A motion card for one gated post.")
    ap.add_argument("command", choices=("brief", "check", "render", "pending", "film", "kit", "generate-signoff"))
    ap.add_argument("id", nargs="?", help="the post's id (Q-...); not for pending or kit")
    ap.add_argument("--write", action="store_true", help="kit: write brand/motion-kit/ (only where there is none)")
    ap.add_argument("--format", choices=tuple(FORMATS), help="square (1080x1080) or wide (1200x675); default: the storyboard's")
    ap.add_argument("--storyboard", help="read this storyboard instead of Content/Motion/<id>/storyboard.json")
    ap.add_argument("--dry-run", action="store_true", help="render: print the timeline and the files, write nothing")
    ap.add_argument("--render", action="store_true", help="pending: render the cards that need no storyboard")
    ap.add_argument("--max", type=int, help="pending: at most this many storyboards (default params.cycle.motion_per_cycle)")
    ap.add_argument("--json", action="store_true", help="pending: print the list as JSON")
    args = ap.parse_args(argv)
    if args.command == "generate-signoff":
        note = generate_signoff()
        if note:
            print(f"motion:generate is open on this machine. Sign-off on record: {note}")
            return 0
        print("motion:generate is closed: it makes paid calls and no cost sign-off is recorded.\n"
              "A person records one, dated and scoped:\n"
              "  engine config set motion.generate_signoff "
              "\"<date>: <role>, <what and how much>\"")
        return 1
    if args.command == "pending":
        return main_pending(args)
    if args.command == "kit":
        return main_kit(args)
    if not args.id:
        ap.error(f"{args.command} needs a post id")
    try:
        item = load_item(args.id)
        if args.command == "brief":
            print(brief(item))
            return 0
        if args.command == "film":
            film, final, problems = register_film(item)
            if problems:
                print(f"motion: {args.id}: the film is not the post's video yet, {len(problems)} to fix")
                for p in problems:
                    print(f"  - {p}")
                return 1
            where = os.path.relpath(final, repo.REPO) if final else "not rendered yet: render it, then run this again"
            print(f"motion: {args.id}: film words ok, {film['format']}, {film['seconds']} s, {where}")
            for line in film["lines"] + [film["tag"] or "", film["link"] or ""]:
                if line:
                    print(f"  says   {line}")
            for line in film["voice"]:
                print(f"  voice  {line}")
            if os.path.isfile(film_poster(args.id)):
                print(f"  poster {os.path.relpath(film_poster(args.id), repo.REPO)}")
            return 0
        board = load_board(args.id, args.storyboard)
        problems = check_board(item, board)
        if problems:
            print(f"motion: {args.id}: {len(problems)} to fix before it renders")
            for p in problems:
                print(f"  - {p}")
            return 1
        if args.command == "check":
            spans, total = timeline(board)
            print(f"motion: {args.id}: ok, {len(spans)} beats, {total / 1000:.1f} s")
            return 0
        fmt = args.format or board.get("format", "square")
        spans, total = timeline(board)
        out_dir = os.path.dirname(args.storyboard or board_path(args.id))
        if args.dry_run:
            for beat, (start, shown, leaving, end) in zip(board["beats"], spans):
                print(f"  {start / 1000:5.2f}-{end / 1000:5.2f} s  {beat.get('role', 'line'):<4}  {beat['text']}")
            print(f"motion: {args.id}: would write {fmt} poster, GIF"
                  f"{' and MP4' if shutil.which('ffmpeg') else ' (no ffmpeg: no MP4)'} to "
                  f"{os.path.relpath(out_dir, repo.REPO)}, {total / 1000:.1f} s")
            return 0
        out, total, n = render(item, board, out_dir, fmt)
        print(f"motion: {args.id}: {fmt}, {total / 1000:.1f} s, {n} frames")
        for kind, path in out.items():
            print(f"  {kind:<6} {os.path.relpath(path, repo.REPO)}")
        return 0
    except MotionError as e:
        print(f"motion: {e}", file=sys.stderr)
        return 1


def main_kit(args):
    rel = os.path.relpath(os.path.join(KIT, "Motion.md"), repo.REPO)
    if os.path.exists(os.path.join(KIT, "Motion.md")):
        print(f"motion: the brand kit is at {rel}; nothing to write (it is never overwritten: "
              "edit it by hand or with /motion:brand-kit)")
        return 0
    if not args.write:
        print(kit_files()["Motion.md"], end="")
        print(f"motion: no brand kit yet; the above is what `motion.py kit --write` puts at {rel}", file=sys.stderr)
        if genome_placeholder():
            print("motion: the brand genome is still the template's placeholder, so --write will refuse: "
                  "set the brand's look in .atelier/memory/brand-genome.json first", file=sys.stderr)
        return 0
    try:
        written = write_kit()
    except MotionError as e:
        print(f"motion: {e}", file=sys.stderr)
        return 1
    for path in written:
        print(f"  wrote  {os.path.relpath(path, repo.REPO)}")
    print("motion: the brand kit is written from the genome. Add the font files under brand/motion-kit/fonts/ "
          "and read it once; /motion:brand-kit refines it")
    return 0


def main_pending(args):
    if not config.cfg("cycle.motion", True):
        print("motion: off (params.cycle.motion is false); /motion still works on request")
        return 0
    try:
        owed = pending(limit=args.max)
    except MotionError as e:
        print(f"motion: {e}", file=sys.stderr)
        return 1
    done = []
    if args.render:
        items = gate_lint.items_by_id()
        for item_id, action, _ in [o for o in owed if o[1] == "render"]:
            try:
                board = load_board(item_id)
                out, total, _n = render(items[item_id], board, os.path.dirname(board_path(item_id)))
                done.append((item_id, "rendered", ", ".join(os.path.relpath(p, repo.REPO) for p in out.values())))
            except Exception as e:  # noqa: BLE001 - one card failing never stops the cycle
                done.append((item_id, "render failed", str(e)))
        owed = [o for o in owed if o[1] != "render"]
    rows = owed + done
    if args.json:
        print(json.dumps([{"id": i, "action": a, "reason": r} for i, a, r in rows], indent=1))
        return 0
    if not rows:
        print("motion: nothing owed; every blog post the gate let through has its card")
    for item_id, action, reason in rows:
        print(f"{action:<13} {item_id}  {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
