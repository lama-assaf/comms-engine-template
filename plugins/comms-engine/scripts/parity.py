#!/usr/bin/env python3
"""
parity.py - does the Composio write driver set do what the native one does, run for run.

The sender (autopilot.py) sends through channels.send() with a write driver chosen by
`channels.write_driver.<stream>`: `native` (xurl, linkedin_api) or `composio`
(channels.x_driver / linkedin_driver). Before the direct code is retired, the two must
behave alike at run level, not just call by call. This script runs the sender's `post`
and `links` steps twice over the same due posts, once per driver set, with the platform
layer FAKED (the subprocess that would start xurl, the Composio HTTP client, and the
LinkedIn API calls), on throwaway copies of the ledger, lifecycle, acts and sends
records, with the calendar notes held in memory. Nothing is sent and nothing real is
written. It then asserts the two runs

  - select and refuse the same posts (the same log lines, the same ledger ids),
  - issue the same kinds of send in the same order,
  - write the same ledger entries, sends lines, lifecycle lines and publish log, and
  - that each platform call carries the same text, the same account (the stream's own)
    and the same reply target.

Posts come from two places: `fixture_case()` (notes in the live shape covering an engine
item on both channels, team posts, a link in the body, a stale post, a future one, another
stream's, a duplicate, a failing send, a first reply with the article link, and a
link-reply owed on an earlier post) and the live notes (`Content/Calendar/` with the
live records copied; what is `scheduled` in the lifecycle is due, and `--rehearse N`
schedules the first N X and LinkedIn teasers of the brand that are not sent yet for today,
in the throwaway copy, so the real gates and the real ledger are exercised).

The caveat is stated, not hidden: the native X path also asks `x_ready()` (an xurl login
check) before a send, which has no composio equivalent; it is faked ready here. Comparing
live result sets is the two-week live parity that precedes retiring the direct code.

  engine parity --dry                 # fixtures, then the live notes
  engine parity --dry --rehearse 6    # the live notes, six teasers scheduled for today
  engine parity --dry --fixtures --json

Exit 0 when every case matches, 1 on any difference. `--dry` is required: this script
has no other mode.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
STATE = paths.state()
sys.path.insert(0, HERE)

import acts  # noqa: E402
import autopilot as ap  # noqa: E402
import channels  # noqa: E402
import desk_acts  # noqa: E402
import guardrails  # noqa: E402
import lifecycle  # noqa: E402
import linkedin_api  # noqa: E402
import repo  # noqa: E402

DRIVERS = ("native", "composio")
RECORDS = (channels.LEDGER_FILE, channels.SENDS_LOG, channels.LIFECYCLE_FILE, channels.ACTS_FILE)
FAIL_MARK = "zzfail"
OTHER_STREAM = "Elsewhere"
LI_CONFIG = {"LINKEDIN_ORG_ID": "555"}
#: log lines that say a row was passed over, and why; the "selected" rows are the ones that were sent
REFUSAL_PREFIXES = ("refused", "hold", "stale", "duplicate", "unsure", "changed", "blocked", "skip")


# ------------------------------------------------------------------ notes in the live shape


def note(eid, title, day, stream=None, x="", linkedin="", post="", by="theme-writer", status="Idea"):
    """One item's notes in the shape `repo.scan_notes()` returns: the post note and its teasers note."""
    slug = repo.slugify(title)
    cta = repo.post_url(slug)
    fm = {"title": title, "date": day.isoformat() if day else "", "status": status, "stream": stream or ap.STREAM_NAME,
          "platform": "Blog", "slug": slug, "engine_id": eid, "theme": "", "cta": cta, "partner_tags": [],
          "drafted_by": by, "alpha_status": "approved", "gate": {"verdict": "pass"}}
    fm_t = dict(fm, title=f"{title} - teasers", platform="LinkedIn", slug="")
    return {"Blog": (f"{title}.md", fm, post),
            "LinkedIn": (f"{title} - teasers.md", fm_t, repo.teaser_body(linkedin, x, repo.tagline_for(fm), cta))}


# ------------------------------------------------------------------ the platform fake


class PlatformFake:
    """The subprocess, Composio HTTP and LinkedIn layers, faked. Records one normalised call per platform write.

    A call is `{platform, op, text, account, target}`: `account` is the stream's own slug for X
    (xurl's `--app`, or the Composio alias minus its channel suffix) and the author URN for
    LinkedIn; `target` is the post id a reply answers (X) or the post URN a comment answers.
    Anything else that reaches the subprocess is recorded under `unexpected`, never run.
    """

    def __init__(self):
        self.calls, self.unexpected = [], []
        self._x, self._li = 9000, 7000

    def _fail(self, text):
        return FAIL_MARK in (text or "")

    # -- subprocess.run
    def run(self, cmd, *args, **kwargs):
        cmd = list(cmd)
        if cmd and cmd[0] == "npx" and "@xdevplatform/xurl" in cmd:
            return self._xurl(cmd)
        self.unexpected.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="parity fake: not a call this script allows")

    def _xurl(self, cmd):
        rest = cmd[cmd.index("--app"):]
        app, verb, params = rest[1], rest[2], rest[3:]
        if verb == "post":
            call = {"platform": "X", "op": "post", "text": params[0], "account": app, "target": None}
        elif verb == "reply":
            call = {"platform": "X", "op": "reply", "text": params[1], "account": app, "target": params[0]}
        else:
            self.unexpected.append(cmd)
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="unexpected xurl verb")
        return self._answer_x(cmd, call)

    def _answer_x(self, cmd, call):
        self.calls.append(call)
        if self._fail(call["text"]):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="platform refused (fake)")
        self._x += 1
        body = {"data": {"id": str(self._x)}}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(body), stderr="")

    # -- channels._http, the Composio REST layer
    def http(self, stream, method, path, query=None, body=None, opener=None):
        if method == "GET" and path == "/api/v3.1/connected_accounts":
            return {"items": [{"id": f"ca_{stream}-{ch}", "alias": f"{stream}-{ch}", "status": "ACTIVE",
                               "toolkit": {"slug": tk}, "auth_config": {"id": "ac_fixture"}}
                              for ch, tk in (("x", "twitter"), ("linkedin", "linkedin"))], "next_cursor": None}
        prefix = "/api/v3.1/tools/execute/"
        if method == "POST" and path.startswith(prefix):
            return self._composio(path[len(prefix):], body)
        self.unexpected.append([method, path])
        raise channels.ChannelError("parity fake: not a call this script allows")

    def _composio(self, slug, request):
        args = request["arguments"]
        account = request["connected_account_id"][len("ca_"):]
        if slug == channels.X_POST_SLUG:
            reply_to = args.get("reply_in_reply_to_tweet_id")
            call = {"platform": "X", "op": "reply" if reply_to else "post", "text": args["text"],
                    "account": account.rsplit("-", 1)[0], "target": reply_to}
            self.calls.append(call)
            if self._fail(call["text"]):
                raise channels.ChannelError("platform refused (fake)")
            self._x += 1
            return {"successful": True, "error": None, "data": {"data": {"id": str(self._x)}}}
        if slug == channels.LINKEDIN_POST_SLUG:
            call = {"platform": "LinkedIn", "op": "post", "text": args["commentary"], "account": args["author"],
                    "target": None}
        elif slug == channels.LINKEDIN_COMMENT_SLUG:
            call = {"platform": "LinkedIn", "op": "comment", "text": args["message"]["text"],
                    "account": args["actor"], "target": args["object"]}
        else:
            self.unexpected.append(["execute", slug])
            raise channels.ChannelError("unexpected slug")
        self.calls.append(call)
        if self._fail(call["text"]):
            raise channels.ChannelError("platform refused (fake)")
        self._li += 1
        urn = f"urn:li:share:{self._li}" if call["op"] == "post" else f"urn:li:comment:{self._li}"
        return {"successful": True, "error": None, "data": {"urn": urn}}

    # -- linkedin_api, the native LinkedIn path
    def create_post(self, config, payload):
        call = {"platform": "LinkedIn", "op": "post", "text": payload["commentary"], "account": payload["author"],
                "target": None}
        self.calls.append(call)
        if self._fail(call["text"]):
            raise linkedin_api.LinkedInError("platform refused (fake)")
        self._li += 1
        urn = f"urn:li:share:{self._li}"
        return {"url": linkedin_api.post_url(urn), "urn": urn}

    def create_comment(self, config, urn, payload):
        call = {"platform": "LinkedIn", "op": "comment", "text": payload["message"]["text"],
                "account": payload["actor"], "target": urn}
        self.calls.append(call)
        if self._fail(call["text"]):
            raise linkedin_api.LinkedInError("platform refused (fake)")
        self._li += 1
        return {"urn": f"urn:li:comment:{self._li}"}


FIXTURE_DAILY_CAP = {"X": 2, "LinkedIn": 3}


def _fixture_check(stream, channel, at, today, week, last, *rest, **kw):
    """The fixture case's guardrail: open, except that a channel at its fixture cap today is full.
    The registry's own caps are exercised by the notes case, which keeps the real check."""
    cap = FIXTURE_DAILY_CAP.get(channel, 2)
    if today >= cap:
        return False, f"{channel} is at the fixture's daily cap of {cap}"
    return True, ""


# ------------------------------------------------------------------ one run


def _seed(state, post_id, platform, text, day, sent=None):
    """Put a channel post in the throwaway lifecycle: gated, approved by Alpha, scheduled; sent when `sent` is a URL."""
    lpath, apath = os.path.join(state, channels.LIFECYCLE_FILE), os.path.join(state, channels.ACTS_FILE)
    key = platform.lower()
    digest = channels.text_hash(key, text)
    lifecycle.gate(post_id, digest, "v1", stream=ap.STREAM, path=lpath)
    act = acts.record("decision", ap.STREAM, post_id, {"decision": "approve"}, base=digest, by="alpha", path=apath)
    acts.applied(act["id"], path=apath)
    lifecycle.decide(post_id, act["id"], acts_path=apath, stream=ap.STREAM, path=lpath)
    lifecycle.schedule(post_id, day.isoformat(), lambda: (True, ""), stream=ap.STREAM, path=lpath)
    if sent:
        at = "2026-11-04T10:00:00Z"
        ledger = channels._load_ledger(state)
        ledger["sends"][post_id] = {"page_id": post_id, "platform": channels.DISPLAY[key], "title": post_id, "hash": digest,
                                    "state": "sent", "at": at, "stream": ap.STREAM_NAME, "kind": "post", "url": sent,
                                    "urn": None}
        channels._save_ledger(state, ledger)
        lifecycle.sent(post_id, {"id": post_id, "sent_at": at, "url": sent}, stream=ap.STREAM, path=lpath)


def _live(state, eid, slug):
    """Mark an item's article live in the throwaway acts, as the control page's blog-live act does."""
    apath = os.path.join(state, channels.ACTS_FILE)
    act = acts.record(desk_acts.BLOG_LIVE, ap.STREAM, eid, {"url": repo.post_url(slug), "slug": slug}, by="alpha",
                      path=apath)
    acts.applied(act["id"], path=apath)


def _norm_ledger(ledger):
    return {k: {f: v for f, v in row.items() if f != "error"} for k, row in sorted(ledger["sends"].items())}


def _norm_sends(lines):
    return [{f: v for f, v in row.items() if f != "reason" or row.get("outcome") == "refused"} for row in lines]


def _norm_log(line):
    """A failure line keeps its row and drops the driver's own error text, which differs by design."""
    m = re.match(r"^(failed \S+ .*?): .*$", line)
    return m.group(1) if m else line


def run_one(driver, case, state_src=None, today=None, now=None, keep_guardrail=False):
    """Run the sender's post and links steps once through `driver` ('native' or 'composio').

    `case` is a dict: notes (as `repo.scan_notes()` returns them), seed (a callable(state) or
    None). The records are copied from `state_src` (when given) into a throwaway directory, the
    platform layer is the fake, the notes are the case's. Returns the trace of what happened."""
    if driver not in DRIVERS:
        raise ValueError(f"driver must be one of {DRIVERS}")
    today = today or case.get("today") or dt.date(2026, 11, 5)
    now = now or case.get("now") or dt.datetime(2026, 11, 5, 10, 0, tzinfo=dt.timezone.utc)  # a Thursday, in sending hours
    work = tempfile.mkdtemp(prefix=f"parity-{driver}-")
    state = os.path.join(work, "state")
    os.makedirs(state)
    log, fake = [], PlatformFake()
    try:
        if state_src:
            for name in RECORDS:
                src = os.path.join(state_src, name)
                if os.path.exists(src):
                    shutil.copyfile(src, os.path.join(state, name))
        if case.get("seed"):
            case["seed"](state)
        with contextlib.ExitStack() as stack:
            po = lambda *a, **kw: stack.enter_context(mock.patch.object(*a, **kw))  # noqa: E731
            po(ap, "DRY", False)
            po(ap, "TODAY", today)
            po(ap, "NOW_DT", now)
            po(ap, "NOW", now.isoformat())
            po(ap, "LEDGER_FILE", os.path.join(state, channels.LEDGER_FILE))
            po(ap, "PUBLISH_LOG", os.path.join(work, "publish-log.json"))
            po(ap, "AUTO_STATE", os.path.join(work, "autopilot-state.json"))
            po(ap, "LOG_FILE", os.path.join(work, "autopilot.log"))
            stack.enter_context(mock.patch.dict(ap.LEGACY, {}, clear=True))
            po(ap, "log", lambda message: log.append(message))
            po(ap, "x_ready", lambda: True)
            po(ap, "_WRITE_DRIVER_LOGGED", [])
            po(ap, "load_notes", lambda: case["notes"])
            if not keep_guardrail:
                po(ap, "guardrail", lambda channel: (True, ""))
                po(guardrails, "check", _fixture_check)
            po(channels, "write_driver", lambda stream: (driver, None))
            po(channels, "composio_key", lambda stream: "fixture-not-a-key")  # the platform layer is faked, so is the key
            stack.enter_context(mock.patch.dict(channels._DRIVERS))
            po(subprocess, "run", fake.run)
            po(channels, "_http", fake.http)
            channels.clear_cache()
            po(linkedin_api, "settings", lambda stream=None: dict(LI_CONFIG))
            po(linkedin_api, "create_post", fake.create_post)
            po(linkedin_api, "create_comment", fake.create_comment)
            ledger = ap.load_json(ap.LEDGER_FILE, {"sends": {}}) or {"sends": {}}
            publish_log = {"entries": []}
            posted = ap.step_post(ledger, publish_log)
            linked = ap.step_links(ledger)
            final = channels._load_ledger(state)
            sends = _norm_sends(channels.sends(state))
            life = {pid: [(r["to"], r.get("date")) for r in lifecycle.lines(pid, os.path.join(state, channels.LIFECYCLE_FILE))]
                    for pid in sorted(lifecycle.fold(os.path.join(state, channels.LIFECYCLE_FILE)))}
        norm = [_norm_log(m) for m in log]
        return {
            "driver": driver,
            "log": norm,
            "refused": [m for m in norm if m.split(" ", 1)[0] in REFUSAL_PREFIXES],
            "sent_order": [(r["id"], r["kind"]) for r in sends if r["outcome"] == "sent"],
            "kinds": [(c["platform"], c["op"]) for c in fake.calls],
            "calls": fake.calls,
            "unexpected": fake.unexpected,
            "ledger": _norm_ledger(final),
            "sends": [{k: v for k, v in r.items() if k != "at"} for r in sends],
            "lifecycle": life,
            "publish_log": [{k: v for k, v in e.items() if k != "published_at"} for e in publish_log["entries"]],
            "counts": {"posted": posted, "links": linked},
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def compare(native, composio):
    """The differences between two traces, as readable lines; empty when the runs match."""
    out = []
    for key in ("log", "refused", "sent_order", "kinds", "calls", "ledger", "sends", "lifecycle",
                "publish_log", "counts"):
        if native[key] != composio[key]:
            out.append(f"{key}: native {json.dumps(native[key], default=str)[:600]}\n"
                       f"{' ' * len(key)}  composio {json.dumps(composio[key], default=str)[:600]}")
    for t in (native, composio):
        if t["unexpected"]:
            out.append(f"{t['driver']}: a call outside the allowed platform layer reached the fake: {t['unexpected']}")
    return out


def check(case, state_src=None, **kw):
    """Run both driver sets over the case; `(native trace, composio trace, differences)`."""
    n = run_one("native", case, state_src, **kw)
    c = run_one("composio", case, state_src, **kw)
    return n, c, compare(n, c)


# ------------------------------------------------------------------ the cases


def fixture_case(today=None):
    """Notes in the live shape covering each way the sender selects, refuses and sends."""
    today = today or dt.date(2026, 11, 5)
    late = today - dt.timedelta(days=9)
    texts = {
        "e1:x": "An engine post about one idea, said plainly.",
        "e1:linkedin": "An engine post for LinkedIn about the same idea.",
        "t1:x": "A team teaser, one sentence, no link.",
        "t2:linkedin": "A team teaser written for LinkedIn readers.",
        "t3:x": "A team teaser with a link https://www.example.com/insights/x in the body.",
        "t4:x": "A team teaser that is too old to post.",
        "t5:x": "A team teaser for a later day.",
        "t6:x": "Another stream's post, never touched.",
        "t7:x": "A team teaser, one sentence, no link.",
        "t8:linkedin": f"A team teaser whose platform call fails {FAIL_MARK}.",
        "t9:linkedin": "A team teaser that goes out after a failure.",
        "t99:x": "A team teaser that finds the day already full.",
        "old1:x": "An earlier post, already out.",
    }
    team = [("t1", "Team plain", today, None), ("t2", "Team on LinkedIn", today, None),
            ("t3", "Team with a link", today, None), ("t4", "Team stale", late, None),
            ("t5", "Team future", today + dt.timedelta(days=3), None), ("t6", "Another stream", today, OTHER_STREAM),
            ("t7", "Team duplicate", today, None), ("t8", "Team platform failure", today, None),
            ("t9", "Team after the failure", today, None), ("t99", "Team over the daily cap", today, None)]
    notes = {"e1": note("e1", "Engine one", today, x=texts["e1:x"], linkedin=texts["e1:linkedin"], post="The article."),
             "old1": note("old1", "Later", late, x=texts["old1:x"], post="An article that went live later.")}
    for eid, title, day, stream in team:
        x, li = texts.get(f"{eid}:x", ""), texts.get(f"{eid}:linkedin", "")
        notes[eid] = note(eid, title, day, stream=stream, x=x, linkedin=li, by=repo.TEAM_BY)
    days = {eid: day for eid, _t, day, _s in team}

    def seed(state):
        _live(state, "e1", "engine-one")
        _live(state, "old1", "later")
        for cid, text in texts.items():
            eid, key = cid.split(":")
            if cid == "old1:x":
                _seed(state, cid, "X", text, late, sent="https://x.com/i/web/status/777")
            elif eid != "t6":  # another stream's post is never scheduled for this one
                _seed(state, cid, channels.DISPLAY[key], text, days.get(eid, today))

    return {"name": "fixtures", "notes": notes, "seed": seed, "today": today}


def notes_case(cal=None, rehearse=0, today=None):
    """The live calendar notes. What is `scheduled` in the copied lifecycle is due; with `rehearse`
    N, the first N X and LinkedIn teasers of the brand that are still drafts are scheduled for today
    in the throwaway records."""
    saved = repo.CAL
    try:
        if cal:
            repo.CAL = cal
        notes = repo.scan_notes()
    finally:
        repo.CAL = saved
    today = today or dt.date.today()
    picks = []
    for eid, (item, _fm, _ft) in sorted(ap.note_items(notes).items(), key=lambda kv: (kv[1][0]["slot"]["date"], kv[0])):
        if item.get("stream") not in ap.STREAM_NAMES:
            continue
        for key, field, platform in desk_acts.CHANNELS:
            if len(picks) < rehearse and str(item.get(field) or "").strip():
                picks.append((desk_acts.channel_id(eid, key), platform, item[field].strip()))

    def seed(state):
        lpath = os.path.join(state, channels.LIFECYCLE_FILE)
        for cid, platform, text in picks:
            if lifecycle.state(cid, lpath) == "draft":
                _seed(state, cid, platform, text, today)

    return {"name": "notes" + (f" (rehearsing {len(picks)})" if rehearse else ""), "notes": notes,
            "seed": seed if picks else None, "today": today}


# ------------------------------------------------------------------ main


def report(case, native, composio, diffs):
    sent = len(native["sent_order"])
    lines = [f"[{case['name']}] {len(native['log'])} log lines, {sent} sent, {len(native['refused'])} passed over, "
             f"{len(native['kinds'])} platform calls: " + ("MATCH" if not diffs else "DIFFERENT")]
    for kind in native["kinds"]:
        lines.append("    " + " ".join(kind))
    for d in diffs:
        lines.append("  ! " + d)
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--dry", action="store_true", help="required: nothing real is ever called or sent")
    p.add_argument("--fixtures", action="store_true", help="only the fixture case")
    p.add_argument("--notes", action="store_true", help="only the live calendar notes")
    p.add_argument("--rehearse", type=int, default=0, metavar="N", help="schedule N of the brand's teasers for today")
    p.add_argument("--now", help="the send time (ISO, UTC) for the notes case, default now")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    if not args.dry:
        print("parity.py has only a dry mode: pass --dry", file=sys.stderr)
        return 2
    cases = []
    if not args.notes:
        cases.append((fixture_case(), {}, False))
    if not args.fixtures:
        now = dt.datetime.fromisoformat(args.now) if args.now else dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        try:
            cases.append((notes_case(rehearse=args.rehearse, today=now.date()),
                          {"state_src": STATE, "today": now.date(), "now": now}, True))
        except OSError as exc:
            print(f"notes case skipped: {exc}", file=sys.stderr)
    failed, out = False, []
    for case, kw, live in cases:
        n, c, diffs = check(case, keep_guardrail=live, **kw)
        failed = failed or bool(diffs)
        out.append({"case": case["name"], "match": not diffs, "differences": diffs, "native": n, "composio": c})
        if not args.json:
            print(report(case, n, c, diffs))
    if args.json:
        print(json.dumps(out, indent=1, default=str))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
