#!/usr/bin/env python3
"""
brandfile.py - the one writer of brand.json, and of the tables of streams.md it renders.

Why: a new project used to edit cells in three markdown tables of
`.atelier/memory/streams.md` and find its way around engine.json. The setup is
now one small file, `brand.json` at the repository root, that `engine.py init`
and the dashboard's Setup page write. Agents and `memory.py` still read
`streams.md`, so its three tables (registry, guardrails, pair rules) are
rendered from the file by `apply`, and `doctor` fails when the two disagree.
The prose of `streams.md` is never touched: only the rows under each table's
header.

What maps to what, per stream of brand.json:

  registry    name, narrator, owner, objectives, autopilot, channels, memory,
              corpus_status; `corpus root` keeps the cell it has (the path
              itself lives in engine.local.json)
  guardrails  drafts_only, posts_per_day, quiet_hours, blocked_topics,
              hold_for_review
  pair rules  one row per entry of pair_rules (to, rule, basis)

`channels` and `posts_per_day` may be structured (`{"x": "@acme"}`,
`{"x": 2, "blog_per_week": 2}`) or the cell's own text, which is what
`from_streams_md` writes when it imports a registry a person edited by hand:
an import followed by `apply` changes nothing.

  engine apply            # render streams.md from brand.json
  engine apply --check    # exit 1 and the rows that differ; writes nothing
  engine brandfile show          # the rows brand.json renders to
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config  # noqa: E402

REGISTRY_COLUMNS = ("slug", "name", "narrator", "owner", "objectives", "autopilot", "channels", "memory",
                    "corpus root", "corpus status")
GUARDRAIL_COLUMNS = ("slug", "drafts-only channels", "posts per channel per day", "quiet hours", "blocked topics",
                     "hold for review")
PAIR_COLUMNS = ("from", "to", "rule", "basis")
SECTIONS = (("registry", REGISTRY_COLUMNS), ("guardrails", GUARDRAIL_COLUMNS), ("pair rules", PAIR_COLUMNS))
#: What a cell reads when brand.json does not say: a stream that is shut.
DEFAULTS = {
    "narrator": "- (set at onboarding)",
    "owner": "unset",
    "objectives": "intent engagement (saves, quote posts, substantive replies, reposts, link clicks); "
                  "reach: not opted in; north star: set at onboarding",
    "autopilot": "nothing",
    "corpus root": "set by `engine.py setup corpus`",
    "corpus status": "candidate",
    "drafts-only channels": "all",
    "posts per channel per day": "0",
    "quiet hours": "all hours until onboarded",
    "blocked topics": "everything, until this stream's `instincts.md` never-say lines and its "
                      "`handles.private.md` denylist are written",
    "hold for review": "everything",
}
PAIR_PLACEHOLDER = ("none recorded; a stream names no other stream until a row from it to that stream is written here",
                    "plan decision 3")
CHANNEL_NAMES = {"x": "X", "linkedin": "LinkedIn", "telegram": "Telegram", "discord": "Discord", "website": "website"}
#: A dict or list no longer than this is written on one line, so the file stays about forty lines.
INLINE = 140


class Refused(RuntimeError):
    """A setup that cannot be written or rendered; the message names the key or the table."""


# --- brand.json: read and write ------------------------------------------------------------

def path(base=None):
    return config.brand_path(base)


def read(base=None):
    """brand.json as written; `{}` when there is none."""
    return config.read_brand_file(base)


def _dump(value, indent=0):
    """JSON with small objects on one line: a `review` map reads as one row, a stream as a block."""
    flat = json.dumps(value, ensure_ascii=False)
    pad = "  " * indent
    if not isinstance(value, (dict, list)) or not value:
        return flat
    notes = isinstance(value, dict) and any(str(k).startswith("_") for k in value)
    nested = any(isinstance(v, dict) and v for v in (value.values() if isinstance(value, dict) else value))
    if len(flat) + len(pad) <= INLINE and not notes and not (nested and indent < 2):
        return flat
    inner = "  " * (indent + 1)
    if isinstance(value, dict):
        rows = [f"{inner}{json.dumps(k, ensure_ascii=False)}: {_dump(v, indent + 1)}" for k, v in value.items()]
        return "{\n" + ",\n".join(rows) + "\n" + pad + "}"
    rows = [f"{inner}{_dump(v, indent + 1)}" for v in value]
    return "[\n" + ",\n".join(rows) + "\n" + pad + "]"


def dumps(bdoc):
    return _dump(bdoc) + "\n"


def write(bdoc, base=None, target=None):
    """Write brand.json; returns the path when the file changed, None when it already read so."""
    target = target or path(base)
    text = dumps(bdoc)
    if os.path.exists(target):
        with open(target, encoding="utf-8") as f:
            if f.read() == text:
                return None
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, target)
    return target


# --- brand.json -> the cells of streams.md ------------------------------------------------------

def _cell(value, key):
    text = str(value).strip()
    if "|" in text or "\n" in text:
        raise Refused(f"{key}: a table cell cannot hold `|` or a line break; reword it")
    return text


def channels_cell(channels):
    """`{"x": "@acme", "linkedin": ""}` -> `X @acme; LinkedIn (collect)`; text is kept as written."""
    if isinstance(channels, str):
        return channels.strip() or "-"
    if not isinstance(channels, dict) or not channels:
        return "-"
    parts = []
    for key, handle in channels.items():
        name = CHANNEL_NAMES.get(key, key)
        handle = str(handle or "").strip()
        parts.append(f"{name} {handle}" if handle else f"{name} (collect)")
    return "; ".join(parts)


def posts_cell(posts):
    """`{"x": 2, "linkedin": 1, "blog_per_week": 2, "blog_days_apart": 3}` in the form guardrails.py parses."""
    if isinstance(posts, str):
        return posts.strip() or DEFAULTS["posts per channel per day"]
    if not isinstance(posts, dict) or not posts:
        return DEFAULTS["posts per channel per day"]
    parts = []
    if "x" in posts:
        parts.append(f"X {int(posts['x'])}")
    if "linkedin" in posts:
        parts.append(f"LinkedIn {int(posts['linkedin'])}")
    if "blog_per_week" in posts:
        blog = f"Blog {int(posts['blog_per_week'])} per ISO week"
        if posts.get("blog_days_apart"):
            blog += f", at least {int(posts['blog_days_apart'])} days apart"
        parts.append(blog)
    return "; ".join(parts) or DEFAULTS["posts per channel per day"]


def default_memory(slug, root):
    return ".atelier/memory" if slug == root else f".atelier/memory/streams/{slug}"


def stream_cells(slug, row, root, brand_name=None):
    """`(registry cells, guardrail cells)` of one stream, by column name; `corpus root` is left to the file."""
    at = f"streams.{slug}"
    drafts = row.get("drafts_only", DEFAULTS["drafts-only channels"])
    reg = {
        "slug": slug,
        "name": row.get("name") or (brand_name if slug == root and brand_name else slug.capitalize()),
        "narrator": row.get("narrator") or DEFAULTS["narrator"],
        "owner": row.get("owner") or DEFAULTS["owner"],
        "objectives": row.get("objectives") or DEFAULTS["objectives"],
        "autopilot": row.get("autopilot") or DEFAULTS["autopilot"],
        "channels": channels_cell(row.get("channels")),
        "memory": row.get("memory") or default_memory(slug, root),
        "corpus status": row.get("corpus_status") or DEFAULTS["corpus status"],
    }
    guard = {
        "slug": slug,
        "drafts-only channels": ", ".join(drafts) if isinstance(drafts, list) else (drafts or DEFAULTS["drafts-only channels"]),
        "posts per channel per day": posts_cell(row.get("posts_per_day")),
        "quiet hours": row.get("quiet_hours") or DEFAULTS["quiet hours"],
        "blocked topics": row.get("blocked_topics") or DEFAULTS["blocked topics"],
        "hold for review": row.get("hold_for_review") or DEFAULTS["hold for review"],
    }
    return ({k: _cell(v, f"{at}.{k}") for k, v in reg.items()}, {k: _cell(v, f"{at}.{k}") for k, v in guard.items()})


def rows(bdoc, base_doc=None):
    """`{"registry": [..], "guardrails": [..], "pair rules": [..]}`: the rows brand.json renders to, as dicts by column."""
    streams = {s: r for s, r in (bdoc.get("streams") or {}).items() if isinstance(r, dict) and not s.startswith("_")}
    if not streams:
        raise Refused("brand.json has no stream; `engine.py init` writes the brand's own")
    block = config._brand_block(bdoc, base_doc or {})
    root = block["slug"] if block else next(iter(streams))
    out = {"registry": [], "guardrails": [], "pair rules": []}
    for slug, row in streams.items():
        reg, guard = stream_cells(slug, row, root, block["name"] if block else None)
        out["registry"].append(reg)
        out["guardrails"].append(guard)
        for i, p in enumerate(row.get("pair_rules") or []):
            at = f"streams.{slug}.pair_rules[{i}]"
            out["pair rules"].append({"from": slug, "to": _cell(p.get("to", ""), at), "rule": _cell(p.get("rule", ""), at),
                                      "basis": _cell(p.get("basis") or "-", at)})
    if not out["pair rules"]:
        # the shape row: a stream to itself, no rule
        out["pair rules"].append({"from": root, "to": root, "rule": PAIR_PLACEHOLDER[0], "basis": PAIR_PLACEHOLDER[1]})
    return out


# --- the tables of streams.md --------------------------------------------------------------------

def _split(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _tables(text):
    """`{heading: (header line index, first row index, end index, columns)}` for the first table under each `##`."""
    lines = text.splitlines()
    out = {}
    heading = None
    i = 0
    while i < len(lines):
        m = re.match(r"^##\s+(.*?)\s*$", lines[i])
        if m:
            heading = m.group(1).strip().lower()
        elif heading and heading not in out and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
            start = i + 1
            if start < len(lines) and re.fullmatch(r"\|?[\s:|-]+\|?", lines[start].strip() or "x"):
                start += 1
            end = start
            while end < len(lines) and lines[end].strip().startswith("|"):
                end += 1
            out[heading] = (i, start, end, [c.lower() for c in _split(lines[i])])
            i = end
            continue
        i += 1
    return out


def render(text, bdoc, base_doc=None):
    """`text` (streams.md) with the rows of its three tables replaced by what brand.json says.

    A table is rendered in the columns its header has: a column this module
    does not know keeps the cell the stream's row had. A section the file does
    not carry is skipped; the registry is required.
    """
    want = rows(bdoc, base_doc)
    tables = _tables(text)
    if "registry" not in tables:
        raise Refused("streams.md has no table under `## registry`; restore the file's headings")
    lines = text.splitlines()
    for heading, _known in reversed(SECTIONS):
        if heading not in tables:
            continue
        _hdr, start, end, columns = tables[heading]
        key = "from" if heading == "pair rules" else "slug"
        old = {}
        for line in lines[start:end]:
            cells = _split(line)
            if len(cells) == len(columns):
                row = dict(zip(columns, cells))
                old.setdefault(row.get(key, ""), row)
        rendered = []
        for row in want[heading]:
            was = old.get(row[key], {})
            cells = []
            for col in columns:
                if col in row:
                    cells.append(row[col])
                elif heading != "pair rules" and was.get(col):
                    cells.append(was[col])
                else:
                    cells.append(DEFAULTS.get(col, "-"))
            rendered.append("| " + " | ".join(cells) + " |")
        lines[start:end] = rendered
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def differences(text, bdoc, base_doc=None):
    """The table rows that would change, as `- old` / `+ new` lines; empty when streams.md is up to date."""
    new = render(text, bdoc, base_doc)
    if new == text:
        return []
    a, b = text.splitlines(), new.splitlines()
    return [f"- {ln}" for ln in a if ln.startswith("|") and ln not in b] + \
           [f"+ {ln}" for ln in b if ln.startswith("|") and ln not in a]


def apply(streams_md, base=None, check=False):
    """Render streams.md from brand.json. Returns `{"changed": bool, "diff": [...]}`; writes unless `check`.

    Refuses a brand.json that `config.validate` finds a problem in: a setup
    that is wrong is fixed in the file, never rendered around.
    """
    bdoc = read(base)
    if not bdoc:
        raise Refused(f"no {os.path.basename(path(base))}; `engine.py init` writes it")
    problems = config.validate(base)
    if problems:
        raise Refused("brand.json has problems, nothing rendered:\n  " + "\n  ".join(problems))
    if not os.path.exists(streams_md):
        raise Refused(f"{streams_md} is missing; restore it from the template")
    with open(streams_md, encoding="utf-8") as f:
        text = f.read()
    base_doc = config._read_json(config.ENGINE_JSON if base is None else base)
    diff = differences(text, bdoc, base_doc)
    if diff and not check:
        tmp = streams_md + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(render(text, bdoc, base_doc))
        os.replace(tmp, streams_md)
    return {"changed": bool(diff), "diff": diff}


# --- streams.md -> brand.json: the import of a registry kept by hand ------------------------------

def _dash(cell):
    cell = (cell or "").strip()
    return "" if cell in ("", "-", "—") else cell


def from_streams_md(text, brand):
    """A brand.json document from an existing streams.md, cell for cell, so `apply` after it changes nothing.

    `brand` is the brand block in force. The cells are kept as text; only a
    `memory` cell that is the derived default and the self-pair shape row are
    left out.
    """
    tables = _tables(text)
    lines = text.splitlines()

    def read_rows(heading):
        if heading not in tables:
            return []
        _hdr, start, end, columns = tables[heading]
        return [dict(zip(columns, _split(ln))) for ln in lines[start:end] if len(_split(ln)) == len(columns)]

    guard = {r.get("slug"): r for r in read_rows("guardrails")}
    streams = {}
    for r in read_rows("registry"):
        slug = r.get("slug", "")
        row = {}
        for col, key in (("name", "name"), ("narrator", "narrator"), ("owner", "owner"), ("objectives", "objectives"),
                         ("autopilot", "autopilot"), ("channels", "channels"), ("corpus status", "corpus_status")):
            if col in r and (key != "channels" or _dash(r[col])):
                row[key] = r[col]
        if "channels" in r and "channels" not in row:
            row["channels"] = {}
        if r.get("memory") and r["memory"].strip("`") != default_memory(slug, brand["slug"]):
            row["memory"] = r["memory"]
        g = guard.get(slug) or {}
        for col, key in (("drafts-only channels", "drafts_only"), ("posts per channel per day", "posts_per_day"),
                         ("quiet hours", "quiet_hours"), ("blocked topics", "blocked_topics"), ("hold for review", "hold_for_review")):
            if col in g:
                row[key] = g[col]
        row["pair_rules"] = []
        streams[slug] = row
    for p in read_rows("pair rules"):
        src, dst = p.get("from", ""), p.get("to", "")
        if src == dst or src not in streams:
            continue
        rule = {"to": dst, "rule": p.get("rule", "")}
        if _dash(p.get("basis")):
            rule["basis"] = p["basis"]
        streams[src]["pair_rules"].append(rule)
    return {"brand": {"slug": brand["slug"], "name": brand["name"]}, "streams": streams}


def rename(bdoc, old, new):
    """The document with the root stream re-keyed from `old` to `new` (brand blocks): the key, each
    pair rule's `to`, and a stream name that was the old brand's."""
    streams = {}
    for slug, row in (bdoc.get("streams") or {}).items():
        if isinstance(row, dict):
            row = dict(row)
            if slug == old["slug"] and row.get("name", old["name"]) == old["name"]:
                row["name"] = new["name"]
            if isinstance(row.get("pair_rules"), list):
                row["pair_rules"] = [({**p, "to": new["slug"]} if isinstance(p, dict) and p.get("to") == old["slug"] else p)
                                     for p in row["pair_rules"]]
        streams[new["slug"] if slug == old["slug"] else slug] = row
    out = dict(bdoc)
    out["streams"] = streams
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv != ["show"]:
        print(__doc__.strip().splitlines()[0])
        print("usage: brandfile.py show", file=sys.stderr)
        return 2
    try:
        print(json.dumps(rows(read(), config._read_json(config.ENGINE_JSON)), indent=1, ensure_ascii=False))
    except Refused as e:
        print(f"brandfile: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
