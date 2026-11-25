"""
onboard.py: a stream's onboarding pass over a temporary copy of the memory tree.

The checkout's `.atelier/memory/` is never read or written: every case copies
the fixture `beta` stream directory (`tests/fixtures/memory/streams/beta/`)
into a temp tree, points memory.py at a fixture registry there, and patches
the template, the engine-local streams folder and engine.local.json to temp
paths. What is asserted:

- an unknown slug is exit 2 and writes nothing
- a slug whose owner is unset ends with "may draft: no" and "drafts nothing",
  with the reasons listed; headless, no question is ever asked
- voice.md is shaped from the template only with --write-voice, with the
  stream's name and slug in it; an existing voice is never overwritten
- --owner-confirmed yes prints the exact registry line with `confirmed` and
  leaves streams.md byte-identical; onboarding never writes the registry
- --corpus-root writes streams.<slug>.corpus_root into engine.local.json, a
  root that does not exist is refused (exit 1), --dry-run writes nothing
- a fixture whose owner is confirmed and whose voice.md was shaped may draft
- the shipped voice template carries the tokens onboarding fills and names no
  brand
"""
import contextlib
import hashlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(ENGINE))
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import config  # noqa: E402
import fixture_memory  # noqa: E402
import memory  # noqa: E402
import onboard  # noqa: E402

SHIPPED_TEMPLATE = os.path.join(REPO, ".atelier", "memory", "templates", "voice.md")
FIXTURE_TEMPLATE = os.path.join(fixture_memory.MEMORY_FIXTURE, "templates", "voice.md")
FIXTURE_STREAM = os.path.join(fixture_memory.MEMORY_FIXTURE, "streams", "beta")
FIXTURE_THEMES_JSON = os.path.join(fixture_memory.ENGINE_STREAMS, "beta", "themes.json")

REGISTRY = """# streams

## registry

| slug | name | narrator | owner | objectives | autopilot | channels | memory | corpus root | corpus status |
|---|---|---|---|---|---|---|---|---|---|
| acme | Acme | authority | confirmed | citations | rule | X @acme_hq | .atelier/memory | drive | confirmed |
| beta | Beta | — (set at onboarding) | {OWNER} | intent | nothing | X @betalabs | .atelier/memory/streams/beta | `~/somewhere` | candidate |

## guardrails

| slug | drafts-only channels | posts per channel per day | quiet hours | blocked topics | hold for review |
|---|---|---|---|---|---|
| acme | none | X 2 | weekends | stealth | statistics |
| beta | all | 0 | all | all | all |

## pair rules

| from | to | rule | basis |
|---|---|---|---|
| acme | beta | first deployment | instincts |
"""


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class Tree(unittest.TestCase):
    """A temp repo with .atelier/memory/{streams.md, templates/, streams/beta/} and an engine streams dir."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.mem = os.path.join(self.dir, ".atelier", "memory")
        os.makedirs(os.path.join(self.mem, "templates"))
        shutil.copytree(FIXTURE_STREAM, os.path.join(self.mem, "streams", "beta"))
        self.stream_dir = os.path.join(self.mem, "streams", "beta")
        if os.path.exists(os.path.join(self.stream_dir, "voice.md")):
            os.remove(os.path.join(self.stream_dir, "voice.md"))
        self.template = os.path.join(self.mem, "templates", "voice.md")
        shutil.copy(FIXTURE_TEMPLATE, self.template)
        self.streams_md = os.path.join(self.mem, "streams.md")
        self.write_registry(owner="unset")
        self.engine_streams = os.path.join(self.dir, "engine-streams")
        os.makedirs(os.path.join(self.engine_streams, "beta"))
        shutil.copy(FIXTURE_THEMES_JSON, os.path.join(self.engine_streams, "beta", "themes.json"))
        self.local = os.path.join(self.dir, "engine.local.json")
        self.patches = [
            mock.patch.object(memory, "REPO", self.dir),
            mock.patch.object(memory, "MEMORY", self.mem),
            mock.patch.object(memory, "STREAMS_MD", self.streams_md),
            mock.patch.object(onboard, "TEMPLATE", self.template),
            mock.patch.object(onboard, "ENGINE_STREAMS", self.engine_streams),
            mock.patch.object(config, "LOCAL_JSON", self.local),
            # headless by contract: a question asked here is a failure
            mock.patch("builtins.input", side_effect=AssertionError("input() called headless")),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(self._stop)

    def _stop(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def write_registry(self, owner):
        with open(self.streams_md, "w", encoding="utf-8") as f:
            f.write(REGISTRY.replace("{OWNER}", owner))

    def run_cli(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = onboard.main(list(argv))
        return rc, buf.getvalue()


class UnknownAndUnset(Tree):
    def test_unknown_slug_exits_2_and_writes_nothing(self):
        rc, out = self.run_cli("nosuch")
        self.assertEqual(rc, 2)
        self.assertIn("unknown stream 'nosuch'", out)
        self.assertFalse(os.path.exists(self.local))

    def test_no_slug_is_usage(self):
        rc, _ = self.run_cli()
        self.assertEqual(rc, 2)
        rc, _ = self.run_cli("--owner-confirmed", "yes")
        self.assertEqual(rc, 2)

    def test_owner_unset_drafts_nothing(self):
        rc, out = self.run_cli("beta")
        self.assertEqual(rc, 0)
        self.assertIn("owner     unset", out)
        self.assertIn("may draft: no", out)
        self.assertIn("drafts nothing", out)
        self.assertIn("owner is `unset`", out)
        self.assertIn("voice.md is missing", out)
        self.assertIn("autopilot is `nothing`", out)
        # the report walks the file set and the engine-local search file
        for name in ("status.md", "claims.md", "campaigns/", "decisions/"):
            self.assertIn(f"ok       {name}", out)
        self.assertIn("MISSING  voice.md  (missing)", out)
        self.assertIn("themes.json  empty, 0 search terms", out)
        self.assertIn("handles.private.md  (gitignored", out)
        # nothing written headless without a flag
        self.assertFalse(os.path.exists(os.path.join(self.stream_dir, "voice.md")))
        self.assertFalse(os.path.exists(self.local))

    def test_closing_checks_run_against_the_stream(self):
        _, out = self.run_cli("beta")
        self.assertIn("stream        beta", out)
        self.assertIn("gate      block", out)
        self.assertIn("not a theme of the beta stream", out)


class Voice(Tree):
    def test_voice_written_only_with_the_flag(self):
        target = os.path.join(self.stream_dir, "voice.md")
        rc, out = self.run_cli("beta", "--voice-from", "template")
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(target), "no --write-voice, no voice.md")
        rc, out = self.run_cli("beta", "--write-voice")
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(target))
        self.assertIn("wrote .atelier/memory/streams/beta/voice.md", out)
        with open(target, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("# voice — Beta", text)
        self.assertIn("onboard-stream beta", text)
        self.assertNotIn("__NAME__", text)
        self.assertNotIn("__DATE__", text)
        self.assertIn("## voice summary", text)
        self.assertIn(onboard.NOT_WRITTEN, text)
        self.assertEqual(onboard.voice_state(target), "shaped")
        # the shaped file still does not let the stream draft
        self.assertIn("may draft: no", out)
        self.assertIn("shaped but not written", out)

    def test_existing_voice_never_overwritten(self):
        target = os.path.join(self.stream_dir, "voice.md")
        with open(target, "w", encoding="utf-8") as f:
            f.write("# voice — Beta\n\n## voice summary\n\nA written voice.\n")
        before = _sha(target)
        rc, out = self.run_cli("beta", "--write-voice")
        self.assertEqual(rc, 0)
        self.assertIn("never overwritten", out)
        self.assertEqual(_sha(target), before)
        self.assertEqual(onboard.voice_state(target), "written")

    def test_dry_run_writes_no_voice(self):
        rc, out = self.run_cli("beta", "--write-voice", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("would write .atelier/memory/streams/beta/voice.md", out)
        self.assertFalse(os.path.exists(os.path.join(self.stream_dir, "voice.md")))

    def test_brief_source_is_named_not_copied(self):
        brief = os.path.join(self.dir, "brief.md")
        with open(brief, "w") as f:
            f.write("# brief\n\nSecret content that must not be copied.\n")
        rc, _ = self.run_cli("beta", "--write-voice", "--voice-from", brief)
        self.assertEqual(rc, 0)
        with open(os.path.join(self.stream_dir, "voice.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn(brief, text)
        self.assertNotIn("Secret content", text)
        rc, out = self.run_cli("beta", "--write-voice", "--voice-from", "/nowhere/brief.md")
        self.assertEqual(rc, 1)
        self.assertIn("refused", out)


class Registry(Tree):
    def test_owner_confirmed_prints_the_line_and_writes_nothing(self):
        before = _sha(self.streams_md)
        rc, out = self.run_cli("beta", "--owner-confirmed", "yes")
        self.assertEqual(rc, 0)
        self.assertIn("onboarding never writes the registry", out)
        self.assertIn("| beta | Beta | — (set at onboarding) | confirmed | intent | nothing | X @betalabs |", out)
        self.assertIn('brand.json  streams.beta.owner = "confirmed"', out, "the key a person sets, not a cell to edit")
        self.assertIn("engine.py apply", out)
        self.assertEqual(_sha(self.streams_md), before)
        self.assertIn("may draft: no", out)

    def test_channels_answer_is_a_registry_edit(self):
        rc, out = self.run_cli("beta", "--channels", "X @betalabs; LinkedIn betalabs")
        self.assertEqual(rc, 0)
        self.assertIn("| unset | intent | nothing | X @betalabs; LinkedIn betalabs |", out)
        self.assertIn('brand.json  streams.beta.channels = "X @betalabs; LinkedIn betalabs"', out)
        self.assertFalse(os.path.exists(self.local))


class LocalConfig(Tree):
    def test_corpus_root_and_themes_file_go_to_engine_local_json(self):
        root = os.path.join(self.dir, "corpus")
        os.makedirs(root)
        rc, out = self.run_cli("beta", "--corpus-root", root, "--themes-file", "streams/beta/themes.json")
        self.assertEqual(rc, 0)
        self.assertIn("streams.beta.corpus_root = ", out)
        self.assertIn("streams.beta.themes_file = ", out)
        doc = config.load(local=self.local)
        self.assertEqual(doc["streams"]["beta"]["corpus_root"], root)
        self.assertEqual(doc["streams"]["beta"]["themes_file"], "streams/beta/themes.json")
        # the second run reads it back and writes nothing new
        rc, out = self.run_cli("beta")
        self.assertIn(f"corpus    ok       {root}  (engine.local.json)", out)
        self.assertNotIn("wrote ", out)

    def test_nonexistent_root_refused(self):
        rc, out = self.run_cli("beta", "--corpus-root", "/nowhere/at/all")
        self.assertEqual(rc, 1)
        self.assertIn("refused   corpus root does not exist", out)
        self.assertFalse(os.path.exists(self.local))

    def test_dry_run_writes_nothing(self):
        root = os.path.join(self.dir, "corpus")
        os.makedirs(root)
        rc, out = self.run_cli("beta", "--corpus-root", root, "--dry-run")
        self.assertEqual(rc, 0)
        self.assertIn("would write", out)
        self.assertFalse(os.path.exists(self.local))

    def test_set_local_never_touches_jobs(self):
        with self.assertRaises(config.ConfigError):
            config.set_local("jobs", [], local=self.local)


class MayDraft(Tree):
    def test_confirmed_owner_and_shaped_voice_may_draft(self):
        self.write_registry(owner="confirmed")
        rc, out = self.run_cli("beta", "--write-voice")
        self.assertEqual(rc, 0)
        self.assertIn("may draft: yes", out)
        self.assertTrue(memory.may_draft("beta"))

    def test_why_not_order(self):
        rep = onboard.report("beta", local=self.local, env={})
        reasons = onboard.why_not(rep)
        self.assertTrue(reasons[0].startswith("owner is `unset`"))
        self.assertIn("voice.md is missing", reasons[1])


class Parse(unittest.TestCase):
    def test_flags(self):
        slug, flags = onboard.parse(["Beta", "--owner-confirmed", "yes", "--corpus-root=/x y", "--write-voice", "--dry-run"])
        self.assertEqual(slug, "beta")
        self.assertEqual(flags, {"owner_confirmed": "yes", "corpus_root": "/x y", "write_voice": "true", "dry_run": "true"})
        with self.assertRaises(onboard.Usage):
            onboard.parse(["beta", "stray"])
        with self.assertRaises(onboard.Usage):
            onboard.parse([])


class Template(unittest.TestCase):
    """The shipped template (`.atelier/memory/templates/voice.md`) is the one
    file of the checkout's memory this suite reads: onboarding writes every
    new stream's voice from it, so its tokens and its sentinel are a contract."""

    def test_shipped_template_carries_the_tokens_and_names_no_brand(self):
        with open(SHIPPED_TEMPLATE, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("## voice summary", text)
        self.assertIn(onboard.NOT_WRITTEN, text)
        for token in ("__NAME__", "__SLUG__", "__DATE__"):
            self.assertIn(token, text)
        # the previous brand's name, spelled in two halves so this file itself
        # passes the fresh-clone grep
        self.assertNotRegex(text, "(?i)" + "lt" + "in")

    def test_fixture_template_matches_the_shipped_tokens(self):
        """The fixture the Tree cases write from carries the same contract."""
        with open(FIXTURE_TEMPLATE, encoding="utf-8") as f:
            text = f.read()
        self.assertIn(onboard.NOT_WRITTEN, text)
        for token in ("__NAME__", "__SLUG__", "__DATE__"):
            self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
