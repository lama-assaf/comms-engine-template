#!/usr/bin/env python3
"""
render.py - engine.json's jobs into launchd plists for this checkout.

  engine render --out <dir> [--repo <path>] [--config-dir <path>] [--only <label>]

Replaces __REPO__ (the instance), __ENGINE__ (the engine's root) and __HOME__ in
the `jobs` of engine.json (one level up), and writes <label>.plist files whose
program is `~/.local/bin/comms-engine runjob <label>` (the shim `engine shim
--install` writes), with PATH, COMMS_ENGINE_INSTANCE, the job's env (and
CLAUDE_CONFIG_DIR when given; COMMS_ENGINE_HOME for an engine outside the plugin
cache, a development checkout) in its environment. Labels come
from scripts/config.py (`<brand.label_prefix>.<job name>`), the one place they
are derived. The installer calls this; the tests call it against a temp dir.
Pure: no launchctl here, and no per-machine schedule: a schedule is a tracked
change, never an engine.local.json override (config.jobs reads engine.json's
jobs only; the brand block may be overridden there, so a machine can carry
its own label prefix if it must).
"""
import argparse
import json
import os
import plistlib
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
JOBS = os.path.join(ENGINE, "engine.json")
CLT = "/Library/Developer/CommandLineTools"
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
import config  # noqa: E402
import paths  # noqa: E402
REPO_DEFAULT = paths.instance()
#: The fixed path every job runs (schedule/comms_engine_shim.py, written by `engine shim --install`).
SHIM = os.path.join(".local", "bin", "comms-engine")


def shim_path(home):
    return os.path.join(home, SHIM)


def in_plugin_cache(engine=ENGINE, home=None):
    """True when this engine is a version Claude Code installed (its root moves on every update)."""
    home = home or os.path.expanduser("~")
    roots = [os.environ.get("CLAUDE_CODE_PLUGIN_CACHE_DIR") or "",
             os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude"), "plugins")]
    real = os.path.realpath(engine)
    return any(r and (real + os.sep).startswith(os.path.realpath(os.path.expanduser(r)) + os.sep) for r in roots)


def load_jobs(path=None):
    """The schedule half of engine.json: `{"path": ..., "jobs": [...]}`, each job with its label derived."""
    path = path or config.ENGINE_JSON  # resolved when called, so a redirected config.py is followed
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    return {"path": spec["path"], "jobs": config.jobs(path), "brand": config.brand(path)}


def _sub(value, repo, home):
    if isinstance(value, str):
        return value.replace("__REPO__", repo).replace("__HOME__", home).replace("__ENGINE__", ENGINE)
    if isinstance(value, list):
        return [_sub(v, repo, home) for v in value]
    if isinstance(value, dict):
        return {k: _sub(v, repo, home) for k, v in value.items()}
    return value


def render_job(job, spec, repo, home, config_dir=None):
    brand = spec.get("brand") or config.brand()
    # Every job but caffeinate runs `comms-engine runjob <label>`: the shim at a path
    # that never moves finds the installed engine at each start (the plugin's root
    # changes on every update), and runjob.py reads engine.json and the script's
    # text and hands it to zsh, which a protected folder (~/Desktop) still allows.
    direct = job["program"][0] in ("/usr/bin/caffeinate",)
    program = _sub(job["program"], repo, home) if direct else [shim_path(home), "runjob", job["label"]]
    plist = {
        "Label": job["label"],
        "ProgramArguments": program,
        "RunAtLoad": bool(job.get("keep_alive", False)),
    }
    env = {"PATH": _sub(spec["path"], repo, home), "HOME": home, paths.ENV: repo,
           **_sub(job.get("env", {}), repo, home)}
    if not in_plugin_cache(home=home):
        # a development checkout: its engine stays where it is, so the shim is told where
        env["COMMS_ENGINE_HOME"] = ENGINE
    if config_dir:
        env["CLAUDE_CONFIG_DIR"] = config_dir
    # Apple's git refuses to run under an Xcode whose licence nobody accepted in
    # a launchd session; pointing the jobs at the Command Line Tools sidesteps it.
    if os.path.isdir(CLT):
        env["DEVELOPER_DIR"] = CLT
    plist["EnvironmentVariables"] = env
    if job.get("calendar"):
        plist["StartCalendarInterval"] = job["calendar"]
    if job.get("keep_alive"):
        plist["KeepAlive"] = True
    if job.get("throttle"):
        plist["ThrottleInterval"] = int(job["throttle"])
    # launchd opens the stdout file itself, and a path under ~/Desktop or
    # ~/Documents is refused by the folder protection (the job then exits 78,
    # EX_CONFIG, before the first line). So the job's own output goes to
    # ~/Library/Logs/<slug>-comms/<label>.log (config.log_dir); the scripts still
    # write their state logs inside the repo (the job's `log` in engine.json says where).
    log = os.path.join(home, "Library", "Logs", f"{brand['slug']}-comms", job["label"] + ".log")
    plist["StandardOutPath"] = log
    plist["StandardErrorPath"] = log
    return plist


def render_all(out_dir, repo=REPO_DEFAULT, home=None, config_dir=None, only=None, jobs_path=None):
    home = home or os.path.expanduser("~")
    spec = load_jobs(jobs_path)
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for job in spec["jobs"]:
        if only and job["label"] != only:
            continue
        plist = render_job(job, spec, repo, home, config_dir)
        path = os.path.join(out_dir, job["label"] + ".plist")
        with open(path, "wb") as f:
            plistlib.dump(plist, f, sort_keys=False)
        written.append(path)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--out", required=True)
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--config-dir", default=os.environ.get("CLAUDE_CONFIG_DIR") or None)
    ap.add_argument("--only")
    a = ap.parse_args(argv)
    for p in render_all(a.out, a.repo, config_dir=a.config_dir, only=a.only):
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
