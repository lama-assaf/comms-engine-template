import { useEffect, useRef, useState } from "react";
import { SquareArrowOutUpRight } from "lucide-react";
import { DESK } from "../api";
import { useApp, type DrawerSpec } from "../ctx";
import { day, fmt, xurl } from "../format";
import { About, Chip, CheckChip, Drawer, Ext, Field, LicenceChip, Theme, Where } from "../components/ui";
import { WatchButtons } from "../pages/Suggestions";
import { ApprovePost } from "../components/Approval";
import { PostCalendar } from "../pages/Posts";

function Keywords({ words, set }: { words: string[]; set: (w: string[]) => void }) {
  const [v, setV] = useState("");
  const take = () => { const w = v.trim().toLowerCase(); if (w && !words.includes(w)) set([...words, w]); setV(""); };
  return (
    <div className="tags">
      {words.map((k, i) => <span key={k} className="chip">{k}<button aria-label={`Remove ${k}`} onClick={() => set(words.filter((_, j) => j !== i))}>×</button></span>)}
      <input value={v} placeholder="add a keyword" aria-label="Add a keyword" onChange={(e) => setV(e.target.value)} onBlur={take}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); take(); } }} />
    </div>
  );
}
const withPending = (words: string[], el: HTMLInputElement | null) => {
  const w = (el?.value || "").trim().toLowerCase();
  return w && !words.includes(w) ? [...words, w] : words;
};
const SEARCH_HELP = "Use quotes for exact phrases, OR between choices, lang:en for English and -filter:replies to skip replies.";

// What we may say about a theme: a person allows it, or holds it again, with the reason that lets them.
const GRADES: { licence: string; word: string; means: string }[] = [
  { licence: "held", word: "Not yet", means: "The general idea only: nothing about what we do, no partner, no date." },
  { licence: "licensed-with-hedge", word: "Careful wording", means: "We may talk about it, but only with the exact words written down for it." },
  { licence: "licensed", word: "Free to use", means: "We may argue it freely, in our voice." },
];
const RANK: Record<string, number> = { held: 0, "licensed-with-hedge": 1, licensed: 2 };

function GradeTheme({ tag, open: startOpen }: { tag: string; open?: boolean }) {
  const { S, act } = useApp();
  const t = (S.themes?.rows || []).find((r) => r.tag === tag)!;
  const [pick, setPick] = useState(startOpen && t.licence === "held" ? "licensed-with-hedge" : t.licence);
  const [why, setWhy] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (startOpen) ref.current?.scrollIntoView({ block: "start" }); }, [startOpen]);
  const changed = pick !== t.licence, looser = (RANK[pick] ?? 0) > (RANK[t.licence] ?? 0);
  const save = async () => {
    if (await act("/api/grade", { tag, licence: pick, basis: why, md_base: S.themes!.md_base },
      `${tag}: ${GRADES.find((g) => g.licence === pick)?.word.toLowerCase()}`)) setWhy("");
  };
  return (
    <div className="grade" ref={ref}>
      <Field>What we may say about it</Field>
      <div className="grade-now"><LicenceChip l={t.licence} /></div>
      {t.plain ? (
        <dl className="plain">
          <dt>What we may say</dt><dd>{t.plain.now}</dd>
          <dt>What we never say</dt><dd>{t.plain.not}</dd>
          <dt>Why</dt><dd>{t.plain.why}</dd>
          {t.plain.next ? <><dt>What would move it up</dt><dd>{t.plain.next}</dd></> : null}
        </dl>
      ) : null}
      {t.plain && !t.plain.current ? <div className="plain-stale">The rule changed after this was written; the next run rewrites it. The rule itself is below.</div> : null}
      {!t.plain ? <div className="plain-stale">No plain explanation yet: the next run writes one. Until then, the rule itself:</div> : null}
      {t.licence_basis ? (
        <details className="rule" open={!t.plain || !t.plain.current}>
          <summary>The exact rule the writers follow</summary>
          <p>{t.licence_basis}</p>
        </details>
      ) : null}
      <div className="grade-opts" role="radiogroup" aria-label={`What we may say about ${tag}`}>
        {GRADES.map((g) => (
          <button key={g.licence} role="radio" aria-checked={pick === g.licence} className={`grade-opt${pick === g.licence ? " on" : ""}`} onClick={() => setPick(g.licence)}>
            <span className="w">{g.word}{g.licence === t.licence ? <em> · now</em> : null}</span><span className="m">{g.means}</span>
          </button>
        ))}
      </div>
      {changed ? <>
        <Field htmlFor="why">{looser ? "Why we may: what we can now prove, and where it is written down" : "Why we hold it"}</Field>
        <textarea id="why" className="textarea" style={{ fontFamily: "inherit", fontSize: 15 }} maxLength={400} value={why} onChange={(e) => setWhy(e.target.value)}
          placeholder={pick === "licensed-with-hedge" ? 'The exact words we may use, in quotes, and why. For example: Only with "is in the process of", because the application is in but not approved.' : looser ? "What we can now prove, and where it is written down." : "What changed, or what we cannot prove yet."} />
        {looser ? <div className="grade-warn">Allowing {tag} lets its posts say what we do under it. The check still stops any claim that is not on the approved list, so be sure of what we can prove first. The old reason is kept.</div> : null}
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 14, flexWrap: "wrap" }}>
          <button className="btn primary" disabled={why.trim().length < 15} onClick={save}>{pick === "held" ? "Hold it" : `Allow it: ${GRADES.find((g) => g.licence === pick)?.word.toLowerCase()}`}</button>
          <span className="small muted">saved to our theme list with today's date</span>
        </div>
      </> : null}
    </div>
  );
}

function EditTheme({ tag, grade }: { tag: string; grade?: boolean }) {
  const { S, act, close } = useApp();
  const t = (S.themes?.rows || []).find((r) => r.tag === tag);
  const [q, setQ] = useState(t?.x_search || "");
  const [kw, setKw] = useState<string[]>(t?.keywords || []);
  if (!t || !S.themes) return null;
  const max = S.themes.x_query_max;
  return (
    <Drawer title={tag} kicker="Theme" onClose={close}>
      <div className="chips"><LicenceChip l={t.licence} /><Chip>{t.upcoming.length} posts planned</Chip><Chip>{t.findings.length} heard</Chip></div>
      <p style={{ fontSize: 16 }}>{t.what}</p>
      {t.different ? <p className="small muted">Why it is ours: {t.different}</p> : null}
      <GradeTheme key={`${tag}-${t.licence}`} tag={tag} open={grade} />
      <Field htmlFor="tq" n={`${q.length}/${max}`}>What the listener searches on X</Field>
      <textarea id="tq" className="textarea" maxLength={max} value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="help">{SEARCH_HELP}</div>
      <Field>Keywords that make a post count as on-topic · type one and press Enter</Field>
      <Keywords words={kw} set={setKw} />
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 20 }}>
        <button className="btn primary" onClick={() => act("/api/terms", { tag, x_search: q, keywords: withPending(kw, document.querySelector(".tags input")), base: S.themes!.terms_base }, `${tag}: saved`)}>Save</button>
        <span className="small muted">the next listening run uses it</span>
      </div>
      {t.signal?.note ? <><Field>What the last listening run said</Field><div className="small">{t.signal.note}</div></> : null}
    </Drawer>
  );
}

function NewTheme({ tag: tag0 = "", what: what0 = "" }: { tag?: string; what?: string }) {
  const { S, act, close, go, open } = useApp();
  const [tag, setTag] = useState(tag0), [what, setWhat] = useState(what0), [diff, setDiff] = useState(""), [q, setQ] = useState(""), [kw, setKw] = useState<string[]>([]);
  if (!S.themes) return null;
  const max = S.themes.x_query_max;
  const create = async () => {
    const t = tag.trim().startsWith("#") ? tag.trim() : `#${tag.trim()}`;
    const ok = await act("/api/theme", { tag: t, what, different: diff, x_search: q, keywords: withPending(kw, document.querySelector(".tags input")),
      md_base: S.themes!.md_base, terms_base: S.themes!.terms_base }, `${t} added as a theme`);
    if (ok) { go("themes"); open({ kind: "theme", tag: t }); }
  };
  return (
    <Drawer title="Add a theme" kicker="New theme" onClose={close}>
      <About><p>A theme is a topic we want to be known for. It starts as <b>not yet</b>: posts under it talk about the general idea only, never about what we do, until someone checks what we can prove and allows it.</p></About>
      <Field htmlFor="nt">Hashtag</Field><input id="nt" className="input" placeholder="#TokenisedDeposits" value={tag} onChange={(e) => setTag(e.target.value)} />
      <Field htmlFor="nw">What it is, in one sentence</Field><input id="nw" className="input" maxLength={220} placeholder="Bank deposits that move on a blockchain without leaving the bank." value={what} onChange={(e) => setWhat(e.target.value)} />
      <Field htmlFor="nd">Why it is ours (optional)</Field><input id="nd" className="input" maxLength={300} placeholder="What we can say about it that others cannot." value={diff} onChange={(e) => setDiff(e.target.value)} />
      <Field htmlFor="tq" n={`${q.length}/${max}`}>What the listener searches on X</Field>
      <textarea id="tq" className="textarea" maxLength={max} placeholder={'("tokenised deposits" OR "deposit token") lang:en -filter:replies'} value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="help">{SEARCH_HELP}</div>
      <Field>Keywords that make a post count as on-topic · type one and press Enter</Field>
      <Keywords words={kw} set={setKw} />
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 20, flexWrap: "wrap" }}>
        <button className="btn primary" onClick={create}>Add the theme</button>
        <span className="small muted">the listener starts on it at its next run (one more X search, a few cents)</span>
      </div>
    </Drawer>
  );
}

function PostDrawer({ id }: { id: string }) {
  const { S, close } = useApp();
  const p = [...(S.posts?.upcoming || []), ...(S.posts?.past || [])].find((x) => x.id === id);
  if (!p) return null;
  const m = p.motion;
  return (
    <Drawer title={p.title} kicker={day(p.date)} onClose={close}>
      <div className="chips"><Theme tag={p.theme} /><CheckChip gate={p.gate} /><Where p={p} /></div>
      <ApprovePost p={p} />
      <PostCalendar p={p} />
      <div style={{ marginTop: 16 }}>
        <a className="btn" href={`${DESK}/item/${encodeURIComponent(p.id)}`} target="_blank" rel="noopener noreferrer"><SquareArrowOutUpRight aria-hidden />Hold, send back or edit it on the desk</a>
      </div>
      {p.note_for_alpha ? <><Field>What the check says</Field><div className="body">{p.note_for_alpha}</div></> : null}
      {p.teaser_x ? <><Field>The X version</Field><div className="body">{p.teaser_x}</div></> : null}
      {p.teaser_linkedin ? <><Field>The LinkedIn version</Field><div className="body">{p.teaser_linkedin}</div></> : null}
      <Field>The full blog post</Field>{p.post ? <div className="body long">{p.post}</div> : <div className="small muted">Not written yet.</div>}
      <Field>Video</Field>
      {m.poster ? <div className="media"><video controls preload="metadata" poster={`/media/${m.poster}`} src={m.video ? `/media/${m.video}` : undefined} /></div>
        : <div className="small muted">{m.storyboard ? "Planned, not made on this computer yet." : `Not made yet: the next run makes it, or type /motion ${p.id}`}</div>}
      {p.hypothesis ? <><Field>What this post tests · expected result: {p.predicted}</Field><div className="small">{p.hypothesis}</div></> : null}
      {p.cta ? <><Field>Link</Field><div className="small"><Ext url={p.cta} /></div></> : null}
    </Drawer>
  );
}

function SuggestionDrawer({ handle }: { handle: string }) {
  const { S, close } = useApp();
  const r = (S.suggested?.rows || []).find((x) => x.handle === handle);
  if (!r) return null;
  return (
    <Drawer title={r.handle} kicker="Suggested account" onClose={close}>
      <p className="small muted">{r.name} · {fmt(r.followers)} followers · seen {r.hits}×</p>
      <div className="chips">{r.themes.map((t) => <Theme key={t} tag={t} />)}</div>
      <Field>The posts that put it here</Field>
      {r.samples.map((s, i) => <div key={i} className="body" style={{ marginBottom: 8 }}>{s.text}<div className="chips" style={{ marginTop: 8 }}><Theme tag={s.theme} /><Ext url={s.url}>open ↗</Ext></div></div>)}
      <div style={{ display: "flex", gap: 10, marginTop: 16, alignItems: "center" }}><WatchButtons s={r} after={close} /><Ext url={xurl(r.handle)}>Profile ↗</Ext></div>
    </Drawer>
  );
}

/** A drawer's headline: the first sentence, at most about 120 characters; the whole text goes below it. */
const headline = (t: string) => {
  const first = (t.match(/^.+?[.!?](?=\s|$)/) || [t])[0];
  return first.length <= 130 ? first : first.slice(0, 120).replace(/\s+\S*$/, "") + "…";
};

function FindingDrawer({ id }: { id: string }) {
  const { S, close } = useApp();
  const f = (S.listening?.findings || []).find((x) => x.id === id);
  if (!f) return null;
  return (
    <Drawer title={headline(f.finding)} kicker={`${f.theme} · ${f.id} · what we heard`} onClose={close}>
      {headline(f.finding) !== f.finding ? <p style={{ fontSize: 16, lineHeight: 1.62 }}>{f.finding}</p> : null}
      {(f.evidence || []).length ? <><Field>The posts it is based on</Field>{f.evidence.map((e, i) => (
        <div key={i} className="body" style={{ marginBottom: 8 }}>
          <div className="small" style={{ fontWeight: 700 }}>{e.title}</div>
          {e.quote ? <div className="quote">“{e.quote}”</div> : null}
          {e.text && e.text !== e.quote ? <div className="small">{e.text}</div> : null}
          <div className="small" style={{ marginTop: 6 }}><Ext url={e.url}>open ↗</Ext></div>
        </div>))}</> : null}
      <Field>Could it become a post?</Field><div className="small"><b>{f.content}</b> {f.content_note}</div>
      <Field>Is it worth a reply?</Field><div className="small"><b>{f.conversation}</b> {f.conversation_note}</div>
    </Drawer>
  );
}

export function Drawers({ spec }: { spec: DrawerSpec }) {
  const { close } = useApp();
  switch (spec.kind) {
    case "post": return <PostDrawer id={spec.id} />;
    case "theme": return <EditTheme key={spec.tag} tag={spec.tag} grade={spec.grade} />;
    case "newTheme": return <NewTheme tag={spec.tag} what={spec.what} />;
    case "suggestion": return <SuggestionDrawer handle={spec.handle} />;
    case "finding": return <FindingDrawer id={spec.id} />;
    case "text": return (
      <Drawer title={spec.title} kicker={spec.kicker} onClose={close}>
        <div className="chips">{(spec.chips || []).filter(Boolean).map((c, i) => <Chip key={i}>{c}</Chip>)}{spec.url ? <Ext url={spec.url}>open the post ↗</Ext> : null}</div>
        <Field>The post</Field>{spec.text ? <div className="body long">{spec.text}</div> : <div className="small muted">No text was kept for this one.</div>}
      </Drawer>
    );
  }
}
