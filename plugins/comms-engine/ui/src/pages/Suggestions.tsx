import { useApp } from "../ctx";
import { clean, fmt, xurl } from "../format";
import type { Suggestion } from "../types";
import { DataTable } from "../components/DataTable";
import { About, Ext, PageHead, Section, Theme } from "../components/ui";

export function WatchButtons({ s, after }: { s: Suggestion; after?: () => void }) {
  const { S, act } = useApp();
  const base = S.accounts?.watch_base;
  return (
    <span style={{ display: "inline-flex", gap: 6 }}>
      <button className="btn small primary" onClick={async () => { if (await act("/api/watch", { handle: s.handle, themes: s.themes, from: "suggestion", base }, `${s.handle} is now watched`)) after?.(); }}>Watch</button>
      <button className="btn small" onClick={async () => { if (await act("/api/dismiss", { handle: s.handle, base }, `${s.handle} dismissed`)) after?.(); }}>Dismiss</button>
    </span>
  );
}

export function Suggestions() {
  const { S, act, open } = useApp();
  const G = S.suggested || { rows: [], days: 30, min_hits: 2 }, D = S.accounts?.dismissed || [];
  return (
    <>
      <PageHead page="suggestions" title="Suggestions" meta={`${G.rows.length} accounts worth a look`} />
      <About words={[["Seen", "How many of its posts the listener found on our themes."], ["Engagement", "Likes, reposts and replies on those posts, added up."]]}>
        <p>Accounts that posted about our themes at least {G.min_hits} times in the last {G.days} days, and that we do not watch yet. Click one to read the posts that put it here.</p>
        <p><b>Watch</b> the useful ones and the listener will follow them. <b>Dismiss</b> the noise and it will not be suggested again. Nothing is saved about an account until you choose.</p>
      </About>
      <DataTable<Suggestion> id="suggested" rows={G.rows} onRow={(r) => open({ kind: "suggestion", handle: r.handle })}
        filters={[{ label: "Theme", get: (r) => r.themes }]} text={(r) => r.samples.map((s) => s.text).join(" ")}
        empty="No suggestions right now: every busy account is already watched or dismissed."
        cols={[
          { id: "handle", label: "Account", cell: (r) => <div><Ext url={xurl(r.handle)}>{r.handle}</Ext><div className="small muted">{r.name}</div></div> },
          { id: "hits", label: "Seen", num: true, cell: (r) => <b>{r.hits}×</b> },
          { id: "themes", label: "Themes", cell: (r) => <div className="chips">{r.themes.map((t) => <Theme key={t} tag={t} />)}</div> },
          { id: "followers", label: "Followers", num: true, cell: (r) => fmt(r.followers) },
          { id: "engagement", label: "Engagement", num: true },
          { id: "said", label: "What it posted", sort: false, get: (r) => r.samples[0]?.text || "", cell: (r) => <div className="cell-text excerpt">{clean(r.samples[0]?.text)}</div> },
          { id: "x", label: "", sort: false, cell: (r) => <WatchButtons s={r} /> },
        ]} />
      {D.length ? (
        <Section title="Dismissed" n={D.length} hint="Accounts you dismissed. Bring one back if you change your mind.">
          <DataTable<{ handle: string; at?: string }> id="dismissed" rows={D} search={false}
            cols={[{ id: "handle", label: "Account", cell: (r) => <Ext url={xurl(r.handle)}>{r.handle}</Ext> }, { id: "at", label: "Dismissed on" },
              { id: "x", label: "", sort: false, cell: (r) => <button className="btn small" onClick={() => act("/api/undismiss", { handle: r.handle, base: S.accounts?.watch_base }, `${r.handle} can be suggested again`)}>Suggest again</button> }]} />
        </Section>
      ) : null}
    </>
  );
}
