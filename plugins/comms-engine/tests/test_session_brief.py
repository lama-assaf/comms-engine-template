"""session_brief: the SessionStart brief shows what is new, once, and never blocks.

The claim is that a new session opens on what changed since the last one on
this clone: the latest listening pass and the lessons, decisions and reviews
added since. Three halves of that are asserted here, each on fixtures in a
temporary directory so the live memory and state are never read or written.

1. **New means new.** A lesson shown once is not shown again; the marker is
   what remembers, and `--dry-run` leaves it alone.
2. **The first brief is bounded.** With no marker the window is WINDOW_DAYS,
   so an old lessons.md does not flood a fresh clone.
3. **A missing file is a line, not a crash.** No signals.json, no decisions
   folder, no reviews.md: the brief still prints and exits 0, because a hook
   that fails would cost the session its context for nothing.
4. **The console line is one line and never a failure.** The brief carries
   `engine console: ...` from engine.status_rows(): the count of jobs stale or
   not loaded (nosleep and the optional stream excluded) with their labels, or
   `none stale`; when engine.py cannot answer, the line says `unavailable` and
   the brief still prints. The fixtures patch the console so no test reads
   launchctl or the live state.
"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixture_memory  # noqa: E402
import session_brief as sb  # noqa: E402


def setUpModule():
    # The checkout may have been stamped with any brand by `engine.py init`;
    # these tests answer for the fixture brand (acme) through fixture_memory.
    fixture_memory.install()


def tearDownModule():
    fixture_memory.uninstall()

NOW = dt.datetime(2026, 10, 30, 9, 0, tzinfo=dt.timezone.utc)
REAL_ENGINE_LINE = sb.engine_line  # the Fixture patches it; EngineLine puts it back

LESSONS = """# lessons

## 2026-07-09 — positioning evolved hard

context: old.

lesson: default to the May–June 2026 material.

cost: generic.

## 2026-10-22 — the carrier's plan outranks the initiative's claim

context: something.

lesson: read the carrier's own plan before repeating the initiative's
line about it.

cost: a date nobody owns.

## 2026-10-26 — the register is the gate's memory, the graph is the watch's

context: plan v2.

lesson: keep what content may cite in a markdown register.

cost: a fail-closed gate on a database.
"""

SIGNALS = {
    "run_id": "20261026T213710Z",
    "stream": "Acme",
    "window": {"from": "2026-10-19T21:37:10Z", "to": "2026-10-26T21:37:10Z"},
    "summary": "Licensed themes carried the week.",
    "mentions_note": "One of five @mentions items is about Acme.",
    "held_slot": {"triggered": False, "reason": "No issuing-body document inside 48 hours."},
    "per_theme": {
        "#ThirdTheme": {"count": 12, "relevance": 2.83},
        "#ExampleTheme": {"count": 2, "relevance": 4.0},
        "#FourthTheme": {"count": 12, "relevance": 1.75},
        "@mentions": {"count": 5, "relevance": 0.6},
    },
    "handed_on": {"a person, hold for review": ["F10 partner-role claim in a third-party post"]},
}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.memory = root / "memory"
        self.state = root / "state"
        self.marker = root / "clone" / "session-brief.json"
        (self.memory / "decisions").mkdir(parents=True)
        self.state.mkdir()
        (self.memory / "lessons.md").write_text(LESSONS, encoding="utf-8")
        (self.memory / "decisions" / "2026-10-26-twitterapi-for-x.md").write_text(
            "# decision: X is read through twitterapi.io only\n\ndate: 2026-10-26\n", encoding="utf-8")
        (self.memory / "decisions" / "README.md").write_text("# decisions\n", encoding="utf-8")
        (self.state / "signals.json").write_text(json.dumps(SIGNALS), encoding="utf-8")
        (self.state / "runs.json").write_text(json.dumps([
            {"run_id": "20261026T213710Z", "step": "assess", "at": "2026-10-26T21:47:24+00:00",
             "stream": "Acme", "detail": "listener: 11 findings"}]), encoding="utf-8")
        # the console reads launchctl and the live state; the fixtures never do
        patch = mock.patch.object(sb, "engine_line", lambda now: "engine console: (fixture)")
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def run_brief(self, write=True, now=NOW):
        return sb.brief(memory_dir=str(self.memory), state_dir=str(self.state),
                        marker_path=str(self.marker), now=now, write=write)


class NewMeansNew(Fixture):
    def test_first_brief_shows_window_then_nothing(self):
        first = self.run_brief()
        self.assertIn("first brief on this clone", first)
        self.assertIn("the register is the gate's memory", first)
        self.assertIn("the carrier's plan outranks", first)
        self.assertNotIn("positioning evolved hard", first, "outside the 14-day window")
        self.assertIn("decision 2026-10-26: X is read through twitterapi.io only (decisions/2026-10-26-twitterapi-for-x.md)", first)
        self.assertNotIn("README", first)
        self.assertTrue(self.marker.exists())

        second = self.run_brief()
        self.assertIn("previous session on this clone: 2026-10-30 09:00Z", second)
        self.assertIn("nothing new since the last session", second)
        self.assertNotIn("the register is the gate's memory", second)

    def test_a_lesson_added_later_is_shown_once(self):
        self.run_brief()
        with open(self.memory / "lessons.md", "a", encoding="utf-8") as f:
            f.write("\n## 2026-10-30 — the brief shows a lesson once\n\nlesson: once is enough.\n")
        third = self.run_brief()
        self.assertIn("the brief shows a lesson once — once is enough.", third)
        self.assertNotIn("the brief shows a lesson once", self.run_brief())

    def test_dry_run_leaves_the_marker_alone(self):
        self.run_brief(write=False)
        self.assertFalse(self.marker.exists())
        self.assertIn("the register is the gate's memory", self.run_brief(write=False))

    def test_old_lessons_appear_after_the_first_run_when_added(self):
        """After the first run the window no longer applies: a back-dated lesson added later is still new."""
        self.run_brief()
        with open(self.memory / "lessons.md", "a", encoding="utf-8") as f:
            f.write("\n## 2026-09-01 — found in an old notebook\n\nlesson: back-dated but new to this clone.\n")
        self.assertIn("found in an old notebook", self.run_brief())


class Monitoring(Fixture):
    def test_signals_are_summarised(self):
        text = self.run_brief()
        self.assertIn("listening pass 20261026T213710Z (Acme), window 2026-10-19 to 2026-10-26, 3 d ago", text)
        self.assertIn("summary: Licensed themes carried the week.", text)
        self.assertIn("held slot: not triggered", text)
        self.assertIn("warmest themes: #ExampleTheme 4.0 over 2; #ThirdTheme 2.8 over 12; #FourthTheme", text)
        self.assertNotIn("@mentions 0.6", text, "the brand search is not a theme")
        self.assertIn("held for a person (1): F10 partner-role claim", text)
        self.assertIn("last engine step: assess 3 d ago (listener: 11 findings)", text)
        self.assertNotIn("x stream listener", text, "no listener.json means no stream line")

    def test_listener_heartbeat_adds_a_line(self):
        (self.state / "x-stream").mkdir()
        (self.state / "x-stream" / "listener.json").write_text(
            json.dumps({"state": "connected", "at": "2026-10-30T07:00:00Z", "pid": 1}), encoding="utf-8")
        self.assertIn("x stream listener: connected, last heartbeat 2 h ago", self.run_brief())


class NeverBlocks(Fixture):
    def test_missing_files_are_lines_not_errors(self):
        os.remove(self.state / "signals.json")
        os.remove(self.state / "runs.json")
        for p in (self.memory / "decisions").iterdir():
            p.unlink()
        (self.memory / "decisions").rmdir()
        text = self.run_brief()
        self.assertIn("no listening pass on file", text)
        self.assertIn("the register is the gate's memory", text)

    def test_cli_exits_zero_with_hook_stdin(self):
        script = Path(__file__).resolve().parent.parent / "scripts" / "session_brief.py"
        r = subprocess.run([sys.executable, str(script), "--dry-run"],
                           input='{"session_id":"t","source":"startup"}', capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        # a subprocess reads the checkout's own engine.json, whatever brand it carries
        with open(fixture_memory.LIVE_ENGINE_JSON, encoding="utf-8") as f:
            live_name = (json.load(f).get("brand") or {}).get("name", fixture_memory.ROOT_NAME)
        self.assertIn(f"# {live_name} comms: since the last session", r.stdout)
        self.assertIn("## social monitoring", r.stdout)
        self.assertIn("engine console: ", r.stdout, "the console line is in the real brief")


FAKE_ROWS = [
    {"job": "com.acme.corpus-cycle", "what": "corpus", "loaded": True, "last_run": "2026-10-30T06:30", "state": "ok"},
    {"job": "com.acme.social-engine", "what": "cycle", "loaded": True, "last_run": "2026-10-30T07:15", "state": "ok"},
    {"job": "com.acme.engagement", "what": "engage", "loaded": True, "last_run": "2026-09-07T21:11", "state": "stale (52.5 d)"},
    {"job": "com.acme.score", "what": "score", "loaded": False, "last_run": None, "state": "not loaded"},
    {"job": "com.acme.x-stream", "what": "stream", "loaded": False, "last_run": None, "state": "not loaded"},
    {"job": "com.acme.nosleep", "what": "caffeinate", "loaded": False, "last_run": None, "state": "not loaded"},
]


class EngineLine(Fixture):
    """The real engine_line over a faked engine.status_rows(); launchctl is never called."""

    def setUp(self):
        super().setUp()
        restore = mock.patch.object(sb, "engine_line", REAL_ENGINE_LINE)
        restore.start()
        self.addCleanup(restore.stop)
        import engine  # the module engine_line imports; scripts/ is on sys.path above
        self.engine = engine

    def test_counts_stale_and_unloaded_and_names_them(self):
        with mock.patch.object(self.engine, "status_rows", lambda now=None: list(FAKE_ROWS)):
            line = sb.engine_line(NOW)
        self.assertEqual(
            line,
            "engine console: 2 of 6 jobs stale or not loaded (com.acme.engagement, com.acme.score); "
            "run engine.py status, then engine.py logs <job>")
        self.assertNotIn("nosleep", line, "caffeinate is excluded")
        self.assertNotIn("x-stream", line, "the optional stream is excluded")

    def test_all_healthy_is_one_calm_line(self):
        rows = [dict(r, state="ok", loaded=True) for r in FAKE_ROWS]
        with mock.patch.object(self.engine, "status_rows", lambda now=None: rows):
            self.assertEqual(sb.engine_line(NOW), "engine console: 6 jobs, none stale or unloaded")

    def test_a_broken_console_is_a_line_not_a_crash(self):
        def boom(now=None):
            raise OSError("launchctl: not found")
        with mock.patch.object(self.engine, "status_rows", boom):
            line = sb.engine_line(NOW)
        self.assertTrue(line.startswith("engine console: unavailable (OSError: launchctl: not found)"), line)

    def test_the_line_sits_in_the_monitoring_section(self):
        with mock.patch.object(self.engine, "status_rows", lambda now=None: list(FAKE_ROWS)):
            text = self.run_brief()
        mon = text.split("## social monitoring")[1].split("## new lessons")[0]
        self.assertIn("engine console: 2 of 6 jobs stale or not loaded", mon)


if __name__ == "__main__":
    unittest.main()
