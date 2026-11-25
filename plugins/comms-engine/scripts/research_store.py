#!/usr/bin/env python3
"""
research_store.py - the research store: ingest, query, export (plan v2, A16).

The store is a Graphiti graph over FalkorDB (`research-store/`). This script
is its only writer and the only reader the engine uses. It has two modes and
says which one it is in:

  graph   `graphiti_core` is importable and FalkorDB answers: episodes are
          written and the queries run over the graph.
  files   otherwise: the same episodes are shaped and written to the day's
          watch log (`Docs/Research/watch/<date>.md`, gitignored), the
          queries run over the files, and the output carries `mode: files`.
          Nothing that gates or publishes depends on the store being up.

Episodes are shaped here, deterministically, from what the engine already
holds: the register's rows, the vault notes with their cites, the signals'
findings, and the watch's candidate claims (one checkable statement each with
source, date, tier and theme). Promotion into `claims.md` is never done here:
`/corpus-analyse` reads `candidates` and proposes rows; `/corpus-update
--apply` writes them.

  engine research_store status
  engine research_store ingest            # register, notes, signals -> episodes
  engine research_store watch --from state/signals.json   # the daily watch
  engine research_store candidates        # candidates whose corroboration changed
  engine research_store topic-map         # the monthly map per hashtag
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
REPO = paths.instance()
STATE = paths.state()
WATCH_DIR = os.path.join(REPO, "Docs", "Research", "watch")
sys.path.insert(0, HERE)
import memory  # noqa: E402
import repo  # noqa: E402

TIER_OF_SOURCE = (
    (re.compile(r"regulator|supervisor|authority|central bank|standards? body|standard|commission|government|ministry", re.I), "primary"),
    (re.compile(r"report|institute|university|oliver wyman|mckinsey|bcg", re.I), "institutional"),
    (re.compile(r"coindesk|the block|ledger insights|reuters|ft\b|bloomberg|press", re.I), "trade"),
)


# ── connection ──────────────────────────────────────────────────────────────

def client(stream=memory.DEFAULT_STREAM):
    """A Graphiti client when the package and the database are both there,
    else None. Never raises: a missing store is the files mode."""
    try:
        from graphiti_core import Graphiti  # noqa: F401
        from graphiti_core.driver.falkordb_driver import FalkorDriver
    except Exception:
        return None
    try:
        host = os.environ.get("RESEARCH_STORE_HOST", "localhost")
        port = int(os.environ.get("RESEARCH_STORE_PORT", "6379"))
        driver = FalkorDriver(host=host, port=port, database=f"research-{stream}")
        return Graphiti(graph_driver=driver)
    except Exception:
        return None


def mode(stream=memory.DEFAULT_STREAM):
    return "graph" if client(stream) is not None else "files"


# ── episodes ────────────────────────────────────────────────────────────────

def _episode(kind, name, body, stream_name, at, meta=None):
    return {"id": kind + ":" + hashlib.sha1((name + body).encode("utf-8")).hexdigest()[:12],
            "kind": kind, "name": name, "body": body, "stream": stream_name,
            "at": at, "meta": meta or {}}


def episodes_from_register(stream=memory.DEFAULT_STREAM):
    row = memory.stream(stream)
    out = []
    for cid, r in memory.load_claims(stream).items():
        body = (f"Claim {cid} ({r['grade']}, {r['tier']}, {r['corroboration']}"
                + (f", superseded by {r['superseded_by']}" if r["superseded_by"] else "") + f"): {r['claim']} "
                f"Source: {r['source']} ({r['date']}). Themes: {', '.join(r['themes']) or 'none'}.")
        out.append(_episode("claim", cid, body, row["name"], r["date"],
                            {"grade": r["grade"], "tier": r["tier"], "corroboration": r["corroboration"], "themes": r["themes"]}))
    return out


def episodes_from_notes(stream=memory.DEFAULT_STREAM, items=None):
    row = memory.stream(stream)
    out = []
    for i in (repo.load_items() if items is None else items):
        if i.get("stream") != row["name"]:
            continue
        body = (f"Content {i['id']} on {i.get('theme', '')}: {i.get('title', '')}. "
                f"Cites: {', '.join(i.get('cites') or []) or 'none'}. Status: {i.get('alpha_status', '')}"
                + (f", published {i['published_at']}" if i.get("published_at") else "") + ".")
        out.append(_episode("content", i["id"], body, row["name"], str((i.get("slot") or {}).get("date", "")),
                            {"theme": i.get("theme", ""), "cites": list(i.get("cites") or [])}))
    return out


def episodes_from_signals(stream=memory.DEFAULT_STREAM, signals=None):
    row = memory.stream(stream)
    sig = signals
    if sig is None:
        p = os.path.join(STATE, "signals.json")
        sig = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    out = []
    for f in sig.get("findings", []) or []:
        ev = (f.get("evidence") or [{}])[0] if isinstance(f.get("evidence"), list) else {}
        body = (f"Finding {f.get('id', '')} on {f.get('theme', '')}: {f.get('finding', '')} "
                f"Evidence: {ev.get('title', '')} {ev.get('url', '')}. Relevance {f.get('relevance', '')}, "
                f"sentiment {f.get('sentiment', '')}, content {f.get('content', '')}.")
        out.append(_episode("finding", str(f.get("id", "")), body, row["name"], str(sig.get("run_id", ""))[:10],
                            {"theme": f.get("theme", ""), "url": ev.get("url", "")}))
    return out


def tier_of(source_text):
    for pat, tier in TIER_OF_SOURCE:
        if pat.search(source_text or ""):
            return tier
    return "social"


def candidates_from_findings(findings, stream_name, today):
    """Claim candidates from a watch's findings: one checkable statement each
    with source, date, tier and theme. A finding without evidence yields
    nothing; a candidate never carries a grade above `asserted`."""
    out = []
    for f in findings:
        ev = (f.get("evidence") or [{}])[0] if isinstance(f.get("evidence"), list) else {}
        src = ev.get("title") or ev.get("source") or ""
        if not src or not str(f.get("finding", "")).strip():
            continue
        statement = str(f.get("finding")).strip().rstrip(".") + "."
        out.append({
            "candidate_id": "W-" + hashlib.sha1((statement + src).encode("utf-8")).hexdigest()[:10],
            "stream": stream_name, "claim": statement, "theme": f.get("theme", ""),
            "source": src, "url": ev.get("url", ""), "date": str(f.get("at") or today),
            "tier": tier_of(src + " " + ev.get("url", "")), "grade": "asserted",
            "corroboration": "watching", "seen": [str(today)],
        })
    return out


# ── the watch log (files mode, and the audit trail in graph mode) ───────────

def watch_log_path(today):
    return os.path.join(WATCH_DIR, f"{today}.md")


def write_watch_log(candidates, today, path=None):
    path = path or watch_log_path(today)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [f"# watch — {today}", "", "Claim candidates from the day's primary-source sweep. Not memory: "
             "`/corpus-analyse` proposes rows, `/corpus-update --apply` writes them.", "",
             "| candidate | theme | claim | source | tier | date | corroboration |", "|---|---|---|---|---|---|---|"]
    for c in candidates:
        lines.append(f"| {c['candidate_id']} | {c['theme']} | {c['claim'].replace('|', '/')} | {c['source'].replace('|', '/')}"
                     f"{(' ' + c['url']) if c.get('url') else ''} | {c['tier']} | {c['date']} | {c['corroboration']} |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def merge_candidates(existing, new):
    """Merge today's candidates into the running set: the same statement
    from a second independent source lifts corroboration to two-independent;
    a repeat of the same source only extends `seen`."""
    by = {c["candidate_id"]: dict(c) for c in existing}
    by_claim = {}
    for c in by.values():
        by_claim.setdefault(c["claim"].lower(), []).append(c["candidate_id"])
    for c in new:
        if c["candidate_id"] in by:
            seen = by[c["candidate_id"]].setdefault("seen", [])
            if c["seen"][0] not in seen:
                seen.append(c["seen"][0])
            continue
        siblings = by_claim.get(c["claim"].lower(), [])
        if siblings:
            first = by[siblings[0]]
            if c["source"].lower() != first["source"].lower():
                first["corroboration"] = "two-independent" if first["tier"] != "primary" and c["tier"] != "primary" else "primary"
                first.setdefault("also", []).append({"source": c["source"], "url": c.get("url", ""), "tier": c["tier"], "date": c["date"]})
                first.setdefault("changed", []).append(c["seen"][0])
            continue
        if c["tier"] == "primary":
            c["corroboration"] = "primary"
            c.setdefault("changed", []).append(c["seen"][0])
        by[c["candidate_id"]] = c
        by_claim.setdefault(c["claim"].lower(), []).append(c["candidate_id"])
    return list(by.values())


def candidates_path(state=None):
    return os.path.join(state or STATE, "watch-candidates.json")


def load_candidates(state=None):
    p = candidates_path(state)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else []


def save_candidates(cands, state=None):
    p = candidates_path(state)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cands, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)


def watch(findings, stream=memory.DEFAULT_STREAM, state=None, today=None, log_path=None):
    """The daily watch: candidates from the findings, merged into the running
    set, logged for the day; in graph mode also written as episodes."""
    today = today or dt.date.today().isoformat()
    row = memory.stream(stream)
    new = candidates_from_findings(findings, row["name"], today)
    merged = merge_candidates(load_candidates(state), new)
    save_candidates(merged, state)
    path = write_watch_log(new, today, log_path)
    written = 0
    g = client(stream)
    if g is not None:
        written = _add_episodes(g, [_episode("candidate", c["candidate_id"], f"Candidate claim on {c['theme']}: {c['claim']} Source: {c['source']} ({c['tier']}, {c['date']}).", row["name"], c["date"]) for c in new])
    return {"mode": "graph" if g is not None else "files", "new": len(new), "total": len(merged), "log": path, "episodes": written}


def promotable(state=None, since=None):
    """Candidates whose corroboration reached a citable level: what
    `/corpus-analyse` proposes as register rows. `since` (ISO date) limits to
    candidates that changed after it."""
    out = []
    for c in load_candidates(state):
        if c.get("corroboration") in memory.CITABLE_CORROBORATION:
            if since and not any(d > since for d in c.get("changed", [])):
                continue
            out.append(c)
    return out


# ── the topic map ───────────────────────────────────────────────────────────

def topic_map(stream=memory.DEFAULT_STREAM, state=None, month=None, signals=None, items=None, changes=None, candidates=None):
    """Per hashtag: sub-topics covered, perspectives seen, open questions from
    replies, claims changed since last month. Files mode reads what it can;
    graph mode would read the same through the store."""
    row = memory.stream(stream)
    month = month or dt.date.today().strftime("%Y-%m")
    tags = memory.theme_tags(stream)
    sig = signals
    if sig is None:
        p = os.path.join(state or STATE, "signals.json")
        sig = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    chg = changes
    if chg is None:
        p = os.path.join(state or STATE, "claims-changes.json")
        chg = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else []
    cands = load_candidates(state) if candidates is None else candidates
    its = [i for i in (repo.load_items() if items is None else items) if i.get("stream") == row["name"]]
    reg = memory.load_claims(stream)
    out = {}
    for t in tags:
        findings = [f for f in sig.get("findings", []) or [] if f.get("theme") == t]
        out[t] = {
            "sub_topics": sorted({str(i.get("title", ""))[:80] for i in its if i.get("theme") == t}),
            "perspectives": sorted({str(f.get("sentiment", "")) for f in findings if f.get("sentiment")}),
            "open_questions": [str(f.get("conversation")) for f in findings if f.get("conversation") and str(f.get("conversation")).strip().lower() not in ("none", "null", "{}")],
            "claims_changed": sorted({c["id"] for c in chg if c["id"] in reg and t in reg[c["id"]]["themes"] and str(c.get("seen_at", ""))[:7] == month}),
            "candidates_watching": [c["candidate_id"] for c in cands if c.get("theme") == t and c.get("corroboration") == "watching"],
        }
    return {"stream": row["name"], "month": month, "mode": mode(stream), "themes": out}


def topic_map_markdown(tm):
    lines = [f"## topic map — {tm['month']} (mode: {tm['mode']})", ""]
    for t, x in tm["themes"].items():
        lines.append(f"### {t}")
        lines.append(f"- sub-topics covered: {', '.join(x['sub_topics']) or 'none'}")
        lines.append(f"- perspectives seen: {', '.join(x['perspectives']) or 'none'}")
        lines.append(f"- open questions from replies: {len(x['open_questions'])}")
        lines.append(f"- claims changed this month: {', '.join(x['claims_changed']) or 'none'}")
        lines.append(f"- candidates watching: {', '.join(x['candidates_watching']) or 'none'}")
        lines.append("")
    return "\n".join(lines)


def write_topic_map(tm, campaign_path):
    """Replace or append the `## topic map` section in the campaign file."""
    text = open(campaign_path, encoding="utf-8").read() if os.path.exists(campaign_path) else ""
    block = topic_map_markdown(tm).rstrip("\n") + "\n"
    pat = re.compile(r"(?ms)^## topic map —.*?(?=^## |\Z)")
    if pat.search(text):
        text = pat.sub(lambda m: block + "\n", text, count=1)
    else:
        text = text.rstrip("\n") + "\n\n" + block
    with open(campaign_path, "w", encoding="utf-8") as f:
        f.write(text)
    return campaign_path


# ── graph writes (graph mode only) ──────────────────────────────────────────

def _add_episodes(g, episodes):
    import asyncio
    from graphiti_core.nodes import EpisodeType

    async def go():
        n = 0
        for e in episodes:
            await g.add_episode(name=e["name"], episode_body=e["body"], source=EpisodeType.text,
                                source_description=f"{e['kind']} ({e['stream']})",
                                reference_time=dt.datetime.fromisoformat(e["at"] + ("T00:00:00+00:00" if len(e["at"]) == 10 else "")) if e["at"] else dt.datetime.now(dt.timezone.utc))
            n += 1
        return n
    return asyncio.run(go())


def ingest(stream=memory.DEFAULT_STREAM, state=None):
    eps = episodes_from_register(stream) + episodes_from_notes(stream) + episodes_from_signals(stream)
    g = client(stream)
    if g is None:
        return {"mode": "files", "episodes": len(eps), "written": 0}
    return {"mode": "graph", "episodes": len(eps), "written": _add_episodes(g, eps)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="the research store: ingest, watch, candidates, topic map")
    ap.add_argument("--stream", default=memory.DEFAULT_STREAM)
    ap.add_argument("--state", default=STATE)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status"); sub.add_parser("ingest")
    w = sub.add_parser("watch"); w.add_argument("--from", dest="src", default=os.path.join(STATE, "signals.json"))
    c = sub.add_parser("candidates"); c.add_argument("--since")
    t = sub.add_parser("topic-map"); t.add_argument("--write", help="campaign file to carry the `## topic map` section")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "status" or a.cmd is None:
            print(f"research store: mode {mode(a.stream)}; candidates {len(load_candidates(a.state))}; watch log dir {os.path.relpath(WATCH_DIR, REPO)}")
        elif a.cmd == "ingest":
            print(json.dumps(ingest(a.stream, a.state)))
        elif a.cmd == "watch":
            sig = json.load(open(a.src, encoding="utf-8"))
            out = watch(sig.get("findings", []) or [], a.stream, a.state)
            print(f"watch ({out['mode']}): {out['new']} new candidate(s), {out['total']} in the running set, log {os.path.relpath(out['log'], REPO)}")
        elif a.cmd == "candidates":
            for c_ in promotable(a.state, a.since):
                print(f"{c_['candidate_id']}  {c_['theme']:<20} {c_['corroboration']:<16} {c_['claim'][:70]}  [{c_['source']}]")
        elif a.cmd == "topic-map":
            tm = topic_map(a.stream, a.state)
            if a.write:
                print(f"wrote the topic map into {os.path.relpath(write_topic_map(tm, a.write), REPO)}")
            else:
                print(topic_map_markdown(tm))
    except memory.SharedMemoryError as e:
        print(f"research_store: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
