"""
channels.py status reads and the engine console's Composio setup and doctor lines.

The Composio HTTP layer is faked (`fake_composio_http`, `channels.connections`, `channels._execute`) and the registry
is a made-up stream, so nothing is spawned and no brand is named:

- `stream_channels` reads the streams.md channels cell: X and LinkedIn count, the
  website and an unfilled cell do not; a 'collect' entry has no handle
- `stream_status` gives connected / active / handle lines per channel: no account
  under the alias is news (ok, with the link command), an account that is not
  ACTIVE or whose live handle differs from the cell is a fault, an unreadable
  account list is one FAIL line
- `x_read_driver` defaults to twitterapi and reads `channels.x_read.<stream>`
- `doctor_report` gives each stream its auth-config line, its channels and ends with its X read driver
- `engine.setup_composio` prints the dashboard steps for the channels not yet connected, with
  the alias `<stream>-<channel>`, starts no process, and refuses a stream with no channel
- `engine.py doctor` prints the composio lines after the checks and counts them
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
sys.path.insert(0, HERE)

import channels  # noqa: E402
import fake_composio_key  # noqa: E402
import config  # noqa: E402
import engine  # noqa: E402
import memory  # noqa: E402

CELL = "X @alpha_x; LinkedIn (slug to collect); website https://alpha.example"
ROWS = {
    "alpha": {"slug": "alpha", "channels": CELL},
    "beta": {"slug": "beta", "channels": "— (collect)"},
    "gamma": {"slug": "gamma", "channels": "X @gamma_x; LinkedIn linkedin.com/company/gamma"},
}


def acct(alias, status="ACTIVE"):
    return {"id": "ca_" + alias, "status": status, "alias": alias, "word_id": "w_" + alias}


def done(stdout="", code=0, stderr=""):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)


class Base(unittest.TestCase):
    def setUp(self):
        def stream(slug, path=None):
            key = (slug or "").strip().lower()
            if key not in ROWS:
                raise memory.SharedMemoryError(f"unknown stream {slug!r}")
            return ROWS[key]

        self.drivers = {}
        for p in (
            mock.patch.object(memory, "stream", stream),
            mock.patch.object(memory, "streams", lambda path=None: list(ROWS)),
            mock.patch.object(config, "cfg", lambda path, default=None, **kw: self.drivers.get(path, default)),
        ):
            p.start()
            self.addCleanup(p.stop)


class Parse(Base):
    def test_channels_cell(self):
        self.assertEqual(channels.stream_channels("alpha"), [("x", "@alpha_x"), ("linkedin", None)])
        self.assertEqual(channels.stream_channels("beta"), [])
        self.assertEqual(channels.stream_channels("gamma"),
                         [("x", "@gamma_x"), ("linkedin", "linkedin.com/company/gamma")])

    def test_unknown_stream_is_refused(self):
        with self.assertRaises(memory.SharedMemoryError):
            channels.stream_channels("nope")

    def test_x_read_driver(self):
        self.assertEqual(channels.x_read_driver("alpha"), ("twitterapi", None))
        self.drivers["channels.x_read.alpha"] = "composio"
        self.assertEqual(channels.x_read_driver("alpha"), ("composio", None))
        self.drivers["channels.x_read.alpha"] = "scraper"
        driver, why = channels.x_read_driver("alpha")
        self.assertEqual(driver, "scraper")
        self.assertIn("unknown driver", why)


class Status(Base):
    def lines(self, conns, **kw):
        return {l["check"]: l for l in channels.stream_status("alpha", conns, **kw)}

    def test_unlinked_is_news_not_a_fault(self):
        got = self.lines({})
        self.assertEqual(set(got), {"composio alpha/x connected", "composio alpha/linkedin connected"})
        line = got["composio alpha/x connected"]
        self.assertTrue(line["ok"])
        self.assertIn("'alpha-x'", line["tail"])
        self.assertIn("engine.py setup composio alpha", line["tail"])

    def test_linked_active_with_matching_handle(self):
        conns = {"twitter": [acct("alpha-x")]}
        with mock.patch.object(channels, "_execute", return_value={"data": {"data": {"username": "Alpha_X"}}, "successful": True}) as ex:
            got = self.lines(conns)
        ex.assert_called_once_with("alpha", "x", "TWITTER_USER_LOOKUP_ME")
        self.assertTrue(all(l["ok"] for l in got.values()))
        self.assertEqual(got["composio alpha/x active"]["tail"], "status ACTIVE")
        self.assertIn("@alpha_x recorded, account says @Alpha_X", got["composio alpha/x handle"]["tail"])

    def test_handle_mismatch_fails(self):
        conns = {"twitter": [acct("alpha-x")]}
        with mock.patch.object(channels, "_execute", return_value={"data": {"username": "someone_else"}}):
            got = self.lines(conns)
        self.assertFalse(got["composio alpha/x handle"]["ok"])
        self.assertIn("@someone_else", got["composio alpha/x handle"]["tail"])

    def test_expired_account_fails_active_and_skips_the_handle_probe(self):
        conns = {"twitter": [acct("alpha-x", "EXPIRED")]}
        with mock.patch.object(channels, "_execute") as ex:
            got = self.lines(conns)
        ex.assert_not_called()
        self.assertFalse(got["composio alpha/x active"]["ok"])
        self.assertNotIn("composio alpha/x handle", got)

    def test_another_streams_account_is_not_this_ones(self):
        conns = {"twitter": [acct("gamma-x")]}
        got = self.lines(conns)
        self.assertEqual(got["composio alpha/x connected"]["tail"].split(" ")[0], "no")

    def test_handle_probe_error_fails(self):
        conns = {"twitter": [acct("alpha-x")]}
        with mock.patch.object(channels, "_execute", side_effect=channels.ChannelError("boom")):
            got = self.lines(conns)
        self.assertFalse(got["composio alpha/x handle"]["ok"])
        self.assertEqual(got["composio alpha/x handle"]["tail"], "boom")

    def test_linkedin_handle_is_looked_for_in_the_profile(self):
        conns = {"linkedin": [acct("gamma-linkedin")]}
        with mock.patch.object(channels, "_execute", return_value={"data": {"vanityName": "gamma"}}):
            got = {l["check"]: l for l in channels.stream_status("gamma", conns)}
        self.assertTrue(got["composio gamma/linkedin handle"]["ok"])
        with mock.patch.object(channels, "_execute", return_value={"data": {"vanityName": "other"}}):
            got = {l["check"]: l for l in channels.stream_status("gamma", conns)}
        self.assertFalse(got["composio gamma/linkedin handle"]["ok"])

    def test_no_recorded_handle_is_ok(self):
        conns = {"linkedin": [acct("alpha-linkedin")]}
        got = self.lines(conns)
        self.assertIn("no handle recorded", got["composio alpha/linkedin handle"]["tail"])

    def test_stream_without_channels_has_no_lines(self):
        self.assertEqual(channels.stream_status("beta", {}), [])

    def test_unreadable_account_list_is_one_fail_line(self):
        with mock.patch.object(channels, "connections", side_effect=channels.ChannelError("HTTP 401")):
            lines = channels.stream_status("alpha")
        self.assertEqual(len(lines), 1)
        self.assertFalse(lines[0]["ok"])
        self.assertIn("HTTP 401", lines[0]["tail"])


class Report(Base):
    def report(self, conns=None, key=True, configs=()):
        with mock.patch.object(channels, "connections", return_value=conns if conns is not None else {}), \
                mock.patch.object(channels, "auth_configs", return_value=[{"id": i} for i in configs]), \
                mock.patch.dict(sys.modules, {"secrets": mock.Mock(get_secret=lambda name, required=True, stream=None: "k" if key else None)}):
            return {l["check"]: l for l in channels.doctor_report()}

    def test_per_stream_lines_and_no_cli_line(self):
        got = self.report()
        self.assertNotIn("composio cli version", got)
        self.assertIn("composio alpha auth configs", got)
        self.assertIn("composio alpha/x connected", got)
        self.assertIn("composio gamma/linkedin connected", got)
        self.assertFalse(any(c.startswith("composio beta") for c in got))
        self.assertEqual(got["composio alpha x read driver"]["tail"], "twitterapi (listening and monitors) (key set)")
        self.assertEqual(got["composio alpha x own driver"]["tail"], "twitterapi (own-post numbers, mentions and replies) (key set)")
        self.assertTrue(all(l["ok"] for l in got.values()))

    def test_missing_key_fails_the_twitterapi_driver(self):
        self.drivers["channels.composio_org.alpha"] = "Team One"  # configured, so not skipped
        self.assertFalse(self.report(key=False)["composio alpha x read driver"]["ok"])

    def test_composio_without_signoff_is_held(self):
        self.drivers["channels.x_read.alpha"] = "composio"
        line = self.report()["composio alpha x read driver"]
        self.assertIn("held: price sign-off not recorded", line["tail"])
        self.assertTrue(line["tail"].startswith("twitterapi"))

    def test_own_class_is_held_on_its_own_signoff(self):
        self.drivers["channels.x_own.alpha"] = "composio"
        line = self.report()["composio alpha x own driver"]
        self.assertIn("held: own-post price sign-off not recorded", line["tail"])
        self.assertTrue(line["tail"].startswith("twitterapi"))
        # the listening sign-off does not release the own class
        self.drivers["listen.x_price_signoff"] = "2026-11-11"
        self.assertIn("held: own-post", self.report()["composio alpha x own driver"]["tail"])

    def test_own_signoff_runs_own_reads_on_composio_and_listening_stays_held(self):
        self.drivers["channels.x_read.alpha"] = "composio"  # even if listening is configured composio...
        self.drivers["channels.x_own.alpha"] = "composio"
        self.drivers["listen.x_own_price_signoff"] = "2026-11-11 owner: own-post numbers and inbound only"
        conns = {"twitter": [acct("alpha-x")]}
        with mock.patch.object(channels, "_execute", return_value={"data": {"username": "alpha_x"}}):
            got = self.report(conns=conns)
        self.assertTrue(got["composio alpha x own driver"]["tail"].startswith("composio (own-post numbers"))
        self.assertTrue(got["composio alpha x own driver"]["ok"])
        # ...the scoped sign-off does not release it: listening is held and reads twitterapi.io
        self.assertIn("held: price sign-off not recorded", got["composio alpha x read driver"]["tail"])
        self.assertTrue(got["composio alpha x read driver"]["tail"].startswith("twitterapi"))

    def test_composio_driver_needs_an_active_x_account(self):
        self.drivers["channels.x_read.alpha"] = "composio"
        self.drivers["listen.x_price_signoff"] = "2026-11-11"
        self.assertFalse(self.report()["composio alpha x read driver"]["ok"])
        conns = {"twitter": [acct("alpha-x")]}
        with mock.patch.object(channels, "_execute", return_value={"data": {"username": "alpha_x"}}):
            self.assertTrue(self.report(conns=conns)["composio alpha x read driver"]["ok"])

    def test_unreadable_connections_fail(self):
        fake_composio_key.install(self)
        with mock.patch.object(channels, "connections", side_effect=channels.ChannelError("HTTP 401")), \
                mock.patch.object(channels, "auth_configs", return_value=[]):
            got = {l["check"]: l for l in channels.doctor_report()}
        self.assertFalse(got["composio alpha connections"]["ok"])


class Key(Base):
    """Every call carries the stream's resolved key in the x-api-key header only."""

    def setUp(self):
        super().setUp()
        import fake_composio_http
        self.asked = fake_composio_key.install(self, {"alpha": "alpha-secret-value", "gamma": "gamma-secret-value"})
        self.fake = fake_composio_http.install(self)
        fake_composio_key.install(self, {"alpha": "alpha-secret-value", "gamma": "gamma-secret-value"})

    def test_each_call_carries_its_streams_key_in_the_header_and_not_the_url(self):
        channels._execute("alpha", "x", "TWITTER_USER_LOOKUP_ME")
        channels._execute("gamma", "x", "TWITTER_USER_LOOKUP_ME")
        channels.connections("gamma", fresh=True)
        channels._proxy_get("alpha", "linkedin", "https://api.example/x")
        keys = [c["headers"]["x-api-key"] for c in self.fake.calls]
        self.assertEqual(set(keys), {"alpha-secret-value", "gamma-secret-value"})
        for call, key in zip(self.fake.calls, keys):
            self.assertNotIn(key, call["url"])
            self.assertNotIn(key, repr(call["body"]))

    def test_the_inherited_environment_key_is_not_used(self):
        with mock.patch.dict(os.environ, {"COMPOSIO_API_KEY": "inherited-personal-key"}):
            channels._execute("alpha", "x", "TWITTER_USER_LOOKUP_ME")
        self.assertEqual({c["headers"]["x-api-key"] for c in self.fake.calls}, {"alpha-secret-value"})

    def test_a_stream_without_a_key_is_refused_and_nothing_is_sent(self):
        with self.assertRaises(channels.MissingComposioKey) as cm:
            channels._execute("beta", "x", "TWITTER_USER_LOOKUP_ME")
        self.assertIn("beta", str(cm.exception))
        self.assertIn("COMPOSIO_API_KEY", str(cm.exception))
        for call in (lambda: channels.connections("beta"), lambda: channels._proxy_get("beta", "x", "https://api.example/x"),
                     lambda: channels.auth_configs("beta")):
            with self.assertRaises(channels.MissingComposioKey):
                call()
        self.assertEqual(self.fake.calls, [])

    def test_the_error_and_the_doctor_lines_never_carry_the_key(self):
        self.fake.status, self.fake.error_body = 403, "denied {key}"
        with self.assertRaises(channels.ChannelError) as cm:
            channels._execute("alpha", "x", "TWITTER_USER_LOOKUP_ME")
        self.assertNotIn("alpha-secret-value", str(cm.exception))
        text = json.dumps(channels.doctor_report())
        self.assertNotIn("alpha-secret-value", text)
        self.assertNotIn("gamma-secret-value", text)


class AuthConfigs(Base):
    def setUp(self):
        super().setUp()
        self.keys = {"alpha": "k", "gamma": "k"}
        fake_composio_key.install(self, self.keys)

    def seen(self, *ids):
        return [{"id": i, "toolkit": "twitter"} for i in ids]

    def test_recorded_and_visible_is_ok(self):
        self.drivers["channels.auth_config.alpha.x"] = "ac_1"
        self.drivers["channels.auth_config.alpha.linkedin"] = "ac_2"
        line = channels.auth_config_line("alpha", self.seen("ac_1", "ac_2", "ac_3"))
        self.assertTrue(line["ok"])
        self.assertEqual(line["check"], "composio alpha auth configs")
        self.assertIn("all visible", line["tail"])

    def test_recorded_but_not_visible_fails_and_names_it(self):
        self.drivers["channels.auth_config.alpha.x"] = "ac_1"
        self.drivers["channels.auth_config.alpha.linkedin"] = "ac_2"
        line = channels.auth_config_line("alpha", self.seen("ac_1"))
        self.assertFalse(line["ok"])
        self.assertIn("linkedin ac_2", line["tail"])
        self.assertIn("not that project's", line["tail"])

    def test_not_recorded_is_ok_and_says_so(self):
        line = channels.auth_config_line("alpha", self.seen("ac_1"))
        self.assertTrue(line["ok"])
        self.assertIn("none recorded", line["tail"])
        self.assertIn("params.channels.auth_config.alpha", line["tail"])

    def test_unreadable_with_a_recorded_id_fails_and_without_stays_green(self):
        with mock.patch.object(channels, "auth_configs", side_effect=channels.ChannelError("HTTP 401")):
            self.assertTrue(channels.auth_config_line("alpha")["ok"])
            self.drivers["channels.auth_config.alpha.x"] = "ac_1"
            line = channels.auth_config_line("alpha")
        self.assertFalse(line["ok"])
        self.assertIn("HTTP 401", line["tail"])

    def test_no_key_is_a_fail_line(self):
        self.keys.clear()
        self.drivers["channels.composio_org.alpha"] = "Team One"
        line = channels.auth_config_line("alpha")
        self.assertFalse(line["ok"])
        self.assertEqual(line["check"], "composio alpha api key")

    def test_doctor_report_fails_a_stream_without_a_key(self):
        del self.keys["gamma"]
        self.drivers["channels.write_driver.gamma"] = "composio"  # configured, so a missing key is a fault
        with mock.patch.object(channels, "connections", return_value={}), \
                mock.patch.object(channels, "auth_configs", return_value=[]):
            got = {l["check"]: l for l in channels.doctor_report()}
        self.assertTrue(got["composio alpha auth configs"]["ok"])
        self.assertFalse(got["composio gamma api key"]["ok"])
        self.assertNotIn("composio gamma/x connected", got, "no composio read for a stream without a key")
        self.assertFalse(any(c.startswith("composio beta") for c in got))

    def test_stream_status_without_a_key_fails(self):
        self.keys.clear()
        self.drivers["channels.composio_org.alpha"] = "Team One"
        lines = channels.stream_status("alpha")
        self.assertEqual([(l["check"], l["ok"]) for l in lines], [("composio alpha api key", False)])


class UnsetStream(Base):
    """A stream with no key and nothing configured for Composio is skipped, not failed."""

    def setUp(self):
        super().setUp()
        self.keys = {"alpha": "k"}  # gamma has none
        self.asked = fake_composio_key.install(self, self.keys)

    def report(self):
        with mock.patch.object(channels, "connections", return_value={}) as conns, \
                mock.patch.object(channels, "auth_configs", return_value=[]):
            got = {l["check"]: l for l in channels.doctor_report()}
        self.conns = conns
        return got

    def test_composio_setup_reasons(self):
        self.assertTrue(channels.composio_setup("alpha")[0])
        self.assertFalse(channels.composio_setup("gamma")[0])
        self.drivers["channels.composio_org.gamma"] = "Team Two"
        self.assertTrue(channels.composio_setup("gamma")[0])
        del self.drivers["channels.composio_org.gamma"]
        self.drivers["channels.write_driver.gamma"] = "composio"
        self.assertTrue(channels.composio_setup("gamma")[0])

    def test_unset_stream_gets_one_green_line_and_nothing_else(self):
        got = self.report()
        mine = [c for c in got if c.startswith("composio gamma")]
        self.assertEqual(mine, ["composio gamma"])
        self.assertTrue(got["composio gamma"]["ok"])
        self.assertIn("not set up for Composio", got["composio gamma"]["tail"])

    def test_stream_with_a_key_is_checked_in_full(self):
        got = self.report()
        for check in ("composio alpha auth configs", "composio alpha/x connected", "composio alpha/linkedin connected",
                      "composio alpha x read driver"):
            self.assertIn(check, got)

    def test_configured_but_no_key_still_fails(self):
        for path, value in (("channels.composio_org.gamma", "Team Two"), ("channels.write_driver.gamma", "composio"),
                            ("channels.x_read.gamma", "composio")):
            with self.subTest(path=path):
                self.drivers.clear()
                self.drivers[path] = value
                got = self.report()
                self.assertFalse(got["composio gamma api key"]["ok"])
                self.assertNotIn("composio gamma", got)
                self.assertNotIn("composio gamma/x connected", got)

    def test_unset_stream_status_is_empty_and_sends_nothing(self):
        import fake_composio_http
        fake = fake_composio_http.install(self)
        fake_composio_key.install(self, self.keys)
        self.assertEqual(channels.stream_status("gamma"), [])
        self.assertEqual(fake.calls, [])

    def test_unset_auth_config_line_is_green(self):
        line = channels.auth_config_line("gamma")
        self.assertTrue(line["ok"])
        self.assertIn("not set up for Composio", line["tail"])

    def test_setup_composio_for_an_unset_stream_says_what_is_missing_and_refuses(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = engine.main(["setup", "composio", "gamma"])
        self.assertEqual(rc, 1)
        self.assertIn("no Composio API key for stream 'gamma'", buf.getvalue())
        self.assertIn("not set up for Composio", buf.getvalue())


class Console(Base):
    def setUp(self):
        super().setUp()
        fake_composio_key.install(self)
        self.spawned = []

        def fake_run_cmd(argv, timeout=None, capture=False, cwd=None, env=None, stdin=None):
            self.spawned.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        p = mock.patch.object(engine, "run_cmd", fake_run_cmd)
        p.start()
        self.addCleanup(p.stop)

    def quiet(self, fn, *a, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = fn(*a, **kw)
        return rc, buf.getvalue()

    def test_setup_prints_dashboard_steps_only_for_what_is_not_connected(self):
        conns = {"twitter": [acct("alpha-x")]}
        self.drivers["channels.auth_config.alpha.linkedin"] = "ac_li"
        with mock.patch.object(channels, "connections", return_value=conns), \
                mock.patch.object(engine, "channel_doctor_results", return_value=[]):
            rc, out = self.quiet(engine.main, ["setup", "composio", "alpha"])
        self.assertEqual(rc, 0)
        self.assertIn("x: already connected as 'alpha-x'", out)
        self.assertIn("linkedin: not connected. In the Composio dashboard:", out)
        self.assertIn("auth config ac_li", out)
        self.assertIn("'alpha-linkedin'", out)
        self.assertIn("params.channels.account_id.alpha.linkedin", out)
        self.assertNotIn("composio link", out)
        self.assertEqual(self.spawned, [], "setup starts no process")

    def test_setup_accepts_a_recorded_account_id_as_connected(self):
        self.drivers["channels.account_id.alpha.x"] = "ca_dash"
        conns = {"twitter": [{"id": "ca_dash", "status": "ACTIVE", "alias": None}]}
        with mock.patch.object(channels, "connections", return_value=conns), \
                mock.patch.object(engine, "channel_doctor_results", return_value=[]):
            rc, out = self.quiet(engine.main, ["setup", "composio", "alpha"])
        self.assertIn("x: already connected", out)

    def test_setup_never_prints_the_key(self):
        fake_composio_key.install(self, {"alpha": "alpha-secret-value"})
        with mock.patch.object(channels, "connections", return_value={}), \
                mock.patch.object(engine, "channel_doctor_results", return_value=[]):
            rc, out = self.quiet(engine.main, ["setup", "composio", "alpha"])
        self.assertEqual(rc, 0)
        self.assertNotIn("alpha-secret-value", out)

    def test_setup_refuses_a_stream_without_a_key(self):
        fake_composio_key.install(self, {})
        rc, out = self.quiet(engine.main, ["setup", "composio", "alpha", "--dry"])
        self.assertEqual(rc, 1)
        self.assertIn("no Composio API key for stream 'alpha'", out)
        self.assertNotIn("composio login", out)
        self.assertEqual(self.spawned, [])

    def test_dry_prints_the_steps_and_leaves_out_the_doctor_lines(self):
        with mock.patch.object(channels, "connections", return_value={}), \
                mock.patch.object(engine, "channel_doctor_results", side_effect=AssertionError("doctor ran")):
            rc, out = self.quiet(engine.main, ["setup", "composio", "alpha", "--dry"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.spawned, [])
        self.assertIn("x: not connected", out)
        self.assertIn("linkedin: not connected", out)

    def test_stream_without_channels_or_unknown_is_refused(self):
        rc, out = self.quiet(engine.main, ["setup", "composio", "beta"])
        self.assertEqual(rc, 1)
        self.assertIn("no channel Composio serves", out)
        rc, _ = self.quiet(engine.main, ["setup", "composio", "nope"])
        self.assertEqual(rc, 1)
        rc, _ = self.quiet(engine.main, ["setup", "composio"])
        self.assertEqual(rc, 2)
        self.assertEqual(self.spawned, [])

    def test_unreadable_project_stops_setup(self):
        with mock.patch.object(channels, "connections", side_effect=channels.ChannelError("HTTP 401")):
            rc, out = self.quiet(engine.main, ["setup", "composio", "alpha"])
        self.assertEqual(rc, 1)
        self.assertIn("HTTP 401", out)
        self.assertNotIn("composio login", out)

    def test_doctor_prints_the_composio_lines_and_counts_them(self):
        fake = [{"check": "composio alpha/x active", "ok": False, "seconds": 0.0, "tail": "status EXPIRED", "note": True},
                {"check": "composio alpha/x connected", "ok": True, "seconds": 0.0, "tail": "account 'alpha-x'", "note": True}]
        with mock.patch.object(engine, "doctor", return_value=[{"check": "c", "ok": True, "seconds": 0.1, "tail": ""}]), \
                mock.patch.object(engine, "channel_doctor_results", return_value=fake), \
                mock.patch.object(engine, "plugin_doctor_results", return_value=[]), \
                mock.patch.object(engine, "engine_version_result", return_value={"check": "v", "ok": True, "seconds": 0.0, "tail": ""}), \
                mock.patch.object(engine, "claude_token_result", return_value={"check": "t", "ok": True, "seconds": 0.0, "tail": ""}):
            # the plugin and engine-version lines have their own tests
            rc, out = self.quiet(engine.main, ["doctor"])
        self.assertEqual(rc, 1)
        self.assertIn("FAIL    0.0s  composio alpha/x active  -- status EXPIRED", out)
        self.assertIn("ok      0.0s  composio alpha/x connected  -- account 'alpha-x'", out)
        self.assertIn("doctor: 4 ok, 1 failed", out)


if __name__ == "__main__":
    unittest.main()
