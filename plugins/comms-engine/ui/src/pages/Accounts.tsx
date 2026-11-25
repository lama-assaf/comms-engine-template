import { useApp } from "../ctx";
import { xurl } from "../format";
import type { HandleRow, Watched } from "../types";
import { AutoReplySwitches } from "../components/AutoReply";
import { DataTable } from "../components/DataTable";
import { About, Chip, Ext, PageHead, Section, Theme } from "../components/ui";

const Status = ({ s }: { s?: string }) =>
  s === "verified" ? <Chip k="good">confirmed</Chip> : s === "collect" ? <Chip k="warning">to confirm</Chip> : <Chip>{s}</Chip>;

export function Accounts() {
  const { S, act } = useApp();
  const A = S.accounts;
  if (!A) return null;
  return (
    <>
      <PageHead page="accounts" title="Accounts" meta="who we keep an eye on" />
      <About words={[["To confirm", "We think this is the right account but nobody has checked the live profile yet."], ["Confirmed", "Someone checked the live profile."],
        ["Partner", "An organisation we may tag in posts, because they cleared it."], ["Standards body", "An organisation we may quote, never claim as a partner."]]}>
        <p>The accounts the listener follows. <b>Watched accounts</b> are yours: add any X account here and the listener checks its posts on every run. Remove it when it stops being useful.</p>
        <p>Our own channels, partners and standards bodies come from our list of handles, kept with the engine's memory. They change there, not here. We also keep a private list of names we must not mention yet; it is {A.private.present
          ? <>in place ({A.private.terms} names), and never shown here.</> : <><b>missing</b>, so every post is stopped until it is restored.</>}</p>
      </About>
      <Section title="Accounts we watch" n={`${A.watched.length} of ${A.watch_max}`}>
        <DataTable<Watched> id="watched" rows={A.watched} filters={[{ label: "Theme", get: (r) => r.themes }, { label: "Added from", get: (r) => r.from }]}
          empty="No watched accounts yet. Type one in the row below, or watch one from Suggestions."
          add={{ label: "Watch an account", fields: [{ key: "handle", placeholder: "@account" }, { key: "themes", placeholder: "#Theme (optional)" }, { key: "note", placeholder: "why we watch it (optional)", grow: 2 }],
            submit: (v) => act("/api/watch", { handle: v.handle, themes: (v.themes || "").split(",").map((s) => s.trim()).filter(Boolean), note: v.note, base: A.watch_base }, `${v.handle} is now watched`) }}
          cols={[
            { id: "handle", label: "Account", cell: (r) => <Ext url={xurl(r.handle)}>{r.handle}</Ext> },
            { id: "themes", label: "Themes", cell: (r) => <div className="chips">{(r.themes || []).map((t) => <Theme key={t} tag={t} />)}</div> },
            { id: "note", label: "Why" }, { id: "added", label: "Added" }, { id: "from", label: "Added from" },
            { id: "x", label: "", sort: false, cell: (r) => <button className="btn small" onClick={() => act("/api/unwatch", { handle: r.handle, base: A.watch_base }, `${r.handle} is no longer watched`)}>Stop watching</button> },
          ]} />
      </Section>
      <Section title="Partners" hint="Organisations that cleared us to name and tag them.">
        <DataTable<HandleRow> id="partners" rows={A.partners} filters={[{ label: "Status", get: (r) => r.status }, { label: "Clearance", get: (r) => r.clearance }]}
          cols={[{ id: "partner", label: "Partner", cell: (r) => <b>{r.partner}</b> }, { id: "x", label: "On X" }, { id: "linkedin", label: "On LinkedIn" },
            { id: "themes", label: "Themes", cell: (r) => <span className="small">{r.themes}</span> }, { id: "status", label: "Status", cell: (r) => <Status s={r.status} /> },
            { id: "last_verified", label: "Last checked" }]} />
      </Section>
      <Section title="Our own channels">
        <DataTable<HandleRow> id="own" rows={A.own} search={false}
          cols={[{ id: "brand", label: "Brand", cell: (r) => <b>{r.brand}</b> }, { id: "platform", label: "Channel" }, { id: "handle", label: "Account" },
            { id: "status", label: "Status", cell: (r) => <Status s={r.status} /> }, { id: "last_verified", label: "Last checked" }]} />
      </Section>
      <Section title="Auto-reply" hint="Off unless you turn it on, per stream and channel. It can never allow more than the stream\u2019s setup. Every other kind of send is on the Autonomy page.">
        <AutoReplySwitches rows={A.switches || []} />
      </Section>
      <Section title="Standards bodies" hint="We quote them; we never call them partners.">
        <DataTable<HandleRow> id="standards" rows={A.standards} search={false}
          cols={[{ id: "body", label: "Organisation", cell: (r) => <b>{r.body}</b> }, { id: "x", label: "On X" }, { id: "themes", label: "Themes" },
            { id: "status", label: "Status", cell: (r) => <Status s={r.status} /> }, { id: "last_verified", label: "Last checked" }]} />
      </Section>
    </>
  );
}
