#!/usr/bin/env python3
"""
guard_skills.py - the PreToolUse hook on the Skill tool: a paid skill opens only behind a recorded sign-off.

Why: `motion:generate` makes paid calls (generated images, voice, music). It used to be denied
outright in `.claude/settings.json`, which also meant the one time an owner wants a generated
shot there was no way to allow it but to edit the deny list. It is now refused here unless a
person recorded a cost sign-off, the way the X price sign-offs work: a dated note in the
engine's configuration, scoped to what was accepted.

  params.motion.generate_signoff   engine.json ships it empty; a person records it per machine:
      engine config set motion.generate_signoff \
          "2026-11-20: owner, up to 20 USD of generated shots for the launch film"

Empty, or `false`, `no`, `off`, `none`, `0`: refused. Anything else: allowed, and the note is
shown so the session sees what was signed. `motion:post` stays denied in settings.json and is
refused here too. Every other skill passes untouched.

It fails closed for the skills it guards: a hook that cannot read the sign-off refuses the paid
skill, with the reason. It reads engine.json and engine.local.json with `json` alone, so it runs
under the system Python a hook gets and never imports the engine.

  echo '{"tool_name": "Skill", "tool_input": {"skill": "motion:generate"}}' | python3 guard_skills.py
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
#: skill -> why it never opens
NEVER = {"motion:post": "motion:post publishes to a channel channels.send() does not know; nothing leaves this repository that way"}
#: skill -> (the configuration key of its sign-off, what it costs)
SIGNED = {"motion:generate": ("motion.generate_signoff", "it makes paid calls for generated images, voice and music")}
OFF = ("", "0", "false", "no", "off", "none")


def skill_name(tool_input):
    """The skill a Skill call names, lower-case, without a leading slash."""
    raw = ""
    if isinstance(tool_input, dict):
        raw = tool_input.get("skill") or tool_input.get("name") or tool_input.get("command") or ""
    return str(raw).strip().lstrip("/").split()[0].lower() if str(raw).strip() else ""


def signoff(key, engine=None):
    """The recorded sign-off for a dotted `params` key: engine.local.json over engine.json. '' when none."""
    engine = engine or ENGINE
    value = ""
    for name in ("engine.json", "engine.local.json"):
        path = os.path.join(engine, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            node = json.load(f).get("params") or {}
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, str):
            value = node.strip()
        elif node is not None:
            value = ""  # a sign-off is a dated note in words, never a bare true
    return "" if value.lower() in OFF else value


def verdict(tool_name, tool_input, engine=None):
    """`(why, note)`: `why` is the refusal, or None; `note` is the sign-off a guarded skill runs under."""
    if tool_name != "Skill":
        return None, None
    name = skill_name(tool_input)
    if name in NEVER:
        return NEVER[name], None
    if name not in SIGNED:
        return None, None
    key, cost = SIGNED[name]
    try:
        note = signoff(key, engine)
    except Exception as exc:  # the sign-off could not be read: a paid skill does not run on a guess
        return f"{name} is refused: its cost sign-off could not be read ({exc}).", None
    if not note:
        return (f"{name} is refused: {cost}, and no cost sign-off is recorded. A person records one, dated and scoped, "
                f"with: engine config set {key} \"<date>: <role>, <what and how much>\""), None
    return None, note


def main() -> int:
    try:
        data = json.load(sys.stdin)
        tool_name = data.get("tool_name")
        tool_input = data.get("tool_input") or {}
    except Exception:  # not a call this hook can read: it is not a guarded skill call either
        return 0
    if tool_name != "Skill":
        return 0
    why, note = verdict(tool_name, tool_input)
    if why:
        print(why, file=sys.stderr)
        return 2
    if note:
        print(f"cost sign-off on record: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
