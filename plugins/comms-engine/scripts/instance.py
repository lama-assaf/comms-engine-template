#!/usr/bin/env python3
"""
instance.py - a new instance repository for one brand: `engine new-instance`.

Why: the engine is the comms-engine plugin, and each brand keeps its own
records in its own repository: brand.json, the memory, Content/, state/. The
template that ships the engine (this repository, or the clone of it Claude Code
keeps as the comms-engine marketplace) is itself the first instance; a new one
gets its instance files and nothing of the engine: the memory as shapes, no
plugins/, no Tooling/. Its .claude/settings.json names the marketplace on GitHub
and enables comms-engine@comms-engine, so the first `claude` in it offers the
plugin; brand.json pins the engine version that wrote it. Then `git init`.
Nothing is committed: the first commit is the owner's.

The files are copied from the template, never from the instance a command runs
in, so another brand's memory can never reach a new one.

  engine new-instance <dir>                          the placeholder brand (acme), set up later with `engine init`
  engine new-instance <dir> --from brand.json        set up from a setup file, as `engine init --from` does
  engine new-instance <dir> --marketplace owner/repo a fork's marketplace instead of params.instance.marketplace
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
sys.path.insert(0, HERE)
import config  # noqa: E402

ENGINE = paths.engine_home()
PLUGIN = "comms-engine@comms-engine"
#: What an instance owns, relative to the template root. A directory is copied whole, but for
#: the files no repository may carry (the private denylist).
INSTANCE_FILES = (".atelier/memory", "brand.json", "themes.json", "streams/README.md", "state/README.md",
                  "state/metrics-input/README.md", ".mcp.json", ".gitignore")
NEVER = ("handles.private.md",)

README = """# {name}: communications

The instance repository of {name}: its setup file (`brand.json`), its memory
(`.atelier/memory/`), its content (`Content/`) and its records (`state/`). The
engine is the comms-engine plugin, pinned in `brand.json` (`engine.version`).

```bash
claude                      # trust the folder: it offers the comms-engine marketplace and plugin
engine init                 # name the brand, if `brand.json` still names the placeholder
engine doctor               # one ok/FAIL line per check
engine shim --install       # ~/.local/bin/comms-engine, the path the schedules run
engine install --dry-run    # the schedules this Mac would load
```

`handles.private.md` (the stealth denylist) is copied here by hand, never
through git.
"""


class Refused(Exception):
    """The instance cannot be written as asked; the message says why and what to do."""


def template_root(engine=ENGINE, plugins_root=None):
    """The template that ships this engine: the checkout around it, or the marketplace clone."""
    here = os.path.dirname(os.path.dirname(engine))
    candidates = [here, os.path.join(plugins_root or _plugins_root(), "marketplaces", "comms-engine")]
    for root in candidates:
        if os.path.isfile(os.path.join(root, ".claude-plugin", "marketplace.json")) and \
                os.path.isdir(os.path.join(root, ".atelier", "memory")):
            return root
    raise Refused("no template found beside this engine or in the comms-engine marketplace clone; "
                  "run new-instance from the template checkout, or `claude plugin marketplace add` it first")


def _plugins_root():
    given = os.environ.get("CLAUDE_CODE_PLUGIN_CACHE_DIR")
    if given:
        return os.path.expanduser(given)
    return os.path.join(os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"), "plugins")


def instance_files(template):
    """Every file a new instance gets, as paths relative to the template."""
    out = []
    for rel in INSTANCE_FILES:
        full = os.path.join(template, rel)
        if os.path.isdir(full):
            for base, dirs, files in os.walk(full):
                dirs[:] = sorted(d for d in dirs if d != "__pycache__")
                for name in sorted(files):
                    if name not in NEVER and name != ".DS_Store":
                        out.append(os.path.relpath(os.path.join(base, name), template))
        elif os.path.isfile(full):
            out.append(rel)
    return out


def settings(template, marketplace):
    """The template's .claude/settings.json with the marketplace named and the engine enabled."""
    with open(os.path.join(template, ".claude", "settings.json"), encoding="utf-8") as f:
        doc = json.load(f)
    doc["_about"] = ("Project settings, tracked. The engine is the comms-engine plugin from the marketplace below; "
                     "Claude Code offers it on the first `claude` in this folder, once the folder is trusted. The deny list "
                     "keeps the plugins' look-alikes of the engine's gate, listening, publish and post skills out. "
                     "Per-machine permissions live in settings.local.json (gitignored).")
    doc["extraKnownMarketplaces"] = {"comms-engine": {"source": dict(marketplace)}}
    doc["enabledPlugins"] = {PLUGIN: True, **{k: v for k, v in (doc.get("enabledPlugins") or {}).items() if k != PLUGIN}}
    order = ["_about", "extraKnownMarketplaces", "enabledPlugins"]
    return {**{k: doc[k] for k in order}, **{k: v for k, v in doc.items() if k not in order}}


def marketplace_source(given=None):
    if given:
        return {"source": "github", "repo": given}
    src = config.cfg("instance.marketplace", {}) or {}
    if not isinstance(src, dict) or not src.get("source"):
        raise Refused("no marketplace to name: set params.instance.marketplace in engine.json, or pass --marketplace owner/repo")
    return {k: v for k, v in src.items() if not k.startswith("_")}


def new_instance(target, from_file=None, marketplace=None, template=None, run=subprocess.run, out=print):
    """Write a new instance at `target`; returns the files written. Refuses a directory that is not empty."""
    target = os.path.abspath(os.path.expanduser(target))
    if os.path.exists(target) and (not os.path.isdir(target) or os.listdir(target)):
        raise Refused(f"{target} exists and is not empty; a new instance starts in an empty directory")
    if from_file and not os.path.isfile(from_file):
        raise Refused(f"--from {from_file}: no such file")
    template = template or template_root()
    source = marketplace_source(marketplace)
    files = instance_files(template)
    os.makedirs(target, exist_ok=True)
    for rel in files:
        dst = os.path.join(target, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(template, rel), dst)
    os.makedirs(os.path.join(target, ".claude"), exist_ok=True)
    with open(os.path.join(target, ".claude", "settings.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(settings(template, source), indent=2) + "\n")
    os.makedirs(os.path.join(target, "Content", "Calendar"), exist_ok=True)
    written = files + [".claude/settings.json"]
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR",)}
    env[paths.ENV] = target
    engine_py = os.path.join(ENGINE, "scripts", "engine.py")
    if from_file:
        proc = run([sys.executable, engine_py, "init", "--from", os.path.abspath(from_file)], cwd=target, env=env,
                   capture_output=True, text=True)
        if proc.returncode != 0:
            raise Refused(f"init --from {from_file} refused it: {(proc.stdout + proc.stderr).strip().splitlines()[-1:]}")
    _pin(target)
    with open(os.path.join(target, "brand.json"), encoding="utf-8") as f:
        name = ((json.load(f).get("brand") or {}).get("name")) or "This brand"
    with open(os.path.join(target, "README.md"), "w", encoding="utf-8") as f:
        f.write(README.format(name=name))
    written.append("README.md")
    proc = run(["git", "init", "-q", target], capture_output=True, text=True)
    out(f"wrote {target}: {len(written)} files, the memory as shapes, no engine code")
    out(f"  marketplace: {json.dumps(source)}; {PLUGIN} enabled in .claude/settings.json")
    out("  git init: " + ("done, nothing committed" if proc.returncode == 0 else f"failed ({(proc.stderr or '').strip()[:120]})"))
    out("next: cd " + target + " && claude   (trust the folder, accept the plugin), then: engine doctor")
    return written


def _pin(target):
    """brand.json pins the engine that wrote the instance, unless the file already pins one."""
    path = os.path.join(target, "brand.json")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    doc = json.loads(text)
    if isinstance(doc.get("engine"), dict) and doc["engine"].get("version"):
        return
    import engine
    version = engine.engine_version()
    if not version:
        return
    import brandfile
    doc = {**{k: doc[k] for k in ("_about", "brand") if k in doc}, "engine": {"version": version},
           **{k: v for k, v in doc.items() if k not in ("_about", "brand", "engine")}}
    brandfile.write(doc, target=path)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    usage = "usage: engine new-instance <dir> [--from <brand.json>] [--marketplace owner/repo]"
    opts = {}
    for flag in ("--from", "--marketplace"):
        if flag in argv:
            i = argv.index(flag)
            if i + 1 >= len(argv):
                print(usage, file=sys.stderr)
                return 2
            opts[flag] = argv[i + 1]
            del argv[i:i + 2]
    if len(argv) != 1 or argv[0].startswith("-"):
        print(usage, file=sys.stderr)
        return 2
    try:
        new_instance(argv[0], from_file=opts.get("--from"), marketplace=opts.get("--marketplace"))
    except Refused as e:
        print(f"new-instance: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
