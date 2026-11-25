"""
Run-level send parity (scripts/parity.py): the sender run once through the native write drivers
and once through the Composio ones, over the same due rows, with the platform layer faked.

The two runs, over notes held in memory, must select and refuse the same posts, issue the same kinds of send in the same
order, write the same ledger entries, and each platform call must carry the same text, the same
account and the same reply target. Nothing real is called: a call that reaches the fake outside
the platform layer fails the case.
"""
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import channels  # noqa: E402
import parity  # noqa: E402
import repo  # noqa: E402

try:
    import fixture_memory  # noqa: E402
    Base = fixture_memory.FixtureMemoryCase
except ImportError:  # the checkout without the fixture suite reads its own memory
    Base = unittest.TestCase


def digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class FixtureRun(Base):
    def setUp(self):
        super().setUp()
        self.case = parity.fixture_case()
        self.native, self.composio, self.diffs = parity.check(self.case)

    def test_the_two_runs_match(self):
        self.assertEqual([], self.diffs)

    def test_the_same_rows_are_selected_and_refused(self):
        n, c = self.native, self.composio
        self.assertEqual(n["refused"], c["refused"])
        self.assertEqual(n["log"], c["log"])
        self.assertEqual(set(n["ledger"]), set(c["ledger"]))
        text = "\n".join(n["refused"])
        for why in ("Team stale", "Team with a link", "Team duplicate", "Team over the daily cap"):
            self.assertIn(why, text)
        self.assertNotIn("Team future", text, "a future row waits without a word")
        self.assertNotIn("Another stream", "\n".join(n["log"]), "another stream's row is never touched")
        self.assertNotIn("t6:x", n["ledger"])

    def test_the_same_kinds_of_send_in_the_same_order(self):
        n, c = self.native, self.composio
        self.assertGreaterEqual(len(n["kinds"]), 7)
        self.assertEqual(n["kinds"], c["kinds"])
        self.assertEqual(n["sent_order"], c["sent_order"])
        kinds = {tuple(k) for k in n["kinds"]}
        for expected in (("X", "post"), ("X", "reply"), ("LinkedIn", "post"), ("LinkedIn", "comment")):
            self.assertIn(expected, kinds)

    def test_the_same_ledger_entries(self):
        n, c = self.native, self.composio
        self.assertEqual(n["ledger"], c["ledger"])
        self.assertEqual(n["sends"], c["sends"])
        self.assertEqual(n["lifecycle"], c["lifecycle"])
        self.assertEqual("failed", n["ledger"]["t8:linkedin"]["state"])
        self.assertEqual("sent", n["ledger"]["t9:linkedin"]["state"], "the post after a failed send still goes")
        self.assertEqual(n["ledger"]["e1:x"]["link_reply"]["link"], c["ledger"]["e1:x"]["link_reply"]["link"])
        self.assertIn("link_reply", n["ledger"]["old1:x"], "the step that adds a link-reply behaves the same")
        self.assertEqual(n["publish_log"], c["publish_log"])
        self.assertEqual({"e1:x", "e1:linkedin"}, {k for k in n["ledger"] if k.startswith("e1:") and "#" not in k},
                         "one item sends once per channel, each under its own id")

    def test_each_call_carries_the_same_text_account_and_reply_target(self):
        n, c = self.native, self.composio
        self.assertEqual(n["calls"], c["calls"])
        for a, b in zip(n["calls"], c["calls"]):
            for field in ("platform", "op", "text", "account", "target"):
                self.assertEqual(a[field], b[field], field)
        x_account = {call["account"] for call in n["calls"] if call["platform"] == "X"}
        self.assertEqual({parity.ap.STREAM}, x_account, "X goes out on the stream's own account")
        li_account = {call["account"] for call in n["calls"] if call["platform"] == "LinkedIn"}
        self.assertEqual({"urn:li:organization:555"}, li_account)
        replies = [call for call in n["calls"] if call["op"] in ("reply", "comment")]
        self.assertEqual(3, len(replies))
        self.assertTrue(all(call["target"] for call in replies), "a reply always names what it answers")
        x_reply = next(call for call in replies if call["platform"] == "X" and call["target"] == "777")
        self.assertIn("insights/later", x_reply["text"])

    def test_nothing_outside_the_platform_layer_was_called(self):
        self.assertEqual([], self.native["unexpected"])
        self.assertEqual([], self.composio["unexpected"])

    def test_a_difference_between_the_driver_sets_is_reported(self):
        real = channels.x_driver

        def altered(request):
            return real(dict(request, text=request["text"].upper()))
        with mock.patch.object(channels, "x_driver", altered):
            _, _, diffs = parity.check(self.case)
        self.assertTrue(any(d.startswith("calls:") for d in diffs), diffs)

    def test_a_dropped_reply_target_is_reported(self):
        real = channels.x_driver

        def dropped(request):
            if request["kind"] == "link-reply":
                raise channels.ChannelError("no target")
            return real(request)
        with mock.patch.object(channels, "x_driver", dropped):
            _, _, diffs = parity.check(self.case)
        self.assertTrue(diffs)


class Records(Base):
    def test_real_records_are_never_written(self):
        names = [os.path.join(parity.STATE, n) for n in parity.RECORDS]
        before = {p: digest(p) for p in names if os.path.exists(p)}
        existed = {p for p in names if os.path.exists(p)}
        parity.check(parity.fixture_case())
        self.assertEqual(before, {p: digest(p) for p in existed})
        self.assertEqual(existed, {p for p in names if os.path.exists(p)})

    def test_an_earlier_send_in_the_copied_records_is_refused_the_same_way(self):
        src = tempfile.mkdtemp()
        case = parity.fixture_case()
        case["seed"] = None
        today = case["today"]
        text = "A teaser that went out already."
        case.update(notes={"d1": parity.note("d1", "Said before", today, x=text)},
                    seed=lambda state: parity._seed(state, "d1:x", "X", text, today))
        name = parity.ap.STREAM_NAME
        h = channels.text_hash("x", "A teaser that went out already.")
        channels._save_ledger(src, {"sends": {"d0": {"page_id": "d0", "platform": "X", "title": "t", "hash": h,
                                                     "state": "sent", "at": "2026-11-04T10:00:00Z", "stream": name,
                                                     "kind": "post", "url": "https://x.com/i/web/status/1"}}})
        n, c, diffs = parity.check(case, state_src=src)
        self.assertEqual([], diffs)
        self.assertEqual([], n["kinds"])
        self.assertTrue(any(line.startswith("duplicate") for line in n["refused"]))


class NotesCase(Base):
    def notes(self, *pairs):
        cal = tempfile.mkdtemp()
        for pair in pairs:
            for name, fm, body in pair.values():
                repo.write_note(os.path.join(cal, name), fm, body)
        return cal

    def test_notes_with_nothing_scheduled_match_trivially(self):
        today = dt.date(2026, 11, 5)
        cal = self.notes(parity.note("a", "Row a", today, x="A notes teaser, one sentence."))
        n, c, diffs = parity.check(parity.notes_case(cal, today=today), today=today)
        self.assertEqual(([], []), (diffs, n["kinds"]))

    def test_rehearse_schedules_the_first_teasers_and_they_go_the_same_way(self):
        today = dt.date(2026, 11, 5)
        cal = self.notes(parity.note("a", "Row a", today, x="A notes teaser, one sentence.",
                                     linkedin="A notes teaser for readers on LinkedIn."),
                         parity.note("b", "Row b", today, x="Another teaser."),
                         parity.note("e", "Row e", today, x="Other stream.", stream="Elsewhere"))
        case = parity.notes_case(cal, rehearse=2, today=today)
        self.assertIn("rehearsing 2", case["name"])
        n, c, diffs = parity.check(case, today=today)
        self.assertEqual([], diffs)
        self.assertEqual([("X", "post"), ("LinkedIn", "post")], sorted(map(tuple, n["kinds"]), reverse=True))
        self.assertEqual({"a:x", "a:linkedin"}, set(n["ledger"]))


class Cli(Base):
    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = parity.main(list(argv))
        return code, out.getvalue()

    def test_dry_is_required(self):
        self.assertEqual(2, self.run_main("--fixtures")[0])

    def test_fixtures_run_matches_and_prints_the_calls(self):
        code, out = self.run_main("--dry", "--fixtures")
        self.assertEqual(0, code)
        self.assertIn("MATCH", out)
        self.assertIn("LinkedIn comment", out)

    def test_json_output_names_both_traces(self):
        code, out = self.run_main("--dry", "--fixtures", "--json")
        data = json.loads(out)
        self.assertEqual(0, code)
        self.assertTrue(data[0]["match"])
        self.assertEqual({"native", "composio"}, {data[0]["native"]["driver"], data[0]["composio"]["driver"]})


if __name__ == "__main__":
    unittest.main()
