"""
The stream registry and per-stream memory (plan v2, items A1 and A2).

What is checked, and why it matters:

1. **The registry parses and joins.** Every row has a guardrails row; a pair
   rule may only name slugs that exist. A slug missing from one of the three
   tables is an error, never a silent skip.
2. **An unknown slug raises, never defaults.** `stream("both")`, `stream("")`
   and `slug_for("Both")` all raise: an item that serves two streams is split
   before it is drafted.
3. **The root stream resolves to the memory root.** `stream_dir("acme")` is
   `memory.MEMORY`, so the module constants a test redirects keep working.
4. **Owners are never named.** The `owner` column carries only `confirmed` or
   `unset`.
5. **A new stream loads empty rosters, never the root's.** `load_themes("beta")`
   is `[]`; `load_handles("beta")` has no partners; its private companion is
   expected and absent, which is what makes the gate block it.
6. **Only a confirmed stream with a voice may draft.** `may_draft` is true for
   `acme` alone; the other row's autopilot is `nothing`.

The registry under test is the fixture one (`tests/fixtures/memory/streams.md`,
two rows) through `fixture_memory.py`; the malformed registries are written to
a temp file.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import fixture_memory  # noqa: E402
import memory  # noqa: E402

ROOT, OTHER = fixture_memory.ROOT, fixture_memory.OTHER

FIXTURE = """# streams

## registry

| slug | name | narrator | owner | objectives | autopilot | channels | memory | corpus root | corpus status |
|---|---|---|---|---|---|---|---|---|---|
| acme | Acme | authority | confirmed | citations | rule | X | .atelier/memory | drive | confirmed |
| beta | Beta | — | unset | intent | nothing | X | .atelier/memory/streams/beta | path | candidate |

## guardrails

| slug | drafts-only channels | posts per channel per day | quiet hours | blocked topics | hold for review |
|---|---|---|---|---|---|
| acme | none | X 2 | weekends | stealth | statistics |
{GUARD_BETA}

## pair rules

| from | to | rule | basis |
|---|---|---|---|
| acme | {PAIR_TO} | first deployment | instincts |
"""


def _write(tmp, guard="| beta | all | 0 | all | all | all |", pair_to="beta"):
    path = os.path.join(tmp, "streams.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(FIXTURE.replace("{GUARD_BETA}", guard).replace("{PAIR_TO}", pair_to))
    return path


class RegistryShape(fixture_memory.FixtureMemoryCase):
    def test_registry_has_the_root_first(self):
        self.assertEqual(memory.streams(), [ROOT, OTHER])
        self.assertEqual(memory.streams()[0], memory.DEFAULT_STREAM)

    def test_every_row_joined_to_guardrails(self):
        for slug, row in memory.load_streams().items():
            self.assertIn("hold for review", row["guardrails"], slug)
            self.assertIn("drafts-only channels", row["guardrails"], slug)

    def test_pair_rules_name_known_streams_only(self):
        reg = memory.load_streams()
        for slug, row in reg.items():
            for p in row["pair_rules"]:
                self.assertIn(p["to"], reg)
                self.assertEqual(p["from"], slug)

    def test_owner_column_never_names_anyone(self):
        for slug, row in memory.load_streams().items():
            self.assertIn(row["owner"].strip().lower(), ("confirmed", "unset"), slug)

    def test_only_the_root_has_an_autopilot_rule(self):
        for slug, row in memory.load_streams().items():
            if slug == ROOT:
                self.assertFalse(row["autopilot"].lower().startswith("nothing"))
            else:
                self.assertEqual(row["autopilot"].strip().lower(), "nothing", slug)

    def test_list_prints_one_line_per_stream(self):
        lines = memory.registry_table().splitlines()
        self.assertEqual(len(lines), 1 + 2)
        self.assertTrue(lines[1].startswith(ROOT + " "))
        self.assertIn("drafts: no", lines[2])


class Resolution(fixture_memory.FixtureMemoryCase):
    def test_root_resolves_to_the_memory_root(self):
        self.assertEqual(memory.stream_dir(ROOT), memory.MEMORY)
        self.assertEqual(memory.paths(ROOT)["themes_md"], memory.THEMES_MD)
        self.assertEqual(memory.paths(None)["handles_private_md"], memory.HANDLES_PRIVATE_MD)

    def test_other_streams_resolve_under_streams_dir(self):
        d = memory.stream_dir(OTHER)
        self.assertEqual(d, os.path.join(memory.MEMORY, "streams", OTHER))
        self.assertTrue(os.path.isdir(d), d)

    def test_unknown_slug_raises_never_defaults(self):
        for bad in ("both", "Both", "", None, "Acme-Beta", fixture_memory.UNKNOWN_NAME):
            with self.assertRaises(memory.SharedMemoryError, msg=repr(bad)):
                memory.stream(bad)

    def test_slug_for_display_names(self):
        self.assertEqual(memory.slug_for(fixture_memory.ROOT_NAME), ROOT)
        self.assertEqual(memory.slug_for(fixture_memory.OTHER_NAME), OTHER)
        self.assertEqual(memory.slug_for(ROOT), ROOT)
        with self.assertRaises(memory.SharedMemoryError):
            memory.slug_for("Both")

    def test_may_draft_only_the_root(self):
        self.assertTrue(memory.may_draft(ROOT))
        self.assertFalse(memory.may_draft(OTHER))

    def test_may_draft_needs_the_voice_file(self):
        os.remove(self.fixture.path("voice.md"))
        self.assertFalse(memory.may_draft(ROOT))


class EmptyRosters(fixture_memory.FixtureMemoryCase):
    """A new stream's files carry the headings and nothing under them."""

    def test_themes_empty_not_the_roots(self):
        self.assertEqual(memory.load_themes(OTHER), [])
        self.assertEqual(memory.theme_tags(OTHER), [])
        self.assertEqual(len(memory.load_themes()), 8)

    def test_handles_empty_and_private_expected_but_absent(self):
        h = memory.load_handles(OTHER)
        self.assertEqual(h["cleared_partners"], [])
        self.assertEqual(h["own_channels"], [])
        self.assertEqual(memory.cleared_names(OTHER), [])
        self.assertEqual(memory.taggable_handles(OTHER), {})
        self.assertTrue(memory.private_expected(OTHER))
        self.assertFalse(h["private"]["present"])
        with self.assertRaises(memory.SharedMemoryError):
            memory.denylist(OTHER)

    def test_claims_empty(self):
        self.assertEqual(memory.load_claims(OTHER), {})
        self.assertEqual(memory.current_claims(OTHER), [])

    def test_summary_names_the_stream(self):
        self.assertIn(f"stream        {OTHER}", memory.summary(OTHER))
        self.assertIn(f"stream        {ROOT}", memory.summary())


class FixtureRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def test_fixture_parses_and_joins(self):
        reg = memory.load_streams(_write(self.tmp))
        self.assertEqual(list(reg), [ROOT, OTHER])
        self.assertEqual(reg[ROOT]["pair_rules"][0]["to"], OTHER)
        self.assertEqual(reg[OTHER]["guardrails"]["posts per channel per day"], "0")

    def test_missing_guardrails_row_is_an_error(self):
        with self.assertRaises(memory.SharedMemoryError) as cm:
            memory.load_streams(_write(self.tmp, guard=""))
        self.assertIn(f"no guardrails row for '{OTHER}'", str(cm.exception))

    def test_pair_rule_to_unknown_stream_is_an_error(self):
        with self.assertRaises(memory.SharedMemoryError) as cm:
            memory.load_streams(_write(self.tmp, pair_to="gamma"))
        self.assertIn("unknown stream 'gamma'", str(cm.exception))

    def test_stream_dir_from_fixture_column(self):
        path = _write(self.tmp)
        self.assertEqual(memory.stream_dir(OTHER, path),
                         os.path.join(memory.REPO, ".atelier", "memory", "streams", OTHER))


class RenderedFromBrandJson(unittest.TestCase):
    """The three tables are rendered from brand.json by one writer (brandfile.py, `engine.py apply`).

    - the shipped streams.md is what the shipped brand.json renders to
    - only table rows change: prose, headings and a column the writer does not know stay
    - the cells it writes are the forms guardrails.py and channels.py parse
    - an import of a registry kept by hand renders back to the same rows
    - `apply --check` names the rows that differ and writes nothing; a setup with a problem is refused
    """

    def setUp(self):
        import brandfile
        import config
        self.brandfile, self.config = brandfile, config
        self.dir = tempfile.mkdtemp()
        self.base = os.path.join(self.dir, "engine.json")
        with open(self.base, "w", encoding="utf-8") as f:
            f.write('{"brand": {"slug": "acme", "name": "Acme", "label_prefix": "com.acme", "env_prefix": "ACME_", '
                    '"keychain_service": "acme-comms"}, "jobs": [], "params": {}, "streams": {}}')
        self.md = _write(self.dir)
        self.bdoc = {
            "brand": {"slug": "acme", "name": "Acme"},
            "streams": {
                "acme": {"narrator": "authority", "owner": "confirmed", "objectives": "citations", "autopilot": "by switch",
                         "channels": {"x": "@acme_x", "linkedin": "", "website": "acme.example"},
                         "corpus_status": "confirmed", "drafts_only": "none",
                         "posts_per_day": {"x": 2, "linkedin": 1, "blog_per_week": 2, "blog_days_apart": 4},
                         "quiet_hours": "weekends; before 08:00 and after 18:00", "blocked_topics": "stealth",
                         "hold_for_review": "statistics",
                         "pair_rules": [{"to": "beta", "rule": "first deployment", "basis": "instincts"}]},
                "beta": {"name": "Beta", "narrator": "—", "objectives": "intent", "channels": "X"},
            },
        }

    def write_brand(self, doc=None):
        self.brandfile.write(doc or self.bdoc, self.base)

    def test_the_shipped_registry_is_what_the_shipped_setup_renders(self):
        repo = os.path.dirname(os.path.dirname(ENGINE))
        with open(os.path.join(repo, ".atelier", "memory", "streams.md"), encoding="utf-8") as f:
            text = f.read()
        bdoc = self.config.read_brand_file(os.path.join(ENGINE, "engine.json"))
        self.assertEqual(self.brandfile.differences(text, bdoc), [],
                         "streams.md is out of date with brand.json: run engine.py apply")

    def test_only_rows_change_and_the_registry_still_parses(self):
        with open(self.md, encoding="utf-8") as f:
            before = f.read()
        self.write_brand()
        result = self.brandfile.apply(self.md, base=self.base)
        self.assertTrue(result["changed"])
        with open(self.md, encoding="utf-8") as f:
            after = f.read()
        self.assertEqual([ln for ln in before.splitlines() if not ln.startswith("| ")],
                         [ln for ln in after.splitlines() if not ln.startswith("| ")], "prose, headings and headers are untouched")
        reg = memory.load_streams(self.md)
        self.assertEqual(list(reg), ["acme", "beta"])
        self.assertEqual(reg["acme"]["autopilot"], "by switch")
        self.assertEqual(reg["acme"]["channels"], "X @acme_x; LinkedIn (collect); website acme.example")
        self.assertEqual(reg["acme"]["corpus root"], "drive", "a cell the setup file does not hold keeps what it had")
        self.assertEqual(reg["beta"]["memory"], ".atelier/memory/streams/beta")
        self.assertEqual((reg["beta"]["owner"], reg["beta"]["autopilot"]), ("unset", "nothing"), "a stream is shut until it says otherwise")
        self.assertEqual(reg["beta"]["guardrails"]["quiet hours"], "all hours until onboarded")
        self.assertEqual(reg["acme"]["pair_rules"], [{"from": "acme", "to": "beta", "rule": "first deployment", "basis": "instincts"}])
        self.assertFalse(self.brandfile.apply(self.md, base=self.base)["changed"], "a second apply writes nothing")

    def test_the_cells_are_the_forms_the_readers_parse(self):
        import guardrails
        self.write_brand()
        self.brandfile.apply(self.md, base=self.base)
        g = guardrails.parse_guardrails(memory.load_streams(self.md)["acme"])
        self.assertEqual(g["caps"], {"X": 2, "LinkedIn": 1})
        self.assertEqual(g["week_caps"], {"Blog": 2})
        self.assertEqual(g["quiet"]["min_days_between_blogs"], 4)
        self.assertEqual((g["quiet"]["weekends"], g["quiet"]["before"], g["quiet"]["after"]), (True, (8, 0), (18, 0)))
        self.assertEqual(g["drafts_only"], set())
        shut = guardrails.parse_guardrails(memory.load_streams(self.md)["beta"])
        self.assertTrue(shut["quiet"]["all"])
        self.assertEqual(shut["drafts_only"], set(guardrails.CHANNELS))
        import channels
        self.assertEqual(channels.handle_of(" @acme_x"), "@acme_x")
        self.assertIsNone(channels.handle_of(" (collect)"))
        self.assertEqual(self.brandfile.posts_cell({"x": 0, "linkedin": 0, "blog_per_week": 0}), "X 0; LinkedIn 0; Blog 0 per ISO week")
        zero = guardrails.parse_guardrails({"guardrails": {"posts per channel per day": "X 0; LinkedIn 0; Blog 0 per ISO week"}})
        self.assertEqual((zero["caps"], zero["week_caps"]), ({"X": 0, "LinkedIn": 0}, {"Blog": 0}))

    def test_an_import_renders_back_to_the_same_rows(self):
        with open(self.md, encoding="utf-8") as f:
            text = f.read()
        bdoc = self.brandfile.from_streams_md(text, {"slug": "acme", "name": "Acme"})
        self.assertEqual(self.brandfile.differences(text, bdoc), [])
        self.assertEqual(bdoc["streams"]["acme"]["pair_rules"], [{"to": "beta", "rule": "first deployment", "basis": "instincts"}])
        self.assertNotIn("memory", bdoc["streams"]["beta"], "the derived memory path is not written")

    def test_check_names_the_rows_and_writes_nothing(self):
        with open(self.md, encoding="utf-8") as f:
            before = f.read()
        self.write_brand()
        result = self.brandfile.apply(self.md, base=self.base, check=True)
        self.assertTrue(result["changed"])
        self.assertTrue(any(ln.startswith("+ | acme | Acme | authority | confirmed | citations | by switch |") for ln in result["diff"]))
        with open(self.md, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)

    def test_a_setup_with_a_problem_is_refused_not_rendered(self):
        bad = dict(self.bdoc, streams={**self.bdoc["streams"], "acme": {**self.bdoc["streams"]["acme"], "owner": "someone"}})
        self.write_brand(bad)
        with self.assertRaises(self.brandfile.Refused) as ctx:
            self.brandfile.apply(self.md, base=self.base)
        self.assertIn("streams.acme.owner", str(ctx.exception))
        cell = dict(self.bdoc, streams={"acme": {"narrator": "a | b"}})
        self.assertIn("streams.acme.narrator", [key for key, _problem, _fix in self.config.brand_problems(cell, {})])
        with self.assertRaises(self.brandfile.Refused):
            self.brandfile.rows(cell)

    def test_the_file_stays_small_when_written(self):
        text = self.brandfile.dumps(self.bdoc)
        self.assertLessEqual(len(text.splitlines()), 30)
        self.assertEqual(__import__("json").loads(text), self.bdoc)


if __name__ == "__main__":
    unittest.main()
