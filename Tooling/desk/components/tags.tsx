import type { Row } from "@/lib/desk";

const STATUS_TONE: Record<string, string> = {
  approved: "ok",
  proposed: "warn",
  rejected: "stop",
  held: "",
  rewrite: "warn",
};

/** Where the item stands with Alpha. */
export function StatusTag({ status }: { status: string }) {
  return <span className={`tag ${STATUS_TONE[status] ?? ""}`}>{status}</span>;
}

/** Where it stands with the claim gate — a different question from the above. */
export function GateTag({ verdict }: { verdict: string }) {
  if (!verdict) return <span className="tag">gate not run</span>;
  const tone = verdict === "block" ? "stop" : verdict === "pass" ? "ok" : "warn";
  return <span className={`tag ${tone}`}>gate {verdict}</span>;
}

/** The three-way edit state, said in the words the distributor uses. */
export function EditTag({ state }: { state: Row["editState"] }) {
  if (state === "none") return null;
  const label: Record<string, [string, string]> = {
    pending: ["edit waiting for the distributor", "warn"],
    conflict: ["edit conflict — nothing written", "stop"],
    applied: ["edit applied to the note", "ok"],
    dropped: ["edit dropped by hand", ""],
  };
  const [text, tone] = label[state] ?? ["", ""];
  return <span className={`tag ${tone}`}>{text}</span>;
}

export function ArgTag({ row }: { row: Row }) {
  if (row.argCurrent) return <span className="tag ok">argument line {row.argument!.act}</span>;
  if (row.argument) return <span className="tag warn">argument line changed since you confirmed it</span>;
  return <span className="tag warn">argument line open</span>;
}

export function RowTags({ row }: { row: Row }) {
  return (
    <div className="tags">
      <StatusTag status={row.status} />
      <GateTag verdict={row.item.gateVerdict} />
      <ArgTag row={row} />
      <EditTag state={row.editState} />
      <span className="tag">{row.item.stream}</span>
      <span className="tag">{row.item.theme}</span>
    </div>
  );
}
