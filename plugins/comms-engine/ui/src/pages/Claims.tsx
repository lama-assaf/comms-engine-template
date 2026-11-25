import { useApp } from "../ctx";
import type { ClaimIdea } from "../types";
import { DataTable } from "../components/DataTable";
import { About, Chip, Ext, PageHead, Section, Theme } from "../components/ui";

export function Claims() {
  const { S } = useApp();
  const C = S.claims || { register: 0, watch: [], review: [] };
  return (
    <>
      <PageHead page="claims" title="Claim ideas" meta={`${C.watch.length} ideas · ${C.register} facts already approved`} />
      <About words={[["Grade", "How strong the proof is."], ["Tier", "What kind of source it is, for example a regulator's own document or a news story."],
        ["Corroboration", "Whether a second, independent source says the same."]]}>
        <p>Things the research found that we might be able to say about ourselves one day, with the source each one came from.</p>
        <p>They are only ideas. A post may only use facts from our approved list ({C.register} so far). An idea joins that list only after someone checks its source in the memory update; this page never adds one.</p>
      </About>
      <DataTable<ClaimIdea> id="claims" rows={C.watch}
        filters={[{ label: "Theme", get: (r) => r.theme }, { label: "Grade", get: (r) => r.grade }, { label: "Tier", get: (r) => r.tier }, { label: "Corroboration", get: (r) => r.corroboration }]}
        empty="No claim ideas right now."
        cols={[
          { id: "date", label: "Found", cell: (r) => <span style={{ whiteSpace: "nowrap" }}>{r.date}</span> },
          { id: "theme", label: "Theme", cell: (r) => <Theme tag={r.theme} /> },
          { id: "claim", label: "What it says", cell: (r) => <div className="cell-text">{r.claim}</div> },
          { id: "source", label: "Source", cell: (r) => <Ext url={r.url}>{r.source}</Ext> },
          { id: "tier", label: "Tier" }, { id: "grade", label: "Grade", cell: (r) => <Chip>{r.grade}</Chip> }, { id: "corroboration", label: "Corroboration" },
        ]} />
      {C.review.length ? (
        <Section title="Posts that rely on a fact that changed">
          <DataTable<Record<string, string>> id="review" rows={C.review}
            cols={[{ id: "post", label: "Post", get: (r) => r.id || r.title }, { id: "what", label: "What changed", get: (r) => r.reason || r.why || JSON.stringify(r) }]} />
        </Section>
      ) : null}
    </>
  );
}
