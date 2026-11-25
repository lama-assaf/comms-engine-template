import crypto from "node:crypto";

/**
 * The four fields Alpha can edit, in the order `repo.HASH_FIELDS` names them.
 * The order is part of the digest: change it here and every edit already saved
 * turns into a phantom conflict.
 */
export const HASH_FIELDS = ["post", "teaser_linkedin", "teaser_x", "title"] as const;

export type HashFields = Partial<Record<(typeof HASH_FIELDS)[number], string | null | undefined>>;

/** U+001F, the separator `repo.base_hash()` joins the four fields with. */
const SEP = "\u001f";

/**
 * `repo.base_hash()`, in TypeScript: sha256 over the four edited fields,
 * U+001F-separated, UTF-8.
 *
 * This has to agree with the Python byte for byte. `apply_edits.py` applies an
 * edit only while the note still hashes to the `base_hash` the desk recorded, so
 * a digest that disagreed would not corrupt a note — it would make every edit
 * unappliable, which is worse, because on the card it looks like a vault
 * conflict rather than like a bug here. `tests/test_desk_sync.py` runs both
 * implementations over the same fixtures.
 */
export function baseHash(fields: HashFields): string {
  const s = HASH_FIELDS.map((f) => {
    const v = fields[f];
    return v === null || v === undefined ? "" : String(v);
  }).join(SEP);
  return crypto.createHash("sha256").update(s, "utf8").digest("hex");
}
