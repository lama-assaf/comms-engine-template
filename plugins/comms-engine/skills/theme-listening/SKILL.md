---
name: theme-listening
description: The listening pass over the stream's leadership themes and brand mentions. Use whenever a listening cycle runs, when the user asks what the community is saying about a theme, or when signals.json needs refreshing. Wraps salon's social-listening with the theme register, the licence rule and the held-slot trigger test.
---

# theme-listening

The Beta half of "the brand listens": *monitoring themes and mentions detects
community signals; relevance and sentiment feed content inspiration,
interaction proposals and reach amplification.* This skill produces
**signals**. Reading them into a content decision is Alpha and happens on the
desk, never here.

## inputs

1. `.atelier/memory/themes.md`: the themes, their differentiators, the fact
   each links back to, and their licence grades. The single source every
   runtime reads; `themes.json` holds only the
   engine-local X search terms and keyword sets, joined to this roster by tag.
2. `.atelier/memory/instincts.md`, `status.md`, `voice.md`: what may be said.
3. The latest machine pass: `state/listening-latest.json`
   (written by `scripts/listen.py`; X via twitterapi.io's advanced search).
   The script is the only X reader, in a session or on the schedule; the Apify
   MCP in `.mcp.json` carries the LinkedIn actors only, for `--linkedin` work.
4. Primary-source sweep: WebSearch (or brave-search MCP) for issuing-body
   publications in the window: the standards bodies, regulators and
   institutions `themes.md` names per theme. Trade press is context, never a
   trigger.

## workflow

1. Read `themes.md` and `instincts.md`. Note which themes are `held`: signals still
   get collected for them, but the content opportunity is capped at the
   standards argument (no brand capability, no partner, no date).
2. Run or load the machine pass. Prescores are hints. For every candidate:
   relevance is whether the post argues something one of the differentiators
   answers; sentiment is toward the *theme*, not toward the brand.
3. Run the primary-source sweep for the window. Apply the held-slot test: the
   source must be the issuing body's own document, published in full, within
   48 hours. Anything else is context.
4. Write each finding in salon's four-part format, plus three engine fields:

   - **finding**: plainly, not hyped
   - **evidence**: links; quote the source's own words where the wording is the point
   - **conversation opportunity**: which thread, which comment shape
     (missing-piece concession, data-point-first, sharper follow-up question),
     or *none*. Comments are drafted by engagement-manager, never sent from here.
   - **content opportunity**: none / theme post / held-slot trigger
   - **theme**: one of the tags in `themes.md`, or `@mentions`. An item the `@watched` pass found (an account a person watches from the control page) is graded under the theme its text fits, or `none`
   - **licence check**: licensed / licensed-with-hedge / held, copied from `themes.md`'s licence table, and what that caps
   - **stealth check**: pass, or which stealth term the finding brushes against

5. Score each finding 0 to 5 on relevance and mark sentiment (positive / neutral /
   negative / critical). Aggregate per theme: count, mean relevance, sentiment mix.
   These are the key result *"listener signals per theme: mentions, relevance,
   sentiment"*.
6. Write `state/signals.json`. `stream` is the brand's
   name as `streams.md` spells it (`Acme` in a fresh clone):

```json
{
  "run_id": "...", "stream": "Acme", "window": {"from": "...", "to": "..."},
  "sources": [{"name": "x/twitterapi.io", "items": 0, "cost_note": "..."}, {"name": "web/primary-source", "queries": 0}],
  "per_theme": {"#Theme": {"count": 0, "relevance": 0.0, "sentiment": {"positive": 0, "neutral": 0, "negative": 0, "critical": 0}}},
  "findings": [{"id": "F1", "stream": "Acme", "theme": "#...", "finding": "...", "evidence": [{"title": "...", "url": "...", "quote": "..."}], "relevance": 0, "sentiment": "neutral", "conversation": {"target": "...", "shape": "..."}, "content": "theme post | held-slot trigger | none", "licence": "...", "stealth": "pass", "freshness_deadline": "..."}]
}
```

7. Hand content-shaped findings to `theme-post`. Hand conversation-shaped
   findings to engagement-manager's comment-strategy. Never post anything.

## rules

- Mentions of the brand, or of a stream it is paired with in `streams.md`, are
  logged, never answered from this skill.
- A finding without a link is a hunch and does not enter signals.json.
- No count of third parties (members, licensees, issuers) is carried into a
  finding as a fact the brand would publish; record the source and let the
  post say "published regularly, anyone can count it".
- X search is pay-per-tweet on twitterapi.io (USD 0.15 per 1,000, a page of up
  to 20 billed for what it returns); the LinkedIn actors cost about sixteen
  times more per item. Keep `--max` at or under 12 per term unless the user
  raises it. Note the run's approximate cost in `sources`.
- X and LinkedIn scraping relocates ToS exposure rather than removing it
  (salon mcp-configs README). Evidence links point at public posts only.
