import { useState } from "react";
import { Heart, Repeat2, Undo2 } from "lucide-react";
import { postAct } from "../api";
import { useApp } from "../ctx";
import { when } from "../format";
import type { Reaction } from "../types";
import { About, Chip, Ext, PageHead, Section, Theme } from "../components/ui";

const KIND: Record<string, [string, string]> = { like: ["Like", "like"], repost: ["Repost", "repost"] };
const TIER: Record<string, string> = { institution: "a partner", peer: "an account we watch", other: "a reply to us" };
const CHANNEL: Record<string, string> = { x: "X", linkedin: "LinkedIn" };
/** The post, addressed by its id alone: no author's name is kept, so none is shown. */
const postUrl = (r: Reaction) => (r.channel === "x" && /^\d+$/.test(r.target_id) ? `https://x.com/i/web/status/${r.target_id}` : "");

/** One planned like or repost. `act` is the one thing a person can do with it here, if any. */
function Row({ r, act }: { r: Reaction; act: "send" | "undo" | null }) {
  const { reload, toast } = useApp();
  const [busy, setBusy] = useState(false);
  const [sure, setSure] = useState(false);
  const [said, setSaid] = useState<string | null>(null);
  const word = KIND[r.kind]?.[1] || r.kind;
  const send = async () => {
    setBusy(true);
    const res = await postAct("/api/react", { id: r.id, by: "alpha" });
    setBusy(false);
    const out = (res.data as { react?: { outcome?: string; reason?: string } } | undefined)?.react;
    if (!res.ok) { setSaid(res.error || "that did not work"); return; }
    if (out?.outcome !== "sent") { setSaid(out?.reason || "it was not sent"); await reload(); return; }
    toast(r.kind === "like" ? "Liked" : "Reposted"); await reload();
  };
  const undo = async () => {
    setBusy(true);
    const res = await postAct("/api/takedown", { id: r.id, by: "alpha" });
    setBusy(false);
    const out = (res.data as { takedown?: { outcome?: string; reason?: string } } | undefined)?.takedown;
    if (!res.ok) { setSaid(res.error || "that did not work"); return; }
    if (out?.outcome !== "taken down") { setSaid(out?.reason || "it could not be undone"); return; }
    toast(`The ${word} is undone`); await reload();
  };
  const url = postUrl(r);
  return (
    <tr>
      <td><Chip>{r.kind === "like" ? <Heart aria-hidden /> : <Repeat2 aria-hidden />}{KIND[r.kind]?.[0] || r.kind}</Chip> <Chip>{CHANNEL[r.channel] || r.channel}</Chip></td>
      <td>
        {url ? <Ext url={url}>the post</Ext> : <span className="mono">{r.target_id}</span>} by {TIER[r.tier] || r.tier}
        {r.reason ? <div className="small muted">{r.reason}</div> : null}
        {said ? <div className="approve-out no" role="status">{said}</div> : null}
      </td>
      <td>{r.theme ? <Theme tag={r.theme} /> : null}</td>
      <td style={{ whiteSpace: "nowrap" }} className="small muted">{r.undone ? `undone ${when(r.undone)}` : r.done_at ? when(r.done_at) : when(r.planned_at)}</td>
      <td style={{ textAlign: "right" }}>
        {act === "send" ? <button className="btn small primary" disabled={busy} onClick={send}>{busy ? "Sending…" : `${KIND[r.kind]?.[0] || "Send"} it`}</button> : null}
        {act === "undo" && !r.undone ? (sure ? (
          <span className="btns" style={{ justifyContent: "flex-end" }}>
            <button className="btn small primary" disabled={busy} onClick={undo}>{busy ? "Undoing…" : `Yes, undo the ${word}`}</button>
            <button className="btn small" disabled={busy} onClick={() => setSure(false)}>Keep it</button>
          </span>
        ) : <button className="btn small" onClick={() => setSure(true)}><Undo2 aria-hidden />Undo</button>) : null}
      </td>
    </tr>
  );
}

function Table({ rows, act, empty }: { rows: Reaction[]; act: "send" | "undo" | null; empty: string }) {
  if (!rows.length) return <div className="panel pad muted">{empty}</div>;
  return (
    <div className="panel tablewrap">
      <table className="modes sent">
        <thead><tr><th scope="col">What</th><th scope="col">On</th><th scope="col">Theme</th><th scope="col">When</th><th scope="col"><span className="sr">Action</span></th></tr></thead>
        <tbody>{rows.map((r) => <Row key={r.id} r={r} act={act} />)}</tbody>
      </table>
    </div>
  );
}

export function Engagement() {
  const { S } = useApp();
  const R = S.reactions;
  if (!R) return null;
  const earned = Object.entries(R.earned || {});
  return (
    <>
      <PageHead page="engagement" title="Engagement" meta={R.planned_at ? `planned ${when(R.planned_at)}` : "nothing planned yet"} />
      <About words={[["A partner", "An organisation on our cleared list, whose account someone checked."],
        ["An account we watch", "One you added on the Accounts page."],
        ["A reply to us", "Someone answered one of our own posts."],
        ["Daily limit", "The most likes or reposts in a day, per channel. It is set on the Setup page; with no number, none are sent."]]}>
        <p>Likes and reposts on other people's posts. The engine only proposes one on a post by a partner, by an account we watch, or on a reply to one of ours, and only after checking the post's words against the same private list as our own posts. It keeps the post's number, never who wrote it.</p>
        <p><b>A like on X always waits for your click</b>: X requires a like to come from a person. Reposts can go on their own where you switched that on (the Autonomy page), inside the daily limit. Every one can be undone here.</p>
      </About>
      <Section title="The rules now" hint={R.live ? "The scheduled sender is live." : "The scheduled sender is on a dry run: it checks everything and sends nothing. A click here still sends."}>
        <div className="panel pad">
          {R.rules.length ? (
            <div className="chips">
              {R.rules.map((x) => (
                <Chip key={`${x.stream}/${x.channel}/${x.kind}`} k={x.cap ? "" : "warning"}>
                  {x.name} · {x.label} · {x.kind === "like" ? "likes" : "reposts"}: {x.cap ? `up to ${x.cap} a day` : "none allowed"}, {x.click_only ? "each on your click" : x.mode === "auto" ? "automatic" : "each on your click"}
                </Chip>
              ))}
            </div>
          ) : <span className="muted">No stream has a channel that takes reactions yet.</span>}
        </div>
      </Section>
      <Section title="Waiting for your click" n={R.waiting.length}>
        <Table rows={R.waiting} act="send" empty="Nothing is waiting for you." />
      </Section>
      <Section title="Queued" n={R.queued.length} hint="The next run tries these. You can send one now.">
        <Table rows={R.queued} act="send" empty="Nothing is queued." />
      </Section>
      <Section title="Done" n={R.done.length}>
        <Table rows={R.done} act="undo" empty="No like or repost has gone out." />
      </Section>
      <Section title="Not sent" n={R.refused.length} hint="Considered and refused, each with the reason.">
        <Table rows={R.refused} act={null} empty="Nothing was refused." />
      </Section>
      {earned.length ? (
        <Section title="What they earned" hint="After three days: did the author reply or follow.">
          <div className="panel tablewrap">
            <table className="modes sent">
              <thead><tr><th scope="col">Whose post / what we did</th><th scope="col">Made</th><th scope="col">Author replied</th><th scope="col">Followed</th><th scope="col">Nothing</th><th scope="col">Too early</th></tr></thead>
              <tbody>{earned.map(([key, row]) => (
                <tr key={key}><th scope="row">{key}</th><td>{row.placed}</td><td>{row["author replied"]}</td><td>{row.follow}</td><td>{row.nothing}</td><td>{row.open}</td></tr>
              ))}</tbody>
            </table>
          </div>
        </Section>
      ) : null}
    </>
  );
}
