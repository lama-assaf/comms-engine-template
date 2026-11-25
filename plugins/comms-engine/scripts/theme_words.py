#!/usr/bin/env python3
"""
theme_words.py - each theme's licence in plain words, for the people who decide.

Why: a theme's licence basis in `themes.md` is written for the writing agents:
argument codes, file names and section marks, and sometimes the internal names
of what we keep quiet about. A person deciding whether to allow a theme needs
its meaning instead: what we may say about it now, what we never say under it,
why, and what would let it move up a grade. The `storyteller` agent writes
those words (the `theme-words` skill); this script gathers what it writes from,
checks what it wrote, and publishes it. The control page shows the plain words
first and keeps the exact rule behind a toggle.

  facts    every theme with its grade, its rule and a hash of the two
           (state/theme-words/facts.json); and which themes have no plain words
           yet, or words written from a rule that has since changed
  check    the draft (state/theme-words/draft.json) against the facts
  publish  check, then write state/theme-words/latest.json
  status   which themes need their words written again; exit 1 when any do

A draft is refused when a theme in it is not in themes.md, when its hash is
not the current rule's (the words were written from an older rule), when a
field is missing or too long, when it carries a file name, a section mark, an
argument or finding code or a backtick (the reader is not an agent), and when
the gate's denylist or status-word check blocks it: the same checks every post
and the story go through. Without the denylist nothing is published.

Nothing here touches themes.md; a stale explanation is shown as stale, never
silently kept as current.

  engine theme_words facts
  engine theme_words publish
  engine theme_words status
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import gate_lint  # noqa: E402
import memory  # noqa: E402

DIR = os.path.join(paths.state(), "theme-words")
FIELDS = {"now": (True, 260), "not": (True, 220), "why": (True, 220), "next": (False, 200)}
# What an agent's rule carries and a person's words never should.
TECHNICAL = [
    (re.compile(r"\b[\w./-]+\.(md|json|py)\b"), "a file name"),
    (re.compile(r"§"), "a section mark"),
    (re.compile(r"\bL\d{1,2}\b"), "an argument code (L1...)"),
    (re.compile(r"\bF\d{1,3}\b"), "a finding code (F1...)"),
    (re.compile(r"\bs\d{1,2}\b"), "a slide reference (s3...)"),
    (re.compile(r"`"), "a backtick"),
]


def p(name):
    return os.path.join(DIR, name)


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def rule_hash(theme):
    """The hash of a theme's grade and rule: the words are current while it holds."""
    return hashlib.sha256(f"{theme.get('licence', '')}\n{theme.get('licence_basis', '')}".encode("utf-8")).hexdigest()[:12]


def facts(stream=None):
    themes = memory.load_themes(stream)
    latest = load(p("latest.json"), {}).get("themes") or {}
    rows = []
    for t in themes:
        h = rule_hash(t)
        have = latest.get(t["tag"])
        rows.append({"tag": t["tag"], "what": t.get("what", ""), "different": t.get("different", ""),
                     "licence": t.get("licence", ""), "layer": t.get("layer", ""), "fact": t.get("fact", ""),
                     "rule": t.get("licence_basis", ""), "hash": h,
                     "words": "current" if have and have.get("hash") == h else "out of date" if have else "missing"})
    return {"written_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "stream": getattr(memory, "DEFAULT_STREAM_NAME", "") or str(memory.DEFAULT_STREAM).upper(),
            "grades": {"held": "the general idea only: nothing about what we do, no partner, no date",
                       "licensed-with-hedge": "only with the exact words written down for it",
                       "licensed": "argue it freely, in our voice"},
            "themes": rows}


def check(draft, f):
    """Every problem with a draft, as lines for the agent; [] when it may be published."""
    problems = []
    by_tag = {t["tag"]: t for t in f.get("themes") or []}
    entries = (draft or {}).get("themes")
    if not isinstance(entries, dict) or not entries:
        return ["the draft has no `themes` (an object of hashtag to its words)"]
    every = []
    for tag, e in entries.items():
        t = by_tag.get(tag)
        if not t:
            problems.append(f"{tag}: not a theme in themes.md")
            continue
        if not isinstance(e, dict):
            problems.append(f"{tag}: give now, not, why (and next) as an object")
            continue
        if e.get("hash") != t["hash"]:
            problems.append(f"{tag}: the hash is not the current rule's ({t['hash']}); write from facts.json as it is now")
        for key, (required, most) in FIELDS.items():
            text = " ".join(str(e.get(key) or "").split())
            if required and not text:
                problems.append(f"{tag}: `{key}` is needed")
            if len(text) > most:
                problems.append(f"{tag}: `{key}` is {len(text)} characters; at most {most}")
            for rx, what in TECHNICAL:
                if text and rx.search(text):
                    problems.append(f"{tag}: `{key}` carries {what}; say what it means instead")
            every.append(text)
    pseudo = {"title": "", "post": "\n".join(every), "teaser_x": "", "teaser_linkedin": "", "stream": f.get("stream")}
    try:
        memory.denylist()
    except Exception:  # noqa: BLE001 - no denylist, nothing published: the check could not see a private name
        return problems + ["the private denylist cannot be read; restore handles.private.md first"]
    slug = gate_lint.resolve_slug(pseudo)
    for name, fn in (("the denylist check", gate_lint.check_stealth), ("the status-word check", gate_lint.check_status_words)):
        try:
            result = fn(pseudo, slug)
        except Exception as e:  # noqa: BLE001 - a check that cannot run stops the words
            problems.append(f"{name} could not run ({e})")
            continue
        if result["result"] == "block":
            problems.append(f"{result['check']}: {result['line']} {result['fix']}".strip())
    return problems


def publish(draft, f, now=None):
    problems = check(draft, f)
    if problems:
        return problems
    latest = load(p("latest.json"), {"themes": {}})
    themes = dict(latest.get("themes") or {})
    for tag, e in draft["themes"].items():
        themes[tag] = {k: " ".join(str(e.get(k) or "").split()) for k in FIELDS} | {
            "hash": e["hash"], "licence": next(t["licence"] for t in f["themes"] if t["tag"] == tag),
            "written": (now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds")}
    save(p("latest.json"), {"_about": "Each theme's licence in plain words, for the people who decide; written by the storyteller "
                                      "(theme-words skill), checked and published by scripts/theme_words.py. A theme whose hash "
                                      "is not its rule's any more is shown as out of date.", "themes": themes})
    return []


def current(stream=None):
    """The published words, each marked current or out of date against today's rule: what views.py shows."""
    latest = load(p("latest.json"), {}).get("themes") or {}
    try:
        hashes = {t["tag"]: rule_hash(t) for t in memory.load_themes(stream)}
    except Exception:  # noqa: BLE001 - a template before its themes are written
        hashes = {}
    return {tag: dict(w, current=hashes.get(tag) == w.get("hash")) for tag, w in latest.items() if tag in hashes}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Each theme's licence in plain words.")
    ap.add_argument("command", choices=("facts", "check", "publish", "status"))
    ap.add_argument("--draft", help="the draft to check or publish (default state/theme-words/draft.json)")
    args = ap.parse_args(argv)
    if args.command == "facts":
        f = facts()
        save(p("facts.json"), f)
        todo = [t["tag"] for t in f["themes"] if t["words"] != "current"]
        print(f"theme_words: facts for {len(f['themes'])} themes in {os.path.relpath(p('facts.json'))}; "
              + (f"words to write: {', '.join(todo)}" if todo else "every theme's words are current"))
        return 0
    if args.command == "status":
        todo = [(t["tag"], t["words"]) for t in facts()["themes"] if t["words"] != "current"]
        for tag, why in todo:
            print(f"{tag}: {why}")
        print("theme_words: " + (f"{len(todo)} theme(s) need their words written" if todo else "every theme's words are current"))
        return 1 if todo else 0
    f = load(p("facts.json"), None)
    if not f:
        print("theme_words: no facts yet; run `theme_words.py facts` first", file=sys.stderr)
        return 2
    draft = load(args.draft or p("draft.json"), None)
    if draft is None:
        print(f"theme_words: no draft at {os.path.relpath(args.draft or p('draft.json'))}", file=sys.stderr)
        return 2
    problems = check(draft, f) if args.command == "check" else publish(draft, f)
    for line in problems:
        print(line)
    if problems:
        print(f"theme_words: {len(problems)} problem(s); nothing published", file=sys.stderr)
        return 1
    print("theme_words: the draft passes" if args.command == "check" else
          f"theme_words: published {len(draft['themes'])} theme(s) to {os.path.relpath(p('latest.json'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
