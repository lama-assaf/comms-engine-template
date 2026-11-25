#!/usr/bin/env python3
"""
workflow.py - code runs the cycle; the model does bounded jobs.

Why: the weekday job was one headless `claude -p "/social-cycle"`: one budget,
one exit line, twelve steps read from prose, and every incident happened in a
hand-off between steps. Here each step is a named workflow that code runs: its
script steps as subprocesses, and at most a few model calls, each one `claude
-p` with one agent, its own `--max-budget-usd`, a narrow `--allowedTools`
list, no prompt left waiting for a person, and a JSON object out that this
module checks before it believes it. A workflow that fails reads `gate failed`,
not `social-cycle exit 1`.

The workflows and the chains are data, in engine.json:

  params.workflows.<name>   {what, when?, optional?, probe?, steps: [...]}
  params.chains.<name>      [workflow, ...]

A step is one of:

  {"run": [argv...]}          a script; a non-zero exit fails the workflow
                              (`"ok_exits": [0, 1]` where exit 1 is an answer)
  {"model": {...}}            one `claude -p`: `agent` (optional), `prompt` (a
                              file under briefs/workflows/), `budget_usd`,
                              `tools`, `expects` (key: int|number|str|bool|list)
                              and an optional `runlog` step name, for an agent
                              that holds no Bash and cannot log itself
                              A reply that passed its check is kept beside the
                              run records (state/runs/<workflow>/replies/) and
                              a later `run` step names it as `{reply_1}`,
                              `{reply_2}`: the model returns, code writes
  {"each": {"from": key, "run": [argv with {field}]}}
                              one script call per row of a list the model
                              returned: the model names, code writes
  {"again": {"if": key, "after": workflow}}
                              when the last model output's list `key` is not
                              empty: run `workflow` over those ids, then the
                              model step once more

Every run writes `state/runs/<workflow>/<UTC stamp>.json`: `workflow`,
`stream`, `chain`, `started`, `ended`, `result` (`ok`, `nothing`,
`needs-person`, `failed`), `counts`, `cost_usd`, `inputs`, `outputs`,
`handed_to`, `error`, `steps`. A chain stops at the first workflow that fails
(one marked `optional` is recorded and passed over), stays inside
`cycle.budget_usd`, and writes its own record under `state/runs/chain-<name>/`.

  engine workflow list
  engine workflow run <workflow> [--dry] [--stream <slug>] [--ids a,b]
  engine workflow chain <chain> [--dry] [--skip <workflow>]... [--with <workflow>]... [--only <workflow>] [--drafts N]
  engine workflow status [--json]
  engine run <workflow or chain> [--live]   # the same; dry unless --live

`--dry` prints every command and model call it would make, calls nothing and
writes no record. Nothing here sends: a send is `channels.send()`'s alone.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
REPO = paths.instance()
STATE = paths.state()
PROMPTS = os.path.join(ENGINE, "briefs", "workflows")
BIN = os.path.join(ENGINE, "bin")
RULES_FILE = "_rules.md"
sys.path.insert(0, HERE)
import config  # noqa: E402
import memory  # noqa: E402

RESULTS = ("ok", "nothing", "needs-person", "failed")
#: What an unattended run must never do, whatever a scraped post or a page it read asks of
#: it: write a script (an allowlist would then run it), rewrite an agent, a command, a hook
#: or CLAUDE.md (the next run would obey it), or run secrets.py. A deny outranks an allow.
#: The first seven are the list corpus_cycle_daily.sh carries too.
DENIED = (
    "Edit(**/*.py)", "Edit(**/*.sh)", "Edit(.claude/**)", "Edit(plugins/**)",
    "Edit(~/.claude/**)", "Edit(CLAUDE.md)", "Bash(python3 *secrets.py*)",
    # a step never starts another run, a sender or the control page, and never edits the setup
    "Bash(python3 *workflow.py*)", "Bash(python3 *autopilot.py*)", "Bash(python3 *control.py*)",
    "Bash(python3 *reactions.py*)", "Edit(brand.json)", "Edit(**/engine.json)", "Edit(**/engine.local.json)",
    # the same, as the `engine` command spells them
    "Bash(engine secrets*)", "Bash(engine workflow*)", "Bash(engine autopilot*)", "Bash(engine control*)",
    "Bash(engine reactions*)", "Bash(engine run *)", "Bash(engine enable*)", "Bash(engine shim*)",
    "Bash(engine backup*)",
    "Edit(state/runs/**)",
)
#: A call outside the allowlist is denied at once instead of waiting for a person who is
#: not there. No `acceptEdits`: a file a step may write is named in its `tools`.
#: Never `--bare`: a bare run skips hooks, skills, agents, plugins and CLAUDE.md.
BASE_FLAGS = ("--permission-prompts", "none", "--output-format", "json")
TYPES = {"int": int, "number": (int, float), "str": str, "bool": bool, "list": list}
MODEL_TIMEOUT = 3600
RUN_TIMEOUT = 900
#: Keys any model output may carry beside the ones its workflow expects.
COMMON = {"result": "str", "summary": "str", "counts": "object", "waiting": "int"}


class UnknownWorkflow(KeyError):
    """A name engine.json does not list."""


class StepFailed(RuntimeError):
    """One step of a workflow failed; the message is the run record's `error`."""


# --- the data ---------------------------------------------------------------------------------

def specs():
    """`{name: spec}` from engine.json `params.workflows` (notes dropped)."""
    return {k: v for k, v in (config.cfg("workflows", {}) or {}).items() if not k.startswith("_") and isinstance(v, dict)}


def chains():
    return {k: list(v) for k, v in (config.cfg("chains", {}) or {}).items() if not k.startswith("_") and isinstance(v, list)}


def spec(name):
    all_specs = specs()
    if name not in all_specs:
        raise UnknownWorkflow(f"no workflow {name!r} in engine.json; workflows: {', '.join(all_specs)}")
    return all_specs[name]


def problems():
    """What is wrong with the workflows and chains as data, one line each; empty when they are sound."""
    out = []
    all_specs = specs()
    for name, sp in all_specs.items():
        steps = sp.get("steps")
        if not isinstance(steps, list) or not steps:
            out.append(f"workflows.{name}: no steps")
            continue
        for i, step in enumerate(steps):
            kinds = [k for k in ("run", "model", "each", "again") if k in step]
            if len(kinds) != 1:
                out.append(f"workflows.{name}.steps[{i}]: one of run, model, each, again")
                continue
            if "model" in step:
                m = step["model"]
                if not os.path.isfile(os.path.join(PROMPTS, str(m.get("prompt", "")))):
                    out.append(f"workflows.{name}.steps[{i}]: prompt file {m.get('prompt')!r} is not under briefs/workflows/")
                if not isinstance(m.get("budget_usd"), (int, float)) or m["budget_usd"] <= 0:
                    out.append(f"workflows.{name}.steps[{i}]: a model call needs its own budget_usd")
                if not m.get("tools"):
                    out.append(f"workflows.{name}.steps[{i}]: a model call needs a tool list")
                for key, typ in (m.get("expects") or {}).items():
                    if typ not in TYPES:
                        out.append(f"workflows.{name}.steps[{i}].expects.{key}: {typ!r} is not one of {', '.join(TYPES)}")
            if "again" in step and step["again"].get("after") not in all_specs:
                out.append(f"workflows.{name}.steps[{i}]: again.after names no workflow")
    for cname, members in chains().items():
        for m in members:
            if m not in all_specs:
                out.append(f"chains.{cname}: {m!r} is not a workflow")
    return out


# --- when a workflow is due -------------------------------------------------------------------

def month_start(day):
    """The first weekday of the month: the 1st when it is a weekday, else the Monday on the 2nd or 3rd."""
    return (day.day == 1 and day.isoweekday() <= 5) or (day.isoweekday() == 1 and day.day <= 3)


def due(sp, now, context=None):
    """`(True, "")` or `(False, why)` for a workflow's `when`: every condition named must hold."""
    when = sp.get("when") or {}
    context = context or {}
    key = when.get("config")
    if key and not config.cfg(key, False):
        return False, f"off in engine.json ({key})"
    days = when.get("weekday")
    if days and now.isoweekday() not in days:
        return False, f"not today (runs on ISO weekday {', '.join(str(d) for d in days)})"
    if when.get("month_start") and not month_start(now):
        return False, "not today (runs on the first weekday of the month)"
    wanted = when.get("channels")
    if wanted:
        import channels
        own = [k for k, _ in channels.stream_channels(context.get("stream") or memory.DEFAULT_STREAM)]
        if not any(c in own for c in wanted):
            return False, f"the stream lists no {' or '.join(wanted)} channel"
    after = when.get("after")
    if after:
        prior = (context.get("outputs") or {}).get(after["workflow"])
        if not prior or not prior.get(after["field"]):
            return False, f"nothing from {after['workflow']} ({after['field']} is empty)"
    return True, ""


# --- one model call ---------------------------------------------------------------------------

def schema_for(expects):
    """The JSON Schema `claude --json-schema` holds the reply to."""
    kinds = {"int": {"type": "integer"}, "number": {"type": "number"}, "str": {"type": "string"},
             "bool": {"type": "boolean"}, "list": {"type": "array"}, "object": {"type": "object"}}
    props = {k: kinds[t] for k, t in {**COMMON, **(expects or {})}.items()}
    props["result"] = {"type": "string", "enum": [r for r in RESULTS if r != "failed"]}
    return {"type": "object", "properties": props, "required": sorted(expects or {})}


#: The atelier and salon plugins inject the ROOT stream's instincts.md when a session starts, whatever
#: stream the run serves, and their hook has no switch to turn that off (atelier 0.3.0,
#: scripts/hooks/session-context.js). Until the injection is stream-aware upstream, a call for any
#: other stream is told so in its own prompt, where it outranks what the hook put in the context.
OTHER_STREAM_NOTE = (
    "## this run is for the stream {stream_name}, not the brand's own\n\n"
    "A plugin hook put the brand's own `.atelier/memory/instincts.md` into this session when it started. "
    "Those are another stream's standing rules: disregard them. This stream's are "
    "`{stream_dir}/instincts.md`, with its `status.md`, `voice.md`, `claims.md` and `handles.md` beside it. "
    "Read those, and nothing from another stream's memory.")


def prompt_text(model, values):
    """The brief (its `{placeholders}` filled) followed by the rules every run carries and the keys to return.
    A call for a stream other than the brand's own also carries OTHER_STREAM_NOTE."""
    with open(os.path.join(PROMPTS, model["prompt"]), encoding="utf-8") as f:
        brief = f.read()
    with open(os.path.join(PROMPTS, RULES_FILE), encoding="utf-8") as f:
        rules = f.read()
    for key, value in values.items():
        brief = brief.replace("{" + key + "}", str(value))
    note = ""
    slug = str(values.get("stream") or "")
    if slug and slug != memory.DEFAULT_STREAM:
        note = "\n\n" + OTHER_STREAM_NOTE.format(stream_name=values.get("stream_name", slug),
                                                 stream_dir=os.path.relpath(memory.stream_dir(slug), memory.REPO))
    keys = ", ".join(f"`{k}` ({t})" for k, t in (model.get("expects") or {}).items())
    return f"{brief.rstrip()}{note}\n\n{rules.rstrip()}\nThis step's keys: {keys or 'none beyond the common ones'}.\n"


def headless_settings():
    """The plugins a schedule has no use for, switched off for this call alone (engine.py's rule)."""
    names = list(config.cfg("plugins.interactive_only", []) or [])
    return {"enabledPlugins": {n: False for n in names}}


def claude_argv(model, prompt, budget):
    argv = ["claude", "-p", prompt]
    if model.get("agent"):
        argv += ["--agent", model["agent"]]
    argv += [*BASE_FLAGS, "--max-budget-usd", f"{budget:g}",
             "--json-schema", json.dumps(schema_for(model.get("expects"))),
             "--settings", json.dumps(headless_settings()),
             "--disallowedTools", ",".join(DENIED),
             "--allowedTools", ",".join(model["tools"])]
    return argv


def _json_object(text):
    """The last JSON object in a text, or None: the reply's closing object, whatever came before it."""
    # a reviewer often closes its reply inside a ```json fence; the fence is not part of the object
    text = re.sub(r"\s*```\s*$", "", (text or "").strip())
    if not text:
        return None
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except ValueError:
        pass
    dec = json.JSONDecoder()
    found = None
    for m in re.finditer(r"\{", text):
        try:
            value, end = dec.raw_decode(text[m.start():])
        except ValueError:
            continue
        if isinstance(value, dict) and not text[m.start() + end:].strip():
            found = value
            break
    return found


def read_reply(stdout):
    """`(output, cost, error)` from what `claude -p --output-format json` printed.

    The envelope is the last line that parses as a result object; the step's
    own object is its `structured_output`, or the closing JSON of its `result`
    text. An envelope that says `is_error`, or no envelope at all, is an error.
    """
    envelope = None
    for line in reversed((stdout or "").strip().splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and ("result" in value or "structured_output" in value or value.get("type") == "result"):
            envelope = value
            break
    if envelope is None:
        envelope = _json_object(stdout)
    if envelope is None:
        tail = (stdout or "").strip().splitlines()[-1:] or ["no output"]
        return None, 0.0, f"no result from claude: {tail[0][:200]}"
    cost = envelope.get("total_cost_usd") or envelope.get("cost_usd") or 0.0
    if envelope.get("is_error") or str(envelope.get("subtype", "success")).startswith("error"):
        return None, float(cost), str(envelope.get("result") or envelope.get("subtype") or "claude reported an error")[:300]
    out = envelope.get("structured_output")
    if not isinstance(out, dict):
        out = _json_object(envelope.get("result") if isinstance(envelope.get("result"), str) else "")
    if not isinstance(out, dict):
        return None, float(cost), "the reply did not end with a JSON object"
    return out, float(cost), None


def check_output(out, expects):
    """The first thing wrong with a step's object against what its workflow expects, or None."""
    for key, typ in (expects or {}).items():
        if key not in out:
            return f"`{key}` is missing"
        value = out[key]
        if not isinstance(value, TYPES[typ]) or (typ in ("int", "number") and isinstance(value, bool)):
            return f"`{key}` should be {typ}, got {type(value).__name__}"
    if "result" in out and out["result"] not in ("ok", "nothing", "needs-person"):
        return f"`result` {out['result']!r} is not ok, nothing or needs-person"
    counts = out.get("counts")
    if counts is not None and not (isinstance(counts, dict) and all(isinstance(v, int) and not isinstance(v, bool) for v in counts.values())):
        return "`counts` holds whole numbers only"
    return None


# --- running ----------------------------------------------------------------------------------

def _execute(argv, timeout, env=None):
    """Run one command in the repository; `(exit code, stdout, stderr)`. A timeout is exit 124.

    A step written `engine <name> ...` runs the script it names (paths.expand), so a
    run step needs nothing on PATH."""
    argv = paths.expand(argv) or list(argv)
    try:
        proc = subprocess.run(argv, cwd=REPO, env=env, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    except OSError as e:
        return 127, "", str(e)
    return proc.returncode, proc.stdout, proc.stderr


#: The subscription token from `claude setup-token` (docs/07-hosting.md): a model call's alone.
CLAUDE_TOKEN = "CLAUDE_CODE_OAUTH_TOKEN"
_token = []


def claude_token():
    """CLAUDE_CODE_OAUTH_TOKEN through secrets.py (environment, then keychain), once per run; None
    when this machine keeps none and claude signs in with its own login."""
    if not _token:
        try:
            import secrets as engine_secrets
            _token.append(engine_secrets.get_secret(CLAUDE_TOKEN, required=False))
        except Exception:  # a keychain that cannot be read leaves claude its own login
            _token.append(None)
    return _token[0]


def _run_env():
    """A script step's environment: the process's, without the Claude token, which is a model call's alone."""
    return {k: v for k, v in os.environ.items() if k != CLAUDE_TOKEN}


def _model_env():
    """claude signs in with the host's token where one is kept (and its own login otherwise), never a
    stray API key, and never stops a background subagent ten minutes after the last turn (the first
    launchd cycle ended there)."""
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", CLAUDE_TOKEN)}
    token = claude_token()
    if token:
        env[CLAUDE_TOKEN] = token
    env["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] = "0"
    # the step's Bash calls are `engine <name>`: the plugin's bin/ first on PATH, the instance named
    env["PATH"] = os.pathsep.join([BIN, *[p for p in env.get("PATH", "").split(os.pathsep) if p and p != BIN]])
    env[paths.ENV] = REPO
    return env


def _stamp(now):
    return now.strftime("%Y%m%dT%H%M%SZ")


def _utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def runs_dir(state=None):
    return os.path.join(state or STATE, "runs")


def write_record(record, state=None):
    """`state/runs/<workflow>/<stamp>.json`; a second run in the same second gets a suffix."""
    d = os.path.join(runs_dir(state), record["workflow"])
    os.makedirs(d, exist_ok=True)
    base = record["started"].replace("-", "").replace(":", "").replace("+0000", "Z")
    path = os.path.join(d, f"{base}.json")
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(d, f"{base}-{n}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
    return path


def save_reply(name, started, n, reply, state=None):
    """Keep a model reply that passed its check, for the script step that reads it:
    `state/runs/<workflow>/replies/<stamp>-<n>.json`. Returns the path relative to the repository."""
    d = os.path.join(runs_dir(state), name, "replies")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{_stamp(started)}-{n}.json")
    k = 1
    while os.path.exists(path):
        k += 1
        path = os.path.join(d, f"{_stamp(started)}-{n}-{k}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(reply, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
    rel = os.path.relpath(path, REPO)
    return path if rel.startswith("..") else rel


def waiting(state=None):
    """How many gated items wait for a person's decision, from the drafting queue."""
    path = os.path.join(state or STATE, "queue.json")
    try:
        with open(path, encoding="utf-8") as f:
            items = json.load(f)
    except (OSError, ValueError):
        return 0
    items = items if isinstance(items, list) else []
    return sum(1 for it in items if isinstance(it, dict)
               and str(it.get("alpha_status") or "proposed") == "proposed"
               and str((it.get("gate") or {}).get("verdict", "")) in ("pass", "pass-with-edits"))


PROBES = {"waiting": waiting}


def _shell(argv):
    return " ".join(a if re.fullmatch(r"[\w@%+=:,./-]+", a) else "'" + a.replace("'", "'\\''") + "'" for a in argv)


def _fill(argv, values):
    return [str(a).format_map(_Keep(values)) for a in argv]


class _Keep(dict):
    """`{drafts}` is filled; a brace pair that names nothing is left as written."""

    def __missing__(self, key):
        return "{" + key + "}"


def run(name, stream=None, dry=False, state=None, now=None, execute=None, values=None, context=None,
        chain=None, budget_left=None, out=None, depth=0):
    """Run one workflow and return its record (written unless `dry`).

    `execute(argv, timeout, env)` is the one place a process starts, so a test
    hands in a fake. `values` fill a prompt's and a command's `{placeholders}`
    (`drafts`, `ids`); `context` carries the outputs of the chain's earlier
    workflows. `budget_left` caps each model call's own budget.
    """
    sp = spec(name)
    execute = execute or _execute
    out = out or (lambda line: print(line, flush=True))
    slug = (stream or memory.DEFAULT_STREAM).strip().lower()
    stream_name = memory.stream(slug)["name"]
    started = now or _utcnow()
    values = {"stream": slug, "stream_name": stream_name, "drafts": config.cfg("cycle.drafts", 3),
              "ids": "", "ids_clause": "", **(values or {})}
    if values.get("ids") and not values.get("ids_clause"):
        values["ids_clause"] = f", these ids only: {values['ids']}"
    if not values.get("ids_arg"):
        values["ids_arg"] = "".join(" " + i for i in str(values.get("ids") or "").replace(",", " ").split())
    record = {"workflow": name, "stream": slug, "chain": chain, "started": started.isoformat(timespec="seconds"),
              "ended": None, "result": "ok", "counts": {}, "cost_usd": 0.0,
              "inputs": {k: v for k, v in values.items() if k in ("drafts", "ids") and v not in ("", None)},
              "outputs": {}, "handed_to": None, "error": None, "steps": []}
    last = {}
    replies = []
    spent = 0.0

    def model_step(model):
        nonlocal spent, last
        budget = float(model["budget_usd"])
        if budget_left is not None:
            budget = min(budget, round(budget_left - spent, 4))
            if budget <= 0:
                raise StepFailed("the chain's budget is spent (cycle.budget_usd)")
        argv = claude_argv(model, prompt_text(model, values), budget)
        shown = f"claude -p <{model['prompt']}>" + (f" --agent {model['agent']}" if model.get("agent") else "") \
                + f" --max-budget-usd {budget:g} --allowedTools {','.join(model['tools'])}"
        out(f"$ {shown}")
        if dry:
            record["steps"].append({"model": model["prompt"], "agent": model.get("agent"), "budget_usd": budget, "dry": True})
            return
        t0 = _utcnow()
        rc, stdout, stderr = execute(argv, model.get("timeout_s", MODEL_TIMEOUT), _model_env())
        reply, cost, error = read_reply(stdout)
        spent += cost
        record["cost_usd"] = round(record["cost_usd"] + cost, 4)
        step = {"model": model["prompt"], "agent": model.get("agent"), "budget_usd": budget, "exit": rc,
                "cost_usd": cost, "seconds": int((_utcnow() - t0).total_seconds())}
        record["steps"].append(step)
        if error is None and rc != 0:
            error = f"claude exit {rc}: {((stderr or '').strip().splitlines() or [''])[-1][:200]}"
        if error is None:
            error = check_output(reply, model.get("expects"))
            if error:
                error = f"the reply did not match what the step returns: {error}"
        if error:
            step["error"] = error
            raise StepFailed(error)
        last = reply
        replies.append(reply)
        saved = save_reply(name, started, len(replies), dict(reply, reviewer=model.get("agent") or model["prompt"]), state)
        values[f"reply_{len(replies)}"] = values["reply"] = saved
        record["outputs"].update({k: v for k, v in reply.items() if k not in ("result", "counts")})
        record["counts"].update(reply.get("counts") or {})
        record["counts"].update({k: v for k, v in reply.items()
                                 if k in (model.get("expects") or {}) and isinstance(v, int) and not isinstance(v, bool)})
        if reply.get("result") in ("nothing", "needs-person"):
            record["result"] = reply["result"]
        if model.get("runlog"):
            import runlog
            who = model.get("agent") or name
            runlog.append(model["runlog"], f"{who}: {reply.get('summary') or json.dumps(record['counts'])}",
                          stream=stream_name, runs_path=os.path.join(state or STATE, "runs.json"))

    def run_step(argv, ok_exits=(0,)):
        argv = _fill(argv, values)
        out(f"$ {_shell(argv)}")
        if dry:
            record["steps"].append({"run": argv, "dry": True})
            return
        t0 = _utcnow()
        rc, stdout, stderr = execute(argv, RUN_TIMEOUT, _run_env())
        step = {"run": argv, "exit": rc, "seconds": int((_utcnow() - t0).total_seconds())}
        said = (stdout or "").strip().splitlines()[-1:]
        if said:
            step["said"] = said[0][:300]  # the script's own closing line: what it found, in its words
        record["steps"].append(step)
        if rc not in ok_exits:
            tail = ((stderr or "").strip() or (stdout or "").strip()).splitlines()[-1:] or [""]
            step["error"] = tail[0][:300]
            raise StepFailed(f"{os.path.basename(argv[1]) if len(argv) > 1 else argv[0]} exit {rc}: {tail[0][:200]}")

    try:
        prior_model = None
        for step in sp["steps"]:
            if "run" in step:
                run_step(step["run"], tuple(step.get("ok_exits", (0,))))
            elif "model" in step:
                prior_model = step["model"]
                model_step(prior_model)
            elif "each" in step:
                rows = last.get(step["each"]["from"]) or []
                refused = 0
                for row in rows if isinstance(rows, list) else []:
                    if not isinstance(row, dict) or any(not isinstance(v, (str, int, float)) for v in row.values()):
                        refused += 1
                        continue
                    argv = _fill(step["each"]["run"], {**values, **{k: str(v) for k, v in row.items()}})
                    if any(re.search(r"\{\w+\}", a) for a in argv):
                        refused += 1  # a row that lacks a field the command needs is not guessed at
                        continue
                    run_step(argv)
                if refused:
                    record["counts"][f"{step['each']['from']}_refused"] = refused
            elif "again" in step:
                ids = last.get(step["again"]["if"]) or []
                if dry or not ids or depth or prior_model is None:
                    continue
                nested = run(step["again"]["after"], stream=slug, state=state, execute=execute, chain=chain,
                             values={"ids": ", ".join(str(i) for i in ids)}, context=context,
                             budget_left=None if budget_left is None else budget_left - spent, out=out, depth=depth + 1)
                spent += nested["cost_usd"]
                record["steps"].append({"again": step["again"]["after"], "result": nested["result"]})
                if nested["result"] == "failed":
                    raise StepFailed(f"{step['again']['after']} failed on the edited items: {nested['error']}")
                model_step(prior_model)
        probe = sp.get("probe")
        if probe and not dry:
            n = PROBES[probe](state)
            record["counts"][probe] = n
            if n and record["result"] == "ok":
                record["result"] = "needs-person"
    except StepFailed as e:
        record["result"] = "failed"
        record["error"] = str(e)
    record["ended"] = _utcnow().isoformat(timespec="seconds")
    if record["result"] == "needs-person":
        record["handed_to"] = "person"
    if not dry:
        record["path"] = os.path.relpath(write_record(record, state), REPO)
    return record


def skipped(name, why, stream, chain, state=None, now=None, dry=False):
    """The record of a workflow that was not due: `nothing`, with the reason, no call made."""
    at = (now or _utcnow()).isoformat(timespec="seconds")
    record = {"workflow": name, "stream": stream, "chain": chain, "started": at, "ended": at, "result": "nothing",
              "counts": {}, "cost_usd": 0.0, "inputs": {}, "outputs": {"skipped": why}, "handed_to": None,
              "error": None, "steps": []}
    if not dry:
        record["path"] = os.path.relpath(write_record(record, state), REPO)
    return record


def run_chain(name, stream=None, dry=False, state=None, now=None, execute=None, skip=(), include=(), only=None,
              values=None, out=None):
    """Run a chain in order. Stops at the first workflow that fails unless it is `optional`.

    `skip` leaves workflows out, `include` runs one whatever its `when` says
    (the by-hand `--editor`), `only` runs that one alone. Returns the chain's
    record: `{chain, stream, started, ended, result, failed, cost_usd, workflows}`.
    """
    all_chains = chains()
    if name not in all_chains:
        raise UnknownWorkflow(f"no chain {name!r} in engine.json; chains: {', '.join(all_chains)}")
    out = out or (lambda line: print(line, flush=True))
    slug = (stream or memory.DEFAULT_STREAM).strip().lower()
    started = now or _utcnow()
    chain_id = f"{name}-{_stamp(started)}"
    budget = float(config.cfg("cycle.budget_usd", 20))
    members = [only] if only else [m for m in all_chains[name]]
    for extra in include:
        if extra not in members:
            members.append(extra)
    context = {"outputs": {}, "stream": slug}
    rows, failed, spent = [], None, 0.0
    for i, member in enumerate(members):
        sp = spec(member)
        ok, why = (False, "left out (--skip)") if member in skip else due(sp, started, context)
        if not ok and member in include and "nothing from" not in why:
            ok = True
        if not ok:
            out(f"-- {member}: skipped, {why}")
            rec = skipped(member, why, slug, chain_id, state=state, now=now, dry=dry)
        else:
            out(f"== {member}: {sp.get('what', '')}")
            vals = dict(values or {})
            prior = context["outputs"].get((sp.get("when") or {}).get("after", {}).get("workflow", ""))
            if prior and isinstance(prior.get("ids"), list):
                vals["ids"] = ", ".join(str(x) for x in prior["ids"])
            rec = run(member, stream=slug, dry=dry, state=state, execute=execute, values=vals, context=context,
                      chain=chain_id, budget_left=budget - spent, out=out)
        spent += rec["cost_usd"]
        context["outputs"][member] = rec["outputs"]
        rows.append({"workflow": member, "result": rec["result"], "cost_usd": rec["cost_usd"],
                     "error": rec["error"], "record": rec.get("path")})
        if rec["result"] == "failed":
            out(f"{member} failed: {rec['error']}")
            if not sp.get("optional"):
                failed = member
                break
        elif ok and not dry:
            out(f"{member} {rec['result']}" + (f"  {json.dumps(rec['counts'])}" if rec["counts"] else ""))
    result = "failed" if failed else ("needs-person" if any(r["result"] == "needs-person" for r in rows) else "ok")
    record = {"workflow": f"chain-{name}", "chain": chain_id, "stream": slug,
              "started": started.isoformat(timespec="seconds"), "ended": _utcnow().isoformat(timespec="seconds"),
              "result": result, "failed": failed, "cost_usd": round(spent, 4), "budget_usd": budget, "workflows": rows}
    if not dry:
        record["path"] = os.path.relpath(write_record(record, state), REPO)
    return record


# --- status -----------------------------------------------------------------------------------

def last_record(name, state=None):
    d = os.path.join(runs_dir(state), name)
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".json"))
    except OSError:
        return None
    for n in reversed(names):
        try:
            with open(os.path.join(d, n), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return None


def cost_today(name, state=None, today=None):
    today = (today or _utcnow().date()).isoformat()
    d = os.path.join(runs_dir(state), name)
    total = 0.0
    try:
        names = [n for n in os.listdir(d) if n.endswith(".json") and n.startswith(today.replace("-", ""))]
    except OSError:
        return 0.0
    for n in names:
        try:
            with open(os.path.join(d, n), encoding="utf-8") as f:
                total += float(json.load(f).get("cost_usd") or 0)
        except (OSError, ValueError):
            continue
    return round(total, 4)


def status_rows(state=None, today=None):
    """One row per workflow: `{workflow, last, result, waiting, cost_today, error}`."""
    rows = []
    for name in specs():
        rec = last_record(name, state) or {}
        rows.append({"workflow": name, "last": rec.get("started"), "result": rec.get("result"),
                     "waiting": (rec.get("counts") or {}).get("waiting", 0), "cost_today": cost_today(name, state, today),
                     "error": rec.get("error")})
    return rows


def status_lines(rows):
    if not rows:
        return ["workflows  none in engine.json"]
    w = max(len(r["workflow"]) for r in rows)
    lines = [f"{'workflow':<{w}}  {'last run':<25}  {'result':<12}  waiting  cost today"]
    for r in rows:
        tail = f"  {r['workflow']} failed: {r['error']}" if r["result"] == "failed" and r["error"] else ""
        lines.append(f"{r['workflow']:<{w}}  {(r['last'] or '-'):<25}  {(r['result'] or '-'):<12}  "
                     f"{r['waiting']:>7}  {r['cost_today']:>8.2f}{tail}")
    lines.append(f"spend today  {sum(r['cost_today'] for r in rows):.2f} USD across the workflows")
    return lines


# --- CLI --------------------------------------------------------------------------------------

def _values(argv):
    """`--skip a --with b --only c --drafts 2 --ids x,y --stream s` and the old cycle flags."""
    opts = {"skip": [], "include": [], "only": None, "values": {}, "stream": None, "dry": False, "json": False}
    legacy = {"--no-listen": ("skip", "listen"), "--no-voice": ("skip", "voice"), "--no-motion": ("skip", "motion"),
              "--no-story": ("skip", "story"), "--editor": ("include", "editor"), "--slots": ("include", "slots"),
              "--readout": ("include", "readout"), "--engage": ("include", "engage")}
    rest, i = [], 0
    while i < len(argv):
        a = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if a in ("--dry", "--dry-run"):
            opts["dry"] = True
        elif a == "--json":
            opts["json"] = True
        elif a in legacy:
            opts[legacy[a][0]].append(legacy[a][1])
        elif a in ("--skip", "--with", "--only", "--drafts", "--ids", "--stream") and nxt is not None:
            if a == "--skip":
                opts["skip"].append(nxt)
            elif a == "--with":
                opts["include"].append(nxt)
            elif a == "--only":
                opts["only"] = nxt
            elif a == "--stream":
                opts["stream"] = nxt
            else:
                opts["values"][a[2:]] = nxt
            i += 1
        else:
            rest.append(a)
        i += 1
    return rest, opts


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv else 2
    cmd = argv[0]
    rest, opts = _values(argv[1:])
    try:
        if cmd == "list":
            for name, sp in specs().items():
                model = sum(1 for s in sp.get("steps", []) if "model" in s)
                print(f"{name:<11} {model} model call(s)  {sp.get('what', '')}")
            for name, members in chains().items():
                print(f"chain {name}: {', '.join(members)}")
            bad = problems()
            for line in bad:
                print(f"PROBLEM  {line}")
            return 1 if bad else 0
        if cmd == "status":
            rows = status_rows()
            print(json.dumps(rows, indent=1) if opts["json"] else "\n".join(status_lines(rows)))
            return 0
        if cmd == "run" and len(rest) == 1:
            rec = run(rest[0], stream=opts["stream"], dry=opts["dry"], values=opts["values"])
            if opts["dry"]:
                print(f"{rest[0]}: dry run, nothing called, no record written")
                return 0
            print(f"{rest[0]} {rec['result']}" + (f": {rec['error']}" if rec["error"] else "")
                  + f"  cost {rec['cost_usd']:.2f} USD  {rec.get('path', '')}")
            return 1 if rec["result"] == "failed" else 0
        if cmd == "chain" and len(rest) == 1:
            rec = run_chain(rest[0], stream=opts["stream"], dry=opts["dry"], skip=opts["skip"], include=opts["include"],
                            only=opts["only"], values=opts["values"])
            if opts["dry"]:
                print(f"chain {rest[0]}: dry run, nothing called, no record written")
                return 0
            line = f"chain {rest[0]} {rec['result']}"
            if rec["failed"]:
                line = f"{rec['failed']} failed"
            print(f"{line}  cost {rec['cost_usd']:.2f} of {rec['budget_usd']:g} USD  {rec.get('path', '')}")
            return 1 if rec["result"] == "failed" else 0
    except (UnknownWorkflow, memory.SharedMemoryError) as e:
        print(f"workflow: {e.args[0]}", file=sys.stderr)
        return 2
    print("usage: workflow.py list | run <workflow> [--dry] | chain <chain> [--dry] [--skip w] [--with w] [--only w] | status [--json]",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
