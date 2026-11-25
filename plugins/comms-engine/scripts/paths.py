#!/usr/bin/env python3
"""
paths.py - where the engine is, and where the instance it serves is.

Why: the engine's code and a brand's records used to share one tree, so every
script found the repository three levels above itself and its state beside its
code. Packaged as the comms-engine plugin, the code lives wherever Claude Code
installed it and the records live in the brand's instance repository, so the
two are found separately, here and nowhere else.

The instance, first hit wins:

  1. COMMS_ENGINE_INSTANCE     set by `engine`, the launchd plists and runjob.py.
                               A fixed name: env_prefix lives inside the instance
                               this has to find.
  2. CLAUDE_PROJECT_DIR        set by Claude Code for hooks and tool calls, used
                               when it holds a brand.json
  3. the nearest parent of the working directory that holds brand.json
  4. three levels above this script: the development checkout, where the engine
     sits inside the instance it serves

  instance()     the instance root: brand.json, memory, Content/, state/
  state()        <instance>/state, the records and logs
  engine_home()  the engine's own root: scripts/, engine.json, briefs/, ui/
  local_json()   <instance>/engine.local.json, this machine's overrides
  script(name)   the engine script `engine <name>` runs, or None
  expand(argv)   `["engine", name, ...]` as the interpreter call it means

  python3 scripts/paths.py                 # every answer, one per line
  python3 scripts/paths.py instance        # one of them
"""
import os
import sys

ENV = "COMMS_ENGINE_INSTANCE"
HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_HOME = os.path.dirname(HERE)
#: Where `engine <name>` looks for <name>.py or <name>.sh, in order.
SCRIPT_DIRS = ("scripts", "schedule", os.path.join("skills", "deck-reader", "scripts"))
#: engine.py's own commands: `engine doctor` is `engine.py doctor`. They come
#: before a script of the same name (`engine secrets` is the console's, which
#: passes --export and --check through to secrets.py).
CONSOLE = ("init", "validate", "apply", "status", "run", "enable", "disable", "logs", "results",
           "export-published", "eval", "doctor", "setup", "onboard-stream", "secrets", "plugins",
           "runtime", "host-check", "shim", "new-instance")


def _marked(d):
    return bool(d) and os.path.isfile(os.path.join(d, "brand.json"))


def _from_cwd(cwd=None):
    d = os.path.abspath(cwd or os.getcwd())
    while True:
        if _marked(d):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def instance(environ=None, cwd=None):
    """The instance root, by the order in the module's docstring."""
    env = os.environ if environ is None else environ
    given = (env.get(ENV) or "").strip()
    if given:
        return os.path.abspath(os.path.expanduser(given))
    project = (env.get("CLAUDE_PROJECT_DIR") or "").strip()
    if _marked(project):
        return os.path.abspath(project)
    try:
        found = _from_cwd(cwd)
    except OSError:  # a working directory deleted under us
        found = None
    return found or os.path.dirname(os.path.dirname(ENGINE_HOME))


def engine_home():
    return ENGINE_HOME


def state(root=None):
    return os.path.join(root or instance(), "state")


def local_json(root=None):
    return os.path.join(root or instance(), "engine.local.json")


def script(name, home=None):
    """The file `engine <name>` runs: scripts/<name>.py first, `-` read as `_`; None when there is none."""
    home = home or ENGINE_HOME
    for stem in dict.fromkeys((name, name.replace("-", "_"))):
        for d in SCRIPT_DIRS:
            for ext in (".py", ".sh"):
                path = os.path.join(home, d, stem + ext)
                if os.path.isfile(path):
                    return path
    return None


def _interpreter(path, python):
    if path.endswith(".py"):
        return python
    with open(path, encoding="utf-8") as f:
        first = f.readline()
    return first[2:].split()[0] if first.startswith("#!") else "/bin/zsh"


def expand(argv, python="python3", home=None):
    """`["engine", name, *args]` as the interpreter call it means; any other argv as given.

    None when `engine` names neither a console command nor a script.
    """
    argv = list(argv)
    if not argv or argv[0] != "engine":
        return argv
    if len(argv) < 2:
        return None
    home = home or ENGINE_HOME
    name, rest = argv[1], argv[2:]
    if name in CONSOLE:
        return [python, os.path.join(home, "scripts", "engine.py"), name, *rest]
    path = script(name, home)
    if path is None:
        return None
    return [_interpreter(path, python), path, *rest]


def names(home=None):
    """Every name `engine` answers to: the console's commands, then the scripts."""
    home = home or ENGINE_HOME
    found = set()
    for d in SCRIPT_DIRS:
        full = os.path.join(home, d)
        if os.path.isdir(full):
            found.update(n.rsplit(".", 1)[0] for n in os.listdir(full)
                         if n.endswith((".py", ".sh")) and not n.startswith("_"))
    return list(CONSOLE) + sorted(found - set(CONSOLE))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    answers = {"instance": instance(), "state": state(), "engine_home": engine_home(), "local_json": local_json()}
    if argv:
        if argv[0] not in answers:
            print(f"paths: one of {', '.join(answers)}", file=sys.stderr)
            return 2
        print(answers[argv[0]])
        return 0
    for k, v in answers.items():
        print(f"{k:<12} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
