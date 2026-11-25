"""
The schedules as a template (engine.json `jobs` -> launchd plists).

- every job renders to a plist that plistlib reads back, with no placeholder
  left and the repo path substituted
- every program the jobs point at exists in this checkout
- labels are unique, each job has a calendar or KeepAlive, logs land under state/
- CLAUDE_CONFIG_DIR is added only when given; no job carries a
  sender marker (every send passes channels.send(), so the hook no longer asks who runs it)
- jobs_status.py lists every job from engine.json; schedule/jobs.json is gone
  and render.py, runjob.py and install.sh all read the same `jobs`
"""
import os
import plistlib
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(ENGINE))
sys.path.insert(0, os.path.join(ENGINE, "schedule"))
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

sys.path.insert(0, HERE)
import fixture_memory  # noqa: E402
import jobs_status  # noqa: E402
import render  # noqa: E402


def setUpModule():
    # The checkout may have been stamped with any brand by `engine.py init`;
    # these tests answer for the fixture brand (acme) through fixture_memory.
    fixture_memory.install()


def tearDownModule():
    fixture_memory.uninstall()


class Render(unittest.TestCase):
    def test_renders_every_job_without_placeholders(self):
        out = tempfile.mkdtemp()
        paths = render.render_all(out, repo=REPO, home="/home/someone", config_dir=None)
        spec = render.load_jobs()
        self.assertEqual(len(paths), len(spec["jobs"]))
        labels = set()
        for p in paths:
            with open(p, "rb") as f:
                plist = plistlib.load(f)
            labels.add(plist["Label"])
            blob = repr(plist)
            self.assertNotIn("__REPO__", blob)
            self.assertNotIn("__HOME__", blob)
            self.assertTrue("StartCalendarInterval" in plist or plist.get("KeepAlive"), plist["Label"])
            self.assertNotIn("CLAUDE_CONFIG_DIR", plist["EnvironmentVariables"])
            self.assertIn("/opt/homebrew/bin", plist["EnvironmentVariables"]["PATH"])
            # launchd's own stdout lives outside the protected Desktop folder
            self.assertEqual(plist["StandardOutPath"], os.path.join("/home/someone", "Library", "Logs", "acme-comms", plist["Label"] + ".log"))
            # every job but caffeinate runs the shim at a path that never moves, which runs runjob
            if plist["ProgramArguments"][0] != "/usr/bin/caffeinate":
                self.assertEqual(plist["ProgramArguments"],
                                 ["/home/someone/.local/bin/comms-engine", "runjob", plist["Label"]])
            self.assertEqual(plist["EnvironmentVariables"]["COMMS_ENGINE_INSTANCE"], REPO)
            self.assertNotIn("ACME_REPO", plist["EnvironmentVariables"])
        self.assertEqual(len(labels), len(spec["jobs"]))

    def test_config_dir_and_no_sender_marker(self):
        out = tempfile.mkdtemp()
        render.render_all(out, repo=REPO, home="/home/someone", config_dir="/home/someone/.claude-acme", only="com.acme.autopilot")
        with open(os.path.join(out, "com.acme.autopilot.plist"), "rb") as f:
            plist = plistlib.load(f)
        self.assertEqual(plist["EnvironmentVariables"]["CLAUDE_CONFIG_DIR"], "/home/someone/.claude-acme")
        self.assertNotIn("ACME_AUTOPILOT_JOB", plist["EnvironmentVariables"])
        self.assertEqual(len(plist["StartCalendarInterval"]), 10)

    def test_runjob_builds_the_command(self):
        import runjob
        spec = render.load_jobs()
        by = {j["label"]: j for j in spec["jobs"]}
        cmd, text = runjob.command_for(by["com.acme.social-engine"], repo=REPO)
        self.assertEqual(cmd[:2], ["/bin/zsh", "-c"])
        self.assertIn("claude -p", text)
        self.assertEqual(cmd[3:], ["zsh"])
        cmd, text = runjob.command_for(by["com.acme.engagement"], repo=REPO)
        self.assertEqual(cmd[3:], ["zsh", "--only", "engage"])
        cmd, text = runjob.command_for(by["com.acme.corpus-cycle"], repo=REPO)
        self.assertIsNotNone(text) and self.assertIn("corpus_sweep", text)
        cmd, text = runjob.command_for(by["com.acme.autopilot"], repo=REPO)
        self.assertIsNone(text)
        self.assertEqual(cmd[-1], "run")
        cmd, text = runjob.command_for(by["com.acme.score"], repo=REPO)
        self.assertEqual(cmd[:2], ["/bin/zsh", "-lc"])
        self.assertIn(REPO, cmd[2])

    def test_status_lists_every_job(self):
        rows = jobs_status.rows()
        labels = {r["job"] for r in rows}
        spec = render.load_jobs()
        self.assertEqual(labels, {j["label"] for j in spec["jobs"]})
        for r in rows:
            self.assertIn(r["state"].split(" ")[0], ("ok", "stale", "loaded", "not", "loaded,"))

    def test_one_jobs_file(self):
        import runjob
        engine_json = os.path.join(ENGINE, "engine.json")
        self.assertFalse(os.path.exists(os.path.join(ENGINE, "schedule", "jobs.json")))
        self.assertEqual(render.JOBS, engine_json)
        self.assertEqual(runjob.JOBS, engine_json)
        self.assertEqual(jobs_status.ENGINE_JSON, engine_json)
        self.assertEqual([j["label"] for j in render.load_jobs()["jobs"]],
                         [j["label"] for j in runjob.load_jobs()["jobs"]])
        with open(os.path.join(ENGINE, "schedule", "install.sh"), encoding="utf-8") as f:
            self.assertIn("engine.json", f.read())


class Shim(unittest.TestCase):
    """~/.local/bin/comms-engine finds the installed engine for the instance at each start."""

    def setUp(self):
        import comms_engine_shim
        self.shim = comms_engine_shim
        self.tmp = tempfile.mkdtemp(prefix="shim-")
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)

    def engine_at(self, *parts):
        root = os.path.join(self.tmp, *parts)
        os.makedirs(os.path.join(root, "bin"))
        with open(os.path.join(root, "bin", "engine"), "w") as f:
            f.write("#!/usr/bin/env python3\n")
        return root

    def installed(self, entries):
        path = os.path.join(self.tmp, "installed_plugins.json")
        with open(path, "w") as f:
            __import__("json").dump({"version": 2, "plugins": {"comms-engine@comms-engine": entries,
                                                                 "other@x": [{"installPath": "/nowhere"}]}}, f)
        return path

    def test_the_instance_own_install_wins_then_the_user_one_then_the_newest(self):
        a, b, u = self.engine_at("cache", "1.0.0"), self.engine_at("cache", "1.1.0"), self.engine_at("cache", "0.9.0")
        inst = os.path.join(self.tmp, "brand")
        os.makedirs(inst)
        path = self.installed([
            {"scope": "project", "projectPath": os.path.join(self.tmp, "elsewhere"), "installPath": a, "version": "1.0.0", "lastUpdated": "2026-11-01"},
            {"scope": "user", "installPath": u, "version": "0.9.0", "lastUpdated": "2026-10-01"},
            {"scope": "local", "projectPath": inst, "installPath": b, "version": "1.1.0", "lastUpdated": "2026-11-02"},
        ])
        self.assertEqual(self.shim.resolve({"COMMS_ENGINE_INSTANCE": inst}, path)[0], b)
        self.assertEqual(self.shim.resolve({"COMMS_ENGINE_INSTANCE": os.path.join(self.tmp, "other")}, path)[0], u)
        path = self.installed([
            {"scope": "project", "projectPath": "/x", "installPath": a, "lastUpdated": "2026-11-01"},
            {"scope": "project", "projectPath": "/y", "installPath": b, "lastUpdated": "2026-11-05"},
        ])
        self.assertEqual(self.shim.resolve({"COMMS_ENGINE_INSTANCE": inst}, path)[0], b)

    def test_a_development_engine_named_outright_wins(self):
        dev = self.engine_at("checkout", "plugins", "comms-engine")
        self.assertEqual(self.shim.resolve({"COMMS_ENGINE_HOME": dev}, os.path.join(self.tmp, "none.json")), (dev, "COMMS_ENGINE_HOME"))

    def test_no_install_is_a_reason_not_a_guess(self):
        root, why = self.shim.resolve({}, self.installed([{"scope": "user", "installPath": os.path.join(self.tmp, "gone")}]))
        self.assertIsNone(root)
        self.assertIn("claude plugin install comms-engine@comms-engine", why)
        root, why = self.shim.resolve({}, os.path.join(self.tmp, "missing.json"))
        self.assertIsNone(root)

    def test_install_writes_the_shim_once_and_says_when_it_is_current(self):
        import engine
        import io
        from contextlib import redirect_stdout
        home = os.path.join(self.tmp, "home")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(engine.shim(home=home), 1, "missing until installed")
            self.assertEqual(engine.shim(install=True, home=home), 0)
        target = engine.shim_path(home)
        self.assertTrue(os.access(target, os.X_OK))
        with open(target) as f, open(engine.SHIM_SOURCE) as g:
            self.assertEqual(f.read(), g.read())
        self.assertEqual(engine.shim_state(home), (target, "current"))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(engine.shim(home=home), 0)

    def test_a_development_checkout_names_its_engine_and_a_cached_one_does_not(self):
        self.assertFalse(render.in_plugin_cache(home="/home/someone"))
        out = tempfile.mkdtemp()
        render.render_all(out, repo=REPO, home="/home/someone", only="com.acme.score")
        with open(os.path.join(out, "com.acme.score.plist"), "rb") as f:
            self.assertEqual(plistlib.load(f)["EnvironmentVariables"]["COMMS_ENGINE_HOME"], render.ENGINE)
        self.assertTrue(render.in_plugin_cache(engine="/home/someone/.claude/plugins/cache/comms-engine/comms-engine/1.0.0",
                                               home="/home/someone"))


if __name__ == "__main__":
    unittest.main()
