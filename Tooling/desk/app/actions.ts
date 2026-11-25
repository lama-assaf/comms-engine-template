"use server";

import { revalidatePath } from "next/cache";
import { eq } from "drizzle-orm";
import { db } from "@/db";
import { decisions, edits, argumentLines, reviews, items } from "@/db/schema";
import { hashOfNote, loadRow } from "@/lib/desk";
import { refusal } from "@/lib/rules";

/*
 * Every act Alpha can make, and nothing else.
 *
 * These write the four decision-store tables and no others. Nothing here
 * touches a `Content/Calendar/` note or `.atelier/memory/`:
 * `scripts/desk_sync.py --pull` is what carries these rows out to the engine,
 * and `scripts/repo.py` remains the only writer of a note.
 *
 * There is deliberately no publish action. Nothing publishes itself: an approval
 * schedules the post for its day, the sender posts it, and marking an article
 * live on the site is a person's act on the control page.
 */

const BY = process.env.DESK_USER ?? "Alpha";
const now = () => new Date().toISOString();

export type ActionResult = { ok: true } | { ok: false; error: string };

function touch(id: string) {
  revalidatePath("/");
  revalidatePath("/queue");
  revalidatePath(`/item/${id}`);
}

/**
 * Approve, hold, reject or request a rewrite.
 *
 * Two standing rules are enforced here rather than in the UI, because the UI is
 * a convenience and this is the gate:
 *
 *   * Approve stays closed until the argument line is current. The hook and the
 *     claim are Alpha's act; Beta only drafts them.
 *   * A hold, a rejection and a rewrite carry a rationale (an approval may,
 *     2026-11-11). It is the review, and a rationale marked `standing` becomes
 *     an entry in `.atelier/memory/reviews.md` that the drafting agents read
 *     next cycle. An approval with none records no review.
 */
export async function decide(input: {
  id: string;
  kind: "post" | "reaction";
  status: "approved" | "held" | "rejected" | "rewrite";
  rationale: string;
  scope: "item" | "standing";
}): Promise<ActionResult> {
  const rationale = input.rationale.trim();
  // One check, shared with the Python faces (lib/rules.ts, scripts/standing_rules.py).
  const first = refusal({ status: input.status, kind: input.kind, rationale, argCurrent: true, blocked: false });
  if (first) return { ok: false, error: first };
  let theme = "";
  let title = "";
  if (input.kind === "post") {
    const row = await loadRow(input.id);
    if (!row) return { ok: false, error: `No item ${input.id} in the desk index. Run desk_sync.py --push.` };
    const why = refusal({ status: input.status, kind: input.kind, rationale, argCurrent: row.argCurrent, blocked: row.blocked });
    if (why) return { ok: false, error: why };
    theme = row.item.theme;
    title = row.view.title;
  }
  const at = now();
  const rec = { id: input.id, kind: input.kind, status: input.status, note: rationale, by: BY, at };
  await db.insert(decisions).values(rec).onConflictDoUpdate({ target: decisions.id, set: rec });
  if (rationale) {
    await db.insert(reviews).values({
      itemId: input.id, kind: input.kind, theme, title,
      verdict: input.status, rationale, scope: input.scope, by: BY, at,
    });
  }
  touch(input.id);
  return { ok: true };
}

/**
 * Confirm the argument line as it stands, or record the rewrite of it.
 *
 * `hook` is stored with the act because the act is only current while it still
 * names the hook on the card: rewriting the hook later reopens the question
 * rather than inheriting an approval of different words.
 */
export async function recordArgument(input: {
  id: string;
  act: "confirmed" | "rewritten";
  hook: string;
  claim: string;
}): Promise<ActionResult> {
  const row = await loadRow(input.id);
  if (!row) return { ok: false, error: `No item ${input.id} in the desk index.` };
  const rec = {
    itemId: input.id,
    act: input.act,
    hook: input.hook.trim() || row.view.title,
    claim: input.claim.trim() || row.item.excerpt,
    by: BY,
    at: now(),
  };
  await db.insert(argumentLines).values(rec).onConflictDoUpdate({ target: argumentLines.itemId, set: rec });
  touch(input.id);
  return { ok: true };
}

/**
 * Alpha's in-place edit of a draft.
 *
 * The edit is stamped with `base_hash` — the note as this page rendered it,
 * recomputed here from the mirror row rather than trusted from the form, so a
 * stale tab cannot claim a hash the note no longer has. `apply_edits.py`
 * applies the edit only while the note still hashes to it and reports a
 * conflict otherwise; neither version is ever lost.
 *
 * Rewriting the hook *is* the Alpha act, so it records the argument line
 * itself. Leaving the hook alone is not, and still needs the explicit confirm.
 */
export async function saveEdit(input: {
  id: string;
  title: string;
  post: string;
  teaser_linkedin: string;
  teaser_x: string;
}): Promise<ActionResult> {
  const row = await loadRow(input.id);
  if (!row) return { ok: false, error: `No item ${input.id} in the desk index.` };
  const at = now();
  const rec = {
    itemId: input.id,
    title: input.title,
    post: input.post,
    teaserLinkedin: input.teaser_linkedin,
    teaserX: input.teaser_x,
    baseHash: hashOfNote(row.item),
    by: BY,
    at,
  };
  await db.insert(edits).values(rec).onConflictDoUpdate({ target: edits.itemId, set: rec });
  if (input.title.trim() && input.title.trim() !== row.item.title) {
    await recordArgument({ id: input.id, act: "rewritten", hook: input.title.trim(), claim: row.item.excerpt });
  }
  touch(input.id);
  return { ok: true };
}

/** Drop a saved edit. The note is untouched either way; this clears the overlay. */
export async function discardEdit(id: string): Promise<ActionResult> {
  await db.delete(edits).where(eq(edits.itemId, id));
  touch(id);
  return { ok: true };
}

/**
 * Record which side of an edit conflict stands.
 *
 * This does not resolve anything by itself — `apply_edits.py --prefer` does,
 * and only a person runs it. What this writes is the instruction, as a review
 * with the reasoning attached, so the distributor and the run log both carry
 * why the call went the way it did.
 */
export async function noteConflictPreference(input: {
  id: string;
  prefer: "desk" | "vault";
  rationale: string;
}): Promise<ActionResult> {
  const rationale = input.rationale.trim();
  if (!rationale) return { ok: false, error: "Say why this version stands before recording it." };
  const row = await loadRow(input.id);
  await db.insert(reviews).values({
    itemId: input.id,
    kind: "post",
    theme: row?.item.theme ?? "",
    title: row?.view.title ?? "",
    verdict: `conflict: prefer ${input.prefer}`,
    rationale,
    scope: "item",
    by: BY,
    at: now(),
  });
  touch(input.id);
  return { ok: true };
}

/** The desk's own view of how stale it is; used by the header. */
export async function itemCount() {
  return (await db.select({ id: items.id }).from(items)).length;
}
