import { sqliteTable, text, integer, index } from "drizzle-orm/sqlite-core";

/*
 * The desk's database is two things and nothing else:
 *
 *   a derived index   tables the engine pushes and the app only reads — items,
 *                     findings, proposals, runs, themes, inventory. Every row
 *                     is rebuildable by `desk_sync.py --push`; deleting the file
 *                     loses nothing.
 *
 *   a decision store  tables the app writes and the engine pulls — decisions,
 *                     edits, argumentLines, reviews. These are the only rows
 *                     that exist nowhere else until `--pull` runs, which is why
 *                     `--pull` is the first step of every cycle.
 *
 * `Content/Calendar/<title>.md` remains the record and `scripts/repo.py` remains
 * its only writer. Nothing here writes a note or `.atelier/memory/`.
 */

/* ------------------------------------------------------------------ index -- */

/**
 * One row per engine note in `Content/Calendar/`, as `repo.load_items()` reads
 * it. Read-only in the app: the columns are a mirror, and an edit Alpha makes
 * goes to `edits`, never here, so a `--push` can always overwrite this table
 * wholesale without losing an act.
 */
export const items = sqliteTable(
  "items",
  {
    id: text("id").primaryKey(), // engine_id, e.g. Q-2026-01-05-example-1
    title: text("title").notNull().default(""),
    theme: text("theme").notNull().default(""),
    stream: text("stream").notNull().default(""),
    type: text("type").notNull().default(""),
    pillar: text("pillar").notNull().default(""),
    platform: text("platform").notNull().default(""),
    format: text("format").notNull().default(""),
    owner: text("owner").notNull().default(""),
    campaign: text("campaign").notNull().default(""),
    // The calendar axis: the note's `date`, an ISO day. Every engine note has
    // one; an item with none is shown in an "unscheduled" rail rather than
    // being given a date the engine has no authority to invent.
    date: text("date"),
    status: text("status").notNull().default("Idea"), // Idea|Drafting|Ready|Scheduled|Published
    alphaStatus: text("alpha_status").notNull().default("proposed"),
    gateVerdict: text("gate_verdict").notNull().default(""),
    gate: text("gate", { mode: "json" }).$type<GateRecord | null>(),
    logic: text("logic").notNull().default(""),
    findingId: text("finding_id").notNull().default(""),
    anchor: text("anchor").notNull().default(""),
    slug: text("slug").notNull().default(""),
    excerpt: text("excerpt").notNull().default(""),
    cta: text("cta").notNull().default(""),
    post: text("post").notNull().default(""),
    teaserLinkedin: text("teaser_linkedin").notNull().default(""),
    teaserX: text("teaser_x").notNull().default(""),
    hooksConsidered: text("hooks_considered", { mode: "json" }).$type<string[]>(),
    partnerTags: text("partner_tags", { mode: "json" }).$type<string[]>(),
    freshnessDeadline: text("freshness_deadline"),
    draftedBy: text("drafted_by").notNull().default(""),
    draftedAt: text("drafted_at"),
    // `repo.base_hash()` over the note as it stands at push time. The app
    // stamps an edit with this value, and `apply_edits.py` re-derives it from
    // the note: where the two disagree the note has moved and nothing is
    // written. See lib/hash.ts.
    noteHash: text("note_hash").notNull().default(""),
    notePath: text("note_path").notNull().default(""),
    // The `desk_edit` marker `apply_edits.py` writes onto the note once an edit
    // has been applied or dropped, so the card can say which.
    deskEdit: text("desk_edit", { mode: "json" }).$type<DeskEditMarker | null>(),
    publishedAt: text("published_at"),
    // plan v2: the claims register rows the post leans on (A5), and the
    // planning query it answers, its one-variable hypothesis, the predicted
    // band and the live test it belongs to (A8). Added by desk_sync.py.
    cites: text("cites", { mode: "json" }).$type<string[]>(),
    query: text("query").notNull().default(""),
    hypothesis: text("hypothesis").notNull().default(""),
    predicted: text("predicted").notNull().default(""),
    testId: text("test_id").notNull().default(""),
    notionUrl: text("notion_url").notNull().default(""),
    syncedAt: text("synced_at").notNull().default(""),
  },
  (t) => [index("items_date_idx").on(t.date), index("items_theme_idx").on(t.theme)],
);

/** One row of the claim gate's own record, as `gatekeeper` writes it onto the note. */
export type GateCheck = { check: string; result: string; line?: string; fix?: string };
export type GateRecord = {
  verdict?: string;
  reviewed_at?: string;
  by?: string;
  checks?: GateCheck[];
  notes?: string[];
  blocks?: string[];
};
export type DeskEditMarker = { edited_at?: string; by?: string; base_hash?: string; resolution?: string; at?: string };

/** The listener's graded findings, from `state/signals.json`. */
export const findings = sqliteTable("findings", {
  stream: text("stream").notNull().default(""),
  id: text("id").primaryKey(), // F1, F3, ...
  theme: text("theme").notNull().default(""),
  summary: text("summary").notNull().default(""),
  why: text("why").notNull().default(""),
  shape: text("shape").notNull().default(""), // content | conversation
  relevance: text("relevance").notNull().default(""),
  sentiment: text("sentiment").notNull().default(""),
  source: text("source").notNull().default(""),
  url: text("url").notNull().default(""),
  at: text("at"),
  status: text("status").notNull().default(""), // picked | not-this-week | held
});

/** Engagement's comment proposals, from `state/engagement.json`. Decidable. */
export const proposals = sqliteTable("proposals", {
  stream: text("stream").notNull().default(""),
  id: text("id").primaryKey(),
  theme: text("theme").notNull().default(""),
  author: text("author").notNull().default(""),
  handle: text("handle").notNull().default(""),
  platform: text("platform").notNull().default(""),
  url: text("url").notNull().default(""),
  why: text("why").notNull().default(""),
  draft: text("draft").notNull().default(""),
  at: text("at"),
});

/** `state/runs.json`, one row per agent step. */
export const runs = sqliteTable("runs", {
  stream: text("stream").notNull().default(""),
  rowid: integer("rowid").primaryKey({ autoIncrement: true }),
  runId: text("run_id").notNull().default(""),
  step: text("step").notNull().default(""),
  at: text("at"),
  detail: text("detail").notNull().default(""),
  items: integer("items"),
  terms: integer("terms"),
  elapsedS: text("elapsed_s"),
  file: text("file").notNull().default(""),
});

/** The leadership themes, one row per hashtag in `.atelier/memory/themes.md`. */
export const themes = sqliteTable("themes", {
  stream: text("stream").notNull().default(""),
  tag: text("tag").primaryKey(), // #ExampleTheme
  differentiator: text("differentiator").notNull().default(""),
  licence: text("licence").notNull().default(""),
  fact: text("fact").notNull().default(""),
  partners: text("partners", { mode: "json" }).$type<string[]>(),
});

/**
 * The handle inventory, from `.atelier/memory/handles.md`.
 *
 * `handles.private.md` is never read into this table. The stealth
 * counterparties are the one part of the inventory that must not reach a store
 * that can be deployed, and `desk_sync.py` strips them exactly as
 * `build_dashboard.py`'s `inv()` does — by dropping the `identity` key and
 * reading only the public file.
 */
export const inventory = sqliteTable("inventory", {
  stream: text("stream").notNull().default(""),
  rowid: integer("rowid").primaryKey({ autoIncrement: true }),
  scope: text("scope").notNull().default(""), // own | partner
  brand: text("brand").notNull().default(""),
  name: text("name").notNull().default(""),
  platform: text("platform").notNull().default(""),
  handle: text("handle").notNull().default(""),
  status: text("status").notNull().default(""), // verified | collect
  lastVerified: text("last_verified"),
  stale: integer("stale", { mode: "boolean" }).notNull().default(false),
  note: text("note").notNull().default(""),
});

/* --------------------------------------------------------- decision store -- */

/**
 * Alpha's decision on one target — a theme post (`kind: post`, id = engine id)
 * or a comment proposal (`kind: reaction`).
 *
 * `--pull` writes these to `state/decisions.json` keyed by id in the shape
 * `{status, note, by, at}`, which is what the `distributor` and `publish.py`
 * already read. `status: rewrite` is the request-rewrite action, which
 * `theme-writer` redrafts first next cycle.
 */
export const decisions = sqliteTable("decisions", {
  id: text("id").primaryKey(),
  kind: text("kind").notNull().default("post"),
  status: text("status").notNull(), // approved | held | rejected | rewrite
  note: text("note").notNull().default(""),
  by: text("by").notNull().default("Alpha"),
  at: text("at").notNull(),
});

/**
 * Alpha's in-place edit of a draft, stamped with the hash of the note as the
 * desk showed it. Same shape as the artifact database's `edits/<id>`, so
 * `apply_edits.py` needs no change: it still applies an edit only while the
 * note hashes to `baseHash`, and reports a conflict rather than clobbering.
 */
export const edits = sqliteTable("edits", {
  itemId: text("item_id").primaryKey(),
  title: text("title").notNull().default(""),
  post: text("post").notNull().default(""),
  teaserLinkedin: text("teaser_linkedin").notNull().default(""),
  teaserX: text("teaser_x").notNull().default(""),
  baseHash: text("base_hash").notNull(),
  by: text("by").notNull().default("Alpha"),
  at: text("at").notNull(),
});

/**
 * The argument line: the hook and the claim the post makes. Beta drafts it,
 * Alpha owns it, and approval stays closed until Alpha has confirmed or
 * rewritten it — the standing rule milestone 1 established. The act is current
 * only while `hook` still names the hook on the card, so a later edit to the
 * hook reopens it.
 */
export const argumentLines = sqliteTable("argument_lines", {
  itemId: text("item_id").primaryKey(),
  act: text("act").notNull(), // confirmed | rewritten
  hook: text("hook").notNull().default(""),
  claim: text("claim").notNull().default(""),
  by: text("by").notNull().default("Alpha"),
  at: text("at").notNull(),
});

/**
 * Why Alpha decided what they decided.
 *
 * A decision cannot be recorded without one. `scope: standing` is the part that
 * outlives the item: `--pull` appends those to `.atelier/memory/reviews.md`,
 * which `theme-writer` reads before drafting and `gatekeeper` reads before
 * gating, so the same note does not have to be written twice. `scope: item`
 * stays here and on the card.
 *
 * `syncedAt` is set by `--pull` and is what stops an entry being appended to
 * memory twice; it is never cleared by a `--push`.
 */
export const reviews = sqliteTable(
  "reviews",
  {
    rowid: integer("rowid").primaryKey({ autoIncrement: true }),
    itemId: text("item_id").notNull(),
    kind: text("kind").notNull().default("post"),
    theme: text("theme").notNull().default(""),
    title: text("title").notNull().default(""),
    verdict: text("verdict").notNull().default(""), // the decision it justifies
    rationale: text("rationale").notNull(),
    scope: text("scope").notNull().default("item"), // item | standing
    by: text("by").notNull().default("Alpha"),
    at: text("at").notNull(),
    syncedAt: text("synced_at"),
  },
  (t) => [index("reviews_item_idx").on(t.itemId), index("reviews_synced_idx").on(t.syncedAt)],
);

/** `--push` / `--pull` bookkeeping, so the desk can say how stale it is. */
export const syncMeta = sqliteTable("sync_meta", {
  key: text("key").primaryKey(),
  value: text("value").notNull().default(""),
});

export type Item = typeof items.$inferSelect;
export type Decision = typeof decisions.$inferSelect;
export type Edit = typeof edits.$inferSelect;
export type ArgumentLine = typeof argumentLines.$inferSelect;
export type Review = typeof reviews.$inferSelect;
export type Proposal = typeof proposals.$inferSelect;
export type Finding = typeof findings.$inferSelect;
