import { useState } from "react";
import { CalendarClock, Globe, PenLine, Play } from "lucide-react";
import { postAct } from "../api";
import { useApp } from "../ctx";
import { day, excerpt, iso, when } from "../format";
import type { CalendarRow, Pick, Post, Send } from "../types";
import { ApprovalChip } from "../components/Approval";
import { DataTable } from "../components/DataTable";
import { About, Chip, CheckChip, Ext, Field, PageHead, Section, Theme, Titled, Where, checkWord, whereWord } from "../components/ui";

const video = (r: Post) => (r.motion.poster ? "ready" : r.motion.storyboard ? "planned" : "not yet");

function PostTable({ id, rows, empty }: { id: string; rows: Post[]; empty?: string }) {
  const { open } = useApp();
  return (
    <DataTable<Post> id={id} rows={rows} onRow={(r) => open({ kind: "post", id: r.id })} empty={empty}
      filters={[{ label: "Theme", get: (r) => r.theme }, { label: "Check", get: (r) => checkWord(r.gate) }, { label: "Status", get: whereWord }]}
      text={(r) => `${r.post} ${r.teaser_x}`}
      cols={[
        { id: "date", label: "Day", cell: (r) => <span style={{ whiteSpace: "nowrap", fontWeight: 650 }}>{day(r.date)}</span> },
        { id: "theme", label: "Theme", cell: (r) => <Theme tag={r.theme} /> },
        { id: "title", label: "Post", cell: (r) => <Titled title={r.title} text={excerpt(r)} /> },
        { id: "gate", label: "Check", get: (r) => checkWord(r.gate), cell: (r) => <CheckChip gate={r.gate} /> },
        { id: "status", label: "Status", get: whereWord, cell: (r) => <Where p={r} /> },
        { id: "approval", label: "Approval", sort: false, cell: (r) => <ApprovalChip p={r} /> },
        { id: "video", label: "Video", get: video, cell: (r) => r.motion.poster ? <Chip k="good"><Play aria-hidden />ready</Chip> : r.motion.storyboard ? <Chip>planned</Chip> : <span className="muted small">not yet</span> },
      ]} />
  );
}

type Said = { ok: boolean; text: string } | null;
const SENT = ["sent", "scored"];

/** A post's calendar acts in its drawer: change its day before it goes out, and mark its article live
 *  once it is on the site (the sender then puts the link in a first reply under the sent teasers). */
export function PostCalendar({ p }: { p: Post }) {
  const { reload, toast } = useApp();
  const [date, setDate] = useState(p.date || "");
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<Said>(null);
  const sent = SENT.includes(p.act?.state || "");
  const move = async () => {
    setBusy(true);
    const r = await postAct("/api/schedule", { id: p.id, date, by: "alpha" });
    setBusy(false);
    if (!r.ok) { setSaid({ ok: false, text: r.error || "that did not work" }); return; }
    setSaid({ ok: true, text: `Moved to ${day(date)}. Nothing was sent.` });
    toast(`Moved to ${day(date)}`);
    await reload();
  };
  const live = async () => {
    setBusy(true);
    const r = await postAct("/api/blog-live", { id: p.id, by: "alpha" });
    setBusy(false);
    if (!r.ok) { setSaid({ ok: false, text: r.error || "that did not work" }); return; }
    const out = (r.data as { live?: { outcome?: string; url?: string } } | undefined)?.live || {};
    if (out.outcome === "applied") { setSaid({ ok: true, text: `Marked live at ${out.url}. The sender adds the link under the sent posts.` }); toast("Article marked live"); }
    else setSaid({ ok: false, text: out.outcome?.startsWith("refused") ? `Not marked: ${out.outcome.replace(/^refused: /, "")}` : "It was marked live already." });
    await reload();
  };
  return (
    <div className="approve" aria-live="polite">
      {!sent ? (
        <>
          <Field htmlFor={`day-${p.id}`}>Its day</Field>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <input id={`day-${p.id}`} className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} style={{ width: "auto" }} />
            <button className="btn" disabled={busy || !date || date === p.date} onClick={move}><CalendarClock aria-hidden />Move to this day</button>
          </div>
          <div className="small muted">Moves the post, and its schedule if it is approved, within the posting rules. Once a version has gone out, its day stays.</div>
        </>
      ) : <div className="small muted">A version of this post has gone out, so its day stays.</div>}
      {p.post ? (p.live ? <div className="small">Article live at <Ext url={p.live} /></div> : (
        <>
          <button className="btn" disabled={busy} onClick={live}><Globe aria-hidden />Mark the article live</button>
          <div className="small muted">Say so once the article is on the site. It records that, tells the site to rebuild, and the sender puts the link in a first reply under the X and LinkedIn posts. It sends nothing itself.</div>
        </>
      )) : null}
      {said ? <div className={`approve-out ${said.ok ? "ok" : "no"}`} role="status">{said.text}</div> : null}
    </div>
  );
}

/** A post a person on the team writes: one channel, one day. It is checked first, then becomes a draft
 *  that is checked again and approved like any other; nothing here schedules or sends it. */
function NewPost() {
  const { S, reload, toast } = useApp();
  const [channel, setChannel] = useState("x");
  const [date, setDate] = useState(S.today || "");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<Said>(null);
  const max = channel === "x" ? 280 : 3000;
  const go = async () => {
    setBusy(true);
    const r = await postAct("/api/new-post", { stream: S.stream, channel, date, title, text, by: "team" });
    setBusy(false);
    if (!r.ok) { setSaid({ ok: false, text: r.error || "that did not work" }); return; }
    setSaid({ ok: true, text: "Written as a draft. It is checked with the next cycle; approve it then and it goes on its day." });
    toast("Draft written");
    setTitle(""); setText("");
    await reload();
  };
  return (
    <div className="approve" aria-live="polite">
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "end" }}>
        <div><Field htmlFor="np-channel">Channel</Field>
          <select id="np-channel" className="input" value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="x">X</option><option value="linkedin">LinkedIn</option>
          </select></div>
        <div><Field htmlFor="np-date">Day</Field><input id="np-date" className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} /></div>
        <div style={{ flex: 1, minWidth: 220 }}><Field htmlFor="np-title">Title (optional)</Field>
          <input id="np-title" className="input" maxLength={100} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="A short name for the calendar" /></div>
      </div>
      <Field htmlFor="np-text" n={`${text.length}/${max}`}>The post</Field>
      <textarea id="np-text" className="textarea" maxLength={max} value={text} onChange={(e) => setText(e.target.value)} placeholder="The words as they will go out. No link: the link goes in the first reply." />
      <button className="btn primary" disabled={busy || !text.trim() || !date} onClick={go}><PenLine aria-hidden />{busy ? "Writing…" : "Write it as a draft"}</button>
      {said ? <div className={`approve-out ${said.ok ? "ok" : "no"}`} role="status">{said.text}</div> : null}
    </div>
  );
}

export function Posts() {
  const { S, open } = useApp();
  const P = S.posts || { upcoming: [], past: [] }, C = S.calendar, st = C?.strategy || {};
  return (
    <>
      <PageHead page="posts" title="Posts" meta="what is planned, what is open, what went out" />
      <About words={[["Ready", "The check found nothing to fix."], ["Small fixes", "The check fixed or flagged small things; read its note before you approve."],
        ["Stopped", "The post says something we cannot prove yet. It will not go out until it is fixed."], ["Waiting for you", "Nobody has approved or held it yet."],
        ["Video", "The short motion card made from the post's own lines."]]}>
        <p>Every blog post the system has written, by the day it is planned for. Click a post to read all of it: the full article, the short X and LinkedIn versions, the check's note and its video.</p>
        <p>You can approve a post here: it is put in the schedule for its day, within the posting rules, and the Approval column shows what happened, or why it was refused. Open a post to move it to another day or to mark its article live once it is on the site. Holding, sending back and editing stay on <b>the desk</b>. Nothing on this page posts anything; the sender posts on the day.</p>
      </About>
      <Section title="Our planned posts" n={P.upcoming.length}>
        <PostTable id="posts" rows={P.upcoming} empty="No posts planned from today on." />
      </Section>
      {st.picks?.length ? (
        <Section title="This week's blog picks" n={st.week || ""} hint="The two blog slots the planner chose for this week, and why.">
          <DataTable<Pick> id="picks" rows={st.picks} search={false}
            cols={[{ id: "slot", label: "Slot" }, { id: "theme", label: "Theme", cell: (r) => <Theme tag={r.theme} /> },
              { id: "why", label: "Why this one", cell: (r) => <div className="cell-text small">{r.why}</div> }, { id: "predicted", label: "Expected result" }]} />
        </Section>
      ) : null}
      <Section title="Write a post" hint="A post of your own for X or LinkedIn. It becomes a draft on the calendar, is checked like every draft, and goes out on its day once approved.">
        <NewPost />
      </Section>
      <Section title="In the content calendar" hint={<>The calendar notes, one row per channel: what is ahead of us, and what is dated in the past but never went out, so someone should finish, move or drop it. Built from the notes {when(C?.taken_at) || "never"}.</>}>
        <DataTable<CalendarRow> id="cal" rows={[...(C?.ahead || []), ...(C?.open_past || [])]}
          onRow={(r) => open({ kind: "text", title: r.title, kicker: "In the calendar", text: r.body, chips: [day(r.date), r.platform, r.status, r.stream] })}
          filters={[{ label: "Status", get: (r) => r.status }, { label: "Channel", get: (r) => r.platform }, { label: "Brand", get: (r) => r.stream }]} text={(r) => r.body}
          empty="Nothing open in the calendar."
          cols={[
            { id: "date", label: "Day", get: (r) => iso(r.date), cell: (r) => <span style={{ whiteSpace: "nowrap", fontWeight: 650 }}>{day(r.date)}</span> },
            { id: "platform", label: "Channel" },
            { id: "status", label: "Status", cell: (r) => <Chip k={r.status === "Ready" ? "good" : r.status === "Published" ? "info" : "warning"}>{r.status}</Chip> },
            { id: "stream", label: "Brand" },
            { id: "title", label: "Post", cell: (r) => <Titled title={r.title} text={r.body} /> },
            { id: "by", label: "Written by", get: (r) => (r.engine ? "system" : "team") },
          ]} />
      </Section>
      <Section title="What went out" hint="Posts the sender put on X and LinkedIn, newest first.">
        <DataTable<Send> id="sends" rows={C?.sends || []}
          onRow={(r) => open({ kind: "text", title: r.title, kicker: "Sent", text: r.body, chips: [when(r.at), r.platform], url: r.url })}
          filters={[{ label: "Channel", get: (r) => r.platform }]} text={(r) => r.body} empty="Nothing has been sent yet."
          cols={[
            { id: "at", label: "When", cell: (r) => <span style={{ whiteSpace: "nowrap" }}>{when(r.at)}</span> },
            { id: "platform", label: "Channel" },
            { id: "title", label: "Post", cell: (r) => <Titled title={r.title} text={r.body} /> },
            { id: "url", label: "Link", sort: false, cell: (r) => <Ext url={r.url}>open ↗</Ext> },
          ]} />
      </Section>
      {P.past.length ? (
        <Section title="Our posts whose day has passed" hint="Planned for an earlier day and never published. Open one to move it to a new day, or drop it on the desk.">
          <PostTable id="past" rows={P.past} />
        </Section>
      ) : null}
    </>
  );
}
