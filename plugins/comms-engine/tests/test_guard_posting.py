"""
The PreToolUse hook that refuses a raw platform write around channels.send().

- xurl post/reply/delete, curl/wget/http writes to api.linkedin.com and api.x.com,
  the site webhook, and the Composio write paths are refused with the rule quoted
- composio execute passes only for the exact read slugs of the channel toolkits;
  composio proxy only as a GET; composio run never; discovery and other toolkits pass
- engine scripts pass: every send they make goes through channels.send(), so the hook
  no longer judges who runs a command (no job marker, no --dry exemption for a write)
- a non-Bash tool or unreadable input never blocks the session
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "hooks"))

import guard_posting as g  # noqa: E402

SCRIPTS = "python3 plugins/comms-engine/scripts/"
#: the same scripts as the `engine` command spells them; the hook judges both forms alike
ENGINE = "engine "


class Verdict(unittest.TestCase):
    def refused(self, *cmds):
        for cmd in cmds:
            why = g.verdict(cmd, {})
            self.assertIsNotNone(why, cmd)
            self.assertIn("channels.send()", why)

    def passes(self, *cmds):
        for cmd in cmds:
            self.assertIsNone(g.verdict(cmd, {}), cmd)

    def test_raw_writes_are_refused(self):
        self.refused("npx -y @xdevplatform/xurl --app acme post 'hello'",
                     "npx xurl --app acme reply 123 'thanks'",
                     "npx xurl delete 123",
                     'npx xurl --app acme "post" hi',
                     "curl -X POST https://api.linkedin.com/rest/posts -d @p.json",
                     "curl https://api.x.com/2/tweets -d '{}'",
                     "curl -X DELETE https://api.x.com/2/tweets/1",
                     "curl -d a=b https://api.linkedin.com/v2/me",
                     "wget --post-data=a=b https://api.x.com/2/tweets",
                     "http POST https://api.linkedin.com/rest/posts",
                     SCRIPTS + "publish.py Q-1 --webhook",
                     ENGINE + "publish Q-1 --webhook",
                     "/opt/plugin/bin/engine publish Q-1 --webhook",
                     "cd x && engine publish --webhook Q-1")

    def test_raw_reads_pass(self):
        self.passes("curl -s https://api.x.com/2/users/me -H 'Authorization: x'",
                    "curl https://api.linkedin.com/v2/me",
                    "npx xurl auth status",
                    SCRIPTS + "publish.py Q-1 --webhook --dry-run",
                    SCRIPTS + "publish.py Q-1",
                    ENGINE + "publish Q-1 --webhook --dry-run",
                    ENGINE + "publish Q-1",
                    "git status", "")

    def test_engine_scripts_pass(self):
        # every send these make goes through channels.send(); the hook no longer judges them
        self.passes(SCRIPTS + "autopilot.py run", SCRIPTS + "autopilot.py post",
                    SCRIPTS + "autopilot.py links", SCRIPTS + "autopilot.py snapshot",
                    SCRIPTS + "linkedin_api.py status",
                    SCRIPTS + "channels.py send --dry",
                    SCRIPTS + "engine.py setup composio acme",
                    "python3 -m unittest discover plugins/comms-engine/tests",
                    ENGINE + "autopilot run", ENGINE + "autopilot post", ENGINE + "channels send --dry",
                    ENGINE + "reactions send-due --live", ENGINE + "doctor")

    def test_no_job_marker_and_no_dry_exemption_for_a_write(self):
        self.assertFalse(hasattr(g, "MARKER"), "the autopilot job marker is retired")
        self.assertIsNotNone(g.verdict("npx xurl post hi --dry-run", {}))
        self.assertIsNotNone(g.verdict("npx xurl post hi", {"ACME_AUTOPILOT_JOB": "1"}))

    def test_composio_execute_reads_only_for_channel_toolkits(self):
        self.passes("composio execute TWITTER_RECENT_SEARCH --account acme-x -d '{}'",
                    "composio execute TWITTER_SEARCH_RECENT_COUNTS --account a -d '{}'",
                    "composio execute TWITTER_GET_POST_ANALYTICS --account a -d '{}'",
                    "composio execute LINKEDIN_GET_SHARE_STATS --account a -d '{}'",
                    "composio execute twitter_recent_search -d '{}'",
                    "~/.local/bin/composio execute LINKEDIN_GET_MY_INFO")
        self.refused("composio execute TWITTER_CREATION_OF_A_POST --account a -d '{}'",
                     "composio execute LINKEDIN_CREATE_LINKED_IN_POST -d '{}'",
                     "composio execute LINKEDIN_CREATE_COMMENT_ON_POST -d '{}'",
                     "composio execute TELEGRAM_SEND_MESSAGE -d '{}'",
                     "composio execute DISCORDBOT_CREATE_MESSAGE -d '{}'",
                     "composio execute TWITTER_SOMETHING_NEW -d '{}'",
                     "composio execute --account a TWITTER_CREATION_OF_A_POST",
                     "npx -y @composio/cli execute TELEGRAM_SEND_MESSAGE",
                     "COMPOSIO_BIN=x composio execute TWITTER_CREATION_OF_A_POST",
                     "composio execute TWITTER_RECENT_SEARCH && composio execute TWITTER_CREATION_OF_A_POST")
        # other toolkits are not judged
        self.passes("composio execute GITHUB_CREATE_AN_ISSUE -d '{}'",
                    "composio execute GMAIL_SEND_EMAIL -d '{}'")

    def test_the_reaction_and_take_down_tools_are_refused_raw(self):
        """A like, a repost, their undoing and a delete are writes: by hand they bypass
        channels.send(), its target check, its caps and its one-per-target rule."""
        self.refused("composio execute TWITTER_USER_LIKE_POST --account acme-x -d '{}'",
                     "composio execute TWITTER_UNLIKE_POST -d '{}'",
                     "composio execute TWITTER_RETWEET_POST -d '{\"tweet_id\": \"1\"}'",
                     "composio execute TWITTER_UNRETWEET_POST -d '{}'",
                     "composio execute TWITTER_POST_DELETE_BY_POST_ID -d '{\"id\": \"1\"}'",
                     "composio execute LINKEDIN_DELETE_POST -d '{}'",
                     "composio execute LINKEDIN_DELETE_COMMENT -d '{}'",
                     "composio execute LINKEDIN_DELETE_LINKED_IN_POST -d '{}'",
                     "curl -X POST https://api.x.com/2/users/1/likes -d '{}'",
                     "curl -X POST https://api.x.com/2/users/1/retweets -d '{}'")
        import channels
        for slug in (channels.X_LIKE_SLUG, channels.X_UNLIKE_SLUG, channels.X_REPOST_SLUG, channels.X_UNREPOST_SLUG,
                     channels.X_DELETE_SLUG, channels.LINKEDIN_DELETE_SLUG, channels.LINKEDIN_DELETE_COMMENT_SLUG):
            self.assertNotIn(slug, g.COMPOSIO_READ_SLUGS, f"{slug} is a write and may never join the read list")
            self.refused(f"composio execute {slug} -d '{{}}'")
        self.assertIn(channels.X_ME_SLUG, g.COMPOSIO_READ_SLUGS, "asking who the account is stays a read")
        # the engine's own senders pass: every send they make is channels.send()'s
        self.passes(SCRIPTS + "reactions.py send-due --live",
                    SCRIPTS + "reactions.py plan",
                    SCRIPTS + "control.py start")

    def test_composio_discovery_passes(self):
        self.passes("composio search post a tweet", "composio link twitter --alias acme-x",
                    "composio connections list", "composio --version",
                    "composio execute TWITTER_RECENT_SEARCH -d '{\"q\": \"see https://api.x.com/2/tweets\"}'",
                    "composio proxy https://api.x.com/2/users/me -d '{}' -X GET",
                    "composio execute TWITTER_CREATION_OF_A_POST --get-schema",
                    "composio execute LINKEDIN_CREATE_LINKED_IN_POST --dry-run -d '{}'")

    def test_composio_proxy_get_only_for_channels(self):
        self.passes("composio proxy https://api.x.com/2/users/me",
                    "composio proxy https://api.x.com/2/users/me -X GET",
                    "composio proxy https://api.linkedin.com/v2/me --request=GET",
                    "composio proxy https://api.github.com/repos/a/b -X POST")
        self.refused("composio proxy https://api.x.com/2/tweets -X POST -d '{}'",
                     "composio proxy https://api.x.com/2/tweets -d '{}'",
                     "composio proxy https://api.linkedin.com/rest/posts --method=DELETE",
                     "composio proxy https://api.linkedin.com/rest/posts -XPUT",
                     "composio proxy https://api.telegram.org/bot/sendMessage -X POST",
                     "composio proxy --toolkit twitter /2/tweets -X POST")

    def test_composio_rest_api_by_hand(self):
        self.refused("curl -X POST https://backend.composio.dev/api/v3.1/tools/execute/TWITTER_CREATION_OF_A_POST -d '{}'",
                     "curl https://backend.composio.dev/api/v3.1/tools/execute/LINKEDIN_CREATE_LINKED_IN_POST -d '{}'",
                     "curl https://backend.composio.dev/api/v3.1/tools/execute/proxy -d '{\"method\": \"POST\"}'")
        self.passes("curl https://backend.composio.dev/api/v3.1/tools/execute/TWITTER_RECENT_SEARCH -d '{}'",
                    "curl https://backend.composio.dev/api/v3.1/tools/execute/proxy -d '{\"method\": \"GET\"}'",
                    "curl https://backend.composio.dev/api/v3.1/tools/execute/GITHUB_CREATE_AN_ISSUE -d '{}'",
                    "curl https://backend.composio.dev/api/v3.1/connected_accounts")

    def test_composio_run_is_refused(self):
        self.refused("composio run script.ts", "composio --verbose run ./post.ts")

    def test_composio_word_elsewhere_is_not_the_cli(self):
        self.passes("engine setup composio acme",
                    "grep -rn 'composio run' docs | head",
                    "echo composio execute TWITTER_CREATION_OF_A_POST")

    def test_segments_are_judged_apart(self):
        # a read on one segment does not launder a write on another
        self.refused("npx xurl auth status; npx xurl post hi",
                     "composio search x && composio run s.ts")
        self.passes("npx xurl auth status && git status")

    def test_prose_in_heredocs_is_not_a_write(self):
        self.passes("python3 - <<'PY'\ns = 'xurl post is refused; composio run too; composio execute TWITTER_CREATION_OF_A_POST'\nPY\n",
                    "cat > README.md <<'EOF'\ncomposio run\nEOF")
        self.refused("cat > x <<'EOF'\nhi\nEOF\nnpx xurl post hi")

    def test_unparseable_command_does_not_raise(self):
        self.assertIsNone(g.verdict("composio execute 'unbalanced", {}))
        self.assertIsNotNone(g.verdict("composio run 'unbalanced", {}))


class Main(unittest.TestCase):
    def run_hook(self, payload):
        old_stdin = sys.stdin
        sys.stdin = io.StringIO(payload)
        err = io.StringIO()
        try:
            with redirect_stderr(err):
                rc = g.main()
        finally:
            sys.stdin = old_stdin
        return rc, err.getvalue()

    def test_blocks_with_exit_2(self):
        rc, err = self.run_hook(json.dumps({"tool_name": "Bash", "tool_input": {"command": "npx xurl post hi"}}))
        self.assertEqual(rc, 2)
        self.assertIn("refused", err)
        rc, _ = self.run_hook(json.dumps({"tool_name": "Bash", "tool_input": {"command": "composio run x.ts"}}))
        self.assertEqual(rc, 2)

    def test_other_tools_and_bad_input_pass(self):
        self.assertEqual(self.run_hook(json.dumps({"tool_name": "Write", "tool_input": {"file_path": "x"}}))[0], 0)
        for bad in ("not json", "", "[]", "null", json.dumps({"tool_name": "Bash", "tool_input": "oops"}),
                    json.dumps({"tool_name": "Bash"})):
            self.assertEqual(self.run_hook(bad)[0], 0, bad)
        self.assertEqual(self.run_hook(json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}))[0], 0)

    def test_reads_exit_0(self):
        rc, _ = self.run_hook(json.dumps({"tool_name": "Bash", "tool_input": {"command": "composio execute TWITTER_RECENT_SEARCH -d '{}'"}}))
        self.assertEqual(rc, 0)


class Instagram(unittest.TestCase):
    """The Motion plugin's `post` skill publishes with `composio execute INSTAGRAM_*`. The
    engine has no Instagram channel, so channels.send() never sees that send and, until
    2026-11-13, neither did this hook."""

    def test_instagram_executes_and_writes_are_refused(self):
        for cmd in ("composio execute INSTAGRAM_POST_IG_USER_MEDIA -d @caption-ig.json",
                    "composio execute INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH -d '{}'",
                    "npx composio execute INSTAGRAM_GET_USER_INFO -d '{}'",
                    "composio proxy -X POST https://graph.facebook.com/v21.0/1/media",
                    "composio proxy instagram -X POST /media",
                    "curl -X POST https://backend.composio.dev/api/v3.1/tools/execute/INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH -d '{}'"):
            why = g.verdict(cmd, {})
            self.assertIsNotNone(why, cmd)
            self.assertIn("channels.send()", why)

    def test_instagram_discovery_and_proxy_reads_pass(self):
        for cmd in ("composio link instagram", "composio connections list",
                    "composio execute INSTAGRAM_GET_USER_INFO --get-schema",
                    "composio proxy https://graph.facebook.com/v21.0/me"):
            self.assertIsNone(g.verdict(cmd, {}), cmd)


if __name__ == "__main__":
    unittest.main()
