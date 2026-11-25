import { useState } from "react";
import { Power, ShieldAlert } from "lucide-react";
import { postAct } from "../api";
import { useApp } from "../ctx";
import { when } from "../format";
import type { SwitchRow } from "../types";
import { Chip, Field } from "./ui";

/** One auto-reply switch: a stream and a channel (the reply and comment modes of the review switch).
 *  Off by default and never looser than the stream's setup. Turning it on is a decision: a second click
 *  to confirm, with a reason if you want to leave one. Turning it off is one click. */
function Switch({ r }: { r: SwitchRow }) {
  const { reload, toast } = useApp();
  const id = `switch-${r.stream}-${r.channel}`;
  const [ask, setAsk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [said, setSaid] = useState<string | null>(null);
  const change = async (value: boolean) => {
    setBusy(true);
    const res = await postAct("/api/switch", { stream: r.stream, channel: r.channel, value, by: "alpha", reason: value ? reason : "", confirm: value });
    setBusy(false);
    const out = (res.data as { switch?: { outcome?: string } } | undefined)?.switch?.outcome || "";
    if (!res.ok) { setSaid(res.error || "that did not work"); return; }
    if (out.startsWith("refused: ")) { setSaid(out.slice(9)); return; }
    setSaid(null); setAsk(false); setReason("");
    toast(value ? `Auto-reply is on for ${r.name} on ${r.label}` : `Auto-reply is off for ${r.name} on ${r.label}`);
    await reload();
  };
  return (
    <div className="panel pad switch" data-switch={`${r.stream}/${r.channel}`}>
      <div className="switch-head">
        <b>{r.name} on {r.label}</b>
        {r.on ? <Chip k="warning"><Power aria-hidden />on</Chip> : <Chip k="good"><Power aria-hidden />off</Chip>}
        {!r.allowed ? <Chip title={r.why}><ShieldAlert aria-hidden />not allowed by streams.md</Chip> : null}
      </div>
      <div className="small muted">
        {r.stored
          ? <>Last changed by <b>{r.by}</b> on {when(r.at)}.{r.reason ? <> Reason: {r.reason}</> : null}</>
          : "Never changed: it has been off since the start."}
      </div>
      {!r.allowed ? <div className="small muted">It cannot be turned on. {r.why}</div> : null}
      {r.on ? <div className="small">While it is on, the engine may send a drafted {r.channel === "x" ? "reply" : "comment"} without your approval. The claim check, the quiet hours and the other checks still apply to each one.</div> : null}
      <div className="btns">
        {r.on ? <button className="btn" disabled={busy} onClick={() => change(false)}>Turn off</button> : null}
        {!r.on && r.allowed && !ask ? <button className="btn" onClick={() => setAsk(true)}>Turn on…</button> : null}
      </div>
      {ask ? (
        <div className="reason" aria-live="polite">
          <div className="small">This lets the engine send drafted {r.channel === "x" ? "replies" : "comments"} for {r.name} on {r.label} without asking you each time. Turning it off again takes effect on the very next send.</div>
          <Field htmlFor={`${id}-reason`}>Why you are turning it on (optional)</Field>
          <textarea id={`${id}-reason`} className="textarea reason-text" value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder="One or two sentences: what made you decide this." />
          <div className="btns">
            <button className="btn primary" disabled={busy} onClick={() => change(true)}>{busy ? "Turning on…" : `Yes, turn on auto-reply for ${r.label}`}</button>
            <button className="btn" disabled={busy} onClick={() => { setAsk(false); setSaid(null); }}>Cancel</button>
          </div>
        </div>
      ) : null}
      {said ? <div className="approve-out no" role="status">{said}</div> : null}
    </div>
  );
}

export function AutoReplySwitches({ rows }: { rows: SwitchRow[] }) {
  if (!rows.length) return <div className="panel pad muted">No stream has a channel that takes replies yet.</div>;
  return <div className="switches">{rows.map((r) => <Switch key={`${r.stream}/${r.channel}`} r={r} />)}</div>;
}
