#!/usr/bin/env python3
"""
The fixture set for `scripts/gate_lint.py`.

Four things are asserted here, and each of them is something the gate would
otherwise only be believed to do:

1. **The fixtures.** `fixtures.json` carries one clean item and its mutations,
   every banned construction a rule of `status.md`, `instincts.md`, `voice.md`
   or the claims register would name. Each case names the check it must trip
   and the verdict it must produce. The cleared hedges are fixtures too, and
   they must pass: a linter that blocks the approved phrasing is as broken as
   one that passes an upgraded form of a cleared hedge.
2. **The queued drafts.** Three drafts with the verdicts the model recorded
   (`fixtures/queue.json`) come out of the lint with the same verdicts: the
   deterministic half adds checks to the gate, it does not re-judge what the
   model already recorded.
3. **The missing companion.** With `handles.private.md` out of the checkout, the
   stealth check blocks rather than passing vacuously.
4. **The recording.** `--write` merges the lint into `gate.checks` in the shape
   the model's checks use, leaves the verdict where it stood, and replaces its
   own entries on a second run rather than piling onto them. It runs against a
   temp vault, never the vault.

Every case reads the fixture memory under `tests/fixtures/memory/` through
`fixture_memory.py`; the denylist it scans against is the fixture companion,
passed by patching `memory.HANDLES_PRIVATE_MD`, never the checkout's own.

  python3 -m unittest discover plugins/comms-engine/tests
"""
import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import fixture_memory  # noqa: E402
import gate_lint  # noqa: E402
import memory  # noqa: E402
import repo  # noqa: E402

with open(os.path.join(HERE, "fixtures.json"), encoding="utf-8") as f:
    FIXTURES = json.load(f)


def item_for(case):
    """The base item with this case's one mutation applied."""
    item = copy.deepcopy(FIXTURES["base"])
    item.update(case.get("set") or {})
    if case.get("insert"):
        # Dropped in ahead of the honest sentence, where a claim would land.
        head, sep, tail = item["post"].rpartition("\n\n")
        item["post"] = f"{head}\n\n{case['insert']}{sep}{tail}" if sep else \
            f"{item['post']}\n\n{case['insert']}"
    return item


class FixtureSet(fixture_memory.FixtureMemoryCase):
    """Every banned construction blocks; every cleared form passes."""

    def test_cases(self):
        for case in FIXTURES["cases"]:
            with self.subTest(case=case["name"]):
                result = gate_lint.lint(item_for(case))
                named = {c["check"]: c for c in result["checks"]}
                expect = case["expect"]
                self.assertIn(expect["check"], named)
                self.assertEqual(expect["result"], named[expect["check"]]["result"],
                                 f"{case['name']} ({case['source']}): "
                                 f"{expect['check']} came back "
                                 f"{named[expect['check']]['result']}: {named[expect['check']]['fix']}")
                self.assertEqual(expect["verdict"], result["verdict"], case["name"])

    def test_every_check_runs_on_every_item(self):
        result = gate_lint.lint(FIXTURES["base"])
        self.assertEqual(len(gate_lint.CHECKS), len(result["checks"]))
        for entry in result["checks"]:
            self.assertEqual(sorted(entry), ["check", "fix", "line", "result"])
            self.assertTrue(entry["check"].startswith(gate_lint.PREFIX))
            self.assertIn(entry["result"], gate_lint.RANK)

    def test_offending_line_is_quoted(self):
        """A verdict without the line is not a verdict (gatekeeper hard rule)."""
        for case in FIXTURES["cases"]:
            expect = case["expect"]
            if expect["result"] == "pass":
                continue
            with self.subTest(case=case["name"]):
                result = gate_lint.lint(item_for(case))
                named = {c["check"]: c for c in result["checks"]}
                self.assertTrue(named[expect["check"]]["line"].strip(),
                                f"{case['name']}: no line quoted")
                self.assertTrue(named[expect["check"]]["fix"].strip())

    def test_fixtures_cover_every_check(self):
        covered = {c["expect"]["check"] for c in FIXTURES["cases"]
                   if c["expect"]["result"] != "pass"}
        expected = {gate_lint.PREFIX + n for n in
                    ("stream", "status words", "stealth", "partner tags",
                     "what we do not claim", "tag line", "cta", "hook", "cites",
                     "hypothesis")}
        if not gate_lint.rules()["status_words"]:
            # the template ships no status rules (a brand writes them from its
            # status.md, with a blocking case per rule beside them); until then
            # the only status-words case there can be is a passing one
            expected.discard(gate_lint.PREFIX + "status words")
        self.assertEqual(expected, covered)

    def test_the_denylist_read_is_the_fixture_companion(self):
        """What the stealth check scans against is the fixture's closed list,
        not whatever companion the checkout may or may not carry."""
        self.assertEqual(memory.denylist(), ["Umbra", "Ruritania", "Project Nightjar", "relay nodes"])
        self.assertTrue(memory.HANDLES_PRIVATE_MD.startswith(self.fixture.root))


class QueuedDrafts(fixture_memory.FixtureMemoryCase):
    """Three drafts in the inbox re-run to the verdicts they carry.

    Pinned by id and verdict in `fixtures/queue.json` rather than read off
    whatever a queue holds, so a draft appended by a later cycle neither
    breaks this nor quietly replaces the regression it is here to hold.
    """

    TODAY = {"Q-2026-10-01-exampletheme-1": "pass-with-edits",
             "Q-2026-10-02-secondtheme-1": "pass-with-edits",
             "Q-2026-10-03-thirdtheme-1": "block"}

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="gate-queue-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        state = os.path.join(self.tmp, "state")
        cal = os.path.join(self.tmp, "Calendar")
        os.makedirs(state)
        os.makedirs(cal)
        shutil.copy(fixture_memory.QUEUE_JSON, os.path.join(state, "queue.json"))
        self.real = (repo.CAL, repo.STATE)
        repo.CAL, repo.STATE = cal, state
        self.addCleanup(self.restore)
        self.items = gate_lint.items_by_id()

    def restore(self):
        repo.CAL, repo.STATE = self.real

    def item(self, item_id):
        self.assertIn(item_id, self.items, f"{item_id} is not in the fixture queue")
        return self.items[item_id]

    def test_the_fixture_queue_holds_the_three(self):
        self.assertEqual(sorted(self.items), sorted(self.TODAY))

    def test_verdicts_unchanged(self):
        for item_id, verdict in sorted(self.TODAY.items()):
            with self.subTest(item=item_id):
                item = self.item(item_id)
                self.assertEqual(verdict, (item.get("gate") or {}).get("verdict"))
                merged = gate_lint.merge(item.get("gate"), gate_lint.lint(item))
                self.assertEqual(verdict, merged["verdict"])

    def test_lint_blocks_none_of_them(self):
        for item_id in sorted(self.TODAY):
            with self.subTest(item=item_id):
                self.assertNotEqual("block", gate_lint.lint(self.item(item_id))["verdict"])

    def test_merge_never_lowers_a_recorded_block(self):
        item = self.item("Q-2026-10-03-thirdtheme-1")
        merged = gate_lint.merge(item["gate"], gate_lint.lint(item))
        self.assertEqual("block", merged["verdict"])
        # The model's own checks survive the merge, the lint's run ahead of them.
        self.assertTrue(merged["checks"][0]["check"].startswith(gate_lint.PREFIX))
        self.assertTrue(any(not c["check"].startswith(gate_lint.PREFIX)
                            for c in merged["checks"]))

    def test_merge_replaces_a_previous_runs_entries(self):
        """The second draft carries a `lint:` entry from an earlier run; the
        merge replaces it rather than keeping two tag-line entries."""
        item = self.item("Q-2026-10-02-secondtheme-1")
        merged = gate_lint.merge(item["gate"], gate_lint.lint(item))
        lint_entries = [c for c in merged["checks"] if c["check"].startswith(gate_lint.PREFIX)]
        self.assertEqual(len(gate_lint.CHECKS), len(lint_entries))
        self.assertEqual(1, sum(1 for c in merged["checks"] if c["check"] == gate_lint.PREFIX + "tag line"))
        self.assertEqual(["names"], [c["check"] for c in merged["checks"] if not c["check"].startswith(gate_lint.PREFIX)])

    def test_merge_never_lowers_a_block_no_check_carries(self):
        """A model block written into note_for_alpha alone still stands."""
        gate = {"verdict": "block", "checks": [], "note_for_alpha": "judgment"}
        merged = gate_lint.merge(gate, gate_lint.lint(FIXTURES["base"]))
        self.assertEqual("block", merged["verdict"])


class MissingPrivateCompanion(fixture_memory.FixtureMemoryCase):
    """An expected-but-absent companion blocks; it never passes vacuously."""

    PRIVATE = False

    def test_stealth_blocks(self):
        self.assertFalse(os.path.exists(memory.HANDLES_PRIVATE_MD))
        self.assertTrue(memory.private_expected())
        result = gate_lint.lint(FIXTURES["base"])
        stealth = {c["check"]: c for c in result["checks"]}[gate_lint.PREFIX + "stealth"]
        self.assertEqual("block", stealth["result"])
        self.assertIn("handles.private.md", stealth["fix"])
        self.assertEqual("block", result["verdict"])

    def test_a_clean_item_would_otherwise_pass(self):
        shutil.copy(os.path.join(fixture_memory.MEMORY_FIXTURE, "handles.private.md"),
                    memory.HANDLES_PRIVATE_MD)
        self.assertEqual("pass", gate_lint.lint(FIXTURES["base"])["verdict"])


class Recording(fixture_memory.FixtureMemoryCase):
    """`--write` records into gate.checks, against a temp vault."""

    ITEM = FIXTURES["base"]["id"]

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="gate-lint-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.real = (repo.CAL, repo.STATE)
        repo.CAL = os.path.join(self.tmp, "Calendar")
        repo.STATE = os.path.join(self.tmp, "state")
        os.makedirs(repo.CAL)
        os.makedirs(repo.STATE)
        self.addCleanup(self.restore)
        # The note is the record: the fixture item enters the vault with the
        # gate the model wrote on it, then the lint is recorded onto that.
        item = copy.deepcopy(FIXTURES["base"])
        item["gate"] = {"verdict": "pass-with-edits",
                        "checks": [{"check": "register", "result": "edit",
                                    "line": "One is engineering.", "fix": "a fuller second line"}],
                        "note_for_alpha": "thin"}
        item["slot"] = {"date": "2026-10-06", "platform": "Blog", "campaign": ""}
        repo.write_item(item, "Idea")
        repo.write_index()

    def restore(self):
        repo.CAL, repo.STATE = self.real

    def write(self, *ids):
        """`--write` as the gatekeeper runs it, with its report swallowed."""
        with contextlib.redirect_stdout(io.StringIO()):
            return gate_lint.main(["--write", *ids])

    def gate_now(self):
        return repo.scan_notes()[self.ITEM]["Blog"][1]["gate"]

    def test_write_records_the_checks_and_keeps_the_verdict(self):
        before = self.gate_now()
        self.assertEqual(0, self.write(self.ITEM))
        after = self.gate_now()
        lint_entries = [c for c in after["checks"]
                        if c["check"].startswith(gate_lint.PREFIX)]
        self.assertEqual(len(gate_lint.CHECKS), len(lint_entries))
        self.assertEqual(after["checks"][:len(lint_entries)], lint_entries)
        for entry in lint_entries:
            self.assertEqual(sorted(entry), ["check", "fix", "line", "result"])
        # The model's checks and the verdict it recorded are untouched.
        self.assertEqual([c for c in before["checks"] if not c["check"].startswith(gate_lint.PREFIX)],
                         [c for c in after["checks"]
                          if not c["check"].startswith(gate_lint.PREFIX)])
        self.assertEqual(before["verdict"], after["verdict"])
        fm = repo.scan_notes()[self.ITEM]["Blog"][1]
        self.assertEqual(before["verdict"], fm["gate_verdict"])

    def test_write_is_idempotent(self):
        self.write(self.ITEM)
        first = self.gate_now()
        self.write(self.ITEM)
        second = self.gate_now()
        self.assertEqual(len([c for c in first["checks"]
                              if c["check"].startswith(gate_lint.PREFIX)]),
                         len([c for c in second["checks"]
                              if c["check"].startswith(gate_lint.PREFIX)]))
        self.assertEqual(first["verdict"], second["verdict"])

    def test_write_reaches_an_inbox_only_item(self):
        """An item the vault has not ingested is recorded in the index."""
        queue_path = os.path.join(repo.STATE, "queue.json")
        item = copy.deepcopy(FIXTURES["base"])
        item["id"] = "T-fixture-inbox-only-1"
        item["gate"] = {"verdict": "pass", "checks": []}
        with open(queue_path, "w", encoding="utf-8") as f:
            json.dump([item], f)
        self.assertEqual(0, self.write(item["id"]))
        with open(queue_path, encoding="utf-8") as f:
            written = json.load(f)[0]
        self.assertEqual(len(gate_lint.CHECKS), len(written["gate"]["checks"]))
        self.assertEqual("pass", written["gate"]["verdict"])



class TeamPosts(fixture_memory.FixtureMemoryCase):
    """Regression: a team post (control page, announcement) was linted as a theme post, and the
    limit check blocked every one, so none could be approved. It binds what binds every surface."""

    def team(self, **kw):
        item = {"id": "T-1", "title": "Short title", "theme": "", "stream": fixture_memory.ROOT_NAME, "post": "",
                "teaser_x": "A plain sentence about the standards work.", "teaser_linkedin": "",
                "drafted_by": repo.TEAM_BY}
        item.update(kw)
        return gate_lint.lint(item)

    def test_the_theme_post_shape_is_not_asked_of_it(self):
        got = self.team()
        self.assertEqual(got["verdict"], "pass", got["checks"])
        self.assertEqual({c["check"] for c in got["checks"]},
                         {gate_lint.PREFIX + n for n in ("stream", "status words", "stealth", "partner tags", "cites")})

    def test_stealth_and_an_uncleared_mention_still_block(self):
        self.assertEqual(self.team(teaser_x="Talks with Umbra Capital went well.")["verdict"], "block")
        self.assertEqual(self.team(teaser_x="Thanks to @not_a_cleared_partner for the work.")["verdict"], "block")

    def test_an_engine_draft_is_still_linted_as_a_theme_post(self):
        item = {"id": "Q-1", "title": "Short title", "theme": "", "stream": fixture_memory.ROOT_NAME, "post": "",
                "teaser_x": "A plain sentence about the standards work.", "teaser_linkedin": "", "drafted_by": "theme-writer"}
        self.assertEqual(gate_lint.lint(item)["verdict"], "block")  # the same copy, drafted by the engine


class RulesAreData(fixture_memory.FixtureMemoryCase):
    """The brand's gate rules live in `.atelier/memory/gate-rules.json`, read through memory.py.

    - the shipped file is a shape with no content, and the code holds no rule of its own
    - a status word and a cleared hedge written in the file are in force at once
    - a stream reads its own file and never another stream's
    - the capability verbs and the house-style switches come from the file
    - a file that does not read blocks; it is never read around
    """

    def write(self, doc, stream=None):
        d = self.fixture.dir if stream is None else self.fixture.stream_dir(stream)
        with open(os.path.join(d, "gate-rules.json"), "w", encoding="utf-8") as f:
            f.write(doc if isinstance(doc, str) else json.dumps(doc))

    def result(self, item, name):
        return next(c for c in gate_lint.lint(item)["checks"] if c["check"] == gate_lint.PREFIX + name)

    def case(self, check):
        return item_for(next(c for c in FIXTURES["cases"]
                             if c["expect"]["check"] == gate_lint.PREFIX + check and c["expect"]["result"] != "pass"))

    def test_the_shipped_file_is_a_shape_and_the_code_holds_no_rule(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(ENGINE)), ".atelier", "memory", "gate-rules.json"),
                  encoding="utf-8") as f:
            shipped = json.load(f)
        self.assertEqual((shipped["status_words"], shipped["cleared_hedges"]), ([], []))
        self.assertEqual(tuple(shipped["capability_verbs"]), memory.DEFAULT_CAPABILITY_VERBS)
        self.assertEqual(shipped["house_style"], {"hook_words": {"min": 6, "max": 17}, "what_we_do_not_claim": True, "tag_line": True,
                                                  "retired": []}, "no house-style rule ships retired: that is a person's act")
        for key in ("_about", "_status_words_about", "_house_style_about"):
            self.assertIn(key, shipped)
        for gone in ("STATUS_WORDS", "CLEARED_HEDGES", "HOOK_MIN", "HOOK_MAX"):
            self.assertFalse(hasattr(gate_lint, gone), f"{gone} is a rule in code; it belongs in gate-rules.json")
        rules = memory.load_gate_rules()
        self.assertFalse(rules["present"], "the fixture memory has no file: the defaults apply")
        self.assertEqual(rules["house_style"]["hook_words"], (6, 17))

    def test_a_status_word_in_the_file_blocks_and_a_cleared_hedge_passes(self):
        item = copy.deepcopy(FIXTURES["base"])
        item["post"] = item["post"] + "\n\nThe platform is fully accredited."
        self.assertEqual(self.result(item, "status words")["result"], "pass", "no rule written yet")
        self.write({"status_words": [{"pattern": r"\baccredited\b", "fix": "say 'working towards accreditation'"}]})
        r = self.result(item, "status words")
        self.assertEqual(r["result"], "block")
        self.assertIn("fully accredited", r["line"])
        self.assertIn("working towards accreditation", r["fix"])
        self.write({"status_words": [{"pattern": r"\baccredited\b", "fix": "x"}], "cleared_hedges": ["fully accredited"]})
        self.assertEqual(self.result(item, "status words")["result"], "pass", "the approved form is masked before the scan")

    def test_a_stream_reads_its_own_rules_and_never_another_streams(self):
        self.write({"status_words": [{"pattern": r"\bcertified\b", "fix": "x"}]})
        fields = [("text", "We are certified.")]
        self.assertEqual(gate_lint.scan_status_words(fields)["result"], "block")
        self.assertEqual(gate_lint.scan_status_words(fields, fixture_memory.OTHER)["result"], "pass",
                         "the other stream has no file and is not held to the root's rules")
        self.write({"status_words": [{"pattern": r"\blicensed\b", "fix": "x"}]}, stream=fixture_memory.OTHER)
        self.assertEqual(gate_lint.scan_status_words([("text", "We are licensed.")], fixture_memory.OTHER)["result"], "block")
        self.assertEqual(gate_lint.scan_status_words([("text", "We are licensed.")])["result"], "pass")

    def test_the_capability_verbs_come_from_the_file(self):
        fields = [("text", "Acme ships the settlement layer.")]
        self.assertEqual(gate_lint.scan_cites(fields, [], None, require_cites=False)["result"], "pass")
        self.write({"capability_verbs": ["ships?", "operates?"]})
        r = gate_lint.scan_cites(fields, [], None, require_cites=False)
        self.assertEqual(r["result"], "block")
        self.assertIn("present-tense capability sentence", r["fix"])
        self.assertEqual(gate_lint.capability_for(fixture_memory.OTHER).search("Beta operates the platform").group(0),
                         "Beta operates", "another stream is read with its own name as the subject")

    def test_the_house_style_switches(self):
        hook = self.case("hook")
        self.assertEqual(self.result(hook, "hook")["result"], "edit")
        self.write({"house_style": {"hook_words": {"min": 1, "max": 60}}})
        self.assertEqual(self.result(hook, "hook")["result"], "pass", "the range is the file's")
        limit = self.case("what we do not claim")
        self.assertEqual(self.result(limit, "what we do not claim")["result"], "block")
        self.write({"house_style": {"what_we_do_not_claim": False, "tag_line": False, "hook_words": False}})
        self.assertEqual(self.result(limit, "what we do not claim")["result"], "pass")
        self.assertIn("Switched off", self.result(limit, "what we do not claim")["fix"])
        self.assertEqual(self.result(self.case("tag line"), "tag line")["result"], "pass")

    def test_rules_that_do_not_read_block(self):
        for bad in ("{ not json", {"status_words": [{"pattern": "(unclosed", "fix": "x"}]},
                    {"status_words": "certified"}, {"capability_verbs": []}, {"house_style": {"hook_words": {"min": 9, "max": 2}}}):
            self.write(bad)
            with self.assertRaises(memory.SharedMemoryError, msg=str(bad)):
                memory.load_gate_rules()
            result = gate_lint.lint(FIXTURES["base"])
            self.assertEqual(result["verdict"], "block", str(bad))
            status = next(c for c in result["checks"] if c["check"] == gate_lint.PREFIX + "status words")
            self.assertEqual(status["result"], "block")
            self.assertIn("did not read", status["fix"])
            text = gate_lint.lint_text(fixture_memory.ROOT_NAME, "X", "A plain reply.")
            self.assertEqual(text["verdict"], "block", "a reply is held to the same rule")



class FormatAware(fixture_memory.FixtureMemoryCase):
    """A format with no article (an X thread) carries its honest limit, tag line and no CTA in the
    teasers it ships as (2026-11-14: a live thread was blocked for the limit an empty post lacked)."""

    FORMATS = {"theme-post": dict(memory.DEFAULT_FORMATS["theme-post"]),
               "x-thread": {"name": "X thread", "structure": ["hook", "limit"], "channels": ["x"]}}

    def thread(self, **over):
        item = copy.deepcopy(FIXTURES["base"])
        limit = "We do not claim the root is settled."
        item.update(format="x-thread", post="", teaser_linkedin="", cta="", limit=limit,
                    teaser_x=f"A root is a governance choice.\n\n{limit}\n\n{item['theme']}")
        item.update(over)
        return item

    def run_checks(self, item):
        from unittest import mock
        with mock.patch.object(gate_lint.memory, "load_formats", return_value=self.FORMATS):
            slug = gate_lint.resolve_slug(item)
            return {c["check"].split(": ", 1)[-1]: c for c in (gate_lint.check_no_claim(item, slug), gate_lint.check_tag_line(item, slug),
                                            gate_lint.check_cta(item, slug))}

    def test_a_thread_is_checked_on_the_teasers_it_ships_as(self):
        got = self.run_checks(self.thread())
        self.assertEqual({k: v["result"] for k, v in got.items()},
                         {"what we do not claim": "pass", "tag line": "pass", "cta": "pass"}, got)

    def test_a_thread_still_needs_its_limit_and_tag_and_no_link_to_a_page_it_never_writes(self):
        self.assertEqual(self.run_checks(self.thread(limit="Not in the thread."))["what we do not claim"]["result"], "block")
        self.assertEqual(self.run_checks(self.thread(teaser_x="A root is a governance choice."))["tag line"]["result"], "edit")
        self.assertEqual(self.run_checks(self.thread(cta="https://www.example.com/insights/x"))["cta"]["result"], "edit")

    def test_an_unknown_format_is_held_to_the_theme_post(self):
        got = self.run_checks(self.thread(format="mystery"))
        self.assertEqual(got["what we do not claim"]["result"], "block", "no article: the limit is not in a post")

if __name__ == "__main__":
    unittest.main()
