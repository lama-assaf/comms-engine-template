"""
engine.py: the console runs nothing real here, and says exactly what it would run.

Every spawn goes through two seams, `engine.run_cmd` and `engine.run_launchctl`,
and both are replaced in every test, so no job, no launchctl and no dry run
ever starts from the suite. What is asserted:

- names: a short name and a label are one job; an unknown name is exit 2
- `run` without --live builds the dry argv (cycle, corpus, autopilot); --live
  is refused for autopilot, x-stream and nosleep before anything is spawned;
  --live elsewhere goes through runjob.py by label; nosleep has nothing to dry-run
- `enable` shells out to install.sh --only <label>, carries the installed
  plist's CLAUDE_CONFIG_DIR when the shell lacks one, and refuses a job that
  is running; `disable` boots out gui/<uid>/<label> through run_launchctl and
  never fails
- `status()` has the four keys and the three summary lines; a stale job is
  unhealthy, nosleep and the optional stream are not
- `doctor()` over a fake command list: one line per check, ok/FAIL, the last
  stderr line after `--`, the count line last
- `setup` headless with flags writes only the keys given into a temp
  engine.local.json, types them by the current value, refuses the three bad
  values and an unknown key, writes a `~` root as __HOME__, marks the keys no
  script reads yet, ends with the dry run and the not-loaded hint
- `logs` tails the repo log and launchd's; `last_cycle` reads schedule.log,
  the `exit N` line first and the Error heuristic for blocks without one
- `onboard-stream` says so when onboard.py is absent
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

sys.path.insert(0, HERE)
import config  # noqa: E402
import engine  # noqa: E402
import fixture_memory  # noqa: E402
import jobs_status  # noqa: E402


def setUpModule():
    # The checkout may have been stamped with any brand by `engine.py init`;
    # these tests answer for the fixture brand (acme) through fixture_memory.
    fixture_memory.install()
    # `plugins` reads one key of this checkout's per-machine Claude settings; the suite reads none.
    # Assigned by hand, not through mock.patch: some classes here call mock.patch.stopall().
    global _SETTINGS_LOCAL
    _SETTINGS_LOCAL = engine.SETTINGS_LOCAL
    engine.SETTINGS_LOCAL = os.path.join(tempfile.gettempdir(), "no-such-claude-settings.local.json")


def tearDownModule():
    engine.SETTINGS_LOCAL = _SETTINGS_LOCAL
    fixture_memory.uninstall()


def proc(argv, rc=0, out="", err=""):
    return subprocess.CompletedProcess(argv, rc, stdout=out, stderr=err)


FAKE_ROWS = [
    {"job": "com.acme.corpus-cycle", "what": "corpus", "loaded": True, "last_run": "2026-11-05T06:30", "state": "ok"},
    {"job": "com.acme.social-engine", "what": "cycle", "loaded": True, "last_run": "2026-11-05T07:15", "state": "ok"},
    {"job": "com.acme.engagement", "what": "engage", "loaded": True, "last_run": "2026-09-07T21:11", "state": "stale (58.9 d)"},
    {"job": "com.acme.x-stream", "what": "stream", "loaded": False, "last_run": None, "state": "not loaded"},
    {"job": "com.acme.nosleep", "what": "caffeinate", "loaded": False, "last_run": None, "state": "not loaded"},
]


class Seams(unittest.TestCase):
    """Every test records what would have been spawned and spawns nothing."""

    def setUp(self):
        self.spawned = []
        self.launchctl = []
        self.rc = {}

        def fake_run_cmd(argv, timeout=None, capture=False, cwd=None, env=None, stdin=None):
            self.spawned.append(list(argv))
            return proc(argv, self.rc.get(tuple(argv), 0), out="", err="")

        def fake_launchctl(args, timeout=20):
            self.launchctl.append(list(args))
            if args[0] == "list":
                return proc(args, 0, out="-\t0\tcom.acme.nosleep\n")
            return proc(args, self.rc.get(("launchctl", *args), 0))

        self.p1 = mock.patch.object(engine, "run_cmd", fake_run_cmd)
        self.p2 = mock.patch.object(engine, "run_launchctl", fake_launchctl)
        self.p1.start()
        self.p2.start()
        self.addCleanup(self.p1.stop)
        self.addCleanup(self.p2.stop)
        self.dir = tempfile.mkdtemp()
        self.local = os.path.join(self.dir, "engine.local.json")
        self.p3 = mock.patch.object(config, "LOCAL_JSON", self.local)
        self.p3.start()
        self.addCleanup(self.p3.stop)

    def quiet(self, fn, *a, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = fn(*a, **kw)
        return rc, buf.getvalue()

    def setup(self, *a, **kw):
        """engine.setup with its output swallowed; returns what was written."""
        return self.quiet(engine.setup, *a, **kw)[0]


class Names(Seams):
    def test_short_and_label_are_one_job(self):
        for short, label in engine.SHORT.items():
            self.assertEqual(engine.label_for(short), label)
            self.assertEqual(engine.label_for(label), label)
            self.assertEqual(engine.short_for(label), short)
        with self.assertRaises(engine.UnknownJob):
            engine.label_for("bogus")
        rc, out = self.quiet(engine.main, ["run", "bogus"])
        self.assertEqual(rc, 2)
        self.assertIn("unknown job", out)
        self.assertEqual(self.spawned, [])

    def test_every_short_name_is_in_engine_json(self):
        labels = {j["label"] for j in config.jobs()}
        self.assertEqual(set(engine.SHORT.values()), labels)


class Run(Seams):
    def test_dry_argv_for_cycle_corpus_autopilot(self):
        rc, out = self.quiet(engine.run, "cycle")
        self.assertEqual(rc, 0)
        self.assertEqual(self.spawned, [
            ["engine", "plan_queries", "--dry-run"],
            ["engine", "listen", "--dry-run"],
        ])
        self.assertIn("$ engine plan_queries --dry-run", out)
        self.spawned.clear()
        self.quiet(engine.run, "corpus")
        root = str(config.cfg("corpus.root", ""))
        self.assertTrue(root and "__HOME__" not in root, root)
        self.assertEqual(self.spawned, [["engine", "corpus_sweep", "--root", root, "--only-todo"]])
        self.spawned.clear()
        self.quiet(engine.run, "com.acme.autopilot", live=False)
        self.assertEqual(self.spawned, [["engine", "autopilot", "run", "--dry"]])

    def test_every_dry_form_is_a_dry_form(self):
        # no dry argv runs autopilot.py post/links/run bare, nothing arms the stream
        for short, cmds in engine.DRY_FORMS.items():
            for argv in cmds:
                joined = " ".join(argv)
                if "autopilot.py" in joined:
                    self.assertIn("--dry", argv, short)
                if "x_stream.py" in joined:
                    self.assertNotIn("--apply", argv, short)
                    self.assertNotIn("listen", argv, short)
                self.assertEqual(argv[0], "engine", short)
                self.assertIsNotNone(engine.paths.expand(argv), argv[1])

    def test_corpus_pending_work_is_an_answer_not_a_failure(self):
        # corpus_sweep.py --only-todo exits 1 when sources wait; the console says so and exits 0
        def fake(argv, timeout=None, capture=False, cwd=None, env=None, stdin=None):
            self.spawned.append(list(argv))
            return proc(argv, 1 if "corpus_sweep" in argv[1] else 0)

        with mock.patch.object(engine, "run_cmd", fake):
            rc, out = self.quiet(engine.run, "corpus")
        self.assertEqual(rc, 0)
        self.assertIn("pending work found", out)
        # exit 2 (root not found) is still a fault
        with mock.patch.object(engine, "run_cmd", lambda argv, **kw: proc(argv, 2)):
            rc, _ = self.quiet(engine.run, "corpus")
        self.assertEqual(rc, 2)

    def test_dry_returns_first_failure(self):
        self.rc[("engine", "score", "--dry-run")] = 4
        rc, _ = self.quiet(engine.run, "score")
        self.assertEqual(rc, 4)
        self.assertEqual(len(self.spawned), 2)

    def test_nosleep_has_nothing_to_dry_run(self):
        rc, out = self.quiet(engine.run, "nosleep")
        self.assertEqual(rc, 0)
        self.assertIn("nothing to dry-run", out)
        self.assertEqual(self.spawned, [])

    def test_live_refused_for_three_labels_before_any_spawn(self):
        for short in ("autopilot", "x-stream", "nosleep"):
            rc, out = self.quiet(engine.run, short, live=True)
            self.assertEqual(rc, 3, short)
            self.assertIn("refused", out)
        self.assertEqual(self.spawned, [])
        rc, _ = self.quiet(engine.main, ["run", "autopilot", "--live"])
        self.assertEqual(rc, 3)

    def test_live_elsewhere_goes_through_runjob_by_label(self):
        rc, out = self.quiet(engine.run, "cycle", live=True)
        self.assertEqual(rc, 0)
        self.assertEqual(self.spawned, [["engine", "runjob", "com.acme.social-engine"]])
        self.assertIn("$ engine runjob com.acme.social-engine", out)

    def test_cli_default_is_dry(self):
        rc, out = self.quiet(engine.main, ["run", "claims-check"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.spawned, [["engine", "claims_check", "--dry-run"]])


class EnableDisable(Seams):
    def test_enable_shells_out_to_install_sh_only(self):
        rc, out = self.quiet(engine.enable, "autopilot")
        self.assertEqual(rc, 0)
        self.assertEqual(self.spawned, [["/bin/bash", engine.INSTALL_SH,
                                         "--only", "com.acme.autopilot"]])
        self.assertIn("$ engine install --only com.acme.autopilot", out)
        # enable reads `launchctl list` once (is the job mid-run?) and never loads anything itself
        self.assertEqual(self.launchctl, [["list"]])

    def test_enable_carries_the_installed_plists_config_dir(self):
        import plistlib
        agents = os.path.join(self.dir, "LaunchAgents")
        os.makedirs(agents)
        with open(os.path.join(agents, "com.acme.social-engine.plist"), "wb") as f:
            plistlib.dump({"Label": "com.acme.social-engine",
                           "EnvironmentVariables": {"CLAUDE_CONFIG_DIR": "/home/someone/.claude-acme"}}, f)
        envs = []

        def fake(argv, timeout=None, capture=False, cwd=None, env=None, stdin=None):
            envs.append(env)
            return proc(argv, 0)

        plain = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
        with mock.patch.object(engine, "LAUNCH_AGENTS", agents), mock.patch.object(engine, "run_cmd", fake), \
             mock.patch.dict(os.environ, plain, clear=True):
            rc, out = self.quiet(engine.enable, "cycle")
            self.assertEqual(rc, 0)
            # the shell had none, the plist had one: the reload keeps the job's login
            self.assertEqual(envs[0]["CLAUDE_CONFIG_DIR"], "/home/someone/.claude-acme")
            self.assertIn("CLAUDE_CONFIG_DIR=/home/someone/.claude-acme", out)
            # a job with no installed plist and no variable: said so, env untouched
            envs.clear()
            rc, out = self.quiet(engine.enable, "score")
            self.assertIsNone(envs[0])
            self.assertIn("CLAUDE_CONFIG_DIR unset", out)
        # the shell's own value wins over the plist and is shown
        with mock.patch.object(engine, "LAUNCH_AGENTS", agents), mock.patch.object(engine, "run_cmd", fake), \
             mock.patch.dict(os.environ, {**plain, "CLAUDE_CONFIG_DIR": "/home/someone/.claude-other"}, clear=True):
            envs.clear()
            rc, out = self.quiet(engine.enable, "cycle")
            self.assertIsNone(envs[0])
            self.assertIn("CLAUDE_CONFIG_DIR=/home/someone/.claude-other", out)

    def test_enable_refuses_a_job_that_is_running(self):
        def fake_launchctl(args, timeout=20):
            self.launchctl.append(list(args))
            return proc(args, 0, out="4242\t0\tcom.acme.social-engine\n49609\t0\tcom.acme.nosleep\n")

        with mock.patch.object(engine, "run_launchctl", fake_launchctl):
            rc, out = self.quiet(engine.enable, "cycle")
            self.assertEqual(rc, 1)
            self.assertIn("running now (pid 4242)", out)
            self.assertEqual(self.spawned, [])
            # a keep_alive job restarts by design: caffeinate's pid is no refusal
            rc, _ = self.quiet(engine.enable, "nosleep")
            self.assertEqual(rc, 0)
            self.assertEqual(len(self.spawned), 1)

    def test_enable_returns_install_exit(self):
        key = ("/bin/bash", engine.INSTALL_SH, "--only", "com.acme.score")
        self.rc[key] = 1
        rc, _ = self.quiet(engine.enable, "score")
        self.assertEqual(rc, 1)

    def test_disable_boots_out_by_uid_and_never_fails(self):
        target = f"gui/{os.getuid()}/com.acme.social-engine"
        rc, out = self.quiet(engine.disable, "cycle")
        self.assertEqual(rc, 0)
        self.assertEqual(self.launchctl, [["bootout", target]])
        self.assertIn(f"$ launchctl bootout {target}", out)
        self.assertIn("booted out com.acme.social-engine", out)
        self.rc[("launchctl", "bootout", target)] = 3
        rc, out = self.quiet(engine.disable, "cycle")
        self.assertEqual(rc, 0)
        self.assertIn("not loaded com.acme.social-engine", out)
        self.assertEqual(self.spawned, [])

    def test_unknown_label_is_2(self):
        for cmd in ("enable", "disable", "logs"):
            rc, _ = self.quiet(engine.main, [cmd, "nope"])
            self.assertEqual(rc, 2, cmd)
        self.assertEqual(self.spawned, [])
        self.assertEqual(self.launchctl, [])


class FakeSecrets:
    _BACKENDS = (("environment", lambda n: "x" if n == "APIFY_TOKEN" else None),
                 ("macOS keychain", lambda n: None))


class Status(Seams):
    def setUp(self):
        super().setUp()
        mock.patch.object(jobs_status, "rows", lambda now=None, loaded=None: list(FAKE_ROWS)).start()
        mock.patch.object(engine, "_engine_secrets", lambda: FakeSecrets).start()
        mock.patch.object(engine, "_claude_plugin_list", lambda: {"atelier@atelier"}).start()
        self.addCleanup(mock.patch.stopall)

    def test_shape_and_lines(self):
        st = engine.status(env={})
        self.assertEqual(set(st), {"jobs", "secrets", "plugins", "last_cycle", "workflows"})
        self.assertEqual(st["jobs"], FAKE_ROWS)
        self.assertEqual({s["name"]: s["present"] for s in st["secrets"] if s["required"]},
                         {"TWITTERAPI_IO_API_KEY": False})
        self.assertEqual(st["plugins"], [{"name": "atelier@atelier", "installed": True},
                                         {"name": "salon@atelier", "installed": False},
                                         {"name": "motion@atelier", "installed": False}])
        self.assertEqual(set(st["last_cycle"]), {"at", "budget_usd", "exit"})
        # never a value: every secret row carries only a name, a backend and a flag
        for s in st["secrets"]:
            self.assertNotIn("value", s)
        lines = engine.status_lines(st)
        self.assertTrue(lines[0].startswith("job"))
        self.assertIn("secrets   0/1 present (missing TWITTERAPI_IO_API_KEY)", lines)
        self.assertIn("plugins   1/3 installed (atelier@atelier)", lines)
        self.assertTrue(lines[-1].startswith("last cycle "), lines[-1])
        self.assertIn("budget", lines[-1])
        self.assertEqual(engine.status_rows(), FAKE_ROWS)

    def test_unhealthy_excludes_nosleep_and_optional(self):
        st = engine.status(env={})
        self.assertEqual(engine.status_unhealthy(st), ["com.acme.engagement"])
        rc, _ = self.quiet(engine.main, ["status"])
        self.assertEqual(rc, 1)
        rc, out = self.quiet(engine.main, ["status", "--json"])
        self.assertEqual(set(json.loads(out)), {"jobs", "secrets", "plugins", "last_cycle", "workflows"})

    def test_status_hands_jobs_status_the_loaded_set_from_the_one_seam(self):
        # jobs_status.rows() would spawn launchctl itself; engine passes what run_launchctl read
        seen = []
        with mock.patch.object(jobs_status, "rows", lambda now=None, loaded=None: seen.append(loaded) or list(FAKE_ROWS)), \
             mock.patch.object(jobs_status, "loaded_labels", side_effect=AssertionError("spawned launchctl")):
            engine.status(env={})
            engine.status_rows()
        self.assertEqual(seen, [{"com.acme.nosleep"}, {"com.acme.nosleep"}])
        self.assertEqual(self.launchctl, [["list"], ["list"]])

    def test_plugins_unknown_when_claude_absent(self):
        with mock.patch.object(engine, "_claude_plugin_list", lambda: None):
            st = engine.status(env={})
            self.assertTrue(all(p["installed"] is None for p in st["plugins"]))
            self.assertIn("plugins   unknown", "\n".join(engine.status_lines(st)))
            rc, out = self.quiet(engine.plugins_cmd)
            self.assertEqual(rc, 0)
            self.assertIn("unknown", out)

    def test_plugins_cmd_names_the_install_command(self):
        rc, out = self.quiet(engine.plugins_cmd)
        self.assertEqual(rc, 1)
        market = config.cfg("plugins.marketplace", "")
        self.assertIn(f"marketplace: {market}" if market else "marketplace: (not set: config.py set plugins.marketplace", out)
        self.assertIn("salon@atelier: not installed  -> claude plugin install salon@atelier --scope project", out)

    def test_secrets_cmd_names_the_set_command(self):
        rc, out = self.quiet(engine.secrets_cmd)
        self.assertEqual(rc, 1)
        self.assertIn("APIFY_TOKEN: present (environment; optional)", out)
        self.assertIn("TWITTERAPI_IO_API_KEY: MISSING  -> engine secrets --set TWITTERAPI_IO_API_KEY", out)
        self.assertEqual(self.spawned, [])

    def test_secrets_set_needs_a_terminal(self):
        with mock.patch.object(sys.stdin, "isatty", lambda: False):
            rc, out = self.quiet(engine.main, ["secrets", "--set", "APIFY_TOKEN"])
        self.assertEqual(rc, 2)
        self.assertIn("needs a terminal", out)
        self.assertEqual(self.spawned, [])


class LastCycle(Seams):
    def test_reads_the_last_block(self):
        log = os.path.join(self.dir, "schedule.log")
        with open(log, "w") as f:
            f.write("=== social-cycle 2026-11-04T07:15:00Z  (claude 2.1) ===\nfine\n"
                    "=== social-cycle 2026-11-05T17:38:38Z --no-listen (claude 2.1) ===\nBudget limit reached\nError: Exceeded USD budget (8)\n")
        lc = engine.last_cycle(log, env={})
        self.assertEqual(lc["at"], "2026-11-05T17:38:38Z")
        self.assertEqual(lc["exit"], 1)
        self.assertEqual(lc["budget_usd"], 20)
        with open(log, "a") as f:
            f.write("=== social-cycle 2026-11-06T07:15:00Z  (claude 2.1) ===\ndone\n")
        self.assertEqual(engine.last_cycle(log, env={})["exit"], 0)
        self.assertEqual(engine.last_cycle(os.path.join(self.dir, "none.log"), env={})["exit"], None)

    def test_exit_line_outranks_the_error_heuristic(self):
        log = os.path.join(self.dir, "schedule.log")
        with open(log, "w") as f:
            f.write("=== social-cycle 2026-11-06T07:15:00Z  (claude 2.1) ===\nError: one the cycle handled\n"
                    "=== social-cycle exit 0 ===\n")
        lc = engine.last_cycle(log, env={})
        self.assertEqual((lc["at"], lc["exit"]), ("2026-11-06T07:15:00Z", 0))
        with open(log, "a") as f:
            f.write("=== social-cycle 2026-11-07T07:15:00Z  (claude 2.1) ===\nall fine\n=== social-cycle exit 7 ===\n")
        lc = engine.last_cycle(log, env={})
        self.assertEqual((lc["at"], lc["exit"]), ("2026-11-07T07:15:00Z", 7))
        # the exit line never opens a block of its own
        self.assertNotEqual(lc["at"], "exit")


class Doctor(Seams):
    def test_lines_over_a_fake_command_list(self):
        checks = ["python3 ok.py --dry-run", "python3 bad.py"]
        self.rc[("python3", "bad.py")] = 1

        def fake(argv, timeout=None, capture=False, cwd=None, env=None, stdin=None):
            self.spawned.append(list(argv))
            if argv[1] == "bad.py":
                return proc(argv, 1, out="partial\n", err="first error\nTraceback: the reason\n")
            return proc(argv, 0, out="fine\n")

        with mock.patch.object(engine, "run_cmd", fake):
            results = engine.doctor(checks=checks)
        self.assertEqual([r["check"] for r in results], checks)
        self.assertEqual([r["ok"] for r in results], [True, False])
        self.assertEqual(set(results[0]), {"check", "ok", "seconds", "tail"})
        lines = engine.doctor_lines(results)
        self.assertRegex(lines[0], r"^ok    +\d+\.\ds  python3 ok\.py --dry-run$")
        self.assertRegex(lines[1], r"^FAIL  +\d+\.\ds  python3 bad\.py  -- Traceback: the reason$")
        self.assertEqual(lines[-1], "doctor: 1 ok, 1 failed")
        self.assertEqual(self.spawned, [["python3", "ok.py", "--dry-run"], ["python3", "bad.py"]])

    def test_guardrails_answer_is_not_a_failure(self):
        check = next(c for c in engine.DOCTOR_CHECKS if c.startswith("engine guardrails "))

        def fake(argv, timeout=None, capture=False, cwd=None, env=None, stdin=None):
            return proc(argv, 1, out="refused: Acme: 19:48 is after 18:00\n")

        with mock.patch.object(engine, "run_cmd", fake):
            results = engine.doctor(checks=[check, "python3 other.py"])
        self.assertEqual([r["ok"] for r in results], [True, False])
        lines = engine.doctor_lines(results)
        self.assertRegex(lines[0], r"^ok    +\d+\.\ds  engine guardrails --stream acme --channel X  -- refused: Acme: 19:48 is after 18:00$")
        # exit 2 is still a fault for the informational check
        with mock.patch.object(engine, "run_cmd", lambda argv, **kw: proc(argv, 2, err="usage")):
            self.assertFalse(engine.doctor(checks=[check])[0]["ok"])

    def test_default_checks_are_claude_md_plus_config_and_secrets(self):
        results = engine.doctor(env={})
        cmds = [r["check"] for r in results]
        self.assertEqual(cmds[0], f"python3 -m unittest discover {engine._shown(os.path.join(engine.ENGINE, 'tests'))}")
        self.assertIn("engine config show", cmds)
        self.assertEqual(cmds[-1], "engine secrets --check TWITTERAPI_IO_API_KEY")
        for c in cmds:
            # every check is a dry form: nothing in the doctor posts or arms a rule
            self.assertNotIn("--apply", c)
            self.assertNotIn("autopilot.py", c)
        self.assertEqual(len(self.spawned), len(cmds))
        with mock.patch.object(engine, "channel_doctor_results", return_value=[]), \
                mock.patch.object(engine, "plugin_doctor_results", return_value=[]), \
                mock.patch.object(engine, "engine_version_result", return_value={"check": "v", "ok": True, "seconds": 0.0, "tail": ""}), \
                mock.patch.object(engine, "claude_token_result", return_value={"check": "t", "ok": True, "seconds": 0.0, "tail": ""}):
            # the composio, plugin and engine-version lines have their own tests
            rc, out = self.quiet(engine.main, ["doctor"])
        self.assertEqual(rc, 0)
        self.assertIn(f"doctor: {len(cmds) + 2} ok, 0 failed", out)


class Setup(Seams):
    def test_headless_writes_only_the_flags_given(self):
        rc, out = self.quiet(engine.main, ["setup", "cycle", "--drafts", "4", "--editor", "no"])
        self.assertEqual(rc, 0)
        with open(self.local) as f:
            doc = json.load(f)
        self.assertEqual(doc, {"params": {"cycle": {"drafts": 4, "weekday_flags": {"editor": False}}}})
        self.assertIn("drafts = 4 (flag)", out)
        self.assertIn("editor = false (flag)", out)
        self.assertIn("budget_usd = 20 (default)", out)
        self.assertIn(f"wrote {self.local}: cycle.drafts, cycle.weekday_flags.editor", out)
        # the schedule is shown, not asked
        self.assertIn("schedule  Mon-Fri 07:15", out)
        # ends with the dry run and the not-loaded hint (the fake launchctl list has nosleep only)
        self.assertIn("$ engine plan_queries --dry-run", out)
        self.assertIn("not loaded; enable with: engine.py enable cycle", out)
        self.assertEqual(self.launchctl, [["list"]])

    def test_api_returns_the_paths_written_and_types_values(self):
        written = self.setup("score", {"x_metrics": "false", "demand": True}, interactive=False, env={}, local=self.local)
        self.assertEqual(written, {"score.x_metrics": False, "score.demand": True})
        self.assertEqual(config.cfg("score.x_metrics", env={}, local=self.local), False)
        written = self.setup("corpus", {"include": "a, b", "max": "2"}, interactive=False, env={}, local=self.local)
        self.assertEqual(written, {"corpus.include": ["a", "b"], "corpus.max": 2})

    def test_keys_no_script_reads_are_said_so(self):
        rc, out = self.quiet(engine.main, ["setup", "score", "--demand", "no"])
        self.assertEqual(rc, 0)
        self.assertIn("demand = false (flag; recorded, not read by any script yet)", out)
        self.assertIn("x_metrics = true (default; recorded, not read by any script yet)", out)
        rc, out = self.quiet(engine.main, ["setup", "cycle", "--drafts", "2"])
        self.assertIn("drafts = 2 (flag)", out)  # a key cycle.sh reads carries no note
        self.assertIn("max_per_term = 12 (default; recorded, not read by any script yet)", out)
        # no setup offers an `on` switch: the jobs run while loaded, and only enable/disable change that
        for short, qs in engine.QUESTIONS.items():
            self.assertNotIn("on", [k for k, _, _ in qs], short)
        for path in engine.INERT:
            self.assertIn(path, {p for qs in engine.QUESTIONS.values() for _, p, _ in qs}, path)

    def test_unknown_key_is_refused_before_anything_is_written(self):
        rc, out = self.quiet(engine.main, ["setup", "cycle", "--draft", "4"])
        self.assertEqual(rc, 1)
        self.assertIn("unknown key(s) draft", out)
        self.assertIn("keys: budget_usd, drafts", out)
        self.assertFalse(os.path.exists(self.local))
        self.assertEqual(self.spawned, [])  # no dry run either
        # the cycle's extra flag is known
        written = self.setup("cycle", {"linkedin_reason": "a week"}, interactive=False, env={}, local=self.local)
        self.assertEqual(written, {})

    def test_tilde_root_is_written_as_the_home_placeholder(self):
        written = self.setup("corpus", {"root": "~"}, interactive=False, env={}, local=self.local)
        self.assertEqual(written, {"corpus.root": "__HOME__"})
        with open(self.local) as f:
            self.assertEqual(json.load(f)["params"]["corpus"]["root"], "__HOME__")
        self.assertEqual(config.cfg("corpus.root", env={}, local=self.local), os.path.expanduser("~"))
        # the dry run that closes the setup reads the expanded root
        self.assertIn(["engine", "corpus_sweep", "--root", os.path.expanduser("~"), "--only-todo"],
                      self.spawned)
        self.assertEqual(engine._home_placeholder(os.path.join(os.path.expanduser("~"), "Desktop", "x")), "__HOME__/Desktop/x")
        self.assertEqual(engine._home_placeholder("/elsewhere/x"), "/elsewhere/x")

    def test_nothing_given_writes_nothing(self):
        written = self.setup("claims-check", {}, interactive=False, env={}, local=self.local)
        self.assertEqual(written, {})
        self.assertFalse(os.path.exists(self.local))

    def test_refusals(self):
        with self.assertRaises(engine.Refused):
            self.setup("cycle", {"max_per_term": "13"}, interactive=False, env={}, local=self.local)
        with self.assertRaises(engine.Refused):
            self.setup("cycle", {"linkedin": "yes"}, interactive=False, env={}, local=self.local)
        with self.assertRaises(engine.Refused):
            self.setup("corpus", {"root": os.path.join(self.dir, "nowhere")}, interactive=False, env={}, local=self.local)
        self.assertFalse(os.path.exists(self.local))
        written = self.setup("cycle", {"linkedin": "yes", "linkedin_reason": "a campaign week"},
                               interactive=False, env={}, local=self.local)
        self.assertEqual(written, {"cycle.linkedin": True})
        written = self.setup("corpus", {"root": self.dir}, interactive=False, env={}, local=self.local)
        self.assertEqual(written, {"corpus.root": self.dir})
        rc, out = self.quiet(engine.main, ["setup", "cycle", "--max-per-term", "20"])
        self.assertEqual(rc, 1)
        self.assertIn("refused", out)

    def test_score_shows_the_reads_and_the_baseline_rule(self):
        rc, out = self.quiet(engine.setup, "score", {}, interactive=False, env={}, local=self.local)
        self.assertRegex(out, r"reads     \d+ file\(s\) under state/metrics-input/")
        self.assertIn("baseline  the median score", out)

    def test_autopilot_shows_the_channel_rule(self):
        rc, out = self.quiet(engine.setup, "autopilot", {"grace_days": "3"}, interactive=False, env={}, local=self.local)
        self.assertEqual(rc, {"autopilot.grace_days": 3})
        self.assertIn("channel rule (streams.md, acme):", out)
        self.assertIn("to change it, add a decision under .atelier/memory/decisions/, set streams.acme.autopilot "
                      "in brand.json and run engine.py apply", out)
        self.assertEqual(self.spawned, [["engine", "autopilot", "run", "--dry"]])

    def test_interactive_only_on_a_terminal(self):
        # interactive=None reads sys.stdin.isatty(): false here, so nothing is asked
        with mock.patch.object(sys.stdin, "isatty", lambda: False), mock.patch("builtins.input", side_effect=AssertionError("asked")):
            self.setup("engagement", {}, env={}, local=self.local)
        # on a terminal every question is asked; an empty answer keeps the value, a typed one is written
        answers = iter(["", "yes"])
        with mock.patch("builtins.input", lambda prompt: next(answers)):
            written = self.setup("autopilot", {}, interactive=True, env={}, local=self.local)
        self.assertEqual(written, {"autopilot.commit": True})
        with open(self.local) as f:
            self.assertEqual(json.load(f), {"params": {"autopilot": {"commit": True}}})

    def test_unknown_job_and_nosleep(self):
        rc, _ = self.quiet(engine.main, ["setup", "nope"])
        self.assertEqual(rc, 2)
        rc, out = self.quiet(engine.main, ["setup", "nosleep"])
        self.assertEqual(rc, 0)
        self.assertIn("nothing to set up", out)
        self.assertFalse(os.path.exists(self.local))

    def test_setup_flags_parse(self):
        self.assertEqual(engine._setup_flags(["--root", "/x y", "--max", "4", "--apply", "--extra-roots=a,b"]),
                         {"root": "/x y", "max": "4", "apply": "true", "extra_roots": "a,b"})
        with self.assertRaises(engine.Refused):
            engine._setup_flags(["stray"])


class Logs(Seams):
    def test_tails_both_logs(self):
        repo = self.dir
        os.makedirs(os.path.join(repo, "state"))
        with open(os.path.join(repo, "state/corpus-cycle.log"), "w") as f:
            f.write("".join(f"line {i}\n" for i in range(50)))
        ld = os.path.join(self.dir, "Logs")
        os.makedirs(ld)
        with open(os.path.join(ld, "com.acme.corpus-cycle.log"), "w") as f:
            f.write("launchd 1\nlaunchd 2\n")
        with mock.patch.object(engine, "REPO", repo), mock.patch.object(engine, "LAUNCHD_LOGS", ld):
            lines = engine.logs("corpus", n=3)
            self.assertEqual(lines[0], f"== {repo}/state/corpus-cycle.log (last 3) ==")
            self.assertEqual(lines[1:4], ["line 47", "line 48", "line 49"])
            self.assertEqual(lines[4], f"== {ld}/com.acme.corpus-cycle.log (last 3) ==")
            self.assertEqual(lines[5:], ["launchd 1", "launchd 2"])
            rc, out = self.quiet(engine.main, ["logs", "corpus", "-n", "2"])
            self.assertEqual(rc, 0)
            self.assertIn("line 49", out)
            # nosleep has no repo log; with no launchd log either the CLI exits 1
            rc, out = self.quiet(engine.main, ["logs", "nosleep"])
            self.assertEqual(rc, 1)
            self.assertIn("no log yet", out)
            # a bare or non-numeric -n is usage (2), never a traceback
            for argv in (["logs", "corpus", "-n"], ["logs", "corpus", "-n", "x"]):
                rc, out = self.quiet(engine.main, argv)
                self.assertEqual(rc, 2, argv)
                self.assertIn("usage: engine.py logs", out)


class Onboard(Seams):
    def test_absent_onboard_py_is_a_line(self):
        with mock.patch.object(engine, "HERE", self.dir):
            rc, out = self.quiet(engine.main, ["onboard-stream", "beta"])
        self.assertEqual(rc, 2)
        self.assertIn("onboard.py is not in this engine yet", out)
        self.assertEqual(self.spawned, [])

    def test_present_onboard_py_gets_the_argv(self):
        with open(os.path.join(self.dir, "onboard.py"), "w") as f:
            f.write("import json, sys\ndef main(argv):\n    print('onboard ' + json.dumps(argv))\n    return 7\n")
        with mock.patch.object(engine, "HERE", self.dir):
            rc, out = self.quiet(engine.main, ["onboard-stream", "beta", "--dry-run"])
        self.assertEqual(rc, 7)
        self.assertIn('onboard ["beta", "--dry-run"]', out)
        self.assertIn("$ engine onboard beta --dry-run", out)


class Cli(Seams):
    def test_usage(self):
        rc, out = self.quiet(engine.main, [])
        self.assertEqual(rc, 2)
        self.assertIn("engine.py", out)
        rc, _ = self.quiet(engine.main, ["--help"])
        self.assertEqual(rc, 0)
        rc, _ = self.quiet(engine.main, ["frobnicate"])
        self.assertEqual(rc, 2)
        self.assertEqual(self.spawned, [])
        self.assertEqual(self.launchctl, [])

    def test_real_seam_never_raises_on_a_missing_binary(self):
        # the one call to the real seam in the suite: a binary that is not there, so nothing runs
        self.p1.stop()
        try:
            r = engine.run_cmd(["/no/such/binary-for-engine-test"], capture=True)
        finally:
            self.p1.start()
        self.assertEqual(r.returncode, 127)
        self.assertIn("not found", r.stderr)


class PluginList(unittest.TestCase):
    """`claude plugin list --json`, read for this checkout. 2026-11-13: the plain listing
    named two plugins that had failed to load (they were installed for other checkouts),
    the console matched the names and said "installed", and no flow could call them."""

    ROWS = [
        {"id": "elsewhere@m", "enabled": True, "projectPath": "/another/checkout", "errors": None},
        {"id": "here@m", "enabled": True, "projectPath": engine.REPO, "errors": None},
        {"id": "broken@m", "enabled": True, "projectPath": engine.REPO, "errors": ["failed to load"]},
        {"id": "off@m", "enabled": False, "projectPath": engine.REPO, "errors": None},
        {"id": "machine@m", "enabled": True, "projectPath": None, "errors": None},
    ]

    def listed(self, out, rc=0):
        self.seen = []
        with mock.patch.object(engine.shutil, "which", lambda name: "/usr/bin/claude"), \
             mock.patch.object(engine, "run_cmd", lambda argv, **kw: self.seen.append(argv) or proc(argv, rc, out)):
            return engine._claude_plugin_list()

    def test_only_what_loads_in_this_checkout(self):
        self.assertEqual(self.listed(json.dumps(self.ROWS)), {"here@m", "machine@m"})
        self.assertEqual(self.seen, [["claude", "plugin", "list", "--json"]])

    def test_a_listing_that_cannot_be_read_is_unknown_never_installed(self):
        self.assertIsNone(self.listed("  > here@m\n    Status: failed to load\n"))
        self.assertIsNone(self.listed("", rc=1))
        self.assertIsNone(self.listed('{"not": "a list"}'))

    def test_headless_settings_switch_off_the_interactive_plugins(self):
        names = config.cfg("plugins.interactive_only", [])
        self.assertTrue(names, "engine.json plugins.interactive_only names the Motion plugin")
        self.assertLessEqual(set(names), set(config.cfg("plugins.names", [])))
        self.assertEqual(engine.headless_settings(), {"enabledPlugins": {n: False for n in names}})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = engine.main(["plugins", "--headless-settings"])
        self.assertEqual((rc, json.loads(buf.getvalue())), (0, engine.headless_settings()))


class PreparePlugins(unittest.TestCase):
    """`plugins --prepare`: atelier's write log goes with the engine's own logs, through one
    `env` key of the per-machine settings file, and nothing else in that file moves."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, ".claude", "settings.local.json")

    def test_writes_one_key_and_keeps_the_rest(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"permissions": {"allow": ["Bash(ls *)"]}, "env": {"OTHER": "1"}}, f)
        self.assertIsNone(engine.atelier_log_dir(self.path))
        self.assertEqual(engine.prepare_plugins(self.path, "/logs/atelier"), (self.path, "/logs/atelier", True))
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"permissions": {"allow": ["Bash(ls *)"]},
                                            "env": {"OTHER": "1", "ATELIER_LOG_DIR": "/logs/atelier"}})
        self.assertEqual(engine.atelier_log_dir(self.path), "/logs/atelier")
        self.assertEqual(engine.prepare_plugins(self.path, "/logs/atelier")[2], False, "a second run writes nothing")

    def test_a_missing_file_is_created_and_an_unreadable_one_is_left_alone(self):
        self.assertTrue(engine.prepare_plugins(self.path, "/logs/atelier")[2])
        self.assertEqual(engine.atelier_log_dir(self.path), "/logs/atelier")
        for broken in ("{ not json", '["a list"]', '{"env": "a string"}'):
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(broken)
            with self.assertRaises(engine.Refused):
                engine.prepare_plugins(self.path, "/logs/atelier")
            with open(self.path, encoding="utf-8") as f:
                self.assertEqual(f.read(), broken)

    def test_the_log_belongs_with_the_engines_own_logs(self):
        self.assertEqual(engine.atelier_log_wanted(), os.path.join(config.log_dir(), "atelier"))

    def test_plugins_says_where_the_log_goes(self):
        buf = io.StringIO()
        with mock.patch.object(engine, "_claude_plugin_list", lambda: None), contextlib.redirect_stdout(buf):
            engine.plugins_cmd()
        self.assertIn("atelier write log: ~/.claude/atelier/logs (the plugin default)  -> "
                      "engine plugins --prepare", buf.getvalue())
        with mock.patch.object(engine, "SETTINGS_LOCAL", self.path), \
             mock.patch.object(engine, "_claude_plugin_list", lambda: None):
            engine.prepare_plugins()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                engine.plugins_cmd()
        self.assertIn(f"atelier write log: {engine.atelier_log_wanted()}\n", buf.getvalue())



class Runtime(unittest.TestCase):
    """The python3 the jobs start must import every pin; a newer Python linked ahead of the
    one holding them (2026-11-13: Homebrew's 3.15, no PyYAML wheel) broke every job."""

    def fake_python(self, body):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "python3")
        with open(p, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n" + body + "\n")
        os.chmod(p, 0o755)
        return d

    def test_a_python_missing_a_pin_fails_and_says_what_to_do(self):
        r = engine.runtime(path=self.fake_python("echo 3.15.2; echo yaml PIL"))
        self.assertFalse(r["ok"])
        self.assertEqual(r["missing"], ["yaml", "PIL"])
        self.assertIn("cannot import yaml, PIL", r["line"])
        self.assertIn("pip install -r requirements.txt", r["line"])

    def test_a_python_with_every_pin_passes_and_none_on_the_path_fails(self):
        r = engine.runtime(path=self.fake_python("echo 3.14.6; echo"))
        self.assertTrue(r["ok"], r["line"])
        self.assertEqual(r["version"], "3.14.6")
        self.assertFalse(engine.runtime(path=tempfile.gettempdir() + "/no-such-dir")["ok"])

    def test_doctor_runs_it(self):
        self.assertIn("engine runtime", engine.DOCTOR_CHECKS)


class ClaudeToken(Seams):
    """The host's token lasts a year: `secrets --set` records the date, doctor warns after 330 days."""

    def test_the_doctor_line_by_age(self):
        today = engine.dt.date(2027, 11, 14)
        r = engine.claude_token_result(set_on="", today=today)
        self.assertTrue(r["ok"])
        self.assertIn("own login", r["tail"])
        self.assertEqual(engine.claude_token_result(set_on="2027-06-01", today=today)["tail"], "set 2027-06-01, 166 days ago")
        warn = engine.claude_token_result(set_on="2026-12-19", today=today)
        self.assertTrue(warn["ok"], "a warning, not a failure")
        self.assertIn("WARN", warn["tail"])
        self.assertIn("expires in 35 days", warn["tail"])
        self.assertIn("claude setup-token", warn["tail"])
        self.assertTrue(engine.claude_token_result(set_on="2026-12-19", today=engine.dt.date(2027, 11, 13))["ok"])
        self.assertNotIn("WARN", engine.claude_token_result(set_on="2026-12-20", today=today)["tail"], "330 days is not yet a warning")
        self.assertFalse(engine.claude_token_result(set_on="2026-11-13", today=today)["ok"], "past a year it has expired")
        self.assertFalse(engine.claude_token_result(set_on="last spring", today=today)["ok"])

    def test_setting_it_records_the_date_and_no_value(self):
        with mock.patch.object(engine.sys.stdin, "isatty", return_value=True):
            rc, out = self.quiet(engine.secrets_cmd, "CLAUDE_CODE_OAUTH_TOKEN")
        self.assertEqual(rc, 0)
        self.assertEqual(self.spawned[-1][-2:], ["--set", "CLAUDE_CODE_OAUTH_TOKEN"])
        with open(self.local, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["params"]["host"]["claude_token_set"], engine.dt.date.today().isoformat())
        self.assertIn("doctor warns after 330 days", out)

    def test_another_secret_records_nothing(self):
        with mock.patch.object(engine.sys.stdin, "isatty", return_value=True):
            self.quiet(engine.secrets_cmd, "APIFY_TOKEN")
        self.assertFalse(os.path.exists(self.local))


PMSET_HOST = """System-wide power settings:
Currently in use:
 standby              0
 disksleep            0
 sleep                0 (sleep prevented by caffeinate)
 autorestart          1
 womp                 1
"""
SERVE_HOST = json.dumps({"TCP": {"443": {"HTTPS": True}},
                         "Web": {"office-mac.tailnet.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:4320"}}}}})


class HostCheck(Seams):
    """`engine host-check` over faked command output: one line per thing the runbook sets up."""

    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.dir, "work", "acme-comms")
        os.makedirs(os.path.join(self.root, ".atelier", "memory"))
        with open(os.path.join(self.root, ".atelier", "memory", "handles.private.md"), "w") as f:
            f.write("| stealth |\n")
        self.answers = {
            "pmset": (0, PMSET_HOST), "defaults": (0, "comms\n"), "fdesetup": (0, "FileVault is Off.\n"),
            "serve": (0, SERVE_HOST), "rev-parse": (0, "origin/main\n"), "ls-remote": (0, "abc\tHEAD\n"),
        }

        def fake(argv, timeout=None, capture=False, cwd=None, env=None, stdin=None):
            key = "serve" if "serve" in argv else next((a for a in ("rev-parse", "ls-remote") if a in argv), argv[0])
            rc, out = self.answers.get(key, (1, ""))
            return proc(argv, rc, out=out)

        p = mock.patch.object(engine, "run_cmd", fake)
        p.start()
        self.addCleanup(p.stop)
        config.set_local("host.claude_token_set", engine.dt.date.today().isoformat(), local=self.local)
        config.set_local("backup.push", True, local=self.local)
        p = mock.patch.object(engine, "secrets_status", lambda names=None, env=None: [{"name": n, "present": True} for n in names])
        p.start()
        self.addCleanup(p.stop)

    def check(self, **kw):
        args = dict(root=self.root, home=self.dir, user="comms", serve_name="office-mac.tailnet.ts.net",
                    roles={"owner@example.com": "alpha"})
        args.update(kw)
        return {r["check"]: r for r in engine.host_checks(**args)}

    def test_a_host_set_up_by_the_runbook_passes_every_line(self):
        got = self.check()
        self.assertEqual(len(got), 7)
        self.assertEqual([c for c, r in got.items() if not r["ok"]], [], got)
        self.assertIn("1 login(s) mapped", got["tailscale serve"]["tail"])
        self.assertNotIn("owner@example.com", json.dumps(got), "a login never reaches the output")
        lines = engine.host_check_lines(list(got.values()))
        self.assertEqual(lines[-1], "host-check: 7 ok, 0 failed")

    def test_each_line_fails_on_its_own(self):
        desktop = os.path.join(self.dir, "Desktop", "acme")
        shutil.copytree(self.root, desktop)
        cases = [
            ("instance path", dict(root=desktop), "under ~/Desktop"),
            ("pmset: never sleep, restart after a power failure", {"pmset": (0, PMSET_HOST.replace("autorestart          1", "autorestart          0"))}, "sudo pmset"),
            ("pmset: never sleep, restart after a power failure", {"pmset": (0, PMSET_HOST.replace("sleep                0", "sleep                10"))}, "sleep 10"),
            ("automatic login", {"fdesetup": (0, "FileVault is On.\n")}, "FileVault is on"),
            ("automatic login", {"defaults": (1, "")}, "Automatically log in"),
            ("automatic login", {"defaults": (0, "someone-else\n")}, "another user"),
            ("tailscale serve", dict(serve_name=""), "no serve name"),
            ("tailscale serve", {"serve": (0, json.dumps({"Web": {"office-mac.tailnet.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8123"}}}}}))}, "tailscale serve --bg 4320"),
            ("tailscale serve", dict(roles={}), "host.roles"),
            ("backup remote", {"rev-parse": (128, "")}, "no upstream"),
            ("backup remote", {"ls-remote": (128, "")}, "deploy key"),
        ]
        for name, change, said in cases:
            with self.subTest(check=name, said=said):
                saved = dict(self.answers)
                self.answers.update({k: v for k, v in change.items() if k in self.answers})
                got = self.check(**{k: v for k, v in change.items() if k not in saved})
                self.answers = saved
                self.assertFalse(got[name]["ok"], got[name])
                self.assertIn(said, got[name]["tail"])
                self.assertEqual(sum(1 for r in got.values() if not r["ok"]), 1, "the others still pass")

    def test_the_token_the_denylist_and_the_push_switch(self):
        with mock.patch.object(engine, "secrets_status", lambda names=None, env=None: [{"name": n, "present": False} for n in names]):
            self.assertIn("claude setup-token", self.check()["claude token"]["tail"])
        config.set_local("host.claude_token_set", "", local=self.local)
        self.assertIn("date is not recorded", self.check()["claude token"]["tail"])
        config.set_local("host.claude_token_set", "2020-01-01", local=self.local)
        self.assertIn("expired", self.check()["claude token"]["tail"])
        os.remove(os.path.join(self.root, ".atelier", "memory", "handles.private.md"))
        self.assertIn("never through git", self.check()["private denylist"]["tail"])
        config.set_local("backup.push", False, local=self.local)
        self.assertIn("push is off", self.check()["backup remote"]["tail"])

    def test_the_parsers(self):
        self.assertEqual(engine.parse_pmset(PMSET_HOST), {"disksleep": 0, "sleep": 0, "autorestart": 1, "womp": 1})
        self.assertEqual(engine.serve_targets(SERVE_HOST, 4320), ["office-mac.tailnet.ts.net"])
        self.assertEqual(engine.serve_targets("not json", 4320), [])


class TheSuiteLine(unittest.TestCase):
    """doctor runs the engine's suite against the template it ships in, whatever instance it answers
    for, and leaves the line out for an engine Claude Code installed, which carries no checkout."""

    def test_run_against_the_template_from_any_instance(self):
        seen = []

        def fake(argv, timeout=None, capture=False, cwd=None, env=None, stdin=None):
            seen.append((argv, cwd, env))
            return proc(argv, 0)

        suite = engine.doctor_checks("acme")[0]
        self.assertIn("unittest", suite)
        with mock.patch.object(engine, "run_cmd", fake), \
                mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": "/some/instance"}):
            engine.doctor(checks=[suite, "engine validate"])
        root = engine.suite_root()
        self.assertEqual(seen[0][1], root)
        self.assertEqual(seen[0][2]["COMMS_ENGINE_INSTANCE"], root)
        self.assertNotIn("CLAUDE_PROJECT_DIR", seen[0][2])
        self.assertIsNone(seen[1][1], "every other check runs in the instance")

    def test_an_installed_engine_has_no_suite_line(self):
        with mock.patch.object(engine, "suite_root", return_value=None):
            self.assertFalse([c for c in engine.doctor_checks("acme") if "unittest" in c])
        self.assertIsNone(engine.suite_root("/home/x/.claude/plugins/cache/comms-engine/comms-engine/1.0.0"))


if __name__ == "__main__":
    unittest.main()

