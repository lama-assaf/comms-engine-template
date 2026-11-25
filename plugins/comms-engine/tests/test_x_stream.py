"""x_stream: rules built from shared memory fit twitterapi.io; the WebSocket parser keeps partial frames.

The rules read the fixture memory (`fixture_memory.py`) and the fixture
`themes.json` beside it, never the checkout's own handles or search terms.
"""
import copy
import json
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixture_memory  # noqa: E402

# x_stream derives PREFIX and BRAND_NAME from the brand at import; the import
# runs under the fixture so the module constants are the fixture brand's, and
# every test case installs the fixture again for its own reads.
_boot = fixture_memory.FixtureMemory().start()
try:
    import x_stream  # noqa: E402
finally:
    _boot.stop()

THEMES_JSON = Path(fixture_memory.THEMES_JSON)


class Rules(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        self.cfg = json.loads(THEMES_JSON.read_text())
        self.rules = x_stream.desired_rules(self.cfg)

    def test_every_rule_fits_and_is_owned(self):
        self.assertEqual(len(self.rules), 4 + len(self.cfg["search_terms"]))
        for tag, value, interval in self.rules:
            self.assertTrue(tag.startswith(x_stream.PREFIX), tag)
            self.assertLessEqual(len(value), x_stream.MAX_RULE, tag)
            self.assertGreaterEqual(interval, 100, tag)

    def test_the_prefix_is_the_brand_slug(self):
        self.assertEqual(x_stream.PREFIX, fixture_memory.ROOT + ":")

    def test_theme_rules_are_the_listener_terms_verbatim(self):
        by_tag = {t: v for t, v, _ in self.rules}
        for tag, term in self.cfg["search_terms"].items():
            self.assertEqual(by_tag[f"{x_stream.PREFIX}theme:{tag[1:]}"], term["x_search"])

    def test_hashtags_are_searched_as_bare_words(self):
        value = dict((t, v) for t, v, _ in self.rules)[x_stream.PREFIX + "hashtags"]
        self.assertNotIn("#", value)
        for tag in list(self.cfg["search_terms"]) + x_stream.OWN_TAGS:
            self.assertIn(tag[1:], value)

    def test_own_and_mentions_rules_use_the_recorded_own_handle(self):
        own = x_stream.own_x_handle()
        self.assertEqual(own, "@acme_hq")
        by_tag = {t: v for t, v, _ in self.rules}
        self.assertEqual(by_tag[x_stream.PREFIX + "own"], "from:acme_hq")
        self.assertIn("-from:acme_hq", by_tag[x_stream.PREFIX + "mentions"])

    def test_partners_come_from_handles_md(self):
        value = dict((t, v) for t, v, _ in self.rules)[x_stream.PREFIX + "partners"]
        kept = [h for h in x_stream.partner_handles() if h != "@betalabs"]
        self.assertEqual(value, " OR ".join("from:" + h[1:] for h in kept))
        # a stream's listening is that stream's only (themes.json `ignore`, 2026-10-26).
        self.assertIn("@betalabs", x_stream.partner_handles())
        self.assertNotIn("from:betalabs", value)

    def test_a_term_over_255_fails_loudly(self):
        cfg = copy.deepcopy(self.cfg)
        tag = next(iter(cfg["search_terms"]))
        cfg["search_terms"][tag]["x_search"] = "x" * 256
        with self.assertRaises(x_stream.RuleError):
            x_stream.desired_rules(cfg)

    def test_a_roster_disagreement_fails_loudly(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["search_terms"].pop(next(iter(cfg["search_terms"])))
        with self.assertRaises(x_stream.RuleError):
            x_stream.desired_rules(cfg)


class NoOwnHandle(fixture_memory.FixtureMemoryCase):
    """A stream without an own X row has no `own` or `mentions` rule: never guessed."""

    def test_own_handle_is_required(self):
        path = self.fixture.path("handles.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace("| Acme | X | @acme_hq |", "| Acme | X |  |"))
        with self.assertRaises(x_stream.RuleError):
            x_stream.own_x_handle()
        with self.assertRaises(x_stream.RuleError):
            x_stream.desired_rules(json.loads(THEMES_JSON.read_text()))

    def test_import_without_an_own_handle(self):
        """`import x_stream` works with no own handle recorded; the pattern is built on demand."""
        import subprocess
        path = self.fixture.path("handles.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace("| Acme | X | @acme_hq |", "| Acme | X |  |"))
        code = ("import sys; sys.path.insert(0, %r); import memory; "
                "memory.HANDLES_MD = %r; import x_stream; print(x_stream.about_pattern().pattern)"
                % (str(Path(__file__).resolve().parent.parent / "scripts"), path))
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # the subprocess reads the checkout's own engine.json for the brand name
        with open(fixture_memory.LIVE_ENGINE_JSON, encoding="utf-8") as f:
            live_name = (json.load(f).get("brand") or {}).get("name", fixture_memory.ROOT_NAME)
        self.assertIn(live_name, proc.stdout)
        self.assertNotIn("acme_hq", proc.stdout)


class FreshClone(unittest.TestCase):
    """The checkout's own handles.md (the template ships its own X row blank) and no key:
    `x_stream.py rules` says what is missing on one line and never tracebacks."""

    def test_rules_against_the_shipped_memory(self):
        import os
        import subprocess
        script = Path(__file__).resolve().parent.parent / "scripts" / "x_stream.py"
        env = {k: v for k, v in os.environ.items() if k != "TWITTERAPI_IO_API_KEY"}
        proc = subprocess.run([sys.executable, str(script), "rules"], capture_output=True, text=True, env=env,
                              cwd=str(script.parent.parent.parent.parent))
        self.assertIn(proc.returncode, (0, 1), proc.stderr)
        self.assertNotIn("Traceback", proc.stdout + proc.stderr)
        if proc.returncode == 1:
            self.assertTrue(proc.stderr.startswith("x_stream: ") or "desired rules only" in proc.stdout,
                            proc.stdout + proc.stderr)

    def test_import_is_the_brand_prefix(self):
        import json
        with open(fixture_memory.LIVE_ENGINE_JSON, encoding="utf-8") as f:
            slug = (json.load(f).get("brand") or {}).get("slug", fixture_memory.ROOT)
        code = ("import sys; sys.path.insert(0, %r); import x_stream; print(x_stream.PREFIX)"
                % str(Path(__file__).resolve().parent.parent / "scripts"))
        import subprocess
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), slug + ":")


def frame(op, payload, fin=True, mask=None):
    n = len(payload)
    b1 = (0x80 if fin else 0) | op
    m = 0x80 if mask else 0
    head = struct.pack("!BB", b1, m | n) if n < 126 else struct.pack("!BBH", b1, m | 126, n)
    if mask:
        payload = bytes(x ^ mask[i % 4] for i, x in enumerate(payload))
        return head + mask + payload
    return head + payload


class Parser(unittest.TestCase):
    def ws(self, buf=b""):
        w = object.__new__(x_stream.WebSocket)
        w.buf, w.parts = buf, []
        return w

    def test_partial_frame_waits_and_keeps_the_buffer(self):
        data = frame(0x1, b'{"event_type":"ping"}')
        w = self.ws(data[:5])
        self.assertIsNone(w._frame())
        self.assertEqual(w.buf, data[:5])
        w.buf += data[5:]
        self.assertEqual(w._frame(), (0x80, 0x1, b'{"event_type":"ping"}'))
        self.assertEqual(w.buf, b"")

    def test_long_and_masked_frames(self):
        body = json.dumps({"event_type": "tweet", "tweets": [{"id": "1", "text": "x" * 300}]}).encode()
        w = self.ws(frame(0x1, body, mask=b"\x01\x02\x03\x04"))
        self.assertEqual(w._frame()[2], body)

    def test_fragments_join_into_one_message(self):
        w = self.ws(frame(0x1, b'{"event_type":', fin=False) + frame(0x0, b'"connected"}'))
        self.assertEqual(json.loads(w.recv())["event_type"], "connected")

    def test_close_frame_raises_with_its_code(self):
        w = self.ws(frame(0x8, struct.pack("!H", 1008) + b"one connection per key"))
        w.send = lambda *a: None
        with self.assertRaises(x_stream.Closed) as cm:
            w.recv()
        self.assertEqual(cm.exception.code, 1008)


class Records(unittest.TestCase):
    def test_a_quote_of_our_post_names_the_brand(self):
        t = {"id": "9", "text": "@someone What's in it for holders?", "author": {"userName": "a", "followers": 39},
             "quoted_tweet": {"id": "8", "text": f"A partner joins {x_stream.BRAND_NAME}", "author": {"userName": "brand_hq"}}}
        r = x_stream.record(t, "r1", x_stream.PREFIX + "mentions")
        self.assertTrue(r["about_brand"])
        self.assertEqual(r["quoted"]["handle"], "brand_hq")
        t["quoted_tweet"]["text"] = "A partner joins nobody in particular"
        self.assertFalse(x_stream.record(t, "r1", x_stream.PREFIX + "mentions")["about_brand"])


class Poll(unittest.TestCase):
    """The scheduled search: planned rules through channels.search, since_id persisted, no live call."""

    RULES = [("t:mentions", "(@x OR y) -from:x", 600), ("t:own", "from:x", 3600)]

    def setUp(self):
        import tempfile
        from unittest import mock
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(x_stream, "STATE", self.tmp.name)
        p.start()
        self.addCleanup(p.stop)
        self.calls = []

    def fake(self, by_query):
        def search(query, since=None, max_items=12, stream=None, query_type="Top", **kw):
            self.calls.append((query, since, max_items))
            return by_query.get(query, [])
        return search

    @staticmethod
    def tweet(i, text="hello"):
        return {"id": str(i), "text": text, "createdAt": "Mon Nov 09 10:00:00 +0000 2026",
                "author": {"userName": "someone", "name": "S", "followers": 5}, "likeCount": 1}

    def written(self):
        out = []
        for p in sorted(Path(self.tmp.name).glob("*.jsonl")):
            out += [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        return out

    def test_dry_run_plans_and_calls_nothing(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(x_stream.poll(dry_run=True, rules=self.RULES, search=self.fake({})), 0)
        self.assertEqual(self.calls, [])
        self.assertIn("would run", buf.getvalue())
        self.assertIn("(@x OR y) -from:x", buf.getvalue())
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_matches_land_in_the_stream_file_with_the_rule_tag(self):
        search = self.fake({"from:x": [self.tweet(105, "one"), self.tweet(103, "two")]})
        x_stream.poll(rules=self.RULES, search=search, now=1_800_000_000, skip=[])
        rows = self.written()
        self.assertEqual({r["id"] for r in rows}, {"105", "103"})
        self.assertEqual({r["rule_tag"] for r in rows}, {"t:own"})
        self.assertIn("text", rows[0])
        self.assertEqual(self.calls[0][2], 12)

    def test_since_id_is_persisted_and_older_items_are_not_rewritten(self):
        x_stream.poll(rules=self.RULES, search=self.fake({"from:x": [self.tweet(105), self.tweet(103)]}),
                      now=1_800_000_000, skip=[])
        self.assertEqual(x_stream.load_poll_state()["t:own"]["since_id"], "105")
        plan = {t: (ts, sid) for t, _q, ts, sid in x_stream.poll_plan(self.RULES, now=1_800_001_800)}
        self.assertEqual(plan["t:own"][1], "105")
        self.assertEqual(plan["t:own"][0], 1_800_000_000 - 60)
        x_stream.poll(rules=self.RULES, search=self.fake({"from:x": [self.tweet(105), self.tweet(106)]}),
                      now=1_800_001_800, skip=[])
        self.assertEqual(sorted(r["id"] for r in self.written()), ["103", "105", "106"])
        self.assertEqual(x_stream.load_poll_state()["t:own"]["since_id"], "106")

    def test_a_failing_rule_keeps_its_since_id_and_the_others_run(self):
        x_stream.poll(rules=self.RULES, search=self.fake({"from:x": [self.tweet(7)]}), now=1_800_000_000, skip=[])

        def boom(query, *a, **kw):
            if query == "from:x":
                raise RuntimeError("down")
            return [self.tweet(9)]
        x_stream.poll(rules=self.RULES, search=boom, now=1_800_001_800, skip=[])
        state = x_stream.load_poll_state()
        self.assertEqual(state["t:own"]["since_id"], "7")
        self.assertEqual(state["t:mentions"]["since_id"], "9")

    def test_other_stream_posts_are_dropped(self):
        search = self.fake({"from:x": [self.tweet(5, "about otherbrand"), self.tweet(6, "ours")]})
        x_stream.poll(rules=self.RULES, search=search, now=1_800_000_000, skip=["otherbrand"])
        self.assertEqual([r["id"] for r in self.written()], ["6"])


class ApplyRefusal(unittest.TestCase):
    """`rules --apply` goes live only in websocket mode with a twitterapi effective driver."""

    def run_apply(self, mode, driver):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        from unittest import mock
        import channels
        called = []
        with mock.patch.object(x_stream, "x_mode", return_value=mode), \
                mock.patch.object(channels, "effective_x_read", return_value=(driver, None)), \
                mock.patch.object(x_stream.secrets, "get_secret", return_value="k"), \
                mock.patch.object(x_stream, "rules_cmd", side_effect=lambda *a, **k: called.append((a, k))), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            code = x_stream.main(["rules", "--apply"])
        return code, called, err.getvalue()

    def test_refused_in_poll_mode(self):
        code, called, err = self.run_apply("poll", "twitterapi")
        self.assertEqual(code, 2)
        self.assertEqual(called, [])
        self.assertIn("refused", err)

    def test_refused_when_the_effective_driver_is_not_twitterapi(self):
        code, called, err = self.run_apply("websocket", "composio")
        self.assertEqual(code, 2)
        self.assertEqual(called, [])
        self.assertIn("composio", err)

    def test_allowed_only_in_websocket_mode_on_twitterapi(self):
        code, called, _ = self.run_apply("websocket", "twitterapi")
        self.assertNotEqual(code, 2)
        self.assertEqual(len(called), 1)
        self.assertTrue(called[0][1]["apply"])

    def test_off_is_never_refused(self):
        from unittest import mock
        import io
        from contextlib import redirect_stdout
        called = []
        with mock.patch.object(x_stream, "x_mode", return_value="poll"), \
                mock.patch.object(x_stream.secrets, "get_secret", return_value="k"), \
                mock.patch.object(x_stream, "rules_cmd", side_effect=lambda *a, **k: called.append(k)), \
                redirect_stdout(io.StringIO()):
            x_stream.main(["rules", "--off"])
        self.assertEqual(len(called), 1)

    def test_the_default_mode_is_poll(self):
        self.assertEqual(x_stream.x_mode(), "poll")


if __name__ == "__main__":
    unittest.main()
