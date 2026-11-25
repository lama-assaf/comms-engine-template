#!/usr/bin/env python3
"""
guard_posting.py - refuses a raw platform write that bypasses channels.send().

Every send the engine makes passes `channels.send()`, whoever calls it (the
scheduled sender, the dashboard, an agent), and `channels.send()` refuses unless
every check passes: the deterministic gate, current cites, the stealth list,
hold for review, the stream's own account and pair rules, quiet hours and caps,
and the kind of send. So this hook no longer judges who runs a command or which
engine script it names. It keeps one job: stopping a command that writes to a
platform directly, around the gate.

Claude Code runs it before every Bash call (the comms-engine plugin's
hooks/hooks.json). It reads the hook's JSON on stdin and exits 2, with the
reason on stderr, when the command is one of these:

  - `xurl [flags] post|reply|delete`            an X post, reply or delete through xurl
  - curl/wget/http to api.linkedin.com or api.x.com / api.twitter.com with a write
    (a non-GET method, a body, or the post endpoints)
  - `publish.py ... --webhook` or `engine publish ... --webhook`
                                                a POST to the site's rebuild hook
  - `composio execute <SLUG>` in the channel toolkits (TWITTER, LINKEDIN, TELEGRAM,
    DISCORDBOT, INSTAGRAM) unless SLUG is in COMPOSIO_READ_SLUGS: an exact allowlist, so
    a new or unknown slug is refused until it is listed here. Instagram is guarded
    although the engine has no Instagram channel: the Motion plugin's `post` skill
    publishes there with `composio execute INSTAGRAM_*`, and a channel channels.send()
    does not know is a send nothing has checked
  - `composio proxy` with any method but GET, against a channel host or toolkit
  - `composio run` (a script can call any tool)
  - curl/wget/http to backend.composio.dev `/tools/execute/<SLUG>` for a channel slug
    not in COMPOSIO_READ_SLUGS, or to `/tools/execute/proxy` with a non-GET method: the
    engine's own client (channels.py) makes these calls inside channels.send(), where no
    hook reaches, so a command that makes one by hand is a send around the gate

Let through: `composio` discovery (search, link, connections, `--get-schema`,
`--dry-run`), `composio execute` of other toolkits, `composio proxy` GETs, and any
command that runs an engine script (`engine <name>`, or the older
`python3 .../scripts/*.py`, judged the same): channels.py's own
subprocesses never reach this hook, and the checks live in channels.send().

It judges the command, not prose: heredoc bodies are stripped before matching, and
the command is judged segment by segment (`;`, `&&`, `||`, `|`, newlines). A
`composio` is read only where a command starts (after env assignments and
`npx`/`env`/`sudo`-style wrappers), so `engine.py setup composio acme` is not it.

Known limit: the hook reads the command text. A write wrapped in another
interpreter (`python3 -c "subprocess.run(['xurl','post',...])"`, `bash -c`, a script
file that itself posts) is not seen here; channels.send() and the keychain are what
stand behind it.

Exit 2 blocks the call and the model reads the reason; exit 0 lets it through.
A hook that cannot read its input must not block the session: any parse error
exits 0. Reads only; writes nothing.

  echo '{"tool_name":"Bash","tool_input":{"command":"npx xurl post hi"}}' | python3 guard_posting.py; echo $?
"""
from __future__ import annotations  # the `str | None` hints parse on macOS's python3 3.9

import json
import os
import re
import shlex
import sys

#: the toolkits whose tools post, reply or message on a channel
COMPOSIO_GUARDED = ("TWITTER", "LINKEDIN", "TELEGRAM", "DISCORDBOT", "INSTAGRAM")
#: the only slugs of those toolkits that read; anything else in them is refused
COMPOSIO_READ_SLUGS = frozenset({
    "TWITTER_RECENT_SEARCH",
    "TWITTER_SEARCH_RECENT_COUNTS",
    "TWITTER_GET_POST_ANALYTICS",
    "TWITTER_USER_LOOKUP_ME",
    "TWITTER_USER_MENTIONS",
    "TWITTER_POST_LOOKUP_BY_POST_ID",
    "LINKEDIN_GET_MY_INFO",
    "LINKEDIN_GET_SHARE_STATS",
})
#: `composio` subcommands that only look, link or describe
COMPOSIO_DISCOVERY = frozenset({
    "search", "link", "connections", "login", "logout", "whoami", "version", "upgrade",
    "tools", "toolkits", "triggers", "listen", "dev", "init", "help", "info", "manage",
})
CHANNEL_HOSTS = ("api.x.com", "api.twitter.com", "api.linkedin.com", "api.telegram.org",
                 "discord.com", "discordapp.com", "graph.facebook.com", "graph.instagram.com")
CHANNEL_TOOLKIT_WORDS = ("twitter", "linkedin", "telegram", "discordbot", "discord", "instagram")
WRAPPERS = frozenset({"npx", "bunx", "pnpx", "pnpm", "yarn", "env", "sudo", "time", "command",
                      "exec", "nohup", "dlx"})

FLAGS = r"(?:\s+-{1,2}[\w-]+(?:[= ]\S+)?)*"  # `--app acme`, `-y`, `--stream=acme`
Q = r"['\"]?"  # the subcommand may be quoted: xurl 'post'
WRITE_METHOD = r"(?:POST|PUT|PATCH|DELETE)"
SEND_PATTERNS = (
    (re.compile(r"\bxurl\b" + FLAGS + r"\s+" + Q + r"(post|reply|delete)\b", re.I), "an X post, reply or delete through xurl"),
    (re.compile(r"(?:\bpublish\.py\b|(?:^|[\s/])engine\s+publish\b)[^\n;|&]*\s--webhook\b", re.I),
     "a POST to the site's rebuild webhook (publish.py --webhook)"),
    (re.compile(r"\b(curl|wget|https?|xh)\s[^\n;|&]*api\.linkedin\.com/(rest|v2)/(posts|socialActions|ugcPosts|shares)", re.I), "a LinkedIn API write"),
    (re.compile(r"\b(curl|wget|https?|xh)\s[^\n;|&]*api\.(x|twitter)\.com/2/tweets", re.I), "an X API write"),
)
HTTP_TOOL = re.compile(r"\b(curl|wget|https?|xh)\s", re.I)  # a command word, not the scheme of a URL
COMPOSIO_API_EXEC = re.compile(r"backend\.composio\.dev/api/v[\w.]+/tools/execute/([A-Za-z0-9_%]+)", re.I)
HTTP_HOST = re.compile(r"api\.(?:linkedin|x|twitter)\.com", re.I)
HTTP_WRITE = re.compile(
    r"(?:\s-X\s*['\"]?" + WRITE_METHOD + r"|\s--(?:request|method)[= ]\s*['\"]?" + WRITE_METHOD
    + r"|\s(?:-d|-F|-T|--data[\w-]*|--form[\w-]*|--json|--post-data|--post-file|--body-data|--upload-file)\b"
    + r"|\s" + WRITE_METHOD + r"\s+['\"]?https?://)", re.I)
HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?\n\s*\1\s*(?=\n|$)", re.S)
SEGMENT = re.compile(r"\s*(?:;|&&|\|\||\||\n)\s*")
SLUG_SHAPE = re.compile(r"^[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+$")
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

RULE = ("Every send goes through channels.send() with its checks (gate, cites, stealth list, hold "
        "for review, account and pair rules, quiet hours and caps); a raw platform write skips them.")


def strip_heredocs(command: str) -> str:
    """The command with every here-document body removed: documentation that
    quotes a sending command is not a sending command."""
    return HEREDOC.sub("<<HEREDOC>", command)


def segments(code: str):
    """The command split at `;`, `&&`, `||`, `|` and newlines: each piece is judged on its own."""
    return [seg for seg in SEGMENT.split(code) if seg and seg.strip()]


def _tokens(seg: str):
    try:
        return shlex.split(seg)
    except ValueError:
        return seg.split()


def _composio_args(tokens):
    """The words after `composio` when this segment starts the composio CLI, else None."""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        base = os.path.basename(tok).lower()
        if ENV_ASSIGN.match(tok) or tok.startswith("-"):
            i += 1
        elif base in WRAPPERS:
            i += 1
        elif base in ("composio", "composio-cli") or "@composio/cli" in tok:
            return tokens[i + 1:]
        else:
            return None
    return None


def _proxy_method(args):
    """The HTTP method a `composio proxy` call uses: -X/--request/--method, else POST with a body, else GET."""
    method = None
    body = False
    for n, tok in enumerate(args):
        low = tok.lower()
        m = re.match(r"^-x(.+)$", tok, re.I) if not tok.startswith("--") else None
        if tok in ("-X", "--request", "--method", "-x") and n + 1 < len(args):
            method = args[n + 1]
        elif low.startswith(("--request=", "--method=")):
            method = tok.split("=", 1)[1]
        elif m:
            method = m.group(1).lstrip("=")
        elif tok in ("-d", "-F", "--json") or low.startswith(("--data", "--form", "--json=", "--body")):
            body = True
    return (method or ("POST" if body else "GET")).upper()


def composio_verdict(args) -> str | None:
    """Why this `composio` call is refused (args are the words after `composio`), or None."""
    for n, tok in enumerate(args):
        if tok.startswith("-"):
            continue
        if tok.lower() in COMPOSIO_DISCOVERY:
            return None
        rest = args[n + 1:]
        if tok == "run":
            return "composio run (a script can call any tool, write tools included)"
        if tok == "proxy":
            channel = any(h in t.lower() for t in rest for h in CHANNEL_HOSTS) or \
                any(t.lower() in CHANNEL_TOOLKIT_WORDS for t in rest)
            method = _proxy_method(rest)
            if channel and method != "GET":
                return f"a {method} through composio proxy to a channel host"
            return None
        if tok == "execute":
            if any(t in ("--get-schema", "--dry-run", "--help", "-h") for t in rest):
                return None
            for t in rest:
                if t.startswith("-") or not SLUG_SHAPE.match(t):
                    continue
                slug = t.upper()
                if slug.split("_", 1)[0] in COMPOSIO_GUARDED and slug not in COMPOSIO_READ_SLUGS:
                    return f"composio execute {slug}, which is not a listed read slug"
            return None
    return None


def segment_verdict(seg: str) -> str | None:
    for pattern, what in SEND_PATTERNS:
        if pattern.search(seg) and not (what.startswith("a POST to the site") and re.search(r"(^|\s)--dry(-run)?(\s|$)", seg)):
            return what
    if HTTP_TOOL.search(seg) and HTTP_HOST.search(seg) and HTTP_WRITE.search(seg):
        return "a write to a platform API with curl/wget/http"
    if HTTP_TOOL.search(seg):
        m = COMPOSIO_API_EXEC.search(seg)
        if m:
            slug = m.group(1).upper()
            if slug == "PROXY":
                if re.search(r'"method"\s*:\s*"?' + WRITE_METHOD, seg, re.I):
                    return "a non-GET proxy call to the Composio API"
            elif slug.split("_", 1)[0] in COMPOSIO_GUARDED and slug not in COMPOSIO_READ_SLUGS:
                return f"a Composio API execute of {slug}, which is not a listed read slug"
    args = _composio_args(_tokens(seg))
    if args is not None:
        return composio_verdict(args)
    return None


def verdict(command: str, env: dict | None = None) -> str | None:
    """The reason this command is refused, or None when it may run. `env` is unused
    (who runs a command no longer matters); the argument stays so callers keep working."""
    if not command:
        return None
    code = strip_heredocs(command)
    for seg in segments(code):
        what = segment_verdict(seg)
        if what:
            return f"refused: this command is a raw platform write ({what}) that bypasses channels.send(). {RULE}"
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
        if data.get("tool_name") != "Bash":
            return 0
        command = str((data.get("tool_input") or {}).get("command") or "")
        why = verdict(command, os.environ)
    except Exception:  # a hook that cannot judge must not block the session
        return 0
    if why:
        print(why, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
