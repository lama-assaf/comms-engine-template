// The page's only two ways to the engine: read every view, and ask for a change.
// control.py answers on 127.0.0.1 only; a change carries the token it wrote
// into this page, so no other site open in the browser can make one.
import type { State } from "./types";

const meta = document.querySelector('meta[name="control-token"]');
const TOKEN = meta?.getAttribute("content") || "";

export const DESK = "http://127.0.0.1:4310";

export async function loadState(): Promise<State> {
  const r = await fetch("/api/state", { cache: "no-store" });
  if (!r.ok) throw new Error(`the engine answered ${r.status}`);
  return r.json();
}

export interface ActResult { ok: boolean; error?: string; conflict?: boolean; data?: Record<string, unknown> }

/** POST one change. A 409 means the file moved since the page read it: reload, never overwrite. */
export async function postAct(path: string, body: unknown): Promise<ActResult> {
  try {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Control-Token": TOKEN },
      body: JSON.stringify(body),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) return { ok: false, error: j.error || "that did not work", conflict: r.status === 409 };
    return { ok: true, data: j };
  } catch (e) {
    return { ok: false, error: `could not reach the engine: ${e}` };
  }
}

export const hasToken = () => Boolean(TOKEN) && TOKEN !== "__CONTROL_TOKEN__";
