// One menu button, bottom-left: on the story, and on the dashboard below the
// sidebar width (styles.css hides it where the sidebar shows). It opens on hover (and on a
// tap or the keyboard), lists every page, and never moves when you switch
// between the story and the dashboard.
import { useEffect, useRef, useState } from "react";
import { LayoutGrid, SquareArrowOutUpRight, X } from "lucide-react";
import { DESK } from "../api";
import { markStyle, pageColor, swatch } from "../genome";
import { PAGES } from "../nav";

interface MenuProps { page: string; counts: Record<string, number>; hot: Set<string>; go: (key: string) => void; className: string; label: string }

// The one page menu: group headings, a page per row with its count (red when it
// needs you) and the desk link. The dock opens it as a pop-over; on a wide
// dashboard the left sidebar shows it permanently.
export function PageMenu({ page, counts, hot, go, className, label }: MenuProps) {
  return (
    <nav className={`pagemenu ${className}`} aria-label={label}>
      {PAGES.map((p) => {
        const c = pageColor(p.key), on = p.key === page;
        return [
          p.group ? <div className="group" key={`g${p.key}`}>{p.group}</div> : null,
          <button key={p.key} className="item" aria-current={on ? "page" : undefined} onClick={() => go(p.key)} style={on ? swatch(c) : undefined}>
            <span className="ico" style={on ? markStyle(c) : swatch(c)}><p.icon aria-hidden /></span>
            {p.label}
            {counts[p.key] ? <span className={`n${hot.has(p.key) && !on ? " hot" : ""}`} style={on ? { color: "inherit" } : undefined}>{counts[p.key]}</span> : null}
          </button>,
        ];
      })}
      <a className="item desk" href={DESK} target="_blank" rel="noopener noreferrer">
        <span className="ico" style={{ background: "var(--grey)" }}><SquareArrowOutUpRight aria-hidden /></span>The desk
      </a>
    </nav>
  );
}

interface Props { page: string; counts: Record<string, number>; hot: Set<string>; go: (key: string) => void }

export function NavDock({ page, counts, hot, go }: Props) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const canHover = () => window.matchMedia("(hover: hover)").matches;
  const cancel = () => window.clearTimeout(timer.current);
  const show = () => { cancel(); setOpen(true); };
  const later = () => { cancel(); timer.current = window.setTimeout(() => setOpen(false), 220); };

  useEffect(() => {
    if (!open) return;
    const off = (e: PointerEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", off);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", off); document.removeEventListener("keydown", esc); };
  }, [open]);
  useEffect(() => cancel, []);

  const pick = (key: string) => { setOpen(false); go(key); };

  return (
    <div className="dock" ref={box}
      onMouseEnter={() => { if (canHover()) show(); }} onMouseLeave={() => { if (canHover()) later(); }}
      onFocus={show} onBlur={(e) => { if (!box.current?.contains(e.relatedTarget as Node)) later(); }}>
      {open ? (
        <PageMenu className="dock-menu" label="All pages" page={page} counts={counts} hot={hot} go={pick} />
      ) : null}
      <button className="dock-btn" aria-label="Menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? <X aria-hidden /> : <LayoutGrid aria-hidden />}
      </button>
    </div>
  );
}
