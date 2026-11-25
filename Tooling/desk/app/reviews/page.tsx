import Link from "next/link";
import { desc } from "drizzle-orm";
import { db } from "@/db";
import { reviews, items } from "@/db/schema";

export default async function ReviewsPage({ searchParams }: { searchParams: Promise<{ stream?: string }> }) {
  const sp = await searchParams;
  const every = await db.select().from(reviews).orderBy(desc(reviews.at));
  const its = await db.select({ id: items.id, stream: items.stream }).from(items);
  // A review carries its item's stream (plan v2, A14): the switcher filters
  // on it, and `desk_sync.py --pull` appends a standing review to that
  // stream's own reviews.md.
  const streamOf = new Map(its.map((i) => [i.id, i.stream]));
  const streams = [...new Set(its.map((i) => i.stream).filter(Boolean))].sort();
  const all = sp.stream ? every.filter((r) => streamOf.get(r.itemId) === sp.stream) : every;
  const standing = all.filter((r) => r.scope === "standing");
  const waiting = standing.filter((r) => !r.syncedAt);

  return (
    <>
      <p className="lede">
        Every reason you gave for a decision. The ones you marked <b>standing</b> are appended to{" "}
        <code className="mono">.atelier/memory/reviews.md</code> by{" "}
        <code className="mono">desk_sync.py --pull</code>, and from there <b>theme-writer</b> reads them before
        drafting and <b>gatekeeper</b> before gating — so a judgement you make once does not have to be made again on
        the next draft of the same shape. The rest stay with their item.
      </p>

      <div className="panel">
        <h3>
          {standing.length} standing · {waiting.length} not yet in memory
        </h3>
        <p className="why">
          {waiting.length
            ? "The next `desk_sync.py --pull` carries these across. /social-cycle runs it as its first step."
            : "Everything standing has reached the agents' memory."}
        </p>
      </div>

      <div className="tags" style={{ margin: "12px 0" }}>
        <Link className={`tag${sp.stream ? "" : " accent"}`} href="/reviews">
          all streams
        </Link>
        {streams.map((s) => (
          <Link key={s} className={`tag${sp.stream === s ? " accent" : ""}`} href={`/reviews?stream=${encodeURIComponent(s)}`}>
            {s}
          </Link>
        ))}
      </div>

      {all.length === 0 && <p className="empty">No reviews recorded yet.</p>}

      {all.map((r) => (
        <div key={r.rowid} className="panel">
          <div className="tags">
            <span className="tag">{r.verdict}</span>
            {r.scope === "standing" ? <span className="tag accent">standing</span> : <span className="tag">item only</span>}
            {r.scope === "standing" &&
              (r.syncedAt ? <span className="tag ok">in memory</span> : <span className="tag warn">waiting for the pull</span>)}
            {r.theme && <span className="tag">{r.theme}</span>}
            {streamOf.get(r.itemId) && <span className="tag">{streamOf.get(r.itemId)}</span>}
          </div>
          <h3 style={{ marginTop: 8 }}>
            <Link href={`/item/${encodeURIComponent(r.itemId)}`}>{r.title || r.itemId}</Link>
          </h3>
          <p className="prose">{r.rationale}</p>
          <span className="mono">
            {r.by} · {r.at.slice(0, 16).replace("T", " ")}
          </span>
        </div>
      ))}
    </>
  );
}
