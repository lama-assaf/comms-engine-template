import { useEffect, type ReactNode } from "react";
import { Check, CircleAlert, OctagonX, X } from "lucide-react";
import type { Post } from "../types";
import { meta as pageMeta } from "../nav";
import { useApp } from "../ctx";
import { swatch, themeColor } from "../genome";

export const Chip = ({ children, k = "", title }: { children: ReactNode; k?: string; title?: string }) =>
  children === "" || children == null ? null : <span className={`chip ${k}`} title={title}>{children}</span>;

/** A theme as a solid pill in its own colour: the colour follows the theme (its place in themes.md), never its rank. */
export function Theme({ tag }: { tag?: string }) {
  const { S } = useApp();
  if (!tag) return null;
  const tags = (S.themes?.rows || []).map((t) => t.tag);
  return tags.includes(tag) ? <span className="chip" style={swatch(themeColor(tags, tag))}>{tag}</span> : <span className="chip">{tag}</span>;
}

export const CHECK: Record<string, [string, string, string]> = {
  pass: ["good", "ready", "The automatic check found nothing to fix."],
  "pass-with-edits": ["warning", "small fixes", "The automatic check fixed or flagged small things; read its note."],
  block: ["critical", "stopped", "The check stopped this post: it says something we cannot prove yet."],
};
export const checkWord = (g?: string) => CHECK[g || ""]?.[1] || "not checked";

export function CheckChip({ gate }: { gate?: string }) {
  const c = CHECK[gate || ""];
  if (!c) return <Chip title="The automatic check has not read this post yet.">not checked yet</Chip>;
  const Icon = c[0] === "good" ? Check : c[0] === "warning" ? CircleAlert : OctagonX;
  return <Chip k={c[0]} title={c[2]}><Icon aria-hidden />{c[1]}</Chip>;
}

export const LICENCE: Record<string, [string, string, string]> = {
  licensed: ["good", "free to use", "We can talk about this freely."],
  "licensed-with-hedge": ["warning", "careful wording", "We can talk about it, but only with the exact words written down for it."],
  held: ["critical", "not yet", "We only talk about the general idea, never about what we do, until it is graded."],
};
export const licenceWord = (l?: string) => LICENCE[l || ""]?.[1] || l || "not graded";
export function LicenceChip({ l }: { l?: string }) {
  const x = LICENCE[l || ""];
  return x ? <Chip k={x[0]} title={x[2]}>{x[1]}</Chip> : <Chip>{l || "not graded"}</Chip>;
}

export const WHERE: Record<string, string> = { proposed: "waiting for you", approved: "approved", rejected: "rejected", hold: "on hold", held: "on hold" };
export const whereWord = (p: Post) => WHERE[p.decision || p.alpha_status] || p.decision || p.alpha_status || "";
export const Where = ({ p }: { p: Post }) => {
  const w = whereWord(p);
  return <Chip k={w === "approved" ? "good" : ""}>{w}</Chip>;
};

export const Ext = ({ url, children }: { url?: string; children?: ReactNode }) =>
  url ? <a href={url} target="_blank" rel="noopener noreferrer">{children || url}</a> : null;

/** What a page means, in plain words, with its words explained behind a toggle. */
export function About({ children, words }: { children: ReactNode; words?: [string, string][] }) {
  return (
    <div className="about">
      {children}
      {words?.length ? (
        <details>
          <summary>Words on this page</summary>
          <dl>{words.map(([w, m]) => [<dt key={`t${w}`}>{w}</dt>, <dd key={`d${w}`}>{m}</dd>])}</dl>
        </details>
      ) : null}
    </div>
  );
}

export function PageHead({ page, kicker, title, meta, actions }: { page: string; kicker?: string; title: string; meta?: ReactNode; actions?: ReactNode }) {
  const m = pageMeta(page);
  return (
    <div className="phead">
      <div>
        <div className="kicker"><i><m.icon aria-hidden /></i>{kicker || m.label}</div>
        <h1>{title}</h1>
        {meta ? <div className="meta">{meta}</div> : null}
      </div>
      {actions ? <div className="actions">{actions}</div> : null}
    </div>
  );
}

export function Section({ title, n, hint, children }: { title: string; n?: ReactNode; hint?: ReactNode; children: ReactNode }) {
  return (
    <section className="section">
      <h2>{title}{n !== undefined && n !== "" ? <span className="n">{n}</span> : null}</h2>
      {hint ? <p className="hint">{hint}</p> : null}
      {children}
    </section>
  );
}

/** A title and the first lines of the text it names: a reference always shows what it says. */
export const Titled = ({ title, text }: { title: string; text?: string }) => (
  <div className="cell-text">
    <div className="cell-title">{title}</div>
    {text ? <div className="excerpt">{text}</div> : null}
  </div>
);

export function Drawer({ title, kicker, onClose, children }: { title: string; kicker?: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <>
      <div className="veil" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={title}>
        <header>
          <div style={{ flex: 1, minWidth: 0 }}>
            {kicker ? <div className="kicker">{kicker}</div> : null}
            <h3>{title}</h3>
          </div>
          <button className="close" onClick={onClose} aria-label="Close"><X size={20} /></button>
        </header>
        <div className="dbody">{children}</div>
      </aside>
    </>
  );
}

export const Field = ({ children, n, htmlFor }: { children: ReactNode; n?: string; htmlFor?: string }) => (
  <label className="field" htmlFor={htmlFor}>{children}{n ? <span className="n">{n}</span> : null}</label>
);
