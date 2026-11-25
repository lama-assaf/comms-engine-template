#!/usr/bin/env python3
"""
`scripts/motion.py`: a motion card says only what the gated post says, and is
drawn the same way every time.

1. **The storyboard check.** A line lifted word for word from the post passes;
   a paraphrase, an added claim, a line stitched from two sentences, a tag that
   is not the theme, a link that is not the CTA, a denylist term, a blocked or
   ungated post, too many beats and too long a clip each stop the render.
2. **The timeline.** Beats run one after another; a line enters in 300 ms and
   leaves in 200 ms; the last beat never leaves; enter is ease-out, exit is
   ease-in.
3. **The render.** At a small scale and frame rate, the poster and the GIF are
   written at the format's proportions; the MP4 too when ffmpeg is on the
   machine. Skipped without Pillow.

The posts are inline and the gate's two text checks (denylist, status words)
are stubbed with an invented denylist, so the file runs the same in any
checkout and reads no live memory. Where the fixture memory is present (the
template), one more test runs the gate's real denylist check.

  python3 -m unittest discover plugins/comms-engine/tests
"""
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import gate_lint  # noqa: E402
import genome  # noqa: E402
import motion  # noqa: E402

try:
    import fixture_memory  # noqa: E402 - the template's fixture memory, when present
except ImportError:
    fixture_memory = None

ITEM = {
    "id": "Q-2026-10-02-secondtheme-1",
    "theme": "#SecondTheme",
    "title": "A closed set answers who may transact by exclusion. Identity answers it by proof.",
    "post": "A settlement set between vetted parties is a closed set. Membership is the product; "
            "the ledger is the plumbing.\n\nWhat we do not claim: the set named here has no members "
            "beyond those on its published list.",
    "teaser_x": "A closed set answers who may transact by exclusion. Identity answers it by proof.\n\n"
                "Membership is the product.\n\n#SecondTheme\nhttps://www.example.com/insights/a-closed-set-is-the-product",
    "teaser_linkedin": "A closed set answers who may transact by exclusion. Identity answers it by proof.\n\n"
                       "Membership is the product; the ledger is the plumbing.\n\n"
                       "https://www.example.com/insights/a-closed-set-is-the-product",
    "cta": "https://www.example.com/insights/a-closed-set-is-the-product",
    "stream": "Acme",
    "gate": {"verdict": "pass-with-edits"},
}
BLOCKED = dict(ITEM, id="Q-2026-10-03-thirdtheme-1", gate={"verdict": "block"})
DENYLIST = ("Umbra Capital",)


def fake_stealth(item, slug=None):
    for term in DENYLIST:
        if term.lower() in item["post"].lower():
            return gate_lint.check("stealth", "block", term, "on the closed denylist")
    return gate_lint.check("stealth")


def fake_status_words(item, slug=None):
    return gate_lint.check("status words")


GOOD = {"format": "square", "beats": [
    {"role": "line", "text": "A closed set answers who may transact by exclusion.", "hold_ms": 2200},
    {"role": "line", "text": "Identity answers it by proof.", "hold_ms": 1800},
    {"role": "tag", "text": ITEM["theme"], "hold_ms": 1000},
    {"role": "cta", "text": "example.com", "hold_ms": 1600},
]}


def board(**changes):
    b = copy.deepcopy(GOOD)
    for index, beat in changes.get("beats", {}).items():
        if beat is None:
            del b["beats"][index]
        else:
            b["beats"][index] = beat
    b.update({k: v for k, v in changes.items() if k != "beats"})
    return b


class StoryboardCheck(unittest.TestCase):
    def setUp(self):
        patches = [mock.patch.object(gate_lint, "check_stealth", fake_stealth),
                   mock.patch.object(gate_lint, "check_status_words", fake_status_words),
                   mock.patch.object(gate_lint, "resolve_slug", lambda item: None)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def assertRefused(self, item, b, fragment):
        problems = motion.check_board(item, b)
        self.assertTrue(any(fragment in p for p in problems), f"expected {fragment!r} in {problems}")

    def test_lifted_lines_pass(self):
        self.assertEqual(motion.check_board(ITEM, GOOD), [])

    def test_a_contiguous_run_of_one_sentence_passes(self):
        b = board(beats={1: {"role": "line", "text": "Membership is the product", "hold_ms": 1600}})
        self.assertEqual(motion.check_board(ITEM, b), [])

    def test_punctuation_and_case_do_not_matter(self):
        b = board(beats={0: {"role": "line", "text": "a closed set answers who may transact by exclusion",
                             "hold_ms": 2200}})
        self.assertEqual(motion.check_board(ITEM, b), [])

    def test_a_paraphrase_is_refused(self):
        b = board(beats={1: {"role": "line", "text": "Identity proves it instead.", "hold_ms": 1800}})
        self.assertRefused(ITEM, b, "not word for word")

    def test_an_added_claim_is_refused(self):
        b = board(beats={1: {"role": "line", "text": "Acme settles for every bank in Europe today.",
                             "hold_ms": 1800}})
        self.assertRefused(ITEM, b, "not word for word")

    def test_two_sentences_stitched_together_are_refused(self):
        b = board(beats={1: {"role": "line", "text": "by exclusion. Identity answers it", "hold_ms": 1800}})
        self.assertRefused(ITEM, b, "not word for word")

    def test_the_tag_is_the_theme(self):
        b = board(beats={2: {"role": "tag", "text": "#OtherTheme", "hold_ms": 1000}})
        self.assertRefused(ITEM, b, "the tag is the post's theme")

    def test_the_link_is_the_ctas_main_domain_and_comes_last(self):
        b = board(beats={3: {"role": "cta", "text": "elsewhere.example", "hold_ms": 1600}})
        self.assertRefused(ITEM, b, "the main domain of the post's CTA")
        moved = copy.deepcopy(GOOD)
        moved["beats"].insert(1, moved["beats"].pop())
        self.assertRefused(ITEM, moved, "the link, when there is one, is the last beat")

    def test_the_full_url_is_never_on_screen(self):
        """Owner, 2026-11-07: a motion piece shows only the main domain, never the full URL."""
        for full in (ITEM["cta"], ITEM["cta"].replace("https://www.", "")):
            b = board(beats={3: {"role": "cta", "text": full, "hold_ms": 1600}})
            self.assertRefused(ITEM, b, "never the full URL")
        self.assertEqual(motion.domain(ITEM["cta"]), "example.com")
        self.assertEqual(motion.domain("www.Example.com/a?b"), "example.com")

    def test_with_scheme_or_www_the_domain_still_matches(self):
        b = board(beats={3: {"role": "cta", "text": "https://www.example.com", "hold_ms": 1600}})
        self.assertEqual(motion.check_board(ITEM, b), [])

    def test_the_hook_opens_the_clip(self):
        b = copy.deepcopy(GOOD)
        b["beats"].insert(0, b["beats"].pop(2))
        self.assertRefused(ITEM, b, "beat 1 is a line from the post")

    def test_a_denylist_term_is_refused_even_if_the_post_carried_it(self):
        item = copy.deepcopy(ITEM)
        item["post"] += f"\n\nWe met {DENYLIST[0]} last week."
        b = board(beats={1: {"role": "line", "text": f"We met {DENYLIST[0]} last week.", "hold_ms": 1800}})
        self.assertRefused(item, b, "stealth")

    def test_a_check_that_cannot_run_stops_the_clip(self):
        with mock.patch.object(gate_lint, "check_stealth", side_effect=RuntimeError("no denylist")):
            self.assertRefused(ITEM, GOOD, "could not run")

    def test_a_blocked_post_gets_no_motion(self):
        self.assertRefused(BLOCKED, GOOD, "the gate blocked this post")

    def test_an_ungated_post_gets_no_motion(self):
        item = copy.deepcopy(ITEM)
        item.pop("gate")
        self.assertRefused(item, GOOD, "the gate has not read this post")

    def test_beat_count_hold_and_length_are_bounded(self):
        self.assertRefused(ITEM, {"beats": GOOD["beats"][:1]}, "2 to 6 beats")
        b = board(beats={1: {"role": "line", "text": "Identity answers it by proof.", "hold_ms": 9000}})
        self.assertRefused(ITEM, b, "hold_ms is a whole number")
        long = {"beats": [{"role": "line", "text": "Identity answers it by proof.", "hold_ms": 4000}] * 4}
        self.assertRefused(ITEM, long, "at most 15 s")

    def test_an_unknown_format_is_refused(self):
        self.assertRefused(ITEM, board(format="portrait"), "format is one of")


if fixture_memory is not None:
    class RealDenylist(fixture_memory.FixtureMemoryCase):
        """The gate's own stealth check, on the fixture memory's denylist."""

        def test_a_fixture_denylist_term_is_refused(self):
            import memory
            term = sorted(memory.denylist(None))[0]
            item = copy.deepcopy(ITEM)
            item["post"] += f"\n\nWe met {term} last week."
            b = board(beats={1: {"role": "line", "text": f"We met {term} last week.", "hold_ms": 1800}})
            self.assertTrue(any("stealth" in p for p in motion.check_board(item, b)))

        def test_the_lifted_board_passes_the_real_checks(self):
            self.assertEqual(motion.check_board(ITEM, GOOD), [])


class MotionDir(unittest.TestCase):
    """A temp Content/Motion, the settings stubbed, posts made inline."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.settings = {"cycle.motion": True, "cycle.motion_per_cycle": 3}
        real_cfg = motion.config.cfg
        patches = [mock.patch.object(motion, "MOTION_DIR", self.dir),
                   mock.patch.object(motion.config, "cfg",
                                     lambda path, default=None, **kw: self.settings.get(path, real_cfg(path, default, **kw))),
                   mock.patch.object(gate_lint, "check_stealth", fake_stealth),
                   mock.patch.object(gate_lint, "check_status_words", fake_status_words),
                   mock.patch.object(gate_lint, "resolve_slug", lambda item: None)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def post(self, item_id, **fields):
        # A far-future slot, so no test here starts failing when a date passes.
        item = dict(copy.deepcopy(ITEM), id=item_id, alpha_status="proposed",
                    slot={"date": "2999-01-01", "platform": "Blog"})
        item.update(fields)
        return item_id, item

    def write_board(self, item_id, b):
        path = motion.board_path(item_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(b, f)


class CycleOwes(MotionDir):
    """`motion.py pending`: what step 7a of the cycle hands the motion-designer."""

    def test_only_blog_posts_the_gate_let_through_and_still_in_play(self):
        items = dict([self.post("Q-ok"),
                      self.post("Q-blocked", gate={"verdict": "block"}),
                      self.post("Q-ungated", gate={}),
                      self.post("Q-rejected", alpha_status="rejected"),
                      self.post("Q-published", status="Published"),
                      self.post("Q-teaser", slot={"date": "2999-01-01", "platform": "X"})])
        self.assertEqual(motion.pending(items), [("Q-ok", "storyboard", "no card yet")])

    def test_a_post_whose_slot_has_passed_is_skipped(self):
        items = dict([self.post("Q-past", alpha_status="approved", slot={"date": "2026-09-09", "platform": "Blog"}),
                      self.post("Q-today", slot={"date": "2026-11-06", "platform": "Blog"}),
                      self.post("Q-undated", slot={"platform": "Blog"})])
        self.assertEqual([i for i, _, _ in motion.pending(items, today="2026-11-06")], ["Q-today", "Q-undated"])

    def test_approved_first_then_the_soonest_slot_and_at_most_the_cap(self):
        items = dict([self.post("Q-late", slot={"date": "2026-12-01", "platform": "Blog"}),
                      self.post("Q-soon", slot={"date": "2026-11-10", "platform": "Blog"}),
                      self.post("Q-approved", alpha_status="approved", slot={"date": "2026-12-20", "platform": "Blog"}),
                      self.post("Q-mid", slot={"date": "2026-11-15", "platform": "Blog"})])
        self.assertEqual([i for i, _, _ in motion.pending(items, today="2026-11-06")],
                         ["Q-approved", "Q-soon", "Q-mid"])
        self.assertEqual(len(motion.pending(items, limit=1, today="2026-11-06")), 1)

    def test_a_card_the_post_moved_past_is_owed_again(self):
        item_id, item = self.post("Q-edited")
        self.write_board(item_id, GOOD)
        item["title"] = "A different title."
        item["teaser_x"] = item["teaser_linkedin"] = "Something else entirely."
        (row,) = motion.pending({item_id: item})
        self.assertEqual(row[1], "storyboard")
        self.assertIn("no longer matches the post", row[2])

    def test_a_passing_card_without_files_needs_only_a_render_and_is_never_capped(self):
        item_id, item = self.post("Q-rendered-elsewhere")
        self.write_board(item_id, GOOD)
        self.assertEqual(motion.pending({item_id: item}, limit=0),
                         [(item_id, "render", "the storyboard passes; no files on this machine")])
        for f in motion.render_files(item_id, "square"):
            open(f, "w").close()
        self.assertEqual(motion.pending({item_id: item}), [])

    def test_motion_off_owes_nothing(self):
        self.settings["cycle.motion"] = False
        self.assertEqual(motion.pending(dict([self.post("Q-ok")])), [])


class Card(MotionDir):
    """`motion.card`: what every page shows of a post's card, and when it is ready to attach."""

    def test_no_storyboard_is_no_card(self):
        c = motion.card("Q-none", dict(ITEM, id="Q-none"))
        self.assertFalse(c["storyboard"])
        self.assertEqual((c["video"], c["poster"], c["beats"], c["current"]), (None, None, [], None))

    def test_a_rendered_card_names_its_files_beats_and_length(self):
        item_id, item = self.post("Q-card")
        self.write_board(item_id, GOOD)
        for f in motion.render_files(item_id, "square") + [motion._stem(item_id, "square") + ".mp4"]:
            open(f, "w").close()
        c = motion.card(item_id, item)
        self.assertTrue(c["storyboard"] and c["current"])
        self.assertEqual(c["format"], "square")
        self.assertEqual(c["beats"], [b["text"] for b in GOOD["beats"]], "the beats in order are the alt text")
        self.assertEqual(c["seconds"], round(motion.timeline(GOOD)[1] / 1000, 1))
        self.assertTrue(c["video"].endswith(f"{item_id}-square.mp4") and os.path.isabs(c["video"]))
        self.assertTrue(c["poster"].endswith("-square-poster.png") and c["gif"].endswith("-square.gif"))

    def test_files_not_rendered_here_are_none(self):
        item_id, item = self.post("Q-elsewhere")
        self.write_board(item_id, GOOD)
        c = motion.card(item_id, item)
        self.assertTrue(c["storyboard"] and c["current"])
        self.assertEqual((c["poster"], c["gif"], c["video"]), (None, None, None))

    def test_a_card_the_post_moved_past_is_not_current(self):
        item_id, item = self.post("Q-moved")
        self.write_board(item_id, GOOD)
        item["title"] = "A different title."
        item["teaser_x"] = item["teaser_linkedin"] = "Something else entirely."
        self.assertIs(motion.card(item_id, item)["current"], False)
        self.assertIsNone(motion.card(item_id)["current"], "without the post, the card is not confirmed")

    def test_a_storyboard_that_is_not_json_is_a_card_that_is_not_ready(self):
        item_id, item = self.post("Q-broken")
        path = motion.board_path(item_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("{not json")
        c = motion.card(item_id, item)
        self.assertNotEqual(c["current"], True)
        self.assertIsNone(c["video"])


FILM = """<!doctype html><html><head><title>not shown</title><style>.x{}</style></head><body>
<div id="root" data-composition-id="main" data-width="1080" data-height="1080" data-duration="15">
  <h1 class="head" data-says>A closed set answers who may transact by exclusion.</h1>
  <div class="block"><span data-says>Membership is the product</span></div>
  <svg><path d="M0 0" /></svg>
  <div id="end"><img src="assets/logo.svg" alt="Acme" /><div class="tagline">#SecondTheme</div>
  <div class="link">example.com</div></div>
  <audio id="vo1" src="assets/vo/vo1.wav" data-start="0" data-says-aloud="Membership is the product; the ledger is the plumbing."></audio>
</div><script>document.title = "words in a script are not on screen";</script></body></html>"""


class Film(MotionDir):
    """A film made with the Motion plugin from the brand kit: found by the post's id,
    held to the same words rule, and the post's video ahead of the text card."""

    def setUp(self):
        super().setUp()
        self.films = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.films, True)
        p = mock.patch.object(motion, "FILMS", self.films)
        p.start()
        self.addCleanup(p.stop)

    def make(self, item_id, page=FILM, versions=(1,)):
        os.makedirs(os.path.join(self.films, "projects", item_id))
        with open(os.path.join(self.films, "projects", item_id, "index.html"), "w", encoding="utf-8") as f:
            f.write(page)
        os.makedirs(os.path.join(self.films, "finals"), exist_ok=True)
        for v in versions:
            open(os.path.join(self.films, "finals", f"{item_id}-v{v}.mp4"), "w").close()

    def test_the_newest_final_is_the_film(self):
        self.make("Q-film", versions=(1, 3, 2))
        project, final = motion.film_paths("Q-film")
        self.assertTrue(project.endswith("Q-film/index.html"))
        self.assertTrue(final.endswith("Q-film-v3.mp4"))
        self.assertEqual(motion.film_paths("Q-none"), (None, None))
        open(os.path.join(self.films, "finals", "Q-film-night-v9.mp4"), "w").close()
        self.assertTrue(motion.film_paths("Q-film")[1].endswith("Q-film-v3.mp4"), "only the exact name")

    def test_what_the_page_says(self):
        self.make("Q-film")
        film = motion.read_film(motion.film_paths("Q-film")[0])
        self.assertEqual(film["lines"], ["A closed set answers who may transact by exclusion.", "Membership is the product"])
        self.assertEqual((film["tag"], film["link"]), ("#SecondTheme", "example.com"))
        self.assertEqual((film["loose"], film["format"], film["seconds"]), ([], "square", 15.0))
        self.assertEqual(film["voice"], ["Membership is the product; the ledger is the plumbing."])

    def test_its_words_are_held_to_the_post(self):
        item_id, item = self.post("Q-film")
        self.make(item_id)
        film = motion.read_film(motion.film_paths(item_id)[0])
        self.assertEqual(motion.check_film(item, film), [])
        for change, fragment in (({"lines": ["Membership is the whole product"]}, "not word for word"),
                                 ({"loose": ["Trusted by banks"]}, "outside a [data-says] element"),
                                 ({"tag": "#OtherTheme"}, "the post's theme"),
                                 ({"link": "elsewhere.example"}, "the main domain of the post's CTA"),
                                 ({"link": "example.com/insights/a-closed-set-is-the-product"}, "never the full URL"),
                                 ({"voice": ["The ledger is the product."]}, "the voice says what the gated post does not"),
                                 ({"unrecorded": ["assets/vo/vo2.wav"]}, "a voice line without its words")):
            problems = motion.check_film(item, dict(film, **change))
            self.assertTrue(any(fragment in p for p in problems), (change, problems))
        self.assertTrue(motion.check_film(dict(item, gate={"verdict": "block"}), film))
        self.assertTrue(any("Umbra Capital" in p for p in motion.check_film(item, dict(film, lines=["Umbra Capital"]))))

    def test_a_film_is_the_posts_video_ahead_of_the_card(self):
        item_id, item = self.post("Q-film")
        self.write_board(item_id, GOOD)
        self.make(item_id)
        c = motion.card(item_id, item)
        self.assertEqual(c["source"], "film")
        self.assertTrue(c["video"].endswith("Q-film-v1.mp4") and c["current"])
        self.assertEqual(c["beats"][-2:], ["#SecondTheme", "example.com"])
        self.assertEqual((c["format"], c["seconds"]), ("square", 15.0))
        item["title"] = item["post"] = item["teaser_x"] = item["teaser_linkedin"] = "Something else entirely."
        self.assertIs(motion.card(item_id, item)["current"], False, "a film the post moved past is not ready")

    def test_a_film_owes_nothing_until_the_post_moves_past_it(self):
        item_id, item = self.post("Q-film")
        self.make(item_id)
        self.assertEqual(motion.pending({item_id: item}), [])
        item["title"] = item["post"] = item["teaser_x"] = item["teaser_linkedin"] = "Something else entirely."
        (row,) = motion.pending({item_id: item}, limit=0)
        self.assertEqual(row[1], "film", "never capped, never handed to the motion-designer")
        self.assertIn("no longer matches", row[2])


class FilmScripts(Film):
    """Words a film's script or stylesheet could put on screen without its markup holding
    them. Until 2026-11-13 the film check read markup alone, so `el.textContent = "..."`,
    a `text:` option or a CSS `content:` string reached the screen with nothing read."""

    def unread(self, script="", style="", srcs=""):
        page = FILM.replace("<style>.x{}</style>", f"<style>{style}</style>{srcs}")
        page = page.replace('document.title = "words in a script are not on screen";', script)
        self.assertNotEqual(page, FILM)
        item_id = f"Q-{len(os.listdir(self.films))}-{abs(hash((script, style, srcs)))}"
        self.make(item_id, page)
        return motion.read_film(motion.film_paths(item_id)[0])["unread"]

    def test_text_a_script_writes_is_refused(self):
        for script, fragment in (
                ('el.textContent = "Trusted by banks";', "writes text into the page: 'Trusted by banks'"),
                ('el.innerHTML += "<b>Now live</b>";', "'Now live'"),
                ('el.textContent =\n    "Split over two lines";', "'Split over two lines'"),
                ("el.innerText = `Certified in ${year}`;", "'Certified in'"),
                ("el.textContent = label;", "a value the check cannot read"),
                ("el.innerHTML = lines.map((l) => `<p>${l}</p>`).join('');", "a value the check cannot read"),
                ('el.insertAdjacentHTML("beforeend", "<p>Certified</p>");', "'Certified'"),
                ("ctx.fillText(score, 10, 10);", "a value the check cannot read"),
                ('document.body.appendChild(document.createTextNode("Est. 1999"));', "'Est. 1999'"),
                ('K.typewrite(tl, el, 0, { text: "A new claim" });', "'A new claim'"),
                ("gsap.to(el, { duration: 1, text: line });", "a value the check cannot read"),
                ("gsap.registerPlugin(TextPlugin);", "the GSAP text plugins")):
            with self.subTest(script=script):
                problems = self.unread(script)
                self.assertTrue(any(fragment in p for p in problems), problems)
                self.assertTrue(all("[data-says]" in p for p in problems), "every refusal says where words belong")
        self.assertTrue(any("text plugins" in p for p in
                            self.unread(" ", srcs='<script src="https://cdn.example.com/gsap/TextPlugin.min.js"></script>')))

    def test_a_script_may_move_the_words_the_markup_holds(self):
        split = ('document.querySelectorAll(".head").forEach((h) => {\n'
                 '  h.innerHTML = h.textContent.trim().split(/\\s+/).map((w) => `<span class="w">${w}</span>`).join(" ");\n'
                 "});")
        for script in (split,
                       'el.textContent = "";',
                       'document.title = "words in a script are not on screen";'.replace("words", "titles"),
                       '// el.textContent = "in a comment";',
                       "/* el.innerHTML = 'in a block comment'; */",
                       """const note = "el.textContent = 'inside a string'";""",
                       'gsap.to("#h1", { opacity: 1, ease: "power3.out", transformOrigin: "left center" });',
                       'const t = ok ? text : other; tl.to(".doc .row", { scaleX: 1 }, 0.8);',
                       "K.typewrite(tl, el, 0, { text: el.textContent });"):
            with self.subTest(script=script):
                self.assertEqual(self.unread(script), [])

    def test_text_a_stylesheet_draws_is_refused(self):
        for style, fragment in (('.x::after { content: "Trusted"; }', 'content: "Trusted"'),
                                (".n::before{content:counter(n)}", "content: counter(n)"),
                                (".x::after { content: attr(data-label) }", "content: attr(data-label)")):
            with self.subTest(style=style):
                problems = self.unread(style=style)
                self.assertTrue(any(fragment in p for p in problems), problems)
        ok = ('.a{justify-content:center;align-content: start} .content:hover{color:red} #content :first-child{top:0} '
              '.b::before{content:""} .c::after{content: none !important} /* content: "in a comment" */')
        self.assertEqual(self.unread(style=ok), [])

    def test_a_form_fields_text_is_loose_text(self):
        page = FILM.replace('<svg><path d="M0 0" /></svg>',
                            '<input value="Trusted by banks"><textarea placeholder="Your name"></textarea><input type="hidden" value="x">')
        self.make("Q-form", page)
        self.assertEqual(motion.read_film(motion.film_paths("Q-form")[0])["loose"], ["Trusted by banks", "Your name"])

    def test_what_a_script_could_write_stops_the_film(self):
        item_id, item = self.post("Q-film")
        self.make(item_id, FILM.replace('document.title = "words in a script are not on screen";',
                                        'document.querySelector(".block").textContent = "Trusted by banks";'))
        problems = motion.check_film(item, motion.read_film(motion.film_paths(item_id)[0]))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("Trusted by banks", problems[0])
        self.assertIs(motion.card(item_id, item)["current"], False, "not ready to attach")


class Kit(unittest.TestCase):
    """The Motion plugin's brand kit, written from the brand genome where there is none:
    the genome's look, the voice left in memory, the repository's words rule in the two
    sections the plugin treats as binding; never over a kit, never from the placeholder."""

    GENOME = {"_source": "The brand guide, 2026-10-01.", "name": "Acme",
              "colors": {"primary": "#112233", "accent": "#445566", "ink": "#000001", "surface": "#fffffe",
                         "paper": "#f0f0f0", "muted": "#777777"},
              "type": {"family": "Inter", "display_weight": 700, "body_weight": 400},
              "logo": {"on_light": "<svg viewBox='0 0 1 1'></svg>", "on_dark": ""}}

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.root = os.path.join(self.dir, "brand", "motion-kit")

    def genome(self, **changes):
        path = os.path.join(self.dir, "brand-genome.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dict(self.GENOME, **changes), f)
        return path

    def files(self, path):
        return motion.kit_files(g=genome.load(file=path), slug="acme", today="2026-11-13")

    def test_the_kit_is_the_genome_and_the_words_rule(self):
        files = self.files(self.genome())
        kit = files["Motion.md"]
        front = kit.split("---")[1]
        for line in ('name: "Acme"', "kit: acme", 'bg: "#fffffe"', 'surface: "#f0f0f0"', 'text: "#000001"',
                     'text-muted: "#777777"', 'primary: "#112233"', 'accent: "#445566"', 'family: "Inter"',
                     "weight: 700", "primary: logo/logo.svg", "on-light: logo/logo.svg", "read by motion.py kit on 2026-11-13"):
            self.assertIn(line, front)
        self.assertNotIn("on-dark:", front, "a logo the genome does not have is not named")
        self.assertEqual(files["logo/logo.svg"], "<svg viewBox='0 0 1 1'></svg>\n")
        for must in ("## Facts and claims", "## On screen", "lifted word for word", "engine motion brief <id>",
                     "engine motion film <id>", "`data-says`", "`data-says-aloud`", "videos/projects/<id>/",
                     ".atelier/memory/voice.md", "text a script writes into the page"):
            self.assertIn(must, kit)

    def test_no_logo_is_no_logo(self):
        kit = self.files(self.genome(logo={"on_light": "", "on_dark": ""}))
        self.assertEqual(list(kit), ["Motion.md"])
        self.assertNotRegex(kit["Motion.md"], r"(?m)^logo:")
        self.assertIn("no mark is drawn or invented", kit["Motion.md"])

    def write(self, path):
        return motion.write_kit(root=self.root, genome_file=path, g=genome.load(file=path),
                                slug="acme", today="2026-11-13")

    def test_written_once_and_never_over_a_kit(self):
        path = self.genome()
        os.makedirs(os.path.join(self.root, "logo"))
        with open(os.path.join(self.root, "logo", "logo.svg"), "w", encoding="utf-8") as f:
            f.write("<svg>placed by hand</svg>")
        written = self.write(path)
        self.assertEqual([os.path.relpath(p, self.root) for p in written], ["Motion.md"], "a logo already there is kept")
        with open(os.path.join(self.root, "Motion.md"), "w", encoding="utf-8") as f:
            f.write("edited by hand")
        with self.assertRaisesRegex(motion.MotionError, "never overwritten"):
            self.write(path)
        with open(os.path.join(self.root, "Motion.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "edited by hand")

    def test_the_templates_placeholder_genome_writes_no_kit(self):
        for path in (self.genome(_source="Placeholder: replace with your brand's colours"),
                     os.path.join(self.dir, "no-such-genome.json")):
            self.assertTrue(motion.genome_placeholder(path))
            with self.assertRaisesRegex(motion.MotionError, "placeholder"):
                motion.write_kit(root=self.root, genome_file=path, slug="acme")
        self.assertFalse(os.path.exists(self.root))
        self.assertFalse(motion.genome_placeholder(self.genome()))


class Timeline(unittest.TestCase):
    def test_beats_run_in_turn_and_the_last_one_stays(self):
        spans, total = motion.timeline(GOOD)
        self.assertEqual(spans[0], (0, 300, 2500, 2700))
        self.assertEqual(spans[1][0], spans[0][3])
        last = spans[-1]
        self.assertEqual(last[2], last[3], "the last beat never leaves")
        self.assertEqual(total, last[3])
        self.assertEqual(motion.pose(total + 5000, last), (1.0, 0.0))

    def test_enter_is_ease_out_and_exit_is_ease_in(self):
        span = (0, 300, 1300, 1500)
        early, _ = motion.pose(60, span)
        self.assertGreater(early, 60 / 300, "ease-out is ahead of linear on the way in")
        leaving, _ = motion.pose(1340, span)
        self.assertGreater(leaving, 1 - 40 / 200, "ease-in is slow to start on the way out")
        self.assertIsNone(motion.pose(1500, span))
        self.assertIsNone(motion.pose(-1, span))
        self.assertEqual(motion.pose(150, span)[1] > 0, True, "a line rises into place")

    def test_no_transition_runs_longer_than_600_ms(self):
        self.assertLessEqual(max(motion.ENTER_MS, motion.EXIT_MS), 600)


try:
    import PIL  # noqa: F401
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


@unittest.skipUnless(HAVE_PIL, "rendering needs Pillow")
class Render(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out, True)

    def test_poster_gif_and_mp4_are_written_at_the_format(self):
        from PIL import Image
        for fmt, (w, h) in motion.FORMATS.items():
            with self.subTest(format=fmt):
                out, total, n = motion.render(ITEM, GOOD, self.out, fmt=fmt, scale=0.2, fps=6, gif_fps=3)
                poster = Image.open(out["poster"])
                self.assertEqual(poster.size, (round(w * 0.2), round(h * 0.2)))
                gif = Image.open(out["gif"])
                self.assertGreater(getattr(gif, "n_frames", 1), 5)
                self.assertEqual(n, -(-total * 6 // 1000) + 1)
                if shutil.which("ffmpeg"):
                    self.assertGreater(os.path.getsize(out["mp4"]), 0)
                else:
                    self.assertNotIn("mp4", out)


if __name__ == "__main__":
    unittest.main()
