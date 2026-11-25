#!/usr/bin/env python3
"""
publish.py - the website-first publish path for one Alpha-approved queue item.

  python3 publish.py Q-2026-01-05-example-1                # write the vault notes
  python3 publish.py Q-... --webhook                        # also POST the site webhook (engine.json site.webhook_url; needs <ENV_PREFIX>WEBHOOK_SECRET)
  python3 publish.py Q-... --force                          # skip the alpha_status check (dry runs only)

Note-writing itself lives in repo.py, which already wrote this item at
`status: Idea` when it was drafted. This is the second of its two calls:

  repo.write_item(item, "Ready")
    Content/Calendar/<title>.md              the full post, status Ready, the brand's stream, platform Blog
    Content/Calendar/<title> - teasers.md    LinkedIn + X teasers with tag line and CTA (platform LinkedIn)

The item itself is read from that note through `repo.load_items()`, and the
publish record - `published_to`, `published_at`, `vault_note` - is written back
onto it. `state/queue.json` is a derived index and is rebuilt from the notes
here, never edited: an edit to it would not survive the next rebuild.

An item Alpha edited on the desk is refused twice over until a person has
cleared it: while the edit is still in conflict with the note (`apply_edits.py`
wrote nothing, and publishing would drop one of the two versions), and while the
gatekeeper's verdict on the note is older than the text the edit left behind. An
edit is a new draft.

The site reads the published-posts feed (`engine.py export-published`, built from the
notes). This script never sets Published: marking the article live on the control
page (the blog-live act) is the manual release the deck requires.
"""
import argparse
import datetime as dt
import json
import re
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
REPO = paths.instance()
STATE = paths.state()

sys.path.insert(0, HERE)
import apply_edits  # noqa: E402  - the desk-edit reconciliation, next to this file
import repo  # noqa: E402  - the engine's note writer, next to this file


# the calendar snapshot, written by scripts/autopilot.py
SNAPSHOT = os.path.join(paths.state(), "calendar-snapshot.json")


def registry_check(item):
    """The registry's guardrails for the Blog row this script makes Ready.

    Judged at the slot's planned send time, 09:00 in the brand's timezone
    (engine.json autopilot.timezone, guardrails.TZ) on the note's
    date (today when it has none), not at the moment someone runs the script:
    quiet hours, caps and spacing govern when a piece goes out, and an
    approval made in the evening is not a send in the evening. The item's own
    note is not counted against its cap.
    """
    import zoneinfo
    import guardrails
    import memory
    try:
        slug = memory.slug_for(item.get("stream") or "")
        day = repo.as_date((item.get("slot") or {}).get("date") or dt.date.today().isoformat())
        if not isinstance(day, dt.date):
            day = dt.date.today()
        at = dt.datetime.combine(day, dt.time(9, 0), tzinfo=zoneinfo.ZoneInfo(guardrails.TZ))
        today, week, last_blog = guardrails.counts_from_notes(memory.stream(slug)["name"], "Blog", at,
                                                              exclude_engine_id=item.get("id"))
        return guardrails.check(slug, "Blog", at, today, week, last_blog)
    except memory.SharedMemoryError as e:
        return False, f"{item.get('stream')!r}: {e}"


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def already_published(item, snapshot_path=None):
    """The Published calendar row that is this item, or None: a Blog, LinkedIn
    or X row whose title equals the item's title, or whose slug equals the
    item's slug or is the slug of the item's title."""
    path = snapshot_path or SNAPSHOT
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        rows = json.load(f).get("rows", [])
    title, slugs = _norm(item.get("title")), {item.get("slug") or "", repo.slugify(item.get("title", ""))} - {""}
    for r in rows:
        if r.get("status") != "Published":
            continue
        rslug = str(r.get("slug") or "")
        base = re.sub(r"-(linkedin|x)$", "", rslug)
        if (title and _norm(r.get("title")) == title) or (base and base in slugs):
            return r
    return None


def site_webhook():
    """POST the site webhook (engine.json site.webhook_url, bearer <ENV_PREFIX>WEBHOOK_SECRET) so the
    site rebuilds. Returns what happened in a few words; raises on a failed call."""
    import config
    secret_name = config.env_name_for("WEBHOOK_SECRET")
    secret = os.environ.get(secret_name)
    hook_url = str(config.cfg("site.webhook_url", "") or "")
    if not secret:
        return f"skipped: {secret_name} not set"
    if not hook_url:
        return "skipped: site.webhook_url is empty in engine.json"
    req = urllib.request.Request(hook_url, data=b"{}",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return f"sent {resp.status}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("id")
    ap.add_argument("--webhook", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    # The item is read from its calendar note, not from state/queue.json: the
    # note is the record and the JSON is a derived index.
    item = next((q for q in repo.load_items() if q["id"] == args.id), None)
    if not item:
        sys.exit(f"no calendar note for {args.id}. Draft it into the vault first: python3 repo.py {args.id}")
    if item.get("alpha_status") != "approved" and not args.force:
        sys.exit(f"{args.id} is '{item.get('alpha_status')}', not approved. Nothing written.")
    if item.get("gate", {}).get("verdict") == "block" and not args.force:
        sys.exit(f"{args.id} is blocked by the claim gate. Nothing written.")

    # An edit Alpha made on the desk is a new draft, and this is the second
    # place the never-clobber rule bites. Two refusals, both cleared by a
    # person, never by this script:
    #
    #   * an edit still in conflict - the note moved after Alpha saved, so
    #     apply_edits.py wrote nothing. Publishing now would ship the version
    #     Alpha did not write and drop the one they did. Resolve it first:
    #     apply_edits.py <id> --prefer desk|vault.
    #   * an edit that landed but has not been re-read - the gatekeeper's
    #     verdict on the note is older than the text now on it.
    edit = apply_edits.load_edits().get(args.id)
    if edit and not args.force:
        state = apply_edits.status_of(item, edit)
        if state != apply_edits.RESOLVED:
            sys.exit(f"{args.id} has an unresolved desk edit ({state}). Nothing written. "
                     f"Apply or drop it first: python3 apply_edits.py {args.id} --prefer desk|vault")
    stale = apply_edits.stale_gate(item)
    if stale and not args.force:
        reviewed = (item.get("gate") or {}).get("reviewed_at") or "never"
        sys.exit(f"{args.id} was edited on the desk ({stale.get('resolution')} {stale.get('at')}) and the "
                 f"gate verdict on it is from {reviewed}. An edit is a new draft: have the gatekeeper "
                 f"re-read it before publishing. Nothing written.")

    # Already live through another path: a desk approval made earlier can still
    # be standing for a piece that has gone out since.
    # The calendar snapshot is built from the notes; a Published row with
    # this item's title or slug means the piece is out, and writing it Ready
    # again would put a second copy on the calendar.
    dup = already_published(item)
    if dup and not args.force:
        sys.exit(f"{args.id} is already Published on the calendar as \"{dup['title']}\" "
                 f"({dup.get('platform')}, {dup.get('date') or 'no date'}). Nothing written. "
                 f"Record it on the desk as held or rejected so the approval stops standing.")

    # The registry's guardrails (A13): a stream whose autopilot is "nothing",
    # a drafts-only channel, quiet hours or a cap refuse here with the rule
    # quoted. The Blog row is what this script makes Ready; the teasers follow
    # on their own channels through the same check when they are staged.
    ok, why = registry_check(item)
    if not ok and not args.force:
        sys.exit(f"{args.id} refused by the registry guardrails: {why} Nothing written.")

    paths = repo.write_item(item, "Ready")
    post_path, teaser_path = paths["post"], paths["teasers"]

    print(f"wrote {os.path.relpath(post_path, REPO)}")
    print(f"wrote {os.path.relpath(teaser_path, REPO)}")

    published_to = ["vault"]
    if args.webhook:
        hook = site_webhook()
        print("webhook", hook)
        if hook.startswith("sent"):
            published_to.append("webhook")

    # The publish record goes onto the note, where the item lives; the index is
    # then rebuilt from the notes. Writing it to queue.json would not survive
    # the next rebuild.
    published_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    repo.set_fields(args.id, {"status": "Ready",
                              "published_to": published_to,
                              "published_at": published_at,
                              "vault_note": os.path.relpath(post_path, REPO)})
    print(f"index {os.path.relpath(repo.write_index(), REPO)}")

    runs_p = os.path.join(STATE, "runs.json")
    runs = json.load(open(runs_p)) if os.path.exists(runs_p) else []
    runs.append({"run_id": dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"), "step": "publish", "item": args.id,
                 "at": published_at, "published_to": published_to,
                 # A13: every run entry names the stream, the agent, the action and the target
                 "stream": item.get("stream", ""), "agent": "publish.py", "action": "ready-row",
                 "target": ", ".join(published_to)})
    with open(runs_p, "w") as f:
        json.dump(runs, f, indent=1)


if __name__ == "__main__":
    main()
