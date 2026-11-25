#!/usr/bin/env python3
"""
build_dashboard.py - inline the engine state into the dashboard page.

Reads the queue from the `Content/Calendar/` notes (through scripts/repo.py,
the engine's read path into the content repository) and
state/{signals,decisions,edits,arguments,engagement,claims-review}.json, and
writes state/dashboard.html from dashboard/template.html by replacing the
token /*__STATE__*/ with the state and the text token __BRAND_NAME__ with the
brand's name.

The page carries two things and nothing else (owner's direction, 2026-11-06):
the posts, and what is live. A post is one card: date, channel, theme, where
it stands in one phrase (waiting for you, ready to approve, approved, live,
needs a fix, your edit needs a decision), the hook and two lines of the text;
the reasons (why this post, the checks and their verdict, what is on the desk)
open behind "Read more". What is live is the listening summary, the replies
drafted and waiting to be placed (with the post to open and a copy button),
what is held for a person, and what people are saying. Until the checkout is
set up, the setup steps (setup_state.py) show above the posts with the next
command. No run, no job, no schedule and no scorecard is on the page: those
are the console's (`engine.py status`, `engine.py results`) and the desk's.
So this script inlines only what the page reads; the run log, the inventory,
the metrics and the per-job digest stay in `state/` and on the desk.

The posts are built from the notes, not from `state/queue.json`: the note is
the record and the JSON is a derived index, so a page built here and an index
rebuilt by `repo.py --index` cannot disagree.

The page is a local file, opened in a browser, and is never published (owner,
2026-11-06: the claude.ai artifact mirror was deleted). It was the decision
store until milestone 2; it is not one any more. Alpha's acts are recorded on the desk (`Tooling/desk/`,
which writes `state/desk.db`) and reach `state/decisions.json`,
`state/edits.json` and `state/arguments.json` through
`scripts/desk_sync.py --pull`, which this script then inlines.

So the page takes no decision. When it was published with a database, its
buttons wrote decisions to a store nothing reads - which is exactly what happened to three of Alpha's
approvals during the migration, recovered by hand and logged in `runs.json`.

Each post compares the edit stored for it against the note as it stands now, so
an edit the vault has moved past is shown as "your edit needs a decision"
rather than as applied. That is the same three-way test scripts/apply_edits.py
makes; the page states it, the script acts on it, and neither version is
written over the other.
"""
import datetime as dt
import json
import os
import re
from urllib.parse import urlparse

import config
import memory
import repo
import setup_state

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
STATE = paths.state()
DASH = os.path.join(ENGINE, "dashboard")
OUT = os.path.join(STATE, "dashboard.html")


def load(name, default):
    p = os.path.join(STATE, name)
    if not os.path.exists(p):
        return default
    with open(p) as f:
        return json.load(f)


def main():
    b = brand()
    state = {
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "brand": b,
        "signals": load("signals.json", {"findings": [], "per_theme": {}, "sources": []}),
        "queue": repo.load_items(),
        "decisions": load("decisions.json", {}),
        # Alpha's saved edits, as desk_sync.py --pull wrote them. A read-only
        # page has no database: without this it would show neither the edit nor
        # the conflict the distributor is waiting on.
        "edits": load("edits.json", {}),
        # Alpha's argument-line acts, the same way. A post treats a confirmation
        # as current only while it names the hook now on the card, so a page
        # without this shows every line as never confirmed - the one state a
        # read-only view cannot be used to correct.
        "arguments": load("arguments.json", {}),
        # The replies drafted for what is live, and the ledger of those placed.
        "engagement": load("engagement.json", {"proposals": [], "ledger": []}),
        # The supersession and decay check (claims_check.py): notes whose cited
        # claim moved after the gate read them, for a person to update, annotate
        # or retire; shown under "Waiting for you". The engine never edits a
        # published piece.
        "claims_review": load("claims-review.json", {"items": []}),
        # Where this checkout stands between clone and running engine
        # (setup_state.py): the page shows the steps and the next command
        # until every required one is done, then hides them.
        "setup": setup_block(),
    }
    with open(os.path.join(DASH, "template.html")) as f:
        tpl = f.read()
    blob = json.dumps(state, ensure_ascii=False).replace("</", "<\\/")
    html = (tpl.replace("/*__STATE__*/null", blob)
               .replace("__BRAND_NAME__", _html(b["name"]))
               .replace("__OWN_X__", _html(b["x_handle"] or "the brand's own X handle (handles.md)")))
    out = OUT
    with open(out, "w") as f:
        f.write(html)
    posts = state["queue"]
    # The same id the page gives a reply (`proposalId` in template.html).
    pid = lambda p: "C-" + str(p.get("finding_id", "")) + "-" + re.sub(r"[^A-Za-z0-9_]", "", str(p.get("author", "")))  # noqa: E731
    open_replies = [p for p in state["engagement"].get("proposals", [])
                    if (state["decisions"].get(pid(p)) or {}).get("status", "proposed") == "proposed"]
    print(f"wrote {out} ({len(html)//1024} KB): {len(posts)} posts, {len(open_replies)} replies to place, "
          f"{len(state['signals'].get('findings', []))} heard, setup {state['setup'].get('done', 0)} of {state['setup'].get('total', 0)}")


def setup_block():
    """setup_state.current(); a failure there must not stop the page."""
    try:
        return setup_state.current()
    except Exception as e:  # noqa: BLE001
        return {"complete": True, "done": 0, "total": 0, "next": None, "steps": [], "error": str(e)}


def _html(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def brand():
    """The brand the page is built for: engine.json's block, the own X handle
    from handles.md (blank when not recorded, never guessed), the site host
    from params.site.post_url (blank for the template's example.com). The page
    carries nothing of a brand that the memory and engine.json of this checkout
    do not say: state/dashboard.html is gitignored and rebuilt on every cycle."""
    b = config.brand()
    x_handle = ""
    for row in memory.load_handles()["own_channels"]:
        if row.get("platform", "").strip().lower() == "x" and re.fullmatch(r"@\w+", memory._handle(row.get("handle", ""))):
            x_handle = memory._handle(row["handle"])
    post_url = str(config.cfg("site.post_url", "") or "")
    host = urlparse(post_url).netloc.lower().removeprefix("www.")
    if host == "example.com":
        host = ""
    return {"name": b["name"], "slug": b["slug"], "x_handle": x_handle, "site_host": host, "post_url": post_url}


if __name__ == "__main__":
    main()
