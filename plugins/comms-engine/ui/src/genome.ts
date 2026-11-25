// The brand genome onto the page.
//
// - The neutrals (white, the greys, the ink) and `primary`, the strong anchor,
//   come from the genome's `colors`.
// - Every coloured surface takes a colour from its `palette`. In the pastel
//   style (owner, 2026-11-07: pastel variants, blue shades by default) a
//   colour is a tone: a soft fill, a deep shade of the same hue for the text on
//   it (WCAG 4.5:1 or better), and the colour itself for small marks and icons.
//   In the solid style it is the colour itself, with white or ink text.
// - The status roles (critical, warning, good) only ever mean a status, never a
//   page or a theme.
//
// genome.py has already checked every colour and dropped any script from the logo.
import type { CSSProperties } from "react";
import type { Genome } from "./types";

let G: Genome | null = null;

// ── colour arithmetic ──────────────────────────────────────────────────
const rgb = (hex: string) => { const c = hex.replace("#", ""); return [0, 2, 4].map((i) => parseInt(c.slice(i, i + 2), 16)); };
const toHex = (v: number[]) => "#" + v.map((x) => Math.round(Math.max(0, Math.min(255, x))).toString(16).padStart(2, "0")).join("");
const mix = (a: string, b: string, t: number) => { const x = rgb(a), y = rgb(b); return toHex(x.map((v, i) => v + (y[i] - v) * t)); };
const lum = (hex: string) => {
  const [r, g, b] = rgb(hex).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: string, b: string) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

const ink = () => G?.colors?.ink || "#111111";

/** White or the ink, whichever reads on a fill (4.5:1 against white, else ink). */
export const onColor = (hex: string) => (contrast(hex, "#ffffff") >= 4.5 ? "#ffffff" : ink());

export interface Tone { soft: string; deep: string; strong: string }
/** A colour as a tone: its pastel fill, the deep shade of it that reads on that fill, and the colour itself. */
export function tone(hex: string): Tone {
  const soft = mix(hex, "#ffffff", 0.8);
  let deep = mix(hex, "#000000", 0.35);
  for (let t = 0.4; t <= 0.85 && contrast(deep, soft) < 4.8; t += 0.05) deep = mix(hex, "#000000", t);
  return { soft, deep, strong: hex };
}
const pastel = () => (G?.palette?.style || "pastel") === "pastel";

/** How a coloured surface looks in this genome's style: a pastel tone, or the solid colour. */
export const swatch = (hex: string): CSSProperties => {
  if (!pastel()) return { background: hex, color: onColor(hex) };
  const t = tone(hex);
  return { background: t.soft, color: t.deep };
};
/** A small solid mark (an icon circle, a dot) in a colour, with what reads on it. */
export const markStyle = (hex: string): CSSProperties => ({ background: hex, color: onColor(hex) });

// ── the genome onto :root ──────────────────────────────────────────────
const NEUTRALS: Record<string, string> = { ink: "--ink", surface: "--surface", paper: "--paper", line: "--line", muted: "--muted" };

export function applyGenome(g: Genome | null) {
  if (!g) return;
  G = g;
  const r = document.documentElement.style;
  for (const [k, v] of Object.entries(g.colors || {})) if (NEUTRALS[k]) r.setProperty(NEUTRALS[k], v);
  const primary = g.colors?.primary || "#1f2a44";
  r.setProperty("--primary", primary);
  r.setProperty("--on-primary", onColor(primary));
  r.setProperty("--primary-soft", tone(primary).soft);
  for (const [role, hex] of Object.entries(g.palette?.roles || {})) {
    const t = tone(hex);
    r.setProperty(`--${role}`, hex);                                  // the mark
    r.setProperty(`--on-${role}`, onColor(hex));
    r.setProperty(`--${role}-soft`, pastel() ? t.soft : hex);         // a fill
    r.setProperty(`--${role}-ink`, pastel() ? t.deep : onColor(hex)); // the text on that fill
  }
  const family = g.type?.family, stack = g.type?.stack || "";
  // Inter ships with the page (no web font call); any other family is used if the machine has it.
  r.setProperty("--font", family === "Inter" ? `"Inter Variable", ${stack}` : stack || "inherit");
  r.setProperty("--display", String(g.type?.display_weight || 800));
  // The control page is rounded and soft (shape.ui_radius); shape.radius is the rule for what the brand publishes.
  r.setProperty("--r", `${g.shape?.ui_radius ?? 18}px`);
  if (g.name) document.title = `${g.name} · control`;
}

// ── which colour a page, a theme or a beat takes ───────────────────────
/** The palette colours a page, theme or beat may take: every one but the status colours (when enough are left). */
function identity() {
  const all = (G?.palette?.colors || []).map((c) => c.hex.toLowerCase());
  const R = G?.palette?.roles || {};
  const status = new Set([R.critical, R.warning, R.good].filter(Boolean).map((h) => h.toLowerCase()));
  const rest = all.filter((h) => !status.has(h));
  return rest.length >= 4 ? rest : all.filter((h) => h !== (R.critical || "").toLowerCase());
}
const gcd = (a: number, b: number): number => (b ? gcd(b, a % b) : a);
/** The i-th identity colour, strided through the list so neighbours differ. */
function nth(i: number) {
  const list = identity();
  if (!list.length) return "#577590";
  const step = [3, 4, 5, 7].find((s) => gcd(s, list.length) === 1) || 1;
  return list[(Math.max(0, i) * step) % list.length];
}

const PAGE_ORDER = ["story", "today", "posts", "themes", "heard", "replies", "accounts", "suggestions", "claims", "results", "autonomy", "engagement"];
/** A page's own colour; the system and setup pages stay grey. */
export const pageColor = (key: string) => (key === "system" || key === "setup" ? G?.colors?.muted || "#6b7280" : nth(PAGE_ORDER.indexOf(key)));

/** A theme's colour follows the theme (its place in themes.md), never its rank, and is never a status colour. */
export const themeColor = (tags: string[], tag: string) => nth(Math.max(0, tags.indexOf(tag)) + 3);

/** A colour for the n-th block on a page (a tile, a card): the same stride, so neighbouring blocks differ. */
export const blockColor = (n: number) => nth(n);

/** A status colour, for a block that means a status. */
export const statusColor = (role: "critical" | "warning" | "good" | "info" | "action") => G?.palette?.roles?.[role] || "#577590";

/** The slide colours for each beat: the strong anchor for the cover and the close, white for where we stand, pastel tones between. */
export function slideLook(kind: string): CSSProperties {
  const white = G?.colors?.surface || "#ffffff", primary = G?.colors?.primary || "#1f2a44";
  if (kind === "cover" || kind === "feedback") {
    const accent = tone(G?.palette?.colors?.[0]?.hex || "#4d7fee").soft;
    return { "--s-bg": primary, "--s-ink": onColor(primary), "--s-accent": accent } as CSSProperties;
  }
  if (kind === "state") return { "--s-bg": white, "--s-ink": ink(), "--s-accent": primary } as CSSProperties;
  const BEAT = ["discoveries", "question", "explore", "add", "next"];
  const hex = nth(BEAT.indexOf(kind) + 1);
  if (!pastel()) return { "--s-bg": hex, "--s-ink": onColor(hex), "--s-accent": onColor(hex) } as CSSProperties;
  const t = tone(hex);
  return { "--s-bg": t.soft, "--s-ink": t.deep, "--s-accent": hex } as CSSProperties;
}

/** Whether a slide's text is white, i.e. it sits on a dark fill. */
export const lightText = (look: CSSProperties) => (look as Record<string, string>)["--s-ink"] === "#ffffff";
