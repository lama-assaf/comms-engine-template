#!/usr/bin/env python3
"""
review.py - the reviewers judge, code checks what they said and stamps the verdict.

Why: the gatekeeper used to read a draft and write its own verdict and its own
`reviewed_at` into the item. A model that stamps its own review can pass a
claim on a cite that does not carry it, and nothing notices. Here the reviewer
returns findings as JSON, one per sentence (is it a claim, which row of the
claims register it cites, the words of that row it rests on, whether the row
supports it), and this script decides what they are worth:

  - every sentence the reviewer quotes is in the text, word for word, and
    every sentence of the text was judged;
  - a claim sentence has a cite, the cite is a current, corroborated row the
    item lists in its `cites`, and the words it rests on are in that row;
  - or, for a fact about a third party only (standing rule 5: "a primary
    source cited in the piece"), the cite is a source the item lists under
    `sources` (`S1`): its link is in the text that ships, listening read it
    (`state/signals.json` or the ledger `state/evidence.json`), and the words
    the claim rests on are in what listening quoted from it. A sentence about
    the brand ("we", "our", its name), a statistic or a capability never rests
    on a source;
  - a present-tense capability sentence (gate_lint's pattern, the stream's own
    verbs) must be judged a claim and its own cite must be a row at grade
    evidenced; a sentence with a statistic must be judged a claim with a cite.
    One evidenced cite somewhere in the item clears nothing else;
  - with two reviewers, both must agree, sentence by sentence. A disagreement
    is a block, whichever of them was right;
  - house style (the check `register`: the hook, the tag line, the link, the
    shape) is advice. It is kept on the item as `gate.style` for the writer and
    a person, and never moves the verdict.

The verdict is the worst of the deterministic gate (gate_lint.py, run again
here on the same text) and the review. It is written into the item's `gate`
with a stamp keyed by the hash of the text it was given for
(`gate.review.text_hash`), so a stamp says nothing about a text that changed
since. Nothing here approves and nothing sends.

  engine review schema                       # what a reviewer returns
  engine review sentences [<id>...] [--file F]   # the sentences a reviewer must judge
  engine review apply --first A.json [--second B.json] [--dry-run]
  engine review check <id>                   # is this item's stamp current
  engine review evidence                     # keep what listening read in state/evidence.json

`sentences` prints, per item, the very sentences `verify` looks for, split
the way gate_lint splits them: the items with `alpha_status` proposed or
approved (or the ids given) from the vault and the inbox, or the JSON list in
`--file`. A reviewer copies them rather than splitting the text itself, so a
title or a teaser is never left unjudged by a different reading of where a
sentence ends.

`--first` and `--second` are the two reviewers' replies (a file holding
`{"items": [...]}`; a workflow run record's reply is that file). Exit 0 when the
findings were read and every item got its verdict, block included; 1 when a
findings file does not read.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
STATE = paths.state()
sys.path.insert(0, HERE)

import gate_lint  # noqa: E402
import memory  # noqa: E402
import repo  # noqa: E402

PREFIX = "review: "
SECOND = "review (second): "
REVIEWER = "review.py"
FIELDS = ("title", "post", "teaser_linkedin", "teaser_x")
RESULTS = ("pass", "edit", "block")
#: The judgment checks a reviewer may report beside its sentences (claim-gate, checks 1 to 9).
CHECK_NAMES = ("status words", "present-tense spec", "dates", "names", "stealth", "stats", "single-pillar",
               "register", "licence")
#: The one check that is house style: what a reviewer says under it is advice.
STYLE_CHECK = "register"
STAT_RE = re.compile(r"\d[\d,.]*\s*(?:%|percent\b|x\b|×)", re.I)
#: The fewest characters of a row a claim may be said to rest on: a word is not evidence.
MIN_RESTS_ON = 12
SOURCE_ID = re.compile(r"^S\d+$")
EVIDENCE_FILE = "evidence.json"
FIRST_PERSON = re.compile(r"\b(?:we|our|ours|us)\b", re.I)

SCHEMA = {
    "type": "object",
    "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "required": ["id", "sentences"],
        "properties": {
            "id": {"type": "string", "description": "the item's id"},
            "sentences": {"type": "array", "description": "every sentence of title, post and both teasers, in order", "items": {
                "type": "object",
                "required": ["field", "text", "claim"],
                "properties": {
                    "field": {"type": "string", "enum": list(FIELDS)},
                    "text": {"type": "string", "description": "the sentence, word for word"},
                    "claim": {"type": "boolean", "description": "does it state a checkable fact about the brand, a partner, a number or a date"},
                    "cite": {"type": ["string", "null"], "description": "the claims register id it rests on, when it is a claim; for a fact about a third party only, the id of a source the item lists under `sources` (S1)"},
                    "rests_on": {"type": "string", "description": "the words of that row's claim it rests on, copied from the row"},
                    "supported": {"type": "boolean", "description": "does that row carry this sentence, in this tense"},
                    "why": {"type": "string"}}}},
            "checks": {"type": "array", "items": {
                "type": "object",
                "required": ["check", "result"],
                "properties": {"check": {"type": "string", "enum": list(CHECK_NAMES)},
                               "result": {"type": "string", "enum": list(RESULTS)},
                               "line": {"type": "string"}, "fix": {"type": "string"}}}},
            "note": {"type": "string", "description": "one sentence on what judgment remains for a person"}}}}},
}


class ReviewError(RuntimeError):
    """The findings could not be read. Never turned into a pass."""


def _norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def text_key(item):
    """The hash a stamp is keyed by: the four fields that ship (repo.base_hash)."""
    return repo.base_hash(item)


def _wordy(sentence):
    """Whether a line says anything: a tag line or a bare link is not a sentence to judge."""
    bare = re.sub(r"https?://\S+|#[A-Za-z][A-Za-z0-9_]*|@[A-Za-z0-9_]+", " ", sentence)
    return len(re.findall(r"[A-Za-z]{2,}", bare)) >= 2


def sentences(item):
    """`[(field, sentence)]`: every sentence of the text that ships, as gate_lint splits them."""
    out = []
    for field in FIELDS:
        for s in gate_lint._sentences(str(item.get(field) or "")):
            if _wordy(s):
                out.append((field, _norm(s)))
    return out


def to_judge(items, ids=()):
    """`{"items": [{id, sentences: [{field, text}]}]}` for the items a reviewer reads: the ids
    given, else every item with `alpha_status` proposed or approved."""
    wanted = [i for i in ids if i]
    out = []
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        if wanted and item["id"] not in wanted:
            continue
        if not wanted and item.get("alpha_status", "proposed") not in ("proposed", "approved"):
            continue
        out.append({"id": item["id"], "sentences": [{"field": f, "text": s} for f, s in sentences(item)]})
    return {"items": out}


def _evidence_rows(signals):
    """Every source a listening pass quoted: `[{stream, finding, url, title, quote}]`, https only."""
    out = []
    for f in (signals or {}).get("findings") or []:
        if not isinstance(f, dict):
            continue
        for ev in f.get("evidence") or []:
            url = str((ev or {}).get("url") or "").strip() if isinstance(ev, dict) else ""
            if url.startswith("https://"):
                out.append({"stream": f.get("stream") or signals.get("stream"), "finding": f.get("id"), "url": url,
                            "title": _norm(ev.get("title")), "quote": _norm(ev.get("quote"))})
    return out


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def load_evidence(state=None):
    """What listening has read: the current pass (`signals.json`) and the ledger (`evidence.json`)."""
    state = state or STATE
    ledger = _read_json(os.path.join(state, EVIDENCE_FILE), {}) or {}
    return _evidence_rows(_read_json(os.path.join(state, "signals.json"), {})) + \
        [r for r in ledger.get("sources", []) or [] if isinstance(r, dict)]


def record_evidence(state=None, now=None):
    """Append the current pass's sources to `state/evidence.json`, once per link and quote, so a
    draft that rests on one still checks after the next pass replaces `signals.json`. Returns the count added."""
    state = state or STATE
    path = os.path.join(state, EVIDENCE_FILE)
    ledger = _read_json(path, {}) or {}
    rows = [r for r in ledger.get("sources", []) or [] if isinstance(r, dict)]
    seen = {(r.get("url"), r.get("quote")) for r in rows}
    at = (now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds")
    added = 0
    for r in _evidence_rows(_read_json(os.path.join(state, "signals.json"), {})):
        if (r["url"], r["quote"]) not in seen and r["stream"]:
            seen.add((r["url"], r["quote"]))
            rows.append(dict(r, at=at))
            added += 1
    if added:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"sources": rows}, f, indent=1, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    return added


def _about_the_brand(text, slug):
    try:
        names = {memory.stream(slug)["name"], slug} if slug else set()
    except memory.SharedMemoryError:
        names = {slug}
    words = [n for n in names if n]
    return bool(FIRST_PERSON.search(text)) or any(re.search(rf"\b{re.escape(n)}\b", text, re.I) for n in words)


def _source_problem(item, row, cid, fields, evidence, slug):
    """Why a claim may not rest on the source `cid`, or None."""
    src = next((s for s in item.get("sources") or [] if isinstance(s, dict) and str(s.get("id") or "").strip() == cid), None)
    if src is None:
        return f"it rests on source {cid}, which the item's `sources` does not list"
    url = str(src.get("url") or "").strip()
    if not url.startswith("https://"):
        return f"source {cid} has no https link"
    if not any(url in text for text in fields.values()):
        return f"source {cid} is not linked in the text that ships"
    stream = str(item.get("stream") or "").strip()
    heard = [e for e in evidence if e.get("url") == url and (not stream or e.get("stream") == stream)]
    if not heard:
        return f"source {cid} is not one listening read"
    rests = _norm(row.get("rests_on")).lower()
    if len(rests) < MIN_RESTS_ON or not any(rests in _norm(e.get("quote")).lower() for e in heard):
        return f"the words it is said to rest on are not in what listening quoted from source {cid}"
    if _about_the_brand(row["text"], slug):
        return "a sentence about the brand rests on a source; it needs a row of the claims register"
    if row.get("supported") is not True:
        return f"source {cid} does not support it ({_norm(row.get('why')) or 'no reason given'})"
    return None


def _entry(name, result, line="", fix="", prefix=PREFIX):
    return {"check": prefix + name, "result": result, "line": line, "fix": fix}


def verify(item, finding, slug=None, evidence=None):
    """What one reviewer's findings on one item are worth.

    Returns `{"verdict", "checks", "problems", "sentences", "claims", "judged"}`. `problems` are
    the reasons code does not accept the findings as a pass, each naming its sentence; `judged`
    maps every sentence of the text to whether the reviewer read it as a claim (None: not
    judged), which is what two reviewers are compared on.
    """
    problems = []
    fields = {f: _norm(item.get(f) or "") for f in FIELDS}
    listed = [str(c).strip() for c in (item.get("cites") or []) if str(c).strip()]
    try:
        register = memory.load_claims(slug)
        capability = gate_lint.capability_for(slug)
    except memory.SharedMemoryError as e:
        return {"verdict": "block", "problems": [f"the claims register or the gate rules did not read: {e}"],
                "checks": [_entry("claims", "block", "", f"the claims register or the gate rules did not read: {e}")],
                "sentences": 0, "claims": 0, "judged": {}, "style": []}
    rows = finding.get("sentences")
    if not isinstance(rows, list):
        rows = []
        problems.append("the reviewer returned no sentences")
    good = []
    for row in rows:
        if not isinstance(row, dict) or row.get("field") not in FIELDS or not isinstance(row.get("text"), str) \
                or not isinstance(row.get("claim"), bool):
            problems.append("a finding without a field, a text and a true or false `claim`")
            continue
        text = _norm(row["text"])
        if not text or text not in fields[row["field"]]:
            problems.append(f"the reviewer quotes a sentence the {row['field']} does not carry: {text[:120]!r}")
            continue
        good.append(dict(row, text=text))
    claims = 0
    for row in good:
        if not row["claim"]:
            continue
        claims += 1
        short = row["text"][:140]
        cid = str(row.get("cite") or "").strip()
        if not cid:
            problems.append(f"a claim with no cite: {short!r}")
            continue
        if SOURCE_ID.match(cid):
            why = _source_problem(item, row, cid, fields, load_evidence() if evidence is None else evidence, slug)
            if why:
                problems.append(f"{why}: {short!r}")
            continue
        ok, why = memory.citable(cid, claims=register)
        if not ok:
            problems.append(f"{why}: {short!r}")
            continue
        if cid not in listed:
            problems.append(f"it rests on {cid}, which the item's `cites` does not list: {short!r}")
            continue
        rests = _norm(row.get("rests_on")).lower()
        if len(rests) < MIN_RESTS_ON or rests not in _norm(register[cid].get("claim")).lower():
            problems.append(f"the words it is said to rest on are not in row {cid}: {short!r}")
            continue
        if row.get("supported") is not True:
            problems.append(f"row {cid} does not support it ({_norm(row.get('why')) or 'no reason given'}): {short!r}")
    judged = {}
    for field, s in sentences(item):
        over = [r for r in good if r["field"] == field and (s in r["text"] or r["text"] in s)]
        judged[(field, s)] = any(r["claim"] for r in over) if over else None
        if not over:
            problems.append(f"a sentence the reviewer did not judge ({field}): {s[:140]!r}")
            continue
        cited = [str(r.get("cite") or "").strip() for r in over if r["claim"] and str(r.get("cite") or "").strip() in register]
        if capability.search(gate_lint.CAPABILITY_MASK.sub("", s)):
            if not judged[(field, s)]:
                problems.append(f"a present-tense capability sentence the reviewer did not read as a claim: {s[:140]!r}")
            elif not any(register[c]["grade"] == "evidenced" for c in cited):
                problems.append(f"a present-tense capability sentence whose own cite is not at grade evidenced: {s[:140]!r}")
        elif STAT_RE.search(s) and not cited:
            problems.append(f"a statistic with no cite of its own: {s[:140]!r}")
    checks, style = [], []
    for c in finding.get("checks") or []:
        if not isinstance(c, dict) or c.get("result") not in RESULTS or not str(c.get("check") or "").strip():
            problems.append("a check without a name and a result of pass, edit or block")
            continue
        name = str(c["check"]).strip()
        if name == STYLE_CHECK:
            # house style is advice: it is shown to the writer and a person, and never moves the verdict
            if c["result"] != "pass":
                style.append({"line": _norm(c.get("line")), "fix": _norm(c.get("fix"))})
            continue
        checks.append(_entry(name, c["result"], _norm(c.get("line")), _norm(c.get("fix"))))
    if style:
        checks.append(_entry(STYLE_CHECK, "pass", style[0]["line"],
                             "House style, as advice (it does not change the verdict): " + "; ".join(s["fix"] for s in style)[:600]))
    first = problems[0] if problems else ""
    line = re.search(r": '(.*)'$", first)
    checks.insert(0, _entry("claims", "block" if problems else "pass", line.group(1) if line else "",
                            "; ".join(problems)[:900] if problems
                            else f"{claims} claim sentence(s), each on a current row whose words it quotes; "
                                 f"{len(judged)} sentence(s) judged."))
    return {"verdict": gate_lint.verdict_of(checks), "checks": checks, "problems": problems,
            "sentences": len(judged), "claims": claims, "judged": judged, "style": style}


def disagreements(first, second):
    """Where two reviewers differ: on a sentence being a claim, or on the item blocking at all."""
    out = []
    for key, a in first["judged"].items():
        b = second["judged"].get(key)
        if a is not None and b is not None and a != b:
            out.append(f"one reviewer reads it as a claim and the other does not ({key[0]}): {key[1][:140]!r}")
    if (first["verdict"] == "block") != (second["verdict"] == "block"):
        out.append("one reviewer blocks the item and the other does not")
    return out


def review(item, first, second=None, slug=None, corpus=None, now=None, evidence=None):
    """The item's whole `gate`, as code decides it from the reviewers' findings and the lint.

    `first` and `second` are the two reviewers' findings on this item (`second` may be None: a
    single review is stamped with one reviewer, which the engine's own approval does not accept).
    """
    slug = gate_lint.resolve_slug(item) if slug is None else slug
    lint = gate_lint.lint(item, corpus=corpus)
    evidence = load_evidence() if evidence is None else evidence
    a = verify(item, first, slug, evidence)
    checks = list(a["checks"])
    problems = list(a["problems"])
    style = list(a["style"])
    reviewers = [str(first.get("reviewer") or "first")]
    if second is not None:
        b = verify(item, second, slug, evidence)
        reviewers.append(str(second.get("reviewer") or "second"))
        diff = disagreements(a, b)
        style += [s for s in b["style"] if s not in style]
        problems += [f"second reviewer: {p}" for p in b["problems"]] + diff
        checks += [dict(c, check=SECOND + c["check"][len(PREFIX):]) for c in b["checks"] if c["result"] != "pass"]
        if diff:
            checks.append(_entry("agreement", "block", "", "The two reviewers disagree, which blocks: " + "; ".join(diff)[:600]))
        else:
            checks.append(_entry("agreement", "pass", "", "Both reviewers judged every sentence the same way."))
    review_verdict = gate_lint.verdict_of(checks)
    at = (now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds")
    gate = {"checks": lint["checks"] + checks,
            "verdict": gate_lint.VERDICT[max(gate_lint.RECORDED_RANK[lint["verdict"]], gate_lint.RECORDED_RANK[review_verdict])],
            "linted_at": at, "linted_by": "gate_lint.py", "reviewed_at": at, "reviewed_by": REVIEWER,
            "note_for_alpha": _norm(first.get("note"))[:400], "style": style[:20],
            "review": {"text_hash": text_key(item), "verdict": review_verdict, "at": at, "reviewers": reviewers,
                       "sentences": a["sentences"], "claims": a["claims"], "problems": problems[:20]}}
    return gate


def current(item):
    """The item's review stamp when it was made by this script for the text the item has now, else None."""
    gate = item.get("gate") or {}
    stamp = gate.get("review")
    if not isinstance(stamp, dict) or gate.get("reviewed_by") != REVIEWER:
        return None
    return stamp if stamp.get("text_hash") == text_key(item) else None


def approvable(item):
    """`(ok, why)`: may this item be approved with no person in the loop, as far as the review goes.

    A stamp of this script for the present text, a review that passed, by two reviewers who
    agreed. A verdict written any other way (a hand edit, an older gate) does not count."""
    stamp = current(item)
    if stamp is None:
        return False, "no review stamp for the text as it stands (review.py has not read this text)"
    if stamp.get("verdict") != "pass" or (item.get("gate") or {}).get("verdict") != "pass":
        return False, f"the review's verdict is {stamp.get('verdict')}, not pass"
    if len(stamp.get("reviewers") or []) < 2:
        return False, "one reviewer read it; going out without a person takes two who agree"
    return True, ""


def _load(path, name):
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        raise ReviewError(f"{path}: does not read ({e})")
    if isinstance(doc, dict) and isinstance(doc.get("outputs"), dict):
        doc = doc["outputs"]  # a workflow run record: the reply is its outputs
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
        raise ReviewError(f"{path}: no `items` list")
    out = {}
    for row in doc["items"]:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            out[row["id"]] = dict(row, reviewer=str(doc.get("reviewer") or name))
    return out


def apply(first_path, second_path=None, write=True, now=None, items=None):
    """Stamp every item the first reviewer returned findings for. Returns `{id: {verdict, review, problems}}`.

    An item the second reviewer did not return is treated as a disagreement: its findings are
    empty, so every sentence goes unjudged and the item blocks."""
    first = _load(first_path, "first")
    second = _load(second_path, "second") if second_path else None
    items = gate_lint.items_by_id() if items is None else items
    corpus = list(items.values())
    out = {}
    for item_id, finding in first.items():
        item = items.get(item_id)
        if item is None:
            out[item_id] = {"verdict": "skipped", "review": None, "problems": ["no item carries this id"]}
            continue
        other = None
        if second is not None:
            other = second.get(item_id) or {"id": item_id, "sentences": [], "reviewer": "second"}
        gate = review(item, finding, other, corpus=corpus, now=now)
        if write:
            gate_lint.write_gate(item_id, gate)
        out[item_id] = {"verdict": gate["verdict"], "review": gate["review"]["verdict"], "problems": gate["review"]["problems"]}
    return out


def summary(results):
    counts = {v: sum(1 for r in results.values() if r["verdict"] == v) for v in ("pass", "pass-with-edits", "block")}
    blocked = next((r["problems"][0] for r in results.values() if r["verdict"] == "block" and r["problems"]), "")
    return (f"review.py: {counts['pass']} pass, {counts['pass-with-edits']} pass-with-edits, {counts['block']} block"
            + (f" ({blocked[:120]})" if blocked else "") + "; nothing approved")


def main(argv=None):
    ap = argparse.ArgumentParser(description="check the reviewers' findings and stamp the gate's verdict")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("schema")
    sub.add_parser("evidence")
    s = sub.add_parser("sentences")
    s.add_argument("ids", nargs="*")
    s.add_argument("--file", help="a JSON list of items (the labelled set) instead of the engine's own")
    a = sub.add_parser("apply")
    a.add_argument("--first", required=True)
    a.add_argument("--second")
    a.add_argument("--dry-run", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("id")
    args = ap.parse_args(argv)
    if args.cmd == "schema":
        print(json.dumps(SCHEMA, indent=1))
        return 0
    if args.cmd == "evidence":
        print(f"review: {record_evidence()} source(s) added to state/{EVIDENCE_FILE}")
        return 0
    if args.cmd == "sentences":
        try:
            if args.file:
                with open(args.file, encoding="utf-8") as f:
                    items = json.load(f)
            else:
                items = list(gate_lint.items_by_id().values())
        except (OSError, ValueError) as e:
            print(f"review: the items did not read: {e}", file=sys.stderr)
            return 1
        print(json.dumps(to_judge(items if isinstance(items, list) else [], args.ids), indent=1, ensure_ascii=False))
        return 0
    if args.cmd == "check":
        item = gate_lint.items_by_id().get(args.id)
        if item is None:
            print(f"review: no item {args.id}", file=sys.stderr)
            return 1
        ok, why = approvable(item)
        print("current, two reviewers, pass" if ok else f"not approvable without a person: {why}")
        return 0 if ok else 1
    if args.cmd != "apply":
        print(__doc__.strip().splitlines()[0])
        ap.print_usage(sys.stderr)
        return 2
    try:
        results = apply(args.first, args.second, write=not args.dry_run)
    except ReviewError as e:
        print(f"review: {e}", file=sys.stderr)
        return 1
    for item_id, r in results.items():
        print(f"{item_id}  {r['verdict']}" + (f"  {r['problems'][0][:160]}" if r["problems"] else ""))
    line = summary(results)
    print(line)
    if results and not args.dry_run:
        import runlog
        try:
            runlog.append("gate", line, stream=memory.DEFAULT_STREAM_NAME, reviewed=len(results))
        except Exception as exc:  # the log must never undo a verdict that was written
            print(f"review: runlog failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
