import { useState } from "react";
import { Pause, Play, ShieldAlert, Trash2 } from "lucide-react";
import { postAct } from "../api";
import { useApp } from "../ctx";
import { when } from "../format";
import type { ModeRow, PolicyStream, Unreviewed } from "../types";
import { About, Chip, Ext, PageHead, Section } from "../components/ui";

const KIND_WORDS: Record<string, [string, string]> = {
  post: ["Posts", "a post on its scheduled day"],
  reply: ["Replies", "a drafted reply"],
  comment: ["Comments", "a drafted comment"],
  like: ["Likes", "a like on someone else's post"],
  repost: ["Reposts", "a repost of someone else's post"],
  quote: ["Quote posts", "a post that quotes someone else's"],
  hold: ["Statistics and named partners", "a text with a statistic, a named partner or a certification word"],
};
const PRESET_WORDS: Record<string, [string, string]> = {
  "review-everything": ["Review everything", "Nothing goes out until you approve it."],
  "review-posts-only": ["Review posts only", "You approve posts, quote posts and anything with a statistic or a named partner. Replies, comments, likes and reposts go out on their own."],
  "fully-automatic": ["Fully automatic", "Everything that passes the automatic checks goes out. Nothing waits for you."],
};
const outcomeOf = (data: unknown, key: string) => ((data as Record<string, { outcome?: string }> | undefined)?.[key]?.outcome || "");

/** One stream: its pause, the three presets, and a switch per channel and kind of send. */
function StreamPolicy({ p }: { p: PolicyStream }) {
  const { reload, toast } = useApp();
  const [busy, setBusy] = useState(false);
  const [ask, setAsk] = useState<{ what: string; yes: string; run: () => Promise<void> } | null>(null);
  const [said, setSaid] = useState<string | null>(null);

  const done = async (ok: boolean, error: string | undefined, outcome: string, message: string) => {
    setBusy(false);
    if (!ok) { setSaid(error || "that did not work"); return; }
    if (outcome.startsWith("refused: ")) { setSaid(outcome.slice(9)); return; }
    setSaid(null); setAsk(null); toast(message); await reload();
  };
  const setMode = async (channel: string, label: string, k: ModeRow, mode: "review" | "auto") => {
    setBusy(true);
    const r = await postAct("/api/switch", { stream: p.stream, channel, kind: k.kind, mode, by: "alpha", confirm: mode === "auto" });
    await done(r.ok, r.error, outcomeOf(r.data, "switch"), `${KIND_WORDS[k.kind]?.[0] || k.kind} on ${label}: ${mode === "auto" ? "automatic" : "you review"}`);
  };
  const setPreset = async (name: string) => {
    setBusy(true);
    const r = await postAct("/api/switch", { stream: p.stream, preset: name, by: "alpha", confirm: true });
    const changes = ((r.data as { switch?: { changes?: { outcome?: string }[] } } | undefined)?.switch?.changes || []);
    const refused = changes.find((c) => (c.outcome || "").startsWith("refused: "));
    await done(r.ok, r.error, refused?.outcome || "", `${p.name}: ${PRESET_WORDS[name]?.[0] || name}`);
  };
  const setPause = async (paused: boolean) => {
    setBusy(true);
    const r = await postAct("/api/pause", { stream: p.stream, paused, by: "alpha", confirm: !paused });
    await done(r.ok, r.error, outcomeOf(r.data, "pause"), paused ? `Every send of ${p.name} is paused` : `${p.name} is sending again`);
  };
  const canSwitch = p.channels.some((c) => c.kinds.some((k) => k.allowed));

  return (
    <div className="panel pad policy" data-policy={p.stream}>
      <div className="switch-head">
        <b>{p.name}</b>
        {p.paused ? <Chip k="critical"><Pause aria-hidden />paused</Chip> : <Chip k="good"><Play aria-hidden />sending</Chip>}
        <Chip title="The stream's autopilot setting, changed on the Setup page">autopilot: {p.autopilot || "nothing"}</Chip>
        {p.owner !== "confirmed" ? <Chip k="warning">owner not confirmed</Chip> : null}
      </div>
      {p.paused
        ? <div className="small">Nothing of {p.name} goes out while it is paused{p.pause.at ? <> (since {when(p.pause.at)}, by {p.pause.by})</> : null}. You can still take a sent post down.</div>
        : <div className="small muted">Pausing stops every send of {p.name} at once, whatever is switched on below. It takes effect on the very next send.</div>}
      <div className="btns">
        {p.paused
          ? <button className="btn" disabled={busy} onClick={() => setAsk({ what: `Resume sending for ${p.name}? Everything that was stopped may go out again.`, yes: "Yes, resume", run: () => setPause(false) })}><Play aria-hidden />Resume…</button>
          : <button className="btn dark" disabled={busy} onClick={() => setPause(true)}><Pause aria-hidden />Pause every send</button>}
      </div>

      {!canSwitch ? (
        <div className="approve-out no" role="note">
          <ShieldAlert aria-hidden size={16} /> Nothing can be switched to automatic for {p.name} yet. {p.channels[0]?.kinds.find((k) => !k.allowed)?.why || "It has no channel of its own yet."}
        </div>
      ) : (
        <>
          <h3 className="policy-h">One choice for everything</h3>
          <div className="presets" role="group" aria-label={`Presets for ${p.name}`}>
            {Object.entries(PRESET_WORDS).map(([name, [label, text]]) => (
              <button key={name} className={`preset ${p.preset === name ? "on" : ""}`} aria-pressed={p.preset === name} disabled={busy}
                onClick={() => name === "review-everything" ? setPreset(name) : setAsk({ what: `${label} for ${p.name}? ${text}`, yes: `Yes, ${label.toLowerCase()}`, run: () => setPreset(name) })}>
                <b>{label}</b><span>{text}</span>
              </button>
            ))}
          </div>
          <h3 className="policy-h">Or choose per kind of send</h3>
          <div className="tablewrap">
            <table className="modes">
              <thead><tr><th scope="col">Kind of send</th>{p.channels.map((c) => <th key={c.channel} scope="col">{c.label}</th>)}</tr></thead>
              <tbody>
                {(p.channels[0]?.kinds || []).map((row, i) => (
                  <tr key={row.kind}>
                    <th scope="row">{KIND_WORDS[row.kind]?.[0] || row.kind}<div className="small muted">{KIND_WORDS[row.kind]?.[1]}</div></th>
                    {p.channels.map((c) => {
                      const k = c.kinds[i];
                      const auto = k.mode === "auto";
                      const what = `${KIND_WORDS[k.kind]?.[0] || k.kind} on ${c.label}`;
                      return (
                        <td key={c.channel}>
                          <button className={`mode ${auto ? "auto" : "review"}`} role="switch" aria-checked={auto} aria-label={`${what}: ${auto ? "automatic" : "you review"}`}
                            disabled={busy || (!auto && !k.allowed)} title={!k.allowed ? k.why : undefined}
                            onClick={() => auto ? setMode(c.channel, c.label, k, "review")
                              : setAsk({ what: `Switch ${what.toLowerCase()} to automatic? Then ${KIND_WORDS[k.kind]?.[1] || "it"} goes out when it passes the automatic checks, without anyone reading it first.`, yes: "Yes, make it automatic", run: () => setMode(c.channel, c.label, k, "auto") })}>
                            {auto ? "Automatic" : "You review"}
                          </button>
                          {k.wanted === "auto" && !k.allowed ? <div className="small muted">switched on, but not allowed now</div> : null}
                          {k.stored ? <div className="small muted">{k.by}, {when(k.at)}</div> : null}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {ask ? (
        <div className="reason confirm-box" role="alertdialog" aria-live="polite" aria-label="Confirm">
          <div>{ask.what}</div>
          <div className="btns">
            <button className="btn primary" disabled={busy} onClick={ask.run}>{busy ? "Working…" : ask.yes}</button>
            <button className="btn" disabled={busy} onClick={() => { setAsk(null); setSaid(null); }}>Cancel</button>
          </div>
        </div>
      ) : null}
      {said ? <div className="approve-out no" role="status">{said}</div> : null}
    </div>
  );
}

/** One thing that went out with nobody reading it first, and the button that takes it down. */
function Sent({ u }: { u: Unreviewed }) {
  const { reload, toast } = useApp();
  const [sure, setSure] = useState(false);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState<string | null>(null);
  const down = async () => {
    setBusy(true);
    const r = await postAct("/api/takedown", { id: u.id, by: "alpha" });
    setBusy(false);
    const t = (r.data as { takedown?: { outcome?: string; reason?: string } } | undefined)?.takedown;
    if (!r.ok) { setSaid(r.error || "that did not work"); return; }
    if (t?.outcome !== "taken down") { setSaid(t?.reason || "it could not be taken down"); return; }
    toast("Taken down"); await reload();
  };
  return (
    <tr>
      <td style={{ whiteSpace: "nowrap" }}>{when(u.at)}</td>
      <td><Chip>{u.channel === "x" ? "X" : u.channel === "linkedin" ? "LinkedIn" : u.channel}</Chip> <Chip>{u.kind}</Chip></td>
      <td>{u.url ? <Ext url={u.url}>{u.title}</Ext> : u.title}{said ? <div className="approve-out no" role="status">{said}</div> : null}</td>
      <td style={{ textAlign: "right" }}>
        {u.taken_down ? <span className="small muted">taken down {when(u.taken_down)}</span>
          : sure ? (
            <span className="btns" style={{ justifyContent: "flex-end" }}>
              <button className="btn small primary" disabled={busy} onClick={down}>{busy ? "Taking down…" : "Yes, delete it"}</button>
              <button className="btn small" disabled={busy} onClick={() => setSure(false)}>Keep it</button>
            </span>
          ) : <button className="btn small" onClick={() => setSure(true)}><Trash2 aria-hidden />Take down</button>}
      </td>
    </tr>
  );
}

export function Autonomy() {
  const { S } = useApp();
  const P = S.policy;
  if (!P) return null;
  return (
    <>
      <PageHead page="autonomy" title="Autonomy" meta="what may go out without you" />
      <About words={[["You review", "It waits here until you approve it. This is how every kind of send starts."],
        ["Automatic", "It goes out when it passes the automatic checks. What fails a check stays in the queue for you."],
        ["Automatic checks", "The claim check with its sources, the private list of names we must not mention, the stream's own account, no duplicates, the daily limits and the quiet hours. They run in both modes and cannot be switched off."],
        ["Pause", "Stops every send of a stream at once. Taking a post down still works."]]}>
        <p>For each stream you choose, per channel and per kind of send, whether it waits for you or goes out on its own. Everything starts on <b>You review</b>. Switching something to <b>Automatic</b> takes one confirmation and is recorded with the time; switching it back is one click and holds from the very next send.</p>
        <p>A stream can only be switched once its owner is confirmed and its autopilot setting says <span className="mono">by switch</span>. Both are on the Setup page.</p>
      </About>
      <Section title="Streams">
        <div className="switches">{P.streams.map((p) => <StreamPolicy key={p.stream} p={p} />)}</div>
      </Section>
      <Section title="Sent without review" n={P.unreviewed.length} hint="What went out with nobody reading it first. Taking one down deletes it on the channel; its text is never sent again.">
        {P.unreviewed.length ? (
          <div className="panel tablewrap">
            <table className="modes sent">
              <thead><tr><th scope="col">When</th><th scope="col">Where</th><th scope="col">What</th><th scope="col"><span className="sr">Take down</span></th></tr></thead>
              <tbody>{P.unreviewed.map((u) => <Sent key={u.id} u={u} />)}</tbody>
            </table>
          </div>
        ) : <div className="panel pad muted">Nothing has gone out without review.</div>}
      </Section>
    </>
  );
}
