import { db } from "@/db";
import { items, decisions, edits, argumentLines, reviews, proposals, findings, runs, themes, inventory, syncMeta } from "@/db/schema";
import type { Item, Decision, Edit, ArgumentLine, Review, Proposal } from "@/db/schema";
import { desc, asc } from "drizzle-orm";
import { readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { baseHash } from "./hash";
import { STATE } from "./paths";

/*
 * The derived reading of a row.
 *
 * Every rule in here already governed the artifact desk; they are restated in
 * one module so the calendar, the queue and the item sheet cannot disagree
 * about whether something is waiting on Alpha.
 */

export type EditState = "none" | "pending" | "applied" | "dropped" | "conflict";

export type Row = {
  item: Item;
  decision?: Decision;
  edit?: Edit;
  argument?: ArgumentLine;
  reviews: Review[];
  /** The item as it should be read: the note, with Alpha's saved edit laid over it. */
  view: { title: string; post: string; teaser_linkedin: string; teaser_x: string };
  editState: EditState;
  /** Alpha's decision if there is one, else the note's own `alpha_status`. */
  status: string;
  /** The argument line is current only while it still names the hook on the card. */
  argCurrent: boolean;
  blocked: boolean;
  /** Approve is closed until the argument line is current. */
  canApprove: boolean;
};

export function viewOf(item: Item, edit?: Edit) {
  return {
    title: edit?.title ?? item.title,
    post: edit?.post ?? item.post,
    teaser_linkedin: edit?.teaserLinkedin ?? item.teaserLinkedin,
    teaser_x: edit?.teaserX ?? item.teaserX,
  };
}

/**
 * Where an edit stands against the note, by the same three-way test
 * `apply_edits.py` makes.
 *
 *   applied/dropped  the note's `desk_edit` marker already names this edit
 *   pending          the note still hashes to `base_hash`; it will apply cleanly
 *   conflict         it does not — the note moved after Alpha was shown it, so
 *                    nothing is written either way until a person picks a side
 */
export function editStateOf(item: Item, edit?: Edit): EditState {
  if (!edit) return "none";
  const marker = item.deskEdit;
  if (marker?.edited_at && marker.edited_at === edit.at) {
    return marker.resolution === "vault" ? "dropped" : "applied";
  }
  return edit.baseHash === item.noteHash ? "pending" : "conflict";
}

export function toRow(
  item: Item,
  decision?: Decision,
  edit?: Edit,
  argument?: ArgumentLine,
  itemReviews: Review[] = [],
): Row {
  const view = viewOf(item, edit);
  const status = decision?.status ?? item.alphaStatus ?? "proposed";
  // Beta drafts the argument line; Alpha owns it. Rewriting the hook reopens
  // it, which is why the act is compared against the hook now on the card
  // rather than simply being present.
  const argCurrent = !!argument && argument.hook === view.title;
  const blocked = item.gateVerdict === "block";
  return {
    item,
    decision,
    edit,
    argument,
    reviews: itemReviews,
    view,
    editState: editStateOf(item, edit),
    status,
    argCurrent,
    blocked,
    canApprove: argCurrent && !blocked,
  };
}

export async function loadRows(): Promise<Row[]> {
  const [is, ds, es, as, rs] = await Promise.all([
    db.select().from(items).orderBy(asc(items.date), asc(items.id)),
    db.select().from(decisions),
    db.select().from(edits),
    db.select().from(argumentLines),
    db.select().from(reviews).orderBy(desc(reviews.at)),
  ]);
  const dm = new Map(ds.map((d) => [d.id, d]));
  const em = new Map(es.map((e) => [e.itemId, e]));
  const am = new Map(as.map((a) => [a.itemId, a]));
  const rm = new Map<string, Review[]>();
  rs.forEach((r) => rm.set(r.itemId, [...(rm.get(r.itemId) ?? []), r]));
  return is.map((i) => toRow(i, dm.get(i.id), em.get(i.id), am.get(i.id), rm.get(i.id) ?? []));
}

export async function loadRow(id: string): Promise<Row | null> {
  const rows = await loadRows();
  return rows.find((r) => r.item.id === id) ?? null;
}

export async function loadProposals(): Promise<{ proposal: Proposal; decision?: Decision }[]> {
  const [ps, ds] = await Promise.all([db.select().from(proposals), db.select().from(decisions)]);
  const dm = new Map(ds.map((d) => [d.id, d]));
  return ps.map((p) => ({ proposal: p, decision: dm.get(p.id) }));
}

export async function loadContext() {
  const [fs, rs, ts, inv, meta] = await Promise.all([
    db.select().from(findings),
    db.select().from(runs).orderBy(desc(runs.at)),
    db.select().from(themes),
    db.select().from(inventory),
    db.select().from(syncMeta),
  ]);
  return { findings: fs, runs: rs, themes: ts, inventory: inv, meta: new Map(meta.map((m) => [m.key, m.value])) };
}

/** The hash the desk stamps on an edit: the note as this page rendered it. */
export function hashOfNote(item: Item) {
  return baseHash({
    post: item.post,
    teaser_linkedin: item.teaserLinkedin,
    teaser_x: item.teaserX,
    title: item.title,
  });
}

/* ---------------------------------------------------------------- waiting -- */

export type Waiting = { rank: number; id: string; kind: "post" | "reaction" | "claims review"; title: string; why: string; act: string };

/** One note `claims_check.py` raised (plan v2, A6): a claim it cites moved. */
export type ClaimsReview = {
  id: string;
  title: string;
  stream: string;
  standing: "published" | "queued";
  cites: string[];
  reasons: { claim: string; kind: string; detail: string }[];
  action: string;
};

/**
 * `state/claims-review.json`, written nightly by `claims_check.py`. Read from
 * the file rather than the database: it is derived state the desk only shows,
 * and a missing file means the check has not run, never that nothing moved.
 */
export function loadClaimsReview(): { checkedAt: string | null; items: ClaimsReview[] } {
  const p = path.join(STATE, "claims-review.json");
  if (!existsSync(p)) return { checkedAt: null, items: [] };
  try {
    const data = JSON.parse(readFileSync(p, "utf-8")) as { checked_at?: string; items?: ClaimsReview[] };
    return { checkedAt: data.checked_at ?? null, items: data.items ?? [] };
  } catch {
    return { checkedAt: null, items: [] };
  }
}

/**
 * What is actually waiting on Alpha, most urgent first. Same ordering the
 * artifact desk used: a conflict outranks a block, a block outranks a missing
 * argument line, and everything outranks an undecided comment.
 */
export function waitingOn(
  rows: Row[],
  props: { proposal: Proposal; decision?: Decision }[],
  claims: ClaimsReview[] = [],
): Waiting[] {
  const out: Waiting[] = [];
  // A claim a piece cites has moved: second only to an edit conflict, because
  // a published piece may now say more than the register supports.
  for (const c of claims) {
    out.push({ rank: 1, id: c.id, kind: "claims review", title: c.title,
      why: `${c.standing === "published" ? "Published" : "Queued"}; ` +
        c.reasons.map((x) => `${x.claim ? x.claim + " " : ""}${x.kind}: ${x.detail}`).join("; ") +
        ". Update, annotate or retire it; the engine never edits a published piece.",
      act: "Review" });
  }
  for (const r of rows) {
    if (r.editState === "conflict") {
      out.push({ rank: 0, id: r.item.id, kind: "post", title: r.view.title,
        why: "Your edit and the note have diverged. Nothing was written either way — pick which version stands.", act: "Resolve" });
    } else if (r.blocked) {
      out.push({ rank: 1, id: r.item.id, kind: "post", title: r.view.title,
        why: "The claim gate stopped this one. Fix the line or drop the post.", act: "Read the check" });
    } else if (r.status === "proposed" && !r.argCurrent) {
      out.push({ rank: 2, id: r.item.id, kind: "post", title: r.view.title,
        why: "Needs your argument line. Confirm the hook and the claim as they stand, or rewrite them.", act: "Open" });
    } else if (r.status === "proposed") {
      out.push({ rank: 3, id: r.item.id, kind: "post", title: r.view.title,
        why: "Argument line confirmed. Approving schedules the post for its day; it puts nothing on the site.", act: "Decide" });
    } else if (r.status === "rewrite") {
      out.push({ rank: 5, id: r.item.id, kind: "post", title: r.view.title,
        why: "Rewrite requested. theme-writer redrafts this one first next cycle.", act: "Open" });
    }
  }
  for (const { proposal, decision } of props) {
    if ((decision?.status ?? "proposed") !== "proposed") continue;
    out.push({ rank: 4, id: proposal.id, kind: "reaction", title: `Reply to ${proposal.author} on ${proposal.theme}`,
      why: "Clearing it lets a person place the comment by hand; the engine never sends it.", act: "Read it" });
  }
  return out.sort((a, b) => a.rank - b.rank);
}

/* --------------------------------------------------------------- calendar -- */

export type Day = { iso: string; date: Date; inMonth: boolean; today: boolean; rows: Row[] };

export function monthGrid(rows: Row[], year: number, month: number, today = new Date()): Day[] {
  const byDate = new Map<string, Row[]>();
  rows.forEach((r) => {
    if (!r.item.date) return;
    byDate.set(r.item.date, [...(byDate.get(r.item.date) ?? []), r]);
  });
  const first = new Date(Date.UTC(year, month, 1));
  // Monday-first, the week the cycle job's calendar in engine.json is written in.
  const lead = (first.getUTCDay() + 6) % 7;
  const start = new Date(first);
  start.setUTCDate(1 - lead);
  const todayIso = isoDay(today);
  const days: Day[] = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(start);
    d.setUTCDate(start.getUTCDate() + i);
    const iso = isoDay(d);
    days.push({ iso, date: d, inMonth: d.getUTCMonth() === month, today: iso === todayIso, rows: byDate.get(iso) ?? [] });
  }
  // Drop a trailing all-out-of-month week rather than always drawing six.
  return days.length === 42 && days.slice(35).every((d) => !d.inMonth && !d.rows.length) ? days.slice(0, 35) : days;
}

export function isoDay(d: Date) {
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
}

export function unscheduled(rows: Row[]) {
  return rows.filter((r) => !r.item.date);
}

export const MONTHS = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];
