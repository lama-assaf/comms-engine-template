"""
The replies view's approve-and-send (`control.approve_reply`, `/api/approve-reply`).

The write driver is always faked and the state directory is a temp one: no platform is
called and the real acts, sends and ledger are untouched. The approval act, the send
through `channels.send()` with every check, its line in `sends.jsonl` and the outcome
the replies view reads back are what is asserted.
"""
import http.server
import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import acts  # noqa: E402
import channels  # noqa: E402
import control  # noqa: E402
import desk_sync  # noqa: E402
import views  # noqa: E402
from test_channels_send import CLEAN, SAT_1000, TUE_1000, Fake, SendBase  # noqa: E402

TARGET = "https://x.com/other/status/9"


class ReplyBase(SendBase):
    def setUp(self):
        super().setUp()
        self.proposal = {"finding_id": "F1", "theme": "#T", "platform": "X", "target_url": TARGET, "target_post": "9",
                         "tier": "peer", "draft_comment": CLEAN, "why": "the thread leaves it open"}
        self.pid = desk_sync.proposal_id(self.proposal)
        self.write_proposals([self.proposal])
        for target, name in ((control, "STATE"), (views, "STATE")):
            p = mock.patch.object(target, name, self.state)
            p.start()
            self.addCleanup(p.stop)

    def write_proposals(self, proposals):
        with open(os.path.join(self.state, "engagement.json"), "w", encoding="utf-8") as f:
            json.dump({"proposals": proposals}, f)

    def approve_reply(self, by="alpha", at=TUE_1000, driver="fake", pid=None, reason="the thread leaves it open", scope=None):
        return control.approve_reply(pid or self.pid, by, state_dir=self.state, driver=self.fake if driver == "fake" else driver,
                                     at=at, reason=reason, scope=scope)


class ApproveAndSend(ReplyBase):
    def test_records_the_approval_for_the_exact_text_and_sends_a_reply(self):
        got = self.approve_reply()
        self.assertEqual((got["outcome"], got["kind"], got["channel"]), ("sent", "reply", "x"))
        self.assertEqual(got["url"], "https://x.com/own/status/1")
        req = self.fake.calls[0]
        self.assertEqual((req["kind"], req["target"], req["text"]), ("reply", TARGET, CLEAN))
        act = acts.list_acts(path=self.acts)[0]
        self.assertEqual((act["kind"], act["target"], act["outcome"], act["by"]), ("decision", self.pid, "applied", "alpha"))
        self.assertEqual(act["payload"]["decision"], "approve")
        self.assertEqual(act["base"], channels.text_hash("x", CLEAN))
        self.assertEqual([r["outcome"] for r in self.lines()], ["sent"])
        self.assertEqual(self.lines()[0]["id"], self.pid)

    def test_a_reply_is_sent_with_no_reason_and_no_review_is_recorded(self):
        got = self.approve_reply(reason="", scope="standing")
        self.assertEqual(got["outcome"], "sent")
        (act,) = acts.list_acts(path=self.acts)
        self.assertEqual((act["kind"], act["payload"]["note"]), ("decision", ""))
        self.assertEqual(len(self.fake.calls), 1)
        self.assertFalse(os.path.exists(os.path.join(self.state, "desk.db")), "no reason, no review row")

    def test_the_reason_is_kept_as_the_approvals_note_and_as_a_desk_review(self):
        import sqlite3
        got = self.approve_reply(reason="  the thread leaves it open ", scope="standing")
        self.assertEqual(got["outcome"], "sent")
        (act, review_act) = acts.list_acts(path=self.acts)
        self.assertEqual(act["payload"]["note"], "the thread leaves it open")
        con = sqlite3.connect(os.path.join(self.state, "desk.db"))
        (row,) = con.execute("SELECT item_id, kind, verdict, rationale, scope, by, synced_at FROM reviews").fetchall()
        self.assertEqual(row, (self.pid, "reaction", "approved", "the thread leaves it open", "standing", "alpha", None))
        self.assertEqual((review_act["kind"], review_act["payload"]["scope"], review_act["outcome"]), ("review", "standing", "applied"))

    def test_a_refused_send_records_no_review_and_a_bad_scope_is_refused(self):
        self.approve_reply(at=SAT_1000)
        self.assertFalse(os.path.exists(os.path.join(self.state, "desk.db")))
        with self.assertRaises(control.Refused):
            self.approve_reply(scope="forever")

    def test_a_name_is_never_the_actor(self):
        self.approve_reply(by="Some Person")
        self.assertEqual(acts.list_acts(path=self.acts)[0]["by"], "alpha")

    def test_a_check_still_refuses_and_the_driver_is_not_called(self):
        got = self.approve_reply(at=SAT_1000)
        self.assertEqual((got["outcome"], got["check"]), ("refused", "guardrails"))
        self.assertTrue(got["reason"])
        self.assertEqual(self.fake.calls, [])
        last = self.lines()[-1]
        self.assertEqual((last["outcome"], last["check"], last["id"]), ("refused", "guardrails", self.pid))

    def test_the_gate_refuses_a_blocked_text(self):
        bad = f"{self.root_name()} issues the credential today."
        self.write_proposals([dict(self.proposal, draft_comment=bad)])
        got = self.approve_reply()
        self.assertEqual((got["outcome"], got["check"]), ("refused", "gate"))
        self.assertEqual(self.fake.calls, [])

    def root_name(self):
        import memory
        return memory.stream(self.root)["name"]

    def test_a_second_approve_does_not_send_twice(self):
        self.approve_reply()
        got = self.approve_reply()
        self.assertEqual((got["outcome"], got["check"]), ("refused", "dedupe"))
        self.assertEqual(len(self.fake.calls), 1)

    def test_a_failing_driver_is_an_answer_not_an_error(self):
        got = self.approve_reply(driver=Fake(fail="boom"))
        self.assertEqual(got["outcome"], "failed")
        self.assertIn("boom", got["reason"])
        self.assertEqual(self.lines()[-1]["outcome"], "failed")

    def test_a_linkedin_proposal_is_a_comment_on_its_urn(self):
        p = dict(self.proposal, finding_id="F2", platform="LinkedIn", target_url="https://www.linkedin.com/feed/update/urn:li:share:5",
                 target_post="urn:li:share:5")
        self.write_proposals([p])
        got = self.approve_reply(pid=desk_sync.proposal_id(p))
        self.assertEqual((got["outcome"], got["kind"], got["channel"]), ("sent", "comment", "linkedin"))
        self.assertEqual(self.fake.calls[0]["target"], "urn:li:share:5")

    def test_no_target_unknown_id_and_empty_id_are_refused_without_an_act(self):
        self.write_proposals([dict(self.proposal, target_url="", target_post="")])
        for pid in (self.pid, "C-nope-", ""):
            with self.assertRaises(control.Refused):
                self.approve_reply(pid=pid)
        self.assertEqual(acts.list_acts(path=self.acts), [])
        self.assertEqual(self.fake.calls, [])

    def test_the_replies_view_shows_the_outcome_or_the_reason(self):
        with mock.patch.object(views, "heard_text", lambda: {}):
            self.assertIsNone(views.replies()["proposals"][0]["send"])
            self.approve_reply(at=SAT_1000)
            send = views.replies()["proposals"][0]["send"]
            self.assertEqual((send["outcome"], send["check"]), ("refused", "guardrails"))
            self.assertTrue(send["reason"])
            self.approve_reply()
            send = views.replies()["proposals"][0]["send"]
            self.assertEqual((send["outcome"], send["url"]), ("sent", "https://x.com/own/status/1"))
            self.assertEqual(views.replies()["proposals"][0]["id"], self.pid)

    def test_the_driver_comes_from_the_streams_write_driver(self):
        with mock.patch.object(channels, "write_driver", return_value=("composio", None)):
            self.assertIs(control.reply_driver(self.root, "x"), channels.x_driver)
            self.assertIs(control.reply_driver(self.root, "linkedin"), channels.linkedin_driver)
        with mock.patch.object(channels, "write_driver", return_value=("native", None)):
            import autopilot
            self.assertIs(control.reply_driver(self.root, "x"), autopilot.NATIVE_DRIVERS["x"])


class Endpoint(unittest.TestCase):
    token = "tok"

    def setUp(self):
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), control.make_handler(0, self.token))
        self.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = control.make_handler(self.port, self.token)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def call(self, body, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/approve-reply", data=json.dumps(body).encode(),
                                     headers=headers or {}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def test_needs_the_token_and_the_origin_and_answers_with_the_send(self):
        with mock.patch.object(control, "approve_reply", return_value={"outcome": "refused", "check": "gate"}) as ap:
            self.assertEqual(self.call({"id": "C-F1-"})[0], 403)
            self.assertEqual(self.call({"id": "C-F1-"}, {"X-Control-Token": self.token, "Origin": "https://evil.example"})[0], 403)
            ap.assert_not_called()
            code, body = self.call({"id": "C-F1-", "by": "alpha"}, {"X-Control-Token": self.token})
            self.assertEqual((code, body["send"]["check"]), (200, "gate"))
            ap.assert_called_once_with("C-F1-", "alpha", reason=None, scope=None)
        code, _ = self.call({"id": ""}, {"X-Control-Token": self.token})
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
