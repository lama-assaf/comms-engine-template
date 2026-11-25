#!/usr/bin/env python3
"""
onboard.py - `onboard-stream <slug>`: where a stream stands before it may draft.

Why: a stream (any row of `.atelier/memory/streams.md`, the brand's own
included) has a registry row, a memory directory, an engine-local search file
and a corpus root, kept in four places, and the question "may it draft yet,
and if not, what is missing" took a walk through all of them. This reads them
all through `memory.py` and `config.py`, prints one line per thing checked,
asks the three onboarding questions on a terminal (every one a flag with a
default, so a headless run never waits), and ends with `memory.may_draft` and
the reasons it is false. On a fresh clone the answer is "no" for the brand's
own stream too, by design: its owner is `unset` and its voice is shaped, not
written.

What it writes, and nothing else: the `streams.<slug>` block of
`engine.local.json` through `config.set_local` (corpus_root, themes_file), and
an empty-but-shaped `voice.md` from `.atelier/memory/templates/voice.md` when
the stream has none and `--write-voice` is given. The registry row, its owner
cell and its channels cell are a person's change to the setup on a recorded
decision: the key of `brand.json` and the row it renders to are printed, never
written (`engine.py apply` renders the row once the person has set the key). `autopilot` stays `nothing`. Memory
content reaches a stream only through `/corpus-update --apply --stream <slug>`.
The layout of a second stream's directory, and the five things that register
one, are in `.atelier/memory/streams/README.md`.

  engine onboard <slug>
  engine onboard <slug> --owner-confirmed yes --corpus-root ~/x --channels "X @handle"
  engine onboard <slug> --write-voice [--voice-from template|<brief path>]
  engine onboard <slug> --themes-file streams/<slug>/themes.json
  engine onboard <slug> --dry-run      # report and the lines to add; writes nothing
  engine onboard-stream <slug>   # the same, through the console

Exit 0; 1 when a value is refused (a corpus root that does not exist, a brief
that does not exist); 2 for an unknown slug (one not in the registry; the
registry never defaults) or a usage error.
"""
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
REPO = paths.instance()

sys.path.insert(0, HERE)
import config  # noqa: E402
import memory  # noqa: E402

#: The template a new voice.md is shaped from; tests point it at a copy.
TEMPLATE = os.path.join(memory.MEMORY, "templates", "voice.md")
#: Engine-local search material per stream (test_streams checks the same path).
ENGINE_STREAMS = os.path.join(REPO, "streams")
#: The file set every stream directory carries (plan v2, item A2; the layout
#: in .atelier/memory/streams/README.md); a trailing slash marks a directory.
FILE_SET = ("voice.md", "status.md", "instincts.md", "themes.md", "handles.md", "claims.md",
            "reviews.md", "lessons.md", "calendar.md", "campaigns/", "decisions/")
#: Files a script creates on first use, so their absence is reported as
#: `absent`, not `MISSING`: reviews.md is written by desk_sync.py --pull.
CREATED_ON_FIRST_USE = ("reviews.md",)
#: The sentinel the stub files and the template carry until a brief fills them.
NOT_WRITTEN = "Not written yet"
#: The questions: flag key, prompt, and which report field holds the default.
QUESTIONS = (
    ("owner_confirmed", "owner confirmed? (yes/no, never a name)"),
    ("corpus_root", "corpus root (a path; empty keeps the current)"),
    ("channels", "channels (as the registry cell reads them)"),
)
#: The gate's fixture: enough of an item for every check to run against the
#: stream's own memory; the verdict on a fresh stream is block, by design.
GATE_FIXTURE = {
    "id": "onboard-fixture",
    "theme": "#Onboarding",
    "slug": "onboard-fixture",
    "title": "A fixture, not a draft.",
    "post": "A fixture item the onboarding check gates against this stream's memory. Nothing in it is claimed.",
    "teaser_linkedin": "A fixture, not a draft.",
    "teaser_x": "A fixture, not a draft.",
    "cites": [],
    "partner_tags": [],
}


class Refused(RuntimeError):
    """A value the onboarding will not write."""


class Usage(RuntimeError):
    """A command line it cannot read."""


# --- reading ---------------------------------------------------------------------

def _rel(path):
    try:
        rel = os.path.relpath(path, memory.REPO)
    except ValueError:
        return path
    return path if rel.startswith("..") else rel


def voice_state(path):
    """`missing`, `shaped` (the template or a stub, no voice in it yet) or `written`."""
    if not os.path.exists(path):
        return "missing"
    with open(path, encoding="utf-8") as f:
        return "shaped" if NOT_WRITTEN in f.read() else "written"


def file_set(stream_dir):
    """`[(name, present)]` over FILE_SET; a directory counts when it is one."""
    out = []
    for name in FILE_SET:
        p = os.path.join(stream_dir, name.rstrip("/"))
        out.append((name, os.path.isdir(p) if name.endswith("/") else os.path.isfile(p)))
    return out


def themes_json_state(slug, path=None):
    """`(path, state, terms)`: the engine-local search file and how many terms it holds."""
    path = path or os.path.join(ENGINE_STREAMS, slug, "themes.json")
    if not os.path.exists(path):
        return path, "missing", 0
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except ValueError:
        return path, "unreadable", 0
    terms = d.get("search_terms") or {}
    return path, ("empty" if not terms else "present"), len(terms)


def report(slug, corpus_root=None, themes_file=None, env=None, local=None):
    """Everything checked, as one dict; raises SharedMemoryError on an unknown slug."""
    row = memory.stream(slug)
    sdir = memory.stream_dir(slug)
    cfg_streams = config.streams(env=env, local=local or config.LOCAL_JSON)
    block = cfg_streams.get(slug) or {}
    root = corpus_root or block.get("corpus_root") or ""
    tfile = themes_file or block.get("themes_file") or _rel(os.path.join(ENGINE_STREAMS, slug, "themes.json"))
    tpath = tfile if os.path.isabs(tfile) else os.path.join(memory.REPO, tfile)
    jpath, jstate, terms = themes_json_state(slug, tpath)
    private = os.path.join(sdir, "handles.private.md")
    return {
        "slug": slug,
        "row": row,
        "owner": row["owner"].strip().lower(),
        "dir": sdir,
        "dir_present": os.path.isdir(sdir),
        "files": file_set(sdir),
        "voice": voice_state(os.path.join(sdir, "voice.md")),
        "private_present": os.path.exists(private),
        "themes_json": (jpath, jstate, terms),
        "themes_file": tfile,
        "corpus_root": root,
        "corpus_root_source": "flag" if corpus_root else ("engine.local.json" if block.get("corpus_root") else "registry only"),
        "corpus_root_exists": bool(root) and os.path.isdir(os.path.expanduser(root)),
        "channels": row["channels"].strip(),
        "own_channels": _own_channels(slug),
        "may_draft": memory.may_draft(slug),
    }


def _own_channels(slug):
    try:
        return len(memory.load_handles(slug)["own_channels"])
    except memory.SharedMemoryError:
        return None


def why_not(rep):
    """The reasons `may_draft` is false, in the order a person fixes them."""
    out = []
    if rep["owner"] != "confirmed":
        out.append(f"owner is `unset` (a person sets streams.{rep['slug']}.owner to \"confirmed\" in brand.json "
                   "on a decision, then engine.py apply; never a name)")
    if rep["voice"] == "missing":
        out.append(f"{_rel(os.path.join(rep['dir'], 'voice.md'))} is missing (--write-voice shapes it)")
    elif rep["voice"] == "shaped":
        out.append(f"{_rel(os.path.join(rep['dir'], 'voice.md'))} is shaped but not written "
                   f"(may_draft counts the file; /corpus-update --apply --stream {rep['slug']} fills it)")
    if not rep["dir_present"]:
        out.append(f"memory directory {_rel(rep['dir'])} does not exist")
    auto = rep["row"]["autopilot"].strip().lower()
    if auto.startswith("nothing"):
        out.append("autopilot is `nothing`: drafts only, nothing leaves the queue (changes by a decision file)")
    return out


# --- the lines a person adds ----------------------------------------------------

def registry_line(row, owner=None, channels=None):
    """The stream's registry row as streams.md carries it, with the cells a person would change."""
    cells = [
        row["slug"], row["name"], row["narrator"],
        owner or row["owner"], row["objectives"], row["autopilot"],
        channels or row["channels"], row["memory"], row["corpus root"], row["corpus status"],
    ]
    return "| " + " | ".join(cells) + " |"


# --- writing ----------------------------------------------------------------------

def write_voice(slug, name, stream_dir, template=None, source=None, now=None):
    """Shape voice.md from the template; refuses to touch a file that exists."""
    target = os.path.join(stream_dir, "voice.md")
    if os.path.exists(target):
        raise Refused(f"{_rel(target)} exists; onboarding never overwrites a voice")
    template = template or TEMPLATE
    if not os.path.exists(template):
        raise Refused(f"template missing: {_rel(template)}")
    with open(template, encoding="utf-8") as f:
        text = f.read()
    today = (now or dt.date.today()).isoformat()
    text = text.replace("__NAME__", name).replace("__SLUG__", slug).replace("__DATE__", today)
    if source and source != "template":
        # The brief is named as the source to fill from, never copied: memory
        # content arrives through /corpus-update only.
        text = text.replace("Not written yet.", f"Not written yet. Source brief to fill from: `{source}`.", 1)
    os.makedirs(stream_dir, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(text)
    return target


def write_local(slug, corpus_root=None, themes_file=None, local=None):
    """The streams block of engine.local.json; returns {path: value} written."""
    local = local or config.LOCAL_JSON
    written = {}
    if corpus_root:
        config.set_local(f"streams.{slug}.corpus_root", corpus_root, local=local)
        written[f"streams.{slug}.corpus_root"] = corpus_root
    if themes_file:
        config.set_local(f"streams.{slug}.themes_file", themes_file, local=local)
        written[f"streams.{slug}.themes_file"] = themes_file
    return written


# --- the closing checks -----------------------------------------------------------

def gate_fixture(slug, name):
    """`gate_lint.lint` over GATE_FIXTURE as this stream's item: the verdict and the stream line."""
    try:
        import gate_lint  # noqa: WPS433  (lazy: it pulls repo.py and the vault paths)
    except Exception as e:  # pragma: no cover - a checkout without the gate
        return [f"gate      skipped  gate_lint did not import: {e}"]
    item = dict(GATE_FIXTURE, stream=name)
    try:
        result = gate_lint.lint(item)
    except Exception as e:
        return [f"gate      ERROR    {type(e).__name__}: {e}"]
    lines = [f"gate      {result['verdict']:<8} gate_lint on a fixture item as stream {name}"]
    for c in result["checks"]:
        if c.get("check") in ("lint: stream", "lint: stealth") and c.get("result") == "block":
            lines.append(f"          {c['check']}: {c.get('fix', '').strip()}")
    return lines


def memory_summary(slug):
    try:
        return memory.summary(slug).splitlines()
    except memory.SharedMemoryError as e:
        return [f"memory    ERROR  {e}"]


# --- the questions ----------------------------------------------------------------

def _yes(raw):
    v = str(raw).strip().lower()
    if v in ("1", "true", "yes", "on", "y"):
        return True
    if v in ("0", "false", "no", "off", "n", ""):
        return False
    raise Refused(f"{raw!r} is not yes/no")


def ask(rep, answers, interactive):
    """Fill the three answers: flags win, a terminal is asked, headless keeps the defaults."""
    defaults = {
        "owner_confirmed": "yes" if rep["owner"] == "confirmed" else "no",
        "corpus_root": rep["corpus_root"],
        "channels": rep["channels"],
    }
    out = {}
    for key, prompt in QUESTIONS:
        if key in answers:
            out[key] = answers[key]
            continue
        if interactive:
            try:
                raw = input(f"{prompt} [{defaults[key] or '-'}]: ").strip()
            except EOFError:
                raw = ""
            out[key] = raw or defaults[key]
        else:
            out[key] = defaults[key]
    if interactive and rep["voice"] == "missing" and "write_voice" not in answers:
        try:
            raw = input("shape voice.md from the template? (yes/no) [no]: ").strip()
        except EOFError:
            raw = ""
        answers["write_voice"] = raw or "no"
    return out


def parse(argv):
    """`<slug> --key value | --key=value | --flag` -> (slug, {key: value}); dashes become underscores."""
    argv = list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        raise Usage("")
    if argv[0].startswith("--"):
        raise Usage(f"the first argument is the slug, got {argv[0]!r}")
    slug = argv[0].strip().lower()
    out = {}
    i = 1
    while i < len(argv):
        a = argv[i]
        if not a.startswith("--"):
            raise Usage(f"unexpected argument {a!r}")
        key = a[2:].replace("-", "_")
        if "=" in key:
            key, val = key.split("=", 1)
            out[key] = val
            i += 1
            continue
        if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            out[key] = argv[i + 1]
            i += 2
        else:
            out[key] = "true"
            i += 1
    return slug, out


# --- main ----------------------------------------------------------------------------

def _tick(ok):
    return "ok     " if ok else "MISSING"


def run(slug, flags, interactive=None, local=None, env=None, now=None):
    """The whole onboarding pass; prints the report and returns the exit code."""
    interactive = sys.stdin.isatty() if interactive is None else interactive
    local = local or config.LOCAL_JSON
    dry = _yes(flags.get("dry_run", "false"))
    try:
        rep = report(slug, corpus_root=flags.get("corpus_root") or None,
                     themes_file=flags.get("themes_file") or None, env=env, local=local)
    except memory.SharedMemoryError as e:
        print(f"onboard-stream: {e}")
        return 2
    row = rep["row"]
    print(f"onboard-stream {slug}{'  (dry run: nothing written)' if dry else ''}")
    print(f"registry  ok       streams.md row: {row['name']}  narrator: {row['narrator']}  "
          f"autopilot: {'nothing' if row['autopilot'].strip().lower().startswith('nothing') else 'rule'}  "
          f"corpus status: {row['corpus status']}")
    print(f"owner     {'ok     ' if rep['owner'] == 'confirmed' else 'unset  '}  {rep['owner']}  (never a name)")
    print(f"memory    {_tick(rep['dir_present'])}  {_rel(rep['dir'])}")
    for name, present in rep["files"]:
        extra = f"  ({rep['voice']})" if name == "voice.md" else ""
        if not present and name in CREATED_ON_FIRST_USE:
            print(f"          absent   {name}  (written by desk_sync.py --pull on the first standing review)")
            continue
        print(f"          {_tick(present)}  {name}{extra}")
    print(f"          {'ok     ' if rep['private_present'] else 'ABSENT '}  handles.private.md"
          f"{'' if rep['private_present'] else '  (gitignored; the gate blocks this stream until it is present)'}")
    jpath, jstate, terms = rep["themes_json"]
    print(f"themes    {_tick(jstate != 'missing')}  {_rel(jpath)}  {jstate}, {terms} search terms"
          f"  (themes_file: {rep['themes_file']})")
    root = rep["corpus_root"]
    if root:
        print(f"corpus    {_tick(rep['corpus_root_exists'])}  {root}  ({rep['corpus_root_source']}"
              f"{'' if rep['corpus_root_exists'] else ', not on this machine'})")
    else:
        print(f"corpus    unset    registry says: {row['corpus root']}  (no path in engine.local.json; --corpus-root sets one)")
    own = rep["own_channels"]
    print(f"channels  {'ok     ' if rep['channels'] not in ('', '—', '-', '— (collect)') else 'collect'}  "
          f"{rep['channels']}  ({own if own is not None else '?'} own-channel rows in handles.md)")

    # The questions, then what each answer does. A root that is already
    # configured but not on this machine (engine.json's placeholder on a fresh
    # clone, or a colleague's path) is reported above as MISSING and kept; only
    # a root this run would write is refused when it does not exist.
    current_root = (config.streams(env=env, local=local).get(slug) or {}).get("corpus_root") or ""
    try:
        answers = ask(rep, flags, interactive)
        owner_yes = _yes(answers["owner_confirmed"])
        new_root = (answers.get("corpus_root") or "").strip()
        new_root = os.path.expanduser(new_root) if new_root else ""
        if new_root and new_root != os.path.expanduser(current_root) and not os.path.isdir(new_root):
            raise Refused(f"corpus root does not exist: {new_root}")
        source = flags.get("voice_from") or "template"
        if source != "template" and not os.path.exists(os.path.expanduser(source)):
            raise Refused(f"voice source brief does not exist: {source}")
    except Refused as e:
        print(f"refused   {e}")
        return 1

    print()
    edits = []
    if owner_yes and rep["owner"] != "confirmed":
        edits.append(("owner cell -> confirmed", registry_line(row, owner="confirmed",
                                                               channels=answers["channels"] if answers["channels"] != rep["channels"] else None)))
    elif answers["channels"] and answers["channels"] != rep["channels"]:
        edits.append(("channels cell", registry_line(row, channels=answers["channels"])))
    if edits:
        print("a person's change to the setup (brand.json, then `engine.py apply`; onboarding never writes the registry):")
        for what, line in edits:
            print(f"  {what}:")
            if "owner" in what:
                print(f"  brand.json  streams.{slug}.owner = \"confirmed\"")
            if answers["channels"] and answers["channels"] != rep["channels"]:
                print(f"  brand.json  streams.{slug}.channels = {json.dumps(answers['channels'], ensure_ascii=False)}")
            print("  the row it renders to in .atelier/memory/streams.md:")
            print(f"  {line}")
    elif not owner_yes and rep["owner"] != "confirmed":
        print(f"owner stays unset: the stream drafts nothing until a person sets streams.{slug}.owner in brand.json")

    # A root is written when it is new to engine.local.json; the headless default
    # is what the file already holds, so a run without flags writes nothing.
    written = {}
    root_to_write = new_root if new_root and new_root != os.path.expanduser(current_root) else ""
    tfile = flags.get("themes_file") or ""
    if root_to_write or tfile:
        if dry:
            print(f"would write {_rel(local)}: "
                  + ", ".join(k for k in (root_to_write and f"streams.{slug}.corpus_root", tfile and f"streams.{slug}.themes_file") if k))
        else:
            written = write_local(slug, corpus_root=root_to_write or None, themes_file=tfile or None, local=local)
            print(f"wrote {_rel(local)}: " + ", ".join(f"{k} = {v}" for k, v in written.items()))

    if _yes(flags.get("write_voice", "false")):
        target = os.path.join(rep["dir"], "voice.md")
        if rep["voice"] != "missing":
            print(f"voice.md  kept     {_rel(target)} exists ({rep['voice']}); never overwritten")
        elif dry:
            print(f"would write {_rel(target)} from {_rel(TEMPLATE)}")
        else:
            try:
                write_voice(slug, row["name"], rep["dir"], source=source, now=now)
                print(f"wrote {_rel(target)} from {_rel(TEMPLATE)} (shaped, not written: the headings only)")
            except Refused as e:
                print(f"refused   {e}")
                return 1

    # The closing checks, read fresh so a voice just shaped shows up.
    print()
    for line in memory_summary(slug):
        print(line)
    for line in gate_fixture(slug, row["name"]):
        print(line)
    print()
    may = memory.may_draft(slug)
    rep2 = report(slug, corpus_root=flags.get("corpus_root") or None,
                  themes_file=flags.get("themes_file") or None, env=env, local=local)
    reasons = why_not(rep2)
    if may:
        print("may draft: yes  (owner confirmed, voice.md present)"
              + ("; " + reasons[0] if reasons else ""))
    else:
        print("may draft: no   -> drafts nothing, publishes nothing, posts nothing, by every path")
        for r in reasons:
            print(f"  - {r}")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        slug, flags = parse(argv)
    except Usage as e:
        print(__doc__.strip().splitlines()[0])
        if str(e):
            print(f"onboard-stream: {e}", file=sys.stderr)
        print("usage: onboard.py <slug> [--owner-confirmed yes|no] [--corpus-root PATH] [--channels TEXT] "
              "[--write-voice] [--voice-from template|BRIEF] [--themes-file PATH] [--dry-run]", file=sys.stderr)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    try:
        return run(slug, flags)
    except Refused as e:
        print(f"refused   {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
