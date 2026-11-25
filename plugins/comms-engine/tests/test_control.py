#!/usr/bin/env python3
"""
`scripts/control.py`, the local control page, `scripts/held_theme.py`, the one
writer of a person's new theme, and the `@watched` pass the page feeds in
`scripts/listen.py`. The views the page reads are tested in `test_views.py`.

1. **What it may change, and how it refuses.** A theme's X query and keywords
   are written to `themes.json` with a dated `_term_log` line; an unknown
   theme, a query past X's 255 characters, no change at all, or a file that
   moved since the page read it are refused. The watchlist takes a valid
   handle once, never one `handles.md` already monitors, at most 30, and
   dismissals stop a suggestion coming back.
2. **A new theme.** Held in both of `themes.md`'s tables with a status-log
   line, and listened for in `themes.json`; refused when it is a theme already,
   not a hashtag, excluded, on the denylist or past X's limit; both files put
   back when the roster does not read back.
3. **Local only.** A Host that is not 127.0.0.1 or localhost, a cross-site
   Origin, or a change without the page's token is refused, through the
   running server as well as the function.
4. **The listener.** Watched accounts become `from:` searches of at most 255
   characters each.

Every file here is a temp file; nothing reads live state.

  python3 -m unittest discover plugins/comms-engine/tests
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))

import control  # noqa: E402
import held_theme  # noqa: E402
import listen  # noqa: E402
import views  # noqa: E402


class Temp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def path(self, name):
        return os.path.join(self.dir, name)


class Terms(Temp):
    def setUp(self):
        super().setUp()
        self.file = self.path("themes.json")
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump({"_about": "x", "search_terms": {"#ExampleTheme": {"x_search": "old query", "linkedin_search": "li",
                                                                         "keywords": ["old"]}},
                       "mentions": {"x_search": "m"}, "_term_log": []}, f, indent=2)
            f.write("\n")

    def write(self, **kw):
        args = dict(tag="#ExampleTheme", x_search="new query lang:en", keywords="Alpha, beta,alpha",
                    base=control.digest(self.file), path=self.file, today="2026-11-06")
        args.update(kw)
        return control.write_terms(**args)

    def test_a_change_is_written_and_logged(self):
        new_base = self.write()
        doc = json.load(open(self.file, encoding="utf-8"))
        self.assertEqual(doc["search_terms"]["#ExampleTheme"]["x_search"], "new query lang:en")
        self.assertEqual(doc["search_terms"]["#ExampleTheme"]["keywords"], ["alpha", "beta"])
        self.assertEqual(doc["search_terms"]["#ExampleTheme"]["linkedin_search"], "li", "the rest of the entry stays")
        self.assertTrue(doc["_term_log"][-1].startswith("2026-11-06 - #ExampleTheme: changed on the control page"))
        self.assertIn("X search was: old query", doc["_term_log"][-1])
        self.assertEqual(new_base, control.digest(self.file))
        self.assertTrue(open(self.file, encoding="utf-8").read().startswith('{\n  "_about"'), "indent 2 is kept")

    def test_a_moved_file_is_never_clobbered(self):
        with self.assertRaises(control.Conflict):
            self.write(base="stale")

    def test_refusals(self):
        with self.assertRaises(control.Refused):
            self.write(tag="#NotATheme")
        with self.assertRaises(control.Refused):
            self.write(x_search="x" * 256)
        with self.assertRaises(control.Refused):
            self.write(x_search="old query", keywords=["old"])
        with self.assertRaises(control.Refused):
            self.write(keywords="")


THEMES_MD = """# themes - the hashtags where this stream leads

| hashtag | what it is | why it is different | fact it links back to | partner tags | intro post |
|---|---|---|---|---|---|
| #ExampleTheme | An example. | Ours. | C-acme-1 | — | not yet |
|  |  |  |  |  |  |

## licence and layer

| hashtag | layer | licence | logics | licence basis |
|---|---|---|---|---|
| #ExampleTheme | core services | licensed | L1 | shipped |
|  |  |  |  |  |

## excluded from listening

`#OtherNarrative` belongs to another stream.

## theme status log

- 2026-09-07 - seeded.
"""


class ThemesFiles(Temp):
    """A themes.md and themes.json of their own, and a denylist of one name."""
    def setUp(self):
        super().setUp()
        self.md, self.json = self.path("themes.md"), self.path("themes.json")
        with open(self.md, "w", encoding="utf-8") as f:
            f.write(THEMES_MD)
        with open(self.json, "w", encoding="utf-8") as f:
            json.dump({"search_terms": {"#ExampleTheme": {"x_search": "q", "linkedin_search": "", "keywords": ["k"]}},
                       "_term_log": []}, f, indent=2)
        for p in (mock.patch.object(control.memory, "THEMES_MD", self.md),
                  mock.patch.object(control.memory, "denylist", lambda stream=None: ["Umbra Capital"])):
            p.start()
            self.addCleanup(p.stop)


class AddTheme(ThemesFiles):
    def add(self, **kw):
        args = dict(tag="#NewTheme", what="A new idea we want to lead.", different="We say it first.",
                    x_search='("new idea") lang:en -filter:replies', keywords="new idea, lead",
                    md_base=control.digest(self.md), terms_base=control.digest(self.json),
                    today="2026-11-06", terms=self.json)
        args.update(kw)
        return control.add_theme(**args)

    def test_a_new_theme_is_held_in_both_tables_and_listened_for(self):
        self.add()
        themes = {t["tag"]: t for t in control.memory.load_themes()}
        self.assertEqual(themes["#NewTheme"]["licence"], "held", "a new theme starts at the lowest grade")
        self.assertEqual(themes["#NewTheme"]["what"], "A new idea we want to lead.")
        terms = json.load(open(self.json, encoding="utf-8"))
        self.assertEqual(terms["search_terms"]["#NewTheme"]["keywords"], ["new idea", "lead"])
        self.assertIn("#NewTheme: added on the control page", terms["_term_log"][-1])
        md = open(self.md, encoding="utf-8").read()
        self.assertIn("- 2026-11-06 — #NewTheme added on the control page as held", md)
        self.assertLess(md.index("| #NewTheme | A new idea"), md.index("|  |  |  |  |  |  |"),
                        "the row goes after the last filled row, above a template's empty ones")

    def test_refusals(self):
        for kw, why in ((dict(tag="#ExampleTheme"), "already"), (dict(tag="no spaces"), "hashtag"),
                        (dict(what="a | b"), "|"), (dict(tag="#OtherNarrative"), "excluded"),
                        (dict(tag="#UmbraCapital"), "denylist"), (dict(x_search="x" * 256), "255"),
                        (dict(what=""), "needed")):
            with self.subTest(why=why):
                with self.assertRaises(control.Refused) as e:
                    self.add(**kw)
                self.assertIn(why, str(e.exception))
        with self.assertRaises(control.Conflict):
            self.add(md_base="stale")

    def test_a_write_that_does_not_read_back_is_undone(self):
        before_md, before_json = open(self.md).read(), open(self.json).read()
        real = control.memory.load_themes
        calls = []

        def flaky(stream=None):
            calls.append(1)
            return real() if len(calls) == 1 else []
        with mock.patch.object(control.memory, "load_themes", flaky):
            with self.assertRaises(control.Refused):
                self.add()
        self.assertEqual(open(self.md).read(), before_md)
        self.assertEqual(open(self.json).read(), before_json)


class HeldTheme(ThemesFiles):
    def test_prepare_writes_nothing_and_write_refuses_a_moved_file(self):
        before = open(self.md, encoding="utf-8").read()
        tag, old, new = held_theme.prepare("NewTheme", "A new idea.", "", "2026-11-07", where="a test")
        self.assertEqual(tag, "#NewTheme", "a bare word gets its #")
        self.assertEqual(open(self.md, encoding="utf-8").read(), before, "prepare only checks")
        self.assertIn("Added on a test on 2026-11-07. Held", new)
        with open(self.md, "a", encoding="utf-8") as f:
            f.write("\n- 2026-11-07 - a person's edit in between.\n")
        with self.assertRaises(held_theme.Refused):
            held_theme.write(old, new, tag)
        self.assertNotIn("#NewTheme", open(self.md, encoding="utf-8").read())

    def test_extra_taken_tags_are_themes_already(self):
        with self.assertRaises(held_theme.Refused) as e:
            held_theme.prepare("#Listened", "x", also_taken={"#listened": {}})
        self.assertIn("already", str(e.exception))


class Grade(ThemesFiles):
    """A person allows a theme, or holds it again, with the reason that lets them."""
    def grade(self, **kw):
        args = dict(tag="#ExampleTheme", licence="held", basis="The layer beneath has not shipped; argue the principle only.",
                    md_base=control.digest(self.md), today="2026-11-07")
        args.update(kw)
        return control.grade_theme(**args)

    def test_a_grade_is_written_read_back_and_logged_with_what_it_replaced(self):
        self.grade()
        self.assertEqual({t["tag"]: t["licence"] for t in control.memory.load_themes()}["#ExampleTheme"], "held")
        md = open(self.md, encoding="utf-8").read()
        self.assertIn("(Graded held on the control page on 2026-11-07; it was licensed.)", md)
        self.assertIn("- 2026-11-07 — #ExampleTheme: licence licensed → held, by a person on the control page.", md)
        self.assertIn("Basis before: shipped", md, "the reason it replaced is kept in the log")
        self.grade(licence="licensed-with-hedge", basis='Only with "is in the process of", per status.md section 1.')
        self.assertEqual({t["tag"]: t["licence"] for t in control.memory.load_themes()}["#ExampleTheme"], "licensed-with-hedge")
        self.assertEqual(open(self.md, encoding="utf-8").read().count("by a person on the control page"), 2)

    def test_refusals(self):
        for kw, why in ((dict(licence="licensed"), "already"), (dict(licence="open"), "a grade is one of"),
                        (dict(basis="ok"), "a few words"), (dict(basis="a | b in the cell breaks it"), "|"),
                        (dict(tag="#NotATheme"), "not a theme"),
                        (dict(licence="licensed-with-hedge", basis="careful wording without its words"), "quotes")):
            with self.subTest(why=why):
                with self.assertRaises(control.Refused) as e:
                    self.grade(**kw)
                self.assertIn(why, str(e.exception))
        with self.assertRaises(control.Conflict):
            self.grade(md_base="stale")
        self.assertEqual(open(self.md, encoding="utf-8").read(), THEMES_MD, "nothing written by a refusal")

    def test_a_grade_that_does_not_read_back_is_undone(self):
        real = control.memory.load_themes
        with mock.patch.object(control.memory, "load_themes", lambda stream=None: [dict(t, licence="licensed") for t in real()]):
            with self.assertRaises(control.Refused):
                self.grade()
        self.assertEqual(open(self.md, encoding="utf-8").read(), THEMES_MD)


class Watchlist(Temp):
    def setUp(self):
        super().setUp()
        self.file = self.path("watchlist.json")
        p = mock.patch.object(views, "known_handles", lambda: {"standardsorg"})
        p.start()
        self.addCleanup(p.stop)

    def base(self):
        return control.digest(self.file)

    def test_watch_unwatch_and_dismiss(self):
        control.watch("@SomeBank", self.base(), ["#ExampleTheme"], "covers tokenised deposits", "suggestion",
                      path=self.file, today="2026-11-06")
        wl = views.watchlist(self.file)
        self.assertEqual(wl["watched"][0]["handle"], "@somebank")
        self.assertEqual(wl["watched"][0]["themes"], ["#ExampleTheme"])
        with self.assertRaises(control.Refused):
            control.watch("somebank", self.base(), path=self.file)
        control.unwatch("@SomeBank", self.base(), path=self.file)
        self.assertEqual(views.watchlist(self.file)["watched"], [])
        control.dismiss("@noise", self.base(), path=self.file, today="2026-11-06")
        self.assertEqual(views.watchlist(self.file)["dismissed"][0]["handle"], "@noise")
        control.undismiss("@noise", self.base(), path=self.file)
        self.assertEqual(views.watchlist(self.file)["dismissed"], [])
        with self.assertRaises(control.Refused):
            control.undismiss("@noise", self.base(), path=self.file)
        control.dismiss("@noise", self.base(), path=self.file)
        control.watch("@noise", self.base(), path=self.file)
        self.assertEqual(views.watchlist(self.file)["dismissed"], [], "watching lifts a dismissal")

    def test_refusals(self):
        with self.assertRaises(control.Refused):
            control.watch("not a handle!", self.base(), path=self.file)
        with self.assertRaises(control.Refused):
            control.watch("@StandardsOrg", self.base(), path=self.file)
        with self.assertRaises(control.Conflict):
            control.watch("@fine", "stale", path=self.file)
        with self.assertRaises(control.Refused):
            control.unwatch("@nobody", self.base(), path=self.file)
        for n in range(control.WATCH_MAX):
            control.watch(f"@acct{n}", self.base(), path=self.file)
        with self.assertRaises(control.Refused):
            control.watch("@onemore", self.base(), path=self.file)


class LocalOnly(unittest.TestCase):
    def test_host_origin_and_token(self):
        ok = {"Host": "127.0.0.1:4320"}
        self.assertIsNone(control.allowed(ok, 4320, "t", "GET"))
        self.assertIsNone(control.allowed({"Host": "localhost:4320"}, 4320, "t", "GET"))
        self.assertIsNotNone(control.allowed({"Host": "evil.example:4320"}, 4320, "t", "GET"), "a rebound host")
        self.assertIsNotNone(control.allowed(dict(ok, Origin="https://evil.example"), 4320, "t", "GET"))
        self.assertIsNotNone(control.allowed(ok, 4320, "t", "POST"), "a change without the token")
        self.assertIsNotNone(control.allowed(dict(ok, **{"X-Control-Token": "wrong"}), 4320, "t", "POST"))
        self.assertIsNone(control.allowed(dict(ok, **{"X-Control-Token": "t"}), 4320, "t", "POST"))


class Approve(Temp):
    """The posts view's approve: a decision act and a lifecycle move to `scheduled`; never a send."""

    def setUp(self):
        super().setUp()
        import desk_acts
        self.desk_acts = desk_acts
        self.item = {"id": "Q-1", "title": "A post", "stream": "Testco", "theme": "#T", "post": "Body.", "gate": {"verdict": "pass"},
                     "slot": {"date": "2026-09-09", "platform": "Blog"}}
        p = mock.patch("gate_lint.items_by_id", lambda: {"Q-1": self.item})
        p.start()
        self.addCleanup(p.stop)
        s = mock.patch.object(control, "STATE", self.dir)
        s.start()
        self.addCleanup(s.stop)
        v = mock.patch.object(views, "STATE", self.dir)
        v.start()
        self.addCleanup(v.stop)
        self.confirmed = mock.patch.dict(os.environ, {"DESK_DB": os.path.join(self.dir, "desk.db")})
        self.confirmed.start()
        self.addCleanup(self.confirmed.stop)
        control.confirm_argument("Q-1", "alpha")

    def approve(self, **kw):
        kw.setdefault("reason", "the claim is on the register")
        return control.approve_post("Q-1", "alpha", **kw)

    def test_approve_schedules_and_the_posts_view_shows_it(self):
        got = self.approve(guard=lambda item, date: (True, ""))
        self.assertEqual((got["outcome"], got["state"], got["date"]), ("applied", "scheduled", "2026-09-09"))
        act = views.post_acts()["Q-1"]
        self.assertEqual((act["outcome"], act["state"], act["source"], act["by"]), ("applied", "scheduled", "dashboard", "alpha"))

    def test_a_refusal_comes_back_with_its_reason(self):
        got = self.approve(guard=lambda item, date: (False, "quiet hours"))
        self.assertEqual(got["outcome"], "refused: guardrails: quiet hours")
        act = views.post_acts()["Q-1"]
        self.assertEqual((act["outcome"], act["state"]), ("refused: guardrails: quiet hours", None))

    def test_block_refuses_and_pass_with_edits_is_allowed(self):
        self.item["gate"] = {"verdict": "block"}
        self.assertIn("block", self.approve(guard=lambda i, d: (True, ""))["outcome"])
        self.item["gate"] = {"verdict": "pass-with-edits"}
        self.assertEqual(self.approve(guard=lambda i, d: (True, ""))["outcome"], "applied")

    def test_blog_live_after_approve_records_the_act_and_fires_the_webhook(self):
        got = control.blog_live("Q-1", "alpha", webhook=lambda: "skipped: no hook")
        self.assertTrue(got["outcome"].startswith("refused: the item is not approved"))
        self.approve(guard=lambda item, date: (True, ""))
        got = control.blog_live("Q-1", "Some Person", webhook=lambda: "sent 204")
        self.assertEqual((got["outcome"], got["webhook"]), ("applied", "sent 204"))
        self.assertTrue(got["url"].startswith("https://"))
        with self.assertRaises(control.Refused):
            control.blog_live("nope", "alpha")

    def test_unknown_post_and_empty_id_are_refused(self):
        with self.assertRaises(control.Refused):
            control.approve_post("nope", "alpha")
        with self.assertRaises(control.Refused):
            control.approve_post("", "alpha")


class Server(unittest.TestCase):
    def setUp(self):
        import http.server
        self.token = "test-token"
        stub = mock.patch.object(views, "snapshot", lambda: {"stream": "Acme", "errors": []})
        stub.start()
        self.addCleanup(stub.stop)
        self.watch = mock.patch.object(control, "watch", return_value="newbase")
        self.watched = self.watch.start()
        self.addCleanup(self.watch.stop)
        # Bind first to learn the free port, then hand the server the handler for that port.
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), control.make_handler(0, self.token))
        self.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = control.make_handler(self.port, self.token)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def call(self, path, body=None, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=None if body is None else json.dumps(body).encode(),
                                     headers=headers or {}, method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def test_the_page_carries_its_token_and_the_state_reads(self):
        code, html = self.call("/")
        self.assertEqual(code, 200)
        self.assertIn(self.token, html)
        self.assertNotIn("__CONTROL_TOKEN__", html)
        code, body = self.call("/api/state")
        self.assertEqual(json.loads(body)["stream"], "Acme")

    def test_approve_needs_the_token_and_the_host_and_answers_with_the_outcome(self):
        with mock.patch.object(control, "approve_post", return_value={"outcome": "refused: guardrails: quiet hours"}) as ap:
            code, _ = self.call("/api/approve", {"id": "Q-1"})
            self.assertEqual(code, 403)
            code, _ = self.call("/api/approve", {"id": "Q-1"}, {"X-Control-Token": self.token, "Origin": "https://evil.example"})
            self.assertEqual(code, 403)
            ap.assert_not_called()
            code, body = self.call("/api/approve", {"id": "Q-1", "by": "alpha", "reason": "why", "scope": "standing"},
                                  {"X-Control-Token": self.token})
            self.assertEqual(code, 200, body)
            self.assertEqual(json.loads(body)["act"]["outcome"], "refused: guardrails: quiet hours")
            ap.assert_called_once_with("Q-1", "alpha", reason="why", scope="standing")
        code, body = self.call("/api/approve", {"id": ""}, {"X-Control-Token": self.token})
        self.assertEqual(code, 400)

    def test_the_published_feed_is_a_read_with_no_token(self):
        feed = {"as_of": "2026-11-12", "posts": [{"id": "Q-1", "url": "https://www.example.com/insights/q"}]}
        with mock.patch.object(views, "published_posts", return_value=feed):
            code, body = self.call("/api/published")
            self.assertEqual((200, feed), (code, json.loads(body)))
            code, _ = self.call("/api/published", {}, {"X-Control-Token": self.token})
            self.assertEqual(404, code, "the feed is read-only")

    def test_a_change_needs_the_token(self):
        code, _ = self.call("/api/watch", {"handle": "@x", "base": ""})
        self.assertEqual(code, 403)
        self.watched.assert_not_called()
        code, body = self.call("/api/watch", {"handle": "@x", "base": ""}, {"X-Control-Token": self.token})
        self.assertEqual(code, 200, body)
        self.assertTrue(json.loads(body)["ok"])

    def test_the_app_is_served_with_its_token_and_the_first_page_stays_at_classic(self):
        ui = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, ui, True)
        os.makedirs(os.path.join(ui, "assets"))
        with open(os.path.join(ui, "index.html"), "w", encoding="utf-8") as f:
            f.write('<meta name="control-token" content="__CONTROL_TOKEN__"><div id="root"></div>')
        with open(os.path.join(ui, "assets", "index-abc.js"), "w", encoding="utf-8") as f:
            f.write("console.log(1)")
        with mock.patch.object(control, "UI", ui):
            code, html = self.call("/")
            self.assertEqual(code, 200)
            self.assertIn(f'content="{self.token}"', html)
            self.assertIn('id="root"', html, "the app, not the first page")
            code, html = self.call("/classic")
            self.assertNotIn('id="root"', html, "the first page, kept until the app matches it")
            self.assertEqual(self.call("/assets/index-abc.js")[0], 200)
            for bad in ("/assets/..%2findex.html", "/assets/../../engine.json", "/assets/missing.js", "/assets/notes.txt"):
                self.assertEqual(self.call(bad)[0], 404, bad)
        with mock.patch.object(control, "UI", os.path.join(ui, "none")):
            self.assertIn(self.token, self.call("/")[1], "no build: the first page answers")

    def test_media_is_only_motion_files(self):
        code, _ = self.call("/media/plugins/comms-engine/engine.json")
        self.assertEqual(code, 404)
        code, _ = self.call("/media/Content/Motion/../../.atelier/memory/handles.private.md")
        self.assertEqual(code, 404)
        code, _ = self.call("/media/videos/projects/Q-1/index.html")
        self.assertEqual(code, 404, "a film's project is not media; only its renders in videos/finals")
        code, _ = self.call("/media/videos/finals/../../.atelier/memory/handles.private.md")
        self.assertEqual(code, 404)


class WatchedPass(Temp):
    def write(self, handles):
        path = self.path("watchlist.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"watched": [{"handle": h} for h in handles]}, f)
        return path

    def test_from_searches_within_the_limit(self):
        handles = [f"@account_{n:02d}" for n in range(25)] + ["@Account_00", "not valid!"]
        passes = listen.watched_passes(self.write(handles))
        self.assertGreater(len(passes), 1)
        self.assertTrue(all(len(p["query"]) <= 255 for p in passes))
        self.assertTrue(all(p["tag"] == "@watched" and p["source"] == "x" for p in passes))
        joined = " ".join(p["query"] for p in passes)
        self.assertEqual(joined.count("from:"), 25, "duplicates and invalid handles are dropped")

    def test_nothing_watched_is_no_pass(self):
        self.assertEqual(listen.watched_passes(self.write([])), [])
        self.assertEqual(listen.watched_passes(self.path("missing.json")), [])


SERVE = "mac.tail1234.ts.net"
ROLES = {"Owner@Example.com": "alpha", "editor@example.com": "team", "odd@example.com": "admin"}


class TheDoor(unittest.TestCase):
    """H4: on a hosted Mac the page answers its Tailscale Serve name too, and only for a signed-in
    tailnet login that engine.local.json maps to a role; that role is the act's `by`."""

    def door(self, headers, method="GET", serve=SERVE, roles=ROLES):
        return control.door(headers, 4320, "t", method, serve, roles)

    def test_a_mapped_identity_is_its_role(self):
        h = {"Host": SERVE, control.LOGIN_HEADER: "owner@example.com"}
        self.assertEqual(self.door(h), (None, "alpha"), "the login is matched without regard to case")
        self.assertEqual(self.door(dict(h, **{"X-Control-Token": "t", "Origin": f"https://{SERVE}"}), "POST"), (None, "alpha"))
        self.assertEqual(self.door({"Host": f"{SERVE}:443", control.LOGIN_HEADER: "editor@example.com"}), (None, "team"))
        why, role = self.door(h, "POST")
        self.assertIn("token", why, "the token check stays")
        self.assertIsNone(role)

    def test_an_unmapped_identity_is_refused_and_never_repeated(self):
        for login in ("stranger@example.com", "odd@example.com"):
            why, role = self.door({"Host": SERVE, control.LOGIN_HEADER: login})
            self.assertIn("not mapped to a role", why, login)
            self.assertNotIn(login, why)
            self.assertIsNone(role)

    def test_a_missing_identity_is_refused(self):
        why, _ = self.door({"Host": SERVE})
        self.assertIn("signed-in identity", why)
        why, _ = self.door({"Host": SERVE, control.LOGIN_HEADER: "  "})
        self.assertIn("signed-in identity", why)

    def test_the_origin_must_be_the_serve_name_over_https(self):
        h = {"Host": SERVE, control.LOGIN_HEADER: "owner@example.com"}
        for bad in (f"http://{SERVE}", "http://127.0.0.1:4320", "https://evil.example"):
            self.assertIn("another site", self.door(dict(h, Origin=bad))[0], bad)

    def test_without_a_serve_name_only_localhost_answers(self):
        h = {"Host": SERVE, control.LOGIN_HEADER: "owner@example.com"}
        self.assertIn("127.0.0.1 and localhost only", self.door(h, serve="")[0])
        self.assertEqual(self.door({"Host": "127.0.0.1:4320"}), (None, None), "localhost keeps the page's own by")
        self.assertIn("another site", self.door({"Host": "127.0.0.1:4320", "Origin": f"https://{SERVE}"})[0])

    def test_the_map_is_read_from_the_machine_file_alone(self):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        local = os.path.join(d, "engine.local.json")
        with open(local, "w", encoding="utf-8") as f:
            json.dump({"params": {"host": {"serve_name": SERVE.upper() + ".", "roles": {"owner@example.com": "alpha"}}}}, f)
        with mock.patch.object(control.config, "LOCAL_JSON", local):
            self.assertEqual(control.door_settings(), (SERVE, {"owner@example.com": "alpha"}))
        with mock.patch.object(control.config, "LOCAL_JSON", os.path.join(d, "none.json")):
            self.assertEqual(control.door_settings()[1], {})


class TheDoorServed(Server):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(control, "door_settings", return_value=(SERVE, ROLES))
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_signed_in_role_replaces_the_pages_by(self):
        with mock.patch.object(control, "approve_post", return_value={"outcome": "applied"}) as ap:
            served = {"Host": SERVE, "Origin": f"https://{SERVE}", "X-Control-Token": self.token}
            code, body = self.call("/api/approve", {"id": "Q-1", "by": "team"}, dict(served, **{control.LOGIN_HEADER: "owner@example.com"}))
            self.assertEqual(code, 200, body)
            ap.assert_called_once_with("Q-1", "alpha", reason=None, scope=None)
            code, body = self.call("/api/approve", {"id": "Q-1", "by": "alpha"}, dict(served, **{control.LOGIN_HEADER: "stranger@example.com"}))
            self.assertEqual(code, 403)
            self.assertNotIn("stranger", body)
            code, _ = self.call("/api/approve", {"id": "Q-1", "by": "alpha"}, served)
            self.assertEqual(code, 403, "no identity, no act")
            self.assertEqual(ap.call_count, 1)
            code, _ = self.call("/api/approve", {"id": "Q-1", "by": "beta"}, {"X-Control-Token": self.token})
            self.assertEqual(code, 200, "localhost is as it was")
            self.assertEqual(ap.call_args.args[1], "beta")


if __name__ == "__main__":
    unittest.main()

