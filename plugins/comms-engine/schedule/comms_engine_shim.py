#!/usr/bin/env python3
"""
comms-engine - the fixed path every launchd job of a comms-engine instance runs.

Written to ~/.local/bin/comms-engine by `engine shim --install`; this file in the
plugin is its source. launchd needs one path that does not move, and the plugin's
root does: Claude Code installs each version under a new directory. So at each
start this reads ~/.claude/plugins/installed_plugins.json (or the plugins root
CLAUDE_CODE_PLUGIN_CACHE_DIR names), finds the comms-engine install for the
instance named in COMMS_ENGINE_INSTANCE, and hands every argument to that
version's `bin/engine`:

  comms-engine runjob <label>     what a plist runs
  comms-engine doctor             any `engine` command, by hand
  comms-engine --where            the engine root it would use, and why

The install picked, first hit wins: COMMS_ENGINE_HOME when it holds bin/engine
(a development checkout, set by render.py only for an engine outside the plugin
cache); the install whose projectPath is the instance; a user-scope install; the
most recently updated one. Nothing here is per brand: one shim serves every
instance on the Mac.
"""
import json
import os
import sys

PLUGIN = "comms-engine@comms-engine"


def plugins_root(environ=None):
    env = os.environ if environ is None else environ
    given = (env.get("CLAUDE_CODE_PLUGIN_CACHE_DIR") or "").strip()
    if given:
        return os.path.expanduser(given)
    config = (env.get("CLAUDE_CONFIG_DIR") or "").strip()
    return os.path.join(os.path.expanduser(config or "~/.claude"), "plugins")


def _engine(root):
    return os.path.join(root, "bin", "engine")


def resolve(environ=None, installed=None):
    """(engine root, why) for the instance in the environment; (None, why) when there is none."""
    env = os.environ if environ is None else environ
    home = (env.get("COMMS_ENGINE_HOME") or "").strip()
    if home and os.path.isfile(_engine(home)):
        return home, "COMMS_ENGINE_HOME"
    installed = installed or os.path.join(plugins_root(env), "installed_plugins.json")
    try:
        with open(installed, encoding="utf-8") as f:
            entries = (json.load(f).get("plugins") or {}).get(PLUGIN) or []
    except (OSError, ValueError, AttributeError) as e:
        return None, f"{installed} cannot be read ({e.__class__.__name__})"
    entries = [e for e in entries if isinstance(e, dict) and os.path.isfile(_engine(str(e.get("installPath") or "")))]
    if not entries:
        return None, f"no {PLUGIN} install in {installed}: claude plugin install {PLUGIN}"
    instance = os.path.realpath((env.get("COMMS_ENGINE_INSTANCE") or "").strip() or os.getcwd())
    for e in entries:
        if e.get("projectPath") and os.path.realpath(e["projectPath"]) == instance:
            return e["installPath"], f"the {e.get('scope', 'project')} install for {instance}, version {e.get('version', '?')}"
    for e in entries:
        if e.get("scope") == "user":
            return e["installPath"], f"the user install, version {e.get('version', '?')}"
    newest = max(entries, key=lambda e: str(e.get("lastUpdated") or e.get("installedAt") or ""))
    return newest["installPath"], f"the most recent install, version {newest.get('version', '?')}"


def main(argv):
    root, why = resolve()
    if argv[:1] == ["--where"]:
        print(f"{root or '(none)'}  ({why})")
        return 0 if root else 1
    if root is None:
        print(f"comms-engine: {why}", file=sys.stderr)
        return 2
    os.execv(sys.executable, [sys.executable, _engine(root), *argv])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
