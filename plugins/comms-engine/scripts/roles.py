#!/usr/bin/env python3
"""
roles.py - which plugin plays which role, at which pinned version, with which brief.

Why: the engine calls agents and skills of three plugins (atelier, salon, motion), and a plugin
agent knows none of this repository's rules. Naming one in a prompt was the whole wiring, so a
plugin update could change what a step does and nothing would say so. A role is now data:

  params.plugins.roles.<role>   {use, kind, version, brief, fallback, when?}

  use       `<plugin>:<agent or skill>`, as it is called
  kind      `agent` or `skill`
  version   the plugin version the brief was read against; doctor fails on another
  brief     the file under  that carries this repository's rules
            for the role (briefs/, or the workflow's own prompt under workflows/)
  fallback  what happens in a checkout where the plugin is not installed: every role has one,
            because plugins are installed per machine and a fresh clone has none
  when      a note on when the role is asked at all

The defaults ship in engine.json; a brand changes one in brand.json (`plugins.roles`), merged
over them by config.py. `problems()` is what the suite pins: every role names an enabled plugin,
a brief that exists, a fallback, and nothing `.claude/settings.json` denies. `doctor_lines()` is
`engine.py doctor`'s: one line per plugin, FAIL when an installed plugin is not the version its
roles are pinned to.

  engine roles            # every role, one line each
  engine roles --check    # exit 1 on a problem
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
REPO = paths.instance()
CLAUDE = ENGINE
SETTINGS = os.path.join(REPO, ".claude", "settings.json")
sys.path.insert(0, HERE)
import config  # noqa: E402

KINDS = ("agent", "skill")
USE = re.compile(r"^([a-z][a-z0-9-]*):([a-z][a-z0-9-]*)$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def roles():
    """`{role: {use, kind, version, brief, fallback, when}}`, engine.json's with the brand's over them."""
    raw = config.cfg("plugins.roles", {}) or {}
    return {k: dict(v) for k, v in raw.items() if not k.startswith("_") and isinstance(v, dict)}


def plugin_of(role):
    m = USE.match(str(role.get("use") or ""))
    return m.group(1) if m else ""


def _denied():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return set((json.load(f).get("permissions") or {}).get("deny") or [])
    except (OSError, ValueError):
        return set()


def problems(all_roles=None):
    """What is wrong with the roles as data, one line each; empty when every role resolves or falls back."""
    all_roles = roles() if all_roles is None else all_roles
    enabled = {str(n).split("@", 1)[0] for n in config.cfg("plugins.names", []) or []}
    denied = _denied()
    out = []
    if not all_roles:
        return ["plugins.roles: no role is defined"]
    for name, r in all_roles.items():
        at = f"plugins.roles.{name}"
        m = USE.match(str(r.get("use") or ""))
        if not m:
            out.append(f"{at}.use: {r.get('use')!r} is not `<plugin>:<agent or skill>`")
            continue
        if m.group(1) not in enabled:
            out.append(f"{at}.use: the plugin {m.group(1)} is not one of plugins.names")
        if r.get("kind") not in KINDS:
            out.append(f"{at}.kind: {r.get('kind')!r} is not agent or skill")
        elif f"{'Agent' if r['kind'] == 'agent' else 'Skill'}({r['use']})" in denied:
            out.append(f"{at}.use: {r['use']} is denied in .claude/settings.json; a role cannot be something the repository forbids")
        if not VERSION.match(str(r.get("version") or "")):
            out.append(f"{at}.version: pin the plugin version the brief was read against, such as 0.3.0")
        brief = str(r.get("brief") or "")
        if not brief or not os.path.isfile(os.path.join(CLAUDE, brief)):
            out.append(f"{at}.brief: {brief!r} is not a file under ")
        if not str(r.get("fallback") or "").strip():
            out.append(f"{at}.fallback: say what happens where the plugin is not installed")
    pins = {}
    for name, r in all_roles.items():
        pins.setdefault(plugin_of(r), set()).add(str(r.get("version")))
    for plugin, versions in pins.items():
        if plugin and len(versions) > 1:
            out.append(f"plugins.roles: {plugin} is pinned to more than one version ({', '.join(sorted(versions))}); one plugin, one pin")
    return out


def pinned(all_roles=None):
    """`{plugin: version}` the roles are pinned to."""
    out = {}
    for r in (roles() if all_roles is None else all_roles).values():
        if plugin_of(r) and VERSION.match(str(r.get("version") or "")):
            out[plugin_of(r)] = str(r["version"])
    return out


def installed(rows, repo=REPO):
    """`{plugin: version}` this checkout loads, from the rows of `claude plugin list --json`:
    enabled, no load error, installed for this checkout or for the whole machine."""
    out = {}
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("id") or not row.get("enabled") or row.get("errors"):
            continue
        path = row.get("projectPath")
        if path and os.path.realpath(path) != os.path.realpath(repo):
            continue
        plugin = str(row["id"]).split("@", 1)[0]
        version = str(row.get("version") or "")
        if VERSION.match(version) or plugin not in out:
            out[plugin] = version
    return out


def doctor_lines(rows, all_roles=None):
    """`[{check, ok, tail}]`: the data itself, then one line per plugin the roles use.

    `rows` is `claude plugin list --json` (None when claude is not here). A plugin that is
    not installed in this checkout is not a failure: its roles fall back, and the line says
    how many. A plugin installed at another version than its pin is: the briefs were read
    against the pinned one."""
    all_roles = roles() if all_roles is None else all_roles
    bad = problems(all_roles)
    lines = [{"check": "plugin roles", "ok": not bad,
              "tail": "; ".join(bad)[:400] if bad else f"{len(all_roles)} roles, each with a brief and a fallback"}]
    have = installed(rows) if rows is not None else None
    for plugin, version in sorted(pinned(all_roles).items()):
        n = sum(1 for r in all_roles.values() if plugin_of(r) == plugin)
        check = f"plugin {plugin} (pinned {version})"
        if have is None:
            lines.append({"check": check, "ok": True, "tail": f"claude is not on PATH; {n} role(s) cannot be checked"})
        elif plugin not in have:
            lines.append({"check": check, "ok": True, "tail": f"not installed in this checkout; its {n} role(s) fall back"})
        elif have[plugin] != version:
            lines.append({"check": check, "ok": False,
                          "tail": f"installed {have[plugin] or 'at an unknown version'}, roles pinned to {version}: read the briefs "
                                  f"against the new version, then move the pin (plugins.roles in brand.json)"})
        else:
            lines.append({"check": check, "ok": True, "tail": f"installed {version}; {n} role(s)"})
    return lines


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    all_roles = roles()
    for name, r in all_roles.items():
        print(f"{name:<18} {r.get('use', ''):<30} {r.get('kind', ''):<6} {r.get('version', ''):<7} {r.get('brief', '')}")
    bad = problems(all_roles)
    for line in bad:
        print(f"PROBLEM  {line}")
    if "--check" in argv:
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
