#!/usr/bin/env python3
"""
desk_acts.py - the desk's decisions, edits, argument lines and reviews as acts.

`desk_sync.py --pull` keeps writing `state/decisions.json`, `edits.json` and
`arguments.json` for `apply_edits.py` and the cycle. This module is the new part
of the pull: each desk row becomes one act in `state/acts.jsonl` (acts.py), and a
decision act is then applied to the post's lifecycle (lifecycle.py):

  approved  gate (if still a draft; a `block` verdict refuses, `pass-with-edits` is allowed, the
            one rule lifecycle.gate_refusal holds and channels.send() applies) -> the act is applied -> decide -> schedule for the
            note's date, within the guardrails. It never sends; the sender does.
            The same approval also schedules one lifecycle id per channel the note has a teaser for,
            `<id>:linkedin` and `<id>:x`, each with its own applied approve act for the teaser's
            `channels.text_hash`, so each channel is sent, and refused, on its own.
  held / rejected / rewrite / argument line / review   recorded, applied (nothing moves)
  edit      applied while the note still hashes to the edit's base; else skipped: moved

`reschedule()` moves a scheduled post, and its channel ids, to a new date before the send;
once any of them is sent, the date stays.

`engine_approve()` is the approval with no person in it, for a stream whose post mode a person
switched to `auto` (switches.py): the gate's verdict is `pass`, every channel the item sends on
is on `auto`, the verdict was stamped by review.py for this very text on two reviewers who agreed
(review.approvable: every claim sentence on its own cite, checked in code), the stream is not
paused and no person has held, rejected or sent it back. It
records a `decision` act with `by: engine` and the switch act that allowed it, then runs the
same applier. Where any of that does not hold it records nothing and the item stays in the
queue for a person. The dashboard can never make an act `by: engine`: `role_of` knows no such role.

Every act ends with one outcome: `applied`, `skipped: moved` or `refused: <reason>`.
Conflicts skip, never clobber: a post that has already moved on (decided, scheduled,
sent, retired) or whose text changed after the gate is skipped, not rewritten.
`by` is a role, never a name. An act is made once: its id comes from the desk row,
so pulling the same row again records nothing new.
"""
import datetime as dt
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import acts  # noqa: E402
import channels  # noqa: E402
import guardrails  # noqa: E402
import lifecycle  # noqa: E402
import memory  # noqa: E402
import repo  # noqa: E402
import standing_rules  # noqa: E402
import store  # noqa: E402

ACTS_FILE = "acts.jsonl"
LIFECYCLE_FILE = "lifecycle.jsonl"
ROLES = ("alpha", "beta", "team")
MOVED = ("decided", "scheduled", "sent", "scored", "retired")
DECISIONS = {"approved": "approve", "held": "hold", "rejected": "reject", "rewrite": "rewrite"}
TZ = guardrails.TZ  # the brand's own zone (autopilot.timezone), as every other send check
# The channels an item sends on: (channel key, the item's teaser field, the calendar's platform name).
CHANNELS = (("linkedin", "teaser_linkedin", "LinkedIn"), ("x", "teaser_x", "X"))
SENT = ("sent", "scored")
DEFAULT_STREAM = getattr(memory, "DEFAULT_STREAM_NAME", None) or memory.DEFAULT_STREAM


def role_of(by):
    """The desk's `by` as a role. Anything that is not a known role is `alpha`: a name never travels."""
    name = str(by or "").strip().lower()
    return name if name in ROLES else "alpha"


def act_id(kind, *parts):
    return f"desk-{kind}-" + hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


def default_guard(item, date):
    """`(ok, reason)`: may the item's stream send on its channel on `date`, by the registry (midday, the brand's zone)."""
    import guardrails
    import zoneinfo
    stream, channel = item.get("stream") or DEFAULT_STREAM, (item.get("slot") or {}).get("platform", "")
    try:
        at = dt.datetime.combine(dt.date.fromisoformat(date), dt.time(12, 0), tzinfo=zoneinfo.ZoneInfo(TZ))
        row = memory.stream(stream)
        today, week, last = guardrails.counts_from_notes(row["name"], channel, at, exclude_engine_id=item["id"])
        return guardrails.check(stream, channel, at, today, week, last)
    except (memory.SharedMemoryError, ValueError) as exc:
        return False, f"registry unreadable: {exc}"


def _note_date(item):
    date = str((item.get("slot") or {}).get("date") or "")[:10]
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        return None
    return date


def channel_id(item_id, key):
    """The lifecycle id of one channel's post of an item: `<id>:<channel>`."""
    return f"{item_id}:{key}"


def channel_posts(item):
    """`[(key, platform, text)]` for each channel the item has a teaser for."""
    out = []
    for key, field, platform in CHANNELS:
        text = str((item or {}).get(field) or "").strip()
        if text:
            out.append((key, platform, text))
    return out


def on_channel(item, platform):
    """The item as the guard reads it for one channel: the same note, the slot on that platform."""
    return dict(item, slot=dict(item.get("slot") or {}, platform=platform))


def _channel_ready(cid, key, text, lpath):
    """Whether a channel id may be gated and scheduled now: still a draft (or blocked), or gated for this text."""
    state = lifecycle.state(cid, lpath)
    if state in ("draft", "blocked"):
        return True
    return state == "gated" and (lifecycle.current(cid, lpath) or {}).get("text_hash") == channels.text_hash(key, text)


def _approve_channel(item, act, key, text, date, verdict_hash, verdict, stream, apath, lpath, guard, platform):
    """Gate, decide and schedule `<id>:<key>` on its own applied approve act, recorded by the same approval."""
    cid = channel_id(item["id"], key)
    digest = channels.text_hash(key, text)
    if lifecycle.state(cid, lpath) in ("draft", "blocked"):
        lifecycle.gate(cid, digest, verdict_hash, verdict=verdict, stream=stream, path=lpath)
    payload = {"decision": "approve", "item_kind": "post", "channel": key, "approval": act["id"],
               "source": (act.get("payload") or {}).get("source") or "desk"}
    media = _media(item, key)
    if media:
        # the card or film is part of what is approved: its hash is on the act, and the send checks it
        payload["media"] = media
    own = acts.record("decision", stream, cid, payload, base=digest, by=act.get("by") or "alpha", path=apath)
    acts.applied(own["id"], path=apath)
    lifecycle.decide(cid, own["id"], acts_path=apath, stream=stream, path=lpath)
    lifecycle.schedule(cid, date, lambda: guard(on_channel(item, platform), date), stream=stream, path=lpath)


def _media(item, key):
    """The motion card or film this post goes out with on a channel, as `{path, sha256, kind}`, or None.
    A lookup that fails never stops an approval: the post then goes out as text."""
    try:
        import motion
        return motion.media_for(item, key)
    except Exception:  # noqa: BLE001
        return None


def approved_media(channel_post_id, state_dir):
    """The media recorded on the approval of a channel post (`<id>:x`), as `{path, sha256}`, or None."""
    lpath = os.path.join(state_dir, LIFECYCLE_FILE)
    for a in channels._approval_acts(channel_post_id, lpath, state_dir):
        media = (a.get("payload") or {}).get("media")
        if isinstance(media, dict) and media.get("path") and media.get("sha256"):
            return {"path": media["path"], "sha256": media["sha256"]}
    return None


def approve(item, act, apath, lpath, guard):
    """Move an approved post gated -> decided -> scheduled. Returns the outcome string."""
    pid = act["target"]
    if item is None:
        return "refused: no note carries this id"
    stream = item.get("stream") or DEFAULT_STREAM
    state = lifecycle.state(pid, lpath)
    if state in MOVED:
        return "skipped: moved"
    base = act["base"]
    gate = item.get("gate") or {}
    if state == "gated":
        if (lifecycle.current(pid, lpath) or {}).get("text_hash") != base:
            return "skipped: moved"
    else:
        why = lifecycle.gate_refusal(gate.get("verdict"))
        if why:
            return f"refused: {why}"
    date = _note_date(item)
    if not date:
        return "refused: the note has no date to schedule for"
    ok, reason = guard(item, date)
    if not ok:
        return f"refused: guardrails: {reason}"
    posts = [p for p in channel_posts(item) if _channel_ready(channel_id(pid, p[0]), p[0], p[2], lpath)]
    for key, platform, _text in posts:  # every channel is asked before anything moves
        ok, reason = guard(on_channel(item, platform), date)
        if not ok:
            return f"refused: guardrails: {platform}: {reason}"
    verdict = gate.get("verdict")
    if any(lifecycle.state(channel_id(pid, key), lpath) in ("draft", "blocked") for key, _p, _t in posts):
        why = lifecycle.gate_refusal(verdict)
        if why:
            return f"refused: {why}"
    verdict_hash = hashlib.sha256(repr(sorted(gate.items())).encode("utf-8")).hexdigest()[:16]
    try:
        if state in ("draft", "blocked"):
            lifecycle.gate(pid, base, verdict_hash, verdict=gate["verdict"], stream=stream, path=lpath)
        acts.applied(act["id"], path=apath)
        lifecycle.decide(pid, act["id"], acts_path=apath, stream=stream, path=lpath)
        lifecycle.schedule(pid, date, lambda: guard(item, date), stream=stream, path=lpath)
        for key, platform, text in posts:
            _approve_channel(item, act, key, text, date, verdict_hash, verdict, stream, apath, lpath, guard, platform)
    except (lifecycle.LifecycleError, store.StoreError) as exc:
        return f"refused: {exc}"
    _mark_approved(item)
    return "applied"


def _mark_approved(item):
    """The note says approved too, so publish.py, the desk mirror, motion and the story read what the
    lifecycle says; a control-page approval reaches no distributor that would write it."""
    if item.get("alpha_status") == "approved":
        return
    try:
        repo.set_fields(item["id"], {"alpha_status": "approved"})
    except (KeyError, ValueError):
        return  # no note behind it, or one repo.py will not rewrite: the approval stands in the lifecycle


def reschedule(item, date, state_dir, guard=None):
    """Move a scheduled post and its channel ids to `date` before the send, each within the guardrails.

    Refused (LifecycleError) once any of them is sent: what went out keeps the date it went out on.
    Ids still short of `scheduled` are left alone; the approval schedules them for the note's date.
    Returns the ids moved."""
    guard = guard or default_guard
    lpath = os.path.join(state_dir, LIFECYCLE_FILE)
    try:
        dt.date.fromisoformat(str(date))
    except ValueError:
        raise lifecycle.LifecycleError(f"{date!r} is not a date (YYYY-MM-DD)")
    ids = [(item["id"], item)] + [(channel_id(item["id"], key), on_channel(item, platform))
                                  for key, _field, platform in CHANNELS]
    for pid, _ in ids:
        if lifecycle.state(pid, lpath) in SENT:
            raise lifecycle.LifecycleError(f"{pid} is already sent; its date stays")
    moving = [(pid, view) for pid, view in ids if lifecycle.state(pid, lpath) == "scheduled"]
    for pid, view in moving:  # every id is asked before any moves
        ok, reason = guard(view, str(date))
        if not ok:
            raise lifecycle.LifecycleError(f"{pid}: guardrails refuse: {reason}")
    for pid, view in moving:
        lifecycle.reschedule(pid, str(date), lambda view=view: guard(view, str(date)), path=lpath)
    return [pid for pid, _ in moving]


def finish(aid, outcome, apath):
    """End act `aid` with its outcome: applied, `skipped: moved` or `refused: <reason>`."""
    if outcome == "applied":
        if not any(a["id"] == aid and a["outcome"] for a in acts.list_acts(path=apath)):
            acts.applied(aid, path=apath)
    elif outcome.startswith("skipped"):
        acts.skipped(aid, path=apath)
    else:
        acts.refused(aid, outcome[len("refused: "):] if outcome.startswith("refused: ") else outcome, path=apath)


def approve_post(post_id, by, items, state_dir, guard=None, note="", source="dashboard", reason=None, scope="item",
                 db_path=None):
    """The dashboard's approve: the desk's standing rules, then one decision act for `post_id`, then the
    same applier the desk uses (gate if still a draft -> decide -> schedule for the note's date,
    within the guardrails).

    The rules are standing_rules.refusal(): an argument line confirmed and
    current in the desk database (`db_path`, else the state directory's `desk.db`). A refusal is an
    outcome with no act: nothing was decided. Once the post is scheduled, a reason typed in (none is needed) is recorded as
    the desk records it (a `review` of `scope` `item` or `standing`; `desk_sync.py --pull` is what
    writes a standing one to `reviews.md`).

    Never sends. Returns `{id, target, outcome, state, date}`; `outcome` is `applied`,
    `skipped: moved` or `refused: <reason>`, and an act ends with it in `acts.jsonl`.
    `by` is made a role, never a name.
    """
    guard = guard or default_guard
    apath, lpath = os.path.join(state_dir, ACTS_FILE), os.path.join(state_dir, LIFECYCLE_FILE)
    db_path = db_path or standing_rules.db_path(state_dir)
    item = items.get(post_id)
    scope = standing_rules.norm_scope(scope)
    if item is not None:
        facts = standing_rules.post_facts(item, db_path)
        why = standing_rules.refusal("approved", reason, "post", facts["argument_current"], facts["blocked"])
        if why:
            return {"id": None, "target": post_id, "outcome": f"refused: {why}", "state": lifecycle.state(post_id, lpath),
                    "date": (lifecycle.current(post_id, lpath) or {}).get("date")}
    stream = (item or {}).get("stream") or DEFAULT_STREAM
    base = repo.base_hash(item) if item else None
    act = acts.record("decision", stream, post_id,
                      {"decision": "approve", "note": note or str(reason or "").strip(), "item_kind": "post",
                       "source": source},
                      base=base, by=role_of(by), path=apath)
    try:
        outcome = approve(item, act, apath, lpath, guard)
    except Exception as exc:  # the act must still end with an outcome
        outcome = f"refused: {exc}"
    finish(act["id"], outcome, apath)
    if outcome == "applied":
        standing_rules.record_review(post_id, "post", item.get("theme"), item.get("title"), "approved", reason, scope,
                                     by, stream, state_dir, path=db_path)
    return {"id": act["id"], "target": post_id, "outcome": outcome, "state": lifecycle.state(post_id, lpath),
            "date": (lifecycle.current(post_id, lpath) or {}).get("date")}


ENGINE_ROLE = standing_rules.ENGINE_ROLE
NOT_APPROVING = ("hold", "reject", "rewrite")


def person_said_no(post_id, item, apath):
    """The applied hold, rejection or rewrite a person recorded on this post's present text, or None."""
    base = repo.base_hash(item)
    found = None
    for a in acts.list_acts(path=apath):
        if a.get("kind") != "decision" or a.get("target") != post_id or a.get("outcome") != "applied":
            continue
        if a.get("by") == ENGINE_ROLE or (a.get("payload") or {}).get("decision") not in NOT_APPROVING:
            continue
        if a.get("base") in (None, base):
            found = a
    return found


def engine_allowed(item, state_dir):
    """`(ok, why, allowed_by)`: may the engine approve this post with no person in the loop.

    Every channel the item has a teaser for is on `auto` for the kind `post` (switches.mode,
    which is `review` unless a person switched it and the stream's setup still allows it), the
    stream is not paused, and the gate's verdict is exactly `pass`. `allowed_by` names, per
    channel, the switch act that allowed it (or the setup file's default)."""
    import switches
    stream = item.get("stream") or DEFAULT_STREAM
    try:
        slug = memory.slug_for(stream)
    except memory.SharedMemoryError as exc:
        return False, str(exc), {}
    if switches.paused(slug, state_dir):
        return False, f"every send of {slug} is paused", {}
    posts = channel_posts(item)
    if not posts:
        return False, "the item has no channel post to schedule", {}
    allowed = {}
    for key, platform, _text in posts:
        if switches.mode(slug, key, "post", state_dir) != "auto":
            return False, f"posts on {platform} wait for a person: the review mode of {slug}/{key}/post is review", {}
        rec = switches.wanted(slug, key, "post", state_dir)[1] or {}
        allowed[key] = rec.get("act") or f"brand.json streams.{slug}.review.post"
    verdict = (item.get("gate") or {}).get("verdict")
    if verdict != "pass":
        return False, f"the gate's verdict is {verdict or 'missing'}, not pass", {}
    import review
    ok, why = review.approvable(item)
    if not ok:
        return False, why, {}
    return True, "", allowed


def engine_approve(post_id, items, state_dir, guard=None, db_path=None, dry=False):
    """The approval with no person in it. Returns `{id, target, outcome, state, date, by}`.

    `outcome` is `applied`, `skipped: moved`, `would approve` (a dry run) or `refused: <reason>`.
    A refusal before the act (the mode is review, the verdict is not pass, a person said no, the
    stream is paused) records nothing: nothing was decided, and the item waits for a person. An
    act once made ends with its outcome, as any other.
    """
    guard = guard or default_guard
    apath, lpath = os.path.join(state_dir, ACTS_FILE), os.path.join(state_dir, LIFECYCLE_FILE)
    db_path = db_path or standing_rules.db_path(state_dir)
    item = items.get(post_id)

    def answer(outcome, aid=None):
        return {"id": aid, "target": post_id, "outcome": outcome, "state": lifecycle.state(post_id, lpath),
                "date": (lifecycle.current(post_id, lpath) or {}).get("date"), "by": ENGINE_ROLE}

    if item is None:
        return answer("refused: no note carries this id")
    if lifecycle.state(post_id, lpath) in MOVED:
        return answer("skipped: moved")
    ok, why, allowed = engine_allowed(item, state_dir)
    if not ok:
        return answer(f"refused: {why}")
    said = person_said_no(post_id, item, apath)
    if said or item.get("alpha_status") in ("held", "rejected", "rewrite", repo.SUPERSEDED):
        what = (said.get("payload") or {}).get("decision") if said else item.get("alpha_status")
        return answer(f"refused: a person's decision stands on this text ({what})")
    facts = standing_rules.post_facts(item, db_path)
    why = standing_rules.refusal("approved", None, "post", facts["argument_current"], facts["blocked"], role=ENGINE_ROLE)
    if why:
        return answer(f"refused: {why}")
    stream = item.get("stream") or DEFAULT_STREAM
    if dry:
        date = _note_date(item)
        if not date:
            return answer("refused: the note has no date to schedule for")
        ok, reason = guard(item, date)
        return answer("would approve" if ok else f"refused: guardrails: {reason}")
    act = acts.record("decision", stream, post_id,
                      {"decision": "approve", "note": "", "item_kind": "post", "source": "engine", "allowed_by": allowed},
                      base=repo.base_hash(item), by=ENGINE_ROLE, path=apath)
    try:
        outcome = approve(item, act, apath, lpath, guard)
    except Exception as exc:  # the act must still end with an outcome
        outcome = f"refused: {exc}"
    finish(act["id"], outcome, apath)
    return answer(outcome, act["id"])


BLOG_LIVE = "blog-live"
LIVE_STATES = ("scheduled", "sent", "scored")


def live_act(item_id, state_dir):
    """The applied `blog-live` act for this item, or None: a person said its article is live."""
    found = None
    for a in acts.list_acts(path=os.path.join(state_dir, ACTS_FILE)):
        if a.get("kind") == BLOG_LIVE and a.get("target") == item_id and a.get("outcome") == "applied":
            found = a
    return found


def live_url(item, state_dir):
    """The live article's URL, once a person has marked it live; else None."""
    act = live_act(item["id"], state_dir) if item else None
    return (act.get("payload") or {}).get("url") if act else None


def _live_refusal(item, state_dir):
    if live_act(item["id"], state_dir):
        return "skipped: moved"
    if not str(item.get("post") or "").strip():
        return "refused: the item has no article"
    why = lifecycle.gate_refusal((item.get("gate") or {}).get("verdict"))
    if why:
        return f"refused: {why}"
    approved = item.get("alpha_status") == "approved"
    if not approved and lifecycle.state(item["id"], os.path.join(state_dir, LIFECYCLE_FILE)) not in LIVE_STATES:
        return "refused: the item is not approved; approve it before its article goes live"
    return None


def blog_live(item_id, by, items, state_dir, webhook=None):
    """A person marks an item's article live on the site: one `blog-live` act (the URL is
    engine.json `site.post_url` with the item's slug), then the site webhook. The link-reply
    under the item's sent posts reads this act; nothing is sent here.

    Returns `{id, target, outcome, url, webhook}`; `outcome` is `applied`, `skipped: moved` (already
    live) or `refused: <reason>`. `webhook` is the callable that fires the site webhook
    (publish.site_webhook by default) and is called only when the act is applied; its answer is
    reported, and a failure never undoes the act. `by` is made a role, never a name."""
    apath = os.path.join(state_dir, ACTS_FILE)
    item = items.get(item_id)
    if item is None:
        return {"id": None, "target": item_id, "outcome": "refused: no note carries this id", "url": None,
                "webhook": None}
    slug = repo.slug_for(item)
    url = repo.post_url(slug)
    outcome = _live_refusal(item, state_dir)
    if outcome is None and not url.startswith("https://"):
        outcome = "refused: the article URL is not https; set engine.json site.post_url"
    act = acts.record(BLOG_LIVE, item.get("stream") or DEFAULT_STREAM, item_id, {"url": url, "slug": slug},
                      by=role_of(by), path=apath)
    outcome = outcome or "applied"
    finish(act["id"], outcome, apath)
    hook = None
    if outcome == "applied":
        if webhook is None:
            import publish
            webhook = publish.site_webhook
        try:
            hook = webhook()
        except Exception as exc:  # the article is live whatever the webhook answers
            hook = f"failed: {str(exc)[:200]}"
    return {"id": act["id"], "target": item_id, "outcome": outcome, "url": url, "webhook": hook}


def edit_outcome(item, row):
    if item is None:
        return "refused: no note carries this id"
    now = repo.base_hash(item)
    if now == row["base_hash"]:
        return "applied"
    wanted = repo.base_hash({k: row[k] for k in repo.HASH_FIELDS})
    return "applied" if now == wanted else "skipped: moved"


def turn_into_acts(decisions, edits, arguments, reviews, items, streams, state_dir, guard=None):
    """Make one act per desk row not seen before and end each with its outcome.

    `decisions`, `edits`, `arguments`, `reviews` are lists of dict rows from the desk;
    `items` is `{id: item}` from the notes; `streams` is `{id: stream}`. Returns one
    `{id, kind, target, outcome}` per act made now.
    """
    guard = guard or default_guard
    apath, lpath = os.path.join(state_dir, ACTS_FILE), os.path.join(state_dir, LIFECYCLE_FILE)
    have = {a["id"] for a in acts.list_acts(path=apath)}
    made = []

    def stream_of(target):
        return streams.get(target) or DEFAULT_STREAM

    def make(kind, aid, target, payload, base, by, at, decide):
        if aid in have:
            return
        have.add(aid)
        act = acts.record(kind, stream_of(target), target, payload, base=base, by=role_of(by), id=aid,
                          at=at or None, path=apath)
        try:
            outcome = decide(act)
        except Exception as exc:  # one bad row must not stop the others; it ends refused
            outcome = f"refused: {exc}"
        finish(aid, outcome, apath)
        made.append({"id": aid, "kind": kind, "target": target, "outcome": outcome})

    for r in decisions:
        item, status = items.get(r["id"]), DECISIONS.get(r["status"], r["status"])
        base = repo.base_hash(item) if item else None
        if status == "approve" and r.get("kind", "post") == "post":
            decide = lambda act, item=item: approve(item, act, apath, lpath, guard)  # noqa: E731
        else:
            decide = lambda act: "applied"  # noqa: E731
        make("decision", act_id("decision", r["id"], r["status"], r["at"]), r["id"],
             {"decision": status, "note": r.get("note", ""), "item_kind": r.get("kind", "post")},
             base, r.get("by"), r["at"], decide)
    for r in edits:
        item = items.get(r["item_id"])
        make("edit", act_id("edit", r["item_id"], r["base_hash"], r["at"]), r["item_id"],
             {k: r[k] for k in ("title", "post", "teaser_linkedin", "teaser_x")}, r["base_hash"], r.get("by"),
             r["at"], lambda act, item=item, r=r: edit_outcome(item, r))
    for r in arguments:
        make("argument_line", act_id("argument", r["item_id"], r["act"], r["at"]), r["item_id"],
             {"act": r["act"], "hook": r["hook"], "claim": r["claim"]}, None, r.get("by"), r["at"],
             lambda act: "applied")
    for r in reviews:
        make("review", act_id("review", r["rowid"], r["item_id"], r["at"]), r["item_id"],
             {"verdict": r["verdict"], "scope": r["scope"], "theme": r["theme"], "rationale": r["rationale"]},
             None, r.get("by"), r["at"], lambda act: "applied")
    return made
