"""
engine_tui.py: the console screen's model, tested without a terminal.

The screen is curses; the model behind it (what the left pane lists, what each
key does, how a row and a detail render) is plain Python, and engine's
functions are patched so nothing spawns. What is asserted:

- rows: the four sections in order, one job row per engine.json job with the
  state word (ok / stale / off / never) and the last run as hh:mm today or
  MM-DD; stream rows carry the owner state; the secrets and plugins counts
- the key table: every key maps to an action the model knows, getch codes
  become key names, movement skips section headers and wraps, tab jumps
- actions: r builds the dry command and calls engine.run(live=False); R is
  refused for autopilot/x-stream/nosleep before any confirm, cancelled without
  y, and calls engine.run(live=True) with y; e / d name install.sh and
  launchctl bootout, ask y, and call engine.enable / engine.disable; s calls
  engine.setup(short, {}, interactive=True) or the secrets/plugins table; o
  asks the slug and calls engine.main(["onboard-stream", slug]); a job key on
  a non-job row is a message, nothing runs
- the small-terminal message names 80x24; headless main() exits 2
"""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

sys.path.insert(0, HERE)
import config  # noqa: E402
import engine  # noqa: E402
import engine_tui as tui  # noqa: E402
import fixture_memory  # noqa: E402
import memory  # noqa: E402


def setUpModule():
    # The checkout may have been stamped with any brand by `engine.py init`;
    # these tests answer for the fixture brand (acme) through fixture_memory.
    fixture_memory.install()


def tearDownModule():
    fixture_memory.uninstall()

TODAY = "2026-11-05"

FAKE_STATUS = {
    "jobs": [
        {"job": "com.acme.corpus-cycle", "what": "corpus", "loaded": True, "last_run": "2026-11-05T06:30", "state": "ok"},
        {"job": "com.acme.social-engine", "what": "cycle", "loaded": True, "last_run": "2026-11-05T07:15", "state": "ok"},
        {"job": "com.acme.autopilot", "what": "autopilot", "loaded": True, "last_run": None, "state": "loaded, never ran"},
        {"job": "com.acme.engagement", "what": "engage", "loaded": True, "last_run": "2026-09-07T21:11", "state": "stale (58.9 d)"},
        {"job": "com.acme.x-stream", "what": "stream", "loaded": False, "last_run": None, "state": "not loaded"},
        {"job": "com.acme.nosleep", "what": "caffeinate", "loaded": False, "last_run": None, "state": "not loaded"},
    ],
    "secrets": [
        {"name": "LINKEDIN_ACCESS_TOKEN", "required": True, "present": True, "backend": "keychain"},
        {"name": "TWITTERAPI_IO_API_KEY", "required": True, "present": False, "backend": None},
        {"name": "APIFY_TOKEN", "required": False, "present": True, "backend": "env"},
    ],
    "plugins": [{"name": "atelier@atelier", "installed": True}, {"name": "salon@atelier", "installed": False}],
    "last_cycle": {"at": "2026-11-05T07:15", "budget_usd": 20, "exit": 0},
}

FAKE_JOBS = [
    {"label": "com.acme.corpus-cycle", "what": "corpus memory 06:30 weekdays",
     "calendar": [{"Weekday": d, "Hour": 6, "Minute": 30} for d in range(1, 6)], "log": "state/corpus-cycle.log"},
    {"label": "com.acme.social-engine", "what": "/social-cycle", "calendar": [{"Weekday": d, "Hour": 7, "Minute": 15} for d in range(1, 6)]},
    {"label": "com.acme.autopilot", "what": "snapshot, post, link replies",
     "calendar": [{"Weekday": d, "Hour": h, "Minute": m} for d in range(1, 6) for h, m in ((9, 5), (13, 35))]},
    {"label": "com.acme.engagement", "what": "engagement pass", "calendar": [{"Weekday": d, "Hour": 15, "Minute": 30} for d in range(1, 6)]},
    {"label": "com.acme.x-stream", "what": "twitterapi.io stream", "keep_alive": True, "optional": True},
    {"label": "com.acme.nosleep", "what": "caffeinate", "keep_alive": True},
]

FAKE_STREAMS = {
    "acme": {"slug": "acme", "name": "Acme", "owner": "confirmed", "autopilot": "themes: ...", "memory": ".atelier/memory", "guardrails": {}},
    "beta": {"slug": "beta", "name": "Beta", "owner": "unset", "autopilot": "nothing", "memory": ".atelier/memory/streams/beta", "guardrails": {}},
}


def model():
    """A refreshed Model over the fakes; engine's readers patched, nothing spawned."""
    with mock.patch.object(engine, "status", return_value=FAKE_STATUS), \
         mock.patch.object(config, "jobs", return_value=FAKE_JOBS), \
         mock.patch.object(memory, "load_streams", return_value=FAKE_STREAMS):
        return tui.Model(today=TODAY).refresh()


def select(m, kind, key=None):
    for i, r in enumerate(m.rows):
        if r.kind == kind and (key is None or r.key == key):
            m.cursor = i
            return r
    raise AssertionError(f"no row {kind} {key}")


class Rows(unittest.TestCase):
    def test_sections_in_order_and_one_row_per_job(self):
        m = model()
        sections = [r.text for r in m.rows if r.kind == "section"]
        self.assertEqual(sections, ["jobs", "streams", "secrets", "plugins"])
        jobs = [r.key for r in m.rows if r.kind == "job"]
        self.assertEqual(jobs, ["corpus", "cycle", "autopilot", "engagement", "x-stream", "nosleep"])
        self.assertEqual([r.key for r in m.rows if r.kind == "stream"], ["acme", "beta"])

    def test_job_row_renders_state_word_and_last_run(self):
        m = model()
        by = {r.key: r.text for r in m.rows if r.kind == "job"}
        self.assertEqual(by["corpus"].split(), ["corpus", "ok", "06:30"])
        self.assertEqual(by["engagement"].split(), ["engagement", "stale", "09-07"])
        self.assertEqual(by["x-stream"].split(), ["x-stream", "off", "-"])
        self.assertEqual(by["autopilot"].split(), ["autopilot", "never", "-"])
        for text in by.values():
            self.assertLessEqual(len(text), tui.LEFT_W - 1, text)

    def test_stream_secrets_plugins_rows(self):
        m = model()
        texts = {r.kind + ":" + str(r.key): r.text for r in m.rows if r.kind != "section"}
        self.assertEqual(texts["stream:acme"].split(), ["acme", "confirmed"])
        self.assertEqual(texts["stream:beta"].split(), ["beta", "unset"])
        self.assertIn("1/2 present", texts["secrets:secrets"])
        self.assertIn("1/2 installed", texts["plugins:plugins"])

    def test_plugins_unknown_when_claude_absent(self):
        st = dict(FAKE_STATUS, plugins=[{"name": "atelier@atelier", "installed": None}])
        rows = tui.build_rows(st, FAKE_JOBS, FAKE_STREAMS, TODAY)
        self.assertIn("unknown", [r for r in rows if r.kind == "plugins"][0].text)

    def test_helpers(self):
        self.assertEqual(tui.when_text("2026-11-05T06:30", TODAY), "06:30")
        self.assertEqual(tui.when_text("2026-09-07T21:11+00:00", TODAY), "09-07")
        self.assertEqual(tui.when_text(None, TODAY), "-")
        self.assertEqual(tui.calendar_text(FAKE_JOBS[0]), "Mon-Fri 06:30")
        self.assertEqual(tui.calendar_text(FAKE_JOBS[2]), "Mon-Fri 09:05, 13:35")
        self.assertEqual(tui.calendar_text({"calendar": [{"Hour": 22, "Minute": 0}]}), "daily 22:00")
        self.assertEqual(tui.calendar_text({"calendar": [{"Weekday": 1, "Hour": 8, "Minute": 0}]}), "Mon 08:00")
        self.assertEqual(tui.calendar_text(FAKE_JOBS[4]), "always on (keep_alive)")
        self.assertEqual(tui.job_state({"state": "stale (3.1 d)"}), "stale")
        self.assertEqual(tui.job_state(None), "?")

    def test_refresh_survives_a_failing_reader(self):
        with mock.patch.object(engine, "status", side_effect=RuntimeError("keychain locked")), \
             mock.patch.object(config, "jobs", return_value=FAKE_JOBS), \
             mock.patch.object(memory, "load_streams", return_value=FAKE_STREAMS):
            m = tui.Model(today=TODAY).refresh()
        self.assertIn("keychain locked", m.error)
        self.assertEqual(len([r for r in m.rows if r.kind == "job"]), 6)


class Detail(unittest.TestCase):
    def test_job_detail_has_what_when_params_and_log(self):
        m = model()
        select(m, "job", "corpus")
        with mock.patch.object(config, "params", return_value={"job": "corpus-cycle", "max": 8, "apply": True,
                                                               "include": [], "weekday_flags": {"editor": True}}), \
             mock.patch.object(engine, "logs", return_value=["== /x/corpus-cycle.log (last 15) ==", "ran fine"]) as lg:
            lines = m.detail_lines()
        self.assertEqual(lines[0], "com.acme.corpus-cycle  (corpus)")
        self.assertIn("what:      corpus memory 06:30 weekdays", lines)
        self.assertIn("when:      Mon-Fri 06:30", lines)
        self.assertIn("loaded:    yes    state: ok", lines)
        self.assertIn("  max = 8", lines)
        self.assertIn("  apply = true", lines)
        self.assertIn("  include = []", lines)
        self.assertIn("  weekday_flags.editor = true", lines)
        self.assertNotIn("  job = corpus-cycle", lines)
        self.assertIn("  ran fine", lines)
        lg.assert_called_once_with("com.acme.corpus-cycle", tui.LOG_LINES)

    def test_nosleep_detail_has_no_params_block(self):
        m = model()
        select(m, "job", "nosleep")
        with mock.patch.object(engine, "logs", return_value=[]):
            lines = m.detail_lines()
        self.assertFalse(any(ln.startswith("params") for ln in lines))
        self.assertIn("  (no log yet)", lines)
        self.assertIn("when:      always on (keep_alive)", lines)

    def test_stream_secrets_plugins_detail(self):
        m = model()
        select(m, "stream", "beta")
        with mock.patch.object(config, "streams", return_value={"acme": {"corpus_root": "/x"}}):
            lines = m.detail_lines()
        self.assertEqual(lines[0], "stream beta  (Beta)")
        self.assertIn("owner:     unset   (a state, never a name)", lines)
        self.assertIn("  (none; o onboards the stream)", lines)
        select(m, "secrets")
        lines = m.detail_lines()
        self.assertIn("  LINKEDIN_ACCESS_TOKEN: present (keychain; required)", lines)
        self.assertIn("  TWITTERAPI_IO_API_KEY: MISSING  -> engine.py secrets --set TWITTERAPI_IO_API_KEY  (required)", lines)
        select(m, "plugins")
        with mock.patch.object(config, "cfg", return_value="https://example/mp.git"):
            lines = m.detail_lines()
        self.assertIn("  salon@atelier: not installed  -> claude plugin install salon@atelier", lines)

    def test_help_and_logs_views(self):
        m = model()
        select(m, "job", "cycle")
        m.perform("help")
        self.assertEqual(m.detail_lines(), tui.HELP)
        m.perform("help")
        with mock.patch.object(engine, "logs", return_value=["== a ==", "l1"]) as lg:
            out = m.perform("logs")
            self.assertEqual(m.view, "logs")
            self.assertEqual(m.detail_lines(), ["== a ==", "l1"])
            lg.assert_called_with("com.acme.social-engine", 200)
        self.assertEqual(out.command, f"{tui.ENGINE_PY} logs cycle")
        m.perform("down")  # moving returns to the detail view
        self.assertEqual(m.view, "detail")
        select(m, "secrets")
        self.assertIn("select a job", m.perform("logs").message)

    def test_summary_is_the_three_status_lines(self):
        m = model()
        s = m.summary()
        self.assertEqual(len(s), 3)
        self.assertTrue(s[0].startswith("secrets"))
        self.assertTrue(s[2].startswith("last cycle"))


class Keys(unittest.TestCase):
    def test_every_key_maps_to_an_action_the_model_handles(self):
        known = {"down", "up", "section", "run_dry", "run_live", "enable", "disable", "setup",
                 "logs", "onboard", "refresh", "help", "quit"}
        self.assertEqual(set(tui.KEYS.values()), known)
        for k in "jkrRedslog?q":
            self.assertIn(k, tui.KEYS)
        self.assertEqual(tui.KEYS["TAB"], "section")
        self.assertEqual(tui.KEYS["KEY_UP"], "up")

    def test_key_name(self):
        self.assertEqual(tui.key_name(ord("q")), "q")
        self.assertEqual(tui.key_name(9), "TAB")
        self.assertIsNone(tui.key_name(-1))
        self.assertIsNone(tui.key_name(27))
        if tui.curses is not None:
            self.assertEqual(tui.key_name(tui.curses.KEY_DOWN), "KEY_DOWN")
            self.assertEqual(tui.key_name(tui.curses.KEY_UP), "KEY_UP")

    def test_unknown_key_is_ignored(self):
        self.assertIsNone(tui.KEYS.get(tui.key_name(ord("x"))))

    def test_movement_skips_headers_and_wraps(self):
        m = model()
        self.assertEqual(m.selected().key, "corpus")  # the cursor never rests on a header
        m.perform("up")
        self.assertEqual(m.selected().kind, "plugins")
        m.perform("down")
        self.assertEqual(m.selected().key, "corpus")
        for _ in range(6):
            m.perform("down")
        self.assertEqual(m.selected().key, "acme")  # the streams header was skipped
        self.assertTrue(all(r.selectable or r.kind == "section" for r in m.rows))

    def test_tab_jumps_to_the_next_section(self):
        m = model()
        m.perform("section")
        self.assertEqual(m.selected().key, "acme")
        m.perform("section")
        self.assertEqual(m.selected().kind, "secrets")
        m.perform("section")
        self.assertEqual(m.selected().kind, "plugins")
        m.perform("section")
        self.assertEqual(m.selected().key, "corpus")

    def test_quit(self):
        self.assertTrue(model().perform("quit").quit)


class Actions(unittest.TestCase):
    def test_run_dry_builds_the_command_and_calls_engine_run(self):
        m = model()
        select(m, "job", "cycle")
        out = m.perform("run_dry")
        self.assertIsNone(out.message)
        self.assertEqual(out.command, " && ".join(" ".join(c) for c in engine.DRY_FORMS["cycle"]))
        with mock.patch.object(engine, "run", return_value=0) as run:
            self.assertEqual(out.on_terminal(), 0)
        run.assert_called_once_with("cycle", live=False)

    def test_run_dry_nosleep_says_nothing_to_dry_run(self):
        m = model()
        select(m, "job", "nosleep")
        out = m.perform("run_dry")
        self.assertIn("nothing to dry-run", out.command)
        with mock.patch.object(engine, "run", return_value=0) as run:
            out.on_terminal()
        run.assert_called_once_with("nosleep", live=False)

    def test_run_live_refused_for_the_three_labels_before_any_confirm(self):
        m = model()
        for short in ("autopilot", "x-stream", "nosleep"):
            select(m, "job", short)
            asked = []
            out = m.perform("run_live", confirm=lambda q: asked.append(q) or True)
            self.assertIn("refused", out.message)
            self.assertIsNone(out.on_terminal)
            self.assertEqual(asked, [])

    def test_run_live_needs_y_then_calls_engine_run_live(self):
        m = model()
        select(m, "job", "cycle")
        out = m.perform("run_live", confirm=lambda q: False)
        self.assertIn("not confirmed", out.message)
        self.assertIsNone(out.on_terminal)
        questions = []
        out = m.perform("run_live", confirm=lambda q: questions.append(q) or True)
        self.assertIn("runjob.py", questions[0])
        self.assertEqual(out.command, " ".join(engine.live_command("cycle")))
        with mock.patch.object(engine, "run", return_value=0) as run:
            out.on_terminal()
        run.assert_called_once_with("cycle", live=True)

    def test_enable_and_disable_name_their_commands(self):
        m = model()
        select(m, "job", "score") if any(r.key == "score" for r in m.rows) else select(m, "job", "engagement")
        row = m.selected()
        questions = []
        out = m.perform("enable", confirm=lambda q: questions.append(q) or True)
        self.assertEqual(out.command, f"engine install --only {row.data['label']}")
        self.assertIn(out.command, questions[0])
        with mock.patch.object(engine, "enable", return_value=0) as en:
            out.on_terminal()
        en.assert_called_once_with(row.key)
        out = m.perform("disable", confirm=lambda q: questions.append(q) or True)
        self.assertEqual(out.command, f"launchctl bootout gui/{os.getuid()}/{row.data['label']}")
        self.assertIn(out.command, questions[1])
        with mock.patch.object(engine, "disable", return_value=0) as dis:
            out.on_terminal()
        dis.assert_called_once_with(row.key)

    def test_enable_and_disable_without_y_run_nothing(self):
        m = model()
        select(m, "job", "engagement")
        for action in ("enable", "disable"):
            with mock.patch.object(engine, "enable", side_effect=AssertionError("ran")), \
                 mock.patch.object(engine, "disable", side_effect=AssertionError("ran")):
                out = m.perform(action, confirm=lambda q: False)
                out_default = m.perform(action)  # no confirm given: never yes
            for o in (out, out_default):
                self.assertIn("not confirmed", o.message)
                self.assertIsNone(o.on_terminal)
                self.assertIsNone(o.command)

    def test_job_keys_on_a_non_job_row_run_nothing(self):
        m = model()
        select(m, "secrets")
        for action in ("run_dry", "run_live", "enable", "disable"):
            out = m.perform(action, confirm=lambda q: True)
            self.assertIn("select a job", out.message)
            self.assertIsNone(out.on_terminal)

    def test_setup_on_a_job_is_interactive_engine_setup(self):
        m = model()
        select(m, "job", "corpus")
        out = m.perform("setup")
        self.assertEqual(out.command, f"{tui.ENGINE_PY} setup corpus")
        with mock.patch.object(engine, "setup", return_value={"corpus.max": 4}) as su:
            self.assertEqual(out.on_terminal(), 0)
        su.assert_called_once_with("corpus", {}, interactive=True)
        with mock.patch.object(engine, "setup", side_effect=engine.Refused("corpus root does not exist: /nope")):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(out.on_terminal(), 1)
        self.assertIn("corpus root does not exist", buf.getvalue())

    def test_setup_on_secrets_and_plugins_rows(self):
        m = model()
        for kind in ("secrets", "plugins"):
            select(m, kind)
            out = m.perform("setup")
            self.assertEqual(out.command, f"{tui.ENGINE_PY} setup {kind}")
            with mock.patch.object(engine, "setup", return_value={"_exit": 1}) as su:
                self.assertEqual(out.on_terminal(), 1)
            su.assert_called_once_with(kind, {}, interactive=True)

    def test_onboard_asks_the_slug_and_forwards_to_engine_main(self):
        m = model()
        select(m, "stream", "beta")
        asked = []

        def prompt(q, default):
            asked.append(default)
            return default

        out = m.perform("onboard", prompt=prompt)
        self.assertEqual(asked, ["beta"])  # the selected stream is the default
        self.assertEqual(out.command, f"{tui.ENGINE_PY} onboard-stream beta")
        with mock.patch.object(engine, "main", return_value=0) as mn:
            out.on_terminal()
        mn.assert_called_once_with(["onboard-stream", "beta"])
        # s on a stream row is the same act
        out = m.perform("setup", prompt=lambda q, d: "GAMMA ")
        self.assertEqual(out.command, f"{tui.ENGINE_PY} onboard-stream gamma")
        # o elsewhere has no default; an empty answer runs nothing
        select(m, "job", "cycle")
        out = m.perform("onboard", prompt=lambda q, d: d)
        self.assertIsNone(out.on_terminal)
        self.assertIn("no slug", out.message)

    def test_refresh_rereads_status(self):
        m = model()
        st2 = dict(FAKE_STATUS, jobs=[dict(FAKE_STATUS["jobs"][0], state="stale (2.0 d)")] + FAKE_STATUS["jobs"][1:])
        with mock.patch.object(engine, "status", return_value=st2), \
             mock.patch.object(config, "jobs", return_value=FAKE_JOBS), \
             mock.patch.object(memory, "load_streams", return_value=FAKE_STREAMS):
            out = m.perform("refresh")
        self.assertEqual(out.command, f"{tui.ENGINE_PY} status")
        self.assertEqual(m.rows[1].text.split()[1], "stale")


class Screen(unittest.TestCase):
    def test_small_terminal_message(self):
        msg = tui.too_small_message(20, 60)
        self.assertIn("60x20", msg)
        self.assertIn("80x24", msg)
        self.assertIn("q quits", msg)
        self.assertEqual((tui.MIN_W, tui.MIN_H), (80, 24))

    def test_log_view_shows_the_tail_and_detail_the_head(self):
        lines = [str(i) for i in range(10)]
        self.assertEqual(tui.visible_lines(lines, "logs", 3), ["7", "8", "9"])
        self.assertEqual(tui.visible_lines(lines, "detail", 3), ["0", "1", "2"])
        self.assertEqual(tui.visible_lines(lines, "logs", 0), [])

    def test_headless_main_exits_2_without_a_screen(self):
        buf = io.StringIO()
        with mock.patch.object(sys.stdin, "isatty", return_value=False), contextlib.redirect_stdout(buf):
            rc = tui.main([])
        self.assertEqual(rc, 2)
        self.assertIn("needs a terminal; use engine.py status", buf.getvalue())

    def test_help_flag_prints_the_docstring(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(tui.main(["--help"]), 0)
        self.assertIn("engine_tui.py", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
