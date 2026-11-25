"""
The sender (scripts/autopilot.py), on note fixtures.

- X length is weighted (a URL counts 23), the body may not carry a link, and
  editorial voice holds the post
- the due window: today and GRACE_DAYS back post; older is stale; future waits
- the calendar is built from the notes and the lifecycle: Blog, LinkedIn and X per
  item, in the snapshot's shape, and the digest keeps the columns the theme-writer reads
- a dry run posts nothing and writes nothing
- a live run sends each scheduled channel post (`<id>:x`, `<id>:linkedin`) with the
  teaser's text from the note, writes the ledger as `sending` BEFORE the send and
  `sent` after, never flips a note to Published, and never sends an identical text twice
- a refused guardrail (streams.md) stops the send with the rule quoted
- the article link goes in a first reply once a person has marked the article live
- the LinkedIn payloads match the API shape the previous sender used
"""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import autopilot as ap  # noqa: E402
import desk_acts  # noqa: E402
import hermetic_channels  # noqa: E402
import linkedin_api as li  # noqa: E402
import publish  # noqa: E402
import repo  # noqa: E402

sys.path.insert(0, HERE)
import fixture_memory  # noqa: E402

TODAY = dt.date(2026, 11, 5)
X_TEXT = "One sentence, no link. #ExampleTheme"
LI_TEXT = "A LinkedIn teaser with no link."


def ok_guard(item, date):
    return True, ""


class Pure(unittest.TestCase):
    def test_weighted_length_and_problems(self):
        self.assertEqual(ap.x_weighted_length("a " + "https://example.com/" + "x" * 100), 2 + 23)
        self.assertIsNone(ap.teaser_problem("X", "A clean teaser. #ExampleTheme @examplestandards"))
        self.assertIn("exceeds", ap.teaser_problem("X", "y" * 281))
        self.assertIn("link inside", ap.teaser_problem("LinkedIn", "Read it https://www.example.com/insights/x"))
        self.assertIn("editorial voice", ap.teaser_problem("LinkedIn", "This draft argues that the claim gate holds."))
        self.assertEqual(ap.teaser_problem("X", "  "), "empty")

    def test_due_window(self):
        today = TODAY
        self.assertIsNone(ap.due(today, today))
        self.assertIsNone(ap.due(today - dt.timedelta(days=2), today))
        self.assertIn("late", ap.due(today - dt.timedelta(days=3), today))
        self.assertEqual(ap.due(today + dt.timedelta(days=1), today), "future")
        self.assertEqual(ap.due(None, today), "no date")

    def test_digest_columns(self):
        rows = [{"stream": ap.STREAM_NAME, "status": "Ready", "date": "2026-11-06", "platform": "X", "title": "A|B", "body": "First line\nmore", "engine": True},
                {"stream": "Beta", "status": "Ready", "date": "2026-11-06", "platform": "X", "title": "Z", "body": "", "engine": False},
                {"stream": ap.STREAM_NAME, "status": "pause", "date": None, "platform": "Blog", "title": "P", "body": "", "engine": False}]
        lines = ap.digest_lines(rows, now="T")
        self.assertIn("| date | platform | status | by | headline | opening line |", lines)
        self.assertIn("calendar notes", lines[2])
        body = [l for l in lines if l.startswith("| 2026")]
        self.assertEqual(len(body), 1)
        self.assertIn("| engine | A/B | First line |", body[0])

    def test_hash_ignores_whitespace_and_case(self):
        self.assertEqual(ap.text_hash("X", "Hello  world"), ap.text_hash("X", "hello world "))
        self.assertNotEqual(ap.text_hash("X", "a"), ap.text_hash("LinkedIn", "a"))


class Post(fixture_memory.FixtureMemoryCase):
    """A temp vault and state directory; items written by repo.write_item, approved by desk_acts."""

    def setUp(self):
        super().setUp()
        hermetic_channels.install(self)
        self.tmp = tempfile.mkdtemp()
        self.cal = os.path.join(self.tmp, "Content", "Calendar")
        self._saved = {k: getattr(ap, k) for k in ("LEDGER_FILE", "PUBLISH_LOG", "AUTO_STATE", "LOG_FILE", "DRY", "TODAY", "NOW_DT", "guardrail", "post_x", "post_x_reply", "post_linkedin", "post_linkedin_comment", "x_ready", "send_first_reply", "SNAPSHOT_FILE", "MEMORY_DIGEST")}
        self._repo = (repo.CAL, repo.STATE)
        repo.CAL, repo.STATE = self.cal, self.tmp
        ap.LEDGER_FILE = os.path.join(self.tmp, "send-ledger.json")
        ap.PUBLISH_LOG = os.path.join(self.tmp, "publish-log.json")
        ap.AUTO_STATE = os.path.join(self.tmp, "autopilot-state.json")
        ap.LOG_FILE = os.path.join(self.tmp, "autopilot.log")
        ap.SNAPSHOT_FILE = os.path.join(self.tmp, "calendar-snapshot.json")
        ap.MEMORY_DIGEST = os.path.join(self.tmp, "calendar.md")
        ap.LEGACY.clear()
        ap.TODAY = TODAY
        ap.NOW_DT = dt.datetime(2026, 11, 5, 10, 0, tzinfo=dt.timezone.utc)  # a Thursday, inside sending hours
        ap.guardrail = lambda channel: (True, "")
        ap.x_ready = lambda: True
        self.sent = []

        def fake_x(text):
            self.sent.append(("X", text, json.load(open(ap.LEDGER_FILE))))
            return "https://x.com/i/web/status/1"

        def fake_li(text):
            self.sent.append(("LinkedIn", text, json.load(open(ap.LEDGER_FILE))))
            return "https://www.linkedin.com/feed/update/urn:li:share:2", "urn:li:share:2"
        ap.post_x, ap.post_linkedin = fake_x, fake_li
        ap.send_first_reply = lambda platform, ref, link, parent_id=None: "reply-url"
        self._drivers = dict(ap.channels._DRIVERS)
        self.addCleanup(lambda: (ap.channels._DRIVERS.clear(), ap.channels._DRIVERS.update(self._drivers)))
        self.lpath = os.path.join(self.tmp, "lifecycle.jsonl")
        self.apath = os.path.join(self.tmp, "acts.jsonl")
        self.log = {"entries": []}

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(ap, k, v)
        repo.CAL, repo.STATE = self._repo
        super().tearDown()

    def item(self, eid, title, day=TODAY, x=X_TEXT, linkedin=LI_TEXT, post="The article.", stream=None, approve=True,
             verdict="pass"):
        """Write the item's notes and, unless told not to, approve it the way the desk does."""
        item = {"id": eid, "title": title, "theme": "#ExampleTheme", "stream": stream or ap.STREAM_NAME, "post": post,
                "teaser_linkedin": linkedin, "teaser_x": x, "slot": {"date": day.isoformat()}, "slug": repo.slugify(title),
                "gate": {"verdict": verdict}, "drafted_by": "theme-writer", "alpha_status": "proposed"}
        repo.write_item(item, "Idea")
        if approve:
            items = {i["id"]: i for i in repo.load_items()}
            made = desk_acts.turn_into_acts([{"id": eid, "status": "approved", "by": "alpha", "at": f"{eid}-at"}],
                                            [], [], [], items, {}, self.tmp, guard=ok_guard)
            self.assertEqual("applied", made[0]["outcome"], made)
        return item

    def run_post(self, ledger=None):
        ledger = {"sends": {}} if ledger is None else ledger
        return ap.step_post(ledger, self.log), ledger


class Sending(Post):
    def setUp(self):
        super().setUp()
        ap.DRY = False

    def test_dry_run_posts_and_writes_nothing(self):
        self.item("Q-1", "Piece one")
        ap.DRY = True
        before = sorted(os.listdir(self.tmp))
        n, _ = self.run_post()
        self.assertEqual(n, 2)
        self.assertEqual(self.sent, [])
        self.assertEqual(before, sorted(os.listdir(self.tmp)))
        self.assertFalse(os.path.exists(ap.LEDGER_FILE))

    def test_live_run_sends_each_channel_with_the_note_text_ledger_first(self):
        self.item("Q-1", "Piece one")
        n, ledger = self.run_post()
        self.assertEqual(n, 2)
        self.assertEqual({("X", X_TEXT), ("LinkedIn", LI_TEXT)}, {(p, t) for p, t, _ in self.sent})
        for platform, _, ledger_at_send in self.sent:
            states = [s["state"] for s in ledger_at_send["sends"].values() if s["platform"] == platform]
            self.assertIn("sending", states)
        self.assertEqual({"Q-1:x", "Q-1:linkedin"}, set(ledger["sends"]))
        self.assertEqual({s["state"] for s in ledger["sends"].values()}, {"sent"})
        self.assertEqual("sent", ap.lifecycle.state("Q-1:x", self.lpath))
        self.assertEqual("scheduled", ap.lifecycle.state("Q-1", self.lpath), "the item's own line is not a send")
        self.assertEqual(len(self.log["entries"]), 2)
        self.assertTrue(all(e["stream"] == ap.STREAM_NAME for e in self.log["entries"]))
        fm, _ = repo.parse_note(os.path.join(self.cal, "Piece one.md"))
        self.assertEqual("Idea", fm["status"], "no note is flipped to Published")
        before = len(self.sent)
        self.run_post(ledger)
        self.assertEqual(len(self.sent), before, "a second run sends nothing again")

    def test_every_send_is_recorded_by_channels(self):
        self.item("Q-1", "Piece one")
        self.run_post()
        outcomes = {(r["id"], r["kind"], r["outcome"]) for r in ap.channels.sends(self.tmp)}
        self.assertEqual({("Q-1:x", "post", "sent"), ("Q-1:linkedin", "post", "sent")}, outcomes)

    def test_an_unapproved_note_is_not_sent(self):
        self.item("Q-1", "Piece one", approve=False)
        n, ledger = self.run_post()
        self.assertEqual((0, {}), (n, ledger["sends"]))

    def test_identical_text_on_another_item_is_a_duplicate(self):
        self.item("Q-1", "Piece one", linkedin="")
        self.item("Q-2", "Piece two", linkedin="")
        n, ledger = self.run_post()
        self.assertEqual(1, n)
        self.assertEqual(1, sum(1 for p, _, _ in self.sent if p == "X"))
        self.assertNotIn("Q-2:x", ledger["sends"])
        with open(ap.LOG_FILE, encoding="utf-8") as f:
            self.assertIn("duplicate X", f.read())

    def test_guardrail_refusal_stops_the_send(self):
        self.item("Q-1", "Piece one")
        ap.guardrail = lambda channel: (False, f"{ap.STREAM_NAME}: X is drafts-only (streams.md)")
        n, ledger = self.run_post()
        self.assertEqual(n, 0)
        self.assertEqual(self.sent, [])
        self.assertEqual(ledger["sends"], {})
        with open(ap.LOG_FILE, encoding="utf-8") as f:
            self.assertIn("refused X", f.read())

    def test_link_in_body_holds(self):
        self.item("Q-1", "Piece one", x="With a link https://www.example.com/insights/x")
        n, _ = self.run_post()
        self.assertEqual(n, 1)
        self.assertEqual([p for p, _, _ in self.sent], ["LinkedIn"])

    def test_stale_waits_and_future_wait(self):
        self.item("Q-1", "Old piece", day=TODAY - dt.timedelta(days=9))
        self.item("Q-2", "Later piece", day=TODAY + dt.timedelta(days=3), x="Another sentence. #ExampleTheme",
                  linkedin="Another LinkedIn teaser.")
        n, _ = self.run_post()
        self.assertEqual(0, n)
        self.assertEqual("scheduled", ap.lifecycle.state("Q-2:x", self.lpath))
        with open(ap.LOG_FILE, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("stale X", text)
        self.assertNotIn("Later piece", text, "a future post waits without a word")

    def test_another_streams_item_is_never_touched(self):
        self.item("Q-1", "Beta piece", stream=fixture_memory.OTHER_NAME)
        n, ledger = self.run_post()
        self.assertEqual((0, {}), (n, ledger["sends"]))

    def test_a_hold_at_send_leaves_the_post_scheduled(self):
        self.item("Q-1", "Piece one", linkedin="")
        with unittest.mock.patch.object(ap.channels, "hold_reasons", return_value=["an @mention"]):
            n, _ = self.run_post()
        self.assertEqual(0, n)
        self.assertEqual("scheduled", ap.lifecycle.state("Q-1:x", self.lpath))
        self.assertTrue(any(r["outcome"] == "refused" and r["check"] == "hold" for r in ap.channels.sends(self.tmp)))

    def test_a_teaser_edited_after_approval_is_refused_until_approved_again(self):
        item = self.item("Q-1", "Piece one", linkedin="")
        repo.write_item(dict(item, teaser_x="A different sentence entirely. #ExampleTheme"), "Idea")
        n, _ = self.run_post()
        self.assertEqual(0, n)
        line = [r for r in ap.channels.sends(self.tmp) if r["id"] == "Q-1:x"][-1]
        self.assertEqual(("refused", "kind rule"), (line["outcome"], line["check"]))
        self.assertEqual("scheduled", ap.lifecycle.state("Q-1:x", self.lpath))

    def test_a_dry_run_shows_a_refusal_the_live_run_would_make(self):
        self.item("Q-1", "Piece one", linkedin="")
        ap.DRY = True
        with unittest.mock.patch.object(ap.channels, "hold_reasons", return_value=["held"]):
            n, _ = self.run_post()
        self.assertEqual(0, n)


class Links(Post):
    """The article link goes out once a person has marked the article live (the blog-live act)."""

    def setUp(self):
        super().setUp()
        ap.DRY = False

    def live(self, eid):
        items = {i["id"]: i for i in repo.load_items()}
        got = desk_acts.blog_live(eid, "alpha", items, self.tmp, webhook=lambda: "skipped: test")
        self.assertEqual("applied", got["outcome"], got)
        return got["url"]

    def test_no_link_before_the_article_is_live(self):
        item = self.item("Q-1", "Piece one", linkedin="")
        self.assertIsNone(ap.article_link_for(item, self.tmp))
        _, ledger = self.run_post()
        self.assertEqual(0, ap.step_links(ledger))

    def test_links_step_adds_first_reply_once_the_article_is_live(self):
        self.item("Q-1", "Piece one", linkedin="")
        _, ledger = self.run_post()
        url = self.live("Q-1")
        self.assertEqual(url, repo.post_url("piece-one"))
        self.assertEqual(1, ap.step_links(ledger))
        self.assertEqual(ledger["sends"]["Q-1:x"]["link_reply"]["link"], url)
        self.assertEqual(0, ap.step_links(ledger))

    def test_the_link_reply_passes_channels_send_on_the_live_act(self):
        self.item("Q-1", "Piece one", linkedin="")
        _, ledger = self.run_post()
        url = self.live("Q-1")
        ap.send_first_reply = self._saved["send_first_reply"]
        ap.post_x_reply = lambda post_url, text: self.sent.append(("X reply", text, None)) or "https://x.com/i/web/status/2"
        self.assertEqual(1, ap.step_links(ledger))
        line = [r for r in ap.channels.sends(self.tmp) if r["kind"] == "link-reply"][-1]
        self.assertEqual(("sent", "Q-1:x#link"), (line["outcome"], line["id"]))
        self.assertEqual(("X reply", f"{ap.channels.LINK_CAPTIONS['x']} {url}"), self.sent[-1][:2])

    def test_a_post_sent_after_the_article_is_live_gets_its_first_reply_at_once(self):
        self.item("Q-1", "Piece one", linkedin="")
        self.live("Q-1")
        replies = []
        ap.send_first_reply = lambda platform, ref, link, parent_id=None: replies.append((platform, parent_id, link)) or "r"
        self.run_post()
        self.assertEqual([("X", "Q-1:x", repo.post_url("piece-one"))], replies)


class Calendar(Post):
    """The calendar is the notes plus the lifecycle; the snapshot keeps its row shape."""

    def test_three_rows_per_item_in_the_snapshot_shape(self):
        self.item("Q-1", "Piece one", approve=False)
        rows = ap.calendar_rows(state=self.tmp)
        self.assertEqual(["Blog", "LinkedIn", "X"], [r["platform"] for r in rows])
        self.assertEqual({"Q-1:blog", "Q-1:linkedin", "Q-1:x"}, {r["page_id"] for r in rows})
        for r in rows:
            for key in ("page_id", "title", "platform", "status", "stream", "pillar", "date", "slug", "engine", "body"):
                self.assertIn(key, r)
        self.assertEqual({"Idea"}, {r["status"] for r in rows})
        self.assertEqual({"piece-one", "piece-one-linkedin", "piece-one-x"}, {r["slug"] for r in rows})
        self.assertEqual(X_TEXT, next(r for r in rows if r["platform"] == "X")["body"])

    def test_status_follows_the_lifecycle_the_ledger_and_the_live_act(self):
        ap.DRY = False
        self.item("Q-1", "Piece one")
        rows = {r["platform"]: r for r in ap.calendar_rows(state=self.tmp)}
        self.assertEqual(("Scheduled", "Scheduled"), (rows["X"]["status"], rows["LinkedIn"]["status"]))
        self.run_post()
        items = {i["id"]: i for i in repo.load_items()}
        desk_acts.blog_live("Q-1", "alpha", items, self.tmp, webhook=lambda: "skipped")
        rows = {r["platform"]: r for r in ap.calendar_rows(state=self.tmp)}
        self.assertEqual({"Published"}, {r["status"] for r in rows.values()})
        self.assertEqual("https://x.com/i/web/status/1", rows["X"]["url"])
        self.assertEqual(repo.post_url("piece-one"), rows["Blog"]["url"])

    def test_a_superseded_item_is_paused_and_a_far_row_has_no_body(self):
        self.item("Q-1", "Piece one", day=TODAY + dt.timedelta(days=60), approve=False)
        repo.set_fields("Q-1", {"alpha_status": repo.SUPERSEDED})
        rows = ap.calendar_rows(state=self.tmp)
        self.assertEqual({"pause"}, {r["status"] for r in rows})
        self.assertEqual({""}, {r["body"] for r in rows})

    def test_snapshot_writes_the_rows_and_the_digest_and_publish_reads_them(self):
        ap.DRY = False
        item = self.item("Q-1", "Piece one", linkedin="")
        self.run_post()
        self.assertEqual(3 - 1, ap.step_snapshot())
        with open(ap.SNAPSHOT_FILE, encoding="utf-8") as f:
            snap = json.load(f)
        self.assertEqual("notes", snap["source"])
        with open(ap.MEMORY_DIGEST, encoding="utf-8") as f:
            digest = f.read()
        self.assertIn("| X | Published | engine | Piece one |", digest)
        self.assertEqual("X", publish.already_published(item, ap.SNAPSHOT_FILE)["platform"])


class WriteDriver(Post):
    """The sender's write driver is a setting, `native` unless set, and either way it is registered into channels.send()."""

    def setUp(self):
        super().setUp()
        ap.DRY = False

    def test_the_default_is_native(self):
        self.assertEqual(("native", None), ap.channels.write_driver(ap.STREAM))
        drivers = ap.write_drivers()
        self.assertIs(ap.native_x_driver, drivers["x"])
        self.assertIs(ap.native_linkedin_driver, drivers["linkedin"])
        self.assertIs(ap.native_x_driver, ap.channels._DRIVERS["x"])

    def test_composio_is_selected_by_the_one_setting(self):
        with unittest.mock.patch.object(ap.channels, "write_driver", return_value=("composio", None)):
            drivers = ap.write_drivers()
        self.assertIs(ap.channels.x_driver, drivers["x"])
        self.assertIs(ap.channels.linkedin_driver, drivers["linkedin"])

    def test_an_unknown_value_falls_back_to_native(self):
        with unittest.mock.patch.object(ap.channels, "write_driver", return_value=("compsio", "unknown driver")):
            drivers = ap.write_drivers()
        self.assertIs(ap.native_x_driver, drivers["x"])

    def test_a_dry_run_gets_the_driver_that_sends_nothing(self):
        ap.DRY = True
        with unittest.mock.patch.object(ap.channels, "write_driver", return_value=("composio", None)):
            drivers = ap.write_drivers()
        self.assertEqual({"x": ap.dry_driver, "linkedin": ap.dry_driver}, drivers)

    def test_the_native_drivers_wrap_the_existing_senders(self):
        calls = []
        ap.post_x = lambda text: calls.append(("post_x", text)) or "https://x.com/i/web/status/5"
        ap.post_x_reply = lambda url, text: calls.append(("reply", url, text)) or "https://x.com/i/web/status/6"
        ap.post_linkedin_comment = lambda urn, text: calls.append(("comment", urn, text)) or "urn:li:comment:7"
        self.assertEqual({"url": "https://x.com/i/web/status/5"}, ap.native_x_driver({"kind": "post", "text": "t"}))
        self.assertEqual({"url": "https://x.com/i/web/status/6"},
                         ap.native_x_driver({"kind": "link-reply", "text": "r", "target": "https://x.com/i/web/status/5"}))
        self.assertEqual({"url": "", "urn": "urn:li:comment:7"},
                         ap.native_linkedin_driver({"kind": "comment", "text": "c", "target": "urn:li:share:2"}))
        self.assertEqual([("post_x", "t"), ("reply", "https://x.com/i/web/status/5", "r"), ("comment", "urn:li:share:2", "c")], calls)


class LinkedInPayloads(unittest.TestCase):
    def test_post_payload_shape(self):
        p = li.build_post_payload(author="urn:li:organization:106602494", text="Hello")
        self.assertEqual(p["author"], "urn:li:organization:106602494")
        self.assertEqual(p["lifecycleState"], "PUBLISHED")
        self.assertEqual(p["distribution"]["feedDistribution"], "MAIN_FEED")
        self.assertNotIn("content", p)
        with_article = li.build_post_payload(author="a", text="t", article_url="https://www.example.com/insights/x", article_title="T")
        self.assertEqual(with_article["content"]["article"]["source"], "https://www.example.com/insights/x")
        with self.assertRaises(li.LinkedInError):
            li.build_post_payload(author="a", text="")
        with self.assertRaises(li.LinkedInError):
            li.build_post_payload(author="a", text="x" * 3001)

    def test_comment_payload_and_urns(self):
        self.assertEqual(li.build_comment_payload(actor="urn:li:organization:1", text="hi"), {"actor": "urn:li:organization:1", "message": {"text": "hi"}})
        self.assertEqual(li.author_urn({"LINKEDIN_ORG_ID": "106602494"}), "urn:li:organization:106602494")
        with self.assertRaises(li.LinkedInError):
            li.author_urn({})
        self.assertEqual(li.post_url("urn:li:share:7"), "https://www.linkedin.com/feed/update/urn:li:share:7")

    def test_failure_text_and_headers(self):
        self.assertIn("token rejected", li._describe_failure(401, json.dumps({"message": "bad"})))
        self.assertIn("Community Management", li._describe_failure(403, "{}"))
        h = li._headers({}, "tok")
        self.assertEqual(h["LinkedIn-Version"], li.DEFAULT_API_VERSION)
        self.assertNotIn("LinkedIn-Version", li._headers({}, "tok", versioned=False))

    def test_token_state(self):
        now = 1_000_000
        s = li.token_state({"LINKEDIN_ACCESS_TOKEN": "t", "LINKEDIN_TOKEN_EXPIRES_AT": str(now + 10 * 86400)}, now=now)
        self.assertTrue(s["authorized"]) and self.assertFalse(s["needs_refresh"])
        s = li.token_state({"LINKEDIN_ACCESS_TOKEN": "t", "LINKEDIN_TOKEN_EXPIRES_AT": str(now + 3600), "LINKEDIN_REFRESH_TOKEN": "r"}, now=now)
        self.assertTrue(s["needs_refresh"]) and self.assertTrue(s["has_refresh_token"])
        self.assertFalse(li.token_state({}, now=now)["authorized"])


if __name__ == "__main__":
    unittest.main()
