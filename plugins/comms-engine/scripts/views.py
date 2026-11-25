#!/usr/bin/env python3
"""
views.py - every view of the engine, computed once from the record.

Why: what the engine knows is spread over a dozen files - the calendar notes,
the calendar snapshot built from them, the listening passes, the search terms, the handles, the
replies, the claims watch, the scores, the jobs, the story. A screen should not
know any of those formats. Each view here is one function that reads them and
returns plain rows; the control page, the story's facts and the command line all
take their data from here, and none keeps a reader of its own
(`PLAN-surfaces.md`, step 1).

Nothing here writes. A person's change goes through the module that owns the
file (`control.py`'s watchlist and search terms, `held_theme.py`, `story.py`),
with the `*_base` digest a view hands out: a change is refused when its file
moved since the view was read (conflicts skip, never clobber).

The views, in the order the page shows them:

  genome      the brand's colours, type and logo (genome.py)
  story       the latest story, its questions, the replies and the feedback on it
  posts       the engine's posts, upcoming and past, where each stands, its checks, its motion card
  calendar    the content calendar (built from the notes and the lifecycle), the sends, the week's strategy
  themes      each theme with its search terms, planning, warmth and posts
  accounts    own channels, partners, standards bodies, the watchlist
  suggested   authors seen on a theme twice in 30 days and not yet known
  listening   the latest listening pass, with the words of what was heard
  replies     the reply drafts waiting to be placed, with the post they answer
  claims      the register's size, the research watch and the claims to review
  learning    the predictions and the scorecard
  engine      the jobs, the recent runs and the motion cards owed
  setup       where this computer stands between clone and running engine, and the setup
              file (brand.json) as the Setup page edits it
  policy      the review switch: per stream its autopilot setting and pause, per channel and
              kind the mode in force, and what was sent with no person in the loop
  reactions   likes and reposts: what is waiting for a click, queued, done and refused (each
              refusal with its reason), the day's caps and what each kind of reaction earned
  reviews     Alpha's standing reviews from reviews.md, newest first

`published_posts()` is not a page view: it is the website's feed of the articles marked
live, served read-only at `GET /api/published` and written by `engine.py export-published`.

  engine views                 the views, one line each
  engine views posts themes    those views as JSON
  engine views --all [--out F] every view: what the page reads
"""
import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
STATE = paths.state()
sys.path.insert(0, HERE)
import config  # noqa: E402
import gate_lint  # noqa: E402
import genome  # noqa: E402
import memory  # noqa: E402
import motion  # noqa: E402
import repo  # noqa: E402

REPO = repo.REPO
TERMS = os.path.join(paths.instance(), "themes.json")
WATCHLIST = os.path.join(STATE, "watchlist.json")
X_QUERY_MAX = 255
WATCH_MAX = 30
SUGGEST_DAYS, SUGGEST_MIN_HITS, SUGGEST_MAX = 30, 2, 40


# ------------------------------------------------------------------ files


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def digest(path):
    """The file's content hash, or "" when it does not exist: a screen sends it
    back with a change, and the change is refused when the file has moved."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError:
        return ""


def rel(path):
    return os.path.relpath(path, REPO)


def stream_name():
    return getattr(memory, "DEFAULT_STREAM_NAME", None) or str(memory.DEFAULT_STREAM).upper()


def norm_handle(value, cell=False):
    """`@Name`, `Name` or a URL's handle, lower case, without the @; "" when none.
    In a handles.md cell (`cell`), only an @handle counts: "collect" is a status."""
    value = str(value or "").strip()
    m = re.search(r"@([A-Za-z0-9_]{1,15})\b", value)
    if not m and not cell:
        m = re.fullmatch(r"([A-Za-z0-9_]{1,15})", value)
    return m.group(1).lower() if m else ""


# ------------------------------------------------------------------ accounts


def watchlist(path=None):
    data = load_json(path or WATCHLIST, {})
    return {"watched": list(data.get("watched") or []), "dismissed": list(data.get("dismissed") or [])}


def known_handles():
    """Every X handle handles.md already carries: those are monitored there."""
    out = set()
    try:
        h = memory.load_handles()
    except Exception:  # noqa: BLE001 - a template without its tables yet
        return out
    for row in h.get("own_channels", []):
        if str(row.get("platform", "")).upper() == "X":
            out.add(norm_handle(row.get("handle"), cell=True))
    for table in ("cleared_partners", "standards_bodies"):
        for row in h.get(table, []):
            out.add(norm_handle(row.get("x"), cell=True))
    out.discard("")
    return out


def listening_items(days=SUGGEST_DAYS, files=None, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=days)
    seen, out = set(), []
    for path in files if files is not None else sorted(glob.glob(os.path.join(STATE, "listening-*.json"))):
        data = load_json(path, {})
        for it in data.get("items") or []:
            key = (it.get("source"), it.get("id"))
            if key in seen:
                continue
            seen.add(key)
            when = _when(it.get("created_at"))
            if when and when < cutoff:
                continue
            out.append(it)
    return out


def _when(value):
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return dt.datetime.strptime(str(value).replace("Z", "+0000"), fmt)
        except ValueError:
            continue
    return None


def suggested(items=None, known=None, wl=None, min_hits=SUGGEST_MIN_HITS, limit=SUGGEST_MAX):
    """Authors seen on a theme at least `min_hits` times, not monitored, watched
    or dismissed, ranked by how often they were seen. Kept nowhere: worked out
    from the listening passes on each read."""
    items = listening_items() if items is None else items
    known = known_handles() if known is None else known
    wl = watchlist() if wl is None else wl
    skip = set(known) | {norm_handle(w.get("handle")) for w in wl["watched"]} \
        | {norm_handle(d.get("handle")) for d in wl["dismissed"]}
    by = {}
    for it in items:
        h = norm_handle(it.get("author"))
        theme = str(it.get("theme") or it.get("_matched_term") or "")
        if not h or h in skip or (it.get("source") or "x") != "x" or not theme.startswith("#"):
            continue
        if ((it.get("prescore") or {}).get("relevance") or 0) <= 0:
            continue
        a = by.setdefault(h, {"handle": f"@{h}", "name": it.get("author_name") or "", "hits": 0, "themes": {},
                              "followers": 0, "engagement": 0, "samples": [], "last": ""})
        a["hits"] += 1
        a["themes"][theme] = a["themes"].get(theme, 0) + 1
        a["followers"] = max(a["followers"], int(it.get("followers") or 0))
        a["engagement"] += int((it.get("prescore") or {}).get("engagement") or 0)
        a["last"] = max(a["last"], str(it.get("created_at") or ""))
        if len(a["samples"]) < 3:
            a["samples"].append({"url": it.get("url") or "", "text": str(it.get("text") or "")[:160], "theme": theme})
    rows = [dict(a, themes=sorted(a["themes"], key=lambda t: -a["themes"][t])) for a in by.values() if a["hits"] >= min_hits]
    rows.sort(key=lambda a: (-a["hits"], -a["engagement"], a["handle"]))
    return rows[:limit]


# ------------------------------------------------------------------ the views


#: The four fields a person edits on the desk; an edit shows over the note.
EDIT_FIELDS = ("title", "post", "teaser_linkedin", "teaser_x")


def edit_state(item, edit):
    """Where a saved desk edit stands against the note: the three-way test
    apply_edits.py makes. None, applied, dropped, pending or conflict."""
    if not edit:
        return None
    de = item.get("desk_edit") or {}
    if de.get("edited_at") and edit.get("at") and de["edited_at"] == edit["at"]:
        return "dropped" if de.get("resolution") == "vault" else "applied"
    return "pending" if repo.base_hash(item) == edit.get("base_hash") else "conflict"


#: Plain labels for the states a person did not just act on.
OTHER_LABELS = {"rewrite": ("Being rewritten", "info", "Sent back for a rewrite; the writer redrafts it in the next cycle."),
                "held": ("On hold", "warning", "Held. It stays out of the calendar until someone lifts the hold."),
                "rejected": ("Rejected", "", "Rejected. It will not go out.")}


def standing(item, status, edit, es, argument):
    """A post's place in plain words: a filter key (needs-you, approved, posted,
    other), a label that says what comes next, a tone and one sentence."""
    live = item.get("published_to") or []
    if live:
        return {"key": "posted", "label": "Posted", "tone": "good", "note": "Posted on " + ", ".join(live) + "."}
    if es == "conflict":
        return {"key": "needs-you", "label": "Pick a version", "tone": "danger",
                "note": "Your edit and the post both changed after you saved it, so nothing was written. Pick which version stands on the desk."}
    gate = item.get("gate") or {}
    if gate.get("verdict") == "block":
        c = next((c for c in gate.get("checks") or [] if c.get("result") == "block"), None)
        why = (str(c.get("check", "")).replace("lint: ", "") + ": \u201c" + str(c.get("line") or "")[:140] + "\u201d") if c else "See the checks."
        return {"key": "needs-you", "label": "Blocked by a check", "tone": "danger", "note": "A check stopped it. " + why}
    title = (edit or {}).get("title", item.get("title")) if es not in (None, "dropped") else item.get("title")
    if status == "proposed":
        if not (argument and argument.get("hook") == title):
            return {"key": "needs-you", "label": "Confirm the hook", "tone": "warning",
                    "note": "Confirm or rewrite the hook and the claim on the desk, then approve."}
        return {"key": "needs-you", "label": "Ready to approve", "tone": "warning",
                "note": "Hook and claim confirmed. Approving puts it in the calendar."}
    if status == "approved":
        return {"key": "approved", "label": "Approved", "tone": "good", "note": "Approved. A person posts it on its date."}
    label, tone, note = OTHER_LABELS.get(status, (status, "", ""))
    return {"key": "other", "label": label, "tone": tone, "note": note}


def post_acts(state_dir=None):
    """{post id: {outcome, at, by, source, state, date}}: the last decision act on each post
    (acts.jsonl) and where the lifecycle has it (lifecycle.jsonl). Empty before either exists."""
    import acts
    import lifecycle
    state_dir = state_dir or STATE
    last = {}
    try:
        for a in acts.list_acts(path=os.path.join(state_dir, "acts.jsonl")):
            if a.get("kind") == "decision" and (a.get("payload") or {}).get("item_kind", "post") == "post":
                last[a["target"]] = a
        fold = lifecycle.fold(os.path.join(state_dir, "lifecycle.jsonl"))
    except Exception:  # a log that cannot be read shows nothing here; the logs are the record
        return {}
    out = {}
    for pid in set(last) | set(fold):
        a, row = last.get(pid), fold.get(pid)
        out[pid] = {"decision": (a.get("payload") or {}).get("decision") if a else None,
                    "outcome": (a.get("outcome") or "pending") if a else None, "at": a.get("at") if a else None,
                    "by": a.get("by") if a else None, "source": (a.get("payload") or {}).get("source", "desk") if a else None,
                    "state": row["to"] if row else None, "date": row.get("date") if row else None}
    # The sender moves a post's channel ids (`<id>:x`), never the item's own: once one has gone
    # out, the post reads as sent, so the page stops offering to move a day that stays.
    for pid, rec in out.items():
        if ":" not in pid and any(str(c).startswith(pid + ":") and (fold.get(c) or {}).get("to") in ("sent", "scored")
                                  for c in fold):
            rec["state"] = "sent"
    return out


def posts(today):
    import desk_acts
    import standing_rules
    items = gate_lint.items_by_id()
    desk_db = standing_rules.db_path(STATE)
    lived = post_acts()
    decisions = load_json(os.path.join(STATE, "decisions.json"), {})
    edits = load_json(os.path.join(STATE, "edits.json"), {})
    arguments = load_json(os.path.join(STATE, "arguments.json"), {})
    rows = []
    for item in items.values():
        slot = item.get("slot") or {}
        # The motion card, its files as repo paths the page fetches under /media/.
        # `ready`: a video this machine holds whose storyboard still matches the post.
        card = motion.card(item["id"], item)
        for key in ("poster", "gif", "video"):
            card[key] = rel(card[key]) if card[key] else None
        card["ready"] = bool(card["video"] and card["current"])
        decision = decisions.get(item["id"])
        dstatus = (decision or {}).get("status") if isinstance(decision, dict) else decision
        edit = edits.get(item["id"])
        es = edit_state(item, edit)
        facts = standing_rules.post_facts(item, desk_db)  # the desk database first: the dashboard confirms there too
        place = standing(item, dstatus or item.get("alpha_status") or "proposed", edit, es,
                         facts["argument"] or arguments.get(item["id"]))
        run = lived.get(item["id"]) or {}
        if run.get("state") in ("decided", "scheduled") and place["key"] != "posted":
            place = {"key": "approved", "label": "Scheduled" if run["state"] == "scheduled" else "Approved", "tone": "good",
                     "note": f"Scheduled for {run.get('date')}. The sender posts it on that day, within the guardrails; approving never sends."
                     if run["state"] == "scheduled" else "Approved; the next step schedules it."}
        rows.append({
            "decision_note": (decision or {}).get("note", "") if isinstance(decision, dict) else "",
            "decision_by": (decision or {}).get("by", "") if isinstance(decision, dict) else "",
            "decision_at": (decision or {}).get("at", "") if isinstance(decision, dict) else "",
            "act": lived.get(item["id"]),
            # the hook and the claim as the card shows them, and whether a person has confirmed exactly these
            "hook": facts["hook"], "claim": facts["claim"],
            "argument": {"current": bool(facts["argument_current"]),
                         "by": (facts["argument"] or {}).get("by"), "at": (facts["argument"] or {}).get("at")},
            "standing": place, "edit_state": es, "published_to": item.get("published_to") or [],
            "checks": [{k: c.get(k) for k in ("check", "result", "line", "fix")} for c in (item.get("gate") or {}).get("checks") or []],
            "id": item["id"], "title": item.get("title", ""), "theme": item.get("theme", ""),
            "date": slot.get("date"), "platform": slot.get("platform", "Blog"), "campaign": slot.get("campaign", ""),
            "status": item.get("status") or "", "alpha_status": item.get("alpha_status") or "",
            "decision": (decision or {}).get("status") if isinstance(decision, dict) else decision,
            "gate": (item.get("gate") or {}).get("verdict") or "", "note_for_alpha": (item.get("gate") or {}).get("note_for_alpha", ""),
            "cta": item.get("cta", ""), "teaser_x": item.get("teaser_x", ""), "teaser_linkedin": item.get("teaser_linkedin", ""),
            "post": item.get("post", ""), "live": desk_acts.live_url(item, STATE), "by_team": item.get("drafted_by") == repo.TEAM_BY,
            "hypothesis": item.get("hypothesis", ""), "predicted": item.get("predicted", ""), "motion": card})
    rows.sort(key=lambda r: (r["date"] or "9999", r["id"]))
    upcoming = [r for r in rows if (r["date"] or "9999") >= today]
    return {"upcoming": upcoming, "past": [r for r in rows if (r["date"] or "9999") < today][-15:][::-1]}


def calendar(today):
    snap = load_json(os.path.join(STATE, "calendar-snapshot.json"), {})
    rows = snap.get("rows") or []
    ahead = sorted((r for r in rows if str(r.get("date") or "") >= today), key=lambda r: (r.get("date") or "", r.get("platform") or ""))
    body = {r.get("page_id"): str(r.get("body") or "")[:2000] for r in rows}
    sends = sorted((dict(v, page_id=k) for k, v in (load_json(os.path.join(STATE, "send-ledger.json"), {}).get("sends") or {}).items()),
                   key=lambda s: str(s.get("at") or ""), reverse=True)
    strategy = load_json(os.path.join(STATE, "strategy.json"), {})
    keep = ("date", "platform", "status", "stream", "title", "pillar", "engine", "body")
    # Rows still open (not Published) whose date has passed: the calendar's loose ends.
    open_rows = sorted((r for r in rows if r.get("date") and str(r["date"]) < today
                        and r.get("status") not in ("Published", "pause")),
                       key=lambda r: r.get("date") or "", reverse=True)
    for r in rows:
        r["body"] = str(r.get("body") or "")[:2000]
    return {"taken_at": snap.get("taken_at"), "ahead": [{k: r.get(k) for k in keep} for r in ahead[:60]],
            "open_past": [{k: r.get(k) for k in keep} for r in open_rows[:25]], "open_past_total": len(open_rows),
            "undated": sum(1 for r in rows if not r.get("date") and r.get("status") != "Published"),
            "sends": [dict({k: s.get(k) for k in ("at", "platform", "title", "url", "state")}, body=body.get(s["page_id"], ""))
                      for s in sends[:12]],
            "strategy": {k: strategy.get(k) for k in ("week", "summary", "picks", "not_this_week", "held_slot")} if strategy else {}}


def published_posts(today=None, state_dir=None):
    """The website's feed: every article a person has marked live on the control page (the
    `blog-live` act), newest first, with what a site needs to show it. Read-only; the notes are
    the article, the act is when and where it went live."""
    import desk_acts
    state_dir = state_dir or STATE
    posts = []
    for item in repo.load_items():
        act = desk_acts.live_act(item["id"], state_dir)
        if not act:
            continue
        posts.append({"id": item["id"], "title": item.get("title", ""), "slug": (act.get("payload") or {}).get("slug") or repo.slug_for(item),
                      "url": (act.get("payload") or {}).get("url"), "published_at": act.get("at"),
                      "date": (item.get("slot") or {}).get("date"), "excerpt": item.get("excerpt", ""),
                      "category": str(item.get("theme") or "").lstrip("#"),
                      "topics": [str(t).lstrip("#") for t in item.get("tags") or []],
                      "stream": item.get("stream", ""), "body": item.get("post", "")})
    posts.sort(key=lambda p: (str(p["published_at"] or ""), p["id"]), reverse=True)
    return {"as_of": today or dt.date.today().isoformat(),
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "posts": posts}


def themes(today):
    try:
        roster = memory.load_themes()
    except Exception:  # noqa: BLE001 - a template before its themes are written
        roster = []
    local = load_json(TERMS, {})
    terms = local.get("search_terms") or {}
    planning = (load_json(os.path.join(STATE, "planning.json"), {}).get("themes") or {})
    signals = load_json(os.path.join(STATE, "signals.json"), {})
    per_theme = signals.get("per_theme") or {}
    warm = {r.get("theme"): r for r in ((signals.get("warmest_themes") or {}).get("ranked") or [])}
    findings = signals.get("findings") or []
    upcoming = posts(today)["upcoming"]
    try:
        import theme_words
        plain = theme_words.current()
    except Exception:  # noqa: BLE001 - no plain words yet: the page shows the rule itself
        plain = {}
    rows = []
    for t in roster:
        tag, term = t["tag"], terms.get(t["tag"]) or {}
        rows.append({
            "tag": tag, "what": t.get("what", ""), "different": t.get("different", ""), "licence": t.get("licence", ""),
            "licence_basis": t.get("licence_basis", ""), "plain": plain.get(t["tag"]),
            "layer": t.get("layer", ""), "fact": t.get("fact", ""),
            "x_search": term.get("x_search", ""), "linkedin_search": term.get("linkedin_search", ""),
            "keywords": term.get("keywords", []),
            "planning": planning.get(tag), "signal": per_theme.get(tag), "warmth": warm.get(tag),
            "findings": [f.get("id") for f in findings if f.get("theme") == tag],
            "upcoming": [p["id"] for p in upcoming if p["theme"] == tag]})
    md_path = memory.paths(None)["themes_md"]
    return {"rows": rows, "terms_file": rel(TERMS), "terms_base": digest(TERMS), "x_query_max": X_QUERY_MAX,
            "themes_md": rel(md_path), "md_base": digest(md_path),
            "mentions": (local.get("mentions") or {}).get("x_search", ""),
            "term_log": list(local.get("_term_log") or [])[-8:][::-1]}


def switch_rows():
    """The auto-reply switches (switches.py): per stream and channel, the live value, whether
    `streams.md` allows it on, and who last changed it, when and why."""
    try:
        import switches
        return switches.rows(STATE)
    except Exception:  # noqa: BLE001 - a template without its registry yet
        return []


def accounts():
    try:
        h = memory.load_handles()
    except Exception as e:  # noqa: BLE001
        h = {"own_channels": [], "cleared_partners": [], "standards_bodies": [], "private": {"present": False}, "error": str(e)}
    private = h.get("private") or {}
    try:
        terms = len(memory.denylist()) if private.get("present") else 0
    except Exception:  # noqa: BLE001
        terms = 0
    ledger = (load_json(os.path.join(STATE, "inventory-ledger.json"), {}).get("rows") or {})
    return {"own": h.get("own_channels", []), "partners": h.get("cleared_partners", []),
            "standards": h.get("standards_bodies", []),
            "private": {"present": bool(private.get("present")), "terms": terms},
            "ledger": [dict(v, key=k) for k, v in ledger.items()],
            "watched": watchlist()["watched"], "dismissed": watchlist()["dismissed"],
            "watch_base": digest(WATCHLIST), "watch_max": WATCH_MAX, "switches": switch_rows()}


def heard_text():
    """What the listener read, by post id and by URL, so a reference shows its words."""
    out = {}
    for it in listening_items(days=90):
        text = str(it.get("text") or "")
        if it.get("id"):
            out[str(it["id"])] = text
        if it.get("url"):
            out[str(it["url"]).split("?")[0]] = text
    return out


def listening():
    s = load_json(os.path.join(STATE, "signals.json"), {})
    heard = heard_text()
    latest = load_json(os.path.join(STATE, "listening-latest.json"), {})
    keep = ("id", "theme", "shape", "finding", "relevance", "sentiment", "content", "content_note",
            "conversation", "conversation_note", "freshness_deadline", "at", "evidence")
    return {"run_id": s.get("run_id"), "window": s.get("window"), "summary": s.get("summary", ""),
            "mentions_note": s.get("mentions_note", ""), "held_slot": s.get("held_slot"),
            "warmest": (s.get("warmest_themes") or {}).get("ranked") or [], "sources": s.get("sources") or [],
            "findings": [dict({k: f.get(k) for k in keep},
                              evidence=[dict(e, text=heard.get(str(e.get("url") or "").split("?")[0], ""))
                                        for e in (f.get("evidence") if isinstance(f.get("evidence"), list) else [])])
                         for f in s.get("findings") or []],
            "held_for_person": (s.get("handed_on") or {}).get("a person, hold for review") or [],
            "pass": {k: latest.get(k) for k in ("run_id", "count", "count_raw", "window_days", "max_per_term")},
            "terms": len(latest.get("terms") or [])}


def replies():
    import desk_sync  # late: desk_sync reads the notes on import
    e = load_json(os.path.join(STATE, "engagement.json"), {})
    decisions = load_json(os.path.join(STATE, "decisions.json"), {})
    heard = heard_text()
    import channels
    last = {}  # the latest send attempt per proposal id: its outcome or refusal is shown on the card
    for row in channels.sends(STATE):
        last[row.get("id")] = row
    proposals, done = [], 0
    for p in e.get("proposals") or []:
        pid = desk_sync.proposal_id(p)
        d = decisions.get(pid)
        status = (d.get("status") if isinstance(d, dict) else d) or "proposed"
        if status != "proposed":  # placed, skipped or rejected on the desk: not waiting any more
            done += 1
            continue
        row = last.get(pid)
        send = {k: row.get(k) for k in ("outcome", "check", "reason", "url", "at") if row.get(k)} if row else None
        proposals.append(dict(p, id=pid, send=send, target_text=heard.get(str(p.get("target_post") or ""), "")
                              or heard.get(str(p.get("target_url") or "").split("?")[0], "")))
    return {"pass_at": e.get("pass_at"), "proposals": proposals, "inbound": e.get("inbound") or {},
            "skipped": len(e.get("skipped") or []), "done": done}


REVIEW_HEAD = re.compile(r"^## (\d{4}-\d{2}-\d{2}) \u2014 (\S+) \u2014 (.+)$")


def reviews():
    """Alpha's standing reviews (`.atelier/memory/reviews.md`), one entry each:
    date, theme, act, the item it was written on, and the review itself."""
    path = os.path.join(REPO, ".atelier", "memory", "reviews.md")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return {"rows": []}
    rows, cur = [], None
    for line in text.splitlines():
        m = REVIEW_HEAD.match(line)
        if m:
            cur = {"date": m.group(1), "theme": m.group(2), "act": m.group(3).strip(), "item": "", "by": "", "text": ""}
            rows.append(cur)
        elif cur is None or line.strip() == "---":
            continue
        elif line.startswith("item:"):
            ids = re.findall(r"`([^`]+)`", line)
            cur["item"] = ids[0] if ids else ""
        elif line.startswith("by:"):
            cur["by"] = line[3:].strip()
        elif line.strip():
            cur["text"] = (cur["text"] + " " + line.strip()).strip()
    return {"rows": rows[::-1]}


def setup_file():
    """brand.json as the Setup page edits it: the brand, each stream's settings, the drivers and
    the jobs, with the file's digest (a save is refused when it moved), what `config.validate`
    finds wrong, and whether the tables of streams.md still match it."""
    import brandfile
    import config
    path = config.brand_path()
    bdoc = brandfile.read()
    out = {"path": rel(path), "present": bool(bdoc), "base": digest(path), "problems": config.validate(),
           "brand": {k: v for k, v in (bdoc.get("brand") or {}).items() if not k.startswith("_")},
           "streams": {s: {k: v for k, v in row.items() if not k.startswith("_")}
                       for s, row in (bdoc.get("streams") or {}).items() if isinstance(row, dict) and not s.startswith("_")},
           "drivers": {k: v for k, v in (bdoc.get("drivers") or {}).items() if not k.startswith("_")},
           "jobs": {k: v for k, v in (bdoc.get("jobs") or {}).items() if not k.startswith("_")},
           "options": {"kinds": list(config.REVIEW_KINDS), "modes": list(config.REVIEW_MODES),
                       "channels": list(config.CHANNEL_KEYS), "drivers": {k: list(v[1]) for k, v in config.DRIVER_KEYS.items()},
                       "autopilot": ["nothing", "by switch"], "owner": ["unset", "confirmed"]},
           "in_sync": True, "diff": []}
    if bdoc and not out["problems"]:
        try:
            with open(memory.STREAMS_MD, encoding="utf-8") as f:
                out["diff"] = brandfile.differences(f.read(), bdoc, config._read_json(config.ENGINE_JSON))
            out["in_sync"] = not out["diff"]
        except (OSError, brandfile.Refused) as e:
            out["in_sync"], out["diff"] = False, [str(e)]
    return out


def setup():
    """Where this checkout stands between clone and running engine (setup_state.py), and the
    setup file itself (`file`: setup_file())."""
    try:
        import setup_state
        out = setup_state.current(brand={"name": stream_name(), "slug": memory.DEFAULT_STREAM})
    except Exception as e:  # noqa: BLE001 - the page must build on a half-set-up machine
        out = {"complete": True, "done": 0, "total": 0, "next": None, "steps": [], "error": str(e)}
    try:
        out["file"] = setup_file()
    except Exception as e:  # noqa: BLE001 - a setup file that cannot be read is said, never fatal
        out["file"] = {"present": False, "problems": [str(e)], "streams": {}, "brand": {}, "drivers": {}, "jobs": {},
                       "base": "", "in_sync": False, "diff": [], "options": {}}
    return out


UNREVIEWED_KINDS = ("post", "reply", "comment", "like", "repost", "quote")
UNREVIEWED_MAX = 50


def unreviewed_sends(state_dir=None, limit=UNREVIEWED_MAX):
    """What went out with no person in the loop, newest first: a post the engine approved itself,
    or a reply, comment or reaction sent under an `auto` mode with no person's approval act.
    Each row says whether it was taken down since. Patterns only: an id, a channel, a url."""
    import channels
    import store
    state_dir = state_dir or STATE
    lpath = os.path.join(state_dir, channels.LIFECYCLE_FILE)
    ledger = channels._load_ledger(state_dir)["sends"]
    acts_ = store.acts(path=os.path.join(state_dir, channels.ACTS_FILE))
    approved = {a.get("target") for a in acts_ if a.get("kind") == "decision" and a.get("outcome") == "applied"
                and a.get("by") != "engine" and (a.get("payload") or {}).get("decision") == "approve"}
    rows = []
    for line in channels.sends(state_dir):
        if line.get("outcome") != "sent" or line.get("kind") not in UNREVIEWED_KINDS:
            continue
        rid = line.get("id")
        if line["kind"] == "post":
            if not channels._approved_by_engine(rid, lpath, state_dir):
                continue
        elif rid in approved:
            continue
        entry = ledger.get(rid) or {}
        rows.append({"id": rid, "kind": line["kind"], "channel": line.get("channel"), "stream": line.get("stream"),
                     "at": line.get("at"), "url": line.get("url") or entry.get("url") or "", "title": entry.get("title") or rid,
                     "taken_down": (entry.get("taken_down") or {}).get("at")})
    return rows[::-1][:limit]


def reactions():
    """Likes and reposts as the Engagement page shows them (reactions.summary): the candidates by
    state, each a post id, a tier and a theme and never a handle; the caps and the mode per
    channel and kind; and the ledger rows of reactions, so a person sees which ones earned a reply."""
    import engage
    import guardrails
    import reactions as reactions_mod
    import switches
    out = reactions_mod.summary(STATE)
    rules = []
    try:
        for slug in memory.streams():
            import channels
            for key in [k for k, _ in channels.stream_channels(slug) if k in channels.DISPLAY]:
                for kind in ("like", "repost"):
                    if key == "linkedin" and kind == "like":
                        continue  # no tool creates one
                    rules.append({"stream": slug, "name": memory.stream(slug)["name"], "channel": key, "label": channels.DISPLAY[key],
                                  "kind": kind, "cap": guardrails.reaction_cap(slug, key, kind),
                                  "mode": switches.mode(slug, key, kind, STATE),
                                  "click_only": key == "x" and kind == "like" and not channels.reactions_signoff(slug)})
    except memory.SharedMemoryError:
        pass
    earned = {k: v for k, v in engage.ledger(STATE).items() if k.split(" / ")[-1] in ("like", "repost", "quote")}
    return dict(out, rules=rules, earned=earned, live=bool(config.cfg("reactions.live", False)))


def policy():
    """The review switch as the Autonomy page shows it (switches.policy), with the presets and
    the sends nobody reviewed."""
    import switches
    return {"streams": switches.policy(STATE), "kinds": list(switches.KINDS), "presets": list(switches.PRESETS),
            "unreviewed": unreviewed_sends()}


def claims():
    review = load_json(os.path.join(STATE, "claims-review.json"), {})
    try:
        register = memory.load_claims()
        register = len(register) if hasattr(register, "__len__") else 0
    except Exception:  # noqa: BLE001
        register = 0
    return {"register": register, "watch": load_json(os.path.join(STATE, "watch-candidates.json"), []),
            "review": review.get("items") or []}


def learning():
    metrics = load_json(os.path.join(STATE, "metrics.json"), {})
    return {"predictions": load_json(os.path.join(STATE, "predictions.json"), []),
            "rows": metrics.get("rows") or [], "key_results": metrics.get("key_results") or [],
            "computed_at": metrics.get("computed_at")}


def engine():
    try:
        import jobs_status
        jobs = jobs_status.rows()
    except Exception as e:  # noqa: BLE001 - the view must build without launchd
        jobs = [{"job": "(jobs unavailable)", "what": str(e)}]
    runs = load_json(os.path.join(STATE, "runs.json"), [])
    try:
        owed = [{"id": i, "action": a, "reason": r} for i, a, r in motion.pending()]
    except Exception as e:  # noqa: BLE001
        owed = [{"id": "", "action": "error", "reason": str(e)}]
    return {"jobs": jobs, "runs": runs[-15:][::-1] if isinstance(runs, list) else [], "motion_owed": owed}


def story():
    import story as story_mod  # late: story.py reads these views for its facts
    qfile = os.path.join(story_mod.STORY, "questions.json")
    latest = load_json(os.path.join(story_mod.STORY, "latest.json"), {})
    rfile = os.path.join(story_mod.STORY, "responses.json")
    return {"latest": latest, "questions": story_mod.load_questions()["questions"], "questions_base": digest(qfile),
            "responses": [r for r in story_mod.load_responses()["responses"] if r.get("run_id") == latest.get("run_id")],
            "responses_base": digest(rfile),
            "feedback": next((x for x in story_mod.load_feedback()["feedback"] if x.get("run_id") == latest.get("run_id")), None),
            "feedback_base": digest(os.path.join(story_mod.STORY, "feedback.json")), "ratings": list(story_mod.RATINGS)}


#: Every view by name, in the order the page shows them; each takes the day.
VIEWS = {
    "genome": lambda today: genome.load(),
    "story": lambda today: story(),
    "posts": posts,
    "calendar": calendar,
    "themes": themes,
    "accounts": lambda today: accounts(),
    "suggested": lambda today: {"rows": suggested(), "days": SUGGEST_DAYS, "min_hits": SUGGEST_MIN_HITS},
    "listening": lambda today: listening(),
    "replies": lambda today: replies(),
    "claims": lambda today: claims(),
    "learning": lambda today: learning(),
    "engine": lambda today: engine(),
    "setup": lambda today: setup(),
    "policy": lambda today: policy(),
    "reactions": lambda today: reactions(),
    "reviews": lambda today: reviews(),
}


def get(name, today=None):
    """One view. An unknown name is a KeyError, said plainly."""
    if name not in VIEWS:
        raise KeyError(f"no view called {name!r}; the views are: {', '.join(VIEWS)}")
    return VIEWS[name](today or dt.date.today().isoformat())


def snapshot(names=None):
    """Every view (or those named), with the stream and the day: what the page
    reads. One view that cannot be read is None with its error listed, and
    never blanks the others."""
    today = dt.date.today().isoformat()
    out = {"built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "stream": stream_name(), "today": today, "errors": []}
    for name in names or VIEWS:
        try:
            out[name] = get(name, today)
        except Exception as e:  # noqa: BLE001 - one unreadable file never blanks the page
            out[name] = None
            out["errors"].append(f"{name}: {e}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="The engine's views, read from the record.")
    ap.add_argument("names", nargs="*", help="the views to print; none lists them")
    ap.add_argument("--all", action="store_true", help="every view, as the page reads them")
    ap.add_argument("--out", help="write the JSON here instead of printing it")
    args = ap.parse_args(argv)
    if not args.names and not args.all:
        first = (__doc__.split("The views, in the order the page shows them:")[1]).split("\n\n")[1]
        print(first)
        return 0
    unknown = [n for n in args.names if n not in VIEWS]
    if unknown:
        print(f"views: no view called {', '.join(unknown)}; the views are: {', '.join(VIEWS)}", file=sys.stderr)
        return 2
    data = snapshot(None if args.all else args.names)
    text = json.dumps(data, indent=1, ensure_ascii=False, default=str)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"views: wrote {len(data) - 4} view(s) to {args.out}" + (f"; errors: {data['errors']}" if data["errors"] else ""))
    else:
        print(text)
    return 1 if data["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
