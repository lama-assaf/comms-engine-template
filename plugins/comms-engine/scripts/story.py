#!/usr/bin/env python3
"""
story.py - the story of each run: a short deck of where we stand, what we
found, the big questions, what is worth exploring and what is worth adding,
with the answers a person gives kept and read back next time.

Why: the dashboard shows everything, which is a lot. The story says what
matters, in a few big slides a person reads on a phone. Code and model split
the work as everywhere else in the engine: this script gathers the facts and
checks the deck; the `storyteller` agent (the `story-deck` skill) only writes
the words; the control page shows it as its landing page and records answers.

  facts     gather this run's facts into state/story/facts.json: posts and
            their checks, what the listener heard, accounts, replies, claim
            ideas, results, jobs, and the questions still open or answered
            since the last story.
  check     a draft (state/story/draft.json) against the rules: 5 to 9 slides,
            a cover first, at most 3 questions, short headlines and points,
            every number one the facts contain (nothing invented), nothing on
            the private denylist and no unearned status word.
  publish   check, then make the draft the latest story (state/story/latest.json,
            and state/story/<run>.json), giving each question an id and adding it
            to state/story/questions.json unless the same question is still open.
  answer    record a person's answer to a question (what the control page calls).
  feedback  the closing frame's feedback on the whole story: a rating, what the
            next story should cover, and anything to always remember
            (state/story/feedback.json). The storyteller reads it, the session
            brief shows the remember notes to every Claude session, and the
            lessons workflow (PLAN-workflows step 4) takes them as proposed lessons.
  respond   record a person's response to any slide: one of its actions, a short
            note, or both (state/story/responses.json); the next story's facts
            carry the responses to the story before it.

  engine story facts
  engine story check
  engine story publish
  engine story show
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
import paths  # noqa: E402
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import control  # noqa: E402 - the writers' helpers: write_json, Refused, Conflict
import views  # noqa: E402
import gate_lint  # noqa: E402

STORY = os.path.join(paths.state(), "story")
KINDS = ("cover", "state", "discoveries", "question", "explore", "add", "next")
MIN_SLIDES, MAX_SLIDES, MAX_QUESTIONS = 5, 9, 3
LIMITS = {"title": 12, "subtitle": 24, "point": 22, "item": 28, "why": 30, "question": 25, "option": 8, "label": 8, "action": 5}
HANDLE_RE = re.compile(r"@[A-Za-z0-9_]{1,15}")
TAG_RE = re.compile(r"#[A-Za-z][A-Za-z0-9]{2,39}")
ADD_KINDS = ("theme", "account", "claim", "post", "other")


class StoryError(ValueError):
    pass


def p(name):
    return os.path.join(STORY, name)


def words(text):
    return len(str(text or "").split())


def numbers(text):
    return set(re.findall(r"\d+(?:[.,]\d+)?", str(text or "")))


# ------------------------------------------------------------------ facts


def facts(today=None):
    """Everything this run's story may say, gathered from the engine's own files."""
    today = today or dt.date.today().isoformat()
    soon = (dt.date.fromisoformat(today) + dt.timedelta(days=13)).isoformat()
    posts = views.posts(today)
    up = posts["upcoming"]
    listening = views.listening()
    accounts = views.accounts()
    suggested = views.suggested()
    replies = views.replies()
    claims = views.claims()
    learning = views.learning()
    engine = views.engine()
    themes = views.themes(today)
    q = load_questions()
    last = views.load_json(p("latest.json"), {})
    since = str(last.get("published_at") or "")
    return {
        "run_id": dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "date": today, "stream": views.stream_name(),
        "posts": {
            "next_14_days": sum(1 for x in up if (x["date"] or "9999") <= soon),
            "planned": len(up),
            "waiting_for_ok": sum(1 for x in up if not x["decision"] and x["alpha_status"] == "proposed" and x["gate"] != "block"),
            "stopped_by_check": sum(1 for x in up if x["gate"] == "block"),
            "videos_ready": sum(1 for x in up if x["motion"]["poster"]),
            "next": [{"date": x["date"], "theme": x["theme"], "title": x["title"], "check": x["gate"]} for x in up[:5]],
            "past_due": len(posts["past"]),
        },
        "listening": {
            "window": listening.get("window"), "summary": listening.get("summary", ""),
            "findings": [{"id": f["id"], "theme": f["theme"], "finding": f["finding"], "kind": f["shape"],
                          "could_be": f.get("content"), "fresh_until": f.get("freshness_deadline")} for f in listening["findings"]],
            "loudest": [{"theme": w.get("theme"), "relevance": w.get("relevance"), "count": w.get("count")} for w in listening["warmest"][:3]],
            "for_a_person": listening["held_for_person"],
        },
        "themes": [{"tag": t["tag"], "allowed": t["licence"], "planned": len(t["upcoming"]), "heard": len(t["findings"])}
                   for t in themes["rows"]],
        "accounts": {"watched": len(accounts["watched"]), "suggestions": len(suggested),
                     "top_suggestions": [{"handle": s["handle"], "seen": s["hits"], "themes": s["themes"]} for s in suggested[:5]]},
        "replies_waiting": len(replies["proposals"]),
        "claims": {"ideas": len(claims["watch"]), "approved": claims["register"],
                   "recent": [{"claim": c.get("claim"), "theme": c.get("theme"), "source": c.get("source")}
                              for c in sorted(claims["watch"], key=lambda c: str(c.get("date") or ""), reverse=True)[:3]]},
        "results": {"guesses": len(learning["predictions"]),
                    "checked": sum(1 for x in learning["predictions"] if x.get("actual") is not None)},
        "system": {"jobs_off": [j.get("job") for j in engine["jobs"] if j.get("loaded") is False],
                   "recent_runs": [{"step": r.get("step"), "at": r.get("at")} for r in engine["runs"][:5]]},
        "questions": {
            "open": [x for x in q["questions"] if x.get("status") == "open"],
            "answered_since_last_story": [x for x in q["questions"] if x.get("status") == "answered"
                                          and str(x.get("answered_at") or "") >= since],
        },
        "responses_to_last_story": [r for r in load_responses()["responses"] if r.get("run_id") == last.get("run_id")] if last else [],
        "feedback_on_last_story": next((x for x in load_feedback()["feedback"] if x.get("run_id") == last.get("run_id")), None) if last else None,
        "always_remember": remember_notes(),
        "previous_story": {"run_id": last.get("run_id"), "title": (last.get("slides") or [{}])[0].get("title")} if last else None,
    }


def write_facts(today=None):
    os.makedirs(STORY, exist_ok=True)
    f = facts(today)
    control.write_json(p("facts.json"), f)
    return f


# ------------------------------------------------------------------ the check


def _texts(slide):
    """Every piece of text a slide shows, with the limit it is held to."""
    out = []
    for key in ("title", "subtitle", "question", "why"):
        if slide.get(key):
            out.append((key, slide[key], LIMITS["title" if key == "title" else key]))
    for point in slide.get("points") or []:
        out.append(("point", point, LIMITS["point"]))
    for item in slide.get("items") or []:
        item = item if isinstance(item, dict) else {"text": item}
        out.append(("item", item.get("text"), LIMITS["item"]))
        if item.get("why"):
            out.append(("why", item["why"], LIMITS["why"]))
    for option in slide.get("options") or []:
        out.append(("option", option, LIMITS["option"]))
    for action in slide.get("actions") or []:
        out.append(("action", action, LIMITS["action"]))
    figure = slide.get("figure") or {}
    if figure:
        out.append(("figure", str(figure.get("value", "")), 3))
        out.append(("label", figure.get("label", ""), LIMITS["label"]))
    return out


def check(draft, f):
    """What stops this deck from being published, one line each; empty means it may."""
    problems = []
    slides = draft.get("slides") if isinstance(draft, dict) else None
    if not isinstance(slides, list) or not MIN_SLIDES <= len(slides) <= MAX_SLIDES:
        return [f"a story has {MIN_SLIDES} to {MAX_SLIDES} slides in `slides`"]
    if (slides[0] or {}).get("kind") != "cover":
        problems.append("slide 1 is the cover")
    if not any((s or {}).get("kind") == "state" for s in slides):
        problems.append("a story has a `state` slide: where we stand")
    if sum(1 for s in slides if (s or {}).get("kind") == "question") > MAX_QUESTIONS:
        problems.append(f"at most {MAX_QUESTIONS} question slides: a few big questions, not a survey")
    allowed = numbers(json.dumps(f, ensure_ascii=False)) | {str(n) for n in range(0, 15)}
    every = []
    for n, s in enumerate(slides, 1):
        s = s or {}
        if s.get("kind") not in KINDS:
            problems.append(f"slide {n}: kind is one of {', '.join(KINDS)}")
            continue
        if s["kind"] != "question" and not s.get("title"):
            problems.append(f"slide {n}: no title")
        if s["kind"] == "question" and not s.get("question"):
            problems.append(f"slide {n}: a question slide asks a question")
        for key in ("points", "items", "options"):
            if len(s.get(key) or []) > (4 if key == "options" else 3):
                problems.append(f"slide {n}: at most {4 if key == 'options' else 3} {key}: one idea per slide, said big")
        if len(s.get("actions") or []) > 3:
            problems.append(f"slide {n}: at most 3 actions: the person picks one")
        if s["kind"] == "add":
            known = {str(h.get("handle", "")).lower() for h in (f.get("accounts") or {}).get("top_suggestions") or []}
            for item in s.get("items") or []:
                if isinstance(item, dict) and item.get("kind") not in ADD_KINDS:
                    problems.append(f"slide {n}: an `add` item's kind is one of {', '.join(ADD_KINDS)}")
                if isinstance(item, dict) and item.get("handle"):
                    if not HANDLE_RE.fullmatch(str(item["handle"])) or str(item["handle"]).lower() not in known:
                        problems.append(f"slide {n}: {item['handle']} is not one of this run's suggested accounts")
                if isinstance(item, dict) and item.get("tag") and not TAG_RE.fullmatch(str(item["tag"])):
                    problems.append(f"slide {n}: {item['tag']} is not a hashtag")
        for key, text, most in _texts(s):
            if words(text) > most:
                problems.append(f"slide {n}: the {key} has {words(text)} words; at most {most}")
            for num in numbers(text) - allowed:
                problems.append(f"slide {n}: the number {num} is not in this run's facts; never invent a number")
            every.append(str(text))
    pseudo = {"title": "", "post": "\n".join(every), "teaser_x": "", "teaser_linkedin": "", "stream": f.get("stream")}
    slug = gate_lint.resolve_slug(pseudo)
    for name, fn in (("the denylist check", gate_lint.check_stealth), ("the status-word check", gate_lint.check_status_words)):
        try:
            result = fn(pseudo, slug)
        except Exception as e:  # noqa: BLE001 - a check that cannot run stops the story
            problems.append(f"{name} could not run ({e})")
            continue
        if result["result"] == "block":
            problems.append(f"{result['check']}: {result['line']} {result['fix']}".strip())
    return problems


# ------------------------------------------------------------------ questions


def load_questions(path=None):
    data = views.load_json(path or p("questions.json"), {})
    return {"questions": list(data.get("questions") or [])}


def _save_questions(data, path=None):
    os.makedirs(STORY, exist_ok=True)
    return control.write_json(path or p("questions.json"), {
        "_about": "The big questions the story asked, and the answers a person gave on the control page. "
                  "Written by scripts/story.py; the next story reads the answers.",
        "questions": data["questions"]})


def _norm(text):
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def publish(draft, f, now=None, qpath=None):
    problems = check(draft, f)
    if problems:
        raise StoryError("; ".join(problems))
    now = now or dt.datetime.now(dt.timezone.utc)
    q = load_questions(qpath)
    open_by_text = {_norm(x["question"]): x for x in q["questions"] if x.get("status") == "open"}
    ids = {x["id"] for x in q["questions"]}
    n = 0
    for s in draft["slides"]:
        if s.get("kind") != "question":
            continue
        same = open_by_text.get(_norm(s["question"]))
        if same:
            s["id"] = same["id"]
            continue
        while True:
            n += 1
            qid = f"Q-{f['date']}-{n}"
            if qid not in ids:
                break
        ids.add(qid)
        s["id"] = qid
        q["questions"].append({"id": qid, "question": s["question"], "why": s.get("why", ""),
                               "options": s.get("options") or [], "asked_in": f["run_id"],
                               "asked_at": now.isoformat(timespec="seconds"), "status": "open",
                               "answer": "", "answered_at": ""})
    _save_questions(q, qpath)
    story = dict(draft, run_id=f["run_id"], date=f["date"], stream=f["stream"],
                 published_at=now.isoformat(timespec="seconds"))
    os.makedirs(STORY, exist_ok=True)
    control.write_json(p(f"{f['run_id']}.json"), story)
    control.write_json(p("latest.json"), story)
    return story


def answer(qid, text, base, path=None, now=None):
    path = path or p("questions.json")
    if views.digest(path) != (base or ""):
        raise control.Conflict("the questions changed since the page read them; reload and try again")
    text = " ".join(str(text or "").split())
    if not text:
        raise control.Refused("an answer needs a few words")
    if len(text) > 500:
        raise control.Refused("an answer is at most 500 characters")
    q = load_questions(path)
    for x in q["questions"]:
        if x["id"] == qid:
            x.update(status="answered", answer=text,
                     answered_at=(now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds"))
            return _save_questions(q, path)
    raise control.Refused(f"no question {qid}")


# ------------------------------------------------------------------ responses


def load_responses(path=None):
    data = views.load_json(path or p("responses.json"), {})
    return {"responses": list(data.get("responses") or [])}


def respond(run_id, slide, action, text, base, item=None, path=None, now=None):
    """Keep a person's response to one slide of a story: an action, a note, or both.
    A second response to the same slide (and item) replaces the first."""
    path = path or p("responses.json")
    if views.digest(path) != (base or ""):
        raise control.Conflict("the responses changed since the page read them; reload and try again")
    latest = views.load_json(p("latest.json"), {})
    slides = latest.get("slides") or []
    if not run_id or run_id != latest.get("run_id"):
        raise control.Refused("that story is not the latest one any more; reload")
    try:
        slide = int(slide)
        target = slides[slide]
    except (TypeError, ValueError, IndexError):
        raise control.Refused("no such slide")
    action = " ".join(str(action or "").split())[:60]
    text = " ".join(str(text or "").split())
    if len(text) > 500:
        raise control.Refused("a note is at most 500 characters")
    if not action and not text:
        raise control.Refused("pick an action or write a few words")
    if item is not None:
        try:
            item = int(item)
            (target.get("items") or [])[item]
        except (TypeError, ValueError, IndexError):
            raise control.Refused("no such item on that slide")
    data = load_responses(path)
    data["responses"] = [r for r in data["responses"]
                         if not (r.get("run_id") == run_id and r.get("slide") == slide and r.get("item") == item)]
    data["responses"].append({"run_id": run_id, "slide": slide, "item": item, "kind": target.get("kind"),
                              "about": target.get("title") or target.get("question") or "",
                              "action": action, "text": text,
                              "at": (now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds")})
    os.makedirs(STORY, exist_ok=True)
    return control.write_json(path, {
        "_about": "What a person said about each slide of a story on the control page: an action, a note, or both. "
                  "Written by scripts/story.py; the next story reads the responses to the one before it.",
        "responses": data["responses"]})


# ------------------------------------------------------------------ the closing frame

RATINGS = ("useful", "too long", "missed something", "not useful")


def load_feedback(path=None):
    data = views.load_json(path or p("feedback.json"), {})
    return {"feedback": list(data.get("feedback") or [])}


def remember_notes(limit=10, path=None):
    """The notes a person asked the engine to always remember, newest first."""
    notes = [{"note": x["remember"], "at": x.get("at"), "run_id": x.get("run_id")}
             for x in load_feedback(path)["feedback"] if x.get("remember")]
    return sorted(notes, key=lambda n: str(n.get("at") or ""), reverse=True)[:limit]


def give_feedback(run_id, rating, next_cover, remember, base, path=None, now=None):
    """The closing frame: how the story was, what the next should cover, what to remember."""
    path = path or p("feedback.json")
    if views.digest(path) != (base or ""):
        raise control.Conflict("the feedback changed since the page read it; reload and try again")
    if not run_id or run_id != views.load_json(p("latest.json"), {}).get("run_id"):
        raise control.Refused("that story is not the latest one any more; reload")
    rating = str(rating or "").strip().lower()
    if rating and rating not in RATINGS:
        raise control.Refused(f"a rating is one of: {', '.join(RATINGS)}")
    next_cover, remember = (" ".join(str(x or "").split()) for x in (next_cover, remember))
    if len(next_cover) > 500 or len(remember) > 500:
        raise control.Refused("each answer is at most 500 characters")
    if not (rating or next_cover or remember):
        raise control.Refused("pick a rating or write a few words")
    data = load_feedback(path)
    data["feedback"] = [x for x in data["feedback"] if x.get("run_id") != run_id]
    data["feedback"].append({"run_id": run_id, "rating": rating, "next": next_cover, "remember": remember,
                             "at": (now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds")})
    os.makedirs(STORY, exist_ok=True)
    return control.write_json(path, {
        "_about": "A person's feedback on each story, from its closing frame: a rating, what the next story should "
                  "cover, and notes to always remember. The storyteller reads it; the session brief shows the notes "
                  "to every Claude session; the lessons workflow takes them as proposed lessons.",
        "feedback": data["feedback"]})


# ------------------------------------------------------------------ the command line


def main(argv=None):
    ap = argparse.ArgumentParser(description="The story of each run.")
    ap.add_argument("command", choices=("facts", "check", "publish", "show"))
    ap.add_argument("--draft", help="the draft to check or publish (default state/story/draft.json)")
    args = ap.parse_args(argv)
    if args.command == "facts":
        f = write_facts()
        print(f"story: facts for {f['run_id']} in {views.rel(p('facts.json'))}: "
              f"{f['posts']['planned']} posts planned, {len(f['listening']['findings'])} findings, "
              f"{len(f['questions']['open'])} questions open, {len(f['questions']['answered_since_last_story'])} answered since the last story")
        return 0
    if args.command == "show":
        s = views.load_json(p("latest.json"), {})
        if not s:
            print("story: none yet")
            return 0
        print(f"story {s.get('run_id')} ({s.get('date')}):")
        for n, slide in enumerate(s.get("slides") or [], 1):
            print(f"  {n}. {slide.get('kind'):<11} {slide.get('title') or slide.get('question')}")
        return 0
    f = views.load_json(p("facts.json"), None)
    if not f:
        print("story: no facts yet; run `story.py facts` first", file=sys.stderr)
        return 1
    draft = views.load_json(args.draft or p("draft.json"), None)
    if not isinstance(draft, dict):
        print(f"story: no draft at {views.rel(args.draft or p('draft.json'))}", file=sys.stderr)
        return 1
    if args.command == "check":
        problems = check(draft, f)
        if problems:
            print(f"story: {len(problems)} to fix")
            for x in problems:
                print(f"  - {x}")
            return 1
        print(f"story: ok, {len(draft['slides'])} slides")
        return 0
    try:
        story = publish(draft, f)
    except StoryError as e:
        print(f"story: not published: {e}", file=sys.stderr)
        return 1
    asked = [s["id"] for s in story["slides"] if s.get("kind") == "question"]
    print(f"story: published {story['run_id']}, {len(story['slides'])} slides, questions {', '.join(asked) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
