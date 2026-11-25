/**
 * The desk's two standing rules as one pure function, so `app/actions.ts` and the
 * Python faces (`scripts/standing_rules.py`: the dashboard, `desk_acts`, `today.py`)
 * refuse the same decisions with the same words.
 *
 *   * A hold, a rejection and a rewrite carry a written reason; an approval may (2026-11-11).
 *   * Approving a post stays closed until its argument line is current (the hook and
 *     the claim are Alpha's act) and the claim gate has not blocked it.
 *
 * Keep the sentences and the order identical to `standing_rules.refusal()`:
 * `tests/test_standing_rules.py` runs both over the same vectors.
 */
export const REASON = "A hold, a rejection or a rewrite carries a reason. Write what made you decide this before recording it.";
export const ARGUMENT =
  "Confirm or rewrite the argument line first — the hook and the claim are your act, and nothing is approved without it.";
export const BLOCKED = "The claim gate blocked this one. Fix the line and let the gatekeeper re-read it before approving.";

export function refusal(input: {
  status: string;
  kind: "post" | "reaction";
  rationale: string;
  argCurrent: boolean;
  blocked: boolean;
}): string | null {
  if (input.status !== "approved" && !input.rationale.trim()) return REASON;
  if (input.kind === "post" && input.status === "approved") {
    if (!input.argCurrent) return ARGUMENT;
    if (input.blocked) return BLOCKED;
  }
  return null;
}
