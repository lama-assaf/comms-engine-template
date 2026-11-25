import { useMemo, useState } from "react";
import { Check, CircleAlert } from "lucide-react";
import { useApp } from "../ctx";
import type { SetupFile, SetupStream } from "../types";
import { About, Chip, Field, PageHead, Section } from "../components/ui";

const CHANNEL_WORDS: Record<string, [string, string]> = { x: ["X handle", "@name"], linkedin: ["LinkedIn page", "linkedin.com/company/name"], website: ["Website", "example.com"] };
const KIND_WORDS: Record<string, string> = { post: "Posts", reply: "Replies", comment: "Comments", like: "Likes", repost: "Reposts", quote: "Quote posts", hold: "Statistics and named partners" };
const DRIVER_WORDS: Record<string, string> = { write: "Posts are sent through", x_read: "X is listened to through", x_own: "Our own X numbers come from" };
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const num = (v: string) => (v.trim() === "" ? 0 : Math.max(0, Math.floor(Number(v) || 0)));

/** The fields of one stream. Text where the file holds text, small forms where it holds a structure. */
function StreamForm({ slug, row, set, opts }: { slug: string; row: SetupStream; set: (patch: Partial<SetupStream>) => void; opts: SetupFile["options"] }) {
  const id = (k: string) => `setup-${slug}-${k}`;
  const channels = row.channels;
  const posts = row.posts_per_day;
  const reactions = row.reactions_per_day || {};
  const review = row.review || {};
  const autopilots = [...new Set([...(opts.autopilot || []), row.autopilot || "nothing"])];
  return (
    <div className="panel pad setup-form">
      <div className="grid2">
        <div>
          <Field htmlFor={id("narrator")}>How it speaks (one register)</Field>
          <input id={id("narrator")} className="input" value={row.narrator || ""} onChange={(e) => set({ narrator: e.target.value })} />
        </div>
        <div>
          <Field htmlFor={id("owner")}>Owner</Field>
          <select id={id("owner")} className="select" value={row.owner || "unset"} onChange={(e) => set({ owner: e.target.value })}>
            {(opts.owner || ["unset", "confirmed"]).map((o) => <option key={o} value={o}>{o === "confirmed" ? "confirmed" : "not confirmed yet"}</option>)}
          </select>
          <div className="small muted">Never a name. Until it is confirmed the stream drafts and sends nothing.</div>
        </div>
        <div>
          <Field htmlFor={id("autopilot")}>May anything go out without a person</Field>
          <select id={id("autopilot")} className="select" value={row.autopilot || "nothing"} onChange={(e) => set({ autopilot: e.target.value })}>
            {autopilots.map((o) => <option key={o} value={o}>{o === "nothing" ? "No: drafts only" : o === "by switch" ? "Yes, where the Autonomy page says so" : o}</option>)}
          </select>
        </div>
        <div>
          <Field htmlFor={id("quiet")}>Quiet hours</Field>
          <input id={id("quiet")} className="input" value={row.quiet_hours || ""} placeholder="weekends; before 08:00 and after 18:00" onChange={(e) => set({ quiet_hours: e.target.value })} />
          <div className="small muted">“all hours until onboarded” blocks every send.</div>
        </div>
        <div>
          <Field htmlFor={id("drafts")}>Channels that never send</Field>
          <input id={id("drafts")} className="input" value={Array.isArray(row.drafts_only) ? row.drafts_only.join(", ") : row.drafts_only || ""} placeholder="all, none, or Blog, X"
            onChange={(e) => set({ drafts_only: e.target.value })} />
        </div>
      </div>

      <h3 className="policy-h">Channels</h3>
      {typeof channels === "string" ? (
        <><Field htmlFor={id("channels")}>The stream's own handles</Field>
          <input id={id("channels")} className="input" value={channels} onChange={(e) => set({ channels: e.target.value })} /></>
      ) : (
        <div className="grid2">
          {Object.entries(CHANNEL_WORDS).map(([key, [label, hint]]) => (
            <div key={key}>
              <Field htmlFor={id(`ch-${key}`)}>{label}</Field>
              <input id={id(`ch-${key}`)} className="input" value={(channels || {})[key] || ""} placeholder={hint}
                onChange={(e) => { const next = { ...(channels || {}) }; if (e.target.value.trim()) next[key] = e.target.value.trim(); else delete next[key]; set({ channels: next }); }} />
            </div>
          ))}
        </div>
      )}

      <h3 className="policy-h">Limits per day</h3>
      {typeof posts === "string" ? (
        <><Field htmlFor={id("posts")}>Posts per channel per day</Field>
          <input id={id("posts")} className="input" value={posts} onChange={(e) => set({ posts_per_day: e.target.value })} /></>
      ) : (
        <div className="grid4">
          {([["x", "Posts on X"], ["linkedin", "Posts on LinkedIn"], ["blog_per_week", "Blogs per week"], ["blog_days_apart", "Days between blogs"]] as const).map(([key, label]) => (
            <div key={key}>
              <Field htmlFor={id(`p-${key}`)}>{label}</Field>
              <input id={id(`p-${key}`)} className="input" type="number" min={0} inputMode="numeric" value={(posts || {})[key] ?? 0}
                onChange={(e) => set({ posts_per_day: { ...(posts || {}), [key]: num(e.target.value) } })} />
            </div>
          ))}
        </div>
      )}
      <div className="grid4">
        {(["x", "linkedin"] as const).flatMap((ch) => (["like", "repost"] as const).map((kind) => (
          <div key={`${ch}-${kind}`}>
            <Field htmlFor={id(`r-${ch}-${kind}`)}>{kind === "like" ? "Likes" : "Reposts"} on {ch === "x" ? "X" : "LinkedIn"}</Field>
            <input id={id(`r-${ch}-${kind}`)} className="input" type="number" min={0} inputMode="numeric" value={reactions[ch]?.[kind] ?? 0}
              onChange={(e) => set({ reactions_per_day: { ...reactions, [ch]: { ...(reactions[ch] || {}), [kind]: num(e.target.value) } } })} />
          </div>
        )))}
      </div>

      <h3 className="policy-h">Where each kind of send starts</h3>
      <div className="small muted">The starting mode on every channel. A switch made on the Autonomy page wins over it.</div>
      <div className="grid4">
        {(opts.kinds || []).map((kind) => {
          const v = review[kind];
          const perChannel = typeof v === "object" && v !== null;
          return (
            <div key={kind}>
              <Field htmlFor={id(`m-${kind}`)}>{KIND_WORDS[kind] || kind}</Field>
              {perChannel ? <div className="small muted">set per channel in the file</div> : (
                <select id={id(`m-${kind}`)} className="select" value={(v as string) || "review"} onChange={(e) => set({ review: { ...review, [kind]: e.target.value } })}>
                  <option value="review">You review</option><option value="auto">Automatic</option>
                </select>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function Setup() {
  const { S, act } = useApp();
  const U = S.setup;
  const F = U?.file;
  const [streams, setStreams] = useState<Record<string, SetupStream>>(F?.streams || {});
  const [drivers, setDrivers] = useState<Record<string, string>>(F?.drivers || {});
  const [jobs, setJobs] = useState<Record<string, boolean>>(F?.jobs || {});
  const [sure, setSure] = useState(false);
  const [busy, setBusy] = useState(false);
  const [base, setBase] = useState(F?.base || "");
  // a save or a reload brings a new file: start again from what it holds
  if (F && F.base !== base) { setBase(F.base); setStreams(F.streams); setDrivers(F.drivers); setJobs(F.jobs); setSure(false); }

  const changes = useMemo(() => {
    if (!F) return {};
    const out: Record<string, unknown> = {};
    const s: Record<string, Record<string, unknown>> = {};
    for (const [slug, row] of Object.entries(streams)) {
      const was = (F.streams[slug] || {}) as Record<string, unknown>;
      for (const [k, v] of Object.entries(row as Record<string, unknown>)) if (!same(v, was[k])) (s[slug] ||= {})[k] = v;
    }
    if (Object.keys(s).length) out.streams = s;
    const d = Object.fromEntries(Object.entries(drivers).filter(([k, v]) => v !== F.drivers[k]));
    if (Object.keys(d).length) out.drivers = d;
    const j = Object.fromEntries(Object.entries(jobs).filter(([k, v]) => v !== F.jobs[k]));
    if (Object.keys(j).length) out.jobs = j;
    return out;
  }, [F, streams, drivers, jobs]);
  if (!U || !F) return null;
  const dirty = Object.keys(changes).length > 0;
  const save = async () => {
    setBusy(true);
    await act("/api/setup", { changes, base: F.base, by: "alpha", confirm: true }, "Setup saved");
    setBusy(false); setSure(false);
  };

  return (
    <>
      <PageHead page="setup" title="Setup" meta="who the brand is and what it may do" />
      <About words={[["Setup file", "One small file, brand.json, holds everything on this page. This page writes it; nobody has to open it."],
        ["Owner", "Whether a person has taken responsibility for the stream. It says confirmed or not, never who."],
        ["Stream", "One voice the engine speaks in, with its own channels and rules. Most brands have one."]]}>
        <p>Everything a new project has to decide is here: how the brand speaks, where it posts, how much, and whether anything may go out without a person. A change is checked before it is saved and recorded with the time. The brand's short name is set once, with <span className="mono">engine.py init</span>.</p>
      </About>

      <Section title="Getting started" n={`${U.done} of ${U.total}`}>
        <div className="panel pad">
          <ol className="steps">
            {U.steps.map((st) => (
              <li key={st.id} className={st.done ? "done" : ""}>
                <span className="tick" aria-hidden>{st.done ? <Check size={16} /> : <CircleAlert size={16} />}</span>
                <div>
                  <b>{st.title}</b>{st.optional ? <span className="small muted"> (optional)</span> : null}
                  <div className="small muted">{st.done ? st.detail : st.why}</div>
                  {!st.done ? <div className="mono cmd">{st.command}</div> : null}
                </div>
              </li>
            ))}
          </ol>
        </div>
      </Section>

      {!F.present ? (
        <Section title="The setup file"><div className="panel pad">There is no brand.json yet. Run <span className="mono">engine.py init</span> once; it asks a few questions and writes it.</div></Section>
      ) : (
        <>
          {F.problems.length ? <div className="errors" role="alert">The setup file has problems: {F.problems.join(" · ")}</div> : null}
          {!F.in_sync && !F.problems.length ? <div className="errors" role="alert">The engine's registry is out of date with the setup file. Saving any change here brings it back in line, or run <span className="mono">engine.py apply</span>.</div> : null}
          {Object.entries(streams).map(([slug, row]) => (
            <Section key={slug} title={row.name || slug} hint={<>Stream <span className="mono">{slug}</span>{slug === F.brand.slug ? ", the brand's own" : ""}</>}>
              <StreamForm slug={slug} row={row} opts={F.options} set={(patch) => setStreams((cur) => ({ ...cur, [slug]: { ...cur[slug], ...patch } }))} />
            </Section>
          ))}
          <Section title="How it connects">
            <div className="panel pad setup-form">
              <div className="grid4">
                {Object.entries(F.options.drivers || {}).map(([key, values]) => (
                  <div key={key}>
                    <Field htmlFor={`setup-driver-${key}`}>{DRIVER_WORDS[key] || key}</Field>
                    <select id={`setup-driver-${key}`} className="select" value={drivers[key] || values[0]} onChange={(e) => setDrivers((cur) => ({ ...cur, [key]: e.target.value }))}>
                      {values.map((v) => <option key={v} value={v}>{v}</option>)}
                    </select>
                  </div>
                ))}
              </div>
              <h3 className="policy-h">Scheduled jobs</h3>
              <div className="small muted">A job switched off here is left out when the schedule is installed. Loading and unloading is the engine console's (/engine).</div>
              <div className="checks">
                {Object.entries(jobs).map(([name, on]) => (
                  <label key={name}><input type="checkbox" checked={on} onChange={(e) => setJobs((cur) => ({ ...cur, [name]: e.target.checked }))} /> <span className="mono">{name}</span></label>
                ))}
              </div>
            </div>
          </Section>
          <div className="savebar" role="region" aria-label="Save the setup">
            {dirty ? <Chip k="warning">unsaved changes</Chip> : <Chip k="good">saved</Chip>}
            {sure ? (
              <>
                <span className="small">Save these changes? They change what the engine may do for this brand, and are recorded with the time.</span>
                <button className="btn primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Yes, save"}</button>
                <button className="btn" disabled={busy} onClick={() => setSure(false)}>Cancel</button>
              </>
            ) : <button className="btn primary" disabled={!dirty} onClick={() => setSure(true)}>Save changes…</button>}
          </div>
        </>
      )}
    </>
  );
}
