"""
Motion cards and films as post media, and the paid skill behind its sign-off.

- a channel takes the file it can carry: X the card's video (else its GIF), a LinkedIn page the
  poster; a card whose words are no longer the post's is not attached at all
- the file's hash is recorded on the approval of each channel's post, and `channels.send()` hashes
  the file again at the send: a file that changed, is missing, was never part of the approval, or
  is not a motion file of this repository is refused, and the post does not go out without what
  was approved
- the drivers stage the file with Composio (the upload request, then the file to the presigned
  URL with no key on it) and hand the tool the descriptor; a LinkedIn page video is refused by
  name; the native drivers refuse media
- `motion:generate` is refused by the Skill hook unless a person recorded a cost sign-off, and
  when the sign-off cannot be read; `motion:post` never opens; every other skill passes
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(ENGINE))
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, os.path.join(ENGINE, "hooks"))
sys.path.insert(0, HERE)

import acts  # noqa: E402
import autopilot as ap  # noqa: E402
import channels  # noqa: E402
import desk_acts  # noqa: E402
import fake_composio_http  # noqa: E402
import guard_skills  # noqa: E402
import linkedin_api  # noqa: E402
import motion  # noqa: E402
from test_autopilot import X_TEXT, Post  # noqa: E402


class MediaBase(Post):
    """The Post fixture with a motion directory of its own and one rendered card in it."""

    def setUp(self):
        super().setUp()
        ap.DRY = False
        self.motion_dir = os.path.join(self.tmp, "Content", "Motion")
        os.makedirs(os.path.join(self.motion_dir, "Q-1"))
        for target, name, value in ((motion, "MOTION_DIR", self.motion_dir), (motion, "FILMS", os.path.join(self.tmp, "videos")),
                                    (channels, "REPO", self.tmp), (motion.repo, "REPO", self.tmp)):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.files = {}
        for which, name, data in (("video", "Q-1-square.mp4", b"mp4-bytes"), ("gif", "Q-1-square.gif", b"gif-bytes"),
                                  ("poster", "Q-1-square-poster.png", b"png-bytes")):
            path = os.path.join(self.motion_dir, "Q-1", name)
            with open(path, "wb") as f:
                f.write(data)
            self.files[which] = path
        self.current = True
        p = mock.patch.object(motion, "card", lambda item_id, item=None: dict(
            self.files if item_id == "Q-1" else {}, current=self.current if item_id == "Q-1" else None, source="card", storyboard=True))
        p.start()
        self.addCleanup(p.stop)

    def channel_act(self, cid):
        return next(a for a in acts.list_acts(path=self.apath) if a["target"] == cid and a["kind"] == "decision")


class WhichFile(MediaBase):
    def test_each_channel_takes_the_file_it_can_carry(self):
        item = {"id": "Q-1"}
        x = motion.media_for(item, "x")
        self.assertEqual((x["path"], x["kind"], x["source"]), ("Content/Motion/Q-1/Q-1-square.mp4", "video", "card"))
        self.assertEqual(x["sha256"], channels.file_sha256(self.files["video"]))
        self.assertEqual(motion.media_for(item, "linkedin")["kind"], "image", "a LinkedIn page takes the poster")
        os.remove(self.files["video"])
        self.assertEqual(motion.media_for(item, "x")["kind"], "gif", "no video on this machine: the GIF")
        self.assertIsNone(motion.media_for(item, "telegram"))

    def test_a_card_the_post_moved_past_is_not_attached(self):
        self.current = False
        self.assertIsNone(motion.media_for({"id": "Q-1"}, "x"))
        self.current = None
        self.assertIsNone(motion.media_for({"id": "Q-1"}, "x"), "a card that could not be checked is not ready either")
        self.assertIsNone(motion.media_for({"id": "Q-2"}, "x"))

    def test_only_a_motion_file_of_this_repository_is_media(self):
        self.assertEqual(channels.media_path("Content/Motion/Q-1/Q-1-square.mp4"), os.path.realpath(self.files["video"]))
        for bad in ("Content/Motion/Q-1/../../../etc/passwd", "plugins/comms-engine/engine.json", "/etc/hosts",
                    "Content/Motion/Q-1/storyboard.json"):
            self.assertIsNone(channels.media_path(bad), bad)


class Approval(MediaBase):
    def test_the_hash_is_on_each_channels_own_approval(self):
        self.item("Q-1", "A post with a card")
        x = self.channel_act("Q-1:x")["payload"]["media"]
        li = self.channel_act("Q-1:linkedin")["payload"]["media"]
        self.assertEqual((x["kind"], x["sha256"]), ("video", channels.file_sha256(self.files["video"])))
        self.assertEqual((li["kind"], li["sha256"]), ("image", channels.file_sha256(self.files["poster"])))
        self.assertEqual(desk_acts.approved_media("Q-1:x", self.tmp), {"path": x["path"], "sha256": x["sha256"]})

    def test_a_post_without_a_card_is_approved_as_text(self):
        self.item("Q-2", "A post without a card", x="Another line with no link.", linkedin="Another LinkedIn line.")
        self.assertNotIn("media", self.channel_act("Q-2:x")["payload"])
        self.assertIsNone(desk_acts.approved_media("Q-2:x", self.tmp))


class Send(MediaBase):
    def setUp(self):
        super().setUp()
        self.item("Q-1", "A post with a card")
        self.requests = []
        self.drivers = {"x": self.record, "linkedin": self.record}
        p = mock.patch.object(ap, "write_drivers", lambda: self.drivers)
        p.start()
        self.addCleanup(p.stop)

    def record(self, request):
        self.requests.append(request)
        return {"url": f"https://example.test/{request['channel']}", "urn": "urn:li:share:1"}

    def refusals(self):
        return [(ln["id"], ln["check"], ln["reason"]) for ln in channels.sends(self.tmp) if ln["outcome"] == "refused"]

    def test_the_sender_attaches_what_was_approved_and_the_ledger_says_so(self):
        n, _ = self.run_post()
        self.assertEqual(n, 2)
        by = {r["channel"]: r for r in self.requests}
        self.assertEqual((by["x"]["media"]["kind"], by["x"]["media"]["mimetype"]), ("video", "video/mp4"))
        self.assertEqual(by["x"]["media"]["path"], os.path.realpath(self.files["video"]))
        self.assertEqual(by["linkedin"]["media"]["kind"], "image")
        with open(os.path.join(self.tmp, channels.LEDGER_FILE), encoding="utf-8") as f:
            ledger = json.load(f)["sends"]
        self.assertEqual(ledger["Q-1:x"]["media"], channels.file_sha256(self.files["video"]))
        line = next(ln for ln in channels.sends(self.tmp) if ln["id"] == "Q-1:x")
        self.assertEqual(line["media"], channels.file_sha256(self.files["video"])[:16])

    def test_a_file_that_changed_since_the_approval_is_refused_and_the_post_waits(self):
        with open(self.files["video"], "wb") as f:
            f.write(b"another render")
        n, _ = self.run_post()
        self.assertEqual([r["channel"] for r in self.requests], ["linkedin"], "the other channel's media is untouched")
        ((cid, check, why),) = self.refusals()
        self.assertEqual((cid, check), ("Q-1:x", "media"))
        self.assertIn("its hash differs", why)

    def test_a_missing_file_and_a_file_nobody_approved(self):
        os.remove(self.files["poster"])
        self.run_post()
        self.assertIn(("Q-1:linkedin", "media"), [(c, k) for c, k, _ in self.refusals()])
        with self.assertRaises(channels.SendRefused) as cm:
            channels.send(ap.STREAM, "x", "post", X_TEXT, {"id": "Q-1:x", "text_gate": True,
                          "media": {"path": "Content/Motion/Q-1/Q-1-square.gif", "sha256": channels.file_sha256(self.files["gif"])}},
                          driver=self.record, state=self.tmp, at=ap.NOW_DT)
        self.assertEqual(cm.exception.check, "dedupe", "the post already went; nothing is sent twice")

    def test_media_that_was_not_part_of_the_approval_is_refused(self):
        self.item("Q-3", "Approved as text", x="A third line with no link.", linkedin="A third LinkedIn line.")
        ref = {"id": "Q-3:x", "text_gate": True,
               "media": {"path": "Content/Motion/Q-1/Q-1-square.gif", "sha256": channels.file_sha256(self.files["gif"])}}
        with self.assertRaises(channels.SendRefused) as cm:
            channels.send(ap.STREAM, "x", "post", "A third line with no link.", ref, driver=self.record, state=self.tmp, at=ap.NOW_DT)
        self.assertEqual(cm.exception.check, "media")
        self.assertIn("not part of this post's approval", cm.exception.reason)
        for bad in ({"path": "plugins/comms-engine/engine.json", "sha256": "x"}, {"path": "Content/Motion/Q-1/Q-1-square.gif"}):
            with self.assertRaises(channels.SendRefused) as cm:
                channels.send(ap.STREAM, "x", "post", "A third line with no link.", dict(ref, media=bad), driver=self.record,
                              state=self.tmp, at=ap.NOW_DT)
            self.assertEqual(cm.exception.check, "media")
        self.assertEqual(self.requests, [])

    def test_the_native_drivers_refuse_media(self):
        for driver in (ap.native_x_driver, ap.native_linkedin_driver):
            with self.assertRaises(RuntimeError) as cm:
                driver({"kind": "post", "text": "x", "media": {"path": self.files["gif"], "kind": "gif"}})
            self.assertIn("cannot attach media", str(cm.exception))


class Drivers(MediaBase):
    def call(self, driver, channel, which, reply=None):
        kind, mimetype = channels.MEDIA_KINDS[os.path.splitext(self.files[which])[1]]
        request = {"stream": ap.STREAM, "channel": channel, "kind": "post", "text": "A post with a card.", "target": None,
                   "account": channels.account_for(ap.STREAM, channel), "ref": {},
                   "media": {"path": self.files[which], "kind": kind, "mimetype": mimetype, "sha256": "h"}}
        fake = fake_composio_http.install(self, reply=reply or {"data": {"id": "777"}, "successful": True})
        with mock.patch.object(linkedin_api, "settings", return_value={"LINKEDIN_ORG_ID": "555"}):
            out = driver(request)
        return out, fake

    def test_x_stages_the_file_uploads_it_and_posts_with_its_media_id(self):
        out, fake = self.call(channels.x_driver, "x", "video")
        staged = next(c for c in fake.calls if c["path"] == "/api/v3.1/files/upload/request")
        self.assertEqual((staged["body"]["toolkit_slug"], staged["body"]["tool_slug"], staged["body"]["filename"], staged["body"]["mimetype"]),
                         ("twitter", "TWITTER_UPLOAD_LARGE_MEDIA", "Q-1-square.mp4", "video/mp4"))
        ((url, headers, data),) = fake.uploads
        self.assertEqual(data, b"mp4-bytes")
        self.assertNotIn("x-api-key", headers, "the key goes to Composio's API, never to the storage host")
        self.assertEqual(headers["content-type"], "video/mp4")
        (upload, post) = fake.executes
        self.assertEqual(upload[0], "TWITTER_UPLOAD_LARGE_MEDIA")
        self.assertEqual(upload[1]["arguments"]["media_category"], "tweet_video")
        self.assertEqual(upload[1]["arguments"]["media"], {"name": "Q-1-square.mp4", "mimetype": "video/mp4",
                                                           "s3key": "projects/pr_1/requests/twitter/TWITTER_UPLOAD_LARGE_MEDIA/Q-1-square.mp4"})
        self.assertEqual((post[0], post[1]["arguments"]), ("TWITTER_CREATION_OF_A_POST", {"text": "A post with a card.", "media_media_ids": ["777"]}))
        self.assertEqual(out["url"], "https://x.com/i/web/status/777")

    def test_an_image_takes_the_small_upload_and_no_media_id_means_no_post(self):
        _, fake = self.call(channels.x_driver, "x", "poster")
        self.assertEqual(fake.executes[0][0], "TWITTER_UPLOAD_MEDIA")
        self.assertEqual(fake.executes[0][1]["arguments"]["media_category"], "tweet_image")
        with self.assertRaises(channels.ChannelError) as cm:
            self.call(channels.x_driver, "x", "gif", reply={"data": {}, "successful": True})
        self.assertIn("gave no media id", str(cm.exception))

    def test_linkedin_takes_an_image_and_refuses_a_page_video_by_name(self):
        _, fake = self.call(channels.linkedin_driver, "linkedin", "poster")
        (post,) = fake.executes
        self.assertEqual(post[0], "LINKEDIN_CREATE_LINKED_IN_POST")
        self.assertEqual(post[1]["arguments"]["images"][0]["name"], "Q-1-square-poster.png")
        self.assertEqual(len(fake.uploads), 1)
        with self.assertRaises(channels.ChannelError) as cm:
            self.call(channels.linkedin_driver, "linkedin", "video")
        self.assertIn("cannot carry a video", str(cm.exception))


class PaidSkill(unittest.TestCase):
    """claude/hooks/guard_skills.py: motion:generate behind a recorded cost sign-off."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, name, signoff):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            json.dump({"params": {"motion": {"generate_signoff": signoff}}}, f)

    def verdict(self, skill, **tool_input):
        return guard_skills.verdict("Skill", dict({"skill": skill}, **tool_input), engine=self.dir)

    def test_refused_without_a_sign_off_and_open_with_one(self):
        self.write("engine.json", "")
        why, note = self.verdict("motion:generate")
        self.assertIn("no cost sign-off is recorded", why)
        self.assertIn("engine config set motion.generate_signoff", why)
        for off in ("false", "no", "off", "none", "0", "  "):
            self.write("engine.local.json", off)
            self.assertIsNotNone(self.verdict("motion:generate")[0], off)
        self.write("engine.local.json", "2026-11-20: owner, up to 20 USD of generated shots for the launch film")
        why, note = self.verdict("motion:generate")
        self.assertIsNone(why)
        self.assertIn("up to 20 USD", note)
        self.assertEqual(self.verdict("/Motion:Generate a hero shot")[1], note, "however the call spells it")

    def test_a_bare_true_is_not_a_sign_off_and_an_unreadable_file_fails_closed(self):
        with open(os.path.join(self.dir, "engine.json"), "w", encoding="utf-8") as f:
            json.dump({"params": {"motion": {"generate_signoff": True}}}, f)
        self.assertIsNotNone(self.verdict("motion:generate")[0], "a sign-off is a dated note in words")
        with open(os.path.join(self.dir, "engine.json"), "w", encoding="utf-8") as f:
            f.write("{ not json")
        why, _ = self.verdict("motion:generate")
        self.assertIn("could not be read", why)
        self.assertEqual(self.verdict("salon:post-audit"), (None, None), "another skill is not held up by it")

    def test_motion_post_never_opens_and_everything_else_passes(self):
        self.write("engine.json", "2026-11-20: owner, anything")
        self.assertIn("channels.send()", self.verdict("motion:post")[0])
        for skill in ("motion:video", "motion:render", "salon:hook-writing", "claim-gate", ""):
            self.assertEqual(self.verdict(skill), (None, None), skill)
        self.assertEqual(guard_skills.verdict("Bash", {"command": "motion:generate"}, engine=self.dir), (None, None))

    def test_the_shipped_setting_is_closed_and_the_hook_runs_under_the_system_python(self):
        with open(os.path.join(ENGINE, "engine.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["params"]["motion"]["generate_signoff"], "")
        script = os.path.join(ENGINE, "hooks", "guard_skills.py")
        py = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
        local = os.path.join(ENGINE, "engine.local.json")
        signed = False
        if os.path.exists(local):
            with open(local, encoding="utf-8") as f:
                signed = bool(((json.load(f).get("params") or {}).get("motion") or {}).get("generate_signoff"))
        proc = subprocess.run([py, script], input=json.dumps({"tool_name": "Skill", "tool_input": {"skill": "motion:generate"}}),
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0 if signed else 2, proc.stderr)
        proc = subprocess.run([py, script], input=json.dumps({"tool_name": "Skill", "tool_input": {"skill": "salon:hook-writing"}}),
                              capture_output=True, text=True, timeout=30)
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        proc = subprocess.run([py, script], input="not json", capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, "a call the hook cannot read is not a guarded skill call")

    def test_the_plugin_carries_the_hook_and_the_project_enables_it(self):
        with open(os.path.join(REPO, ".claude", "settings.json"), encoding="utf-8") as f:
            settings = json.load(f)
        with open(os.path.join(ENGINE, "hooks", "hooks.json"), encoding="utf-8") as f:
            hooks = json.load(f)["hooks"]
        skill = next(h for h in hooks["PreToolUse"] if h["matcher"] == "Skill")
        self.assertEqual(skill["hooks"][0]["command"], 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/guard_skills.py"')
        self.assertIs(settings["enabledPlugins"].get("comms-engine@comms-engine"), True)
        self.assertIn("Skill(motion:post)", settings["permissions"]["deny"])
        self.assertNotIn("Skill(motion:generate)", settings["permissions"]["deny"])
        self.assertEqual(motion.generate_signoff() == "", not guard_skills.signoff("motion.generate_signoff"))


if __name__ == "__main__":
    unittest.main()
