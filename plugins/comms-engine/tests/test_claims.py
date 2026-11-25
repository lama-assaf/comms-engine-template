"""
The claims register (plan v2, item A4).

1. **The fixture register parses and is internally consistent**: ids unique,
   every grade, tier and corroboration in the closed vocabularies, every
   supersession pointing both ways, every theme a row names present in
   `themes.md`, and every row sourced and dated. The same reader runs on the
   checkout's own register; the fixture is what pins the rules.
2. **Citability is mechanical**: a superseded row is not citable; a `watching`
   or `single` row is not citable; an unknown id is not citable; the rest are.
3. **A malformed register is refused, never read around**: a second row with
   the same id, a grade outside the vocabulary, a one-sided supersession, a
   theme the stream does not have.
4. **A new stream's register is empty**, not the root stream's.
5. **Nothing from the private companion leaks in**: no row names a term on the
   denylist.

Malformed registers are written to a temp file and loaded by path, which skips
the theme check (there is no stream to check against) but keeps every other
rule. Everything else reads the fixture memory (`fixture_memory.py`).
"""
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import fixture_memory  # noqa: E402
import memory  # noqa: E402

HEADER = """# fixture

## register

| id | claim | grade | source | date | tier | themes | supersedes | superseded_by | from | corroboration |
|---|---|---|---|---|---|---|---|---|---|---|
"""


def _reg(tmp, rows):
    path = os.path.join(tmp, "claims.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(HEADER + "".join(rows))
    return path


def _row(cid, grade="evidenced", tier="primary", corr="primary", sup="—", supby="—", frm="—", themes="—"):
    return f"| {cid} | claim {cid} | {grade} | a source | 2026-10-26 | {tier} | {themes} | {sup} | {supby} | {frm} | {corr} |\n"


class FixtureRegister(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        self.reg = memory.load_claims()

    def test_seeded_and_sourced(self):
        self.assertGreaterEqual(len(self.reg), 10)
        for cid, r in self.reg.items():
            self.assertRegex(cid, r"^C-acme-\d+$")
            self.assertTrue(r["source"].strip(), cid)
            self.assertRegex(r["date"], r"^\d{4}-\d{2}-\d{2}$", cid)
            self.assertTrue(r["claim"].strip(), cid)

    def test_vocabularies_and_themes(self):
        tags = set(memory.theme_tags())
        for cid, r in self.reg.items():
            self.assertIn(r["grade"], memory.CLAIM_GRADES, cid)
            self.assertIn(r["tier"], memory.CLAIM_TIERS, cid)
            self.assertIn(r["corroboration"], memory.CLAIM_CORROBORATION, cid)
            for t in r["themes"]:
                self.assertIn(t, tags, cid)

    def test_supersession_both_ways(self):
        self.assertEqual(self.reg["C-acme-6"]["superseded_by"], "C-acme-7")
        self.assertEqual(self.reg["C-acme-7"]["supersedes"], "C-acme-6")
        self.assertFalse(memory.citable("C-acme-6")[0])
        self.assertTrue(memory.citable("C-acme-7")[0])
        self.assertNotIn("C-acme-6", [r["id"] for r in memory.current_claims()])

    def test_watching_and_single_rows_are_not_citable(self):
        ok, why = memory.citable("C-acme-8")
        self.assertFalse(ok)
        self.assertIn("watching", why)
        ok, why = memory.citable("C-acme-10")
        self.assertFalse(ok)
        self.assertIn("single", why)

    def test_the_evidenced_rows_the_gate_leans_on_are_citable(self):
        for cid in ("C-acme-1", "C-acme-2", "C-acme-4", "C-acme-5"):
            self.assertEqual(self.reg[cid]["grade"], "evidenced", cid)
            self.assertTrue(memory.citable(cid)[0], cid)

    def test_an_intended_row_is_citable_but_not_evidenced(self):
        """The grade is not judged by `citable`; the gate decides what an
        intended row may support (a capability sentence, nothing)."""
        self.assertEqual(self.reg["C-acme-9"]["grade"], "intended")
        self.assertTrue(memory.citable("C-acme-9")[0])

    def test_unknown_id_is_not_citable(self):
        ok, why = memory.citable("C-acme-999")
        self.assertFalse(ok)
        self.assertIn("no such claim", why)
        with self.assertRaises(memory.SharedMemoryError):
            memory.claim("C-acme-999")

    def test_nothing_from_the_denylist_in_the_register(self):
        text = " ".join(r["claim"] + " " + r["source"] for r in self.reg.values())
        for term in memory.denylist():
            self.assertIsNone(re.search(r"\b" + re.escape(term) + r"\b", text, re.I), term)

    def test_new_stream_register_is_empty(self):
        slug = fixture_memory.OTHER
        self.assertEqual(memory.load_claims(slug), {})
        self.assertFalse(memory.citable("C-acme-1", slug)[0])


class MalformedRegisters(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="claims-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def test_fixture_parses(self):
        reg = memory.load_claims(path=_reg(self.tmp, [_row("C-x-1"), _row("C-x-2", corr="single")]))
        self.assertEqual(list(reg), ["C-x-1", "C-x-2"])
        self.assertTrue(memory.citable("C-x-1", claims=reg)[0])
        ok, why = memory.citable("C-x-2", claims=reg)
        self.assertFalse(ok)
        self.assertIn("single", why)

    def test_duplicate_id(self):
        with self.assertRaises(memory.SharedMemoryError) as cm:
            memory.load_claims(path=_reg(self.tmp, [_row("C-x-1"), _row("C-x-1")]))
        self.assertIn("listed twice", str(cm.exception))

    def test_grade_outside_vocabulary(self):
        with self.assertRaises(memory.SharedMemoryError) as cm:
            memory.load_claims(path=_reg(self.tmp, [_row("C-x-1", grade="proven")]))
        self.assertIn("grade 'proven'", str(cm.exception))

    def test_one_sided_supersession(self):
        rows = [_row("C-x-1", supby="C-x-2"), _row("C-x-2")]
        with self.assertRaises(memory.SharedMemoryError) as cm:
            memory.load_claims(path=_reg(self.tmp, rows))
        self.assertIn("does not point back", str(cm.exception))

    def test_supersession_to_missing_row(self):
        with self.assertRaises(memory.SharedMemoryError) as cm:
            memory.load_claims(path=_reg(self.tmp, [_row("C-x-1", supby="C-x-9")]))
        self.assertIn("is not a row", str(cm.exception))

    def test_from_must_name_a_registry_stream(self):
        with self.assertRaises(memory.SharedMemoryError) as cm:
            memory.load_claims(path=_reg(self.tmp, [_row("C-x-1", frm="umbra/C-umbra-1")]))
        self.assertIn("names no registry stream", str(cm.exception))
        reg = memory.load_claims(path=_reg(self.tmp, [_row("C-x-1", frm="acme/C-acme-1")]))
        self.assertEqual(reg["C-x-1"]["from"], "acme/C-acme-1")

    def test_theme_unknown_to_the_stream_is_refused(self):
        # Through the stream path (not `path=`) the theme check runs against
        # that stream's themes.md; beta has none, so any theme is refused. The
        # register written to is the temp copy's, never a checkout file.
        real = os.path.join(memory.stream_dir(fixture_memory.OTHER), "claims.md")
        with open(real, "w", encoding="utf-8") as f:
            f.write(HEADER + _row("C-beta-1", themes="#ExampleTheme"))
        with self.assertRaises(memory.SharedMemoryError) as cm:
            memory.load_claims(fixture_memory.OTHER)
        self.assertIn("not in themes.md", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
