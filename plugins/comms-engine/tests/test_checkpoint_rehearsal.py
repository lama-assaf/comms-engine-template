"""
The checkpoint, rehearsed (plan v2, after A9; ORCHESTRATION.md section 13).

The plan's checkpoint is one article going plan -> draft -> gate -> publish ->
score -> readout on real records. A real one needs a publication and 72
hours, so this rehearses the same month on fixtures, in a temp vault and a
temp state directory, through the real scripts in the order the schedule
runs them:

  07:15  plan_queries -> five drafts with cites, query, hypothesis, predicted
         -> gate_lint -> repo ingest -> predictions appended
         (publish: the record publish.py writes, published_at on the note)
  22:00  score.py at 7 days -> actual beside predicted -> metrics rows ->
         livetests close
  22:15  claims_check with a cited row superseded -> the citing note raised
  1st    readout -> correlation live, the month's stage

Shared memory is the fixture copy (`fixture_memory.py`). Nothing here touches
Content/Calendar, state/ or the register.
"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ENGINE, "scripts"))
sys.path.insert(0, HERE)

import claims_check  # noqa: E402
import fixture_memory  # noqa: E402
import gate_lint  # noqa: E402
import livetests  # noqa: E402
import memory  # noqa: E402
import metrics  # noqa: E402
import plan_queries  # noqa: E402
import predictions  # noqa: E402
import readout  # noqa: E402
import repo  # noqa: E402
import score  # noqa: E402

with open(os.path.join(HERE, "fixtures.json"), encoding="utf-8") as f:
    BASE = json.load(f)["base"]

PUB = dt.datetime(2026, 10, 6, 8, 0, tzinfo=dt.timezone.utc)
# predicted band, likes read at day 6: three at baseline, one above, one below
PLAN = [("baseline", 20), ("baseline", 22), ("baseline", 18), ("above", 60), ("below", 5)]
TEST_ID = "T-acme-9"


def draft(n, predicted):
    item = json.loads(json.dumps(BASE))
    slug = f"rehearsal-piece-{n}"
    item.update({
        "id": f"Q-R-{n}", "stream": "Acme", "type": "Evergreen", "finding_id": f"F{n}",
        "anchor": "The standards body's governance framework.",
        "logic": f"L{n % 3 + 1}", "format": "Observation", "title": f"Piece {n} holds a credential. It does not choose the root.",
        "slug": slug, "cta": repo.post_url(slug),
        "teaser_linkedin": BASE["teaser_linkedin"].replace("a-root-is-not-a-wallet", slug),
        "teaser_x": BASE["teaser_x"].replace("a-root-is-not-a-wallet", slug),
        "query": "gaps" if n < 3 else "depth", "hypothesis": "hook form: a two-sentence contrast",
        "predicted": predicted, "test_id": TEST_ID, "cites": ["C-acme-4", "C-acme-1"],
        "hooks_considered": [], "alpha_status": "approved",
        "slot": {"date": (PUB.date() + dt.timedelta(days=n)).isoformat(), "platform": "Blog", "campaign": "q4"},
    })
    return item


class Rehearsal(fixture_memory.FixtureMemoryCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="rehearsal-")
        self.state = os.path.join(self.tmp, "state")
        self.cal = os.path.join(self.tmp, "Calendar")
        os.makedirs(os.path.join(self.state, "metrics-input"))
        os.makedirs(self.cal)
        self.lessons = os.path.join(self.tmp, "lessons.md")
        with open(self.lessons, "w", encoding="utf-8") as f:
            f.write("# lessons\n")
        self._saved = (repo.CAL, repo.STATE, livetests.LESSONS)
        repo.CAL, repo.STATE, livetests.LESSONS = self.cal, self.state, self.lessons

    def tearDown(self):
        repo.CAL, repo.STATE, livetests.LESSONS = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def test_one_month_of_the_loop(self):
        # 07:15 - plan
        planning = plan_queries.run("acme", state=self.state, cal=self.cal, today=PUB.date(),
                                    signals={"per_theme": {"#ExampleTheme": {"count": 20, "relevance": 3.0}}, "findings": []},
                                    engagement={}, changes=[])
        self.assertEqual(planning["queries"], "files")
        self.assertIn("#ExampleTheme", planning["order"])

        # draft, gate, ingest, prediction
        items = [draft(n, p) for n, (p, _) in enumerate(PLAN)]
        for it in items:
            verdict = gate_lint.lint(it)
            self.assertEqual(verdict["verdict"], "pass", [c for c in verdict["checks"] if c["result"] != "pass"])
            repo.write_item(it, "Idea")
        self.assertEqual(predictions.append_for(repo.load_items(), self.state), [f"Q-R-{n}" for n in range(5)])

        # publish: the record publish.py writes onto the note
        for n, it in enumerate(items):
            repo.set_fields(it["id"], {"status": "Ready", "published_to": ["vault"],
                                       "published_at": (PUB + dt.timedelta(hours=n)).isoformat(timespec="seconds"),
                                       "vault_note": "x"})
        livetests.new(TEST_ID, "hook form", "a two-sentence contrast beats a declarative", "Blog", "variation",
                      state=self.state, now=PUB)
        livetests.assign(TEST_ID, variant=["Q-R-3", "Q-R-0"], control=["Q-R-4", "Q-R-2"], state=self.state)

        # what a person read off the platform at day 6
        for n, (_, likes) in enumerate(PLAN):
            with open(os.path.join(self.state, "metrics-input", f"Q-R-{n}.json"), "w", encoding="utf-8") as f:
                json.dump({"reads": [{"at": (PUB + dt.timedelta(days=6)).isoformat(), "platform": "X", "likes": likes,
                                      "impressions": likes * 40, "negatives": {"corrections": 0}}]}, f)

        # 22:00, day 8 - score, metrics, tests
        night = PUB + dt.timedelta(days=8)
        published = repo.load_items()
        records, done = score.score_all("acme", self.state, now=night, items=published,
                                        publish_log={"entries": []}, ledger={"sends": {}}, queue=[])
        self.assertEqual(sorted(done), [f"Q-R-{n}" for n in range(5)])
        by = {r["id"]: r for r in records}
        self.assertEqual(by["Q-R-3"]["score"], 60)
        self.assertIsNotNone(by["Q-R-3"]["baseline"])
        preds = {p["id"]: p for p in predictions.load(self.state)}
        self.assertEqual(preds["Q-R-3"]["actual"], "above")
        self.assertEqual(preds["Q-R-4"]["actual"], "below")
        rows = {r["row"]: r for r in metrics.rows("acme", self.state, now=night, items=published)["rows"]}
        self.assertEqual(rows["correlation"]["status"], "live")
        self.assertGreater(rows["correlation"]["value"], 0.5)
        self.assertEqual(rows["reach"]["status"], "context")
        closed = livetests.close(self.state, now=night)
        self.assertEqual(closed[0][:2], (TEST_ID, "trending"))

        # 22:15 - a cited claim is superseded after the gate read the notes
        claims_check.run(state=self.state, items=published, register=memory.load_claims(), now=night)
        moved = memory.load_claims()
        moved["C-acme-1"] = {**moved["C-acme-1"], "superseded_by": "C-acme-99"}
        out = claims_check.run(state=self.state, items=published, register=moved, now=night + dt.timedelta(days=1))
        self.assertEqual(sorted(i["id"] for i in out["items"]), [f"Q-R-{n}" for n in range(5)])
        self.assertTrue(all(i["standing"] == "published" for i in out["items"]))

        # the first of the month - readout
        ro = readout.run("acme", self.state, today=dt.date(2026, 11, 2), lessons_path=self.lessons, items=published)
        self.assertEqual(ro["month"], "2026-10")
        self.assertEqual(ro["correlation"]["pairs"], 5)
        self.assertFalse(ro["scorer_frozen"])
        self.assertEqual(ro["stage"]["pieces"], 5)
        self.assertEqual(ro["stage"]["stage"], "explore")


if __name__ == "__main__":
    unittest.main()
