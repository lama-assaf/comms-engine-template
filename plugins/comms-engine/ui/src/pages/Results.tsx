import { useApp } from "../ctx";
import { iso } from "../format";
import type { Prediction, ScoreRow } from "../types";
import { DataTable } from "../components/DataTable";
import { About, Chip, PageHead, Section, Theme } from "../components/ui";

export function Results() {
  const { S } = useApp();
  const L = S.learning || { predictions: [], rows: [], key_results: [], computed_at: "" };
  const P = L.predictions;
  return (
    <>
      <PageHead page="results" title="Results" meta={`${P.filter((p) => p.actual != null).length} of ${P.length} guesses checked`} />
      <About words={[["Guess", "Below, usual or above: how the system expects the post to do."], ["Actual", "How it really did, filled in after it went out."], ["Idea being tested", "The one thing this post tries differently."]]}>
        <p>Before a post goes out, the system guesses how it will do: below usual, usual, or above usual. Once the post is out, it checks. Over time this shows which kinds of posts work.</p>
        <p>Few results so far: the comparison needs posts that are out and have been measured.</p>
      </About>
      <Section title="The scorecard">
        <DataTable<ScoreRow> id="score" rows={L.rows} search={false}
          cols={[{ id: "row", label: "Measure", cell: (r) => <b>{r.row}</b> }, { id: "value", label: "Value", num: true, cell: (r) => String(r.value ?? "—") },
            { id: "records", label: "Based on", num: true },
            { id: "status", label: "Status", cell: (r) => <Chip k={r.status === "live" ? "good" : r.status === "blank" ? "" : "warning"}>{r.status}</Chip> },
            { id: "note", label: "What it means", cell: (r) => <div className="cell-text small">{r.note}</div> }]} />
      </Section>
      <Section title="Guesses and results">
        <DataTable<Prediction> id="predictions" rows={P} filters={[{ label: "Theme", get: (r) => r.theme }, { label: "Channel", get: (r) => r.platform }, { label: "Guess", get: (r) => r.predicted }]}
          cols={[{ id: "made", label: "Made", get: (r) => iso(r.predicted_at) }, { id: "theme", label: "Theme", cell: (r) => <Theme tag={r.theme} /> }, { id: "platform", label: "Channel" },
            { id: "hypothesis", label: "Idea being tested", cell: (r) => <div className="cell-text small">{r.hypothesis}</div> }, { id: "predicted", label: "Guess" },
            { id: "actual", label: "Actual", cell: (r) => r.actual ?? <span className="muted">not yet</span> }]} />
      </Section>
      {L.key_results.length ? (
        <Section title="Our goals">
          <DataTable<{ objective: string; key_result: string }> id="krs" rows={L.key_results} filters={[{ label: "Goal", get: (r) => r.objective }]}
            cols={[{ id: "objective", label: "Goal" }, { id: "key_result", label: "How we know" }]} />
        </Section>
      ) : null}
    </>
  );
}
