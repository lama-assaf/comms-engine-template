// The story deck: the landing page. One idea per slide in the palette's solid
// colours; every slide takes a reply (one of its actions, a note, or both); the
// page adds its own closing frame, feedback on the whole story, which the next
// story and every session read.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Fragment, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, ExternalLink } from "lucide-react";
import "../deck.css";
import { useApp } from "../ctx";
import { clean, day, fmt, needs, plus, upcoming, xurl } from "../format";
import { slideLook } from "../genome";
import type { Slide, SlideItem, State } from "../types";
import { CheckChip } from "../components/ui";

const RESPOND: Record<string, string[]> = {
  cover: ["Got it", "Tell me more next time"], state: ["Looks right", "Something is off"], discoveries: ["Useful", "Not useful"],
  explore: ["Look into it", "Not now"], add: [], next: ["Looks right", "Change the plan"],
};
const KICKER: Record<string, string> = {
  state: "Where we stand", discoveries: "What we found", question: "A big question for you", explore: "Worth exploring",
  add: "Worth adding", next: "What happens next", feedback: "Before you go",
};

// ── every reference on a slide opens what it names ─────────────────────
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const TOKEN = /(#[A-Za-z][A-Za-z0-9]{2,39})|(@[A-Za-z0-9_]{1,15})\b|\b(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/g;

/** Slide text with its references made clickable: a theme opens the theme, an account opens it
 *  (or its X profile), a day like "17 Nov" opens the post planned for it when there is one. */
function Linked({ text }: { text?: string }) {
  const { S, open } = useApp();
  if (!text) return null;
  const tags = new Set((S.themes?.rows || []).map((t) => t.tag.toLowerCase()));
  const suggested = new Set((S.suggested?.rows || []).map((a) => a.handle.toLowerCase()));
  const posts = [...(S.posts?.upcoming || []), ...(S.posts?.past || [])];
  const out: ReactNode[] = [];
  let last = 0, k = 0;
  for (const m of text.matchAll(TOKEN)) {
    const at = m.index ?? 0;
    let node: ReactNode = null;
    if (m[1] && tags.has(m[1].toLowerCase())) {
      const tag = (S.themes?.rows || []).find((t) => t.tag.toLowerCase() === m[1].toLowerCase())!.tag;
      node = <button className="ref" onClick={() => open({ kind: "theme", tag })} title={`Open ${tag}`}>{m[1]}</button>;
    } else if (m[2]) {
      const h = m[2].toLowerCase();
      node = suggested.has(h)
        ? <button className="ref" onClick={() => open({ kind: "suggestion", handle: (S.suggested?.rows || []).find((a) => a.handle.toLowerCase() === h)!.handle })} title={`Open ${m[2]}`}>{m[2]}</button>
        : <a className="ref" href={xurl(m[2])} target="_blank" rel="noopener noreferrer" title={`${m[2]} on X`}>{m[2]}</a>;
    } else if (m[3]) {
      const mmdd = `-${String(MONTHS.indexOf(m[4]) + 1).padStart(2, "0")}-${m[3].padStart(2, "0")}`;
      const hits = posts.filter((p) => (p.date || "").endsWith(mmdd));
      if (hits.length === 1) node = <button className="ref" onClick={() => open({ kind: "post", id: hits[0].id })} title={hits[0].title}>{m[0]}</button>;
    }
    if (!node) continue;
    out.push(<Fragment key={k++}>{text.slice(last, at)}</Fragment>, <Fragment key={k++}>{node}</Fragment>);
    last = at + m[0].length;
  }
  out.push(<Fragment key={k++}>{text.slice(last)}</Fragment>);
  return <>{out}</>;
}

export function storySlides(S: State): Slide[] {
  const st = S.story?.latest;
  if (st?.slides?.length) return [...st.slides, { kind: "feedback" }];
  return [
    { kind: "cover", title: "No story yet", subtitle: "The engine writes one at the end of every run. To write one now, type /story in Claude Code." },
    { kind: "next", title: "Meanwhile, everything is on the dashboard", points: ["Posts, themes, accounts and what we heard are one tap away."] },
  ];
}

/** Shrink each slide's type in steps until it fits the screen; mark the deck wide from its own width. */
function fit(deck: HTMLElement) {
  deck.classList.toggle("wide", deck.clientWidth >= 900);
  deck.querySelectorAll<HTMLElement>(".slide").forEach((sl) => {
    let f = 1;
    sl.style.setProperty("--fit", "1");
    for (let k = 0; k < 7 && sl.scrollHeight > sl.clientHeight + 1; k++) { f -= 0.05; sl.style.setProperty("--fit", f.toFixed(2)); }
  });
}

export function Story() {
  const { S, slide: start } = useApp();
  const slides = storySlides(S);
  const deck = useRef<HTMLDivElement>(null);
  const [at, setAt] = useState(Math.min(start, slides.length - 1));
  const [ink, setInk] = useState("#ffffff");

  const toSlide = useCallback((i: number, smooth = true) => {
    const d = deck.current; if (!d) return;
    i = Math.max(0, Math.min(i, slides.length - 1));
    d.scrollTo({ left: i * d.clientWidth, behavior: smooth ? "smooth" : "auto" });
  }, [slides.length]);

  useLayoutEffect(() => {
    const d = deck.current; if (!d) return;
    fit(d);
    d.scrollLeft = at * d.clientWidth;
    document.fonts?.ready?.then(() => fit(d));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [S]);

  useEffect(() => {
    const d = deck.current; if (!d) return;
    let raf = 0, t: ReturnType<typeof setTimeout>;
    const mark = () => { const i = Math.round(d.scrollLeft / Math.max(d.clientWidth, 1)); setAt(i); const sl = d.children[i] as HTMLElement | undefined; if (sl) setInk(getComputedStyle(sl).color); };
    const onScroll = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(mark); clearTimeout(t); t = setTimeout(mark, 120); };
    d.addEventListener("scroll", onScroll, { passive: true });
    d.addEventListener("scrollend", mark);
    mark();
    let rt: ReturnType<typeof setTimeout>;
    const onResize = () => { clearTimeout(rt); rt = setTimeout(() => { const i = Math.round(d.scrollLeft / Math.max(d.clientWidth, 1)); fit(d); d.scrollLeft = i * d.clientWidth; }, 80); };
    window.addEventListener("resize", onResize);
    const onKey = (e: KeyboardEvent) => {
      if (/INPUT|TEXTAREA|SELECT/.test((e.target as HTMLElement).tagName) || document.querySelector(".drawer")) return;
      const i = Math.round(d.scrollLeft / Math.max(d.clientWidth, 1));
      if (e.key === "ArrowRight" || e.key === "PageDown") { e.preventDefault(); toSlide(i + 1); }
      if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); toSlide(i - 1); }
    };
    document.addEventListener("keydown", onKey);
    return () => { d.removeEventListener("scroll", onScroll); d.removeEventListener("scrollend", mark); window.removeEventListener("resize", onResize); document.removeEventListener("keydown", onKey); };
  }, [toSlide]);

  const advance = () => setTimeout(() => toSlide(at + 1), 420);

  return (
    <div className="story">
      <div className="storybar" style={{ color: ink }}>
        <div className="segs">{slides.map((_, i) => <button key={i} className={i === at ? "on" : i < at ? "done" : ""} aria-label={`Slide ${i + 1}`} onClick={() => toSlide(i)} />)}</div>
        <div className="row"><span>Story · {at + 1} of {slides.length}</span></div>
      </div>
      <button className="arrow prev" aria-label="Previous slide" onClick={() => toSlide(at - 1)}><ChevronLeft /></button>
      <button className="arrow next" aria-label="Next slide" onClick={() => toSlide(at + 1)}><ChevronRight /></button>
      <div className="deck" ref={deck}>
        {slides.map((s, i) => <SlideView key={`${S.story?.latest?.run_id}-${i}`} s={s} i={i} total={slides.length} advance={advance} />)}
      </div>
    </div>
  );
}

function SlideView({ s, i, total, advance }: { s: Slide; i: number; total: number; advance: () => void }) {
  const { S } = useApp();
  const g = S.genome;
  const kicker = KICKER[s.kind] || "";
  const same = (t?: string) => Boolean(t && kicker && t.trim().toLowerCase() === kicker.toLowerCase());
  const Kick = () => (same(s.title) ? null : <div className="kicker">{kicker}</div>);
  const points = s.points?.length ? <ul className="points">{s.points.map((x, k) => <li key={k}><Linked text={x} /></li>)}</ul> : null;
  const items = s.items?.length ? <ol className="items">{s.items.map((o, j) => <Item key={j} s={s} i={i} o={typeof o === "string" ? { text: o } : o} j={j} />)}</ol> : null;
  const look = slideLook(s.kind);
  const dark = (look as Record<string, string>)["--s-ink"] === "#ffffff";

  let body = null, reply = null;
  if (s.kind === "cover") {
    const logo = dark ? g?.logo?.on_dark : g?.logo?.on_light;
    body = <>
      {logo ? <div className="logo" dangerouslySetInnerHTML={{ __html: logo }} /> : <div className="logo"><div className="word">{g?.name || S.stream}</div></div>}
      <div className="kicker">The story of {day(S.story?.latest?.date || S.today)}</div>
      <h2 className="big"><Linked text={s.title} /></h2>
      {s.subtitle ? <div className="sub"><Linked text={s.subtitle} /></div> : null}
      {S.story?.latest ? <div className="swipehint">{matchMedia("(hover: hover)").matches ? "Use → or the arrows to read on" : "Swipe to read on"} · answer any slide as you go</div> : null}
    </>;
    reply = S.story?.latest ? <Respond s={s} i={i} advance={advance} /> : null;
  } else if (s.kind === "state") {
    body = <><div className="kicker">{kicker}</div>{s.figure ? <><div className="figure">{s.figure.value}</div><div className="figure-label">{s.figure.label}</div></> : null}<h2 className="big"><Linked text={s.title} /></h2>{points}</>;
    reply = <Respond s={s} i={i} advance={advance} />;
  } else if (s.kind === "question") {
    body = <><div className="kicker">{kicker}</div><h2 className="big"><Linked text={s.question} /></h2>{s.why ? <div className="sub"><Linked text={s.why} /></div> : null}</>;
    reply = <Answer s={s} advance={advance} />;
  } else if (s.kind === "feedback") {
    body = <><div className="kicker">{kicker}</div><h2 className="big">How was this story?</h2></>;
    reply = <Feedback />;
  } else {
    body = <><Kick /><h2 className="big"><Linked text={s.title} /></h2>{points}{items}</>;
    reply = <Respond s={s} i={i} advance={advance} />;
  }
  const panel = <TopPanel s={s} i={i} />;
  const two = hasPanel(S, s) || ["question", "feedback"].includes(s.kind);
  return (
    <section className={`slide ${s.kind}`} style={look} aria-label={`Slide ${i + 1} of ${total}`}>
      <div className={`frame${two ? " two" : ""}`}><div className="sbody">{body}</div><div className="side">{panel}{reply}</div></div>
    </section>
  );
}

// ── the person's turn ──────────────────────────────────────────────────

function useRespond() {
  const { S, act } = useApp();
  return (slide: number, action: string, text: string, item: number | null = null) =>
    act("/api/respond", { run_id: S.story?.latest?.run_id, slide, action, text, item, base: S.story?.responses_base }, "Noted. The next story reads it.");
}
const responseOf = (S: State, i: number, item: number | null = null) => (S.story?.responses || []).find((r) => r.slide === i && (r.item ?? null) === item);

function Respond({ s, i, advance }: { s: Slide; i: number; advance: () => void }) {
  const { S, toast } = useApp();
  const respond = useRespond();
  const [note, setNote] = useState("");
  const [redo, setRedo] = useState(false);
  const r = responseOf(S, i);
  if (r && !redo) return <div className="respond"><div className="done"><span>✓ {r.action || "Noted"}{r.text ? ` · “${r.text}”` : ""}</span><button onClick={() => setRedo(true)}>change</button></div></div>;
  const acts = s.actions?.length ? s.actions : RESPOND[s.kind] || [];
  const send = async (action: string) => {
    if (!action && !note.trim()) { toast("Write a few words first, or tap one of the buttons"); return; }
    if (await respond(i, action, note)) { setRedo(false); setNote(""); advance(); }
  };
  return (
    <div className="respond" data-label="Your reply">
      {acts.length ? <div className="acts">{acts.map((a) => <button key={a} onClick={() => send(a)}>{a}</button>)}</div> : null}
      <div className="note">
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={acts.length ? "Or add a note" : "Add a note"} aria-label="A note on this slide" enterKeyHint="send"
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); send(""); } }} />
        <button onClick={() => send("")}>Send</button>
      </div>
    </div>
  );
}

function Answer({ s, advance }: { s: Slide; advance: () => void }) {
  const { S, act } = useApp();
  const [text, setText] = useState("");
  const [redo, setRedo] = useState(false);
  const q = (S.story?.questions || []).find((x) => x.id === s.id);
  if (!s.id) return null;
  if (q && q.status === "answered" && !redo) return <div className="answered"><span>✓ Your answer: {q.answer}</span><button onClick={() => setRedo(true)}>change</button></div>;
  const save = async () => { if (await act("/api/answer", { id: s.id, answer: text, base: S.story?.questions_base }, "Saved. The next story reads your answer.")) { setRedo(false); advance(); } };
  return (
    <div className="answer" data-label="Your answer">
      {s.options?.length ? <div className="opts">{s.options.map((o) => <button key={o} className={text === o ? "on" : ""} onClick={() => setText(o)}>{o}</button>)}</div> : null}
      <textarea className="ans" value={text} onChange={(e) => setText(e.target.value)} placeholder={s.options?.length ? "Pick one, or say it in your words" : "Your answer, in a few words"} />
      <button className="save" onClick={save}>Save my answer</button>
    </div>
  );
}

function Feedback() {
  const { S, act, go } = useApp();
  const [rating, setRating] = useState(""), [next, setNext] = useState(""), [remember, setRemember] = useState("");
  const [redo, setRedo] = useState(false);
  const F = S.story?.feedback;
  if (F && !redo) return <>
    <div className="answered"><span>✓ Thank you. {F.rating ? `You found it ${F.rating}. ` : ""}The storyteller reads this next time{F.remember ? ", and every session now starts with what you asked us to remember" : ""}.</span><button onClick={() => setRedo(true)}>change it</button></div>
    <button className="cta" onClick={() => go("today")}>Open the dashboard →</button>
  </>;
  const send = async () => {
    if (await act("/api/feedback", { run_id: S.story?.latest?.run_id, rating, next, remember, base: S.story?.feedback_base }, "Thank you. The next story reads this.")) setRedo(false);
  };
  return (
    <div className="answer" data-label="Your feedback">
      <div className="rates">{(S.story?.ratings || []).map((x) => <button key={x} className={rating === x ? "on" : ""} onClick={() => setRating(x)}>{x[0].toUpperCase() + x.slice(1)}</button>)}</div>
      <label className="fl" htmlFor="fb-next">What should the next story cover?</label>
      <textarea className="fb" id="fb-next" value={next} onChange={(e) => setNext(e.target.value)} placeholder="A topic, a question, a number you want to see" />
      <label className="fl" htmlFor="fb-rem">Anything we should always remember?</label>
      <textarea className="fb" id="fb-rem" value={remember} onChange={(e) => setRemember(e.target.value)} placeholder="A rule, a preference, a fact: every future session sees it" />
      <button className="save" onClick={send}>Send</button>
    </div>
  );
}

function Item({ s, i, o, j }: { s: Slide; i: number; o: SlideItem; j: number }) {
  const { S, act, open, go } = useApp();
  const respond = useRespond();
  const [redo, setRedo] = useState(false);
  const f = o.source ? (S.listening?.findings || []).find((x) => x.id === o.source) : undefined;
  const ev = f?.evidence?.[0];
  const quote = ev?.quote ? clean(ev.quote) : "";
  const accountList = o.kind === "account" && !o.handle;
  let acts = null;
  if (s.kind === "add") {
    const r = responseOf(S, i, j);
    const label = o.handle ? `Watch ${o.handle}` : o.kind === "theme" && o.tag ? `Add ${o.tag}` : "Add it";
    const add = async () => {
      if (o.handle) { if (await act("/api/watch", { handle: o.handle, themes: [], note: o.why || "", from: "story", base: S.accounts?.watch_base }, `${o.handle} is now watched`)) respond(i, `Watched ${o.handle}`, "", j); return; }
      if (o.kind === "theme" && o.tag) { if (await respond(i, `Adding ${o.tag}`, "", j)) open({ kind: "newTheme", tag: o.tag, what: o.text }); return; }
      respond(i, "Add it", "", j);
    };
    acts = r && !redo ? <div className="item-done">✓ {r.action} <button style={{ background: "none", border: 0, color: "inherit", textDecoration: "underline", padding: 0 }} onClick={() => setRedo(true)}>change</button></div>
      : accountList
        // "watch one of the suggested accounts": the accounts themselves are the list below, each one to open, watch or dismiss
        ? <div className="item-acts"><button className="go" onClick={() => go("suggestions")}>See all {S.suggested?.rows.length || ""} suggestions</button><button onClick={async () => { if (await respond(i, "Skip", "", j)) setRedo(false); }}>Not now</button></div>
        : <div className="item-acts"><button className="go" onClick={async () => { await add(); setRedo(false); }}>{label}</button><button onClick={async () => { if (await respond(i, "Skip", "", j)) setRedo(false); }}>Skip</button></div>;
  }
  return (
    <li><div>
      {o.kind ? <span className="tag">{o.kind}</span> : null}<Linked text={o.text} />
      {o.handle ? <> <button className="ref" onClick={() => open({ kind: "suggestion", handle: o.handle! })}>{o.handle}</button></> : null}
      {o.why ? <span className="why"><Linked text={o.why} /></span> : null}
      {quote ? (ev?.url
        ? <a className="quote2 ref-quote" href={ev.url} target="_blank" rel="noopener noreferrer" title={`Open the post: ${quote}`}>“{quote}”</a>
        : <span className="quote2" title={quote}>“{quote}”</span>) : null}
      {o.source ? <span className="src">{f
        ? <><button className="ref" onClick={() => open({ kind: "finding", id: f.id })} title="Open what we heard">{o.source}</button> · <button className="ref" onClick={() => open({ kind: "theme", tag: f.theme })}>{f.theme}</button></>
        : o.source}</span> : null}
      {accountList && s.kind !== "add" ? <span className="src"><button className="ref" onClick={() => go("suggestions")}>See the suggested accounts</button></span> : null}
      {acts}
    </div></li>
  );
}

// ── the engine's own top three under the storyteller's words ───────────

function hasPanel(S: State, s: Slide) {
  if (s.kind === "cover") return Boolean(S.story?.latest);
  if (s.kind === "state") return upcoming(S).length > 0;
  if (s.kind === "discoveries") return !(s.items || []).length && (S.listening?.findings || []).length > 0;
  if (s.kind === "explore") return (S.listening?.warmest || []).length > 0;
  if (s.kind === "add") return (s.items || []).some((o) => typeof o === "object" && o.kind === "account" && !o.handle) && (S.suggested?.rows || []).length > 0;
  if (s.kind === "next") return needs(S).length > 0;
  return false;
}

function TopPanel({ s, i }: { s: Slide; i: number }) {
  const { S, go, act, open } = useApp();
  const respond = useRespond();
  if (!hasPanel(S, s)) return null;
  const Head = ({ t }: { t: string }) => <div className="t3h">{t}</div>;
  if (s.kind === "cover") {
    const up = upcoming(S), fortnight = up.filter((p) => (p.date || "9999") <= plus(S.today, 13)).length;
    const waiting = up.filter((p) => !p.decision && p.alpha_status === "proposed" && p.gate !== "block").length;
    return <div className="stats">
      <button className="stat" onClick={() => go("posts")}><b>{fortnight}</b>posts in 2 weeks</button>
      <button className="stat" onClick={() => go("today")}><b>{waiting}</b>waiting for you</button>
      <button className="stat" onClick={() => go("heard")}><b>{(S.listening?.findings || []).length}</b>things heard</button>
    </div>;
  }
  if (s.kind === "state") return <div className="top3"><Head t="Next up" />{upcoming(S).slice(0, 3).map((p) => (
    <button key={p.id} className="t3" onClick={() => go(`post:${p.id}`)}><span className="t3d">{day(p.date)}</span><span className="t3t">{p.title}<small>{p.theme}</small></span><CheckChip gate={p.gate} /></button>))}</div>;
  if (s.kind === "discoveries") {
    const F = [...(S.listening?.findings || [])].sort((a, b) => (Number(b.relevance) || 0) - (Number(a.relevance) || 0)).slice(0, 3);
    return <div className="top3"><Head t="Top findings" />{F.map((f) => <button key={f.id} className="t3" onClick={() => open({ kind: "finding", id: f.id })}><span className="t3d">{f.theme}</span><span className="t3t">{f.finding}</span><span /></button>)}</div>;
  }
  if (s.kind === "explore") return <div className="top3"><Head t="Loudest themes this pass" />{(S.listening?.warmest || []).slice(0, 3).map((w) => (
    <button key={w.theme} className="t3" onClick={() => open({ kind: "theme", tag: w.theme })}><span className="t3d">{String(w.relevance)}</span><span className="t3t">{w.theme}<small>{w.count} posts · {clean(w.why).slice(0, 110)}</small></span><span /></button>))}</div>;
  if (s.kind === "add") {
    const j = (s.items || []).findIndex((o) => typeof o === "object" && o.kind === "account" && !o.handle);
    return <div className="top3"><Head t="Top suggested accounts" />{(S.suggested?.rows || []).slice(0, 3).map((a) => (
      <div key={a.handle} className="t3 acct">
        <button className="t3t t3open" onClick={() => open({ kind: "suggestion", handle: a.handle })} title={`Open ${a.handle}: the posts that put it here`}>
          <b>{a.handle}</b> · seen {a.hits}× · {fmt(a.followers)} followers<small>{a.themes.join(" ")} · {clean(a.samples[0]?.text).slice(0, 100)}</small>
        </button>
        <span className="acts2">
          <button className="go" onClick={async () => { if (await act("/api/watch", { handle: a.handle, themes: a.themes, from: "story", base: S.accounts?.watch_base }, `${a.handle} is now watched`)) respond(i, `Watched ${a.handle}`, "", j); }}>Watch</button>
          <button onClick={() => act("/api/dismiss", { handle: a.handle, base: S.accounts?.watch_base }, `${a.handle} dismissed`)}>Dismiss</button>
          <a className="xlink" href={xurl(a.handle)} target="_blank" rel="noopener noreferrer" aria-label={`${a.handle} on X`} title={`${a.handle} on X`}><ExternalLink /></a>
        </span>
      </div>))}</div>;
  }
  if (s.kind === "next") return <div className="top3"><Head t="Waiting for you" />{needs(S).slice(0, 3).map((n, k) => (
    <button key={k} className="t3" onClick={() => go(n.go)}><span className="t3d">{n.d ? day(n.d) : "now"}</span><span className="t3t">{n.t}</span><span /></button>))}</div>;
  return null;
}

