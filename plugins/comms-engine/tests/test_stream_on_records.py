"""
`stream` on every record (plan v2, item A3).

1. **`repo.write_item` refuses an item without a stream**, or with one the
   registry does not list, before anything is written; `Both` is written and
   flagged `needs_split`, and `--index` lists it under *needs split*.
2. **`state_check.py` fails on a record without the key** in any state file,
   `--stamp` adds it only where it is missing, and the check then passes.
3. **Listening is per stream**: raw output lands under `state/raw/<slug>/`
   and the search terms come from that stream's engine-local file.
4. **The run log carries the stream** (asserted in `test_runlog`); the pulled
   desk acts carry it (asserted in `test_desk_sync`).

Everything runs against temp copies: `repo.CAL`, `repo.STATE` redirected, the
registry and the search terms read from `tests/fixtures/` (`fixture_memory.py`).
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import fixture_memory  # noqa: E402
import listen  # noqa: E402
import memory  # noqa: E402
import repo  # noqa: E402
import state_check  # noqa: E402


def _item(eid="Q-T-1", **over):
    item = {
        "id": eid, "theme": "#SecondTheme", "stream": "Acme", "type": "Evergreen",
        "finding_id": "F1", "anchor": "A primary source.", "logic": "L1",
        "title": f"Test item {eid}", "hooks_considered": [], "excerpt": "x",
        "post": "Body.", "teaser_linkedin": "LI teaser", "teaser_x": "X teaser",
        "tags": ["#SecondTheme"], "partner_tags": [], "alpha_status": "proposed",
    }
    item.update(over)
    return item


class TempVault(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="stream-records-")
        self._saved = (repo.CAL, repo.STATE)
        repo.CAL = os.path.join(self.tmp, "Calendar")
        repo.STATE = os.path.join(self.tmp, "state")
        os.makedirs(repo.CAL)
        os.makedirs(repo.STATE)

    def tearDown(self):
        repo.CAL, repo.STATE = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)


class WriteItemRefuses(TempVault):
    def test_no_stream_is_refused_before_anything_is_written(self):
        item = _item()
        del item["stream"]
        with self.assertRaises(ValueError) as cm:
            repo.write_item(item, "Idea")
        self.assertIn("no stream", str(cm.exception))
        self.assertEqual(os.listdir(repo.CAL), [])

    def test_empty_stream_is_refused(self):
        with self.assertRaises(ValueError):
            repo.write_item(_item(stream="  "), "Idea")
        self.assertEqual(os.listdir(repo.CAL), [])

    def test_unknown_stream_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            repo.write_item(_item(stream="Umbra"), "Idea")
        self.assertIn("not a stream", str(cm.exception))

    def test_registry_name_round_trips(self):
        repo.write_item(_item(stream="Acme"), "Idea")
        items = repo.load_items()
        self.assertEqual(items[0]["stream"], "Acme")
        self.assertNotIn("needs_split", items[0])

    def test_slug_is_normalised_to_the_registry_name(self):
        repo.write_item(_item(stream="acme"), "Idea")
        self.assertEqual(repo.load_items()[0]["stream"], "Acme")

    def test_both_is_written_and_flagged(self):
        repo.write_item(_item(stream="Both"), "Idea")
        items = repo.load_items()
        self.assertTrue(items[0]["needs_split"])
        self.assertEqual(repo.split_report(items), [("Q-T-1", "Both")])
        repo.write_index(items)
        with open(os.path.join(repo.STATE, "queue.json"), encoding="utf-8") as f:
            self.assertTrue(json.load(f)[0]["needs_split"])


class StateCheck(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        self.state = tempfile.mkdtemp(prefix="state-check-")

    def tearDown(self):
        shutil.rmtree(self.state, ignore_errors=True)

    def _write(self, name, data):
        with open(os.path.join(self.state, name), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_fails_on_a_record_without_the_key_in_each_file(self):
        self._write("queue.json", [{"id": "Q-1", "stream": "Acme"}, {"id": "Q-2"}])
        self._write("runs.json", [{"run_id": "r", "step": "listen", "stream": "Acme"}, {"run_id": "r", "step": "gate"}])
        self._write("decisions.json", {"Q-1": {"status": "approved"}})
        self._write("signals.json", {"run_id": "r", "stream": "Acme", "findings": [{"id": "F1"}]})
        self._write("engagement.json", {"stream": "Acme", "proposals": [{"finding_id": "F1"}]})
        problems, split = state_check.check(self.state)
        self.assertEqual(split, [])
        self.assertEqual(len(problems), 5, problems)
        for name in ("queue.json", "runs.json", "decisions.json", "signals.json", "engagement.json"):
            self.assertTrue(any(p.startswith(name) for p in problems), name)

    def test_unknown_stream_fails_and_both_is_reported_not_failed(self):
        self._write("queue.json", [{"id": "Q-1", "stream": "Umbra"}, {"id": "Q-2", "stream": "Both"}])
        problems, split = state_check.check(self.state)
        self.assertEqual(len(problems), 1)
        self.assertIn("'Umbra'", problems[0])
        self.assertEqual(len(split), 1)

    def test_stamp_adds_only_where_missing_then_check_passes(self):
        self._write("queue.json", [{"id": "Q-1", "stream": "Beta"}, {"id": "Q-2"}])
        self._write("runs.json", [{"run_id": "r", "step": "gate"}])
        n = state_check.stamp("Acme", self.state)
        self.assertEqual(n, 2)
        with open(os.path.join(self.state, "queue.json"), encoding="utf-8") as f:
            q = json.load(f)
        self.assertEqual([i["stream"] for i in q], ["Beta", "Acme"])
        self.assertEqual(state_check.check(self.state), ([], []))

    def test_stamp_refuses_a_name_not_in_the_registry(self):
        with self.assertRaises(memory.SharedMemoryError):
            state_check.stamp("Umbra", self.state)

    def test_cli_exit_codes(self):
        self._write("queue.json", [{"id": "Q-2"}])
        self.assertEqual(state_check.main(["--state", self.state]), 1)
        self.assertEqual(state_check.main(["--state", self.state, "--stamp", "Acme"]), 0)
        self.assertEqual(state_check.main(["--state", self.state]), 0)

    def test_an_empty_state_directory_passes(self):
        """A fresh clone ships no state records: nothing to fail on."""
        problems, split = state_check.check(self.state)
        self.assertEqual((problems, split), ([], []))


class ListeningPerStream(fixture_memory.FixtureMemoryCase):
    """The search terms come from the fixture `themes.json` files, joined to the fixture themes."""

    def setUp(self):
        super().setUp()
        terms = {None: fixture_memory.THEMES_JSON, "acme": fixture_memory.THEMES_JSON,
                 "beta": os.path.join(fixture_memory.ENGINE_STREAMS, "beta", "themes.json")}
        patch = mock.patch.object(listen, "terms_file", lambda stream=None: terms[stream])
        patch.start()
        self.addCleanup(patch.stop)

    def test_raw_dir_per_stream(self):
        self.assertEqual(listen.raw_dir(), os.path.join(listen.STATE, "raw", "acme"))
        self.assertEqual(listen.raw_dir("beta"), os.path.join(listen.STATE, "raw", "beta"))

    def test_an_empty_stream_loads_an_empty_pass(self):
        cfg = listen.load_themes("beta")
        self.assertEqual(cfg["themes"], [])

    def test_root_pass_joins_every_theme_to_a_term(self):
        cfg = listen.load_themes()
        self.assertEqual(len(cfg["themes"]), 8)
        self.assertTrue(all(t["x_search"] for t in cfg["themes"]))
        self.assertEqual(cfg["ignore"], ["betalabs", "beta labs"])

    def test_a_roster_disagreement_stops_the_pass(self):
        with open(fixture_memory.THEMES_JSON, encoding="utf-8") as f:
            local = json.load(f)
        local["search_terms"].pop("#EighthTheme")
        path = os.path.join(self.fixture.root, "themes.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(local, f)
        with mock.patch.object(listen, "terms_file", lambda stream=None: path):
            with self.assertRaises(SystemExit) as cm:
                listen.load_themes()
        self.assertIn("#EighthTheme", str(cm.exception))


class ListeningPaths(unittest.TestCase):
    def test_terms_file_per_stream(self):
        self.assertEqual(listen.terms_file(), os.path.join(listen.REPO, "themes.json"))
        self.assertEqual(listen.terms_file("gamma"), os.path.join(listen.REPO, "streams", "gamma", "themes.json"))


if __name__ == "__main__":
    unittest.main()
