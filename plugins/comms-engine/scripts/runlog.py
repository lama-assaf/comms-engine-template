#!/usr/bin/env python3
"""
runlog.py - one entry in `state/runs.json`, appended by whoever did the work.

The run log is the desk's Operations table: when the engine ran, which step
ran, and what that step found. Until now the scripted steps wrote their own row
(`listen.py`, `inventory.py`, `apply_edits.py`, `publish.py`) while the four
agent steps - the listener's assessment, the writer's drafts, the gate, the
distribution - were typed into the file afterwards by a person reading the
agents' reports. A log written after the fact is a log that is wrong whenever
the cycle is interrupted: the steps that ran unattended at 07:15 are exactly
the ones nobody was there to record.

So each agent appends its own entry as it finishes, through this one script,
and the log is never edited by hand. `listener` writes `assess`,
`theme-writer` writes `draft`, `gatekeeper` writes `gate`, `distributor`
writes `distribute` - the step names the log already carries from the
2026-09-07 cycle, so the Operations table stays continuous.

**The entry shape is the one the desk already renders.** `run_id`, `step`, `at`
and a `detail` sentence; the desk's run table (`desk_sync.py --push`, `runs`)
shows `detail` for any step that carries no item count. The detail is the agent's own report in one line -
the counts it is about to put in front of a person - because a row that says
only that a step ran tells the reader nothing they could not infer from the
timestamp.

**Appending never rewrites what is there.** The log is read back by the desk
and by the next cycle, so a partial write would lose the history: the file is
loaded, extended and replaced atomically. A `runs.json` that is not a JSON list
is a corrupted log, and this refuses it rather than starting a fresh one over
the top.

  engine runlog assess "listener: 12 findings" --stream Acme
  engine runlog gate "gatekeeper: 2 pass, 1 block" --stream Acme

Every entry names its `stream` (plan v2, A3): the desk and the scorer read the
log per stream, and an entry that does not say which stream it served is one
they cannot place.
"""
import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
STATE = paths.state()

#: The four agent steps, in the order one cycle runs them. Any step name is
#: accepted - the scripted steps use their own - but these are the ones the
#: agent definitions carry.
AGENT_STEPS = ("assess", "draft", "gate", "distribute")


def runs_file(runs_path=None):
    return runs_path or os.path.join(STATE, "runs.json")


def load(runs_path=None):
    """The log as it stands. Missing file is an empty log; anything that is
    not a list is a corrupted one and stops the caller."""
    p = runs_file(runs_path)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        runs = json.load(f)
    if not isinstance(runs, list):
        raise RuntimeError(f"{p} is not a JSON list - refusing to overwrite it")
    return runs


def append(step, detail, stream=None, run_id=None, runs_path=None, now=None, **extra):
    """Append one entry and return it.

    `step` names the step (`assess`, `draft`, `gate`, `distribute` for the four
    agents); `detail` is the one-line report the desk renders; `stream` names
    the stream the step ran for, as the registry spells it (`Acme`), and is
    required: a run entry that does not say which stream it served cannot be
    read back per stream (plan v2, A3). `extra` carries the fields a particular
    step counts - `item`, `items`, `file` - in the shape the existing entries
    use.
    """
    step = (step or "").strip()
    detail = (detail or "").strip()
    stream = (stream or "").strip()
    if not step:
        raise ValueError("a run entry needs a step")
    if not detail:
        raise ValueError(f"a run entry needs a detail: {step} of what?")
    if not stream:
        raise ValueError(f"a run entry needs a stream: {step} ran for which stream?")
    now = now or dt.datetime.now(dt.timezone.utc)
    entry = {
        "run_id": run_id or now.strftime("%Y%m%dT%H%M%SZ"),
        "step": step,
        "at": now.isoformat(timespec="seconds"),
        "stream": stream,
        "detail": detail,
    }
    entry.update(extra)

    runs = load(runs_path)
    runs.append(entry)
    p = runs_file(runs_path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(runs, f, indent=1, ensure_ascii=False)
    os.replace(tmp, p)
    return entry


def main():
    ap = argparse.ArgumentParser(
        description="Append one entry to the engine run log.")
    ap.add_argument("step", help="the step that just finished (assess, draft, "
                                 "gate, distribute)")
    ap.add_argument("detail", help="one line: what the step found, in the "
                                   "counts your report carries")
    ap.add_argument("--stream", required=True,
                    help="the stream this step ran for, as the registry spells it (the brand's name)")
    ap.add_argument("--run-id", help="group this entry with a cycle "
                                     "(default: the current UTC stamp)")
    ap.add_argument("--runs", help="write to this log instead of state/runs.json")
    args = ap.parse_args()

    try:
        entry = append(args.step, args.detail, stream=args.stream,
                       run_id=args.run_id, runs_path=args.runs)
    except (ValueError, RuntimeError) as e:
        print(f"runlog: {e}", file=sys.stderr)
        return 1
    print(f"runs.json + {entry['step']} ({entry['run_id']}) {entry['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
