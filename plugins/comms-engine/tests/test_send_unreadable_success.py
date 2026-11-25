"""
A Composio create call that answered `successful: true` is a post that exists, whether or not
its body can be read. The driver then records it as sent with an unknown url and a warning on
the run log; it never raises, so no ledger row is left that a later run could send again. A
genuine failure (`successful: false`, an HTTP error) still records `failed`.
"""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import channels  # noqa: E402
import fake_composio_http  # noqa: E402
import gate_lint  # noqa: E402
import lifecycle  # noqa: E402
import runlog  # noqa: E402
import test_channels_send as base  # noqa: E402

PASS = base.PASS


class UnreadableSuccess(base.SendBase):
    def post(self, reply, driver=None, pid="p1", error_status=None, text=base.CLEAN):
        fake = fake_composio_http.install(self, reply=reply)
        if error_status:
            fake.status = error_status
        self.schedule_post(pid)
        with mock.patch.object(gate_lint, "lint", return_value=PASS):
            return fake, self.send("post", text=text, ref={"id": pid, "item": {}}, driver=driver or channels.x_driver)

    def ledger_row(self, pid="p1"):
        return channels._load_ledger(self.state)["sends"][pid]

    def test_success_with_an_unreadable_body_is_sent_with_an_unknown_url(self):
        for n, reply in enumerate(({"successful": True, "data": {"note": "no id here"}},
                                   {"successful": True, "data": {"data": {"id": "not-a-number"}}})):
            pid = f"p{n + 1}"
            _, out = self.post(reply, pid=pid, text=f"{base.CLEAN} Variant {n}.")
            self.assertEqual("", out["url"])
            row = self.ledger_row(pid)
            self.assertEqual("sent", row["state"])
            self.assertEqual("", row["url"])
            self.assertEqual("sent", lifecycle.state(pid, self.lc))
            last = [s for s in self.lines() if s["id"] == pid][-1]
            self.assertEqual("sent", last["outcome"])
            self.assertIn("no readable post id", last["warning"])

    def test_the_warning_is_logged_on_the_run_log_without_values(self):
        self.post({"successful": True, "data": {"note": "SECRET-TEXT"}})
        runs = runlog.load(os.path.join(self.state, "runs.json"))
        self.assertEqual(1, len(runs))
        self.assertEqual("send-warning", runs[0]["step"])
        self.assertIn("recorded as sent with an unknown url", runs[0]["detail"])
        self.assertNotIn("SECRET-TEXT", runs[0]["detail"])
        self.assertEqual(memory_name(self.root), runs[0]["stream"])

    def test_the_next_send_of_the_same_text_is_refused_as_a_duplicate(self):
        fake, _ = self.post({"successful": True, "data": {}})
        self.assertEqual(1, len(fake.executes))
        self.schedule_post("p2")
        with mock.patch.object(gate_lint, "lint", return_value=PASS):
            with self.assertRaises(channels.SendRefused) as cm:
                self.send("post", ref={"id": "p2", "item": {}}, driver=channels.x_driver)
            with self.assertRaises(channels.SendRefused) as again:
                self.send("post", ref={"id": "p1", "item": {}}, driver=channels.x_driver)
        self.assertEqual("dedupe", cm.exception.check)
        self.assertEqual("dedupe", again.exception.check)
        self.assertEqual(1, len(fake.executes), "the create tool is not called a second time")

    def test_a_readable_success_has_no_warning(self):
        _, out = self.post({"successful": True, "data": {"data": {"id": "123"}}})
        self.assertEqual("https://x.com/i/web/status/123", out["url"])
        self.assertNotIn("warning", [s for s in self.lines() if s["outcome"] == "sent"][-1])
        self.assertFalse(os.path.exists(os.path.join(self.state, "runs.json")))

    def test_successful_false_still_records_failed(self):
        with self.assertRaises(channels.ChannelError):
            self.post({"successful": False, "error": "forbidden", "data": {}})
        self.assertEqual("failed", self.ledger_row()["state"])
        self.assertEqual("failed", self.lines()[-1]["outcome"])

    def test_an_http_error_still_records_failed(self):
        with self.assertRaises(channels.ChannelError):
            self.post({"successful": True}, error_status=500)
        self.assertEqual("failed", self.ledger_row()["state"])


class LinkedInUnreadable(base.SendBase):
    def test_a_linkedin_post_with_no_urn_is_sent_with_an_unknown_url(self):
        import linkedin_api
        fake_composio_http.install(self, reply={"successful": True, "data": {"note": "x"}})
        self.schedule_post("p1")
        with mock.patch.object(gate_lint, "lint", return_value=PASS), \
                mock.patch.object(linkedin_api, "settings", return_value={"LINKEDIN_ORG_ID": "555"}):
            out = self.send("post", channel="linkedin", ref={"id": "p1", "item": {}}, driver=channels.linkedin_driver)
            self.assertEqual("", out["url"])
            row = channels._load_ledger(self.state)["sends"]["p1"]
            self.assertEqual("sent", row["state"])
            self.schedule_post("p2")
            with self.assertRaises(channels.SendRefused) as cm:
                self.send("post", channel="linkedin", ref={"id": "p2", "item": {}}, driver=channels.linkedin_driver)
        self.assertEqual("dedupe", cm.exception.check)
        self.assertTrue(any("no readable urn" in r["detail"] for r in runlog.load(os.path.join(self.state, "runs.json"))))


def memory_name(stream):
    import memory
    return memory.stream(stream)["name"]


if __name__ == "__main__":
    unittest.main()
