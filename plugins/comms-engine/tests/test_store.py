"""
store.py and acts.py: the interface on the files driver.

- append_act, acts(since, status) and mark round-trip through state/acts.jsonl
- an outcome is the last mark; status filters pending, applied, skipped, refused
- a repeated id, an unknown id on mark and an empty field are refused
- a torn last line is skipped on read and does not spoil the next append
- params.store.driver is `files`; any other driver is refused
- acts.py: kinds, role-only `by`, the three outcomes, nothing rewritten
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import acts  # noqa: E402
import config  # noqa: E402
import store  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "acts.jsonl")

    def act(self, id, at="2026-11-10T10:00:00Z", **kw):
        d = {"id": id, "at": at, "stream": "acme", "kind": "decision", "target": "post-1",
             "payload": {"verdict": "approve"}, "base": None, "by": "alpha"}
        d.update(kw)
        return d


class Store(Base):
    def test_shipped_driver_is_files(self):
        self.assertEqual(config.cfg("store.driver"), "files")
        self.assertEqual(store.driver(), "files")

    def test_other_driver_refused(self):
        with mock.patch.object(config, "cfg", return_value="sqlite"):
            with self.assertRaises(store.StoreError):
                store.append_act(self.act("a1"), path=self.path)
        self.assertFalse(os.path.exists(self.path))

    def test_default_path_is_state_acts_jsonl(self):
        self.assertTrue(store.acts_path().endswith(os.path.join("state", "acts.jsonl")))

    def test_append_and_read_back(self):
        store.append_act(self.act("a1"), path=self.path)
        store.append_act(self.act("a2", at="2026-11-10T11:00:00Z"), path=self.path)
        got = store.acts(path=self.path)
        self.assertEqual([a["id"] for a in got], ["a1", "a2"])
        self.assertIsNone(got[0]["outcome"])
        with open(self.path) as f:
            self.assertEqual(len(f.readlines()), 2)

    def test_stream_argument_and_default_time(self):
        a = store.append_act({"id": "a1", "kind": "watch"}, stream="beta", path=self.path)
        self.assertEqual(a["stream"], "beta")
        self.assertRegex(a["at"], r"^\d{4}-\d\d-\d\dT")

    def test_since(self):
        store.append_act(self.act("a1", at="2026-11-09T10:00:00Z"), path=self.path)
        store.append_act(self.act("a2", at="2026-11-10T10:00:00Z"), path=self.path)
        self.assertEqual([a["id"] for a in store.acts(since="2026-11-10T00:00:00Z", path=self.path)], ["a2"])

    def test_mark_and_status(self):
        for i in ("a1", "a2", "a3", "a4"):
            store.append_act(self.act(i), path=self.path)
        store.mark("a1", "applied", path=self.path)
        store.mark("a2", "skipped: moved", path=self.path)
        store.mark("a3", "refused: stale base", path=self.path)
        ids = lambda s: [a["id"] for a in store.acts(status=s, path=self.path)]  # noqa: E731
        self.assertEqual(ids("pending"), ["a4"])
        self.assertEqual(ids("applied"), ["a1"])
        self.assertEqual(ids("skipped"), ["a2"])
        self.assertEqual(ids("refused"), ["a3"])
        self.assertEqual(ids("refused: stale base"), ["a3"])

    def test_last_mark_wins_and_nothing_rewritten(self):
        store.append_act(self.act("a1"), path=self.path)
        store.mark("a1", "refused: busy", path=self.path)
        store.mark("a1", "applied", path=self.path)
        self.assertEqual(store.acts(path=self.path)[0]["outcome"], "applied")
        with open(self.path) as f:
            self.assertEqual(len(f.readlines()), 3)

    def test_refusals(self):
        store.append_act(self.act("a1"), path=self.path)
        with self.assertRaises(store.StoreError):
            store.append_act(self.act("a1"), path=self.path)
        with self.assertRaises(store.StoreError):
            store.mark("nope", "applied", path=self.path)
        with self.assertRaises(store.StoreError):
            store.mark("a1", "", path=self.path)
        for bad in ({"id": "", "stream": "s", "kind": "k"}, {"id": "x", "stream": "s"}, {"id": "x", "kind": "k"}):
            with self.assertRaises(store.StoreError):
                store.append_act(bad, path=self.path)
        with self.assertRaises(store.StoreError):
            store.append_act(self.act("a9", outcome="applied"), path=self.path)

    def test_torn_last_line(self):
        store.append_act(self.act("a1"), path=self.path)
        with open(self.path, "a") as f:
            f.write('{"id": "a2", "at": "2026-11')  # cut short, no newline
        self.assertEqual([a["id"] for a in store.acts(path=self.path)], ["a1"])
        store.append_act(self.act("a3"), path=self.path)
        self.assertEqual([a["id"] for a in store.acts(path=self.path)], ["a1", "a3"])
        store.mark("a3", "applied", path=self.path)
        self.assertEqual(store.acts(status="applied", path=self.path)[0]["id"], "a3")

    def test_missing_file_is_empty(self):
        self.assertEqual(store.acts(path=self.path), [])


class Acts(Base):
    def test_record_shape(self):
        a = acts.record("decision", "acme", "post-1", {"verdict": "approve"}, base="h1", by="alpha", path=self.path)
        self.assertEqual(set(a), {"id", "at", "stream", "kind", "target", "payload", "base", "by"})
        self.assertEqual(acts.list_acts(status="pending", path=self.path)[0]["id"], a["id"])

    def test_kind_and_role(self):
        with self.assertRaises(acts.ActError):
            acts.record("bogus", "acme", "t", path=self.path)
        for by in ("Someone", "a@b.co", "two words", ""):
            with self.assertRaises(acts.ActError):
                acts.record("decision", "acme", "t", by=by, path=self.path)
        self.assertFalse(os.path.exists(self.path))

    def test_every_kind_accepted(self):
        for k in acts.KINDS:
            acts.record(k, "acme", "t", path=self.path)
        self.assertEqual(len(acts.list_acts(path=self.path)), len(acts.KINDS))

    def test_outcomes(self):
        ids = [acts.record("edit", "acme", "t", path=self.path)["id"] for _ in range(3)]
        acts.applied(ids[0], path=self.path)
        acts.skipped(ids[1], path=self.path)
        acts.refused(ids[2], "not scheduled", path=self.path)
        out = {a["id"]: a["outcome"] for a in acts.list_acts(path=self.path)}
        self.assertEqual(out, {ids[0]: "applied", ids[1]: "skipped: moved", ids[2]: "refused: not scheduled"})
        with self.assertRaises(acts.ActError):
            acts.refused(ids[0], "  ", path=self.path)
        with self.assertRaises(acts.ActError):
            acts.check_outcome("done")


if __name__ == "__main__":
    unittest.main()
