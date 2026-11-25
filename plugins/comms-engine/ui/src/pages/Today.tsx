import type { ReactNode } from "react";
import { CalendarDays, Clapperboard, Ear, Hourglass, MessageSquare, ShieldAlert, ShieldCheck, Users } from "lucide-react";
import { useApp } from "../ctx";
import { clean, day, excerpt, greeting, iso, narrowDay, needs, plus, upcoming } from "../format";
import { blockColor, markStyle, statusColor, swatch } from "../genome";
import { About, CheckChip, Chip, PageHead, Section, Theme } from "../components/ui";
import { ThemeTable } from "./Themes";

// A tile is a pastel tone of its colour with a solid mark for its icon; the hero is the brand's strong anchor.
function Tile({ label, value, note, go, color, icon, size = "", children }: { label: string; value: ReactNode; note: ReactNode; go: string; color: string; icon: ReactNode; size?: "" | "hero" | "wide"; children?: ReactNode }) {
  const { go: nav } = useApp();
  const look = size === "hero" ? { background: "var(--primary)", color: "var(--on-primary)" } : swatch(color);
  const mark = size === "hero" ? { background: "rgba(255,255,255,.16)", color: "var(--on-primary)" } : markStyle(color);
  return (
    <button className={`tile ${size}`} style={look} onClick={() => nav(go)}>
      <div className="top"><span className="label">{label}</span><span className="ic" style={mark}>{icon}</span></div>
      <div className="value">{value}</div>
      {children}
      <div className="note">{note}</div>
    </button>
  );
}

export function Today() {
  const { S, go } = useApp();
  const up = upcoming(S), today = S.today;
  const fortnight = up.filter((p) => (p.date || "9999") <= plus(today, 13));
  const waiting = up.filter((p) => !p.decision && p.alpha_status === "proposed" && p.gate !== "block");
  const thisWeek = waiting.filter((p) => (p.date || "9999") <= plus(today, 6)).length;
  const blocked = up.filter((p) => p.gate === "block").length;
  const cards = up.filter((p) => p.motion.poster).length;
  const owed = (S.engine?.motion_owed || []).filter((o) => o.action === "storyboard").length;
  const warm = (S.listening?.warmest || [])[0], next = fortnight[0], N = needs(S);
  const agenda = [
    ...fortnight.map((p) => ({ date: p.date || "", post: p, row: null })),
    ...(S.calendar?.ahead || []).filter((r) => !r.engine && iso(r.date) <= plus(today, 13)).map((r) => ({ date: iso(r.date), post: null, row: r })),
  ].sort((a, b) => a.date.localeCompare(b.date));
  const Q = S.story?.questions || [], open = Q.filter((q) => q.status === "open"), done = Q.filter((q) => q.status === "answered").slice(-5).reverse();

  return (
    <>
      <PageHead page="today" title={`${greeting()}.`} meta={<>Here is where things stand on {day(today)}.</>} />
      <About words={[["Post", "A blog article the system wrote, with a short X version and a LinkedIn version."],
        ["The check", "An automatic reading of every post that stops anything we cannot prove yet."],
        ["The desk", "The separate app where you approve, hold or edit posts."], ["Motion card", "A short video of a post's own lines, for X and LinkedIn."]]}>
        <p>This page is the quick look at everything. The big dark block counts the blog posts planned for the next two weeks; each little bar is one day (white: a post, yellow: a post with small fixes, red: a post the check stopped).</p>
        <p><b>Needs you</b> lists the things only a person can do. Click any block or line to go straight to it.</p>
      </About>

      <div className="kpis">
        <Tile size="hero" label="Posts in the next 14 days" value={fortnight.length} color={blockColor(0)} go="posts" icon={<CalendarDays aria-hidden />}
          note={next ? `Next: ${day(next.date)} · ${next.title}` : "Nothing planned yet."}>
          <div className="strip">
            {Array.from({ length: 14 }, (_, i) => {
              const d = plus(today, i), ps = up.filter((p) => p.date === d);
              const k = ps.some((p) => p.gate === "block") ? "stop" : ps.some((p) => p.gate === "pass-with-edits") ? "warn" : ps.length ? "post" : "";
              return <div key={d} title={`${day(d)}: ${ps.length ? ps.map((p) => p.title).join(" · ") : "no post"}`}><div className={`b ${k}`} /><div className="d">{narrowDay(d)}</div></div>;
            })}
          </div>
        </Tile>
        <Tile label="Waiting for your OK" value={waiting.length} note={`${thisWeek} of them this week`} go="posts" color={blockColor(1)} icon={<Hourglass aria-hidden />} />
        <Tile label="Stopped by the check" value={blocked} note={blocked ? "open them in Posts" : "nothing stopped"} go="posts"
          color={blocked ? statusColor("critical") : statusColor("good")} icon={blocked ? <ShieldAlert aria-hidden /> : <ShieldCheck aria-hidden />} />
        <Tile label="Videos ready" value={<>{cards}<small> of {up.length}</small></>} note={`${owed} will be made on the next run`} go="posts" color={blockColor(2)} icon={<Clapperboard aria-hidden />}>
          <div className="meter"><span style={{ width: `${up.length ? Math.round((cards / up.length) * 100) : 0}%` }} /></div>
        </Tile>
        <Tile label="Things we heard" value={(S.listening?.findings || []).length} note={warm ? `loudest: ${warm.theme}` : "no listening run yet"} go="heard" color={blockColor(3)} icon={<Ear aria-hidden />} />
        <Tile size="wide" label="Replies to post" value={(S.replies?.proposals || []).length} note="you post them yourself" go="replies" color={blockColor(4)} icon={<MessageSquare aria-hidden />} />
        <Tile size="wide" label="Accounts we watch" value={(S.accounts?.watched || []).length} note={`${(S.suggested?.rows || []).length} suggestions waiting`} go="suggestions" color={blockColor(5)} icon={<Users aria-hidden />} />
      </div>

      <div className="cols2" style={{ marginTop: 20 }}>
        <Section title="Needs you" n={N.length}>
          <div className="panel">
            <ul className="rows">
              {N.length ? N.slice(0, 12).map((x, i) => (
                <li key={i} className="click" onClick={() => go(x.go)}>
                  <span className={`mark ${x.k}`} />
                  <span className="what"><div className="t">{x.t}</div>{x.x ? <div className="excerpt">{clean(x.x)}</div> : null}</span>
                  <span className="when">{x.d ? day(x.d) : ""}</span>
                </li>
              )) : <li><span /><span className="empty">Nothing is waiting for you.</span><span /></li>}
            </ul>
          </div>
        </Section>
        <Section title="Coming up" n="the next 14 days">
          <div className="panel">
            <ul className="rows">
              {agenda.length ? agenda.map((a, i) => a.post ? (
                <li key={i} className="click" onClick={() => go(`post:${a.post!.id}`)}>
                  <span className="when">{day(a.date)}</span>
                  <span className="what"><div className="chips" style={{ marginBottom: 4 }}><Theme tag={a.post.theme} /></div><div className="t">{a.post.title}</div><div className="excerpt">{excerpt(a.post)}</div></span>
                  <CheckChip gate={a.post.gate} />
                </li>
              ) : (
                <li key={i}>
                  <span className="when">{day(a.date)}</span>
                  <span className="what"><div className="chips" style={{ marginBottom: 4 }}><Chip>{a.row!.platform}</Chip></div><div className="t">{a.row!.title}</div><div className="excerpt">{clean(a.row!.body)}</div></span>
                  <Chip>{a.row!.status}</Chip>
                </li>
              )) : <li><span /><span className="empty">Nothing planned in the next two weeks.</span><span /></li>}
            </ul>
          </div>
        </Section>
      </div>

      {Q.length ? (
        <Section title="Big questions" n={`${open.length} open · ${Q.length - open.length} answered`} hint="The story asks these; your answers are kept and the next story reads them.">
          <div className="panel">
            <ul className="rows">
              {open.map((q) => (
                <li key={q.id} className="click" onClick={() => go(`q:${q.id}`)}>
                  <span className="mark info" />
                  <span className="what"><div className="t">{q.question}</div>{q.why ? <div className="excerpt">{q.why}</div> : null}</span>
                  <span className="btn small primary">Answer</span>
                </li>
              ))}
              {done.map((q) => (
                <li key={q.id}>
                  <span className="mark good" />
                  <span className="what"><div className="t">{q.question}</div><div className="excerpt">Your answer: {q.answer}</div></span>
                  <span className="when">{day(q.answered_at)}</span>
                </li>
              ))}
            </ul>
          </div>
        </Section>
      ) : null}

      <Section title="Our themes at a glance" hint="Click a theme to change what the listener searches for.">
        <ThemeTable id="today-themes" />
      </Section>
    </>
  );
}
