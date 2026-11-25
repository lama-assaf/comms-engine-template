#!/usr/bin/env python3
"""
control.py - the control page: a local dashboard over everything the engine
holds, with the few controls a person may use from it.

Why: what the engine knows is spread over a dozen files. `views.py` computes
every view from them, live on each request, and this page shows them in one
place; this module reads nothing itself. The page is the web app in `ui/`,
built into `ui/dist` (committed, so no Node is needed to run it) and served
here with the token written into it; the first page, `control/page.html`,
answers at `/classic` until the app matches it. It binds 127.0.0.1 only and
answers a Host of 127.0.0.1 or localhost, refuses a cross-site Origin, and
every change needs the token written into the page it served, so no other site
open in the browser can drive it. On a hosted Mac (docs/07-hosting.md) it also
answers the Tailscale Serve name in params.host.serve_name, and only with a
Tailscale-User-Login that engine.local.json host.roles maps to a role, which
becomes each act's `by`. Any process on the Mac could set that header on
127.0.0.1: the same trust as the localhost page. Nothing is
published and nothing posts.

What it changes, and nothing else:

- a theme's search terms in `themes.json`: the X query (at most 255
  characters, X's limit) and the keywords the listener scores with, each change
  appended to the file's `_term_log` with its date. Which hashtags are themes,
  and what a theme may claim, stay in `themes.md`, through the corpus;
- the watchlist, `state/watchlist.json`: accounts a person watches, which the
  listener reads with the `@watched` X pass (`from:` each, in as few searches
  of 255 characters as they fit, at most 30 accounts); added from the
  suggestions or by hand, and removed;
- dismissed suggestions, in the same file, and their restoring;
- an answer to one of the story's big questions (`state/story/questions.json`,
  through `story.answer`), and a response to any slide, an action or a note
  (`state/story/responses.json`, through `story.respond`), and the closing frame's
  feedback on the whole story (`state/story/feedback.json`), which the next story reads;
- the argument line of a post (`/api/confirm-argument`): the hook and claim as the card
  shows them, confirmed as `today.py confirm` does (an `argument_lines` row in `state/desk.db`
  and its act), which approving needs;
- an approve on a post in the posts view (`/api/approve`): the desk's two standing rules first
  (`standing_rules.py`: a confirmed, current argument line; a reason is optional, and when typed,
  optionally `standing`, recorded as a desk review so that `desk_sync.py --pull` is still the only writer
  of `reviews.md`), then one decision act in
  `state/acts.jsonl` and the post moved to `scheduled` for its date in
  `state/lifecycle.jsonl`, through the same applier as the desk's approve
  (`desk_acts`); it never sends, and a refusal comes back with its reason;
- an article marked live (`/api/blog-live`): one `blog-live` act with the role, the URL
  `site.post_url` gives for the post's slug, and the site webhook (`site.webhook_url`); the sender
  then puts the article link in a first reply under the post's sent teasers;
- a post's date (`/api/schedule`): before it is sent, the lifecycle of the post and of each
  scheduled channel moved within the guardrails, then the note's date through `repo.py`; refused
  once a channel of it is sent;
- a team post (`/api/new-post`): one post on X or LinkedIn written by a person, gated by the
  text-level gate (a block writes nothing), then a note at status Idea through `repo.py`
  (`drafted_by: team`) that the gatekeeper gates and a person approves like any draft;
- an approve-and-send on a drafted reply or comment in the replies view
  (`/api/approve-reply`): no written reason is needed, one typed is stored as above (the argument line is for posts
  only), then one approval act for that exact text in `state/acts.jsonl`,
  then `channels.send()` at once (reply on X, comment on LinkedIn, to the proposal's
  target), so the gate, cites, hold, quiet hours and every other check still apply. The
  outcome, or the refusal's check and reason, comes back and is read again from
  `state/sends.jsonl` by the replies view; the write driver is the stream's
  (`channels.write_driver`);
- the auto-reply switch of a stream and channel (`/api/switch`, `switches.py`): off by default and only
  ever tighter than `streams.md`; a `switch` act with the role and time, applied to `state/switches.json`
  (the act applier is its only writer). Turning it on needs a confirmation (a written reason is optional);
  turning it off needs neither. `channels.send()` reads it at every send; nothing here sends;
- the review mode of one stream, channel and kind, or a preset over all of them (`/api/switch` with a
  `kind` and a `mode`, or a `preset`): `review` or `auto`, a `switch` act as above; `auto` takes one
  confirmation and is refused where the stream's setup does not allow it;
- the pause of a stream (`/api/pause`): a `pause` act, applied at once; `channels.send()` refuses every
  send of a paused stream. Pausing is one click, resuming takes a confirmation;
- the setup file (`/api/setup`): a change to a stream's settings, the drivers or the jobs in brand.json,
  checked by `config.validate` before anything is written, recorded as a `setup` act with the role and
  time, then the tables of streams.md rendered from it (brandfile.py, the one writer). Every change takes
  a confirmation and is refused when the file moved since the page read it. The brand's slug and a new
  stream are `engine.py init` and the onboarding's, not the page's;
- a reaction (`/api/react`): one click on a like or a repost the engine planned (`reactions.py`): an
  approval act for exactly that reaction on that target, then `channels.send()` at once, with the target
  check, the day's cap and the one-per-target rule still applying; its undoing is a take down;
- a take down (`/api/takedown`): one `takedown` act with the role, then `channels.send()` with the kind
  `delete` on a post, reply or comment the engine itself sent (the ledger says so). The post stays on the
  ledger as sent and is marked taken down, so its text is never sent again. It works while the stream is
  paused. The engine never deletes on its own;
- a theme's licence: a person allows a held theme (`licensed`, or
  `licensed-with-hedge` with the exact wording quoted) or holds it again, with
  the reason that lets them, through `held_theme.py`; the status log keeps the
  grade and the reason it replaced;
- a new theme: a person's decision. `held_theme.py`, the one writer of
  `themes.md` besides `/corpus-update --apply` (`ORCHESTRATION.md` §7), adds
  it at the lowest grade, `held` (posts under it argue the general idea only,
  never what we do, until a person grades it against `status.md`), and this
  module adds its search to `themes.json`. Both files are checked after the
  write and put back as they were if the roster no longer reads.

It also answers one read for the website, `GET /api/published`: the articles marked live, as JSON
(`views.published_posts`). Like the page, it is local until the engine is hosted;
`engine.py export-published <file>` writes the same JSON for a site build meanwhile.

A write is refused when its file changed since the page read it: conflicts
skip, never clobber. Holds, rewrites and edits of posts stay on the desk (approving is the one decision made here); `handles.md` and
`claims.md` are shown, never written, here, and of a theme already in
`themes.md` only its licence grade is.

  engine control start     # in the background; prints the URL and opens it
  engine control stop
  engine control status
  engine control serve [--port 4320] [--no-open]   # in the foreground
"""
import argparse
import datetime as dt
import base64
import hmac
import http.server
import json
import mimetypes
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.parse
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
STATE = paths.state()
sys.path.insert(0, HERE)
import config  # noqa: E402
import held_theme  # noqa: E402
import memory  # noqa: E402
import motion  # noqa: E402
import views  # noqa: E402
from views import REPO, TERMS, WATCHLIST, WATCH_MAX, X_QUERY_MAX, digest, load_json, norm_handle, rel  # noqa: E402,F401

PAGE = os.path.join(ENGINE, "control", "page.html")       # the first page, kept at /classic until the app matches it
UI = os.path.join(ENGINE, "ui", "dist")                    # the web app (ui/), built and committed
ASSETS = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".woff2": "font/woff2",
          ".svg": "image/svg+xml", ".png": "image/png"}
PIDFILE = os.path.join(STATE, "control.pid")
LOGFILE = os.path.join(STATE, "control.log")
DEFAULT_PORT = 4320
HANDLE_RE = re.compile(r"@?[A-Za-z0-9_]{1,15}")
MEDIA = {".png", ".gif", ".mp4"}


class Refused(ValueError):
    """A change the page may not make, said in one line for the person."""


class Conflict(Refused):
    """The file changed since the page read it."""


# ------------------------------------------------------------------ files


def write_json(path, data, indent=2):
    tmp = f"{path}.control-{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
    return digest(path)


# ------------------------------------------------------------------ the watchlist


def _save_watchlist(data, path):
    return write_json(path, {
        "_about": "Accounts a person watches from the control page (scripts/control.py); listen.py reads "
                  "them in its @watched X pass. Dismissed suggestions are kept so they are not suggested again.",
        "watched": data["watched"], "dismissed": data["dismissed"]})


def watch(handle, base, themes=(), note="", origin="by hand", path=None, today=None):
    path = path or WATCHLIST
    if digest(path) != (base or ""):
        raise Conflict("the watchlist changed since the page read it; reload and try again")
    if not HANDLE_RE.fullmatch(str(handle or "").strip()):
        raise Refused("an X handle is 1 to 15 letters, digits or underscores")
    h = norm_handle(handle)
    data = views.watchlist(path)
    if h in {norm_handle(w.get("handle")) for w in data["watched"]}:
        raise Refused(f"@{h} is already watched")
    if h in views.known_handles():
        raise Refused(f"@{h} is in handles.md already, and monitored there")
    if len(data["watched"]) >= WATCH_MAX:
        raise Refused(f"at most {WATCH_MAX} watched accounts; remove one first")
    data["watched"].append({"handle": f"@{h}", "platform": "X", "themes": [t for t in themes if t],
                            "note": str(note or "")[:200], "from": origin,
                            "added": today or dt.date.today().isoformat()})
    data["dismissed"] = [d for d in data["dismissed"] if norm_handle(d.get("handle")) != h]
    return _save_watchlist(data, path)


def unwatch(handle, base, path=None):
    path = path or WATCHLIST
    if digest(path) != (base or ""):
        raise Conflict("the watchlist changed since the page read it; reload and try again")
    h, data = norm_handle(handle), views.watchlist(path)
    kept = [w for w in data["watched"] if norm_handle(w.get("handle")) != h]
    if len(kept) == len(data["watched"]):
        raise Refused(f"@{h} is not watched")
    data["watched"] = kept
    return _save_watchlist(data, path)


def dismiss(handle, base, path=None, today=None):
    path = path or WATCHLIST
    if digest(path) != (base or ""):
        raise Conflict("the watchlist changed since the page read it; reload and try again")
    h, data = norm_handle(handle), views.watchlist(path)
    if not h:
        raise Refused("no handle")
    if h not in {norm_handle(d.get("handle")) for d in data["dismissed"]}:
        data["dismissed"].append({"handle": f"@{h}", "at": today or dt.date.today().isoformat()})
    return _save_watchlist(data, path)


def undismiss(handle, base, path=None):
    """Let a dismissed account be suggested again."""
    path = path or WATCHLIST
    if digest(path) != (base or ""):
        raise Conflict("the watchlist changed since the page read it; reload and try again")
    h, data = norm_handle(handle), views.watchlist(path)
    kept = [d for d in data["dismissed"] if norm_handle(d.get("handle")) != h]
    if len(kept) == len(data["dismissed"]):
        raise Refused(f"@{h} is not dismissed")
    data["dismissed"] = kept
    return _save_watchlist(data, path)


# ------------------------------------------------------------------ themes

def add_theme(tag, what, different, x_search, keywords, md_base, terms_base, today=None, terms=None):
    """A new theme, held: its rows through held_theme.py, its search in themes.json."""
    themes_md = held_theme.path()
    terms = terms or TERMS
    if digest(themes_md) != (md_base or "") or digest(terms) != (terms_base or ""):
        raise Conflict("themes.md or themes.json changed since the page read them; reload and try again")
    today = today or dt.date.today().isoformat()
    x_search = " ".join(str(x_search or "").split())
    words = keywords if isinstance(keywords, list) else str(keywords or "").split(",")
    words = list(dict.fromkeys(w.strip().lower() for w in words if w and w.strip()))
    local = load_json(terms, None)
    if not isinstance(local, dict):
        raise Refused("themes.json could not be read")
    try:
        tag, old_md, new_md = held_theme.prepare(tag, what, different, today, also_taken=local.get("search_terms") or {})
    except held_theme.Refused as e:
        raise Refused(str(e)) from None
    if not 3 <= len(x_search) <= X_QUERY_MAX:
        raise Refused(f"the X search is {len(x_search)} characters; X takes 3 to {X_QUERY_MAX}")
    if not 1 <= len(words) <= 40 or any(len(w) > 60 for w in words):
        raise Refused("keywords: 1 to 40 of them, each at most 60 characters")
    local.setdefault("search_terms", {})[tag] = {"x_search": x_search, "linkedin_search": "", "keywords": words}
    log = local.setdefault("_term_log", [])
    if isinstance(log, list):
        log.append(f"{today} - {tag}: added on the control page (held), X search: {x_search}")

    with open(terms, "rb") as f:
        old_terms = f.read()
    md_written = False
    try:
        write_json(terms, local)
        held_theme.write(old_md, new_md, tag)
        md_written = True
        tags = {t["tag"] for t in memory.load_themes()}
        if tag not in tags or tags != set(load_json(terms, {}).get("search_terms") or {}):
            raise Refused("the theme roster did not read back the same from both files")
    except Exception as e:
        if md_written:
            held_theme.undo(old_md)
        with open(terms, "wb") as f:
            f.write(old_terms)
        if isinstance(e, held_theme.Refused):
            raise Refused(str(e)) from None
        raise
    return {"terms_base": digest(terms), "md_base": digest(themes_md)}


def grade_theme(tag, licence, basis, md_base, today=None):
    """A person's grade of one theme's licence, through held_theme.py, with its reason."""
    themes_md = held_theme.path()
    if digest(themes_md) != (md_base or ""):
        raise Conflict("themes.md changed since the page read it; reload and try again")
    try:
        old, new, _was = held_theme.prepare_grade(tag, licence, basis, today)
        held_theme.write(old, new, held_theme.normalise(tag), licence=licence)
    except held_theme.Refused as e:
        raise Refused(str(e)) from None
    return {"md_base": digest(themes_md)}


# ------------------------------------------------------------------ search terms


def write_terms(tag, x_search, keywords, base, path=None, today=None):
    """Replace one theme's X query and keywords in themes.json, logged."""
    path = path or TERMS
    if digest(path) != (base or ""):
        raise Conflict("themes.json changed since the page read it; reload and try again")
    local = load_json(path, None)
    if not isinstance(local, dict) or tag not in (local.get("search_terms") or {}):
        raise Refused(f"{tag} has no search terms in themes.json; a theme is added through themes.md first")
    x_search = " ".join(str(x_search or "").split())
    if not 3 <= len(x_search) <= X_QUERY_MAX:
        raise Refused(f"the X query is {len(x_search)} characters; X takes 3 to {X_QUERY_MAX}")
    words = keywords if isinstance(keywords, list) else str(keywords or "").split(",")
    words = list(dict.fromkeys(w.strip().lower() for w in words if w and w.strip()))
    if not 1 <= len(words) <= 40 or any(len(w) > 60 for w in words):
        raise Refused("keywords: 1 to 40 of them, each at most 60 characters")
    entry = local["search_terms"][tag]
    changes = []
    if entry.get("x_search") != x_search:
        changes.append(f"X search was: {entry.get('x_search', '')}")
    if [str(k).lower() for k in entry.get("keywords", [])] != words:
        changes.append(f"keywords were: {', '.join(entry.get('keywords', []))}")
    if not changes:
        raise Refused("nothing changed")
    entry["x_search"], entry["keywords"] = x_search, words
    log = local.setdefault("_term_log", [])
    if isinstance(log, list):
        log.append(f"{today or dt.date.today().isoformat()} - {tag}: changed on the control page; " + "; ".join(changes))
    return write_json(path, local)


# ------------------------------------------------------------------ the server


#: The header Tailscale Serve sets to the signed-in tailnet user (docs/07-hosting.md).
LOGIN_HEADER = "Tailscale-User-Login"


def door_settings():
    """(serve_name, roles): this Mac's Tailscale Serve name (params.host.serve_name) and the map of
    tailnet login to role, read per request so a removed login is refused at once. The map lives in
    the gitignored engine.local.json (host.roles), so no login reaches a tracked file or a record."""
    name = str(config.cfg("host.serve_name", "") or "").strip().lower().rstrip(".")
    try:
        local = config._read_json(config.LOCAL_JSON)
    except ValueError:
        local = {}
    roles = ((local.get("params") or {}).get("host") or {}).get("roles") if isinstance(local, dict) else None
    return name, roles if isinstance(roles, dict) else {}


def door(headers, port, token, method, serve_name="", roles=None):
    """(reason, role): reason is None when the request may proceed; role is the act's `by` when the
    request came through Tailscale Serve, None on localhost (the page's own `by` stands there).

    Localhost is today's page. The Serve name (and its https origin) is answered only with a
    Tailscale-User-Login that `roles` maps to a known role; an unmapped or missing login is refused,
    and a refusal never repeats the login. The token check holds for both."""
    import desk_acts
    host = (headers.get("Host") or "").lower()
    local = host in (f"127.0.0.1:{port}", f"localhost:{port}")
    served = bool(serve_name) and host in (serve_name, f"{serve_name}:443")
    if not (local or served):
        return ("this page answers on 127.0.0.1 and localhost only"
                + (f", and on {serve_name} through Tailscale Serve" if serve_name else "")), None
    origins = (f"http://127.0.0.1:{port}", f"http://localhost:{port}") if local else (f"https://{serve_name}",)
    origin = headers.get("Origin")
    if origin and origin.lower().rstrip("/") not in origins:
        return "a change from another site is refused", None
    role = None
    if served:
        login = (headers.get(LOGIN_HEADER) or "").strip().lower()
        if not login:
            return "a request over Tailscale must carry the signed-in identity; reach the page through `tailscale serve`", None
        mapped = {str(k).strip().lower(): v for k, v in (roles or {}).items()}.get(login)
        if mapped not in desk_acts.ROLES:
            return "this Tailscale login is not mapped to a role on this Mac (engine.local.json host.roles)", None
        role = mapped
    if method == "POST" and not hmac.compare_digest(headers.get("X-Control-Token") or "", token):
        return "a change needs the token of the page that asks for it; reload the page", None
    return None, role


def allowed(headers, port, token, method, serve_name="", roles=None):
    """None when the request may proceed, else the reason it may not."""
    return door(headers, port, token, method, serve_name, roles)[0]


def _post_item(post_id):
    import gate_lint
    if not isinstance(post_id, str) or not post_id.strip():
        raise Refused("no post named")
    items = gate_lint.items_by_id()
    if post_id not in items:
        raise Refused("no post carries this id")
    return items


def approve_post(post_id, by=None, state_dir=None, guard=None, reason=None, scope=None):
    """The posts view's approve: the desk's standing rules (a confirmed, current argument line; a
    reason is optional; `standing_rules`), then one decision act and the lifecycle move to `scheduled`
    for the post's date, through the desk's own applier. It never sends. A refusal is an answer, not
    an error: the outcome comes back for the page to show."""
    import desk_acts
    import standing_rules
    items = _post_item(post_id)
    try:
        scope = standing_rules.norm_scope(scope)
    except ValueError as exc:
        raise Refused(str(exc))
    return desk_acts.approve_post(post_id, by, items, state_dir or STATE, guard=guard, reason=reason, scope=scope)


def confirm_argument(post_id, by=None, state_dir=None):
    """Confirm the hook and the claim as the card shows them: the argument-line act `today.py confirm`
    records, which approving needs. Returns the hook and claim that were confirmed."""
    import standing_rules
    items = _post_item(post_id)
    return standing_rules.confirm_argument(items[post_id], by, state_dir or STATE)


def blog_live(post_id, by=None, state_dir=None, webhook=None):
    """Mark a post's article live on the site: one `blog-live` act (desk_acts.blog_live), then the site
    webhook. The sender's link-reply under the post's sent teasers reads the act. A refusal is an
    answer, not an error; nothing is sent here. `webhook` is for tests."""
    import desk_acts
    items = _post_item(post_id)
    return desk_acts.blog_live(post_id, by, items, state_dir or STATE, webhook=webhook)


def schedule_post(post_id, date, by=None, state_dir=None, guard=None):
    """Change a post's date before it is sent: the lifecycle first (its own id and each channel id
    that is scheduled, each within the guardrails, through desk_acts.reschedule), then the note's
    date through repo.py. Refused once any channel of it is sent; nothing moves on a refusal. One
    `schedule` act records the change with the role."""
    import acts
    import desk_acts
    import lifecycle
    import repo
    items = _post_item(post_id)
    item = items[post_id]
    day = repo.as_date(date)
    if not isinstance(day, dt.date):
        raise Refused(f"{date!r} is not a date (YYYY-MM-DD)")
    state_dir = state_dir or STATE
    was = str((item.get("slot") or {}).get("date") or "")
    if day.isoformat() == was[:10]:
        raise Refused("the post is on that date already")
    apath = os.path.join(state_dir, desk_acts.ACTS_FILE)
    act = acts.record("schedule", item.get("stream") or memory.DEFAULT_STREAM, post_id,
                      {"date": day.isoformat(), "from": was}, by=desk_acts.role_of(by), path=apath)
    try:
        moved = desk_acts.reschedule(item, day.isoformat(), state_dir, guard=guard)
    except lifecycle.LifecycleError as exc:
        acts.refused(act["id"], str(exc)[:200], path=apath)
        raise Refused(str(exc))
    repo.set_fields(post_id, {"slot": dict(item.get("slot") or {}, date=day.isoformat())})
    repo.write_index()
    acts.applied(act["id"], path=apath)
    return {"id": post_id, "date": day.isoformat(), "from": was, "moved": moved}


def new_post(stream, channel, date, text, title=None, theme="", by=None, state_dir=None):
    """A team post written on the control page: the text-level gate first (a `block` refuses and
    nothing is written), then one note at status Idea through repo.py, `drafted_by: team`, which
    the gatekeeper gates and a person approves like any draft. It is never scheduled or sent here."""
    import acts
    import desk_acts
    import gate_lint
    import repo
    try:
        slug = memory.slug_for(stream or memory.DEFAULT_STREAM)
        item = repo.team_item(memory.stream(slug)["name"], channel, date, text, title, theme)
        result = gate_lint.lint_text(slug, channel, item[repo.TEAM_CHANNELS[channel]], None)
    except (ValueError, memory.SharedMemoryError, gate_lint.LintError) as exc:
        raise Refused(str(exc))
    if result["verdict"] == "block":
        bad = [c for c in result["checks"] if c["result"] == "block"]
        raise Refused("the gate blocks it: " + "; ".join(f"{c['check']}: {c.get('fix') or c.get('line')}" for c in bad)[:400])
    item["gate_writer"] = {"verdict": result["verdict"], "by": "gate_lint.lint_text",
                           "checks": [{k: c.get(k) for k in ("check", "result", "fix")} for c in result["checks"]]}
    try:
        paths = repo.write_team_item(item)
    except ValueError as exc:
        raise Refused(str(exc))
    repo.write_index()
    apath = os.path.join(state_dir or STATE, desk_acts.ACTS_FILE)
    act = acts.record("new-post", slug, item["id"], {"channel": channel, "date": item["slot"]["date"]},
                      by=desk_acts.role_of(by), path=apath)
    acts.applied(act["id"], path=apath)
    return {"id": item["id"], "note": rel(paths["post"]), "gate": result["verdict"]}


def reply_driver(stream, channel):
    """The write driver the stream is configured for on this channel: `channels.write_driver.<stream>`
    (`composio`: channels.py's; anything else: the native one autopilot.py holds)."""
    import channels
    name, why = channels.write_driver(stream)
    if name == "composio" and not why:
        return {"x": channels.x_driver, "linkedin": channels.linkedin_driver}.get(channel)
    import autopilot
    return autopilot.NATIVE_DRIVERS.get(channel)


def approve_reply(proposal_id, by=None, state_dir=None, driver=None, at=None, reason=None, scope=None):
    """The replies view's approve-and-send: no written reason is needed (owner decision 2026-11-11; one
    typed is still stored; no argument line is asked of a reply), then an approval act for the proposal's exact
    text, then send it through `channels.send()` as a reply (X) or comment (LinkedIn) to its target.

    A refusal or a failed send is an answer, not an error: `{id, target, outcome, check?, reason?,
    url?}` with `outcome` `sent`, `refused` or `failed`; the attempt is also a line in
    `state/sends.jsonl`. `by` is made a role, never a name. `driver` is for tests."""
    import acts
    import channels
    import desk_acts
    import desk_sync
    import standing_rules
    state_dir = state_dir or STATE
    try:
        scope = standing_rules.norm_scope(scope)
    except ValueError as exc:
        raise Refused(str(exc))
    if not isinstance(proposal_id, str) or not proposal_id.strip():
        raise Refused("no reply named")
    found = next((p for p in (load_json(os.path.join(state_dir, "engagement.json"), {}).get("proposals") or [])
                  if desk_sync.proposal_id(p) == proposal_id), None)
    if found is None:
        raise Refused("no drafted reply carries this id")
    try:
        key = channels.channel_key(found.get("platform"))
    except channels.ChannelError as exc:
        raise Refused(str(exc))
    kind = "reply" if key == "x" else "comment"
    text = str(found.get("draft_comment") or "")
    target = str(found.get("target_url") or "").strip()
    if key == "linkedin" and str(found.get("target_post") or "").startswith("urn:li:"):
        target = str(found["target_post"]).strip()
    if not text.strip():
        raise Refused("the drafted reply is empty")
    if not target:
        raise Refused("this reply has no post to answer: it needs a target_url")
    why = standing_rules.refusal("approved", reason, "reaction")
    if why:
        return {"id": None, "target": proposal_id, "kind": kind, "channel": key, "outcome": "refused",
                "check": "standing rules", "reason": why}
    stream = found.get("stream") or memory.DEFAULT_STREAM
    apath = os.path.join(state_dir, channels.ACTS_FILE)
    act = acts.record("decision", stream, proposal_id,
                      {"decision": "approve", "note": str(reason or "").strip(), "item_kind": kind, "source": "dashboard",
                       "target": target},
                      base=channels.text_hash(key, text), by=desk_acts.role_of(by), path=apath)
    acts.applied(act["id"], path=apath)
    ref = {"id": proposal_id, "target": target, "cites": found.get("cites") or [],
           "title": found.get("target_title") or proposal_id}
    out = {"id": act["id"], "target": proposal_id, "kind": kind, "channel": key}
    try:
        driver = driver or reply_driver(stream, key)
        got = channels.send(stream, key, kind, text, ref, driver=driver, state=state_dir, at=at)
        out = dict(out, outcome="sent", url=got.get("url", ""))
        try:  # the send happened; a review that could not be written must not turn it into an error
            standing_rules.record_review(proposal_id, "reaction", found.get("theme"), found.get("target_title"),
                                         "approved", reason, scope, by, stream, state_dir)
        except Exception as exc:
            out["review_error"] = str(exc)[:200]
        return out
    except channels.SendRefused as exc:
        return dict(out, outcome="refused", check=exc.check, reason=exc.reason)
    except channels.ChannelError as exc:
        return dict(out, outcome="failed", reason=str(exc)[:200])


def takedown(send_id, by=None, reason=None, state_dir=None, driver=None, at=None):
    """Take down something the engine sent: one `takedown` act with the role, then `channels.send()`
    with the kind `delete` for the ledger entry `send_id`.

    A refusal or a failed delete is an answer, not an error: `{id, target, outcome, check?, reason?,
    url?}` with `outcome` `taken down`, `refused` or `failed`; the attempt is also a line in
    `state/sends.jsonl`. `by` is made a role, never a name. `driver` is for tests."""
    import acts
    import channels
    import desk_acts
    state_dir = state_dir or STATE
    if not isinstance(send_id, str) or not send_id.strip():
        raise Refused("no sent post named")
    entry = channels._load_ledger(state_dir)["sends"].get(send_id)
    if not entry or entry.get("state") != "sent":
        raise Refused("the ledger has no sent post with this id")
    try:
        slug = memory.slug_for(entry.get("stream") or memory.DEFAULT_STREAM)
        key = channels.channel_key(entry.get("platform"))
    except (memory.SharedMemoryError, channels.ChannelError) as exc:
        raise Refused(str(exc))
    apath = os.path.join(state_dir, channels.ACTS_FILE)
    act = acts.record("takedown", slug, send_id,
                      {"channel": key, "url": entry.get("url") or "", "reason": str(reason or "").strip()},
                      by=desk_acts.role_of(by), path=apath)
    acts.applied(act["id"], path=apath)
    out = {"id": act["id"], "target": send_id, "kind": "delete", "channel": key}
    try:
        got = channels.send(slug, key, "delete", "", {"target_id": send_id, "title": f"take down {entry.get('title') or send_id}"},
                            driver=driver or reply_driver(slug, key), state=state_dir, at=at)
        return dict(out, outcome="taken down", url=got.get("url", ""))
    except channels.SendRefused as exc:
        return dict(out, outcome="refused", check=exc.check, reason=exc.reason)
    except channels.ChannelError as exc:
        return dict(out, outcome="failed", reason=str(exc)[:200])


def react(candidate_id, by=None, state_dir=None, driver=None, at=None):
    """One click on a planned like or repost (`reactions.click`): an approval act for exactly that
    reaction on that target, then the send through `channels.send()`. A refusal is an answer:
    `{id, kind, channel, outcome, check?, reason?, act}` with `outcome` `sent`, `waiting`, `refused` or
    `failed`. `driver` is for tests."""
    import reactions
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise Refused("no reaction named")
    try:
        return reactions.click(candidate_id, by=by, state=state_dir or STATE, driver=driver, at=at)
    except KeyError as exc:
        raise Refused(str(exc).strip("'\""))


def set_switch(stream, channel, value=None, by=None, reason=None, confirm=False, state_dir=None, kind=None, mode=None,
               preset=None):
    """The review switch (`switches.py`): a `switch` act with the role and time, applied to
    `state/switches.json`. Three forms:

      kind + mode   one stream, channel and kind set to `review` or `auto`
      preset        every kind on every channel of the stream, by one of switches.PRESETS
      value         the auto-reply switch as first built: the reply and comment modes together

    Loosening (`auto`, on) needs `confirm: true`; a written reason is optional. Tightening needs
    neither. A refusal (not confirmed, the stream's setup does not allow it) is an answer with
    `outcome: refused: <why>`; nothing here sends."""
    import switches
    state = state_dir or STATE
    try:
        if preset is not None:
            return {"stream": stream, "preset": preset,
                    "changes": switches.preset(stream, preset, by=by, confirm=confirm, state=state)}
        if kind is not None or mode is not None:
            return switches.set_mode(stream, channel, kind, mode, by=by, reason=reason, confirm=confirm, state=state)
        return switches.change(stream, channel, value, by=by, reason=reason, confirm=confirm, state=state)
    except switches.SwitchError as exc:
        raise Refused(str(exc))


def set_pause(stream, paused, by=None, reason=None, confirm=False, state_dir=None):
    """Pause or resume every send of a stream: a `pause` act, applied at once (`switches.set_pause`).
    Pausing needs nothing; resuming needs `confirm: true`."""
    import switches
    try:
        return switches.set_pause(stream, paused, by=by, reason=reason, confirm=confirm, state=state_dir or STATE)
    except switches.SwitchError as exc:
        raise Refused(str(exc))


#: What the Setup page may change in brand.json: these keys of an existing stream, the drivers and
#: the jobs. The brand block and a new stream are `engine.py init` and the onboarding's.
SETUP_STREAM_KEYS = ("name", "narrator", "owner", "objectives", "autopilot", "channels", "review", "drafts_only",
                     "posts_per_day", "reactions_per_day", "quiet_hours", "blocked_topics", "hold_for_review")
SETUP_CONFIRM = "Changing the setup needs your confirmation: it changes what the engine may do for this brand."


def change_setup(changes, base, by=None, confirm=False, state_dir=None, streams_md=None):
    """One change to the setup file, from the Setup page. `changes` is the part of brand.json to
    replace: `{"streams": {"<slug>": {key: value}}, "drivers": {..}, "jobs": {..}}`.

    Refused, with nothing written: a key the page may not change, a stream the file does not have,
    a file that moved since the page read it (`base`), no confirmation, or a result
    `config.validate` finds a problem in (the key and the fix come back). Applied: brand.json is
    written, the tables of streams.md are rendered from it, and one `setup` act records the change
    with the role and time. Returns `{id, outcome, changed, base}`."""
    import acts
    import brandfile
    import desk_acts
    path = config.brand_path()
    bdoc = brandfile.read()
    if not bdoc:
        raise Refused("there is no brand.json yet; run engine.py init first")
    if not isinstance(changes, dict) or not changes:
        raise Refused("no change named")
    if digest(path) != base:
        raise Conflict("brand.json changed since this page read it; the page has been reloaded, try again")
    new = json.loads(json.dumps(bdoc))
    changed = []
    for section, value in changes.items():
        if section == "streams" and isinstance(value, dict):
            for slug, row in value.items():
                if slug not in (new.get("streams") or {}) or not isinstance(row, dict):
                    raise Refused(f"{slug!r} is not a stream of brand.json; a new stream is onboarded with engine.py onboard-stream")
                for key, v in row.items():
                    if key not in SETUP_STREAM_KEYS:
                        raise Refused(f"streams.{slug}.{key} is not changed from this page")
                    if new["streams"][slug].get(key) != v:
                        new["streams"][slug][key] = v
                        changed.append(f"streams.{slug}.{key}")
        elif section in ("drivers", "jobs") and isinstance(value, dict):
            block = dict(new.get(section) or {})
            for key, v in value.items():
                if block.get(key) != v:
                    block[key] = v
                    changed.append(f"{section}.{key}")
            new[section] = block
        else:
            raise Refused(f"{section!r} is not changed from this page")
    if not changed:
        return {"id": None, "outcome": "applied", "changed": [], "base": base}
    problems = config.brand_problems(new, config._read_json(config.ENGINE_JSON))
    if problems:
        raise Refused("; ".join(f"{k}: {p}. Fix: {fix}" for k, p, fix in problems[:3]))
    if confirm is not True:
        raise Refused(SETUP_CONFIRM)
    streams_md = streams_md or memory.STREAMS_MD
    apath = os.path.join(state_dir or STATE, desk_acts.ACTS_FILE)
    act = acts.record("setup", config.brand()["slug"], os.path.basename(path),
                      {"changed": changed, "changes": changes}, base=base, by=desk_acts.role_of(by), path=apath)
    before = brandfile.dumps(bdoc)
    try:
        brandfile.write(new)
        if os.path.exists(streams_md):
            brandfile.apply(streams_md)
    except (OSError, brandfile.Refused) as exc:
        with open(path, "w", encoding="utf-8") as f:  # put the file back as it was: a half change is no change
            f.write(before)
        acts.refused(act["id"], str(exc)[:200], path=apath)
        raise Refused(str(exc))
    acts.applied(act["id"], path=apath)
    return {"id": act["id"], "outcome": "applied", "changed": changed, "base": digest(path)}


ACTIONS = {
    "/api/switch": lambda b: {"switch": set_switch(b.get("stream"), b.get("channel"), b.get("value"), b.get("by"),
                                                   reason=b.get("reason"), confirm=b.get("confirm") is True,
                                                   kind=b.get("kind"), mode=b.get("mode"), preset=b.get("preset"))},
    "/api/pause": lambda b: {"pause": set_pause(b.get("stream"), b.get("paused"), b.get("by"), reason=b.get("reason"),
                                                confirm=b.get("confirm") is True)},
    "/api/setup": lambda b: {"setup": change_setup(b.get("changes"), b.get("base"), b.get("by"),
                                                   confirm=b.get("confirm") is True)},
    "/api/react": lambda b: {"react": react(b.get("id"), b.get("by"))},
    "/api/takedown": lambda b: {"takedown": takedown(b.get("id"), b.get("by"), reason=b.get("reason"))},
    "/api/approve": lambda b: {"act": approve_post(b.get("id"), b.get("by"), reason=b.get("reason"), scope=b.get("scope"))},
    "/api/confirm-argument": lambda b: {"argument": confirm_argument(b.get("id"), b.get("by"))},
    "/api/blog-live": lambda b: {"live": blog_live(b.get("id"), b.get("by"))},
    "/api/schedule": lambda b: {"schedule": schedule_post(b.get("id"), b.get("date"), b.get("by"))},
    "/api/new-post": lambda b: {"post": new_post(b.get("stream"), b.get("channel"), b.get("date"), b.get("text"),
                                                 b.get("title"), b.get("theme") or "", b.get("by"))},
    "/api/approve-reply": lambda b: {"send": approve_reply(b.get("id"), b.get("by"), reason=b.get("reason"),
                                                           scope=b.get("scope"))},
    "/api/terms": lambda b: {"terms_base": write_terms(b.get("tag"), b.get("x_search"), b.get("keywords"), b.get("base"))},
    "/api/watch": lambda b: {"watch_base": watch(b.get("handle"), b.get("base"), b.get("themes") or [],
                                                 b.get("note", ""), b.get("from", "by hand"))},
    "/api/unwatch": lambda b: {"watch_base": unwatch(b.get("handle"), b.get("base"))},
    "/api/dismiss": lambda b: {"watch_base": dismiss(b.get("handle"), b.get("base"))},
    "/api/undismiss": lambda b: {"watch_base": undismiss(b.get("handle"), b.get("base"))},
    "/api/respond": lambda b: {"responses_base": __import__("story").respond(b.get("run_id"), b.get("slide"), b.get("action"),
                                                                           b.get("text"), b.get("base"), b.get("item"))},
    "/api/feedback": lambda b: {"feedback_base": __import__("story").give_feedback(b.get("run_id"), b.get("rating"), b.get("next"),
                                                                             b.get("remember"), b.get("base"))},
    "/api/answer": lambda b: {"questions_base": __import__("story").answer(b.get("id"), b.get("answer"), b.get("base"))},
    "/api/theme": lambda b: add_theme(b.get("tag"), b.get("what"), b.get("different"), b.get("x_search"),
                                      b.get("keywords"), b.get("md_base"), b.get("terms_base")),
    "/api/grade": lambda b: grade_theme(b.get("tag"), b.get("licence"), b.get("basis"), b.get("md_base")),
}


def make_handler(port, token):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "control/1"

        def log_message(self, fmt, *args):
            sys.stderr.write(f"{self.log_date_time_string()} {fmt % args}\n")

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else (json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            why, _role = door(self.headers, port, token, "GET", *door_settings())
            if why:
                return self._send(403, {"error": why})
            path = urllib.parse.urlparse(self.path).path
            if path in ("/", "/index.html", "/classic"):
                app = os.path.join(UI, "index.html")
                page = app if path != "/classic" and os.path.isfile(app) else PAGE
                with open(page, encoding="utf-8") as f:
                    html = f.read().replace("__CONTROL_TOKEN__", token)
                return self._send(200, html, "text/html; charset=utf-8")
            if path.startswith("/assets/"):
                return self._asset(urllib.parse.unquote(path[len("/assets/"):]))
            if path == "/api/state":
                return self._send(200, views.snapshot())
            if path == "/api/published":
                return self._send(200, views.published_posts())
            if path.startswith("/media/"):
                return self._media(urllib.parse.unquote(path[len("/media/"):]))
            return self._send(404, {"error": "not found"})

        def _asset(self, name):
            """One of the built app's own files, by name: nothing outside ui/dist/assets, nothing but its kinds."""
            base = os.path.realpath(os.path.join(UI, "assets"))
            full = os.path.realpath(os.path.join(base, name))
            kind = ASSETS.get(os.path.splitext(full)[1].lower())
            if not full.startswith(base + os.sep) or not kind or not os.path.isfile(full):
                return self._send(404, {"error": "not found"})
            with open(full, "rb") as f:
                return self._send(200, f.read(), kind)

        def _media(self, relpath):
            # Motion only: the text cards beside their storyboards, and the films' renders
            # (the Motion plugin's videos/finals). Nothing else in the repo is served.
            bases = [os.path.realpath(motion.MOTION_DIR), os.path.realpath(os.path.join(motion.FILMS, "finals"))]
            full = os.path.realpath(os.path.join(REPO, relpath))
            inside = any(full.startswith(base + os.sep) for base in bases)
            if not inside or os.path.splitext(full)[1].lower() not in MEDIA or not os.path.isfile(full):
                return self._send(404, {"error": "not found"})
            with open(full, "rb") as f:
                data = f.read()
            return self._send(200, data, mimetypes.guess_type(full)[0] or "application/octet-stream")

        def do_POST(self):
            why, role = door(self.headers, port, token, "POST", *door_settings())
            if why:
                return self._send(403, {"error": why})
            action = ACTIONS.get(urllib.parse.urlparse(self.path).path)
            if not action:
                return self._send(404, {"error": "not found"})
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 64 * 1024)
                body = json.loads(self.rfile.read(length) or b"{}")
                if role is not None and isinstance(body, dict):
                    body["by"] = role  # over Tailscale the signed-in identity is who acts, never the page's say
                return self._send(200, dict(action(body), ok=True))
            except Conflict as e:
                return self._send(409, {"error": str(e)})
            except Refused as e:
                return self._send(400, {"error": str(e)})
            except (ValueError, TypeError) as e:
                return self._send(400, {"error": f"a change the page could not read: {e}"})

    return Handler


def serve(port=DEFAULT_PORT, open_browser=True):
    # The stdlib `secrets` is shadowed by the engine's own scripts/secrets.py.
    token = base64.urlsafe_b64encode(os.urandom(18)).decode()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), make_handler(port, token))
    url = f"http://127.0.0.1:{port}/"
    print(f"control: {url} (local only; Ctrl-C stops it)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def _listening(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def running():
    info = load_json(PIDFILE, {})
    pid, port = info.get("pid"), info.get("port", DEFAULT_PORT)
    if not pid:
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return info if _listening(port) else None


def start(port=DEFAULT_PORT, open_browser=True):
    info = running()
    if info:
        url = f"http://127.0.0.1:{info['port']}/"
        print(f"control: already running at {url} (pid {info['pid']})")
    else:
        if _listening(port):
            print(f"control: port {port} is taken by something else; use --port", file=sys.stderr)
            return 1
        os.makedirs(STATE, exist_ok=True)
        with open(LOGFILE, "a") as log:
            proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), "serve", "--port", str(port), "--no-open"],
                                    stdout=log, stderr=log, stdin=subprocess.DEVNULL, cwd=REPO, start_new_session=True)
        for _ in range(50):
            if _listening(port):
                break
            time.sleep(0.1)
        else:
            print(f"control: the server did not come up; see {rel(LOGFILE)}", file=sys.stderr)
            return 1
        write_json(PIDFILE, {"pid": proc.pid, "port": port, "started": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
        url = f"http://127.0.0.1:{port}/"
        print(f"control: {url} (local only; pid {proc.pid}; stop with `control.py stop`)")
    if open_browser:
        webbrowser.open(url)
    return 0


def stop():
    info = running()
    if not info:
        print("control: not running")
        if os.path.exists(PIDFILE):
            os.remove(PIDFILE)
        return 0
    os.kill(info["pid"], signal.SIGTERM)
    for _ in range(30):
        try:
            os.kill(info["pid"], 0)
        except OSError:
            break
        time.sleep(0.1)
    if os.path.exists(PIDFILE):
        os.remove(PIDFILE)
    print(f"control: stopped (pid {info['pid']})")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="The local control page.")
    ap.add_argument("command", nargs="?", default="start", choices=("start", "stop", "status", "serve"))
    ap.add_argument("--port", type=int, default=int(config.cfg("control.port", DEFAULT_PORT) or DEFAULT_PORT))
    ap.add_argument("--no-open", action="store_true", help="do not open the browser")
    args = ap.parse_args(argv)
    if args.command == "serve":
        return serve(args.port, not args.no_open)
    if args.command == "stop":
        return stop()
    if args.command == "status":
        info = running()
        print(f"control: running at http://127.0.0.1:{info['port']}/ (pid {info['pid']})" if info else "control: not running")
        return 0
    return start(args.port, not args.no_open)


if __name__ == "__main__":
    sys.exit(main())
