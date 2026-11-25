import { useState } from "react";
import { Copy, Send, SquareArrowOutUpRight } from "lucide-react";
import { postAct } from "../api";
import { useApp } from "../ctx";
import { ReasonBox } from "../components/Approval";
import { About, Chip, Field, PageHead, Section, Theme } from "../components/ui";
import type { Proposal, SendOutcome } from "../types";

/** What the last send attempt did, in a few words. A refusal names the check that stopped it. */
export function sendNote(s: SendOutcome): { ok: boolean; text: string } {
  if (s.outcome === "sent") return { ok: true, text: s.url ? `Sent: ${s.url}` : "Sent." };
  if (s.outcome === "refused") return { ok: false, text: `Not sent. The ${s.check || "send"} check refused it: ${s.reason || "no reason given"}` };
  return { ok: false, text: `The send failed: ${s.reason || "no reason given"}. Check the account by hand before trying again.` };
}

/** Two clicks: record an approval for this exact text and send it as a reply (X) or comment (LinkedIn) now. */
function ApproveAndSend({ p }: { p: Proposal }) {
  const { reload, toast } = useApp();
  const [ask, setAsk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<{ ok: boolean; text: string } | null>(null);
  const [reasonText, setReasonText] = useState("");
  const [standing, setStanding] = useState(false);
  const word = p.platform === "LinkedIn" ? "comment" : "reply";
  const sent = p.send?.outcome === "sent";
  const go = async () => {
    setBusy(true);
    const r = await postAct("/api/approve-reply", { id: p.id, by: "alpha", reason: reasonText, scope: standing && reasonText.trim() ? "standing" : "item" });
    setBusy(false);
    setAsk(false);
    if (!r.ok) { setSaid({ ok: false, text: r.error || "that did not work" }); return; }
    const s = (r.data as { send?: SendOutcome } | undefined)?.send;
    if (s) { const n = sendNote(s); setSaid(n); if (n.ok) toast(`Your ${word} was sent`); }
    await reload();
  };
  const shown = said || (p.send ? sendNote(p.send) : null);
  return (
    <div className="approve" aria-live="polite">
      {!sent && !ask ? <button className="btn primary" disabled={busy || !p.id || !p.target_url} onClick={() => setAsk(true)}><Send aria-hidden />Approve and send</button> : null}
      {ask ? (
        <>
          <div className="small">This posts the {word} above to {p.platform} now, from our account, if every check passes. It cannot be taken back from here.</div>
          <ReasonBox id={`reply-${p.id}`} reason={reasonText} setReason={setReasonText} standing={standing} setStanding={setStanding} what={`sending this ${word}`} />
          <div className="btns" style={{ marginTop: 0 }}>
            <button className="btn primary" disabled={busy} onClick={go}><Send aria-hidden />{busy ? "Sending…" : `Yes, send this ${word}`}</button>
            <button className="btn" disabled={busy} onClick={() => setAsk(false)}>Cancel</button>
          </div>
        </>
      ) : null}
      {!p.target_url && !sent ? <div className="small muted">There is no post to answer, so it cannot be sent from here.</div> : null}
      {shown ? <div className={`approve-out ${shown.ok ? "ok" : "no"}`} role="status">{shown.text}</div> : null}
    </div>
  );
}

export function Replies() {
  const { S, toast } = useApp();
  const R = S.replies;
  const copy = (t: string) => navigator.clipboard?.writeText(t).then(() => toast("Copied: now open their post and paste it"), () => toast("Copy failed"));
  return (
    <>
      <PageHead page="replies" title="Replies" meta={`${R?.proposals.length || 0} written for you`} />
      <About><p>Replies the system wrote for other people's posts. Nothing is sent until you press <b>Approve and send</b>: that records your approval for this exact text and sends it at once, and the quiet hours, caps and the claim check still apply. The card then shows that it was sent, or the check that refused it. You can also copy our reply, open the post and reply as yourself.</p></About>
      {(R?.proposals || []).length ? R!.proposals.map((p, i) => (
        <div key={i} className="panel reply">
          <div className="chips"><Theme tag={p.theme} /><Chip>{p.platform}</Chip>{p.tier ? <Chip>{p.tier}</Chip> : null}</div>
          <Field>Their post{p.target_title ? `: ${p.target_title}` : ""}</Field>
          {p.target_text ? <div className="body">{p.target_text}</div> : <div className="small muted">The listener did not keep its text; open it to read it.</div>}
          <Field>Our reply</Field>
          <div className="body" style={{ background: "var(--surface)", border: "2px solid var(--line)" }}>{p.draft_comment}</div>
          <div className="small muted" style={{ marginTop: 10 }}>Why: {p.why}</div>
          <div className="btns">
            <button className="btn primary" onClick={() => copy(p.draft_comment)}><Copy aria-hidden />Copy our reply</button>
            {p.target_url ? <a className="btn" href={p.target_url} target="_blank" rel="noopener noreferrer"><SquareArrowOutUpRight aria-hidden />Open their post</a> : null}
          </div>
          <ApproveAndSend p={p} />
        </div>
      )) : <div className="panel pad muted">No replies waiting.</div>}
      {R?.inbound?.note ? <Section title="Replies to our own posts"><div className="panel pad small">{R.inbound.note}</div></Section> : null}
    </>
  );
}
