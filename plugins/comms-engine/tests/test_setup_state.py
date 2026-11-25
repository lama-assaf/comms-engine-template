"""setup_state.steps(): the facts of a checkout become ordered steps, and block()
counts only the required ones."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import setup_state  # noqa: E402

JOBS = [{"job": "com.acme.corpus-cycle", "loaded": False}, {"job": "com.acme.social-engine", "loaded": False},
        {"job": "com.acme.nosleep", "loaded": True}, {"job": "com.acme.x-stream", "loaded": False, "optional": True}]


def facts(**over):
    base = dict(slug="acme", name="Acme", missing_secrets=["APIFY_TOKEN", "TWITTERAPI_IO_API_KEY"], corpus_root="",
                voice_text="Not written yet. Until this file carries a voice, the stream drafts nothing.",
                local_cfg={}, jobs=JOBS)
    base.update(over)
    return base


class FreshClone(unittest.TestCase):
    def test_nothing_done_next_is_name(self):
        b = setup_state.block(setup_state.steps(**facts()))
        self.assertFalse(b["complete"])
        self.assertEqual((b["done"], b["total"], b["next"]), (0, 6, "name"))
        self.assertEqual([s["id"] for s in b["steps"]], ["name", "secrets", "corpus", "memory", "cycle", "jobs"])

    def test_secrets_step_names_the_first_missing_one(self):
        s = {x["id"]: x for x in setup_state.steps(**facts())}
        self.assertIn("APIFY_TOKEN", s["secrets"]["detail"])
        self.assertIn("--set APIFY_TOKEN", s["secrets"]["command"])

    def test_jobs_count_excludes_nosleep_and_optional(self):
        s = {x["id"]: x for x in setup_state.steps(**facts())}
        self.assertEqual(s["jobs"]["detail"], "0 of 2 loaded")


class Walked(unittest.TestCase):
    def test_every_required_step_done_is_complete(self):
        with tempfile.TemporaryDirectory() as root:
            jobs = [dict(j, loaded=True) for j in JOBS]
            b = setup_state.block(setup_state.steps(**facts(slug="zed", name="Zed", missing_secrets=[], corpus_root=root,
                                                             voice_text="# voice\nsober, specific.", local_cfg={"cycle": {"budget_usd": 3}},
                                                             jobs=jobs)))
        self.assertTrue(b["complete"])
        self.assertEqual((b["done"], b["total"], b["next"]), (6, 6, None))

    def test_named_but_corpus_root_missing_on_disk(self):
        s = {x["id"]: x for x in setup_state.steps(**facts(slug="zed", name="Zed", corpus_root="/nowhere/at/all"))}
        self.assertTrue(s["name"]["done"])
        self.assertFalse(s["corpus"]["done"])
        self.assertIn("root not found", s["corpus"]["detail"])

    def test_loaded_jobs_count_as_cycle_configured(self):
        jobs = [dict(j, loaded=True) for j in JOBS]
        s = {x["id"]: x for x in setup_state.steps(**facts(jobs=jobs))}
        self.assertTrue(s["cycle"]["done"])
        self.assertTrue(s["jobs"]["done"])


class CommandsNameNoMachine(unittest.TestCase):
    def test_no_home_path_in_any_command(self):
        home = os.path.expanduser("~")
        for s in setup_state.steps(**facts()):
            self.assertNotIn(home, s["command"])
            self.assertNotIn(home, s["why"])
            self.assertFalse(s["command"].startswith("/"), s["command"])


if __name__ == "__main__":
    unittest.main()
