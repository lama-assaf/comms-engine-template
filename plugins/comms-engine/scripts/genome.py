#!/usr/bin/env python3
"""
genome.py - the brand genome: the brand's look, read from one file.

Why: the engine now makes several visuals (the story deck, the control page,
the motion cards). They must look like the brand every time and the same as
each other, so none of them carries its own colours. They all read
`.atelier/memory/brand-genome.json` (a stream's own under
`.atelier/memory/streams/<slug>/brand-genome.json`) through `load()`, which
fills anything the file leaves out from neutral defaults and checks every
colour is a hex value, so a typo never reaches a page.

The file holds: `name`; `colors` (primary, accent, ink, on_primary, surface,
paper, tint, line, muted); `type` (family, stack, display_weight,
body_weight); `shape` (radius in px for what the brand publishes, ui_radius
for the control page and the deck, gradients); `logo` (`on_light`,
`on_dark`: inline SVG, or empty for a text mark); `voice` (where the words
live); `palette`, the colours the control page and the story deck paint
with: `colors`, a list of `{name, hex}` in a fixed order that pages, themes
and the deck's beats take by position (so a colour follows its page or
theme); `roles`, what critical, warning, good, action and info look like
(a colour's name or a hex); and `style`, `pastel` (a soft fill of each
colour with a deep shade of it for the text) or `solid`. The neutrals
(white, the greys, the ink) and `primary`, the strong anchor, stay those in
`colors`. Take the rest from the brand's own website or brand guide.

  engine genome            # the genome as the visuals see it
  engine genome --css      # the same, as CSS variables
"""
import argparse
import copy
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memory  # noqa: E402

DEFAULT = {
    "name": "",
    "colors": {"primary": "#1f2a44", "accent": "#2a5bd7", "ink": "#0b0b0b", "on_primary": "#ffffff",
               "surface": "#ffffff", "paper": "#f7f7f5", "tint": "#e8eefc", "line": "#e1e0d9", "muted": "#77776f"},
    "type": {"family": "Inter", "stack": "Inter, -apple-system, BlinkMacSystemFont, \"Segoe UI\", system-ui, sans-serif",
             "display_weight": 800, "body_weight": 400},
    "shape": {"radius": 8, "ui_radius": 18, "gradients": "none"},
    "logo": {"on_light": "", "on_dark": ""},
    "voice": ".atelier/memory/voice.md",
    "palette": {
        "colors": [{"name": "Strawberry Red", "hex": "#f94144"}, {"name": "Atomic Tangerine", "hex": "#f3722c"},
                   {"name": "Carrot Orange", "hex": "#f8961e"}, {"name": "Coral Glow", "hex": "#f9844a"},
                   {"name": "Tuscan Sun", "hex": "#f9c74f"}, {"name": "Willow Green", "hex": "#90be6d"},
                   {"name": "Seagrass", "hex": "#43aa8b"}, {"name": "Dark Cyan", "hex": "#4d908e"},
                   {"name": "Blue Slate", "hex": "#577590"}, {"name": "Cerulean", "hex": "#277da1"}],
        "roles": {"critical": "Strawberry Red", "warning": "Tuscan Sun", "good": "Willow Green",
                  "action": "Cerulean", "info": "Blue Slate"},
        "style": "pastel",
    },
}
HEX = re.compile(r"#[0-9a-fA-F]{6}")
PALETTE_MAX = 16


def path(stream=None):
    base = memory.paths(stream)["dir"] if stream not in (None, memory.DEFAULT_STREAM) else memory.MEMORY
    return os.path.join(base, "brand-genome.json")


def load(stream=None, file=None):
    """The genome with defaults filled in; a bad colour or a missing file falls back, never fails."""
    g = copy.deepcopy(DEFAULT)
    try:
        with open(file or path(stream), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    for key in ("name", "voice"):
        if isinstance(data.get(key), str) and data[key]:
            g[key] = data[key]
    for section in ("colors", "type", "shape", "logo"):
        for k, v in (data.get(section) or {}).items():
            if section == "colors" and not (isinstance(v, str) and HEX.fullmatch(v)):
                continue
            if section == "logo" and not (isinstance(v, str) and (not v or v.lstrip().startswith("<svg"))
                                          and not re.search(r"<script|\son[a-z]+\s*=|javascript:|<foreignObject", v, re.I)):
                continue  # a logo is drawn into pages as is: an SVG, and nothing that runs
            g[section][k] = v
    g["palette"] = _palette(data.get("palette"))
    for key, most in (("radius", 24), ("ui_radius", 32)):
        try:
            g["shape"][key] = max(0, min(int(g["shape"][key]), most))
        except (TypeError, ValueError):
            g["shape"][key] = DEFAULT["shape"][key]
    if not g["name"]:
        g["name"] = getattr(memory, "DEFAULT_STREAM_NAME", None) or str(memory.DEFAULT_STREAM).upper()
    return g


def _palette(data):
    """The file's palette when every colour in it reads, else the default. Each
    role resolves to its colour's hex; an unknown role name falls back to the
    default role's colour, so a page never paints with nothing."""
    out = copy.deepcopy(DEFAULT["palette"])
    if not isinstance(data, dict):
        data = {}
    colors = []
    for c in data.get("colors") or []:
        if isinstance(c, str):
            c = {"name": c, "hex": c}
        if isinstance(c, dict) and isinstance(c.get("hex"), str):
            h = c["hex"] if c["hex"].startswith("#") else "#" + c["hex"]
            if HEX.fullmatch(h):
                colors.append({"name": str(c.get("name") or h)[:40], "hex": h.lower()})
    if colors:
        out["colors"] = colors[:PALETTE_MAX]
    by_name = {c["name"].lower(): c["hex"] for c in out["colors"]}
    default_hex = {c["name"]: c["hex"] for c in DEFAULT["palette"]["colors"]}
    roles = dict(out["roles"], **{k: v for k, v in (data.get("roles") or {}).items() if isinstance(v, str)})
    def resolve(r, n):
        n = str(n).strip()
        h = n if n.startswith("#") else "#" + n
        if HEX.fullmatch(h) and n.lower() not in by_name:
            return h.lower()  # a role may give its colour as a hex
        return by_name.get(n.lower()) or default_hex.get(DEFAULT["palette"]["roles"].get(r, ""), out["colors"][0]["hex"])
    out["roles"] = {r: resolve(r, n) for r, n in roles.items() if r in DEFAULT["palette"]["roles"]}
    out["style"] = data.get("style") if data.get("style") in ("pastel", "solid") else DEFAULT["palette"]["style"]
    return out


def css(g=None):
    """The genome as CSS custom properties, for a page's :root."""
    g = g or load()
    lines = [f"--brand-{k.replace('_', '-')}: {v};" for k, v in g["colors"].items()]
    lines += [f"--brand-font: {g['type']['stack']};", f"--brand-display-weight: {g['type']['display_weight']};",
              f"--brand-radius: {g['shape']['radius']}px;"]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="The brand genome as the visuals see it.")
    ap.add_argument("--stream")
    ap.add_argument("--css", action="store_true")
    args = ap.parse_args(argv)
    g = load(args.stream)
    if args.css:
        print(css(g))
    else:
        shown = dict(g, logo={k: (f"<svg, {len(v)} characters>" if v else "") for k, v in g["logo"].items()})
        print(json.dumps(shown, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
