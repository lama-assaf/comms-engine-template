import { useApp } from "../ctx";
import { day } from "../format";
import type { Finding, Warmth } from "../types";
import { DataTable } from "../components/DataTable";
import { About, Chip, PageHead, Section, Theme } from "../components/ui";

export function Heard() {
  const { S, open } = useApp();
  const L = S.listening;
  return (
    <>
      <PageHead page="heard" title="What we heard" meta={L?.window ? `from ${L.window.from} to ${L.window.to}` : "no listening run yet"} />
      <About words={[["Finding", "Something the listener thinks we should know, with its sources."], ["Content", "It could feed a blog post."], ["Conversation", "It could be worth a reply."],
        ["Fresh until", "After this day it is old news."], ["Urgent slot", "A free slot kept for urgent news; it opens only when an official document changes the rules."]]}>
        <p>Every weekday the listener searches X for our themes, our name and the accounts we watch, then picks out what matters. Each finding says what it is and whether it could become a post or a reply.</p>
        <p>Click a finding to see the posts it is based on.</p>
      </About>
      {L?.summary ? <Section title="In short"><div className="panel pad" style={{ fontSize: 16, lineHeight: 1.65 }}>{L.summary}</div></Section> : null}
      <Section title="Findings" n={L?.findings.length || 0}>
        <DataTable<Finding> id="findings" rows={L?.findings || []} onRow={(r) => open({ kind: "finding", id: r.id })}
          filters={[{ label: "Theme", get: (r) => r.theme }, { label: "Kind", get: (r) => r.shape }]} text={(r) => (r.evidence || []).map((e) => `${e.quote} ${e.text}`).join(" ")}
          empty="Nothing new heard."
          cols={[
            { id: "theme", label: "Theme", cell: (r) => <Theme tag={r.theme} /> },
            { id: "finding", label: "What we heard", cell: (r) => <div className="cell-text"><div>{r.finding}</div>{r.evidence?.[0]?.quote ? <div className="quote">“{r.evidence[0].quote}”</div> : null}</div> },
            { id: "shape", label: "Kind", cell: (r) => <Chip>{r.shape}</Chip> },
            { id: "relevance", label: "Relevance", num: true, get: (r) => Number(r.relevance) || 0, cell: (r) => <b>{String(r.relevance)}</b> },
            { id: "fresh", label: "Fresh until", get: (r) => r.freshness_deadline, cell: (r) => (r.freshness_deadline ? day(r.freshness_deadline) : "") },
          ]} />
      </Section>
      {L?.warmest?.length ? (
        <Section title="Loudest themes">
          <DataTable<Warmth> id="warm" rows={L.warmest} search={false}
            cols={[{ id: "theme", label: "Theme", cell: (r) => <Theme tag={r.theme} /> }, { id: "relevance", label: "Loudness", num: true },
              { id: "count", label: "Posts found", num: true }, { id: "why", label: "Why", cell: (r) => <div className="cell-text small">{r.why}</div> }]} />
        </Section>
      ) : null}
      {L?.held_slot ? (
        <Section title="Urgent slot">
          <div className="panel pad small"><div className="chips" style={{ marginBottom: 8 }}>{L.held_slot.triggered ? <Chip k="critical">opened</Chip> : <Chip>closed</Chip>}</div>{L.held_slot.reason}</div>
        </Section>
      ) : null}
      {L?.held_for_person?.length ? (
        <Section title="For a person to check">
          <div className="panel"><ul className="rows">{L.held_for_person.map((h, i) => <li key={i}><span className="mark info" /><span className="what small">{typeof h === "string" ? h : JSON.stringify(h)}</span><span /></li>)}</ul></div>
        </Section>
      ) : null}
      {L?.mentions_note ? <Section title="Mentions of us"><div className="panel pad small">{L.mentions_note}</div></Section> : null}
    </>
  );
}
