import Link from "next/link";
import { loadRows, loadProposals, waitingOn, loadClaimsReview } from "@/lib/desk";
import { RowTags } from "@/components/tags";
import { DecideBox } from "@/components/quick-actions";

export default async function QueuePage({ searchParams }: { searchParams: Promise<{ stream?: string }> }) {
  const sp = await searchParams;
  const all = await loadRows();
  const allProps = await loadProposals();
  // The stream switcher (plan v2, A14): every view filters on it; a reaction
  // proposal belongs to the stream its row carries.
  const rows = sp.stream ? all.filter((r) => r.item.stream === sp.stream) : all;
  const props = sp.stream ? allProps.filter((p) => (p.proposal as { stream?: string }).stream === sp.stream) : allProps;
  const claims = loadClaimsReview().items.filter((c) => !sp.stream || c.stream === sp.stream);
  const waiting = waitingOn(rows, props, claims);
  const byId = new Map(rows.map((r) => [r.item.id, r]));
  const propsById = new Map(props.map((p) => [p.proposal.id, p]));
  const streams = [...new Set(all.map((r) => r.item.stream).filter(Boolean))].sort();

  return (
    <>
      <div className="tags" style={{ margin: "12px 0" }}>
        <Link className={`tag${sp.stream ? "" : " accent"}`} href="/queue">
          all streams
        </Link>
        {streams.map((s) => (
          <Link key={s} className={`tag${sp.stream === s ? " accent" : ""}`} href={`/queue?stream=${encodeURIComponent(s)}`}>
            {s}
          </Link>
        ))}
      </div>
      <p className="lede">
        Everything the cycle is holding for you, most urgent first: an edit conflict outranks a blocked claim, a
        blocked claim outranks a missing argument line, and a comment proposal waits behind all of them. Clearing a
        comment lets a person place it by hand — the engine never sends one.
      </p>

      {waiting.length === 0 && <p className="empty">Nothing is waiting. The next cycle runs on the social-engine job's schedule (engine.json; engine.py status).</p>}

      {waiting.map((w) => {
        const row = byId.get(w.id);
        const prop = propsById.get(w.id);
        return (
          <div key={w.id} className={`panel${w.rank === 0 ? " urgent" : w.rank <= 2 ? " attention" : ""}`}>
            <h3>
              {row ? <Link href={`/item/${encodeURIComponent(w.id)}`}>{w.title}</Link> : w.title}
            </h3>
            <p className="why">{w.why}</p>
            {row && <RowTags row={row} />}
            {prop && (
              <>
                <p className="note">
                  {prop.proposal.platform} ·{" "}
                  <a href={prop.proposal.url} target="_blank" rel="noreferrer">
                    the post being replied to
                  </a>
                </p>
                <div className="prose" style={{ marginTop: 8 }}>
                  {prop.proposal.draft}
                </div>
                <DecideBox id={prop.proposal.id} kind="reaction" canApprove />
              </>
            )}
            {row && (
              <div className="actions">
                <Link className="btn" href={`/item/${encodeURIComponent(w.id)}`}>
                  {w.act}
                </Link>
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}
