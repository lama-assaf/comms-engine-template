#!/usr/bin/env python3
"""
The fixture set for `scripts/runlog.py` and for the four agents that call it.

The claim here is that the run log writes itself. Every step of a cycle appends
its own row as it finishes — the scripts through their own code, the four
agents through `runlog.py` — so nothing is left to be typed up afterwards by a
person reading the reports. That claim has two halves, and both are asserted
below.

1. **The appender is safe to share.** Four writers now extend the same file, so
   appending must never lose what is there, must never start a fresh log over a
   corrupted one, must refuse an entry with no detail (a row that says only
   that a step ran tells the desk nothing the timestamp did not), and must
   produce the shape the desk's run table already renders.

2. **Each agent really does carry its own call.** The definitions under
   `claude/agents/` are the deliverable, not the prose about them, so the cycle
   rehearsal below *reads the four command lines out of those four files* and
   runs them in the order a cycle spawns the agents. What it asserts is what
   `/social-cycle` would produce: a log that gains `assess`, `draft`, `gate`
   and `distribute`, in that order, around the scripted rows, with no manual
   step. It stands in for a live `/social-cycle`, which spends the paid Apify
   actor, rewrites the vault notes and republishes the desk Alpha is reading —
   none of which belongs in a test suite.

The relative order is what is asserted, never contiguity: `listen`,
`inventory`, `edits` and `publish` rows land between the agent rows, and a
re-gate after Alpha's desk edits legitimately adds a second `gate`.

  python3 -m unittest discover plugins/comms-engine/tests
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(ENGINE))
AGENTS = os.path.join(ENGINE, "agents")
SCRIPT = os.path.join(ENGINE, "scripts", "runlog.py")
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import runlog  # noqa: E402

#: agent definition -> the step it owns, in the order one cycle runs them. The `gate` row is
#: not an agent's: the gatekeeper returns findings and writes nothing, and scripts/review.py,
#: which stamps the verdict, logs the reading (tests/test_review.py).
CYCLE = [
    ("listener.md", "assess"),
    ("theme-writer.md", "draft"),
    ("distributor.md", "distribute"),
]


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_log(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def agent_command(filename):
    """The `runlog.py` command line the agent definition carries, unwrapped.

    The definitions wrap it over several lines with trailing backslashes for
    readability; this rejoins them the way a shell would.
    """
    with open(os.path.join(AGENTS, filename), encoding="utf-8") as f:
        lines = f.read().splitlines()
    start = next(i for i, l in enumerate(lines)
                 if re.match(r"\s*engine runlog\b", l))
    parts, i = [], start
    while True:
        line = lines[i].strip()
        cont = line.endswith("\\")
        parts.append(line[:-1].strip() if cont else line)
        i += 1
        if not cont:
            break
    return " ".join(parts)


class AppendTest(unittest.TestCase):
    """The appender itself."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.log = os.path.join(self.dir, "runs.json")

    def read(self):
        return read_log(self.log)

    def test_missing_file_is_an_empty_log(self):
        runlog.append("assess", "listener: 12 findings", stream="Acme", runs_path=self.log)
        self.assertEqual([e["step"] for e in self.read()], ["assess"])

    def test_existing_entries_are_kept(self):
        """The log is history. An append extends it and touches nothing else."""
        seed = [{"run_id": "20260907T194018Z", "step": "listen",
                 "at": "2026-09-07T19:43:54+00:00", "items": 180, "terms": 9,
                 "elapsed_s": 215.3, "file": "state/listening-x.json"}]
        with open(self.log, "w", encoding="utf-8") as f:
            json.dump(seed, f, indent=1)
        runlog.append("assess", "listener: 12 findings", stream="Acme", runs_path=self.log)
        runs = self.read()
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0], seed[0])
        self.assertEqual(runs[-1]["step"], "assess")

    def test_the_shape_the_desk_renders(self):
        """`run_id`, `step`, `at`, `detail` — plus whatever that step counts,
        in the shape the entries already in the log use."""
        entry = runlog.append("distribute", "distributor: 1 published",
                              stream="Acme", runs_path=self.log, item="Q-3",
                              published_to=["vault"])
        for key in ("run_id", "step", "at", "detail", "stream"):
            self.assertTrue(entry[key], key)
        self.assertEqual(entry["item"], "Q-3")
        self.assertEqual(entry["published_to"], ["vault"])
        stamped = dt.datetime.fromisoformat(entry["at"])
        self.assertIsNotNone(stamped.tzinfo, "the stamp carries its offset")
        self.assertEqual(entry, self.read()[-1])

    def test_a_run_id_can_group_a_cycle(self):
        for step in ("assess", "draft"):
            runlog.append(step, f"{step}: something", run_id="20260908T070000Z",
                          stream="Acme", runs_path=self.log)
        self.assertEqual({e["run_id"] for e in self.read()},
                         {"20260908T070000Z"})

    def test_refuses_an_entry_with_no_stream(self):
        """A3: a run entry names the stream it served, or it is not written."""
        with self.assertRaises(ValueError):
            runlog.append("gate", "gatekeeper: 3 read", runs_path=self.log)
        self.assertFalse(os.path.exists(self.log))

    def test_an_entry_with_no_detail_is_refused(self):
        with self.assertRaises(ValueError):
            runlog.append("gate", "   ", stream="Acme", runs_path=self.log)
        with self.assertRaises(ValueError):
            runlog.append("", "gatekeeper: 3 read", stream="Acme", runs_path=self.log)
        self.assertFalse(os.path.exists(self.log), "nothing was written")

    def test_a_corrupted_log_is_never_overwritten(self):
        """Not a list means the log is damaged. Starting a fresh one over the
        top would destroy the only record of what the engine did."""
        with open(self.log, "w", encoding="utf-8") as f:
            f.write('{"step": "listen"}')
        with self.assertRaises(RuntimeError):
            runlog.append("assess", "listener: 12 findings", stream="Acme", runs_path=self.log)
        with open(self.log, encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"step": "listen"}')

    def test_the_default_path_is_the_engine_log(self):
        self.assertEqual(runlog.runs_file(),
                         os.path.join(REPO, "state", "runs.json"))


class CommandLineTest(unittest.TestCase):
    """The agents reach it through the shell, so the CLI is the interface."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.log = os.path.join(self.dir, "runs.json")

    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT, *args, "--stream", "Acme", "--runs", self.log],
                              capture_output=True, text=True)

    def test_two_calls_append_rather_than_replace(self):
        self.assertEqual(self.run_cli("assess", "listener: 12 findings").returncode, 0)
        self.assertEqual(self.run_cli("gate", "gatekeeper: 1 block").returncode, 0)
        runs = read_log(self.log)
        self.assertEqual([e["step"] for e in runs], ["assess", "gate"])
        self.assertEqual(runs[1]["detail"], "gatekeeper: 1 block")

    def test_a_detail_less_call_fails_loudly(self):
        proc = self.run_cli("gate", "")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("detail", proc.stderr)
        self.assertFalse(os.path.exists(self.log))


class AgentDefinitionTest(unittest.TestCase):
    """Each of the four agents carries its own call, and can run it."""

    def test_each_agent_owns_one_step(self):
        for filename, step in CYCLE:
            cmd = agent_command(filename)
            self.assertRegex(cmd, rf"^engine runlog {step}\b",
                             f"{filename} does not log `{step}`")

    def test_no_agent_writes_the_log_any_other_way(self):
        """A hard rule per agent, so the run is not finished until it logs."""
        for filename, step in CYCLE:
            rules = read_text(os.path.join(AGENTS, filename)).split(
                "## hard rules", 1)[1]
            self.assertIn("runs.json", rules, filename)
            self.assertIn("never by editing the file", rules, filename)

    def test_the_writer_can_actually_run_its_command(self):
        """`theme-writer` held no Bash, so the tool list is part of the
        deliverable: without it the call in its definition is prose."""
        text = read_text(os.path.join(AGENTS, "theme-writer.md"))
        tools = re.search(r"^tools:\s*(\[.*\])\s*$", text, re.M)
        self.assertIsNotNone(tools, "theme-writer declares a tool list")
        self.assertIn("Bash", json.loads(tools.group(1)))
        self.assertNotIn("You have no Bash", text)

    def test_the_cycle_never_writes_the_log_by_hand(self):
        cycle = read_text(os.path.join(ENGINE, "commands",
                                       "social-cycle.md"))
        never = cycle.split("## never", 1)[1]
        self.assertIn("runs.json", never)


class CycleRehearsalTest(unittest.TestCase):
    """One cycle's worth of logging, running the definitions' own commands.

    This is the stand-in for `/social-cycle`: the four agent rows are produced
    by executing exactly the command lines the four definitions carry, in the
    order the cycle spawns them, interleaved with the rows the scripted steps
    write. What it proves is that a completed cycle leaves one entry per agent,
    in order, with nothing typed by hand.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.log = os.path.join(self.dir, "runs.json")

    def scripted(self, step, detail):
        runlog.append(step, detail, stream="Acme", runs_path=self.log)

    def agent(self, filename):
        cmd = f"{agent_command(filename)} --runs {self.log}"
        env = dict(os.environ, PATH=os.path.join(ENGINE, "bin") + os.pathsep + os.environ.get("PATH", ""))
        proc = subprocess.run(cmd, shell=True, cwd=REPO, env=env,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_one_entry_per_agent_in_order(self):
        self.scripted("listen", "listen.py: 27 items, 2 terms")
        self.agent("listener.md")
        self.scripted("inventory", "inventory-refresh: 11 rows, 2 paid checks")
        self.agent("theme-writer.md")
        self.scripted("gate", "review.py: 2 pass, 0 pass-with-edits, 1 block; nothing approved")
        self.scripted("edits", "apply_edits: 1 applied")
        self.agent("distributor.md")
        self.scripted("publish", "publish.py: Q-3")

        runs = read_log(self.log)
        steps = [e["step"] for e in runs]
        self.assertEqual([s for s in steps if s in runlog.AGENT_STEPS],
                         ["assess", "draft", "gate", "distribute"])
        self.assertEqual(len(steps), 8, "every step logged exactly once")
        for entry in runs:
            self.assertTrue(entry["detail"].strip(), entry["step"])
        stamps = [e["at"] for e in runs]
        self.assertEqual(stamps, sorted(stamps), "the log runs forwards")

    def test_a_re_gate_after_a_desk_edit_logs_again(self):
        """`/social-cycle` step 6 re-spawns the gate over the ids whose edits
        landed. That is a second reading, and it gets its own row."""
        self.scripted("gate", "review.py: 1 pass, 0 pass-with-edits, 0 block; nothing approved")
        self.scripted("edits", "apply_edits: 1 applied")
        self.scripted("gate", "review.py: 1 pass, 0 pass-with-edits, 0 block; nothing approved")
        steps = [e["step"] for e in read_log(self.log)]
        self.assertEqual(steps, ["gate", "edits", "gate"])


if __name__ == "__main__":
    unittest.main()
