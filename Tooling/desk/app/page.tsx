import Link from "next/link";
import { loadRows, loadProposals, waitingOn, loadClaimsReview, monthGrid, unscheduled, isoDay, MONTHS, type Row } from "@/lib/desk";

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default async function CalendarPage({
  searchParams,
}: {
  searchParams: Promise<{ m?: string; stream?: string; theme?: string }>;
}) {
  const sp = await searchParams;
  const today = new Date();
  // `m` is an offset in months from today, so a link never goes stale.
  const offset = Number.parseInt(sp.m ?? "0", 10) || 0;
  const cursor = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth() + offset, 1));
  const year = cursor.getUTCFullYear();
  const month = cursor.getUTCMonth();

  const all = await loadRows();
  const props = await loadProposals();
  const rows = all.filter(
    (r) => (!sp.stream || r.item.stream === sp.stream) && (!sp.theme || r.item.theme === sp.theme),
  );
  const days = monthGrid(rows, year, month, today);
  const loose = unscheduled(rows);
  const waiting = waitingOn(all, props, loadClaimsReview().items);

  const streams = [...new Set(all.map((r) => r.item.stream).filter(Boolean))].sort();
  const themes = [...new Set(all.map((r) => r.item.theme).filter(Boolean))].sort();
  const qs = (patch: Record<string, string | undefined>) => {
    const p = new URLSearchParams();
    const merged = { m: String(offset), stream: sp.stream, theme: sp.theme, ...patch };
    Object.entries(merged).forEach(([k, v]) => {
      if (v && v !== "0") p.set(k, v);
    });
    const s = p.toString();
    return s ? `/?${s}` : "/";
  };

  return (
    <>
      <p className="lede">
        Every drafted item on the day its note schedules it. The colour of a chip is where it stands with you, not
        where it stands with the gate — the gate is the second tag. Nothing here publishes: approving schedules the
        post for its day once pulled, and marking its article <em>live</em> stays a person's act on the control page.
      </p>

      {waiting.length > 0 && (
        <div className="panel attention">
          <h3>
            {waiting.length} waiting on you
            <span className="note"> · {waiting.filter((w) => w.rank <= 1).length} urgent</span>
          </h3>
          <p className="why">{waiting[0].why}</p>
          <Link className="btn" href="/queue">
            Open the queue
          </Link>
        </div>
      )}

      <div className="calhead">
        <h2>
          {MONTHS[month]} {year}
        </h2>
        <div className="calnav">
          <Link className="btn small" href={qs({ m: String(offset - 1) })}>
            ‹ Prev
          </Link>
          <Link className="btn small" href={qs({ m: "0" })}>
            Today
          </Link>
          <Link className="btn small" href={qs({ m: String(offset + 1) })}>
            Next ›
          </Link>
        </div>
        <div className="tags" style={{ marginLeft: "auto" }}>
          <Link className={`tag${sp.stream ? "" : " accent"}`} href={qs({ stream: undefined })}>
            all streams
          </Link>
          {streams.map((s) => (
            <Link key={s} className={`tag${sp.stream === s ? " accent" : ""}`} href={qs({ stream: s })}>
              {s}
            </Link>
          ))}
          {sp.theme && (
            <Link className="tag accent" href={qs({ theme: undefined })}>
              {sp.theme} ×
            </Link>
          )}
        </div>
      </div>

      <div className="grid">
        {DOW.map((d) => (
          <div key={d} className="dow">
            {d}
          </div>
        ))}
        {days.map((d) => (
          <div key={d.iso} className={`cell${d.inMonth ? "" : " out"}${d.today ? " today" : ""}`}>
            <span className="num">{d.date.getUTCDate()}</span>
            {d.rows.map((r) => (
              <Chip key={r.item.id} row={r} />
            ))}
          </div>
        ))}
      </div>

      {!sp.theme && themes.length > 0 && (
        <div className="tags" style={{ marginTop: 12 }}>
          <span className="note">Filter by theme:</span>
          {themes.map((t) => (
            <Link key={t} className="tag" href={qs({ theme: t })}>
              {t}
            </Link>
          ))}
        </div>
      )}

      {loose.length > 0 && (
        <>
          <h2 className="sec">No date on the note</h2>
          <p className="note">
            An item reaches the calendar through its note&rsquo;s <code className="mono">date</code>. These have none,
            and the desk will not invent one — set it in the vault.
          </p>
          {loose.map((r) => (
            <div key={r.item.id} className="panel">
              <Link href={`/item/${encodeURIComponent(r.item.id)}`}>{r.view.title}</Link>
            </div>
          ))}
        </>
      )}
    </>
  );
}

function Chip({ row }: { row: Row }) {
  const cls = row.blocked ? "blocked" : row.status;
  return (
    <Link className={`chip ${cls}`} href={`/item/${encodeURIComponent(row.item.id)}`}>
      {row.view.title.length > 74 ? row.view.title.slice(0, 72) + "…" : row.view.title}
      <span className="meta">
        {row.item.platform} · {row.item.theme}
        {row.editState === "conflict" ? " · edit conflict" : ""}
        {row.status === "proposed" && !row.argCurrent ? " · argument line open" : ""}
      </span>
    </Link>
  );
}
