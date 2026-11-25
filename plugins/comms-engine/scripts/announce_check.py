#!/usr/bin/env python3
"""Read a partner-announcement folder and say what stands between it and the calendar.

The folder is the one the comms lead fills (one shared folder per partner):
a blog-post .docx, a social-copy .docx with `## LinkedIn post` and
`## X post` sections, and a banner. This script writes nothing outside
`--out`, posts nothing and calls no paid service. It extracts the copy, runs
the claim gate, adds the checks an announcement needs on top (placeholders,
names spelled two ways, what the calendar autopilot will refuse to post,
claims `status.md` does not carry, whether the partner is cleared to name),
measures the banner, and writes `plan.json` and `plan.md` for `/announce`.

`write` is the one step that writes the calendar: it turns a checked plan into one
calendar item through `repo.py` (status Idea, `drafted_by: team`), the article and,
with `--post engine`, the X post. LinkedIn always goes out by hand (the banner and
typed @mentions), and with `--post hand` so does X, so neither is on the item for an
approval to schedule. It fills `[Date]` and the link placeholders, refuses a plan
with a block finding or a placeholder left, and rewrites the same item on a re-run
while nobody has decided it. The gatekeeper gates it and a person approves it and
marks the article live on the control page, like any draft.

    engine announce_check "<folder>" \\
        --out <scratch>/announce/<partner> [--theme "#<Theme>"] [--slug ...]
    engine announce_check write <scratch>/announce/<partner> \\
        --approved "<the user's approval, word for word>" [--post hand|engine]
"""
import argparse
import datetime as dt
import difflib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
REPO = Path(paths.instance())
import gate_lint  # noqa: E402
import repo  # noqa: E402

MEMORY = REPO / ".atelier" / "memory"
EXTRACT = Path(paths.engine_home()) / "skills" / "deck-reader" / "scripts" / "extract_doc.py"
X_LIMIT = 280            # calendar_autopilot.py counts raw characters, links in full
URL_RE = re.compile(r"https?://\S+")
PLACEHOLDER_RE = re.compile(r"\[(?:date|website link|link|url|tbd|tbc|name|quote|title)[^\]]*\]|\bTBD\b|\bTBC\b|\bXX+\b", re.I)
STAGE_RE = re.compile(r"^(post with|attach|use the|add the|note:|image:)", re.I)
# overlapping on purpose: in "Contact Firstname Lastname" both pairs are seen
NAME_RE = re.compile(r"(?=\b([A-Z][a-z]{2,})\s+([A-Z][a-z]{2,})\b)")

# The announcement rules are data: the `announce` section of the brand's
# .atelier/memory/gate-rules.json, read through memory.load_gate_rules.
# status_flags are claims status.md does not carry, as (regex, why) pairs: an
# operating claim a release could make that the brand's status.md does not
# evidence - live, a date, a figure, a held theme. Approved releases teach the
# file: a phrasing an approved release used goes into cleared_phrases and is
# never flagged again (the approved-copy rule: fix the rules, never the copy).
# voice_flags are vocabulary that belongs to another stream's voice. All three
# ship empty and are written per brand from its status.md and its decisions
# (TEMPLATE-CONTRACT.md, "Not done"); until then the status pass finds nothing.


def rules():
    """`{status_flags: [(regex, why)], voice_flags: [(regex, why)], cleared_re}` from gate-rules.json.

    A file that does not read stops the check (SystemExit with the reason): an
    announcement is never passed on rules that could not be read."""
    try:
        a = gate_lint.memory.load_gate_rules()["announce"]
    except gate_lint.memory.SharedMemoryError as exc:
        raise SystemExit(f"announce_check: {exc}")
    cleared = a["cleared_phrases"]
    return {"status_flags": a["status_flags"], "voice_flags": a["voice_flags"],
            "cleared_re": re.compile("|".join(cleared) if cleared else r"(?!)", re.I)}


BRAND_NAME = gate_lint.BRAND_NAME


def extract(docx: Path, out: Path) -> str:
    subprocess.run([sys.executable, str(EXTRACT), str(docx), "-o", str(out)], check=True,
                   capture_output=True, text=True)
    return out.read_text().split("---\n", 1)[-1]


def section(text: str, heading: str) -> str:
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S | re.I)
    return m.group(1).strip() if m else ""


def strip_stage(text: str) -> tuple[str, list[str]]:
    keep, cut = [], []
    for line in text.splitlines():
        (cut if STAGE_RE.match(line.strip()) else keep).append(line)
    return "\n".join(keep).strip(), [c.strip() for c in cut if c.strip()]


def x_option(x_section: str, option: str = "A") -> str:
    """The chosen `Option X` block of the X section, or the whole section when it has no options."""
    parts = re.split(r"^Option ([A-Z])\s*$", x_section, flags=re.M)
    if len(parts) == 1:
        return x_section.strip()
    options = dict(zip(parts[1::2], (p.strip() for p in parts[2::2])))
    if option.upper() not in options:
        raise SystemExit(f"announce_check: no Option {option} in the X copy (have {', '.join(sorted(options))})")
    return options[option.upper()]


def slugify(title: str, limit: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if len(s) <= limit:
        return s
    return s[:limit].rsplit("-", 1)[0]


def finding(kind, severity, where, line, why):
    return dict(check=kind, severity=severity, where=where, line=line[:240], why=why)


def known_names() -> str:
    """People as shared memory spells them (project.md, voice.md, lessons.md)."""
    return " ".join((MEMORY / f).read_text() for f in ("project.md", "voice.md", "lessons.md") if (MEMORY / f).exists())


def name_clashes(texts: dict) -> list:
    seen = {}
    for where, t in texts.items():
        for first, last in NAME_RE.findall(t):
            seen.setdefault(first, {}).setdefault(last, where)
    out = []
    for first, lasts in seen.items():
        names = sorted(lasts)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                if a != b and difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.8:
                    known = [n for n in (a, b) if f"{first} {n}" in known_names()]
                    why = (f"Memory spells it {first} {known[0]}. Correct the other spelling: a confirmed typo is fixed, not an edit."
                           if len(known) == 1 else
                           "The same person is spelled two ways. Ask the user which is right; fix only the confirmed typo.")
                    out.append(finding("names", "fill" if len(known) == 1 else "note",
                                       f"{lasts[a]} / {lasts[b]}", f"{first} {a} · {first} {b}", why))
    return out


def partner_status(partner: str) -> dict:
    pat = re.compile(rf"\b{re.escape(partner)}\b", re.I)
    public = [l.strip() for l in (MEMORY / "handles.md").read_text().splitlines() if l.startswith("|") and pat.search(l)]
    private_path = MEMORY / "handles.private.md"
    private = [l.strip() for l in private_path.read_text().splitlines() if l.startswith("|") and pat.search(l)] if private_path.exists() else None
    decisions = sorted(p.name for p in (MEMORY / "decisions").glob(f"*{partner.lower()}*"))
    cleared = any("cleared" in l.lower() for l in public) and not private
    return dict(partner=partner, handles_md=public, handles_private_md=private, decisions=decisions,
                cleared=bool(cleared), private_file_present=private is not None)


def banner_plan(paths: list) -> list:
    out = []
    for p in paths:
        info = dict(file=p.name)
        if p.suffix.lower() == ".svg":
            info.update(kind="svg", note="Render first (qlmanage -t -s 2400, or headless Chrome), then size as below.")
        else:
            try:
                from PIL import Image
                with Image.open(p) as im:
                    w, h = im.size
                info.update(kind=p.suffix.lower().lstrip("."), width=w, height=h, ratio=round(w / h, 3))
            except Exception as exc:  # PIL missing or unreadable file: say so, do not guess
                info.update(kind="unknown", note=f"could not read: {exc}")
        r = info.get("ratio")
        info["blog_cover"] = "WebP 2400x1350 (16:9)" + (
            "" if r is None or abs(r - 16 / 9) < 0.04 else f": the source is {r}:1, so pad or crop it, and look at the result before uploading")
        info["linkedin_image"] = ("PNG at the source ratio, 1200 px wide minimum" if r and abs(r - 1.91) < 0.04
                                  else "PNG 1600x900")
        out.append(info)
    return out


FILLABLE_RE = re.compile(r"\[(?:date|website link|link|url)[^\]]*\]", re.I)
ANNOUNCE_PREFIX = "A-"


def fill(text: str, day: str, url: str) -> str:
    """The two fills an announcement may take without an edit: the release day and the article URL."""
    return FILLABLE_RE.sub(lambda m: day if "date" in m.group(0).lower() else url, text)


def announcement_item(plan: dict, approved: str, post: str = "hand", items=None) -> dict:
    """The announcement as one calendar item, or ValueError saying why it cannot be one yet."""
    if post not in ("hand", "engine"):
        raise ValueError(f"--post is hand or engine, not {post!r}")
    approved = " ".join(str(approved or "").split())
    if not approved:
        raise ValueError("no approval: --approved takes the user's own statement, word for word")
    blocks = [x for x in plan.get("findings", []) if x.get("severity") == "block"]
    if blocks:
        raise ValueError("the plan has block findings: " + "; ".join(f"{b['check']}: {b['line']}" for b in blocks)[:400])
    day = repo.as_date(plan.get("date") or "")
    if not isinstance(day, dt.date):
        raise ValueError("no release day: run the check again with --date YYYY-MM-DD")
    slug = plan["slug"]
    url = repo.post_url(slug)
    texts = {k: fill(str(plan.get(k) or ""), day.isoformat(), url) for k in ("blog", "linkedin", "x")}
    left = [f"{k}: {m.group(0)}" for k, t in texts.items() for m in PLACEHOLDER_RE.finditer(t)]
    if left:
        raise ValueError("placeholders still to fill: " + ", ".join(left))
    if not texts["blog"].strip():
        raise ValueError("the plan has no article")
    items = repo.load_items() if items is None else items
    same = [i for i in items if repo.slug_for(i) == slug]
    if same and not str(same[0]["id"]).startswith(ANNOUNCE_PREFIX):
        raise ValueError(f"the slug {slug} is already {same[0]['id']}'s; give the announcement another --slug")
    if same and same[0].get("alpha_status") != "proposed":
        raise ValueError(f"{same[0]['id']} is already {same[0].get('alpha_status')}; nothing written")
    lead = re.split(r"(?<=[.!?])\s+", texts["blog"].strip(), maxsplit=1)[0][:200]
    return {
        "id": same[0]["id"] if same else f"{ANNOUNCE_PREFIX}{day.isoformat()}-{slug[:40].strip('-')}",
        "title": repo.safe_title(plan["title"]), "theme": plan.get("theme") or "", "stream": BRAND_NAME,
        "post": texts["blog"], "teaser_linkedin": "", "teaser_x": texts["x"] if post == "engine" else "",
        "slot": {"date": day.isoformat()}, "slug": slug, "excerpt": lead,
        "drafted_by": repo.TEAM_BY, "drafted_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "alpha_status": "proposed", "format": "Announcement", "type": "Milestone", "pillar": "Partnerships",
        "owner": repo.TEAM_BY, "anchor": approved,
        "gate_writer": {"verdict": plan.get("gate_verdict") or "", "by": "announce_check.py",
                        "checks": [{k: x.get(k) for k in ("check", "severity", "where", "why")} for x in plan.get("findings", [])]},
    }


def write(argv) -> int:
    ap = argparse.ArgumentParser(prog="announce_check.py write", description="write a checked plan as one calendar item")
    ap.add_argument("out", type=Path, help="the --out folder the check wrote plan.json into")
    ap.add_argument("--approved", default="", help="the user's approval, word for word")
    ap.add_argument("--post", default="hand", choices=("hand", "engine"), help="who posts X (LinkedIn is always by hand)")
    a = ap.parse_args(argv)
    try:
        plan = json.loads((a.out / "plan.json").read_text())
        item = announcement_item(plan, a.approved, a.post)
        paths = repo.write_item(item, "Idea")
    except (OSError, ValueError, KeyError) as exc:
        print(f"announce_check write: {exc}. Nothing written.", file=sys.stderr)
        return 2
    repo.write_index()
    print(f"{item['id']}: wrote {os.path.relpath(paths['post'], REPO)}")
    print("Next: the gatekeeper gates it with the cycle; approve it and mark the article live on the control page.")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["write"]:
        return write(argv[1:])
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--theme", default="")
    ap.add_argument("--slug", default="")
    ap.add_argument("--partner", default="", help="defaults to the folder name")
    ap.add_argument("--x-option", default="A", help="which Option block of the X copy (default A)")
    ap.add_argument("--date", default="", help="release day YYYY-MM-DD; shown as the [Date] fill")
    a = ap.parse_args(argv)

    folder, out = a.folder, a.out
    out.mkdir(parents=True, exist_ok=True)
    docs = sorted(folder.glob("*.docx"))
    blog_doc = next((d for d in docs if "blog" in d.name.lower()), None)
    social_doc = next((d for d in docs if "social" in d.name.lower()), None)
    images = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".svg", ".webp"))
    missing = [n for n, d in (("blog post .docx", blog_doc), ("social copy .docx", social_doc)) if d is None]
    if missing:
        print(f"announce_check: the folder has no {', no '.join(missing)}: {folder}", file=sys.stderr)
        return 2

    blog_raw = extract(blog_doc, out / "blog.md")
    social_raw = extract(social_doc, out / "social.md")
    tm = re.search(r"^#\s+(.+)$", blog_raw, re.M)
    title = tm.group(1).strip() if tm else blog_doc.stem
    body = blog_raw[tm.end():].strip() if tm else blog_raw.strip()
    li, li_stage = strip_stage(section(social_raw, "LinkedIn post"))
    x, x_stage = strip_stage(x_option(section(social_raw, "X post"), a.x_option))
    partner = a.partner or folder.name
    slug = a.slug or slugify(title)

    f = []
    # 1. the claim gate. Status words, stealth and partner tags bind every
    #    surface; the theme-post checks (no-claim panel, tag line, CTA, hook)
    #    are written for engine theme posts and are advice for a team release.
    item = dict(id=f"announce-{partner.lower()}", title=title, post=body, teaser_linkedin=li,
                teaser_x=x, theme=a.theme, stream=BRAND_NAME)
    try:
        gate = gate_lint.lint(item)
    except gate_lint.LintError as exc:
        print(f"announce_check: the claim gate could not run: {exc}", file=sys.stderr)
        return 3
    binding = ("status words", "stealth", "partner tags")
    for c in gate["checks"]:
        name = c["check"].replace(gate_lint.PREFIX, "")
        if c["result"] == "pass" or name not in binding:
            continue  # no-claim panel, tag line, CTA, hook: theme-post rules, not newsroom rules
        f.append(finding(f"gate: {name}", "block" if c["result"] == "block" else "learn",
                         "", c.get("line", ""), c.get("fix", "")))
    # 2. placeholders and names
    texts = {"blog": f"{title}\n{body}", "linkedin": li, "x": x}
    for where, t in texts.items():
        for m in PLACEHOLDER_RE.finditer(t):
            fill = (a.date or "the release day") if "date" in m.group(0).lower() else repo.post_url(slug)
            f.append(finding("placeholder", "fill", where, m.group(0), f"Fill with {fill}. Filling a placeholder is not an edit."))
    f += name_clashes(texts)
    # 3. what calendar_autopilot.py will refuse (teaser_problem)
    if len(x) > X_LIMIT:
        f.append(finding("engine: X length", "posting", "x", f"{len(x)} characters",
                         f"The autopilot holds X rows over {X_LIMIT} raw characters; a longer row never posts."))
    for where, t in (("linkedin", li), ("x", x)):
        if URL_RE.search(t) or re.search(r"\[website link\]|read the full announcement", t, re.I):
            f.append(finding("engine: link in body", "posting", where, (URL_RE.search(t) or re.search(r"(?i)read the full announcement.*", t)).group(0),
                             "The autopilot holds any teaser with a link in its body, so this row goes out by hand (the copy keeps its link). "
                             f"Slug {slug}-{where} lets the engine add the link reply if it ever posts a link-free version."))
        if re.search(r"(?<![\w.])@[A-Z][\w ]+", t) and where == "linkedin":
            f.append(finding("linkedin mentions", "posting", where, ", ".join(sorted(set(re.findall(r"@[A-Z][\w]*(?: [A-Z][\w]*)?", t)))),
                             "LinkedIn @mentions only tag when typed in the LinkedIn editor. Post this one by hand, with the banner."))
    for where, cut in (("linkedin", li_stage), ("x", x_stage)):
        for c in cut:
            f.append(finding("stage direction", "posting", where, c, "Instruction to the poster, removed from the copy. Follow it by hand."))
    # 4. claims status.md does not carry, and the other voice's vocabulary
    brand_rules = rules()
    for where, t in texts.items():
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", t):
            if brand_rules["cleared_re"].search(sentence):
                continue
            for pat, why in brand_rules["status_flags"]:
                if re.search(pat, sentence, re.I):
                    f.append(finding("status", "learn", where, sentence.strip(),
                                     why + " If the copy is approved, record the wording as cleared in a decision; never edit it."))
            for pat, why in brand_rules["voice_flags"]:
                if re.search(pat, sentence, re.I) and not sentence.strip().startswith("#" + BRAND_NAME):
                    f.append(finding("voice", "learn", where, sentence.strip(), why))
    # 5. is the partner cleared to name at all
    ps = partner_status(partner)
    if not ps["private_file_present"]:
        f.append(finding("clearance", "block", "", "handles.private.md missing",
                         "Without the private handles file the stealth check cannot be trusted. Stop."))
    elif not ps["cleared"]:
        f.append(finding("clearance", "block", "", " / ".join(ps["handles_private_md"] or ["not listed"]),
                         f"{partner} is not on the cleared list. A dated decision file under decisions/ must clear it first."))

    plan = dict(folder=str(folder), partner=partner, title=title, slug=slug, theme=a.theme,
                date=a.date, x_option=a.x_option.upper(),
                blog_words=len(body.split()), x_chars=len(x), linkedin_chars=len(li),
                blog=body, linkedin=li, x=x, banners=banner_plan(images), partner_status=ps,
                gate_verdict=gate.get("verdict"), findings=f,
                blocking=sum(1 for x_ in f if x_["severity"] in ("block", "fill")))
    (out / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False))

    md = [f"# {title}", "", f"- partner: **{partner}** · cleared to name: **{'yes' if ps['cleared'] else 'no'}**",
          f"- slug: `{slug}` · theme: {a.theme or '(not set)'} · blog {plan['blog_words']} words · X {plan['x_chars']} chars · LinkedIn {plan['linkedin_chars']} chars",
          f"- blocking findings: **{plan['blocking']}** of {len(f)}", "", "| severity | check | where | line | why |", "|---|---|---|---|---|"]
    # block: stops the push · fill: placeholder to complete · learn: our rules
    # disagree with approved copy · posting: how it must go out · note: tell the owner
    order = {"block": 0, "fill": 1, "learn": 2, "posting": 3, "note": 4}
    for x_ in sorted(f, key=lambda r: order[r["severity"]]):
        md.append("| {severity} | {check} | {where} | {line} | {why} |".format(**{k: str(v).replace("|", "/").replace("\n", " ") for k, v in x_.items()}))
    md += ["", "## banners", ""] + [f"- {b['file']}: {b.get('width', '?')}x{b.get('height', '?')} ({b.get('ratio', '?')}:1) · blog cover {b['blog_cover']} · LinkedIn {b['linkedin_image']}" for b in plan["banners"]]
    (out / "plan.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    return 1 if plan["blocking"] else 0


if __name__ == "__main__":
    sys.exit(main())
