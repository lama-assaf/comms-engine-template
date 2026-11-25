// Small helpers for words, dates and numbers, in plain language.
import type { Post, State } from "./types";

export const iso = (d?: string | null) => (d ? String(d).slice(0, 10) : "");

export const day = (d?: string | null) =>
  d ? new Date(iso(d) + "T12:00:00").toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" }) : "no date";

export const when = (t?: string | null) =>
  t ? new Date(t).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";

export const plus = (d: string, n: number) => {
  const x = new Date(d + "T12:00:00");
  x.setDate(x.getDate() + n);
  return x.toISOString().slice(0, 10);
};

export const narrowDay = (d: string) => new Date(d + "T12:00:00").toLocaleDateString(undefined, { weekday: "narrow" });

export const fmt = (n?: number | string | null) => Number(n || 0).toLocaleString();

export const xurl = (h?: string) => `https://x.com/${String(h || "").replace(/^@/, "")}`;

/** Text without links and runs of white space, for a one-line preview. */
export const clean = (t?: unknown) => String(t ?? "").replace(/https?:\/\/\S+/g, "").replace(/\s+/g, " ").trim();

export const excerpt = (p: Post) => clean(p.teaser_x || p.teaser_linkedin || p.post || "").slice(0, 240);

export const greeting = () => {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
};

export const upcoming = (S: State) => S.posts?.upcoming || [];

export const waitingForYou = (p: Post) => !p.decision && p.alpha_status === "proposed" && p.gate !== "block";

export interface Need { k: "critical" | "warning" | "info"; d?: string | null; t: string; x?: string; go: string }

/** What only a person can do, most urgent first. */
export function needs(S: State): Need[] {
  const out: Need[] = [];
  const week = plus(S.today, 7);
  for (const p of upcoming(S)) {
    if (p.gate === "block") out.push({ k: "critical", d: p.date, t: `Stopped by the check: ${p.title}`, x: excerpt(p), go: `post:${p.id}` });
    else if (!p.decision && p.alpha_status === "proposed" && (p.date || "9999") <= week)
      out.push({ k: "warning", d: p.date, t: `Approve or hold: ${p.title}`, x: excerpt(p), go: `post:${p.id}` });
  }
  for (const q of (S.story?.questions || []).filter((q) => q.status === "open"))
    out.push({ k: "info", t: `A big question for you: ${q.question}`, x: q.why, go: `q:${q.id}` });
  for (const r of S.replies?.proposals || [])
    out.push({ k: "info", t: `Place a reply on: ${r.target_title || r.theme}`, x: r.draft_comment, go: "replies" });
  for (const h of S.listening?.held_for_person || [])
    out.push({ k: "info", t: "The listener wants a person to check this", x: typeof h === "string" ? h : JSON.stringify(h), go: "heard" });
  for (const c of S.claims?.review || [])
    out.push({ k: "warning", t: `A fact a post relies on has changed: ${c.id || c.title || ""}`, go: "claims" });
  if (S.accounts && !S.accounts.private.present)
    out.push({ k: "critical", t: "The private list of names to keep quiet is missing, so every post is stopped", go: "accounts" });
  for (const j of S.engine?.jobs || [])
    if (j.loaded === false && !/optional/i.test(j.what || "")) out.push({ k: "warning", t: `A scheduled job is switched off: ${j.job}`, x: j.what, go: "system" });
  return out;
}
