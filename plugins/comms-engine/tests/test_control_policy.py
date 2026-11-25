"""
The Autonomy and Setup pages' side of the engine: the `policy` and `setup` views, and the
control page's `/api/switch` (with a kind), `/api/pause`, `/api/setup` and `/api/takedown`.

- the policy view shows every stream with its pause and, per channel and kind, the mode in
  force; what went out with no person in the loop is listed, and marked once taken down
- a mode, a preset and a pause change over HTTP, each a recorded act, and a refusal is an answer
- the setup file changes only through `change_setup`: checked first, confirmed, recorded as a
  `setup` act, the registry rendered from it; a stale page, an unknown key, a bad value or no
  confirmation writes nothing
- the committed build of the page carries both pages

A fixture memory, a temp state directory and fake drivers: nothing is sent and the checkout's
own brand.json is never read or written.
"""
import http.server
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import acts  # noqa: E402
import brandfile  # noqa: E402
import config  # noqa: E402
import control  # noqa: E402
import memory  # noqa: E402
import switches  # noqa: E402
import views  # noqa: E402
from test_channels_send import TUE_1000  # noqa: E402
from test_switches import SwitchBase  # noqa: E402


class Base(SwitchBase):
    def setUp(self):
        super().setUp()
        for target in (control, views):
            p = mock.patch.object(target, "STATE", self.state)
            p.start()
            self.addCleanup(p.stop)


class PolicyView(Base):
    def test_every_stream_with_its_pause_and_a_mode_per_channel_and_kind(self):
        self.autopilot()
        self.set("like")
        switches.set_pause(self.other, True, state=self.state)
        view = views.policy()
        self.assertEqual(view["kinds"], list(switches.KINDS))
        self.assertEqual(view["presets"], ["review-everything", "review-posts-only", "fully-automatic"])
        root = next(s for s in view["streams"] if s["stream"] == self.root)
        self.assertEqual((root["by_switch"], root["paused"], root["autopilot"]), (True, False, "by switch"))
        x = next(c for c in root["channels"] if c["channel"] == "x")
        modes = {k["kind"]: k["mode"] for k in x["kinds"]}
        self.assertEqual((modes["like"], modes["post"], modes["hold"]), ("auto", "review", "review"))
        self.assertTrue(next(s for s in view["streams"] if s["stream"] == self.other)["paused"])
        self.assertIn("policy", views.VIEWS)
        self.assertIsNotNone(views.snapshot(["policy"])["policy"])

    def test_what_went_out_with_no_person_is_listed_and_marked_once_taken_down(self):
        self.approve("r-reviewed")
        self.send("reply", ref={"id": "r-reviewed"})
        self.turn()
        self.send("reply", text="A second clean line about the register.", ref={"id": "r-auto"})
        rows = views.unreviewed_sends(self.state)
        self.assertEqual([(r["id"], r["kind"], r["channel"], r["taken_down"]) for r in rows], [("r-auto", "reply", "x", None)])
        got = control.takedown("r-auto", state_dir=self.state, driver=self.fake, at=TUE_1000)
        self.assertEqual(got["outcome"], "taken down")
        (row,) = views.unreviewed_sends(self.state)
        self.assertTrue(row["taken_down"])


class Http(Base):
    token = "tok"

    def setUp(self):
        super().setUp()
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), control.make_handler(0, self.token))
        self.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = control.make_handler(self.port, self.token)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def call(self, path, body, token=True):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode(),
                                     headers={"X-Control-Token": self.token} if token else {}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read().decode())

    def test_a_mode_a_preset_and_a_pause_over_http(self):
        self.autopilot()
        body = {"stream": self.root, "channel": "x", "kind": "like", "mode": "auto"}
        self.assertEqual(self.call("/api/switch", dict(body, confirm=True), token=False)[0], 403)
        code, got = self.call("/api/switch", body)
        self.assertEqual(code, 200)
        self.assertIn("confirmation", got["switch"]["outcome"])
        code, got = self.call("/api/switch", dict(body, confirm=True, by="Some Person"))
        self.assertEqual((got["switch"]["outcome"], got["switch"]["by"], got["switch"]["kind"]), ("applied", "alpha", "like"))
        self.assertEqual(switches.mode(self.root, "x", "like", self.state), "auto")
        self.assertEqual(self.call("/api/switch", dict(body, kind="fax", confirm=True))[0], 400)
        self.assertEqual(self.call("/api/switch", dict(body, mode="sometimes", confirm=True))[0], 400)
        code, got = self.call("/api/switch", {"stream": self.root, "preset": "review-everything"})
        self.assertEqual(code, 200)
        self.assertEqual([c["outcome"] for c in got["switch"]["changes"]], ["applied"])
        self.assertEqual(switches.mode(self.root, "x", "like", self.state), "review")
        self.assertEqual(self.call("/api/switch", {"stream": self.root, "preset": "yolo", "confirm": True})[0], 400)
        code, got = self.call("/api/pause", {"stream": self.root, "paused": True})
        self.assertEqual((code, got["pause"]["outcome"]), (200, "applied"))
        self.assertTrue(switches.paused(self.root, self.state))
        code, got = self.call("/api/pause", {"stream": self.root, "paused": False})
        self.assertTrue(got["pause"]["outcome"].startswith("refused: "))
        code, got = self.call("/api/pause", {"stream": self.root, "paused": False, "confirm": True})
        self.assertEqual(got["pause"]["outcome"], "applied")
        self.assertEqual(self.call("/api/pause", {"stream": "nowhere", "paused": True})[0], 400)
        for path in ("/api/pause", "/api/setup", "/api/takedown", "/api/switch"):
            self.assertIn(path, control.ACTIONS)


class SetupFile(Base):
    def setUp(self):
        super().setUp()
        self.path = config.brand_path()
        self.assertTrue(self.path.startswith(self.fixture.root), "the fixture's own setup file, never the checkout's")
        with open(memory.STREAMS_MD, encoding="utf-8") as f:
            self.registry = f.read()
        brandfile.write(brandfile.from_streams_md(self.registry, config.brand()))
        self.base = views.digest(self.path)

    def change(self, changes, **kw):
        kw.setdefault("confirm", True)
        kw.setdefault("base", self.base)
        return control.change_setup(changes, kw.pop("base"), state_dir=self.state, **kw)

    def setup_acts(self):
        return [a for a in acts.list_acts(path=self.acts) if a["kind"] == "setup"]

    def test_the_view_shows_the_file_its_problems_and_whether_the_registry_matches(self):
        f = views.setup()["file"]
        self.assertTrue(f["present"])
        self.assertEqual((f["problems"], f["in_sync"]), ([], True))
        self.assertEqual(f["brand"]["slug"], self.root)
        self.assertEqual(list(f["streams"]), [self.root, self.other])
        self.assertEqual(f["options"]["autopilot"], ["nothing", "by switch"])
        self.assertEqual(f["base"], self.base)

    def test_a_change_is_checked_recorded_and_rendered_into_the_registry(self):
        got = self.change({"streams": {self.root: {"autopilot": "by switch", "narrator": "a newsroom"}}}, by="Some Person")
        self.assertEqual((got["outcome"], got["changed"]), ("applied", [f"streams.{self.root}.autopilot", f"streams.{self.root}.narrator"]))
        self.assertNotEqual(got["base"], self.base)
        self.assertEqual(brandfile.read()["streams"][self.root]["autopilot"], "by switch")
        row = memory.stream(self.root)
        self.assertEqual((row["autopilot"], row["narrator"]), ("by switch", "a newsroom"))
        (act,) = self.setup_acts()
        self.assertEqual((act["by"], act["outcome"], act["target"], act["payload"]["changed"]),
                         ("alpha", "applied", "brand.json", got["changed"]))
        self.assertTrue(act["at"])
        self.assertTrue(views.setup()["file"]["in_sync"])
        self.assertEqual(switches.streams_allow(self.root, "x", "post"), (True, ""), "the switch reads the new setting at once")

    def test_drivers_and_jobs_change_too(self):
        got = self.change({"drivers": {"write": "composio"}, "jobs": {"autopilot": False}})
        self.assertEqual(got["changed"], ["drivers.write", "jobs.autopilot"])
        # read from the merged files themselves: the suite keeps config.cfg off the driver settings
        self.assertEqual(config.load()["params"]["channels"]["write_driver"][self.root], "composio")
        self.assertTrue(config.job("autopilot")["off"])

    def test_refusals_write_nothing(self):
        before = open(self.path, encoding="utf-8").read()
        cases = (
            ({"streams": {self.root: {"owner": "the founder"}}}, {}, "streams.acme.owner"),
            ({"streams": {self.root: {"memory": "elsewhere"}}}, {}, "not changed from this page"),
            ({"streams": {"umbra": {"owner": "unset"}}}, {}, "not a stream"),
            ({"brand": {"slug": "evil"}}, {}, "not changed from this page"),
            ({"drivers": {"write": "carrier-pigeon"}}, {}, "is not a driver"),
            ({"jobs": {"no-such-job": True}}, {}, "no such job"),
            ({"streams": {self.root: {"narrator": "a newsroom"}}}, {"confirm": False}, "confirmation"),
            ({}, {}, "no change named"),
        )
        for changes, kw, why in cases:
            with self.assertRaises(control.Refused, msg=str(changes)) as cm:
                self.change(changes, **kw)
            self.assertIn(why, str(cm.exception))
            self.assertNotIsInstance(cm.exception, control.Conflict)
        with self.assertRaises(control.Conflict):
            self.change({"streams": {self.root: {"narrator": "a newsroom"}}}, base="an-older-digest")
        self.assertEqual(open(self.path, encoding="utf-8").read(), before)
        self.assertEqual(open(memory.STREAMS_MD, encoding="utf-8").read(), self.registry)
        self.assertEqual(self.setup_acts(), [])

    def test_a_change_that_changes_nothing_records_nothing(self):
        row = brandfile.read()["streams"][self.root]
        got = self.change({"streams": {self.root: {"owner": row["owner"]}}})
        self.assertEqual((got["outcome"], got["changed"], got["id"]), ("applied", [], None))
        self.assertEqual(self.setup_acts(), [])


class ReactionsView(Base):
    """The Engagement page's side: the `reactions` view and the one click (`/api/react`)."""

    POST = "1900000000000000001"

    def setUp(self):
        super().setUp()
        import datetime as dt
        import reactions
        self.reactions = reactions
        with open(memory.STREAMS_MD, encoding="utf-8") as f:
            bdoc = brandfile.from_streams_md(f.read(), config.brand())
        bdoc["streams"][self.root]["reactions_per_day"] = {"x": {"like": 3, "repost": 1}}
        brandfile.write(bdoc)
        partner = next(row["x"] for row in memory.taggable_handles(self.root).values() if row.get("x")).lstrip("@")
        with open(os.path.join(self.state, "listening-2026-11-10.json"), "w", encoding="utf-8") as f:
            json.dump({"items": [{"id": self.POST, "source": "x", "author": partner, "text": "The standard is the public part.",
                                  "created_at": (TUE_1000 - dt.timedelta(hours=3)).isoformat(), "_matched_term": "#SecondTheme"}]}, f)
        reactions.plan(self.root, self.state, now=TUE_1000)

    def test_the_view_groups_the_candidates_and_says_the_rules(self):
        view = views.reactions()
        self.assertEqual({c["id"] for c in view["queued"]}, {f"like:{self.POST}", f"repost:{self.POST}"})
        self.assertEqual((view["waiting"], view["done"], view["refused"], view["live"]), ([], [], [], False))
        rules = {(r["channel"], r["kind"]): r for r in view["rules"] if r["stream"] == self.root}
        self.assertEqual((rules[("x", "like")]["cap"], rules[("x", "like")]["click_only"], rules[("x", "like")]["mode"]), (3, True, "review"))
        self.assertEqual(rules[("x", "repost")]["cap"], 1)
        self.assertNotIn(("linkedin", "like"), rules, "no tool likes on LinkedIn, so no rule is shown for it")
        self.assertNotIn("@", json.dumps(view))
        self.assertIn("reactions", views.VIEWS)

    def test_one_click_sends_it_and_it_can_be_undone(self):
        got = control.react(f"like:{self.POST}", by="Some Person", state_dir=self.state, driver=self.fake, at=TUE_1000)
        self.assertEqual((got["outcome"], got["kind"]), ("sent", "like"))
        self.assertEqual(self.fake.calls[-1]["kind"], "like")
        view = views.reactions()
        self.assertEqual([c["id"] for c in view["done"]], [f"like:{self.POST}"])
        self.assertEqual(view["earned"], {"institution / like": {"placed": 1, "author replied": 0, "follow": 0, "nothing": 0, "open": 1}})
        self.assertEqual(views.unreviewed_sends(self.state), [], "a like a person clicked was reviewed")
        with self.assertRaises(control.Refused):
            control.react(f"like:{self.POST}", state_dir=self.state, driver=self.fake, at=TUE_1000)
        with self.assertRaises(control.Refused):
            control.react("", state_dir=self.state)
        control.takedown(f"like:{self.POST}", state_dir=self.state, driver=self.fake, at=TUE_1000)
        self.assertTrue(views.reactions()["done"][0]["undone"])
        self.assertIn("/api/react", control.ACTIONS)


class TheBuiltPage(Base):
    def test_the_committed_build_carries_both_pages(self):
        dist = os.path.join(ENGINE, "ui", "dist")
        with open(os.path.join(dist, "index.html"), encoding="utf-8") as f:
            index = f.read()
        import re
        script = re.search(r'src="/assets/(index-[^"]+\.js)"', index).group(1)
        with open(os.path.join(dist, "assets", script), encoding="utf-8") as f:
            js = f.read()
        for words in ("Sent without review", "Pause every send", "Fully automatic", "/api/pause", "/api/setup", "/api/takedown",
                      "Save changes", "Waiting for your click", "/api/react", "A like on X always waits for your click"):
            self.assertIn(words, js, f"ui/dist is older than ui/src: rebuild it (missing {words!r})")


if __name__ == "__main__":
    import unittest
    unittest.main()
