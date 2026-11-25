import { useState } from "react";
import { CalendarCheck, ShieldCheck } from "lucide-react";
import { postAct } from "../api";
import { useApp } from "../ctx";
import { day } from "../format";
import type { Post } from "../types";
import { Chip, Field } from "./ui";

const MOVED = ["decided", "scheduled", "sent", "scored", "retired"];
const reason = (o: string) => o.replace(/^refused: /, "");

/** What the last approve act did to a post, in a few words: its chip and the sentence under it. */
export function approvalOf(p: Post): { word: string; kind: string; note: string } | null {
  const a = p.act;
  if (!a) return null;
  if (a.state === "scheduled" && a.outcome !== "refused") return { word: `Scheduled ${day(a.date || p.date)}`, kind: "good", note: "Approved and scheduled. The sender posts it on that day, within the guardrails; approving never sends." };
  if (a.state === "sent" || a.state === "scored") return { word: "Sent", kind: "good", note: "The sender has put it out." };
  if (a.outcome?.startsWith("refused")) return { word: "Approval refused", kind: "warning", note: `Not scheduled: ${reason(a.outcome)}` };
  if (a.outcome?.startsWith("skipped")) return { word: "Already moved", kind: "", note: "The post had already moved on, so nothing changed." };
  return null;
}

export function ApprovalChip({ p }: { p: Post }) {
  const a = approvalOf(p);
  if (!a) return <span className="muted small">not approved</span>;
  return <Chip k={a.kind} title={a.note}>{a.word}</Chip>;
}

/** An approval needs no written reason (owner decision, 2026-11-11; a hold, a rejection and a rewrite still do).
 *  A reason typed here is stored, and can be kept as a standing rule that the drafting agents read next cycle (it
 *  reaches reviews.md through the desk's pull, not from here). The standing option opens once a reason is typed. */
export function ReasonBox({ id, reason, setReason, standing, setStanding, what }: {
  id: string; reason: string; setReason: (v: string) => void; standing: boolean; setStanding: (v: boolean) => void; what: string;
}) {
  return (
    <div className="reason">
      <Field htmlFor={`${id}-reason`}>Why you are {what} (optional)</Field>
      <textarea id={`${id}-reason`} className="textarea reason-text" value={reason} onChange={(e) => setReason(e.target.value)}
        placeholder="Optional. One or two sentences: what made you decide this." />
      <label className="reason-standing">
        <input type="checkbox" checked={standing && Boolean(reason.trim())} disabled={!reason.trim()} onChange={(e) => setStanding(e.target.checked)} />
        <span>Keep this as a standing rule. The writer and the checker read it before every later draft, not only this one.</span>
      </label>
    </div>
  );
}

/** Two steps, as on the desk: confirm the hook and the claim (your act), then approve (a reason is optional).
 *  Approving records the decision and puts the post in the schedule for its day. It never sends. */
export function ApprovePost({ p }: { p: Post }) {
  const { reload, toast } = useApp();
  const [busy, setBusy] = useState(false);
  const [reasonText, setReasonText] = useState("");
  const [standing, setStanding] = useState(false);
  const [said, setSaid] = useState<{ ok: boolean; text: string } | null>(null);
  const done = Boolean(p.published_to?.length) || MOVED.includes(p.act?.state || "");
  const blocked = p.gate === "block";
  const confirmed = Boolean(p.argument?.current);
  const shown = approvalOf(p);
  const confirm = async () => {
    setBusy(true);
    const r = await postAct("/api/confirm-argument", { id: p.id, by: "alpha" });
    setBusy(false);
    if (!r.ok) { setSaid({ ok: false, text: r.error || "that did not work" }); return; }
    setSaid({ ok: true, text: "Hook and claim confirmed. You can approve now." });
    toast("Hook and claim confirmed");
    await reload();
  };
  const go = async () => {
    setBusy(true);
    const r = await postAct("/api/approve", { id: p.id, by: "alpha", reason: reasonText, scope: standing && reasonText.trim() ? "standing" : "item" });
    setBusy(false);
    if (!r.ok) { setSaid({ ok: false, text: r.error || "that did not work" }); return; }
    const out = String((r.data as { act?: { outcome?: string } } | undefined)?.act?.outcome || "");
    if (out === "applied") { setSaid({ ok: true, text: standing && reasonText.trim() ? "Approved and scheduled. Your reason is kept as a standing rule once the desk is pulled. Nothing was sent." : "Approved and scheduled. Nothing was sent." }); toast("Scheduled for its day"); setReasonText(""); }
    else setSaid({ ok: false, text: out.startsWith("refused") ? `Not scheduled: ${reason(out)}` : "The post had already moved on; nothing changed." });
    await reload();
  };
  return (
    <div className="approve" aria-live="polite">
      {!done && !blocked ? (
        <div className="confirm-arg">
          <div className="confirm-head"><ShieldCheck aria-hidden />{confirmed ? "Hook and claim confirmed" : "Confirm the hook and claim"}</div>
          <div className="confirm-line"><b>Hook</b><span>{p.hook || p.title}</span></div>
          <div className="confirm-line"><b>Claim</b><span>{p.claim || <i>no claim written on this post</i>}</span></div>
          {!confirmed ? (
            <>
              <div className="small muted">The hook and the claim are your act, not the writer's. Confirming records that you read exactly these words. Change the hook later and this has to be done again.</div>
              <button className="btn" disabled={busy} onClick={confirm}><ShieldCheck aria-hidden />{busy ? "Confirming…" : "Confirm the hook and claim"}</button>
            </>
          ) : null}
        </div>
      ) : null}
      {!done ? <ReasonBox id={`approve-${p.id}`} reason={reasonText} setReason={setReasonText} standing={standing} setStanding={setStanding} what="approving it" /> : null}
      {!done ? (
        <button className="btn primary" disabled={busy || blocked || !p.date || !confirmed} onClick={go}><CalendarCheck aria-hidden />{busy ? "Approving…" : "Approve and schedule for its day"}</button>
      ) : null}
      {blocked && !done ? <div className="small muted">A check stopped this post; it cannot be approved until that is fixed.</div> : null}
      {!done && !blocked && !confirmed ? <div className="small muted">Approving opens once the hook and claim are confirmed.</div> : null}
      {!done ? <div className="small muted">Records your approval and puts the post in the schedule for {p.date ? day(p.date) : "its day"}. It does not send anything.</div> : null}
      {said ? <div className={`approve-out ${said.ok ? "ok" : "no"}`} role="status">{said.text}</div>
        : shown ? <div className={`approve-out ${shown.kind === "warning" ? "no" : "ok"}`}>{shown.note}</div> : null}
    </div>
  );
}
