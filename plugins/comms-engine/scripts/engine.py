#!/usr/bin/env python3
"""
engine.py - the engine console: one CLI over the eight scheduled jobs.

Why: the engine had eight launchd jobs, two install scripts, a dozen dry-run
commands and parameters in four places, and a new operator had to read three
chapters to know which command to run. This is the one module that calls
`launchctl`, `install.sh`, `runjob.py` and the dry runs; the curses screen
(engine_tui.py) and the `/engine` command import its functions or call its
CLI, so each behaviour exists once. Every action prints the exact command it
runs (`$ ...`) first, so the console teaches the CLI.

Nothing here posts, publishes or loads a job on its own: `run` is a dry run
unless `--live` is given, `--live` is refused outright for the autopilot, the
stream and caffeinate, `enable` goes through schedule/install.sh, and `setup`
writes engine.local.json and ends with a dry run, never with a load.

  engine init                                  # on a terminal: a few questions, then brand.json
  engine init --slug <slug> --name "<Name>" [--narrator ..] [--x @handle] [--linkedin ..] [--label-prefix ..] [--env-prefix ..] [--keychain-service ..]
  engine init --from <brand.json>              # set a clone up from a setup file, no questions
  engine apply [--check]                       # render the streams.md tables from brand.json
  engine validate          # brand.json checked: the key and the fix per problem
  engine status [--json]
  engine run <job> [--dry|--live]
  engine run <workflow or chain> [--live]      # scripts/workflow.py; dry unless --live
  engine enable <job> | disable <job>
  engine logs <job> [-n 40]
  engine results [--since 36h|7d|ISO] [--json]
  engine doctor
  engine runtime          # the python3 the scheduled jobs start, and whether it imports every pin
  engine eval gate [--live | --status]          # the reviewers on the labelled drafts; --live is paid
  engine export-published <file>
  engine setup <job> [--<key> <value>]...
  engine setup composio <stream> [--dry]
  engine onboard-stream <slug> [...]
  engine secrets [--set NAME]
  engine plugins [--prepare | --headless-settings]
  engine host-check                 # the office Mac: path, pmset, auto login, Tailscale Serve, token, denylist, backup
  engine new-instance <dir> [--from <brand.json>]   # a brand's own instance repository, the memory as shapes
  engine shim [--install]       # ~/.local/bin/comms-engine, the fixed path every launchd job runs

<job> is a console alias (corpus, cycle, autopilot, engagement, score,
claims-check, x-stream, nosleep), the job's name in engine.json (corpus-cycle,
social-engine, ...) or its launchd label (<brand.label_prefix>.<name>,
com.acme.social-engine for the shipped brand).

`init` writes brand.json at the repository root, the one setup file (the
brand, each stream, the drivers, which jobs are on, the plugin roles), and
never edits engine.json, which stays as shipped defaults. It then renders the
three tables of .atelier/memory/streams.md from the file (`apply`), renames
the brand cells of handles.md's own channels and the example claim id in
claims.md, and prints the first commands. A checkout that has a registry kept
by hand and no brand.json gets one imported from it, cell for cell.
Idempotent; a slug outside [a-z][a-z0-9-]{1,23} is refused. `apply --check`
is doctor's line: exit 1 when streams.md and brand.json disagree.
"""
import datetime as dt
import importlib.util
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
REPO = paths.instance()
STATE = paths.state()
#: How a command is written for a person and spawned here: `engine <name>` (bin/engine);
#: run_cmd turns it into the interpreter call (paths.expand), so nothing needs it on PATH.
INSTALL_SH = os.path.join(ENGINE, "schedule", "install.sh")
LAUNCH_AGENTS = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents")
STREAMS_MD = os.path.join(REPO, ".atelier", "memory", "streams.md")

sys.path.insert(0, HERE)
import config  # noqa: E402
import jobs_status  # noqa: E402

#: Where launchd writes each job's own stdout (config.log_dir: ~/Library/Logs/<slug>-comms).
LAUNCHD_LOGS = config.log_dir()
#: Console alias -> the job's name in engine.json. The two differ where the
#: alias is the word an operator says (`cycle`) and the name is the job's.
JOB_NAMES = {
    "corpus": "corpus-cycle",
    "cycle": "social-engine",
    "autopilot": "autopilot",
    "engagement": "engagement",
    "score": "score",
    "claims-check": "claims-check",
    "x-stream": "x-stream",
    "x-poll": "x-poll",
    "inbound": "inbound",
    "control": "control",
    "backup": "backup",
    "nosleep": "nosleep",
}
#: Console alias -> launchd label, derived from the brand's label_prefix once at
#: import; every subcommand accepts the alias, the job name or the label.
SHORT = {alias: config.label(name) for alias, name in JOB_NAMES.items()}
#: Short name -> the `params` section the job's script reads (none for nosleep).
PARAMS_SECTION = {
    "corpus": "corpus", "cycle": "cycle", "autopilot": "autopilot", "engagement": "engagement",
    "score": "score", "claims-check": "claims_check", "x-stream": "x_stream", "x-poll": "x_stream",
    "inbound": "inbound",
}
#: `run --live` is refused here: the autopilot sends, the stream is billed per
#: match, caffeinate is launchd's to hold. The PreToolUse hook would refuse the
#: first anyway; this says so before anything is spawned.
LIVE_REFUSED = ("autopilot", "x-stream", "x-poll", "inbound", "control", "nosleep")

#: The dry form of each job: argv lists relative to the repo root. engage.py has
#: no --dry-run flag, so the engagement job's dry form is its read-only `due`
#: listing. nosleep has nothing to dry-run. The corpus form gets `--root` from
#: config at call time (dry_commands), so it reads the corpus the 06:30 job reads.
DRY_FORMS = {
    "corpus": [["engine", "corpus_sweep", "--only-todo"]],
    "cycle": [["engine", "plan_queries", "--dry-run"],
              ["engine", "listen", "--dry-run"]],
    "autopilot": [["engine", "autopilot", "run", "--dry"]],
    "engagement": [["engine", "engage", "due"]],
    "score": [["engine", "score", "--dry-run"],
              ["engine", "metrics", "--dry-run"]],
    "claims-check": [["engine", "claims_check", "--dry-run"]],
    "x-stream": [["engine", "x_stream", "rules"]],
    "x-poll": [["engine", "x_stream", "poll", "--dry-run"]],
    "inbound": [["engine", "inbound", "poll", "--dry-run"]],
    "control": [["engine", "control", "status"]],
    "backup": [["engine", "backup", "--dry"]],
    "nosleep": [],
}

def suite_root(engine=ENGINE):
    """The template checkout the engine sits in (its marketplace root), where its suite runs; None
    for an engine Claude Code installed, which carries no checkout to test against."""
    root = os.path.dirname(os.path.dirname(engine))
    return root if os.path.isfile(os.path.join(root, ".claude-plugin", "marketplace.json")) else None


def _shown(path):
    """A path as a person reads it from the instance: relative inside it, absolute outside."""
    rel = os.path.relpath(path, REPO)
    return path if rel.startswith("..") else rel


def doctor_checks(slug):
    """CLAUDE.md "How work is verified", in that order, then config.py show; the
    guardrails line asks about the brand's own stream. doctor() appends
    secrets.py --check <required...> at call time."""
    suite = [f"python3 -m unittest discover {_shown(os.path.join(ENGINE, 'tests'))}"] if suite_root() else []
    return suite + [
        "engine listen --dry-run",
        "engine x_stream rules",
        "engine desk_sync --pull --dry-run",
        "engine memory --list",
        "engine state_check",
        "engine gate_lint",
        "engine claims_check --dry-run",
        "engine plan_queries --dry-run",
        "engine x_metrics --dry-run",
        "engine score --dry-run",
        "engine metrics --dry-run",
        f"engine guardrails --stream {slug} --channel X",
        "engine session_brief --dry-run",
        "engine config show",
        "engine validate",
        "engine apply --check",
        "engine runtime",
    ]


DOCTOR_CHECKS = doctor_checks(config.brand()["slug"])
#: Checks whose exit 1 is an answer, not a fault: guardrails.py says "may the
#: brand send now" and exits 1 outside the sending window; x_stream.py rules
#: exits 1 with what the stream still lacks (an own X handle in handles.md, the
#: key); secrets.py --check exits 1 when a keychain item is not seeded yet,
#: which doctor reports with the missing names rather than failing (a fresh
#: machine has none). Exit 2 is still a failure for all three.
def info_checks(checks):
    return {c for c in checks if c.startswith(("engine guardrails ", "engine x_stream rules"))}


INFO_CHECKS = info_checks(DOCTOR_CHECKS)
INFO_PREFIXES = ("engine secrets --check",)


def is_informational(cmd):
    """True for a check whose exit 1 is reported, not counted as failed."""
    return cmd in INFO_CHECKS or cmd.startswith(INFO_PREFIXES)
DOCTOR_TIMEOUT = 300
#: What the scripts import beyond the standard library, by import name; requirements.txt pins each.
PINNED_IMPORTS = ("yaml", "pdfplumber", "pdfminer", "pptx", "docx", "PIL")
_PROBE = ("import importlib.util, sys; print(sys.version.split()[0]); "
          "print(' '.join(n for n in sys.argv[1:] if importlib.util.find_spec(n) is None))")
SUITE_TIMEOUT = 600


class UnknownJob(KeyError):
    """A name that is neither a short name nor a label in engine.json."""


class Refused(RuntimeError):
    """A setup value the console will not write, or a live run it will not start."""


# --- the two seams every spawn goes through ------------------------------------

def run_cmd(argv, timeout=None, capture=False, cwd=REPO, env=None, stdin=None):
    """The one subprocess seam. Tests replace it so nothing real runs.

    Returns a CompletedProcess; a missing binary or a timeout comes back as a
    CompletedProcess with returncode 127 / 124 and the reason in stderr, so a
    caller prints one line instead of a traceback.
    """
    argv = paths.expand(argv) or list(argv)
    try:
        return subprocess.run(argv, timeout=timeout, capture_output=capture, text=True, cwd=cwd,
                              env=env, stdin=stdin)
    except FileNotFoundError as e:
        return subprocess.CompletedProcess(argv, 127, stdout="", stderr=f"not found: {e.filename or argv[0]}")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, stdout="", stderr=f"timed out after {timeout}s")


def run_launchctl(args, timeout=20):
    """The ONE function that spawns launchctl. Tests monkeypatch it; bootstrap,
    bootout and kickstart never run in a test."""
    return run_cmd(["launchctl", *list(args)], timeout=timeout, capture=True)


def _say(cmd):
    """Print the exact command an action is about to run."""
    print(f"$ {cmd}", flush=True)


def _shell(argv):
    return " ".join(a if re.fullmatch(r"[\w./:=@-]+", a) else repr(a) for a in argv)


# --- names ---------------------------------------------------------------------

def label_for(name):
    """`cycle`, `social-engine` or `com.acme.social-engine` -> the label; unknown raises UnknownJob."""
    if name in SHORT:
        return SHORT[name]
    if name in SHORT.values():
        return name
    try:
        return config.job(name)["label"]
    except config.ConfigError:
        raise UnknownJob(f"unknown job {name!r}; one of {', '.join(SHORT)}") from None


def short_for(label):
    """The short name of a label; a label without one keeps its label."""
    for k, v in SHORT.items():
        if v == label:
            return k
    return label


def _label_and_short(name):
    label = label_for(name)
    return label, short_for(label)


# --- status ----------------------------------------------------------------------

def _engine_secrets():
    """scripts/secrets.py loaded by path, so the stdlib `secrets` never shadows it."""
    spec = importlib.util.spec_from_file_location("engine_secrets", os.path.join(HERE, "secrets.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def secrets_status(names=None, env=None):
    """[{name, required, present, backend}] for the configured secret names; never a value."""
    sec = _engine_secrets()
    required = list(config.cfg("secrets.required", [], env=env) or [])
    optional = list(config.cfg("secrets.optional", [], env=env) or [])
    wanted = list(names) if names else required + optional
    out = []
    for n in wanted:
        backend = None
        try:
            for label, fn in sec._BACKENDS:
                if fn(n):
                    backend = label
                    break
        except Exception as e:  # a locked keychain is a reason, not a crash
            backend = None
            out.append({"name": n, "required": n in required, "present": False, "backend": None,
                        "error": str(e)[:120]})
            continue
        out.append({"name": n, "required": n in required, "present": backend is not None, "backend": backend})
    return out


def _plugin_loaded(row, repo=REPO):
    """True when one row of `claude plugin list --json` is a plugin this checkout loads:
    enabled, no load error, and installed for this checkout or for the whole machine."""
    if not isinstance(row, dict) or not row.get("id") or not row.get("enabled") or row.get("errors"):
        return False
    path = row.get("projectPath")
    return not path or os.path.realpath(path) == os.path.realpath(repo)


def _claude_plugin_list():
    """The plugins this checkout loads, or None when claude is not here or cannot say.

    Read from `claude plugin list --json`, never the plain listing: that one also prints a
    plugin that failed to load, which is how a plugin installed for another checkout was
    once reported as installed here."""
    if not shutil.which("claude"):
        return None
    proc = run_cmd(["claude", "plugin", "list", "--json"], timeout=30, capture=True)
    try:
        rows = json.loads(proc.stdout or "")
    except ValueError:
        return None
    if not isinstance(rows, list):
        return None
    return {r["id"] for r in rows if _plugin_loaded(r)}


def plugins_status(env=None):
    """[{name, installed}] with installed True/False, or None when claude is absent."""
    names = list(config.cfg("plugins.names", [], env=env) or [])
    listed = _claude_plugin_list()
    return [{"name": n, "installed": None if listed is None else (n in listed)} for n in names]


def headless_settings(env=None):
    """The settings a scheduled `claude -p` adds (cycle.sh passes them as --settings): every
    plugin in `plugins.interactive_only` switched off for that run alone. A plugin a person
    drives, whose session hook may install packages, has no place in a run nobody watches."""
    names = list(config.cfg("plugins.interactive_only", [], env=env) or [])
    return {"enabledPlugins": {n: False for n in names}}


def last_cycle(log=os.path.join(STATE, "schedule.log"), env=None):
    """{at, budget_usd, exit} from the last `=== social-cycle` block of schedule.log.

    cycle.sh closes a block with `=== social-cycle exit N ===`; that N is the
    exit. A block without one (an older run, or one still running) falls back
    to the heuristic: 1 when the block carries an `Error:` or `Traceback`
    line, 0 otherwise. None when the log is missing."""
    budget = config.cfg("cycle.budget_usd", None, env=env)
    if not os.path.exists(log):
        return {"at": None, "budget_usd": budget, "exit": None}
    at, failed, seen, code = None, False, False, None
    with open(log, encoding="utf-8", errors="replace") as f:
        for line in f:
            m_exit = re.match(r"=== social-cycle exit (\d+) ===", line)
            if m_exit:
                if seen:
                    code = int(m_exit.group(1))
                continue
            m = re.match(r"=== social-cycle (\S+)", line)
            if m:
                at, failed, seen, code = m.group(1), False, True, None
            elif seen and re.match(r"(Error|ERROR|Traceback)\b", line.strip()):
                failed = True
    if not seen:
        return {"at": None, "budget_usd": budget, "exit": None}
    return {"at": at, "budget_usd": budget, "exit": code if code is not None else (1 if failed else 0)}


def workflow_rows():
    """One row per workflow (last run, result, what waits for a person, cost today); [] when the
    runner or its data cannot be read, so status never fails on it."""
    try:
        import workflow
        return workflow.status_rows()
    except Exception:
        return []


def status(now=None, env=None):
    """The console's status: the jobs table, the secrets, the plugins, the last cycle, the workflows."""
    return {
        "jobs": jobs_status.rows(now, loaded=loaded_labels()),
        "secrets": secrets_status(env=env),
        "plugins": plugins_status(env=env),
        "last_cycle": last_cycle(env=env),
        "workflows": workflow_rows(),
    }


def status_rows(now=None):
    """The jobs table alone, as jobs_status.rows() gives it (the TUI's left pane)."""
    return jobs_status.rows(now, loaded=loaded_labels())


def status_unhealthy(st):
    """Labels that are stale or not loaded, nosleep and optional jobs excluded."""
    optional = {j["label"] for j in config.jobs() if j.get("optional")} | {SHORT["nosleep"]}
    return [r["job"] for r in st["jobs"]
            if r["job"] not in optional and (r["state"].startswith("stale") or r["state"] == "not loaded")]


def status_lines(st):
    """The jobs_status.py table plus the three summary lines."""
    rows = st["jobs"]
    lines = []
    if rows:
        w = max(len(r["job"]) for r in rows)
        lines.append(f"{'job':<{w}}  {'last run':<17}  {'state':<22}  what")
        for r in rows:
            lines.append(f"{r['job']:<{w}}  {(r['last_run'] or '-'):<17}  {r['state']:<22}  {r['what']}")
    req = [s for s in st["secrets"] if s["required"]]
    present = [s["name"] for s in req if s["present"]]
    missing = [s["name"] for s in req if not s["present"]]
    tail = "; ".join(x for x in (", ".join(present), f"missing {', '.join(missing)}" if missing else "") if x)
    lines.append(f"secrets   {len(present)}/{len(req)} present ({tail})")
    pl = st["plugins"]
    if pl and all(p["installed"] is None for p in pl):
        lines.append(f"plugins   unknown (claude not on PATH; {', '.join(p['name'] for p in pl)})")
    else:
        inst = [p["name"] for p in pl if p["installed"]]
        lines.append(f"plugins   {len(inst)}/{len(pl)} installed ({', '.join(inst) or '-'})")
    lc = st["last_cycle"]
    ex = "?" if lc["exit"] is None else lc["exit"]
    lines.append(f"last cycle {lc['at'] or 'none'}  budget {lc['budget_usd']} USD  exit {ex}")
    ran = [r for r in st.get("workflows") or [] if r.get("last")]
    if ran:
        import workflow
        lines += workflow.status_lines(ran)
    return lines


# --- run, enable, disable, logs -------------------------------------------------

def dry_commands(name):
    """The dry-run argv list for a job (relative to the repo root); [] for nosleep."""
    _, short = _label_and_short(name)
    cmds = [list(c) for c in DRY_FORMS.get(short, [])]
    if short == "corpus":
        # corpus_sweep.py's own default root names one machine; the configured
        # root is what corpus_cycle_daily.sh passes, so the dry run reads the same corpus
        root = str(config.cfg("corpus.root", "", local=config.LOCAL_JSON))
        cmds = [[*c[:2], "--root", root, *c[2:]] for c in cmds]
    return cmds


def live_command(name):
    """The argv runjob.py runs for `--live`."""
    label, _ = _label_and_short(name)
    return ["engine", "runjob", label]


def run(name, live=False, timeout=None):
    """Run a job: its dry form (the default), or the real job through runjob.py with live=True.

    Prints `$ <command>` before each spawn and streams the output. Returns the
    exit code; 3 when `--live` is refused for autopilot, x-stream or nosleep.
    A name that is a workflow or a chain of engine.json and not a job goes to
    scripts/workflow.py, dry unless `--live`."""
    try:
        label, short = _label_and_short(name)
    except UnknownJob:
        import workflow
        kind = "chain" if name in workflow.chains() else "run" if name in workflow.specs() else None
        if kind is None:
            raise
        argv = [kind, name] + ([] if live else ["--dry"])
        _say(f"engine workflow {' '.join(argv)}")
        return workflow.main(argv)
    if live:
        if short in LIVE_REFUSED:
            print(f"run --live {short}: refused; {label} is started by launchd only "
                  f"(enable {short}), and the PreToolUse hook would refuse a hand-run post anyway.")
            return 3
        argv = live_command(label)
        _say(_shell(argv))
        return run_cmd(argv, timeout=timeout).returncode
    cmds = dry_commands(label)
    if not cmds:
        what = re.split(r"[:;(]", config.job(label).get("what", ""))[0].strip()
        print(f"{short}: nothing to dry-run ({label} is {what}; launchd holds it)")
        return 0
    rc = 0
    for argv in cmds:
        _say(_shell(argv))
        code = run_cmd(argv, timeout=timeout).returncode
        if short == "corpus" and code == 1 and "corpus_sweep" in argv[1]:
            # the sweep's exit 1 is an answer (work is pending), not a fault
            print("pending work found (corpus_sweep.py --only-todo exits 1 when sources wait; "
                  "the scheduled job would run /corpus-cycle on them)")
            code = 0
        rc = rc or code
    return rc


def installed_config_dir(label):
    """CLAUDE_CONFIG_DIR as the installed plist under ~/Library/LaunchAgents carries it, or None."""
    path = os.path.join(LAUNCH_AGENTS, f"{label}.plist")
    try:
        with open(path, "rb") as f:
            return plistlib.load(f).get("EnvironmentVariables", {}).get("CLAUDE_CONFIG_DIR") or None
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None


def running_pid(label):
    """The PID `launchctl list` shows for a label, or None when it is idle or not loaded."""
    proc = run_launchctl(["list"], timeout=10)
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] == label and parts[0] != "-":
            return parts[0]
    return None


def enable(name):
    """Render and (re)load one job through schedule/install.sh --only <label>.

    install.sh adds CLAUDE_CONFIG_DIR to the plist only when its shell has it,
    so a reload from a plain Terminal would silently move a job that runs
    `claude -p` to the default ~/.claude login: the installed plist's value is
    carried over when the environment lacks one. install.sh also boots the job
    out before it bootstraps, which would kill a run in progress, so a calendar
    job with a live PID is refused (exit 1); a keep_alive job restarts by design."""
    label, short = _label_and_short(name)
    pid = running_pid(label)
    if pid and not config.job(label).get("keep_alive"):
        print(f"enable {short}: refused; {label} is running now (pid {pid}); "
              f"install.sh would boot it out mid-run. Enable it once the run has ended.")
        return 1
    env = None
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or installed_config_dir(label)
    if config_dir and not os.environ.get("CLAUDE_CONFIG_DIR"):
        env = {**os.environ, "CLAUDE_CONFIG_DIR": config_dir}
    carried = f"CLAUDE_CONFIG_DIR={config_dir}" if config_dir else "CLAUDE_CONFIG_DIR unset: the job runs under ~/.claude"
    _say(f"engine install --only {label}  ({carried})")
    proc = run_cmd(["/bin/bash", INSTALL_SH, "--only", label], timeout=120, env=env)
    return proc.returncode


def disable(name):
    """Boot one job out of launchd; the plist stays under ~/Library/LaunchAgents."""
    label, _ = _label_and_short(name)
    target = f"gui/{os.getuid()}/{label}"
    _say(f"launchctl bootout {target}")
    proc = run_launchctl(["bootout", target])
    print(f"{'booted out' if proc.returncode == 0 else 'not loaded'} {label}")
    return 0


def loaded_labels():
    """The labels under the brand's prefix that launchctl has loaded, through run_launchctl."""
    proc = run_launchctl(["list"], timeout=10)
    prefix = config.brand()["label_prefix"] + "."
    return {line.split()[-1] for line in (proc.stdout or "").splitlines()
            if line.split() and line.split()[-1].startswith(prefix)}


def log_paths(name):
    """(repo log or None, launchd log) for a job."""
    label, _ = _label_and_short(name)
    rel = config.job(label).get("log")
    repo_log = os.path.join(REPO, rel) if rel else None
    return repo_log, os.path.join(LAUNCHD_LOGS, f"{label}.log")


def _tail(path, n):
    with open(path, encoding="utf-8", errors="replace") as f:
        return [line.rstrip("\n") for line in f][-n:]


def logs(name, n=40):
    """The last N lines of the job's own log and of launchd's, each under a `==` header.

    An empty list means neither file exists (the CLI exits 1)."""
    out = []
    for path in [p for p in log_paths(name) if p]:
        if os.path.exists(path):
            out.append(f"== {path} (last {n}) ==")
            out.extend(_tail(path, n))
    return out


# --- doctor ------------------------------------------------------------------------

def runtime(path=None, env=None):
    """The python3 a scheduled job starts (the first on the jobs' own PATH, engine.json `path`)
    and whether it imports every pinned package: `{ok, python, version, missing, line}`.

    The doctor's own python3 may differ from the jobs': a package manager that links a newer
    Python ahead of the one holding the pins breaks every job while the console still works."""
    path = config.cfg("path", "", env=env) if path is None else path
    py = shutil.which("python3", path=path)
    if not py:
        return {"ok": False, "python": None, "version": None, "missing": list(PINNED_IMPORTS),
                "line": f"runtime: no python3 on the jobs' PATH ({path})"}
    proc = run_cmd([py, "-c", _PROBE, *PINNED_IMPORTS], timeout=60, capture=True)
    out = (proc.stdout or "").splitlines()
    if proc.returncode != 0 or not out:
        return {"ok": False, "python": py, "version": None, "missing": list(PINNED_IMPORTS),
                "line": f"runtime: {py} did not run ({(proc.stderr or '').strip()[-160:]})"}
    version, missing = out[0].strip(), (out[1].split() if len(out) > 1 else [])
    where = f"{py} -> {os.path.realpath(py)} ({version})"
    if missing:
        return {"ok": False, "python": py, "version": version, "missing": missing,
                "line": f"runtime: the jobs' python3 {where} cannot import {', '.join(missing)}, so every job would fail; "
                        f"install the pins for it ({py} -m pip install -r requirements.txt) or link a Python that has them"}
    return {"ok": True, "python": py, "version": version, "missing": [],
            "line": f"runtime: the jobs' python3 {where} imports every pinned package"}


def doctor(checks=None, timeout=DOCTOR_TIMEOUT, env=None):
    """Run every verification command and the suite; [{check, ok, seconds, tail}] per command."""
    if checks is None:
        required = list(config.cfg("secrets.required", [], env=env) or [])
        checks = DOCTOR_CHECKS + [f"engine secrets --check {' '.join(required)}".rstrip()]
    results = []
    for cmd in checks:
        argv = cmd.split()
        t0 = time.monotonic()
        # stdin closed: session_brief.py drains the hook's stdin JSON when it is
        # not a terminal, and an inherited pipe nobody closes would hold it
        suite = "unittest" in cmd and suite_root()
        # the suite tests the template it ships in, whatever instance this doctor answers for
        proc = run_cmd(argv, timeout=SUITE_TIMEOUT if "unittest" in cmd else timeout, capture=True,
                       stdin=subprocess.DEVNULL,
                       **({"cwd": suite, "env": {**{k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"},
                                                 paths.ENV: suite}} if suite else {}))
        seconds = round(time.monotonic() - t0, 1)
        ok = proc.returncode == 0 or (is_informational(cmd) and proc.returncode == 1)
        # the suite reports on stderr; a failing script's last stderr line is the reason
        source = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        tail = source.splitlines()[-1] if source else ""
        if cmd.startswith(INFO_PREFIXES) and proc.returncode == 1:
            # every name secrets.py could not find, not just the last line
            missing = [ln.split(":")[0] for ln in source.splitlines() if "NOT FOUND" in ln or ": ERROR" in ln]
            tail = "missing: " + ", ".join(missing) if missing else tail
        results.append({"check": cmd, "ok": ok, "seconds": seconds, "tail": tail})
    return results


def doctor_lines(results):
    lines = []
    for r in results:
        if r["ok"] and is_informational(r["check"]) and r["tail"]:
            lines.append(f"ok    {r['seconds']:>5.1f}s  {r['check']}  -- {r['tail']}")
        elif r["ok"] and r.get("note") and r["tail"]:
            lines.append(f"ok    {r['seconds']:>5.1f}s  {r['check']}  -- {r['tail']}")
        elif r["ok"]:
            lines.append(f"ok    {r['seconds']:>5.1f}s  {r['check']}")
        else:
            lines.append(f"FAIL  {r['seconds']:>5.1f}s  {r['check']}  -- {r['tail']}")
    n_ok = sum(1 for r in results if r["ok"])
    lines.append(f"doctor: {n_ok} ok, {len(results) - n_ok} failed")
    return lines


# --- composio channels: doctor lines and setup --------------------------------------

def channel_doctor_results():
    """The composio doctor lines in the shape doctor() returns: [{check, ok, seconds, tail, note}].

    Per stream: whether its key sees the recorded auth configs, its channels (connected,
    active, handle against the channels cell) and its X read driver. Read-only: it lists connections
    and asks an ACTIVE account who it is, nothing else.
    """
    import channels
    out = []
    for line in channels.doctor_report():
        out.append({"check": line["check"], "ok": line["ok"], "seconds": 0.0, "tail": line["tail"], "note": True})
    return out


def _plugin_rows():
    """The rows of `claude plugin list --json`, or None when claude is not here or cannot say."""
    if not shutil.which("claude"):
        return None
    proc = run_cmd(["claude", "plugin", "list", "--json"], timeout=30, capture=True)
    try:
        rows = json.loads(proc.stdout or "")
    except ValueError:
        return None
    return rows if isinstance(rows, list) else None


def engine_version(home=None):
    """The version of the engine running this command: its own .claude-plugin/plugin.json; "" when unreadable."""
    try:
        with open(os.path.join(home or ENGINE, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            return str(json.load(f).get("version") or "").strip()
    except (OSError, ValueError, AttributeError):
        return ""


def engine_version_result(pinned=None, loaded=None):
    """The doctor line for brand.json engine.version against the loaded plugin: FAIL on a mismatch,
    as roles.py fails a plugin role on another version; a brand.json that pins nothing is reported."""
    loaded = engine_version() if loaded is None else loaded
    pinned = str(config.cfg("engine.version", "") or "").strip() if pinned is None else pinned
    check = "comms-engine version (brand.json engine.version)"
    if not pinned:
        return {"check": check, "ok": True, "seconds": 0.0, "note": True,
                "tail": f"not pinned: write engine.version {loaded or '<version>'} in brand.json"}
    if pinned != loaded:
        return {"check": check, "ok": False, "seconds": 0.0,
                "tail": f"brand.json pins {pinned}, the loaded plugin is {loaded or 'unreadable'}: "
                        f"claude plugin update comms-engine@comms-engine, or move the pin after reading the release"}
    return {"check": check, "ok": True, "seconds": 0.0, "note": True, "tail": f"{loaded}, as pinned"}


#: The Claude Code subscription token (`claude setup-token`) lasts a year; doctor warns this long after it was set.
CLAUDE_TOKEN = "CLAUDE_CODE_OAUTH_TOKEN"
TOKEN_WARN_DAYS = 330
TOKEN_LIFE_DAYS = 365


def claude_token_result(set_on=None, today=None):
    """The doctor line for the host's Claude token, from the date `engine secrets --set` recorded
    (params.host.claude_token_set): a warning from day 330, 35 days before it ends; FAIL after a year. No date, no token
    kept here: claude signs in with its own login, reported not failed."""
    check = "claude token (params.host.claude_token_set)"
    raw = str(config.cfg("host.claude_token_set", "") or "").strip() if set_on is None else set_on
    today = today or dt.date.today()
    if not raw:
        return {"check": check, "ok": True, "seconds": 0.0, "note": True,
                "tail": "none recorded: claude signs in with its own login (a host keeps one: docs/07-hosting.md)"}
    try:
        age = (today - dt.date.fromisoformat(raw[:10])).days
    except ValueError:
        return {"check": check, "ok": False, "seconds": 0.0,
                "tail": f"{raw!r} is not a date: engine config set host.claude_token_set YYYY-MM-DD"}
    renew = "claude setup-token, then engine secrets --set " + CLAUDE_TOKEN
    if age > TOKEN_LIFE_DAYS:
        return {"check": check, "ok": False, "seconds": 0.0, "tail": f"set {raw}, {age} days ago: expired; {renew}"}
    if age >= TOKEN_WARN_DAYS:
        return {"check": check, "ok": True, "seconds": 0.0, "note": True,
                "tail": f"WARN set {raw}: expires in {TOKEN_LIFE_DAYS - age} days; {renew}"}
    return {"check": check, "ok": True, "seconds": 0.0, "note": True, "tail": f"set {raw}, {age} days ago"}


#: Folders launchd may not read on its own (macOS folder protection): a hosted instance lives elsewhere.
PROTECTED = ("Desktop", "Documents", "Downloads")


def parse_pmset(text):
    """`pmset -g` as {setting: int} for the settings host-check reads; a setting not shown is absent."""
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"^\s*(sleep|autorestart|disksleep|womp)\s+(\d+)", line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def serve_targets(text, port):
    """The hostnames `tailscale serve status --json` proxies to the control page's port."""
    try:
        web = (json.loads(text or "{}") or {}).get("Web") or {}
    except ValueError:
        return []
    wanted = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    return sorted({h.rsplit(":", 1)[0].lower().rstrip(".") for h, v in web.items() if isinstance(v, dict)
                   for handler in (v.get("Handlers") or {}).values()
                   if isinstance(handler, dict) and str(handler.get("Proxy") or "").rstrip("/") in wanted})


def host_checks(root=None, home=None, user=None, serve_name=None, roles=None):
    """`engine host-check`: one ok/FAIL line per thing docs/07-hosting.md sets up on the office Mac:
    the instance's path, pmset, automatic login, Tailscale Serve and its role map, the Claude token,
    the private denylist and the backup remote. Reads only; every command goes through run_cmd."""
    import getpass
    root, home = os.path.realpath(root or REPO), home or os.path.expanduser("~")
    user = user or getpass.getuser()
    out = []

    def line(check, ok, tail):
        out.append({"check": check, "ok": bool(ok), "seconds": 0.0, "tail": tail, "note": True})

    under = [d for d in PROTECTED if (root + os.sep).startswith(os.path.realpath(os.path.join(home, d)) + os.sep)]
    line("instance path", not under, f"under ~/{under[0]}, which launchd may not read: move the instance (~/work/<brand>)"
         if under else root)

    proc = run_cmd(["pmset", "-g"], timeout=20, capture=True)
    pm = parse_pmset(proc.stdout if proc.returncode == 0 else "")
    ok = pm.get("sleep") == 0 and pm.get("autorestart") == 1
    line("pmset: never sleep, restart after a power failure", ok,
         f"sleep {pm.get('sleep', '?')}, autorestart {pm.get('autorestart', 'not shown')}"
         + ("" if ok else ": sudo pmset -a sleep 0 autorestart 1"))

    who = run_cmd(["defaults", "read", "/Library/Preferences/com.apple.loginwindow", "autoLoginUser"], timeout=20, capture=True)
    vault = run_cmd(["fdesetup", "status"], timeout=20, capture=True)
    auto = (who.stdout or "").strip() if who.returncode == 0 else ""
    if "FileVault is On" in (vault.stdout or ""):
        line("automatic login", False, "FileVault is on, which turns automatic login off: the owner's choice (docs/07-hosting.md)")
    elif not auto:
        line("automatic login", False, "off: System Settings > Users & Groups > Automatically log in as this user")
    else:
        line("automatic login", auto == user, "as this user" if auto == user else "as another user, not the one the jobs run as")

    if serve_name is None or roles is None:
        import control
        got_name, got_roles = control.door_settings()
        serve_name = got_name if serve_name is None else serve_name
        roles = got_roles if roles is None else roles
    port = int(config.cfg("control.port", 4320) or 4320)
    tailscale = shutil.which("tailscale") or "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
    proc = run_cmd([tailscale, "serve", "status", "--json"], timeout=20, capture=True)
    targets = serve_targets(proc.stdout if proc.returncode == 0 else "", port)
    if not serve_name:
        line("tailscale serve", False, "no serve name: engine config set host.serve_name <machine>.<tailnet>.ts.net")
    elif serve_name not in targets:
        line("tailscale serve", False, f"{serve_name} is not served to 127.0.0.1:{port}: tailscale serve --bg {port}")
    elif not roles:
        line("tailscale serve", False, "no tailnet login is mapped to a role: host.roles in engine.local.json")
    else:
        line("tailscale serve", True, f"{serve_name} -> 127.0.0.1:{port}, {len(roles)} login(s) mapped to a role")

    token = (secrets_status([CLAUDE_TOKEN]) or [{}])[0]
    dated = claude_token_result()
    recorded = bool(str(config.cfg("host.claude_token_set", "") or "").strip())
    if not token.get("present"):
        line("claude token", False, f"not kept: claude setup-token, then engine secrets --set {CLAUDE_TOKEN}")
    elif not recorded:
        line("claude token", False, "kept, but its date is not recorded: engine config set host.claude_token_set YYYY-MM-DD")
    else:
        line("claude token", dated["ok"], dated["tail"])

    private = os.path.join(root, ".atelier", "memory", "handles.private.md")
    present = os.path.isfile(private) and os.path.getsize(private) > 0
    line("private denylist", present, "handles.private.md is here" if present else
         "handles.private.md is missing: copy it by hand over Tailscale, never through git (the gate blocks without it)")

    up = run_cmd(["git", "-C", root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], timeout=20, capture=True)
    upstream = (up.stdout or "").strip() if up.returncode == 0 else ""
    push = config.cfg("backup.push", False) is True
    if not upstream:
        line("backup remote", False, "the branch has no upstream: git push -u <remote> <branch>, with the Mac's deploy key")
    else:
        reach = run_cmd(["git", "-C", root, "ls-remote", "--exit-code", upstream.split("/", 1)[0], "HEAD"], timeout=30, capture=True,
                        env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
        if reach.returncode != 0:
            line("backup remote", False, f"{upstream} cannot be reached with this Mac's key: check the deploy key")
        elif not push:
            line("backup remote", False, f"{upstream} answers, but push is off: engine config set backup.push true")
        else:
            line("backup remote", True, f"{upstream} answers; the daily backup pushes there")
    return out


def host_check_lines(results):
    lines = doctor_lines(results)
    lines[-1] = lines[-1].replace("doctor:", "host-check:", 1)
    return lines


SHIM_SOURCE = os.path.join(ENGINE, "schedule", "comms_engine_shim.py")


def shim_path(home=None):
    return os.path.join(home or os.path.expanduser("~"), ".local", "bin", "comms-engine")


def shim_state(home=None):
    """(path, state): `missing`, `current` or `out of date` against the shim this engine ships."""
    target = shim_path(home)
    with open(SHIM_SOURCE, encoding="utf-8") as f:
        want = f.read()
    try:
        with open(target, encoding="utf-8") as f:
            have = f.read()
    except OSError:
        return target, "missing"
    return target, "current" if have == want and os.access(target, os.X_OK) else "out of date"


def shim(install=False, home=None):
    """`engine shim [--install]`: the fixed path launchd runs. Dry by default: says where it is and
    whether it is this engine's; --install writes it (0755) and changes nothing else."""
    target, state = shim_state(home)
    if not install:
        print(f"{target}: {state}" + ("" if state == "current" else "  -> engine shim --install"))
        return 0 if state == "current" else 1
    if state == "current":
        print(f"{target}: current, nothing to write")
        return 0
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".tmp"
    with open(SHIM_SOURCE, encoding="utf-8") as src, open(tmp, "w", encoding="utf-8") as out:
        out.write(src.read())
    os.chmod(tmp, 0o755)
    os.replace(tmp, target)
    print(f"wrote {target} (it finds the installed engine at each start; `comms-engine --where` says which)")
    return 0


def plugin_doctor_results(rows=None):
    """The plugin-role doctor lines in the shape doctor() returns (scripts/roles.py): the roles as
    data, then one line per plugin, FAIL when an installed plugin is not the version its roles are
    pinned to. A plugin not installed in this checkout is reported, not failed: its roles fall back."""
    import roles
    rows = _plugin_rows() if rows is None else rows
    return [{"check": ln["check"], "ok": ln["ok"], "seconds": 0.0, "tail": ln["tail"], "note": True}
            for ln in roles.doctor_lines(rows)]


def setup_composio(stream, dry=False):
    """Say what is connected for each channel in the stream's `streams.md` row and, for each
    channel not yet connected, the dashboard steps that connect it.

    The stream's Composio project key (`COMPOSIO_API_KEY`, scoped by stream) lists the project's
    connected accounts (a read); a stream without a key is refused. Nothing is linked or written
    from here: connecting is an OAuth sign-in the owner does in the Composio dashboard, so the
    steps are printed, with the auth config id recorded for the channel. Nothing is written either
    way; `dry` only leaves out the doctor lines at the end. Returns the exit code (0 when every channel is connected or the steps
    were printed).
    """
    import channels
    try:
        channels.memory.stream(stream)
    except channels.memory.SharedMemoryError as exc:
        print(f"engine: {exc}", file=sys.stderr)
        return 1
    if not channels.stream_channels(stream):
        print(f"engine: {stream} has no channel Composio serves in its streams.md channels cell", file=sys.stderr)
        return 1
    try:
        plan = channels.link_plan(stream)
    except channels.MissingComposioKey as exc:
        print(f"engine: {exc}", file=sys.stderr)
        if not channels.composio_setup(stream)[0]:
            print(f"engine: {stream} is not set up for Composio; missing: a Composio API key "
                  f"of its own (the secret named above). Nothing was checked.", file=sys.stderr)
        return 1
    except channels.ChannelError as exc:
        print(f"engine: {exc}", file=sys.stderr)
        return 1
    for key, alias, auth_config, linked in plan:
        if linked:
            print(f"{key}: already connected as {alias!r}")
            continue
        cfg = f" (auth config {auth_config})" if auth_config else " (record its id as params.channels.auth_config.%s.%s in engine.json)" % (stream, key)
        print(f"{key}: not connected. In the Composio dashboard:")
        print(f"  1. open the {channels.composio_org(stream) or stream} project > Connected accounts")
        print(f"  2. connect a {key} account under the {stream} {key} auth config{cfg}")
        print(f"  3. sign in as the {stream} {key} account (the handle in streams.md), not a personal one")
        print(f"  4. name the account {alias!r} if the dashboard offers a name; otherwise copy its id into "
              f"params.channels.account_id.{stream}.{key} in engine.json")
    if not dry:
        print("")
        print("\n".join(doctor_lines(channel_doctor_results())))
    return 0


# --- setup ---------------------------------------------------------------------------

#: Per job: (flag key, config path, prompt). The default is the current value
#: through config.cfg, so the questionnaire always shows what the job reads now.
QUESTIONS = {
    "corpus": [
        ("root", "corpus.root", "the corpus root (checked for existence)"),
        ("include", "corpus.include", "folders under the root to read ([] = all; comma-separated)"),
        ("exclude", "corpus.exclude", "folders under the root to skip (comma-separated)"),
        ("extra_roots", "corpus.extra_roots", "blind-spot roots added to the sweep (comma-separated)"),
        ("max", "corpus.max", "sources per run"),
        ("apply", "corpus.apply", "apply memory edits (false = plan only)"),
        ("budget_usd", "corpus.budget_usd", "budget cap of the headless run, USD"),
    ],
    "cycle": [
        ("drafts", "cycle.drafts", "drafts per run"),
        ("listen", "cycle.listen", "listening on"),
        ("max_per_term", "cycle.max_per_term", "listen.py --max per term (never above 12)"),
        ("linkedin", "cycle.linkedin", "LinkedIn listening through Apify (paid; needs --linkedin-reason)"),
        ("budget_usd", "cycle.budget_usd", "budget cap per cycle, USD"),
        ("editor", "cycle.weekday_flags.editor", "the weekly editor on Monday"),
        ("slots", "cycle.weekday_flags.slots", "the blog slots on Friday"),
        ("readout", "cycle.weekday_flags.readout", "the monthly readout on the first weekday"),
    ],
    "autopilot": [
        ("grace_days", "autopilot.grace_days", "days a Ready row may be late and still go"),
        ("commit", "autopilot.commit", "run `autopilot.py commit` after `run`"),
    ],
    "engagement": [
        ("window_days", "engagement.window_days", "days after which an act's outcome is due"),
    ],
    "score": [
        ("x_metrics", "score.x_metrics", "x_metrics.py before score.py"),
        ("demand", "score.demand", "score.py --demand"),
        ("close_livetests", "score.close_livetests", "livetests.py close"),
    ],
    "claims-check": [
        ("state_check", "claims_check.state_check", "state_check.py"),
        ("dashboard", "claims_check.dashboard", "build_dashboard.py"),
    ],
    "x-stream": [
        ("rules_file", "x_stream.rules_file", "the themes file the rule plan is built from"),
        ("max_rules", "x_stream.max_rules", "rules at most"),
    ],
}
#: Flags a setup takes that are not written to engine.json.
EXTRA_FLAGS = {"cycle": ("linkedin_reason",)}
#: Keys setup records in engine.local.json that no job script reads yet (the
#: score and claims-check programs are fixed strings in engine.json; the sweep
#: takes no include/exclude; listen.py's --max and --linkedin come from the
#: /social-cycle command). setup says so beside each, so nobody believes a job
#: changed when only the file did. A key leaves this set when its reader lands.
INERT = {
    "corpus.include", "corpus.exclude", "corpus.extra_roots",
    "cycle.max_per_term", "cycle.linkedin",
    "autopilot.commit",
    "score.x_metrics", "score.demand", "score.close_livetests",
    "claims_check.state_check", "claims_check.dashboard",
    "x_stream.rules_file", "x_stream.max_rules",
}
INERT_NOTE = "; recorded, not read by any script yet"
#: Keys that hold a path: `~` is expanded before the write and the home prefix
#: is written as __HOME__, the placeholder config.py expands on read.
PATH_KEYS = {"corpus.root", "x_stream.rules_file"}


def _home_placeholder(value):
    home = os.path.expanduser("~")
    value = os.path.expanduser(str(value))
    if value == home:
        return "__HOME__"
    if value.startswith(home + os.sep):
        return "__HOME__" + value[len(home):]
    return value


def coerce(raw, like):
    """Type a flag or typed answer by the value it replaces."""
    if isinstance(raw, str):
        if isinstance(like, bool):
            v = raw.strip().lower()
            if v in ("1", "true", "yes", "on", "y"):
                return True
            if v in ("0", "false", "no", "off", "n"):
                return False
            raise Refused(f"{raw!r} is not yes/no")
        if isinstance(like, int) and not isinstance(like, bool):
            return int(raw)
        if isinstance(like, float):
            return float(raw)
        if isinstance(like, list):
            s = raw.strip()
            if s in ("", "[]"):
                return []
            if s.startswith("["):
                return json.loads(s)
            return [x.strip() for x in s.split(",") if x.strip()]
        return raw
    return raw


def _fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return ", ".join(map(str, v)) if v else "[]"
    return str(v)


def validate(short, key, value, answers):
    """The refusals: a corpus root that is not there, more than 12 per term, paid LinkedIn without a reason."""
    if short == "corpus" and key == "root" and not os.path.isdir(os.path.expanduser(str(value))):
        raise Refused(f"corpus root does not exist: {value}")
    if short == "cycle" and key == "max_per_term" and int(value) > 12:
        raise Refused("max_per_term above 12 is refused (CLAUDE.md: keep --max at or under 12 per term)")
    if short == "cycle" and key == "linkedin" and value is True and not answers.get("linkedin_reason"):
        raise Refused("linkedin true needs --linkedin-reason: it is paid and never on without one")


def _ask(prompt, default):
    try:
        raw = input(f"{prompt} [{_fmt(default)}]: ")
    except EOFError:
        return ""
    return raw.strip()


def _corpus_folders(root):
    """Folder -> (files, stages) from corpus_sweep.py --json, for the include/exclude question."""
    argv = ["engine", "corpus_sweep", "--root", root, "--json"]
    proc = run_cmd(argv, timeout=120, capture=True)
    if proc.returncode != 0:
        return {}
    try:
        rows = json.loads(proc.stdout)
    except ValueError:
        return {}
    out = {}
    for r in rows:
        folder = (r.get("folder") or ".").split("/")[0]
        n, stages = out.get(folder, (0, {}))
        stages[r.get("stage", "?")] = stages.get(r.get("stage", "?"), 0) + 1
        out[folder] = (n + 1, stages)
    return out


def _print_context(short, label, env=None):
    """What a setup shows but does not ask: the schedule, the channel rule, dry_run."""
    try:
        cal = config.job(label).get("calendar") or []
    except config.ConfigError:
        cal = []
    if cal:
        times = sorted({f"{c.get('Hour', 0):02d}:{c.get('Minute', 0):02d}" for c in cal})
        days = sorted({c["Weekday"] for c in cal if "Weekday" in c})
        when = ("Mon-Fri " if days == [1, 2, 3, 4, 5] else "daily " if not days else f"weekdays {days} ")
        print(f"schedule  {when}{', '.join(times)}  (a schedule changes in engine.json, then: engine.py enable {short})")
    if short == "autopilot":
        slug = config.brand()["slug"]
        try:
            import memory
            rule = memory.load_streams()[slug]["autopilot"]
        except Exception as e:  # the registry is read-only context here
            rule = f"(streams.md unreadable: {e})"
        print(f"channel rule (streams.md, {slug}): {rule}")
        print(f"to change it, add a decision under .atelier/memory/decisions/, set streams.{slug}.autopilot "
              "in brand.json and run engine.py apply")
    if short == "engagement":
        print(f"dry_run   {_fmt(config.cfg('engagement.dry_run', True, env=env))}  (always, until a decision file says otherwise)")
    if short == "x-stream":
        print("cost      an active rule is billed per matched post; `x_stream.py rules` plans, `--apply` arms")
    if short == "x-poll":
        print("cost      each poll is a paid search per rule (<= 12 posts each); `x_stream.py poll --dry-run` plans, nothing calls")
    if short == "inbound":
        print("cost      the X half is held until the price sign-off; the LinkedIn half needs a linked account; `inbound.py poll --dry-run` plans, nothing calls")
    if short == "score":
        d = os.path.join(STATE, "metrics-input")
        files = sorted(f for f in os.listdir(d) if f.endswith(".json")) if os.path.isdir(d) else []
        newest = max((os.path.getmtime(os.path.join(d, f)) for f in files), default=None)
        when = dt.datetime.fromtimestamp(newest).strftime("%Y-%m-%d") if newest else "-"
        print(f"reads     {len(files)} file(s) under state/metrics-input/ (newest {when}): numbers a person "
              f"read off the platform, the only full source until the platform logins exist")
        print("baseline  the median score of the stream's earlier records on the same platform and format "
              "once three exist; the band is below (< 0.75), baseline, above (> 1.25)")


def setup(job, answers=None, interactive=None, env=None, local=None):
    """The setup conversation for one job: show, ask (terminal only), write, dry-run.

    `answers` maps flag keys to values (strings allowed; typed by the current
    value). Headless, only the keys given are written; on a terminal every
    question is asked and an empty answer keeps the current value. Returns the
    dict of config paths written. Raises Refused on a value the console will
    not write, UnknownJob on a name it does not know."""
    answers = dict(answers or {})
    interactive = sys.stdin.isatty() if interactive is None else interactive
    local = local or config.LOCAL_JSON
    if job == "secrets":
        rc = secrets_cmd()
        return {"_exit": rc}
    if job == "plugins":
        rc = plugins_cmd()
        return {"_exit": rc}
    label, short = _label_and_short(job)
    questions = QUESTIONS.get(short)
    if questions is None:
        print(f"setup {short}: nothing to set up ({label} takes no parameters)")
        return {}
    # a typo'd flag is refused before anything is written, headless included
    known = {k for k, _, _ in questions} | set(EXTRA_FLAGS.get(short, ()))
    unknown = sorted(set(answers) - known)
    if unknown:
        raise Refused(f"setup {short}: unknown key(s) {', '.join(unknown)}; keys: {', '.join(sorted(known))}")
    shown = os.path.relpath(local, REPO) if os.path.abspath(local).startswith(REPO + os.sep) else local
    print(f"setup {short}  ({label}; writes {shown})")
    _print_context(short, label, env=env)

    if interactive and short == "corpus":
        root = os.path.expanduser(str(answers.get("root") or config.cfg("corpus.root", "", env=env)))
        if os.path.isdir(root):
            folders = _corpus_folders(root)
            if folders:
                print("folders under the root (files; stages):")
                for name, (n, stages) in sorted(folders.items()):
                    print(f"  {name:<40} {n:>4}  {', '.join(f'{k} {v}' for k, v in sorted(stages.items()))}")
        else:
            print(f"corpus root not mounted here: {root}")

    written = {}
    for key, path, prompt in questions:
        current = config.cfg(path, None, env=env, local=local)
        note = INERT_NOTE if path in INERT else ""
        if key in answers:
            value = coerce(answers[key], current)
            source = "flag"
        elif interactive:
            raw = _ask(f"{key}  {prompt}", current)
            if raw == "":
                print(f"{key} = {_fmt(current)} (kept{note})")
                continue
            value = coerce(raw, current)
            source = "answer"
        else:
            print(f"{key} = {_fmt(current)} (default{note})")
            continue
        validate(short, key, value, answers)
        if path in PATH_KEYS:
            value = _home_placeholder(value)
        config.set_local(path, value, local=local)
        written[path] = value
        print(f"{key} = {_fmt(value)} ({source}{note})")
    if written:
        print(f"wrote {shown}: {', '.join(written)}")
    else:
        print(f"nothing written to {shown}")

    print(f"dry run of {short}:")
    run(label, live=False)
    if label not in loaded_labels():
        print(f"not loaded; enable with: engine.py enable {short}")
    return written


# --- secrets, plugins, onboarding -----------------------------------------------------

def secrets_cmd(set_name=None):
    if set_name:
        if not sys.stdin.isatty():
            print(f"secrets --set {set_name}: needs a terminal (the value is typed at a hidden prompt)")
            return 2
        _say(f"engine secrets --set {set_name}")
        rc = run_cmd(["python3", os.path.join(HERE, "secrets.py"), "--set", set_name]).returncode
        if rc == 0 and set_name == CLAUDE_TOKEN:
            today = dt.date.today().isoformat()
            config.set_local("host.claude_token_set", today)
            print(f"host.claude_token_set: {today} (engine.local.json); doctor warns after {TOKEN_WARN_DAYS} days")
        return rc
    rows = secrets_status()
    rc = 0
    for s in sorted(rows, key=lambda s: not s["required"]):
        tag = "required" if s["required"] else "optional"
        if s["present"]:
            print(f"{s['name']}: present ({s['backend']}; {tag})")
        else:
            print(f"{s['name']}: MISSING  -> engine secrets --set {s['name']}  ({tag})")
            if s["required"]:
                rc = 1
    return rc


#: the per-machine Claude Code settings of this checkout (gitignored); `plugins --prepare` writes one key of it
SETTINGS_LOCAL = os.path.join(REPO, ".claude", "settings.local.json")
ATELIER_LOG = "ATELIER_LOG_DIR"


def atelier_log_wanted():
    """Where atelier's write log belongs on this machine: with the engine's own logs."""
    return os.path.join(config.log_dir(), "atelier")


def atelier_log_dir(settings_local=None):
    """Where atelier's write log goes now, or None for the plugin's default (~/.claude/atelier/logs)."""
    try:
        with open(settings_local or SETTINGS_LOCAL, encoding="utf-8") as f:
            return (json.load(f).get("env") or {}).get(ATELIER_LOG) or None
    except (OSError, ValueError, AttributeError):
        return None


def prepare_plugins(settings_local=None, log_dir=None):
    """Point atelier's write log (the path and size of every Write and Edit, appended by its
    PostToolUse hook) at the engine's own log folder instead of ~/.claude. One `env` key in
    the gitignored settings.local.json, which Claude Code hands to every hook, scheduled run
    or not; every other key of the file is kept. Returns (file, folder, changed)."""
    path = settings_local or SETTINGS_LOCAL
    want = log_dir or atelier_log_wanted()
    data = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except ValueError as e:
            raise Refused(f"{os.path.relpath(path, REPO)} is not JSON ({e}); nothing written")
        if not isinstance(data, dict) or not isinstance(data.get("env", {}), dict):
            raise Refused(f"{os.path.relpath(path, REPO)} does not hold a settings object; nothing written")
    if (data.get("env") or {}).get(ATELIER_LOG) == want:
        return path, want, False
    data.setdefault("env", {})[ATELIER_LOG] = want
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    return path, want, True


def plugins_cmd():
    market = config.cfg("plugins.marketplace", "")
    print(f"marketplace: {market or '(not set: config.py set plugins.marketplace <git url>, the marketplace the plugins come from)'}")
    scope = config.cfg("plugins.scope", "project")
    rows = plugins_status()
    rc = 0
    for p in rows:
        if p["installed"] is None:
            print(f"{p['name']}: unknown (claude not on PATH, or its `plugin list --json` cannot be read)")
        elif p["installed"]:
            print(f"{p['name']}: installed")
        else:
            print(f"{p['name']}: not installed  -> claude plugin install {p['name']} --scope {scope}")
            rc = 1
    if any(p["name"].startswith("atelier@") for p in rows):
        now, want = atelier_log_dir(), atelier_log_wanted()
        hint = "" if now == want else f"  -> engine plugins --prepare (keeps it at {want})"
        print(f"atelier write log: {now or '~/.claude/atelier/logs (the plugin default)'}{hint}")
    return rc


def onboard_stream(argv):
    """Forward to scripts/onboard.py (the onboarding builder's); a clear line when it is absent."""
    path = os.path.join(HERE, "onboard.py")
    if not os.path.exists(path):
        print("onboard-stream: scripts/onboard.py is not in this engine yet "
              "(the onboarding builder writes it); nothing done.")
        return 2
    spec = importlib.util.spec_from_file_location("onboard", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _say(f"engine onboard {' '.join(argv)}")
    return int(mod.main(list(argv)) or 0)


# --- init: the brand block -----------------------------------------------------------------

def _rename_cells(text, old, new):
    """Every table cell of a markdown file that equals `old` becomes `new`; prose is left alone.

    streams.md's three tables are joined by slug, so the registry row, the
    guardrails row and the pair-rule rows all follow one rename."""
    out = []
    for line in text.splitlines(keepends=True):
        if line.startswith("|") and old in line:
            cells = line.rstrip("\n").split("|")
            cells = [(" " + new + " ") if c.strip() == old else c for c in cells]
            line = "|".join(cells) + ("\n" if line.endswith("\n") else "")
        out.append(line)
    return "".join(out)


def _rename_claim_ids(text, old, new):
    """`C-<old>-<n>` becomes `C-<new>-<n>` wherever the register spells it: a
    claim id is an identifier notes cite, so the prose that names the example
    row follows too."""
    return re.sub(r"\bC-" + re.escape(old) + r"-(?=\d)", f"C-{new}-", text)


def _init_questions(flags, current, ask=None):
    """The few questions of a guided setup, each with the current value as its default; flags win."""
    ask = ask or _ask
    out = dict(flags)
    for key, prompt, default in (
            ("slug", "slug (lower-case, a letter first, such as acme)", current["slug"]),
            ("name", "name (as posts and notes carry it)", None),
            ("narrator", "narrator (the one register the brand speaks in; empty to set later)", ""),
            ("x", "X handle (@name; empty to collect later)", ""),
            ("linkedin", "LinkedIn page (linkedin.com/company/...; empty to collect later)", "")):
        if key in out:
            continue
        if key == "name":
            default = current["name"] if out.get("slug") == current["slug"] else str(out.get("slug", "")).capitalize()
        answer = ask(prompt, default)
        if answer not in (None, ""):
            out[key] = answer
    return out


def init(slug=None, name=None, label_prefix=None, env_prefix=None, keychain_service=None,
         engine_json=None, streams_md=None, local=None, handles_md=None, claims_md=None,
         from_file=None, narrator=None, x=None, linkedin=None):
    """Write brand.json and render the root stream everywhere it is keyed. engine.json is never edited.

    What it does:
      - brand.json's `brand` becomes the slug and name given (and any of
        label_prefix, env_prefix, keychain_service that was named); a checkout
        with no brand.json gets one imported from its streams.md first, so a
        registry kept by hand is carried over cell for cell;
      - the root stream's key, and every pair rule that points at it, follow
        the slug; `narrator`, `x` and `linkedin` fill the root stream's cells;
      - `from_file` takes a whole setup file instead: it is checked
        (config.brand_problems) and written as brand.json, no flag needed;
      - the three tables of .atelier/memory/streams.md are rendered from the
        file (brandfile.render), the `brand` cells of handles.md's own channels
        follow the name, and the example claim id `C-<slug>-0` in claims.md
        takes the new slug.
    handles.md and claims.md are looked for beside streams.md and skipped when
    absent. Run twice with the same flags it changes nothing; run with new
    values it renames from whatever the files hold now, so a brand can be
    re-stamped. Refuses a slug config.SLUG_RE does not accept (config.ConfigError).
    Returns {"brand", "previous", "changed": [paths]}."""
    import brandfile
    engine_json = engine_json or config.ENGINE_JSON
    streams_md = streams_md or STREAMS_MD
    memory_dir = os.path.dirname(streams_md)
    handles_md = handles_md or os.path.join(memory_dir, "handles.md")
    claims_md = claims_md or os.path.join(memory_dir, "claims.md")
    local = local or config.LOCAL_JSON
    old = config.brand(engine_json, local)
    base_doc = config._read_json(engine_json)
    md_text = None
    if os.path.exists(streams_md):
        with open(streams_md, encoding="utf-8") as f:
            md_text = f.read()
    if from_file:
        if not os.path.exists(from_file):
            raise Refused(f"init --from: {from_file} does not exist")
        try:
            with open(from_file, encoding="utf-8") as f:
                bdoc = json.load(f)
        except ValueError as e:
            raise Refused(f"init --from: {from_file} does not parse as JSON ({e})")
        problems = config.brand_problems(bdoc, base_doc)
        if problems:
            raise Refused("init --from: the file has problems, nothing written:\n  "
                          + "\n  ".join(f"{k}: {p}. Fix: {fix}" for k, p, fix in problems))
        new = config._brand_block(bdoc, base_doc)
    else:
        if not slug:
            raise Refused('init: --slug <slug> is required (and --name "<Name>" is what the notes will carry)')
        new = config.derive_brand(slug, name, label_prefix, env_prefix, keychain_service)
        bdoc = brandfile.read(engine_json)
        if not bdoc:
            bdoc = brandfile.from_streams_md(md_text, old) if md_text else {"brand": {}, "streams": {}}
        bdoc = brandfile.rename(bdoc, old, new)
        block = {"slug": new["slug"], "name": new["name"]}
        for key, given in (("label_prefix", label_prefix), ("env_prefix", env_prefix), ("keychain_service", keychain_service)):
            if given:
                block[key] = new[key]
        kept = bdoc.get("brand") if isinstance(bdoc.get("brand"), dict) else {}
        if kept.get("slug") == new["slug"]:
            block = {**{k: v for k, v in kept.items() if k not in ("slug", "name")}, **block}
        bdoc["brand"] = block
        root = bdoc["streams"].setdefault(new["slug"], {"name": new["name"], "owner": "unset", "autopilot": "nothing"})
        if narrator:
            root["narrator"] = narrator
        if x or linkedin:
            ch = root.get("channels") if isinstance(root.get("channels"), dict) else {}
            if x:
                ch["x"] = x if str(x).startswith("@") else "@" + str(x)
            if linkedin:
                ch["linkedin"] = linkedin
            root["channels"] = ch
        # the brand's own stream comes first, as the registry's first row
        bdoc["streams"] = {new["slug"]: root, **{k: v for k, v in bdoc["streams"].items() if k != new["slug"]}}
        ordered = {k: bdoc[k] for k in ("_about", "brand") if k in bdoc}
        if not isinstance(bdoc.get("engine"), dict) and engine_version():
            # a new setup file pins the engine that wrote it; an existing pin is never moved here
            bdoc["engine"] = {"version": engine_version()}
        ordered = {k: bdoc[k] for k in ("_about", "brand", "_engine_about", "engine") if k in bdoc}
        bdoc = {**ordered, **{k: v for k, v in bdoc.items() if k not in ordered}}
    changed = []
    wrote = brandfile.write(bdoc, engine_json)
    if wrote:
        changed.append(wrote)
    if md_text is not None:
        rendered = brandfile.render(md_text, bdoc, base_doc)
        if rendered != md_text:
            with open(streams_md, "w", encoding="utf-8") as f:
                f.write(rendered)
            changed.append(streams_md)
    if os.path.exists(handles_md):
        with open(handles_md, encoding="utf-8") as f:
            text = f.read()
        renamed = _rename_cells(text, old["name"], new["name"])
        if renamed != text:
            with open(handles_md, "w", encoding="utf-8") as f:
                f.write(renamed)
            changed.append(handles_md)
    if os.path.exists(claims_md):
        with open(claims_md, encoding="utf-8") as f:
            text = f.read()
        renamed = _rename_claim_ids(text, old["slug"], new["slug"])
        if renamed != text:
            with open(claims_md, "w", encoding="utf-8") as f:
                f.write(renamed)
            changed.append(claims_md)
    return {"brand": new, "previous": old, "changed": changed}


def apply_cmd(check=False, streams_md=None):
    """`engine.py apply [--check]`: render streams.md from brand.json, or say what differs."""
    import brandfile
    streams_md = streams_md or STREAMS_MD
    rel = os.path.relpath(streams_md, REPO)
    if check and not brandfile.read():
        print(f"ok  no brand.json: {rel} is kept by hand (engine.py init imports it)")
        return 0
    try:
        result = brandfile.apply(streams_md, check=check)
    except brandfile.Refused as e:
        raise Refused(f"apply: {e}")
    if not result["changed"]:
        print(f"ok  {rel} matches brand.json")
        return 0
    print("\n".join(result["diff"]))
    if check:
        print(f"{rel} is out of date with brand.json; run: engine apply")
        return 1
    print(f"wrote {rel} from brand.json")
    return 0


def init_lines(result):
    b = result["brand"]
    lines = [f"brand  {b['slug']}  ({b['name']}); labels {b['label_prefix']}.<job>, environment {b['env_prefix']}*, "
             f"keychain service {b['keychain_service']}"]
    if result["changed"]:
        lines.append("wrote  " + ", ".join(os.path.relpath(p, REPO) for p in result["changed"]))
    else:
        lines.append("nothing to write: brand.json and streams.md already carry this brand")
    lines += ["next:",
              "  engine doctor                    # what works on this machine, secrets reported not failed",
              "  engine setup corpus --root <dir>  # the strategy corpus the memory reads from",
              "  engine setup cycle               # drafts, budget, listening",
              "  engine secrets                   # the keychain items to seed",
              "  engine enable cycle              # load the first schedule, after a dry run"]
    return lines


def _init_flags(rest, interactive=None, ask=None):
    """The flags of `init`. With `--from` nothing else is needed; without a slug a terminal is asked
    the few questions and a headless run is refused."""
    flags = _setup_flags(rest)
    known = {"slug", "name", "label_prefix", "env_prefix", "keychain_service", "narrator", "x", "linkedin", "from"}
    unknown = sorted(set(flags) - known)
    if unknown:
        raise Refused(f"init: unknown flag(s) {', '.join('--' + u.replace('_', '-') for u in unknown)}")
    if "from" in flags:
        if flags["from"] == "true" or len(flags) > 1:
            raise Refused("init: --from <brand.json> takes a file and no other flag")
        return {"from_file": flags["from"]}
    if "slug" not in flags or flags["slug"] == "true":
        interactive = sys.stdin.isatty() if interactive is None else interactive
        if not interactive:
            raise Refused('init: --slug <slug> is required (and --name "<Name>" is what the notes will carry)')
        flags.pop("slug", None)
        flags = _init_questions(flags, config.brand(), ask)
        if not flags.get("slug"):
            raise Refused("init: no slug given, nothing written")
    return flags


# --- CLI ------------------------------------------------------------------------------------

def _setup_flags(rest):
    """`--root /x --max 4 --apply yes` -> {"root": "/x", "max": "4", "apply": "yes"}; a lone bool flag is true."""
    out = {}
    i = 0
    while i < len(rest):
        a = rest[i]
        if not a.startswith("--"):
            raise Refused(f"setup: unexpected argument {a!r}")
        key = a[2:].replace("-", "_")
        if "=" in key:
            key, val = key.split("=", 1)
            out[key] = val
            i += 1
            continue
        if i + 1 < len(rest) and not rest[i + 1].startswith("--"):
            out[key] = rest[i + 1]
            i += 2
        else:
            out[key] = "true"
            i += 1
    return out


def export_published(path, state_dir=None):
    """Write the website's feed (views.published_posts: the articles marked live) to `path`, for a
    site build while the control page is local. Writes that one file and nothing else."""
    import views
    data = views.published_posts(state_dir=state_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
    print(f"wrote {len(data['posts'])} published post(s) to {path}")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv else 2
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "init":
            result = init(**_init_flags(rest))
            print("\n".join(init_lines(result)))
            return 0
        if cmd == "apply":
            return apply_cmd(check="--check" in rest)
        if cmd == "validate":
            return config.validate_cli()
        if cmd == "runtime":
            r = runtime()
            print(r["line"], file=sys.stdout if r["ok"] else sys.stderr)
            return 0 if r["ok"] else 1
        if cmd == "status":
            st = status()
            if "--json" in rest:
                print(json.dumps(st, indent=2))
            else:
                print("\n".join(status_lines(st)))
            return 1 if status_unhealthy(st) else 0
        if cmd == "run":
            names = [a for a in rest if not a.startswith("--")]
            if len(names) != 1:
                print("usage: engine.py run <job> [--dry|--live]", file=sys.stderr)
                return 2
            return run(names[0], live="--live" in rest)
        if cmd in ("enable", "disable"):
            if len(rest) != 1:
                print(f"usage: engine.py {cmd} <job>", file=sys.stderr)
                return 2
            return enable(rest[0]) if cmd == "enable" else disable(rest[0])
        if cmd == "logs":
            names = [a for a in rest if not a.startswith("-") and not a.isdigit()]
            n = 40
            if "-n" in rest:
                i = rest.index("-n")
                if i + 1 >= len(rest) or not rest[i + 1].isdigit():
                    names = []  # a bare or non-numeric -n is a usage error
                else:
                    n = int(rest[i + 1])
            if len(names) != 1:
                print("usage: engine.py logs <job> [-n N]", file=sys.stderr)
                return 2
            lines = logs(names[0], n)
            if not lines:
                repo_log, ld = log_paths(names[0])
                print(f"no log yet: {repo_log or '(no repo log for this job)'}, {ld}")
                return 1
            print("\n".join(lines))
            return 0
        if cmd == "results":
            import results as results_mod
            now = dt.datetime.now(dt.timezone.utc)
            since_arg = rest[rest.index("--since") + 1] if "--since" in rest and rest.index("--since") + 1 < len(rest) else None
            d = results_mod.digest(since=results_mod.since_from(since_arg, now), now=now)
            print(json.dumps(d, indent=1, ensure_ascii=False) if "--json" in rest else "\n".join(results_mod.lines(d)))
            return 0
        if cmd == "export-published":
            if len(rest) != 1 or rest[0].startswith("-"):
                print("usage: engine.py export-published <file>", file=sys.stderr)
                return 2
            return export_published(rest[0])
        if cmd == "eval":
            if not rest or rest[0] != "gate":
                print("usage: engine.py eval gate [--live | --status]", file=sys.stderr)
                return 2
            import gate_eval
            _say(f"engine gate_eval {' '.join(rest[1:])}".rstrip())
            return gate_eval.main(rest[1:])
        if cmd == "doctor":
            results = doctor() + channel_doctor_results() + plugin_doctor_results() + [engine_version_result(), claude_token_result()]
            print("\n".join(doctor_lines(results)))
            return 0 if all(r["ok"] for r in results) else 1
        if cmd == "setup":
            if not rest:
                print("usage: engine.py setup <job> [--<key> <value>]...", file=sys.stderr)
                return 2
            if rest[0] == "composio":
                names = [a for a in rest[1:] if not a.startswith("--")]
                if len(names) != 1:
                    print("usage: engine.py setup composio <stream> [--dry]", file=sys.stderr)
                    return 2
                return setup_composio(names[0], dry="--dry" in rest)
            flags = _setup_flags(rest[1:])
            if rest[0] in ("secrets", "plugins"):
                return setup(rest[0])["_exit"]
            setup(rest[0], flags)
            return 0
        if cmd == "onboard-stream":
            return onboard_stream(rest)
        if cmd == "secrets":
            if rest and rest[0] in ("--export", "--check"):
                import secrets as engine_secrets
                return engine_secrets.main(["secrets.py", *rest])
            set_name = rest[rest.index("--set") + 1] if "--set" in rest and rest.index("--set") + 1 < len(rest) else None
            return secrets_cmd(set_name)
        if cmd == "host-check":
            results = host_checks()
            print("\n".join(host_check_lines(results)))
            return 0 if all(r["ok"] for r in results) else 1
        if cmd == "new-instance":
            import instance
            return instance.main(rest)
        if cmd == "shim":
            unknown = [a for a in rest if a != "--install"]
            if unknown:
                print("usage: engine shim [--install]", file=sys.stderr)
                return 2
            return shim(install="--install" in rest)
        if cmd == "plugins":
            if "--headless-settings" in rest:
                print(json.dumps(headless_settings()))
                return 0
            if "--prepare" in rest:
                path, want, changed = prepare_plugins()
                print(f"{'wrote' if changed else 'nothing to write:'} env.{ATELIER_LOG} = {want}  ({os.path.relpath(path, REPO)})")
                return 0
            return plugins_cmd()
    except UnknownJob as e:
        print(f"engine: {e.args[0]}", file=sys.stderr)
        return 2
    except Refused as e:
        print(f"engine: {e.args[0]}", file=sys.stderr)
        return 1
    except (ValueError, config.ConfigError) as e:
        print(f"engine: {e}", file=sys.stderr)
        return 1
    print(f"engine: unknown subcommand {cmd!r}", file=sys.stderr)
    print(__doc__.strip().splitlines()[0], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
