#!/usr/bin/env python3
"""
channels.py - the one connector module for the official channels (PLAN-channels-hosting, C2).

This step carries only the call mechanism. Everything that reaches Composio goes
through `_http`, an HTTPS client (stdlib `urllib`) for https://backend.composio.dev
that sends the stream's project API key in the `x-api-key` header and nowhere else.
The composio CLI is not used: it was found to ignore COMPOSIO_API_KEY and run on the
machine's stored login, so it could not be pointed at a stream's project. Tools run
through `POST /api/v3.1/tools/execute/{slug}`; the connected account is found by listing
`GET /api/v3.1/connected_accounts`. The engine stays stdlib-only.

One Composio project (and key) per stream: a connected account is named by an alias
`<stream>-<channel>` (`acme-x`, `acme-linkedin`), or, where the dashboard offers no alias,
by an id recorded as `params.channels.account_id.<stream>.<channel>`. `account_for`
resolves an alias only inside the stream that asks, and refuses any other stream's
alias, so a run for one stream cannot reach another stream's account.

`dry_run=True` plans the call and checks the account (a read), and makes no execute call.

`send()` (below) is the only code that calls a write driver. It refuses unless every
check passes, writes `state/send-ledger.json` before each real send, and appends one
line per attempt, sent or refused, to `state/sends.jsonl`.
"""
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zoneinfo

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
sys.path.insert(0, HERE)

import memory  # noqa: E402

ENGINE = os.path.dirname(HERE)
STATE = paths.state()
LEDGER_FILE = "send-ledger.json"
SENDS_LOG = "sends.jsonl"
LIFECYCLE_FILE = "lifecycle.jsonl"
ACTS_FILE = "acts.jsonl"

TIMEOUT = 120

# channel name (lower-case) -> the Composio toolkit prefix of its slugs
TOOLKITS = {"x": "TWITTER", "linkedin": "LINKEDIN", "telegram": "TELEGRAM", "discord": "DISCORDBOT"}


class ChannelError(RuntimeError):
    """A channel call that could not be made or did not succeed."""


class MissingComposioKey(ChannelError):
    """A stream has no Composio API key of its own; nothing falls back to a stored login."""


class CrossStreamAccount(ChannelError):
    """An account that belongs to another stream was asked for."""


def channel_key(channel):
    key = (channel or "").strip().lower()
    if key not in TOOLKITS:
        raise ChannelError(f"unknown channel {channel!r}; known: {sorted(TOOLKITS)}")
    return key


def alias_for(stream, channel):
    """The connected-account alias of a stream's channel: `<stream>-<channel>`."""
    memory.stream(stream)  # an unknown stream raises; nothing defaults
    return f"{(stream or '').strip().lower()}-{channel_key(channel)}"


def account_for(stream, channel, account=None):
    """The account selector for a stream's channel, resolved within that stream only.

    No `account` gives the stream's own alias. An explicit `account` must be that
    same alias; any other value (another stream's alias, a bare account id) is
    refused, because it cannot be shown to belong to the stream.
    """
    own = alias_for(stream, channel)
    if account is None or account == own:
        return own
    raise CrossStreamAccount(f"account {account!r} is not {stream!r}'s {channel} account ({own!r})")


KEY_NAME = "COMPOSIO_API_KEY"


def composio_key(stream):
    """The stream's Composio API key, resolved through scripts/secrets.py (environment, then keychain).

    The root stream keeps the bare name `COMPOSIO_API_KEY`; every other stream resolves its own
    scoped one (`<STREAM>_COMPOSIO_API_KEY`, keychain account `<stream>/COMPOSIO_API_KEY`). A
    stream without a key raises `ChannelError` (nothing falls back to a stored login). The
    message names the secret, never a value.
    """
    import secrets as secrets_mod
    value = secrets_mod.get_secret(KEY_NAME, required=False, stream=stream)
    if not value:
        scoped = secrets_mod.scoped_name(KEY_NAME, stream)
        raise MissingComposioKey(f"no Composio API key for stream {stream!r} ({scoped} is not set in the environment "
                           f"or the keychain); no other login is used")
    return value


def composio_setup(stream):
    """`(set_up, why)`: whether the stream is set up for Composio.

    Set up means it has a resolvable `COMPOSIO_API_KEY` (and so can list the accounts it has
    linked), or, with no key, the owner has configured something that says it should: a
    workspace recorded as `channels.composio_org.<stream>` or a `composio` write or X read
    driver. A stream that is neither is not set up: Composio checks skip it, and its missing
    key is no fault. A configured stream with no key stays a fault."""
    try:
        composio_key(stream)
        return True, "has a Composio API key"
    except MissingComposioKey:
        pass
    if composio_org(stream):
        return True, "a Composio workspace is recorded for it"
    if "composio" in (write_driver(stream)[0], x_read_driver(stream)[0], x_own_driver(stream)[0]):
        return True, "it is configured for the composio driver"
    return False, "no Composio API key and nothing configured for Composio"


def not_set_up_line(stream):
    """The one green doctor line of a stream that is not set up for Composio."""
    return {"check": f"composio {stream}", "ok": True, "tail": "not set up for Composio (no API key, no workspace or composio driver configured); skipped"}


API_BASE = "https://backend.composio.dev"
USER_AGENT = "comms-engine/1.0"
#: the urllib opener tests inject; None builds a real one per call
_OPENER = None
#: `{(stream, key fingerprint): (monotonic time, connections)}`: the account list, kept briefly
_CONN_CACHE = {}
CONN_TTL = 120.0


def clear_cache():
    _CONN_CACHE.clear()


def _scrub(text, key):
    """`text` with the key removed (and a note that it was): no error message carries the secret."""
    text = str(text)
    return text.replace(key, "[key]") if key else text


def _http(stream, method, path, query=None, body=None, opener=None):
    """One call to the Composio API with the stream's key; returns the parsed JSON.

    The key is read through `composio_key` (secrets.py) and sent only as the `x-api-key`
    header: never in the URL, a log line or an exception message (errors are scrubbed).
    Raises MissingComposioKey without a key, ChannelError for a failed call or non-JSON reply."""
    key = composio_key(stream)
    url = API_BASE + path
    if query:
        url += "?" + urllib.parse.urlencode([(k, v) for k, vs in query.items() for v in (vs if isinstance(vs, (list, tuple)) else [vs])])
    data = json.dumps(body, sort_keys=True).encode("utf-8") if body is not None else None
    headers = {"x-api-key": key, "Accept": "application/json", "User-Agent": USER_AGENT}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    label = f"composio {method} {path}"
    try:
        resp = (opener or _OPENER or urllib.request.build_opener()).open(req, timeout=TIMEOUT)
        raw = resp.read()
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")[-300:].strip()
        except Exception:  # noqa: BLE001
            detail = ""
        finally:
            exc.close()
        raise ChannelError(_scrub(f"{label} failed: HTTP {exc.code} {detail}".strip(), key)) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ChannelError(_scrub(f"{label} did not run: {getattr(exc, 'reason', exc)}", key)) from None
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    try:
        return json.loads(text)
    except ValueError:
        raise ChannelError(_scrub(f"{label} returned no JSON: {text[-200:].strip()!r}", key)) from None


def _paged(stream, path, query=None, opener=None, max_pages=20):
    """Every item of a cursor-paged list endpoint."""
    items, cursor = [], None
    for _ in range(max_pages):
        q = dict(query or {}, limit=100)
        if cursor:
            q["cursor"] = cursor
        page = _http(stream, "GET", path, query=q, opener=opener)
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            raise ChannelError(f"composio GET {path} returned an unexpected shape")
        items.extend(i for i in page["items"] if isinstance(i, dict))
        cursor = page.get("next_cursor")
        if not cursor:
            break
    return items


def _fingerprint(stream):
    return hashlib.sha256(composio_key(stream).encode("utf-8")).hexdigest()[:12]


def recorded_account_id(stream, channel):
    """The connected-account id recorded for a stream's channel (`params.channels.account_id.<stream>.<channel>`), or ''."""
    import config
    return str(config.cfg(f"channels.account_id.{stream.strip().lower()}.{channel_key(channel)}", "") or "").strip()


def recorded_auth_config(stream, channel):
    """The auth config id recorded for a stream's channel (`params.channels.auth_config.<stream>.<channel>`), or ''."""
    import config
    return str(config.cfg(f"channels.auth_config.{stream.strip().lower()}.{channel_key(channel)}", "") or "").strip()


def resolve_account(stream, channel, account=None, conns=None):
    """The connected account (`{id, alias, status, auth_config_id, user_id, ...}`) a stream's channel acts as.

    The selector is checked first (`account_for`: another stream's alias or a bare id is refused).
    The account is the one in the stream's own project whose alias is `<stream>-<channel>`,
    else the one whose id is recorded in engine.json; none found raises ChannelError."""
    own = account_for(stream, channel, account)
    key = channel_key(channel)
    conns = conns if conns is not None else connections(stream)
    found = account_status(stream, key, conns)
    if found is None:
        rec = recorded_account_id(stream, key)
        if rec:
            found = next((a for a in conns.get(LINK_TOOLKITS[key]) or [] if a.get("id") == rec), None)
            if found is None:
                raise ChannelError(f"the recorded {key} account {rec!r} for {stream!r} is not in its Composio project "
                                   f"(params.channels.account_id.{stream}.{key})")
    if found is None:
        raise ChannelError(f"no {key} account {own!r} in {stream!r}'s Composio project; connect one: engine.py setup composio {stream}")
    return found


def _execute(stream, channel, slug, args=None, dry_run=False, account=None):
    """Run one Composio tool for a stream's channel and return its parsed JSON.

    The only function that executes a tool. Raises `CrossStreamAccount` for another stream's
    account and `ChannelError` for a missing account, a failed call, a reply that is not JSON, or
    a result that reports `successful: false`. `dry_run` resolves the account and returns the plan
    (`{"dry_run": True, "slug", "account", "arguments"}`) without calling execute.
    """
    key = channel_key(channel)
    slug = (slug or "").strip().upper()
    if not slug.startswith(TOOLKITS[key] + "_"):
        raise ChannelError(f"{slug!r} is not a {TOOLKITS[key]} tool; channel {channel!r} cannot call it")
    account_for(stream, channel, account)  # refuses another stream's account before any call
    acct = resolve_account(stream, channel, account)
    body = {"connected_account_id": acct["id"], "arguments": args or {}}
    if acct.get("user_id"):
        body["user_id"] = acct["user_id"]
    if dry_run:
        return {"dry_run": True, "slug": slug, "account": acct["id"], "alias": acct.get("alias"), "arguments": args or {}}
    result = _http(stream, "POST", f"/api/v3.1/tools/execute/{urllib.parse.quote(slug, safe='')}", body=body)
    if isinstance(result, dict) and result.get("successful") is False:
        raise ChannelError(_scrub(f"composio execute {slug} was not successful: {str(result.get('error'))[:300]}", composio_key(stream)))
    return result


# --- what is connected: setup and doctor read these (engine.py setup composio / doctor) ---

#: channel name (lower-case) -> the Composio toolkit slug the connected-accounts list reports
LINK_TOOLKITS = {key: prefix.lower() for key, prefix in TOOLKITS.items()}
#: channel name -> the tool that answers "which account is this", for the handle check
WHOAMI = {"x": "TWITTER_USER_LOOKUP_ME", "linkedin": "LINKEDIN_GET_MY_INFO"}
#: the stream's X read driver when `channels.x_read.<stream>` is not set. twitterapi.io stays
#: the default until the owner has seen the official API's price (plan step L0).
DEFAULT_X_READ = "twitterapi"
X_READ_DRIVERS = ("twitterapi", "composio")
#: the stream's driver for the X reads on its own accounts (our posts' numbers, the mentions and
#: replies) when `channels.x_own.<stream>` is not set. `x_read` covers listening and the standing
#: monitors; this is the second read class, with its own price sign-off.
DEFAULT_X_OWN = "twitterapi"
X_OWN_DRIVERS = ("twitterapi", "composio")
#: the stream's write driver when `channels.write_driver.<stream>` is not set. `native` is the
#: sender's own xurl and LinkedIn code, wrapped as drivers by autopilot.py; Composio is selected
#: by that one setting and never by default (no account is linked until the owner does it).
DEFAULT_WRITE = "native"
WRITE_DRIVERS = ("native", "composio")


def connections(stream, opener=None, fresh=False):
    """The connected accounts of the stream's Composio project (its key) as
    `{toolkit: [{id, status, alias, auth_config_id, user_id}]}`, from `GET /api/v3.1/connected_accounts`;
    raises ChannelError, also when the stream has no key. Kept for `CONN_TTL` seconds unless `fresh`."""
    import time
    ck = (stream, _fingerprint(stream))
    hit = _CONN_CACHE.get(ck)
    if hit and not fresh and opener is None and time.monotonic() - hit[0] < CONN_TTL:
        return hit[1]
    out = {}
    for item in _paged(stream, "/api/v3.1/connected_accounts", opener=opener):
        slug = str((item.get("toolkit") or {}).get("slug") or "").lower()
        out.setdefault(slug, []).append({
            "id": item.get("id"), "status": item.get("status"), "alias": item.get("alias"),
            "word_id": item.get("word_id"), "user_id": item.get("user_id"),
            "auth_config_id": (item.get("auth_config") or {}).get("id")})
    _CONN_CACHE[ck] = (time.monotonic(), out)
    return out


def auth_configs(stream, opener=None):
    """The auth configs of the stream's Composio project as `[{id, toolkit, name, status, type, connections}]`,
    from `GET /api/v3.1/auth_configs`; raises ChannelError, also when the stream has no key."""
    return [{"id": i.get("id"), "toolkit": str((i.get("toolkit") or {}).get("slug") or "").lower(), "name": i.get("name"),
             "status": i.get("status"), "type": i.get("type"), "connections": i.get("no_of_connections")}
            for i in _paged(stream, "/api/v3.1/auth_configs", opener=opener)]


def account_status(stream, channel, conns):
    """The connected account whose alias is the stream's `<stream>-<channel>`, or the one recorded as
    `params.channels.account_id.<stream>.<channel>`, or None."""
    alias = alias_for(stream, channel)
    accounts = conns.get(LINK_TOOLKITS[channel_key(channel)]) or []
    for acct in accounts:
        if (acct.get("alias") or "").strip().lower() == alias:
            return acct
    recorded = recorded_account_id(stream, channel)
    if recorded:  # the dashboard gave the account no alias: the id recorded in engine.json names it
        for acct in accounts:
            if acct.get("id") == recorded:
                return acct
    return None


def handle_of(cell):
    """The handle in a channel entry's text: `@acme_x`, a profile URL or slug; None when it is 'collect'."""
    text = (cell or "").strip()
    if not text or "collect" in text.lower():
        return None
    m = re.search(r"@\w+", text)
    if m:
        return m.group(0)
    m = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/\S+", text)
    return m.group(0) if m else None


def stream_channels(stream):
    """`[(channel key, handle or None)]` for the channels in the stream's `streams.md` cell.

    The cell is `;`-separated entries (`X @acme_x; LinkedIn (slug to collect); website ...`).
    An entry counts when it opens with a channel Composio serves; the website and an
    unfilled `—` cell are not channels.
    """
    cell = memory.stream(stream).get("channels") or ""
    out = []
    for entry in cell.split(";"):
        entry = entry.strip()
        word = re.split(r"[\s(]", entry, maxsplit=1)[0].lower() if entry else ""
        if word in TOOLKITS:
            out.append((word, handle_of(entry[len(word):])))
    return out


def x_read_driver(stream):
    """`(driver, why)`: the stream's X read driver, from `channels.x_read.<stream>` in engine.json."""
    import config
    memory.stream(stream)
    driver = str(config.cfg(f"channels.x_read.{stream.strip().lower()}", DEFAULT_X_READ) or DEFAULT_X_READ).strip().lower()
    if driver not in X_READ_DRIVERS:
        return driver, f"unknown driver; one of {', '.join(X_READ_DRIVERS)}"
    return driver, None


def x_own_driver(stream):
    """`(driver, why)`: the driver for X reads on the stream's own accounts, from `channels.x_own.<stream>`."""
    import config
    memory.stream(stream)
    driver = str(config.cfg(f"channels.x_own.{stream.strip().lower()}", DEFAULT_X_OWN) or DEFAULT_X_OWN).strip().lower()
    if driver not in X_OWN_DRIVERS:
        return driver, f"unknown driver; one of {', '.join(X_OWN_DRIVERS)}"
    return driver, None


def write_driver(stream):
    """`(driver, why)`: the stream's write driver, from `channels.write_driver.<stream>` in engine.json."""
    import config
    memory.stream(stream)
    driver = str(config.cfg(f"channels.write_driver.{stream.strip().lower()}", DEFAULT_WRITE) or DEFAULT_WRITE).strip().lower()
    if driver not in WRITE_DRIVERS:
        return driver, f"unknown driver; one of {', '.join(WRITE_DRIVERS)}"
    return driver, None


def _find_text(value, key):
    """The first string stored under `key` anywhere in a nested result."""
    if isinstance(value, dict):
        if isinstance(value.get(key), str):
            return value[key]
        for v in value.values():
            found = _find_text(v, key)
            if found:
                return found
    elif isinstance(value, list):
        for v in value:
            found = _find_text(v, key)
            if found:
                return found
    return None


def live_handle(stream, channel):
    """The handle the connected account reports for itself (X: its username), or None where the channel gives none."""
    key = channel_key(channel)
    if key not in WHOAMI:
        return None
    result = _execute(stream, key, WHOAMI[key])
    if key == "x":
        name = _find_text(result, "username")
        return "@" + name.lstrip("@") if name else None
    return json.dumps(result, sort_keys=True)  # LinkedIn: the profile text, searched for the recorded slug


def link_plan(stream, conns=None):
    """`[(channel, alias, auth_config_id, linked)]` for each channel of the stream: what the dashboard needs.

    `auth_config_id` is the one recorded as `params.channels.auth_config.<stream>.<channel>` ('' when none)."""
    conns = conns if conns is not None else connections(stream)
    plan = []
    for key, _handle in stream_channels(stream):
        linked = account_status(stream, key, conns) is not None or \
            bool(recorded_account_id(stream, key) and any(a.get("id") == recorded_account_id(stream, key)
                                                        for a in conns.get(LINK_TOOLKITS[key]) or []))
        plan.append((key, alias_for(stream, key), recorded_auth_config(stream, key), linked))
    return plan


def stream_status(stream, conns=None, probe_handle=True):
    """Doctor lines for one stream, `[{check, ok, tail}]`, one per channel check.

    connected / active / handle for each channel in the stream's cell. A channel with no
    account under its alias yet is reported ok with the command that links it: sending
    still has the direct drivers until the parity period ends, so an unlinked channel is
    news, not a fault. A linked account that is not ACTIVE, or whose live handle differs
    from the cell, is a fault. Where the account list cannot be read, one FAIL line says so.
    """
    chans = stream_channels(stream)
    if not chans:
        return []
    lines = []
    if conns is None:
        try:
            conns = connections(stream)
        except MissingComposioKey as exc:
            if not composio_setup(stream)[0]:
                return []  # not set up for Composio: nothing to check
            return [{"check": f"composio {stream} api key", "ok": False, "tail": str(exc)[:300]}]
        except ChannelError as exc:
            return [{"check": f"composio {stream} connections", "ok": False, "tail": f"not readable: {str(exc)[:200]}"}]
    for key, recorded in chans:
        label = f"composio {stream}/{key}"
        acct = account_status(stream, key, conns)
        alias = alias_for(stream, key)
        if acct is None:
            lines.append({"check": f"{label} connected", "ok": True,
                          "tail": f"no account {alias!r} yet; link with: engine.py setup composio {stream}"})
            continue
        lines.append({"check": f"{label} connected", "ok": True, "tail": f"account {alias!r}"})
        status = str(acct.get("status") or "").upper()
        lines.append({"check": f"{label} active", "ok": status == "ACTIVE", "tail": f"status {status or 'unknown'}"})
        if status != "ACTIVE" or not probe_handle:
            continue
        if recorded is None:
            lines.append({"check": f"{label} handle", "ok": True, "tail": "no handle recorded in the channels cell"})
            continue
        if key not in WHOAMI:
            lines.append({"check": f"{label} handle", "ok": True, "tail": f"{recorded} recorded; this channel reports no handle to compare"})
            continue
        try:
            live = live_handle(stream, key)
        except ChannelError as exc:
            lines.append({"check": f"{label} handle", "ok": False, "tail": str(exc)[:200]})
            continue
        if key == "x":
            same = bool(live) and live.lower() == recorded.lower()
            lines.append({"check": f"{label} handle", "ok": same, "tail": f"{recorded} recorded, account says {live or 'nothing'}"})
        else:
            slug = recorded.rstrip("/").rsplit("/", 1)[-1].lower()
            same = bool(live) and slug in live.lower()
            lines.append({"check": f"{label} handle", "ok": same, "tail": f"{recorded} recorded, " + ("found in the account profile" if same else "not found in the account profile")})
    return lines


def composio_org(stream):
    """The workspace recorded for the stream (`params.channels.composio_org.<stream>`), or ''. A label only."""
    import config
    return str(config.cfg(f"channels.composio_org.{stream.strip().lower()}", "") or "").strip()


def auth_config_line(stream, configs=None):
    """The doctor line saying whether the stream's key can see the auth configs recorded for it.

    FAIL when a recorded `params.channels.auth_config.<stream>.<channel>` id is not in the project the
    key belongs to (the key is then another project's), when the list cannot be read, or when the key is
    missing. While none is recorded the line is ok and says so."""
    check = f"composio {stream} auth configs"
    recorded = [(k, recorded_auth_config(stream, k)) for k, _h in stream_channels(stream)]
    recorded = [(k, i) for k, i in recorded if i]
    try:
        seen = configs if configs is not None else auth_configs(stream)
    except MissingComposioKey as exc:
        if not composio_setup(stream)[0]:
            return not_set_up_line(stream)
        return {"check": f"composio {stream} api key", "ok": False, "tail": str(exc)[:300]}
    except ChannelError as exc:
        return {"check": check, "ok": not recorded, "tail": f"auth configs not readable with the key: {str(exc)[:200]}"}
    ids = {c.get("id") for c in seen}
    if not recorded:
        return {"check": check, "ok": True, "tail": f"the key sees {len(ids)} auth config(s); none recorded "
                f"(params.channels.auth_config.{stream}.<channel> in engine.json)"}
    missing = [f"{k} {i}" for k, i in recorded if i not in ids]
    if missing:
        return {"check": check, "ok": False,
                "tail": f"not visible to this key: {', '.join(missing)}; the key is not that project's ({len(ids)} auth config(s) seen)"}
    return {"check": check, "ok": True, "tail": "recorded: " + ", ".join(f"{k} {i}" for k, i in recorded) + " (all visible to the key)"}


def doctor_report():
    """Every composio doctor line: per stream whether its key sees the recorded auth configs, its channels and X read driver.

    Each stream is read with its own key (one workspace per stream). A stream that is not set up
    for Composio (no key, nothing configured for it) gets one green line and no other composio
    check; a configured stream with no key gets one FAIL line and no other composio read."""
    import secrets as secrets_mod
    lines = []
    unset = set()
    conns_by = {}
    for slug in memory.streams():
        if not stream_channels(slug):
            continue
        try:
            composio_key(slug)
        except MissingComposioKey as exc:
            if not composio_setup(slug)[0]:
                unset.add(slug)
                lines.append(not_set_up_line(slug))
                continue
            lines.append({"check": f"composio {slug} api key", "ok": False, "tail": str(exc)[:300]})
            continue
        lines.append(auth_config_line(slug))
        try:
            conns_by[slug] = connections(slug)
        except ChannelError as exc:
            lines.append({"check": f"composio {slug} connections", "ok": False, "tail": f"not readable: {str(exc)[:200]}"})
            continue
        lines.extend(stream_status(slug, conns_by[slug]))
    for slug in memory.streams():
        if not stream_channels(slug) or slug in unset:
            continue
        conns = conns_by.get(slug)
        driver, bad = x_read_driver(slug)
        if bad:
            lines.append({"check": f"composio {slug} x read driver", "ok": False, "tail": f"{driver}: {bad}"})
        elif driver == "twitterapi" or not price_signoff():
            have = bool(secrets_mod.get_secret("TWITTERAPI_IO_API_KEY", required=False))
            held = f" ({HELD_REASON}; configured: composio)" if driver == "composio" else ""
            lines.append({"check": f"composio {slug} x read driver", "ok": have,
                          "tail": "twitterapi (listening and monitors)" + held + (" (key set)" if have else " (TWITTERAPI_IO_API_KEY not set)")})
        else:
            lines.append(_composio_x_line(slug, conns, "x read driver", "composio (listening and monitors)"))
        own, bad = x_own_driver(slug)
        if bad:
            lines.append({"check": f"composio {slug} x own driver", "ok": False, "tail": f"{own}: {bad}"})
        elif own == "twitterapi" or not own_price_signoff():
            have = bool(secrets_mod.get_secret("TWITTERAPI_IO_API_KEY", required=False))
            held = f" ({HELD_OWN_REASON}; configured: composio)" if own == "composio" else ""
            lines.append({"check": f"composio {slug} x own driver", "ok": have,
                          "tail": "twitterapi (own-post numbers, mentions and replies)" + held
                                  + (" (key set)" if have else " (TWITTERAPI_IO_API_KEY not set)")})
        else:
            lines.append(_composio_x_line(slug, conns, "x own driver", "composio (own-post numbers, mentions and replies; own sign-off recorded)"))
    for slug in memory.streams():
        if stream_channels(slug) and slug not in unset:
            lines.extend(_inbound_doctor(slug, conns_by.get(slug)))
    return lines


def _composio_x_line(slug, conns, what, label):
    """The doctor line of an X read class that really runs on composio: it needs an ACTIVE X account."""
    has_x = any(k == "x" for k, _ in stream_channels(slug))
    x_ok = bool(has_x and conns is not None and (account_status(slug, "x", conns) or {}).get("status") == "ACTIVE")
    return {"check": f"composio {slug} {what}", "ok": x_ok,
            "tail": label + ("" if x_ok else f" (needs an ACTIVE {alias_for(slug, 'x')!r} account)")}


def _inbound_doctor(stream, conns):
    """The inbound doctor line(s): per inbound channel, on, held (price sign-off) or off (LinkedIn account missing)."""
    out = []
    for key in INBOUND_CHANNELS:
        if key not in [k for k, _ in stream_channels(stream)]:
            continue
        state, reason = inbound_status(stream, key, conns)
        out.append({"check": f"composio {stream} inbound {key}", "ok": True, "tail": reason if reason.startswith(state) else f"{state}: {reason}"})
    return out


# --- X reads: one search and one count, two drivers, the price hold, a logged fallback ---

#: the Composio tools the composio read driver calls (all in guard_posting.COMPOSIO_READ_SLUGS)
SEARCH_SLUG = "TWITTER_RECENT_SEARCH"
COUNTS_SLUG = "TWITTER_SEARCH_RECENT_COUNTS"
HELD_REASON = "held: price sign-off not recorded"
HELD_OWN_REASON = "held: own-post price sign-off not recorded"
#: the query length each driver accepts, used when `listen.query_limit.<driver>` is not set
DEFAULT_QUERY_LIMIT = {"twitterapi": 255, "composio": 512}
#: Composio calls one process may make before the driver falls back (`listen.composio_call_cap`)
DEFAULT_CALL_CAP = 200
_composio_calls = {"n": 0}


def price_signoff():
    """True when the owner has recorded the X price sign-off (`listen.x_price_signoff` in engine.json)."""
    import config
    value = config.cfg("listen.x_price_signoff", "")
    if isinstance(value, str):
        value = value.strip().lower() not in ("", "0", "false", "no", "off", "none")
    return bool(value)


def own_price_signoff():
    """True when the owner has recorded the price sign-off for the official-API reads on our own
    accounts (`listen.x_own_price_signoff` in engine.json): own-post numbers, mentions and replies.

    It is a separate record from `price_signoff()`: a note scoped to own reads never lets
    listening or the standing monitors read the official API."""
    import config
    value = config.cfg("listen.x_own_price_signoff", "")
    if isinstance(value, str):
        value = value.strip().lower() not in ("", "0", "false", "no", "off", "none")
    return bool(value)


def effective_x_own(stream):
    """`(driver, note)`: the driver the X reads on a stream's own accounts really use.

    The configured driver (`x_own_driver`) wins only when it is twitterapi, or when it is
    composio and the own-reads sign-off (`own_price_signoff`) is recorded. Composio without it
    is held: the answer is twitterapi and the note says so. `note` is None when nothing is held."""
    driver, bad = x_own_driver(stream)
    if bad:
        raise ChannelError(f"x own driver for {stream!r}: {driver}: {bad}")
    if driver == "composio" and not own_price_signoff():
        return "twitterapi", HELD_OWN_REASON
    return driver, None


def effective_x_read(stream):
    """`(driver, note)`: the driver X reads really use for a stream.

    The configured driver (`x_read_driver`) wins only when it is twitterapi, or when it is
    composio and the price sign-off is recorded. Composio without the sign-off is held:
    the answer is twitterapi and the note says so. `note` is None when nothing is held.
    """
    driver, bad = x_read_driver(stream)
    if bad:
        raise ChannelError(f"x read driver for {stream!r}: {driver}: {bad}")
    if driver == "composio" and not price_signoff():
        return "twitterapi", HELD_REASON
    return driver, None


def query_limit(driver=None, stream=None):
    """The query length limit for `@watched` packing: from `listen.query_limit.<driver>`."""
    import config
    if driver is None:
        driver = effective_x_read(stream or memory.DEFAULT_STREAM)[0]
    default = DEFAULT_QUERY_LIMIT.get(driver, DEFAULT_QUERY_LIMIT["twitterapi"])
    try:
        return int(config.cfg(f"listen.query_limit.{driver}", default) or default)
    except (TypeError, ValueError):
        return default


def _log_fallback(stream, why, runs_path=None):
    """Record a composio-to-twitterapi fallback on the run log, never silently."""
    import runlog
    name = memory.stream(stream)["name"]  # the registry's spelling, which state_check expects
    return runlog.append("listen-fallback", f"x read: composio -> twitterapi: {why}"[:300], stream=name,
                         runs_path=runs_path, driver="twitterapi", fallback_from="composio")


def _unwrap(result):
    """The tool's payload: Composio nests it as `{data: {data: [...], includes, meta}}`."""
    data = result.get("data") if isinstance(result, dict) else None
    if isinstance(data, dict) and isinstance(data.get("data"), (list, dict)):
        return data
    return data if isinstance(data, dict) else (result if isinstance(result, dict) else {})


def _x_item(tweet, users):
    """One official-API post in the shape twitterapi.io returns (what listen.norm_item reads)."""
    m = tweet.get("public_metrics") or {}
    user = users.get(str(tweet.get("author_id") or "")) or {}
    um = user.get("public_metrics") or {}
    handle = user.get("username") or ""
    tid = str(tweet.get("id") or "")
    return {
        "type": "tweet", "id": tid,
        "url": f"https://x.com/{handle or 'i'}/status/{tid}",
        "text": tweet.get("text") or "",
        "createdAt": tweet.get("created_at") or "",
        "lang": tweet.get("lang") or "",
        "conversationId": str(tweet.get("conversation_id") or ""),
        "likeCount": m.get("like_count") or 0, "retweetCount": m.get("retweet_count") or 0,
        "replyCount": m.get("reply_count") or 0, "viewCount": m.get("impression_count") or 0,
        "author": {"userName": handle, "name": user.get("name") or "",
                   "followers": um.get("followers_count") or 0},
    }


def _search_composio(stream, query, since, max_items, query_type, dry_run):
    import config
    cap = int(config.cfg("listen.composio_call_cap", DEFAULT_CALL_CAP) or DEFAULT_CALL_CAP)
    if _composio_calls["n"] >= cap:
        raise ChannelError(f"composio call cap {cap} reached")
    args = {"query": query, "max_results": max(10, min(100, int(max_items))),
            "sort_order": "relevancy" if query_type == "Top" else "recency",
            "tweet_fields": ["created_at", "public_metrics", "lang", "author_id", "conversation_id"],
            "expansions": ["author_id"], "user_fields": ["username", "name", "public_metrics"]}
    if since:
        args["start_time"] = dt.datetime.fromtimestamp(int(since), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _composio_calls["n"] += 1
    result = _execute(stream, "x", SEARCH_SLUG, args, dry_run=dry_run)
    if dry_run:
        return []
    body = _unwrap(result)
    users = {str(u.get("id")): u for u in (body.get("includes") or {}).get("users") or [] if isinstance(u, dict)}
    posts = [t for t in body.get("data") or [] if isinstance(t, dict) and t.get("id")]
    return [_x_item(t, users) for t in posts][:max_items]


def search(query, since=None, max_items=12, stream=None, query_type="Top", dry_run=False,
           key=None, opener=None, runs_path=None, own=False):
    """X posts for one advanced-search query, in the shape `listen.norm_item` reads.

    `since` is a Unix timestamp. The driver is `effective_x_read(stream)`. A composio
    read that cannot be made (no connected account, call cap, API error) falls back to
    twitterapi and is logged on the run log; it is never silent. `max_items` is the
    caller's per-term bound (listen.py keeps it at or under 12). `dry_run` previews the
    composio call (account check only, no execute) and returns []. `own` marks a read of our
    own accounts (mentions and replies): it takes `effective_x_own` instead of
    `effective_x_read`, so the two read classes keep their own driver and price hold.
    """
    import twitterapi
    stream = (stream or memory.DEFAULT_STREAM)
    driver, _held = (effective_x_own if own else effective_x_read)(stream)
    if driver == "composio":
        try:
            return _search_composio(stream, query, since, max_items, query_type, dry_run)
        except ChannelError as exc:
            if dry_run:
                raise
            _log_fallback(stream, str(exc), runs_path)
    if dry_run:
        return []
    key = key or twitterapi.load_key(None if stream == memory.DEFAULT_STREAM else stream)
    return twitterapi.search(key, query, max_items, since, query_type=query_type, opener=opener)


def _day(value):
    """The calendar day of a timestamp, ISO (official API) or twitterapi.io's ctime-like form."""
    text = str(value or "")
    if re.match(r"\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(text).astimezone(dt.timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return text[:10]


def counts(query, stream=None, dry_run=False, key=None, opener=None, runs_path=None):
    """How many recent posts match a query: `{total, buckets: [{start, count}], driver, approximate}`.

    Composio reads `TWITTER_SEARCH_RECENT_COUNTS` (day buckets, exact). twitterapi.io has no
    counts endpoint, so that driver counts one page of search results by day and says
    `approximate`. The same fallback and logging as `search`.
    """
    import twitterapi
    stream = (stream or memory.DEFAULT_STREAM)
    driver, _held = effective_x_read(stream)
    if driver == "composio":
        try:
            result = _execute(stream, "x", COUNTS_SLUG, {"query": query, "granularity": "day"}, dry_run=dry_run)
            if dry_run:
                return {"total": 0, "buckets": [], "driver": "composio", "approximate": False}
            body = _unwrap(result)
            rows = [b for b in body.get("data") or [] if isinstance(b, dict)]
            total = (body.get("meta") or {}).get("total_tweet_count")
            buckets = [{"start": _day(b.get("start")), "count": int(b.get("tweet_count") or 0)} for b in rows]
            return {"total": int(total if total is not None else sum(b["count"] for b in buckets)),
                    "buckets": buckets, "driver": "composio", "approximate": False}
        except ChannelError as exc:
            if dry_run:
                raise
            _log_fallback(stream, str(exc), runs_path)
    if dry_run:
        return {"total": 0, "buckets": [], "driver": "twitterapi", "approximate": True}
    key = key or twitterapi.load_key(None if stream == memory.DEFAULT_STREAM else stream)
    found = twitterapi.search(key, query, twitterapi.PAGE_SIZE, None, query_type="Latest", opener=opener)
    days = {}
    for t in found:
        d = _day(t.get("createdAt"))
        days[d] = days.get(d, 0) + 1
    return {"total": len(found), "buckets": [{"start": d, "count": n} for d, n in sorted(days.items())],
            "driver": "twitterapi", "approximate": True}


# --- own-post numbers: the official analytics, in the shape x_metrics.py writes ---

X_ANALYTICS_SLUG = "TWITTER_GET_POST_ANALYTICS"
LINKEDIN_STATS_SLUG = "LINKEDIN_GET_SHARE_STATS"
#: the metrics-input keys a read always carries (score.py reads them)
METRIC_KEYS = ("impressions", "likes", "reposts", "quotes", "replies", "saves")
#: official X analytics field -> metrics-input key
_X_FIELDS = {"impression_count": "impressions", "like_count": "likes", "retweet_count": "reposts",
             "quote_count": "quotes", "reply_count": "replies", "bookmark_count": "saves"}
#: LinkedIn totalShareStatistics field -> metrics-input key (clickCount is not a link click; left out)
_LI_FIELDS = {"impressionCount": "impressions", "likeCount": "likes", "shareCount": "reposts",
              "commentCount": "replies"}


def empty_read(platform, source, now):
    """A zero read in the metrics-input shape: counts only, no author, no text, no handle."""
    r = {"at": now.isoformat(timespec="seconds"), "platform": platform, "source": source}
    r.update({k: 0 for k in METRIC_KEYS})
    return r


def _walk_max(value, fields, out):
    if isinstance(value, dict):
        for k, v in value.items():
            if k in fields and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[fields[k]] = max(out.get(fields[k], 0), int(v))
            else:
                _walk_max(v, fields, out)
    elif isinstance(value, list):
        for v in value:
            _walk_max(v, fields, out)


def _x_post_counts(post):
    """One post's counts from an analytics row: cumulative fields (max), or timeseries buckets (summed)."""
    series = post.get("timestamped_metrics")
    out = {}
    if isinstance(series, list) and series:
        for bucket in series:
            part = {}
            _walk_max(bucket, _X_FIELDS, part)
            for k, v in part.items():
                out[k] = out.get(k, 0) + v
        return out
    _walk_max(post, _X_FIELDS, out)
    return out


def _x_analytics(stream, refs, now, dry_run):
    args = {"ids": list(refs), "granularity": "total",
            "tweet_fields": ["public_metrics", "organic_metrics", "non_public_metrics"]}
    result = _execute(stream, "x", X_ANALYTICS_SLUG, args, dry_run=dry_run)
    if dry_run:
        return None
    body = _unwrap(result)
    rows = [r for r in body.get("data") or [] if isinstance(r, dict) and str(r.get("id") or "") in set(map(str, refs))]
    if not rows:
        return None
    read = empty_read("X", "composio", now)
    for row in rows:
        for k, v in _x_post_counts(row).items():
            read[k] += v
    read["posts"] = len(rows)
    return read


def _linkedin_stats(stream, refs, now, dry_run):
    import linkedin_api
    org = linkedin_api.author_urn(linkedin_api.settings(stream))
    args = {"organizationalEntity": org, "shares": list(refs)}
    result = _execute(stream, "linkedin", LINKEDIN_STATS_SLUG, args, dry_run=dry_run)
    if dry_run:
        return None
    body = result.get("data") if isinstance(result, dict) else {}
    rows = []
    for el in (_unwrap(result).get("elements") or (body or {}).get("elements") or []):
        if isinstance(el, dict) and isinstance(el.get("totalShareStatistics"), dict):
            rows.append(el["totalShareStatistics"])
    if not rows:
        return None
    read = empty_read("LinkedIn", "composio", now)
    for stats in rows:
        for field, key in _LI_FIELDS.items():
            read[key] += int(stats.get(field) or 0)
    read["posts"] = len(rows)
    return read


def metrics(stream, channel, post_ref, now=None, dry_run=False):
    """Our own post's official numbers as one read in the metrics-input shape, or None.

    `post_ref` is a post id (X) or share URN (LinkedIn), or a list of them for one item; the
    read is summed over what was found. X reads `TWITTER_GET_POST_ANALYTICS`, billed to the
    brand's X app, so callers take it only when `effective_x_own` is composio (the own-reads
    price hold covers it). LinkedIn reads `LINKEDIN_GET_SHARE_STATS`. The read carries
    `source: composio`; counts only, no author, no text, no handle. Impressions here are the
    platform's own analytics, a different measure from twitterapi.io's public view count.
    """
    key = channel_key(channel)
    refs = [str(r) for r in (post_ref if isinstance(post_ref, (list, tuple)) else [post_ref]) if r]
    if not refs:
        return None
    if _composio_calls["n"] >= int(_cap()):
        raise ChannelError("composio call cap reached")
    now = now or _now_utc()
    _composio_calls["n"] += 1
    if key == "x":
        return _x_analytics(stream, refs, now, dry_run)
    if key == "linkedin":
        return _linkedin_stats(stream, refs, now, dry_run)
    raise ChannelError(f"no own-post metrics for channel {channel!r}")


def _cap():
    import config
    return config.cfg("listen.composio_call_cap", DEFAULT_CALL_CAP) or DEFAULT_CALL_CAP


def linkedin_linked(stream, conns=None):
    """True when the stream's LinkedIn composio account is linked; False when not or when the account list cannot be read."""
    try:
        return account_status(stream, "linkedin", conns if conns is not None else connections(stream)) is not None
    except ChannelError:
        return False


# --- inbound: mentions, replies and comments on our own accounts, as patterns only ---

INBOUND_FILE = "inbound.json"
INBOUND_CHANNELS = ("x", "linkedin")
#: the first poll of a channel, before any cursor is persisted
INBOUND_LOOKBACK_HOURS = 6
#: our own sent posts looked at for replies and comments: sent within this many days, at most this many
INBOUND_POST_DAYS = 3
INBOUND_POST_MAX = 8
INBOUND_PER_QUERY = 12
LINKEDIN_API = "https://api.linkedin.com/rest/socialActions"
LINKEDIN_VERSION = "202411"


def inbound_status(stream, channel, conns=None):
    """`(state, reason)`: `on`, `held` (own-reads price sign-off not recorded) or `off` (and why).

    X inbound reads X's own API, so it is held until `listen.x_own_price_signoff` is recorded and
    then runs only when the stream's configured own-reads driver (`channels.x_own`) is composio. LinkedIn runs only when the
    stream's LinkedIn composio account is linked."""
    key = channel_key(channel)
    if key not in INBOUND_CHANNELS:
        return "off", f"no inbound read for {key}"
    if key not in [k for k, _ in stream_channels(stream)]:
        return "off", f"{key} is not in {stream}'s channels cell"
    if key == "x":
        driver, bad = x_own_driver(stream)
        if bad:
            return "off", f"x own driver: {bad}"
        if driver != "composio":
            return "off", f"x own driver is {driver!r}; inbound reads X's own API (channels.x_own.{stream} composio)"
        if not own_price_signoff():
            return "held", HELD_OWN_REASON
        return "on", "own-reads price sign-off recorded; x own driver composio"
    if not linkedin_linked(stream, conns):
        return "off", f"no linkedin composio account linked ({alias_for(stream, 'linkedin')!r})"
    return "on", "linkedin account linked"


def _search_own(*args, **kwargs):
    """`search` for a read of our own accounts: the own-reads driver and hold, not listening's."""
    return search(*args, own=True, **kwargs)


def _inbound_path(state):
    return _state_path(state, INBOUND_FILE)


def load_inbound_cursors(state=None):
    """`{stream: {channel: {"since_id": str, "since_ts": int, "at": iso}}}`; empty when never polled."""
    try:
        with open(_inbound_path(state), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_inbound_cursors(data, state=None):
    p = _inbound_path(state)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, p)


def _id_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def recent_sent(stream, channel, state=None, now=None):
    """`[(post id or URN, sent_at)]`: our own posts sent on the channel in the last few days, newest first.

    Read from the send ledger: an X post's id is the last path piece of its URL (a root post is
    its own conversation); a LinkedIn post's id is its URN. Replies and comments we sent are not
    posts of ours to watch."""
    key = channel_key(channel)
    now = now or _now_utc()
    name = memory.stream(stream)["name"]
    out = []
    for row in _load_ledger(state)["sends"].values():
        if row.get("state") != "sent" or row.get("platform") != DISPLAY[key] or row.get("stream") != name:
            continue
        if row.get("kind") not in (None, "post"):
            continue
        try:
            at = dt.datetime.fromisoformat(str(row.get("at")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=dt.timezone.utc)
        if now - at > dt.timedelta(days=INBOUND_POST_DAYS):
            continue
        if key == "x":
            ref = str(row.get("url") or "").rstrip("/").rsplit("/", 1)[-1]
            ref = ref if ref.isdigit() else ""
        else:
            ref = str(row.get("urn") or "")
            ref = ref if ref.startswith("urn:li:") else ""
        if ref:
            out.append((ref, at))
    out.sort(key=lambda p: p[1], reverse=True)
    return out[:INBOUND_POST_MAX]


def _x_inbound_queries(stream, posts):
    """`([(kind, query)], own handle)`: the mentions rule's query, then replies in our recent posts' conversations."""
    import x_stream
    if (stream or "").strip().lower() != memory.DEFAULT_STREAM:
        raise ChannelError(f"no mentions rule for stream {stream!r}")
    try:
        mentions = next((value for tag, value, _ in x_stream.desired_rules() if tag.endswith(":mentions")), "")
    except x_stream.RuleError as exc:
        raise ChannelError(f"no mentions rule: {exc}") from exc
    # the rule ends `-from:<own handle>`: the handle is read from the rule, never typed here
    m = re.search(r"-from:(\w+)\s*$", mentions)
    if not m:
        raise ChannelError("the mentions rule names no own handle to exclude")
    own = m.group(1)
    limit = query_limit("composio", stream)
    out = [("mention", mentions)]
    chunk = []
    suffix = f" -from:{own}"
    for ref, _ in posts:
        trial = chunk + [ref]
        text = "(" + " OR ".join(f"conversation_id:{r}" for r in trial) + ")" + suffix
        if len(text) > limit and chunk:
            out.append(("reply", "(" + " OR ".join(f"conversation_id:{r}" for r in chunk) + ")" + suffix))
            chunk = [ref]
        else:
            chunk = trial
    if chunk:
        out.append(("reply", "(" + " OR ".join(f"conversation_id:{r}" for r in chunk) + ")" + suffix))
    return out, own


def inbound_plan(stream, channel, since=None, state=None, now=None):
    """What one inbound poll would ask, without asking: `{channel, queries: [(kind, query-or-url)], since_id, since_ts}`."""
    key = channel_key(channel)
    now = now or _now_utc()
    cursor = (load_inbound_cursors(state).get(stream) or {}).get(key) or {}
    since_ts = int(since) if since else int(cursor.get("since_ts") or (now.timestamp() - 3600 * INBOUND_LOOKBACK_HOURS))
    posts = recent_sent(stream, key, state, now)
    if key == "x":
        queries, own = _x_inbound_queries(stream, posts)
    else:
        own = ""
        queries = [("comment", f"GET {LINKEDIN_API}/{urllib.parse.quote(ref, safe='')}/comments") for ref, _ in posts]
    return {"channel": key, "queries": queries, "since_id": str(cursor.get("since_id") or ""), "since_ts": since_ts,
            "posts": len(posts), "own": own}


def _proxy_get(stream, channel, url, headers=None):
    """One proxied GET for a stream's channel account, parsed JSON (`POST /api/v3.1/tools/execute/proxy`
    with method GET). The only proxy call here, a GET only; the proxied reply is returned as Composio gives it."""
    key = channel_key(channel)
    acct = resolve_account(stream, key)
    body = {"connected_account_id": acct["id"], "endpoint": url, "method": "GET",
            "parameters": [{"name": n, "value": str(v), "type": "header"} for n, v in (headers or {}).items()]}
    if acct.get("user_id"):
        body["user_id"] = acct["user_id"]
    return _http(stream, "POST", "/api/v3.1/tools/execute/proxy", body=body)


def _partner_tier(handle, partners):
    return "institution" if handle and ("@" + handle.lower()) in partners else "other"


def _theme_of(text, tags):
    low = (text or "").lower()
    for tag in tags:
        if tag.lower() in low:
            return tag
    return ""


def _shape(kind, text):
    return "question" if "?" in (text or "") else kind


def _pattern(channel, tier, shape, theme, target):
    return {"channel": channel, "tier": tier, "shape": shape, "theme": theme, "target_post": str(target or "")}


def inbound(stream, channel, since=None, dry_run=False, state=None, now=None, search=None, proxy=None):
    """Poll one channel's inbound once and return patterns only.

    `{channel, state: on|held|off, reason, plan, patterns: [{channel, tier, shape, theme, target_post, count}], cursor}`.
    A pattern carries a tier, a shape, a theme and our own post's id, never a handle, a name or
    any text of a third party. The cursor per stream and channel (`state/inbound.json`) advances
    only for a channel whose reads all succeeded. `held` and `off` make no call. `dry_run` plans the
    queries and calls nothing and writes nothing. `search` and `proxy` are the read seams (tests)."""
    key = channel_key(channel)
    now = now or _now_utc()
    status, reason = inbound_status(stream, key)
    result = {"channel": key, "state": status, "reason": reason, "plan": None, "patterns": [], "cursor": None}
    if status == "off" or (status == "held" and not dry_run):
        return result
    result["plan"] = plan = inbound_plan(stream, key, since, state, now)
    if dry_run:
        return result
    counts, newest = {}, plan["since_id"]
    ts = int(now.timestamp())
    if key == "x":
        search = search or _search_own
        import x_stream
        own = plan["own"].lower()
        partners = {h.lower() for h in x_stream.partner_handles()}
        tags = memory.theme_tags(stream)
        seen = set()
        for kind, query in plan["queries"]:
            items = search(query, plan["since_ts"], INBOUND_PER_QUERY, stream=stream, query_type="Latest")
            for t in items or []:
                tid = str(t.get("id") or "")
                author = ((t.get("author") or {}).get("userName") or "").lower()
                if not tid or tid in seen or author == own:
                    continue
                seen.add(tid)
                if _id_int(tid) > _id_int(newest):
                    newest = tid
                if plan["since_id"] and _id_int(tid) <= _id_int(plan["since_id"]):
                    continue
                target = str(t.get("conversationId") or "") if kind == "reply" else ""
                p = _pattern("X", _partner_tier(author, partners), _shape(kind, t.get("text")),
                             _theme_of(t.get("text"), tags), target)
                counts[tuple(p.items())] = counts.get(tuple(p.items()), 0) + 1
    else:
        proxy = proxy or _proxy_get
        tags = memory.theme_tags(stream)
        headers = {"X-Restli-Protocol-Version": "2.0.0", "Linkedin-Version": LINKEDIN_VERSION}
        since_ms = int(plan["since_id"] or 0) or plan["since_ts"] * 1000
        newest = str(since_ms)
        for (ref, _), (kind, _desc) in zip(recent_sent(stream, key, state, now), plan["queries"]):
            if _composio_calls["n"] >= int(_cap()):
                raise ChannelError("composio call cap reached")
            _composio_calls["n"] += 1
            body = proxy(stream, key, f"{LINKEDIN_API}/{urllib.parse.quote(ref, safe='')}/comments?count={INBOUND_PER_QUERY}", headers)
            elements = (body.get("elements") if isinstance(body, dict) else None) or \
                       ((body.get("data") or {}).get("elements") if isinstance(body, dict) and isinstance(body.get("data"), dict) else None) or []
            for el in elements:
                if not isinstance(el, dict):
                    continue
                created = int(((el.get("created") or {}).get("time")) or 0)
                if created <= since_ms:
                    continue
                if created > int(newest):
                    newest = str(created)
                text = (el.get("message") or {}).get("text") if isinstance(el.get("message"), dict) else ""
                p = _pattern("LinkedIn", "other", _shape("comment", text), _theme_of(text, tags), ref)
                counts[tuple(p.items())] = counts.get(tuple(p.items()), 0) + 1
    result["patterns"] = [dict(dict(k), count=n) for k, n in sorted(counts.items())]
    cursor = {"since_id": newest, "since_ts": ts - 60, "at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    cursors = load_inbound_cursors(state)
    cursors.setdefault(stream, {})[key] = cursor
    save_inbound_cursors(cursors, state)
    result["cursor"] = cursor
    return result


# --- the send gate: the only code that calls a write driver ---

KINDS = ("post", "reply", "comment", "link-reply", "delete", "like", "repost", "quote")
#: a reaction with no text of ours: one per target, ever
REACTIONS = ("like", "repost")
#: every kind that acts on someone else's post, and so asks whether that post is one we may touch
TARGETED = REACTIONS + ("quote",)
#: the kinds a take down may remove (a like or a repost is undone): what the engine itself sent
DELETABLE = ("post", "reply", "comment", "link-reply", "like", "repost", "quote")
WATCHLIST_FILE = "watchlist.json"
TAKEDOWN_SUFFIX = "#takedown"
#: the fixed caption a link-reply opens with, per channel (the link goes in the first reply or comment)
LINK_CAPTIONS = {
    "x": "The full argument, with the facts it rests on:",
    "linkedin": "The full piece is on the blog, with the facts it rests on:",
}
#: channel key -> the name guardrails.py and the ledger use
DISPLAY = {"x": "X", "linkedin": "LinkedIn"}
CHECK_ORDER = ("pause", "kind", "driver", "account", "dedupe", "target", "cites", "gate", "stealth", "hold", "pair",
               "guardrails", "kind rule", "media")
#: what a post may carry, by extension: (the kind a driver is told, the mimetype)
MEDIA_KINDS = {".mp4": ("video", "video/mp4"), ".gif": ("gif", "image/gif"), ".png": ("image", "image/png")}
REPO = paths.instance()

STAT_RE = re.compile(r"\d[\d,.]*\s*(?:%|percent\b|x\b|\u00d7)", re.I)
CERT_RE = re.compile(r"\b(?:certif\w*|accredit\w*)\b", re.I)
MENTION_RE = re.compile(r"(?<![\w@])@[A-Za-z0-9_]{1,30}")

_DRIVERS = {}


class SendRefused(ChannelError):
    """A send the gate refused. `check` names the failing check, `reason` says why."""

    def __init__(self, check, reason):
        super().__init__(f"{check}: {reason}")
        self.check = check
        self.reason = reason


def register_driver(channel, fn):
    """Configure the write driver of a channel: `fn(request) -> {"url": ..., "urn"?: ...}`.

    `request` is `{stream, channel, kind, text, target, account, ref}`. X and LinkedIn
    have the Composio drivers registered at import (`register_defaults`); a channel with
    none registered (or passed to `send`) is refused at the `driver` check."""
    _DRIVERS[channel_key(channel)] = fn


def clear_drivers():
    _DRIVERS.clear()


def text_hash(channel, text):
    """The hash the ledger and the dedupe use: the channel's name and the text, whitespace and case folded."""
    name = DISPLAY.get(channel_key(channel), channel)
    return hashlib.sha256((name + "\n" + re.sub(r"\s+", " ", (text or "").strip().lower())).encode()).hexdigest()[:20]


def _now_utc():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _state_path(state, name):
    return os.path.join(state or STATE, name)


def _load_ledger(state):
    p = _state_path(state, LEDGER_FILE)
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("sends"), dict):
        data["sends"] = {}
    return data


def _save_ledger(state, data):
    p = _state_path(state, LEDGER_FILE)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def _append_line(path, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
    with open(path, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            size = f.seek(0, os.SEEK_END)
            if size:
                f.seek(size - 1)
                if f.read(1) != "\n":
                    data = "\n" + data
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def sends(state=None):
    """Every line of `state/sends.jsonl`: one per attempt, a torn or unreadable line skipped."""
    rows = []
    try:
        with open(_state_path(state, SENDS_LOG), encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def auto_reply_on(stream, channel, state=None):
    """Whether the stream's auto-reply switch for this channel is on now; off by default.

    The live value is `state/switches.json` (switches.py, written by the act applier from the
    dashboard's `switch` act), read at every call, so turning it off takes effect on the next
    send. Never changed, it falls back to the `channels.auto_reply.<stream>.<channel>` default in
    engine.json. It can only tighten: a switch on while `streams.md` does not allow an unapproved
    reply for the stream and channel is off."""
    import switches
    memory.stream(stream)
    return switches.effective(stream, channel_key(channel), state)


def mode(stream, channel, kind, state=None):
    """The review mode in force for this stream, channel and kind: `review` or `auto` (switches.py).
    Read at every call, so a change on the dashboard takes effect on the next send."""
    import switches
    return switches.mode(stream, channel_key(channel), kind, state)


def paused(stream, state=None):
    """Whether a person has paused every send of the stream (switches.py). Read at every send."""
    import switches
    return switches.paused(stream, state)


def _act_ok(act, target, decision, expected_hashes):
    if act.get("kind") != "decision" or act.get("target") != target or act.get("outcome") != "applied":
        return False
    if (act.get("payload") or {}).get("decision") != decision:
        return False
    return act.get("base") is None or act["base"] in expected_hashes


def _find_act(state, stream, target, decision, hashes):
    import store
    for act in store.acts(path=_state_path(state, ACTS_FILE)):
        if act.get("stream") in (None, stream) and _act_ok(act, target, decision, hashes):
            return act
    return None


def hold_reasons(stream, text, cites=None):
    """Why this text is in a hold-for-review class (streams.md), `[]` when it is in none.

    A percentage or multiple with no cited claim behind it; an @mention that is not the
    stream's own handle or a verified cleared partner; a certification or accreditation word.
    """
    out = []
    if STAT_RE.search(text) and not cites:
        out.append("a statistic with no cited claim")
    cleared = set()
    try:
        for row in memory.taggable_handles(stream).values():
            for key in ("x", "linkedin"):
                if row.get(key):
                    cleared.add(row[key].lower())
        for row in memory.load_handles(stream)["own_channels"]:
            if (row.get("handle") or "").strip().startswith("@"):
                cleared.add(row["handle"].strip().lower())
    except memory.SharedMemoryError:
        pass
    for m in MENTION_RE.findall(text):
        if m.lower() not in cleared:
            out.append(f"{m} is not on the cleared list")
    m = CERT_RE.search(text)
    if m:
        out.append(f"the word {m.group(0)!r}")
    return out


def _pair_rules_for(stream, text):
    """`[(other slug, rule)]` for each other stream the text names; rule is None when streams.md has no row."""
    named = []
    for slug, row in memory.load_streams().items():
        if slug == stream:
            continue
        for word in {slug, row["name"]}:
            if re.search(r"(?<![\w])" + re.escape(word) + r"(?![\w])", text, re.I):
                rule = next((p["rule"] for p in memory.stream(stream)["pair_rules"] if p["to"] == slug), None)
                named.append((slug, rule))
                break
    return named


def _check_gate(stream, channel, kind, text, ref):
    import gate_lint
    cites = ref.get("cites")
    try:
        if kind == "post":
            item = ref.get("item")
            if isinstance(item, dict):
                result = gate_lint.lint(item)
            elif ref.get("text_gate"):
                # a team row has no item: the text-level gate reads the text that will go out
                result = gate_lint.lint_text(stream, channel, text, cites)
            else:
                return "a post needs ref['item'], the item the gate reads"
        else:
            result = gate_lint.lint_text(stream, channel, text, cites)
    except (gate_lint.LintError, memory.SharedMemoryError) as exc:
        return f"the gate could not run: {exc}"
    if result["verdict"] == "block":
        bad = [c for c in result["checks"] if c["result"] == "block"]
        return "gate blocked: " + "; ".join(f"{c['check']}: {c.get('fix') or c.get('line')}" for c in bad)[:400]
    return None


def _evaluate(stream, channel, kind, text, ref, state, at, driver):
    """`(failing check, reason)` for the first check that fails, `(None, None)` when all pass."""
    import guardrails
    import gate_lint
    import lifecycle
    key = channel_key(channel)
    rid = ref.get("id")
    if kind == "delete":
        # before the pause: pausing a stream and taking a post down are one emergency, in that order
        return _delete_rule(stream, key, ref, state, driver)
    if paused(stream, state):
        return "pause", f"every send of {stream} is paused; a person resumes it on the dashboard"
    if kind not in KINDS:
        return "kind", f"unknown kind {kind!r}; one of {list(KINDS)}"
    if not isinstance(rid, str) or not rid.strip():
        return "kind", "ref['id'] is required"
    if kind in TARGETED:
        target_id = str(ref.get("target_id") or "").strip()
        if not target_id or rid != f"{kind}:{target_id}":
            return "kind", f"a {kind} is recorded once per target: ref['id'] is '{kind}:<the target post's id>' and ref['target_id'] that id"
        if key == "linkedin" and kind == "like":
            return "kind", "a like on LinkedIn is done by hand: no tool creates a reaction there"
    if kind in REACTIONS:
        return _reaction_rule(stream, key, kind, ref, state, at, driver)
    if not (text or "").strip():
        return "kind", "the text is empty"
    if driver is None:
        return "driver", f"no write driver is configured for {key}"
    try:
        account_for(stream, key, ref.get("account"))
    except ChannelError as exc:
        return "account", str(exc)
    if key not in [k for k, _ in stream_channels(stream)]:
        return "account", f"{key} is not one of {stream!r}'s own channels in streams.md"
    h = text_hash(key, text)
    ledger = _load_ledger(state)["sends"]
    prior = ledger.get(rid) or next((v for v in ledger.values() if v.get("hash") == h), None)
    if prior and prior.get("state") == "sending":
        return "dedupe", "an earlier send did not confirm; not re-sent, check the account by hand"
    if prior and prior.get("state") == "sent":
        return "dedupe", f"identical text or the same id was already sent {prior.get('url') or ''}".strip()
    cites = ref.get("cites") or (ref.get("item") or {}).get("cites") or []
    for cid in cites:
        ok, reason = memory.citable(cid, stream)
        if not ok:
            return "cites", reason
    why = _check_gate(stream, key, kind, text, ref)
    if why:
        return "gate", why
    try:
        stealth = gate_lint.scan_stealth([("text", text)], stream)
    except (gate_lint.LintError, memory.SharedMemoryError) as exc:
        return "stealth", f"the denylist could not be read: {exc}"
    if stealth["result"] != "pass":
        return "stealth", stealth["fix"]
    held = hold_reasons(stream, text, cites)
    if held and mode(stream, key, "hold", state) != "auto":
        # the hold is a kind of the review switch: on `auto`, set by a person, it passes without a release
        if not _find_act(state, stream, rid, "release-hold", {h, ref.get("text_hash")}):
            return "hold", "held for review (" + "; ".join(held) + ") and no applied release-hold act for this text"
    for other, rule in _pair_rules_for(stream, text):
        if rule is None:
            return "pair", f"the text names stream {other!r} and streams.md has no pair rule {stream} -> {other}"
    local = at.astimezone(zoneinfo.ZoneInfo(guardrails.TZ))
    gname = DISPLAY.get(key)
    if gname is None:
        return "guardrails", f"streams.md carries no guardrails for {key}"
    today = week = 0
    if kind == "post":
        for row in sends(state):
            if row.get("outcome") != "sent" or row.get("kind") != "post" or row.get("stream") != stream or row.get("channel") != key:
                continue
            try:
                when = dt.datetime.fromisoformat(row["at"].replace("Z", "+00:00")).astimezone(zoneinfo.ZoneInfo(guardrails.TZ))
            except (KeyError, ValueError, AttributeError):
                continue
            if when.date() == local.date():
                today += 1
            if when.isocalendar()[:2] == local.isocalendar()[:2]:
                week += 1
    ok, reason = guardrails.check(stream, gname, at, today, week, None)
    if not ok:
        return "guardrails", reason
    lpath = _state_path(state, LIFECYCLE_FILE)
    hashes = {h, ref.get("text_hash")}
    if kind == "post":
        cur = lifecycle.current(rid, lpath)
        if not cur or cur["to"] != "scheduled":
            return "kind rule", f"a post must be scheduled in the lifecycle; {rid} is {lifecycle.state(rid, lpath)}"
        if ref.get("text_hash") and cur.get("text_hash") and ref["text_hash"] != cur["text_hash"]:
            return "kind rule", "the text is not the one that was gated and approved"
        if str(cur.get("date", "")) > local.date().isoformat():
            return "kind rule", f"scheduled for {cur.get('date')}, not due before {local.date().isoformat()}"
        if _approved_by_engine(rid, lpath, state) and mode(stream, key, "post", state) != "auto":
            return "kind rule", (f"{rid} was approved by the engine and the review mode of {stream}/{key}/post is "
                                 "review now; a person approves it")
        why = media_refusal(rid, ref, lpath, state)
        if why:
            return "media", why
    elif kind in ("reply", "comment"):
        if not (ref.get("target") or "").strip():
            return "kind rule", f"a {kind} needs ref['target'], the post it answers"
        if not (_find_act(state, stream, rid, "approve", hashes) or auto_reply_on(stream, key, state)):
            return "kind rule", f"a {kind} needs an applied approval or the auto-reply switch on for {stream}/{key}"
    elif kind == "quote":
        # a quote is a post of ours on someone else's: the whole text gate above, and the target's own checks
        why = target_refusal(stream, key, ref, state)
        if why:
            return "target", why
        why = _reaction_cap_refusal(stream, key, kind, state, local)
        if why:
            return "guardrails", why
        if not (_find_act(state, stream, rid, "approve", hashes) or mode(stream, key, "quote", state) == "auto"):
            return "kind rule", f"a quote needs an applied approval or the quote mode on auto for {stream}/{key}"
    else:
        return _link_reply_rule(stream, key, text, ref, ledger, lpath, state)
    return None, None


def reactions_signoff(stream):
    """The owner's dated sign-off for automatic likes on X (`channels.reactions_signoff.<stream>`), or ''.

    X's developer guidelines say a like must be directly initiated by the account's user, so a
    like on X goes out on a person's click and never on the `like` mode alone
    (decisions/2026-11-13-reactions-platform-rules.md). The key exists because the plan named it;
    it ships empty and the decision recommends it stays so."""
    import config
    return str(config.cfg(f"channels.reactions_signoff.{stream.strip().lower()}", "") or "").strip()


def _handle(value):
    return str(value or "").strip().lower().lstrip("@")


def _watched(state):
    try:
        with open(_state_path(state, WATCHLIST_FILE), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return set()
    rows = data.get("watched") if isinstance(data, dict) else None
    return {_handle(r.get("handle")) for r in rows or [] if isinstance(r, dict) and r.get("handle")}


def target_refusal(stream, key, ref, state):
    """Why someone else's post is not one this stream may like, repost or quote, or None when it is.

    Its author is on a verified, cleared row of the stream's handles.md, or on the watchlist, or
    the post replies to one of our own sent posts (`in_reply_to`, a ledger id) or to our own
    account (`in_reply_to_handle`); and its text passes the stealth list, the
    status words and the pair rules, because a reaction puts the brand's name beside it. The
    author's handle is read from `ref` for this check and written nowhere (standing rule 6)."""
    import gate_lint
    text = str(ref.get("target_text") or "").strip()
    if not text:
        return "the target's text is not known, so it cannot be checked"
    eligible = False
    parent = ref.get("in_reply_to")
    if isinstance(parent, str) and parent:
        entry = _load_ledger(state)["sends"].get(parent) or {}
        names = {stream.lower(), memory.stream(stream)["name"].lower()}
        eligible = entry.get("state") == "sent" and str(entry.get("stream", "")).lower() in names
    reply_to = _handle(ref.get("in_reply_to_handle"))
    if not eligible and reply_to:
        # a reply to our own account, as the standing monitors record it: the handle answered is ours
        eligible = reply_to == _handle(dict(stream_channels(stream)).get(key))
    author = _handle(ref.get("author"))
    if not eligible and author:
        cleared = set()
        try:
            for row in memory.taggable_handles(stream).values():
                cleared |= {_handle(row.get(k)) for k in ("x", "linkedin") if row.get(k)}
        except memory.SharedMemoryError as exc:
            return f"handles.md did not read: {exc}"
        eligible = author in cleared or author in _watched(state)
    if not eligible:
        return ("the target's author is not on a verified cleared row of handles.md and not on the watchlist, "
                "and the post does not reply to one of ours")
    try:
        if gate_lint.scan_stealth([("target", text)], stream)["result"] != "pass":
            # the reason goes into records a person reads and a repository keeps: it never repeats the term
            return "the target's text fails stealth: it carries a term on the closed denylist, or the denylist is missing"
        status = gate_lint.scan_status_words([("target", text)], stream)
        if status["result"] != "pass":
            return f"the target's text fails status words: {status['fix']}"[:300]
    except (gate_lint.LintError, memory.SharedMemoryError) as exc:
        return f"the target's text could not be checked: {exc}"
    for other, rule in _pair_rules_for(stream, text):
        if rule is None:
            return f"the target names stream {other!r} and streams.md has no pair rule {stream} -> {other}"
    return None


def _reactions_today(stream, key, kind, state, local):
    import guardrails
    n = 0
    for row in sends(state):
        if row.get("outcome") != "sent" or row.get("kind") != kind or row.get("stream") != stream or row.get("channel") != key:
            continue
        try:
            when = dt.datetime.fromisoformat(row["at"].replace("Z", "+00:00")).astimezone(zoneinfo.ZoneInfo(guardrails.TZ))
        except (KeyError, ValueError, AttributeError):
            continue
        if when.date() == local.date():
            n += 1
    return n


def _reaction_cap_refusal(stream, key, kind, state, local):
    """Why the stream's `reactions_per_day` cap for this channel and kind refuses one more today, or None."""
    import guardrails
    cap = guardrails.reaction_cap(stream, key, kind)
    if cap <= 0:
        return f"no {kind} is allowed on {key}: the stream's reactions_per_day sets none (brand.json)"
    used = _reactions_today(stream, key, kind, state, local)
    if used >= cap:
        return f"{stream}: {key} is at its daily cap of {cap} {kind}(s) (reactions_per_day)"
    return None


def reaction_hash(key, kind, target_id):
    """The hash a like or a repost is recorded and approved under: it has no text of ours."""
    return text_hash(key, f"{kind} {target_id}")


def _reaction_rule(stream, key, kind, ref, state, at, driver):
    """The checks of a like or a repost. There is no text of ours to gate, so what is asked is:
    the stream's own account, one reaction per target ever, a target we may touch, the hours,
    the day's cap, and either a person's click or the kind's mode on `auto`."""
    import guardrails
    rid, target_id = ref["id"], str(ref["target_id"])
    if driver is None:
        return "driver", f"no write driver is configured for {key}"
    try:
        account_for(stream, key, ref.get("account"))
    except ChannelError as exc:
        return "account", str(exc)
    if key not in [k for k, _ in stream_channels(stream)]:
        return "account", f"{key} is not one of {stream!r}'s own channels in streams.md"
    prior = _load_ledger(state)["sends"].get(rid)
    if prior and prior.get("state") == "sending":
        return "dedupe", "an earlier send did not confirm; not re-sent, check the account by hand"
    if prior and prior.get("state") == "sent":
        return "dedupe", f"this post already has our {kind}; one per target, ever"
    why = target_refusal(stream, key, ref, state)
    if why:
        return "target", why
    gname = DISPLAY.get(key)
    if gname is None:
        return "guardrails", f"streams.md carries no guardrails for {key}"
    ok, reason = guardrails.check_hours(stream, gname, at)
    if not ok:
        return "guardrails", reason
    why = _reaction_cap_refusal(stream, key, kind, state, at.astimezone(zoneinfo.ZoneInfo(guardrails.TZ)))
    if why:
        return "guardrails", why
    if _find_act(state, stream, rid, "approve", {reaction_hash(key, kind, target_id)}):
        return None, None
    if mode(stream, key, kind, state) != "auto":
        return "kind rule", f"a {kind} needs a person's click or the {kind} mode on auto for {stream}/{key}"
    if key == "x" and kind == "like" and not reactions_signoff(stream):
        return "kind rule", ("a like on X goes out on a person's click only: X requires a like to be directly initiated by "
                             "the account's user, and no owner sign-off is recorded (channels.reactions_signoff)")
    return None, None


def takedown_target(stream, key, ref, state):
    """`(ledger entry, None)` for the sent post a delete names in `ref['target_id']`, or `(None, why)`."""
    target_id = ref.get("target_id")
    if not isinstance(target_id, str) or not target_id.strip():
        return None, "a delete needs ref['target_id'], the ledger id of the post to take down"
    entry = _load_ledger(state)["sends"].get(target_id)
    names = {stream.lower(), memory.stream(stream)["name"].lower()}
    if not entry or entry.get("state") != "sent" or str(entry.get("stream", "")).lower() not in names:
        return None, "the target must be our own sent post, on the ledger as sent for this stream"
    if entry.get("platform") != DISPLAY.get(key):
        return None, f"the target was sent on {entry.get('platform')}, not {DISPLAY.get(key, key)}"
    if entry.get("kind", "post") not in DELETABLE:
        return None, f"a {entry.get('kind')} cannot be taken down"
    if entry.get("kind") in REACTIONS:
        if not entry.get("target_id"):
            return None, "the ledger does not say which post it was on; undo it on the platform by hand"
    elif not (entry.get("url") or entry.get("urn")):
        return None, "the ledger has no url or urn for it; take it down on the platform by hand"
    return entry, None


def _delete_rule(stream, key, ref, state, driver):
    """The checks of a take down: our own sent post, not taken down already, on a person's
    applied `takedown` act. No gate, hours or cap applies to removing what we sent."""
    import store
    rid = ref.get("id")
    if not isinstance(rid, str) or not rid.strip():
        return "kind", "ref['id'] is required"
    if driver is None:
        return "driver", f"no write driver is configured for {key}"
    try:
        account_for(stream, key, ref.get("account"))
    except ChannelError as exc:
        return "account", str(exc)
    entry, why = takedown_target(stream, key, ref, state)
    if why:
        return "kind rule", why
    if entry.get("taken_down"):
        return "dedupe", f"already taken down {entry['taken_down'].get('at') or ''}".strip()
    acts_ = [a for a in store.acts(path=_state_path(state, ACTS_FILE))
             if a.get("kind") == "takedown" and a.get("target") == ref["target_id"] and a.get("outcome") == "applied"
             and a.get("by") != "engine" and a.get("stream") in (None, stream, memory.stream(stream)["name"])]
    if not acts_:
        return "kind rule", "a take down needs a person's applied takedown act for this post; the engine never deletes on its own"
    return None, None


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def media_path(rel):
    """The absolute path of a post's media, or None when it is not a motion card or film of this
    repository: a file under Content/Motion/ or videos/finals/, of a kind a post may carry."""
    import motion
    full = os.path.realpath(rel if os.path.isabs(str(rel)) else os.path.join(REPO, str(rel)))
    roots = [os.path.realpath(motion.MOTION_DIR), os.path.realpath(os.path.join(motion.FILMS, "finals"))]
    if not any(full.startswith(root + os.sep) for root in roots):
        return None
    return full if os.path.splitext(full)[1].lower() in MEDIA_KINDS else None


def _approval_acts(rid, lpath, state):
    """The applied decision acts that moved this post to `decided` (its own channel act among them)."""
    import lifecycle
    import store
    ids = {(ln.get("allowed_by") or {}).get("decision_act") for ln in lifecycle.lines(rid, lpath)} - {None}
    return [a for a in store.acts(path=_state_path(state, ACTS_FILE)) if a["id"] in ids and a.get("outcome") == "applied"]


def media_refusal(rid, ref, lpath, state):
    """Why the media named in `ref['media']` may not go out with this post, or None (also when there is none).

    A card or a film is part of what was approved: its hash is recorded in the approval act
    (`payload.media.sha256`) when the post is approved. At the send the file is hashed again:
    a file that is not a motion card or film of this repository, that is missing, or that is
    not byte for byte the one approved is refused. Nothing is attached that nobody saw."""
    media = ref.get("media")
    if not media:
        return None
    if not isinstance(media, dict) or not media.get("path") or not media.get("sha256"):
        return "ref['media'] needs the file's path and its sha256"
    full = media_path(media["path"])
    if full is None:
        return "the media is not a motion card or a film of this repository (Content/Motion/, videos/finals/), or not an mp4, gif or png"
    if not os.path.isfile(full):
        return "the media file is not on this machine; render it again, then approve the post with it"
    actual = file_sha256(full)
    if actual != str(media["sha256"]):
        return "the media file is not the one named: its hash differs"
    approved = {str(((a.get("payload") or {}).get("media") or {}).get("sha256") or "") for a in _approval_acts(rid, lpath, state)}
    if actual not in approved:
        return ("the media was not part of this post's approval, or the file changed since: "
                "approve the post again with it, or send it without")
    return None


def _approved_by_engine(rid, lpath, state):
    """Whether the approval that moved this post to `decided` was the engine's own (`by: engine`)."""
    import lifecycle
    import store
    ids = {(ln.get("allowed_by") or {}).get("decision_act") for ln in lifecycle.lines(rid, lpath)} - {None}
    if not ids:
        return False
    return any(a["id"] in ids and a.get("by") == "engine" for a in store.acts(path=_state_path(state, ACTS_FILE)))


def _link_reply_rule(stream, key, text, ref, ledger, lpath, state):
    import lifecycle
    if key not in LINK_CAPTIONS:
        return "kind rule", f"a link-reply is for X or LinkedIn, not {key}"
    row = ref.get("blog_row") or {}
    url = str(row.get("url") or "")
    if str(row.get("status")) != "Published" or not url.startswith("https://"):
        return "kind rule", "the link must come from the parent's own Blog row, Published, with an https URL"
    if text.strip() != f"{LINK_CAPTIONS[key]} {url}":
        return "kind rule", "a link-reply is the fixed caption and the Blog row's URL, nothing else"
    parent = ref.get("parent_id")
    entry = ledger.get(parent) if isinstance(parent, str) else None
    names = {stream.lower(), memory.stream(stream)["name"].lower()}
    if not entry or entry.get("state") != "sent" or str(entry.get("stream", "")).lower() not in names:
        return "kind rule", "the target must be our own sent post, on the ledger as sent for this stream"
    target = ref.get("target")
    if not target or target not in (entry.get("url"), entry.get("urn")):
        return "kind rule", "the target is not the sent post's url or urn"
    act_ids = [(ln.get("allowed_by") or {}).get("decision_act") for ln in lifecycle.lines(parent, lpath)]
    import store
    applied = {a["id"] for a in store.acts(path=_state_path(state, ACTS_FILE))
               if a.get("outcome") == "applied" and (a.get("payload") or {}).get("decision") == "approve"}
    if not any(a in applied for a in act_ids if a):
        return "kind rule", f"the parent {parent} has no applied approval in the lifecycle"
    return None, None


def send(stream, channel, kind, text, ref, driver=None, state=None, at=None):
    """Send one text, or refuse. The only code that calls a write driver.

    `ref` is a dict: `id` (always), `item` (or `text_gate: True` for a team row, which has no
    item: the text-level gate reads the text) and optional `cites`/`text_hash`/`title` for a
    post, `target` for a reply or comment, `parent_id`, `target` and `blog_row` for a
    link-reply. `driver` (or the one `register_driver` set) is called with the request
    and returns `{"url", "urn"?}`; none configured is a refusal. `state` is the state
    directory (default `state/`), `at` the send time (default now).

    Every attempt appends one line to `state/sends.jsonl`. A refusal raises `SendRefused`
    after recording the failing check; a driver failure is recorded `failed` and raises
    `ChannelError`. A passed check list writes `state/send-ledger.json` first.
    """
    at = at or _now_utc()
    ref = dict(ref or {})
    if kind == "link-reply" and not ref.get("id") and ref.get("parent_id"):
        ref["id"] = f"{ref['parent_id']}#link"
    if kind == "delete" and not ref.get("id") and ref.get("target_id"):
        ref["id"] = f"{ref['target_id']}{TAKEDOWN_SUFFIX}"
    key = channel_key(channel)
    driver = driver or _DRIVERS.get(key)
    memory.stream(stream)
    # a take down has no text of ours: its hash names the post it removes, so no two collide;
    # a like or a repost has none either: its hash names its target
    if kind == "delete":
        h = text_hash(key, f"delete {ref.get('target_id')}")
    elif kind in REACTIONS:
        h = reaction_hash(key, kind, ref.get("target_id"))
    else:
        h = text_hash(key, text)
    line = {"at": at.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "stream": stream, "channel": key,
            "kind": kind, "id": ref.get("id"), "text_hash": h}
    check, reason = _evaluate(stream, key, kind, text, ref, state, at, driver)
    if check:
        _append_line(_state_path(state, SENDS_LOG), dict(line, outcome="refused", check=check, reason=reason))
        raise SendRefused(check, reason)
    rid = ref["id"]
    ledger = _load_ledger(state)
    ledger["sends"][rid] = {"page_id": rid, "platform": DISPLAY[key], "title": str(ref.get("title") or rid)[:60],
                            "hash": h, "state": "sending", "at": line["at"], "stream": memory.stream(stream)["name"],
                            "kind": kind}
    if kind in TARGETED:
        # the target is kept as a post id, never as a URL: an X URL carries its author's handle
        ledger["sends"][rid]["target_id"] = str(ref["target_id"])
        ledger["sends"][rid]["title"] = f"{kind} {ref['target_id']}"[:60]
        line["target_id"] = str(ref["target_id"])
    _save_ledger(state, ledger)
    request = {"stream": stream, "channel": key, "kind": kind, "text": text, "target": ref.get("target"),
               "account": account_for(stream, key, ref.get("account")), "ref": ref}
    if ref.get("media"):
        full = media_path(ref["media"]["path"])
        what, mimetype = MEDIA_KINDS[os.path.splitext(full)[1].lower()]
        request["media"] = {"path": full, "kind": what, "mimetype": mimetype, "sha256": ref["media"]["sha256"]}
        ledger["sends"][rid]["media"] = ref["media"]["sha256"]
        line["media"] = str(ref["media"]["sha256"])[:16]
        _save_ledger(state, ledger)
    if kind == "delete":
        entry = ledger["sends"][ref["target_id"]]
        # X is addressed by the post's URL, LinkedIn by its URN
        request["target"] = (entry.get("urn") or entry.get("url")) if key == "linkedin" else entry.get("url")
        # undoing a like or a repost names the post it was on, not a post of ours
        request["target_kind"], request["target_post"] = entry.get("kind", "post"), entry.get("target_id")
    try:
        result = driver(request) or {}
    except Exception as exc:  # the failure is recorded, then raised; the ledger keeps `failed`
        ledger["sends"][rid].update({"state": "failed", "error": str(exc)[:200]})
        _save_ledger(state, ledger)
        _append_line(_state_path(state, SENDS_LOG), dict(line, outcome="failed", reason=str(exc)[:200]))
        raise ChannelError(f"{kind} on {key} failed: {exc}") from exc
    url, urn = result.get("url", ""), result.get("urn")
    warning = str(result.get("warning") or "")[:300]
    ledger["sends"][rid].update({"state": "sent", "url": url, "urn": urn})
    if kind == "link-reply" and ref.get("parent_id") in ledger["sends"]:
        ledger["sends"][ref["parent_id"]]["link_reply"] = {"url": url, "at": line["at"], "link": ref["blog_row"]["url"]}
    if kind == "delete":
        # the post stays on the ledger as sent, so its text is never sent again; it is marked taken down
        ledger["sends"][ref["target_id"]]["taken_down"] = {"at": line["at"], "by": rid}
    _save_ledger(state, ledger)
    out = dict(line, outcome="sent", url=url)
    if warning:
        out["warning"] = warning
        _warn_run(stream, key, rid, warning, state)
    if kind == "post":
        import lifecycle
        try:
            lifecycle.sent(rid, {"id": rid, "sent_at": line["at"], "url": url},
                           path=_state_path(state, LIFECYCLE_FILE))
        except lifecycle.LifecycleError as exc:
            out["lifecycle"] = str(exc)[:200]
    _append_line(_state_path(state, SENDS_LOG), out)
    return {"url": url, "urn": urn, "id": rid, "kind": kind}


def _warn_run(stream, key, rid, warning, state):
    """Log a send warning on the run log; a failure to log never undoes a send that happened."""
    try:
        import runlog
        runlog.append("send-warning", f"{key} {rid}: {warning}"[:300], stream=memory.stream(stream)["name"],
                      runs_path=_state_path(state, "runs.json"), channel=key, item=rid)
    except Exception:  # noqa: BLE001
        pass


# --- the Composio write drivers: X and LinkedIn, registered as the channel defaults ---
#
# Each driver takes `send()`'s request and makes one `_execute` call carrying what the
# native path (xurl; linkedin_api.py) carries: the text, the stream's own account (the
# alias `_execute` resolves) and, for a reply or comment, the target. The native paths
# stay in autopilot.py; nothing here removes them.

X_POST_SLUG = "TWITTER_CREATION_OF_A_POST"
LINKEDIN_POST_SLUG = "LINKEDIN_CREATE_LINKED_IN_POST"
LINKEDIN_COMMENT_SLUG = "LINKEDIN_CREATE_COMMENT_ON_POST"
# The take-down tools, as Composio's tool list names them (docs.composio.dev/toolkits/twitter and
# /linkedin, toolkit versions 20261101_00 and 20261112_00, read 2026-11-13): looked up, not guessed.
# Media: a file is staged with Composio first (POST /api/v3.1/files/upload/request, then a PUT to the
# presigned URL it answers with), and the tool is handed the descriptor {name, mimetype, s3key}
# (docs.composio.dev, "executing tools" and the files API reference, read 2026-11-13).
X_UPLOAD_SLUG = "TWITTER_UPLOAD_MEDIA"              # one image under 5 MiB
X_UPLOAD_LARGE_SLUG = "TWITTER_UPLOAD_LARGE_MEDIA"  # a GIF or a video, chunked, waits for processing
X_MEDIA_CATEGORY = {"image": "tweet_image", "gif": "tweet_gif", "video": "tweet_video"}
UPLOAD_PATH = "/api/v3.1/files/upload/request"
X_LIKE_SLUG = "TWITTER_USER_LIKE_POST"
X_UNLIKE_SLUG = "TWITTER_UNLIKE_POST"
X_REPOST_SLUG = "TWITTER_RETWEET_POST"
X_UNREPOST_SLUG = "TWITTER_UNRETWEET_POST"
X_ME_SLUG = "TWITTER_USER_LOOKUP_ME"
X_DELETE_SLUG = "TWITTER_POST_DELETE_BY_POST_ID"
LINKEDIN_DELETE_SLUG = "LINKEDIN_DELETE_POST"
LINKEDIN_DELETE_COMMENT_SLUG = "LINKEDIN_DELETE_COMMENT"
LINKEDIN_COMMENT_URN = re.compile(r"^urn:li:comment:\((urn:li:[A-Za-z]+:[^,()]+),([^,()]+)\)$")


def _find_id(value):
    """The first `id` anywhere in a nested result, as text (a string or a whole number)."""
    if isinstance(value, dict):
        v = value.get("id")
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, int) and not isinstance(v, bool):
            return str(v)
        for v in value.values():
            found = _find_id(v)
            if found:
                return found
    elif isinstance(value, list):
        for v in value:
            found = _find_id(v)
            if found:
                return found
    return None


def _tweet_id(result):
    """The numeric post id in a create-post result, wherever Composio nests it, or '' when unreadable.

    Never raises: the call has already succeeded when this runs (`_execute` raises on
    `successful: false`), so an id that cannot be read must not turn a post that exists into a
    failure a later run would send again."""
    found = _find_id(result)
    return found if found and found.isdigit() else ""


def _x_status_url(tweet_id):
    return f"https://x.com/i/web/status/{tweet_id}"


def x_driver(request):
    """Post, reply to `target` (a post URL), like, repost or quote the post `ref['target_id']`, or take
    `target` down (undo a like or a repost), on the stream's X account. Returns `{"url"}`."""
    stream, kind, account = request["stream"], request["kind"], request.get("account")
    if kind == "delete":
        undo = request.get("target_kind")
        if undo in REACTIONS:
            post_id = _x_post_id(request.get("target_post"), f"undoing an X {undo}")
            if undo == "like":
                _execute(stream, "x", X_UNLIKE_SLUG, {"id": _x_user_id(stream, account), "tweet_id": post_id}, account=account)
            else:
                _execute(stream, "x", X_UNREPOST_SLUG, {"source_tweet_id": post_id}, account=account)
            return {"url": ""}
        target = (request.get("target") or "").strip().rstrip("/")
        post_id = target.rsplit("/", 1)[-1] if target else ""
        if not post_id.isdigit():
            raise ChannelError(f"an X take down needs the post's URL, got {target!r}")
        _execute(stream, "x", X_DELETE_SLUG, {"id": post_id}, account=account)
        return {"url": target}
    if kind in REACTIONS:
        post_id = _x_post_id((request.get("ref") or {}).get("target_id"), f"an X {kind}")
        if kind == "like":
            _execute(stream, "x", X_LIKE_SLUG, {"id": _x_user_id(stream, account), "tweet_id": post_id}, account=account)
        else:
            _execute(stream, "x", X_REPOST_SLUG, {"tweet_id": post_id}, account=account)
        return {"url": ""}
    if kind not in ("post", "reply", "comment", "link-reply", "quote"):
        raise ChannelError(f"the X driver has no {kind}")
    args = {"text": request["text"]}
    if kind == "quote":
        args["quote_tweet_id"] = _x_post_id((request.get("ref") or {}).get("target_id"), "an X quote")
    if request.get("media"):
        args["media_media_ids"] = [_x_upload(stream, request["media"], account)]
    if request["kind"] in ("reply", "comment", "link-reply"):
        target = (request.get("target") or "").strip().rstrip("/")
        reply_to = target.rsplit("/", 1)[-1] if target else ""
        if not reply_to.isdigit():
            raise ChannelError(f"an X {request['kind']} needs a post URL as its target, got {target!r}")
        args["reply_in_reply_to_tweet_id"] = reply_to
    result = _execute(request["stream"], "x", X_POST_SLUG, args, account=request.get("account"))
    tweet_id = _tweet_id(result)
    if not tweet_id:
        return {"url": "", "warning": f"{X_POST_SLUG} succeeded but its result has no readable post id "
                                      f"(result keys: {_shape_of(result)}); recorded as sent with an unknown url"}
    return {"url": _x_status_url(tweet_id)}


def stage_file(stream, channel, slug, media, opener=None):
    """Hand one file to Composio for a tool call and return the descriptor the tool takes:
    `{name, mimetype, s3key}`. Two requests: the upload request (with the stream's key), then the
    file itself to the presigned URL it answers with (no key: that host is storage, not Composio's API)."""
    key = channel_key(channel)
    with open(media["path"], "rb") as f:
        data = f.read()
    name = os.path.basename(media["path"])
    got = _http(stream, "POST", UPLOAD_PATH, body={
        "toolkit_slug": LINK_TOOLKITS[key], "tool_slug": slug, "filename": name, "mimetype": media["mimetype"],
        "md5": hashlib.md5(data).hexdigest()}, opener=opener)  # the md5 is the API's integrity field, not a secret
    url = got.get("new_presigned_url") or got.get("newPresignedUrl") if isinstance(got, dict) else None
    s3key = got.get("key") if isinstance(got, dict) else None
    if not url or not s3key:
        raise ChannelError("composio did not answer the upload request with a storage key and a presigned URL")
    headers = {"Content-Type": media["mimetype"], "User-Agent": USER_AGENT}
    if str(((got.get("metadata") or {}).get("storage_backend")) or "") == "azure_blob_storage":
        headers["x-ms-blob-type"] = "BlockBlob"
    req = urllib.request.Request(url, data=data, method="PUT", headers=headers)
    try:
        (opener or _OPENER or urllib.request.build_opener()).open(req, timeout=TIMEOUT).read()
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        raise ChannelError(f"the media upload failed: HTTP {code}") from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ChannelError(f"the media upload did not run: {getattr(exc, 'reason', exc)}") from None
    return {"name": name, "mimetype": media["mimetype"], "s3key": s3key}


def _media_id(result):
    """The numeric media id in an X upload result, wherever Composio nests it, or ''."""
    for key in ("media_id_string", "media_id", "id"):
        found = _find_text(result, key)
        if found and str(found).isdigit():
            return str(found)
    found = _find_id(result)
    return found if found and found.isdigit() else ""


def _x_upload(stream, media, account=None):
    """Upload a post's media to X and return its media id; raises when X did not give one."""
    slug = X_UPLOAD_SLUG if media["kind"] == "image" else X_UPLOAD_LARGE_SLUG
    args = {"media": stage_file(stream, "x", slug, media), "media_category": X_MEDIA_CATEGORY[media["kind"]]}
    media_id = _media_id(_execute(stream, "x", slug, args, account=account))
    if not media_id:
        raise ChannelError(f"{slug} succeeded but gave no media id; the post was not sent without the media it was approved with")
    return media_id


def _x_post_id(value, what):
    post_id = str(value or "").strip().rstrip("/").rsplit("/", 1)[-1]
    if not post_id.isdigit():
        raise ChannelError(f"{what} needs the target post's numeric id, got {value!r}")
    return post_id


def _x_user_id(stream, account=None):
    """The stream's own X user id, which the like tools ask for beside the post's: asked of the
    account itself, so a like can only ever be made as the account the stream is linked to."""
    found = _find_id(_execute(stream, "x", X_ME_SLUG, {}, account=account))
    if not found or not found.isdigit():
        raise ChannelError(f"{X_ME_SLUG} did not say who the {stream} X account is; the like was not sent")
    return found


def _shape_of(result):
    """The key names of a result, never its values (a warning must carry no post text or token)."""
    keys = []

    def walk(value, prefix, depth):
        if isinstance(value, dict) and depth < 4:
            for k, v in value.items():
                keys.append(f"{prefix}{k}")
                walk(v, f"{prefix}{k}.", depth + 1)
    walk(result, "", 0)
    return ", ".join(keys[:20]) or "none"


def _linkedin_urn(result):
    for key in ("$URN", "urn", "id", "x-restli-id"):
        found = _find_text(result, key)
        if found and found.startswith("urn:"):
            return found
    return ""


def linkedin_driver(request):
    """Post, comment on `target` (a post URN), or take `target` down, as the stream's LinkedIn author.
    Returns `{"url", "urn"}`."""
    import linkedin_api
    stream = request["stream"]
    author = linkedin_api.author_urn(linkedin_api.settings(stream))
    text = request["text"]
    if request["kind"] == "delete":
        target = (request.get("target") or "").strip()
        comment = LINKEDIN_COMMENT_URN.match(target)
        if comment:
            args = {"entity_urn": comment.group(1), "comment_id": comment.group(2)}
            if author.startswith("urn:li:organization:"):
                args["actor"] = author
            _execute(stream, "linkedin", LINKEDIN_DELETE_COMMENT_SLUG, args, account=request.get("account"))
        elif target.startswith(("urn:li:share:", "urn:li:ugcPost:")):
            _execute(stream, "linkedin", LINKEDIN_DELETE_SLUG, {"post_urn": target}, account=request.get("account"))
        else:
            raise ChannelError(f"a LinkedIn take down needs the post's or the comment's URN, got {target!r}")
        return {"url": "", "urn": target}
    if request["kind"] in ("repost", "quote"):
        # a reshare is a post whose reshareContext names the post it shares; a quote is one with our words on it
        parent = str((request.get("ref") or {}).get("target") or (request.get("ref") or {}).get("target_id") or "").strip()
        if not parent.startswith(("urn:li:share:", "urn:li:ugcPost:")):
            raise ChannelError(f"a LinkedIn {request['kind']} needs the target post's URN, got {parent!r}")
        commentary, visibility = "", "PUBLIC"  # a plain reshare carries no words of ours
        if request["kind"] == "quote":
            payload = linkedin_api.build_post_payload(author=author, text=text)
            commentary, visibility = payload["commentary"], payload["visibility"]
        args = {"author": author, "commentary": commentary, "visibility": visibility, "reshareContext": {"parent": parent}}
        result = _execute(stream, "linkedin", LINKEDIN_POST_SLUG, args, account=request.get("account"))
        urn = _linkedin_urn(result)
        if not urn:
            return {"url": "", "urn": "", "warning": f"{LINKEDIN_POST_SLUG} succeeded but its result has no readable urn "
                                                    f"(result keys: {_shape_of(result)}); recorded as sent with an unknown url"}
        try:
            url = linkedin_api.post_url(urn)
        except Exception:  # noqa: BLE001 - the reshare exists; an odd urn must not make it a failure
            url = ""
        return {"url": url, "urn": urn}
    if request["kind"] not in ("post", "reply", "comment", "link-reply"):
        raise ChannelError(f"the LinkedIn driver has no {request['kind']}")
    if request["kind"] == "post":
        payload = linkedin_api.build_post_payload(author=author, text=text)
        args = {"author": author, "commentary": payload["commentary"], "visibility": payload["visibility"]}
        media = request.get("media")
        if media:
            if media["kind"] == "video":
                # the one video tool posts as a member, never as the page: say so rather than post as someone else
                raise ChannelError("a LinkedIn page post cannot carry a video through Composio; approve it with the card's poster, or post it by hand")
            args["images"] = [stage_file(stream, "linkedin", LINKEDIN_POST_SLUG, media)]
        result = _execute(stream, "linkedin", LINKEDIN_POST_SLUG, args, account=request.get("account"))
        urn = _linkedin_urn(result)
        if not urn:
            return {"url": "", "urn": "", "warning": f"{LINKEDIN_POST_SLUG} succeeded but its result has no readable urn "
                                                    f"(result keys: {_shape_of(result)}); recorded as sent with an unknown url"}
        try:
            url = linkedin_api.post_url(urn)
        except Exception:  # noqa: BLE001 - the post exists; an odd urn must not make it a failure
            url = ""
        return {"url": url, "urn": urn}
    target = (request.get("target") or "").strip()
    if not target.startswith("urn:li:"):
        raise ChannelError(f"a LinkedIn {request['kind']} needs a post URN as its target, got {target!r}")
    payload = linkedin_api.build_comment_payload(actor=author, text=text)
    args = {"actor": author, "message": payload["message"], "object": target, "target_urn": target}
    result = _execute(stream, "linkedin", LINKEDIN_COMMENT_SLUG, args, account=request.get("account"))
    urn = _linkedin_urn(result)
    out = {"url": "", "urn": urn}
    if not urn:
        out["warning"] = (f"{LINKEDIN_COMMENT_SLUG} succeeded but its result has no readable urn "
                          f"(result keys: {_shape_of(result)}); recorded as sent with an unknown urn")
    return out


def register_defaults():
    """Make the Composio drivers the write drivers of X and LinkedIn."""
    register_driver("x", x_driver)
    register_driver("linkedin", linkedin_driver)


register_defaults()
