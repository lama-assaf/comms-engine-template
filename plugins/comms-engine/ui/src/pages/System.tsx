import { useApp } from "../ctx";
import { when } from "../format";
import type { Job, Run } from "../types";
import { DataTable } from "../components/DataTable";
import { About, Chip, PageHead, Section } from "../components/ui";

export function System() {
  const { S } = useApp();
  const E = S.engine || { jobs: [], runs: [], motion_owed: [] };
  return (
    <>
      <PageHead page="system" title="System" meta="what runs on this computer" />
      <About><p>The jobs that run on a schedule on this Mac: listening, writing, checking, sending, scoring. This page only shows them; they are switched on and off with the engine console (/engine).</p></About>
      <Section title="Scheduled jobs">
        <DataTable<Job> id="jobs" rows={E.jobs} search={false}
          cols={[{ id: "job", label: "Job", get: (r) => r.job || r.label, cell: (r) => <span className="mono">{r.job || r.label}</span> },
            { id: "on", label: "Switched on", get: (r) => (r.loaded === undefined ? "" : r.loaded ? "on" : "off"), cell: (r) => r.loaded === undefined ? null : r.loaded ? <Chip k="good">on</Chip> : <Chip k="warning">off</Chip> },
            { id: "last_run", label: "Last ran" }, { id: "what", label: "What it does", cell: (r) => <div className="cell-text small">{r.what}</div> }]} />
      </Section>
      <Section title="Videos the next run will make">
        <DataTable<{ id: string; action: string; reason: string }> id="owed" rows={E.motion_owed} search={false} empty="Every planned post has its video."
          cols={[{ id: "id", label: "Post", cell: (r) => <span className="mono">{r.id}</span> }, { id: "action", label: "Needs", cell: (r) => <Chip>{r.action === "storyboard" ? "a video plan" : "a render"}</Chip> },
            { id: "reason", label: "Why" }]} />
      </Section>
      <Section title="What ran lately">
        <DataTable<Run> id="runs" rows={E.runs} filters={[{ label: "Step", get: (r) => r.step }]}
          cols={[{ id: "at", label: "When", cell: (r) => <span style={{ whiteSpace: "nowrap" }}>{when(r.at)}</span> }, { id: "step", label: "Step", cell: (r) => <Chip>{r.step}</Chip> },
            { id: "detail", label: "What happened", cell: (r) => <div className="cell-text small">{r.detail}</div> }]} />
      </Section>
    </>
  );
}
