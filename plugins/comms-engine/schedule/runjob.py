#!/usr/bin/env python3
"""
runjob.py - what every launchd job runs, behind the shim.

  ~/.local/bin/comms-engine runjob <label>     the plist's program (render.py)
  engine runjob <label>                        the same, by hand

The shim finds the installed engine and starts `engine runjob`, with the
instance in COMMS_ENGINE_INSTANCE. Why a launcher here as well: macOS folder
protection lets launchd run `python3` against a repository under ~/Desktop (or
~/Documents) once that interpreter has been allowed, but refuses to exec a shell
script that lives there, and refuses a shell asked to read it (`Operation not
permitted`, exit 126, or `can't open input file`, exit 127). So python3 reads
the job from engine.json and the script's text, and hands that text to /bin/zsh
as a `-c` argument, started in the instance with COMMS_ENGINE_INSTANCE and
COMMS_ENGINE_HOME set (and <ENV_PREFIX>REPO, for anything that still reads it),
so nothing depends on `$0`. A job whose program is already `/bin/zsh -lc ...` or
`python3 ...` is run as written.

Best fix on a new machine: keep the instance outside ~/Desktop, ~/Documents and
~/Downloads (for example ~/work/<brand>); the launcher then has nothing to work
around and still works. A hosted instance must (`engine host-check`).

  engine runjob --show social-engine   # the argv, runs nothing (a label works too)
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
JOBS = os.path.join(ENGINE, "engine.json")
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
import config  # noqa: E402
import paths  # noqa: E402
REPO = paths.instance()


def load_jobs(path=None):
    """The schedule half of engine.json, labels derived; engine.local.json never changes a job."""
    path = path or config.ENGINE_JSON  # resolved when called, so a redirected config.py is followed
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    return {"path": spec["path"], "jobs": config.jobs(path)}


def _sub(v, repo, home):
    return v.replace("__REPO__", repo).replace("__HOME__", home).replace("__ENGINE__", ENGINE) if isinstance(v, str) else v


def command_for(job, repo=REPO, home=None):
    """(argv, script_text_or_None): what to exec for this job.

    A program whose first element is a shell script under the repo is turned
    into `/bin/zsh -c <text> zsh <args...>` with the script's text read here;
    everything else is passed through with placeholders substituted."""
    home = home or os.path.expanduser("~")
    prog = [_sub(p, repo, home) for p in job["program"]]
    # `/bin/zsh <script> args` or `<script> args`
    script = None
    if prog and prog[0] in ("/bin/zsh", "/bin/bash") and len(prog) > 1 and prog[1].endswith(".sh"):
        script, args = prog[1], prog[2:]
    elif prog and prog[0].endswith(".sh"):
        script, args = prog[0], prog[1:]
    if script is None:
        return prog, None
    with open(script, encoding="utf-8") as f:
        text = f.read()
    return ["/bin/zsh", "-c", text, "zsh", *args], text


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    show = "--show" in argv
    labels = [a for a in argv if not a.startswith("--")]
    if len(labels) != 1:
        print(__doc__)
        return 2
    spec = load_jobs()
    job = next((j for j in spec["jobs"] if labels[0] in (j["label"], j["name"])), None)
    if job is None:
        print(f"runjob: no job {labels[0]} in engine.json", file=sys.stderr)
        return 2
    cmd, _ = command_for(job)
    env = dict(os.environ, **{config.env_name_for("REPO"): REPO, paths.ENV: REPO, "COMMS_ENGINE_HOME": ENGINE},
               **{k: _sub(v, REPO, os.path.expanduser("~")) for k, v in (job.get("env") or {}).items()})
    if show:
        print(json.dumps([c if len(c) < 200 else c[:120] + " ..." for c in cmd], indent=1))
        return 0
    os.chdir(REPO)
    return subprocess.call(cmd, env=env, cwd=REPO)


if __name__ == "__main__":
    sys.exit(main())
