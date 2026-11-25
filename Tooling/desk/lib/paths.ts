import path from "node:path";
import { existsSync, readFileSync } from "node:fs";

/** The instance root (brand.json, Content/, state/): two levels above `Tooling/desk/`. */
export const INSTANCE = process.env.COMMS_ENGINE_INSTANCE ?? path.resolve(process.cwd(), "..", "..");
export const STATE = path.join(INSTANCE, "state");

/**
 * The derived index and decision store.
 *
 * It sits in `state/` beside `queue.json` and `decisions.json` because it is the
 * same kind of thing: run state derived from the notes, gitignored, rebuildable
 * from scratch with `desk_sync.py --push`. The record is `Content/Calendar/`.
 */
export const DB_PATH = process.env.DESK_DB ?? path.join(STATE, "desk.db");

/**
 * The brand's display name, from brand.json's `brand` block (engine.local.json
 * may override it, as the engine's config.py allows). Read per request like the
 * rest: the desk shows whatever brand this checkout is stamped with.
 */
export function brandName(): string {
  let name = "Acme";
  for (const file of ["brand.json", "engine.local.json"]) {
    const p = path.join(INSTANCE, file);
    if (!existsSync(p)) continue;
    try {
      const doc = JSON.parse(readFileSync(p, "utf-8")) as { brand?: { name?: string } };
      if (doc.brand?.name) name = doc.brand.name;
    } catch {
      // an unreadable override never hides the desk; the tracked file's name stands
    }
  }
  return name;
}
