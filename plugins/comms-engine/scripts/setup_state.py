#!/usr/bin/env python3
"""
setup_state.py - where a checkout stands on the way from clone to running engine.

Why: the dashboard is the first page a new operator opens, and before the
engine runs it has nothing to show. This module turns the facts the console
already knows (is the brand named, which required secrets are missing, is the
corpus root set, has memory been written, are the jobs loaded) into an ordered
list of steps with the exact command each one needs, so the page can show
"3 of 6" and the next command instead of an empty engine. Nothing here runs
doctor or a job: every check is a file test or a keychain presence check, so
the block costs milliseconds and the page builds on a machine with nothing yet.

The steps are the ones docs/01-setup.md walks through, in that order. A step
is `optional` when the engine runs without it (the publish targets only matter
once the autopilot is meant to send); optional steps never block `complete`.

    engine setup_state          # the steps, one line each
    engine setup_state --json
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
REPO = paths.instance()
PLACEHOLDER_SLUG = "acme"
#: The sentence templates/voice.md carries until a brief writes the voice.
UNWRITTEN_MARK = "Not written yet"


def steps(*, slug, name, missing_secrets, corpus_root, voice_text, local_cfg,
          jobs, placeholder=PLACEHOLDER_SLUG):
    """The ordered steps from the facts. Pure: every input is a value."""
    named = bool(slug) and slug != placeholder
    required_jobs = [j for j in jobs if not j.get("optional") and not _is_helper(j)]
    loaded = [j for j in required_jobs if j.get("loaded")]
    corpus_ok = bool(corpus_root) and os.path.isdir(os.path.expanduser(corpus_root))
    memory_ok = bool(voice_text) and UNWRITTEN_MARK not in voice_text
    cycle_ok = bool((local_cfg or {}).get("cycle")) or bool(loaded)
    out = [
        {"id": "name", "title": "Name the brand", "done": named,
         "detail": f"{name} ({slug})" if named else "still carries the placeholder brand",
         "command": 'engine init --slug <slug> --name "<Name>"',
         "chat": "/engine init",
         "why": "The schedule labels, the environment prefix, the keychain service and the first row of streams.md all derive from this one block."},
        {"id": "secrets", "title": "Add the keys", "done": not missing_secrets,
         "detail": ("missing: " + ", ".join(missing_secrets)) if missing_secrets else "every required secret resolves",
         "command": f"engine secrets --set {missing_secrets[0] if missing_secrets else 'NAME'}",
         "chat": "/engine secrets",
         "why": "Into the login keychain, never a file. twitterapi.io first (listening), then the channel keys when the brand posts."},
        {"id": "corpus", "title": "Point at the strategy corpus", "done": corpus_ok,
         "detail": corpus_root if corpus_ok else ("root not found: " + corpus_root if corpus_root else "no corpus root set"),
         "command": "engine setup corpus --root <path>",
         "chat": "/engine setup corpus",
         "why": "The decks and prose the memory is read from. Per machine, in engine.local.json."},
        {"id": "memory", "title": "Write the memory from the corpus", "done": memory_ok,
         "detail": "voice.md carries a voice" if memory_ok else "the voice is not written yet; nothing is drafted until it is",
         "command": "claude  # then /corpus-cycle, review the brief, /corpus-update --apply",
         "chat": "/corpus-cycle",
         "why": "Tighten-only, from the brand's own briefs. A person reads the brief before --apply."},
        {"id": "cycle", "title": "Set the rhythm: budget, slots, quiet hours", "done": cycle_ok,
         "detail": "cycle section in engine.local.json" if (local_cfg or {}).get("cycle") else ("defaults in use" if cycle_ok else "not reviewed yet"),
         "command": "engine setup cycle",
         "chat": "/engine setup cycle",
         "why": "Ends with a dry run: drafts and gate verdicts appear, nothing is paid for and nothing is loaded."},
        {"id": "jobs", "title": "Switch the schedule on", "done": bool(loaded) and len(loaded) == len(required_jobs),
         "detail": f"{len(loaded)} of {len(required_jobs)} loaded",
         "command": "engine enable corpus && engine enable cycle",
         "chat": "/engine enable cycle",
         "why": "Through install.sh, one schedule at a time. Nothing is posted until the autopilot cell in streams.md says otherwise."}
    ]
    return out


def _is_helper(job):
    """nosleep keeps the Mac awake; it is loaded with the others but is not a step."""
    return (job.get("name") or job.get("job") or job.get("label") or "").endswith("nosleep")


def block(step_list):
    required = [s for s in step_list if not s.get("optional")]
    done = [s for s in required if s["done"]]
    nxt = next((s for s in step_list if not s["done"] and not s.get("optional")), None)
    return {"complete": len(done) == len(required), "done": len(done), "total": len(required),
            "next": nxt["id"] if nxt else None, "steps": step_list}


# --- the facts, read from this checkout ------------------------------------------------

def missing_required_secrets(required):
    """secrets.py --check <names>: the names it could not resolve (exit 1), [] when all resolve."""
    if not required:
        return []
    proc = subprocess.run([sys.executable, os.path.join(HERE, "secrets.py"), "--check", *required],
                          capture_output=True, text=True, timeout=30)
    if proc.returncode == 0:
        return []
    out = (proc.stdout or "") + (proc.stderr or "")
    missing = [ln.split(":")[0].strip() for ln in out.splitlines() if "NOT FOUND" in ln or ": ERROR" in ln]
    return missing or list(required)


def _jobs_cfg(config):
    """engine.json's jobs, through config.jobs() where the checkout has it."""
    if hasattr(config, "jobs"):
        return config.jobs()
    with open(os.path.join(ENGINE, "engine.json")) as f:
        return json.load(f).get("jobs", [])


def read_facts(brand=None):
    """`brand` overrides config.brand() for a checkout that has no brand block yet."""
    sys.path.insert(0, HERE)
    import config  # noqa: E402
    cfg_jobs = _jobs_cfg(config)
    try:
        import jobs_status  # noqa: E402
        jobs = jobs_status.rows()
    except Exception:  # noqa: BLE001 - a machine without launchctl
        jobs = [{"job": j.get("label") or j.get("name", ""), "loaded": False, "optional": j.get("optional", False)} for j in cfg_jobs]
    for j in jobs:
        j.setdefault("optional", any(x.get("optional") and (x.get("label") == j.get("job") or x.get("name") == j.get("job")) for x in cfg_jobs))
    b = brand or config.brand()
    local_path = paths.local_json()
    local_cfg = {}
    if os.path.exists(local_path):
        try:
            with open(local_path) as f:
                local_cfg = json.load(f)
        except (OSError, ValueError):
            local_cfg = {}
    voice_path = os.path.join(REPO, ".atelier", "memory", "voice.md")
    voice = open(voice_path).read() if os.path.exists(voice_path) else ""
    try:
        missing = missing_required_secrets(list(config.cfg("secrets.required", []) or []))
    except Exception:  # noqa: BLE001 - keychain unreachable: report, never fail the build
        missing = list(config.cfg("secrets.required", []) or [])
    return dict(slug=b["slug"], name=b["name"], missing_secrets=missing,
                corpus_root=str(config.cfg("corpus.root", "") or ""), voice_text=voice, local_cfg=local_cfg,
                jobs=jobs)


def current(brand=None):
    return block(steps(**read_facts(brand)))


def main(argv):
    b = current()
    if "--json" in argv:
        print(json.dumps(b, indent=2))
        return 0
    for s in b["steps"]:
        mark = "done" if s["done"] else ("opt " if s.get("optional") else "todo")
        print(f"{mark}  {s['title']:<34} {s['detail']}")
        if not s["done"]:
            print(f"        $ {s['command']}")
    print(f"setup: {b['done']} of {b['total']}" + ("" if b["complete"] else f", next: {b['next']}"))
    return 0 if b["complete"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
