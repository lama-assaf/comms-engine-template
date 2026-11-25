"use client";

import { useState, useTransition } from "react";
import { decide, recordArgument, saveEdit, discardEdit, noteConflictPreference } from "@/app/actions";

/*
 * The quick actions.
 *
 * Two rules are visible here because Alpha has to see them, and enforced again
 * in `app/actions.ts` because the UI is not the gate:
 *
 *   * Approve is closed until the argument line is current.
 *   * A hold, a rejection and a rewrite carry a reason (an approval may), and a reason marked "standing" is what
 *     reaches `.atelier/memory/reviews.md` for the agents to read next cycle.
 *
 * There is no publish button. There is no button anywhere in this application
 * that puts anything on a social handle or a site.
 */

type Msg = { tone: "err" | "ok"; text: string } | null;

export function DecideBox({
  id,
  kind,
  canApprove,
  approveBlockedWhy,
}: {
  id: string;
  kind: "post" | "reaction";
  canApprove: boolean;
  approveBlockedWhy?: string;
}) {
  const [rationale, setRationale] = useState("");
  const [scope, setScope] = useState<"item" | "standing">("item");
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();

  const run = (status: "approved" | "held" | "rejected" | "rewrite") =>
    start(async () => {
      const res = await decide({ id, kind, status, rationale, scope });
      if (res.ok) {
        setMsg({ tone: "ok", text: `Recorded as ${status}. The reason is saved${scope === "standing" ? " and goes to the agents' memory on the next pull." : " with the item."}` });
        setRationale("");
      } else {
        setMsg({ tone: "err", text: res.error });
      }
    });

  return (
    <div className="panel">
      <h3>Decide</h3>
      <p className="why">
        {kind === "post"
          ? "Approving schedules the post for its day once pulled. It does not put anything on the site or on a handle; the sender posts it, and marking the article live is a person's act on the control page."
          : "Clearing this lets a person place the comment by hand. The engine never sends one, so approving here decides that the reply is worth making, not that it has been made."}
      </p>
      <label className="fl" htmlFor={`r-${id}`}>
        Why (required to hold, reject or ask for a rewrite; optional to approve)
      </label>
      <textarea
        id={`r-${id}`}
        rows={4}
        value={rationale}
        onChange={(e) => setRationale(e.target.value)}
        placeholder="What made you decide this. If it is a judgement the next draft should inherit, mark it standing."
      />
      <label className="fl">
        <input
          type="checkbox"
          checked={scope === "standing"}
          disabled={!rationale.trim()}
          onChange={(e) => setScope(e.target.checked ? "standing" : "item")}
        />{" "}
        Standing — this outlives the item. Append it to <code className="mono">.atelier/memory/reviews.md</code>, which
        theme-writer reads before drafting and gatekeeper reads before gating.
      </label>
      <div className="actions">
        <button className="btn primary" disabled={pending || !canApprove} onClick={() => run("approved")}>
          Approve
        </button>
        <button className="btn" disabled={pending} onClick={() => run("held")}>
          Hold
        </button>
        <button className="btn" disabled={pending} onClick={() => run("rewrite")}>
          Request rewrite
        </button>
        <button className="btn" disabled={pending} onClick={() => run("rejected")}>
          Reject
        </button>
      </div>
      {!canApprove && approveBlockedWhy && <div className="err">{approveBlockedWhy}</div>}
      {msg && <div className={msg.tone === "err" ? "err" : "ok-msg"}>{msg.text}</div>}
    </div>
  );
}

export function ArgumentBox({
  id,
  hook,
  claim,
  current,
  act,
}: {
  id: string;
  hook: string;
  claim: string;
  current: boolean;
  act?: string;
}) {
  const [h, setH] = useState(hook);
  const [c, setC] = useState(claim);
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  const changed = h !== hook || c !== claim;

  const run = () =>
    start(async () => {
      const res = await recordArgument({ id, act: changed ? "rewritten" : "confirmed", hook: h, claim: c });
      setMsg(res.ok ? { tone: "ok", text: changed ? "Rewritten and recorded." : "Confirmed." } : { tone: "err", text: res.error });
    });

  return (
    <div className={`panel${current ? "" : " attention"}`}>
      <h3>Argument line</h3>
      <p className="why">
        The hook and the claim the post makes. Beta drafts them; they are yours. Approve stays closed until you have
        confirmed them as they stand or rewritten them — and rewriting the hook later reopens this.
        {current && act ? ` Currently ${act}.` : ""}
      </p>
      <label className="fl" htmlFor={`h-${id}`}>
        Hook
      </label>
      <textarea id={`h-${id}`} rows={2} value={h} onChange={(e) => setH(e.target.value)} />
      <label className="fl" htmlFor={`c-${id}`}>
        Claim
      </label>
      <textarea id={`c-${id}`} rows={3} value={c} onChange={(e) => setC(e.target.value)} />
      <div className="actions">
        <button className="btn primary" disabled={pending} onClick={run}>
          {changed ? "Record the rewrite" : "Confirm as it stands"}
        </button>
      </div>
      {msg && <div className={msg.tone === "err" ? "err" : "ok-msg"}>{msg.text}</div>}
    </div>
  );
}

export function EditBox({
  id,
  title,
  post,
  teaserLinkedin,
  teaserX,
  hasEdit,
}: {
  id: string;
  title: string;
  post: string;
  teaserLinkedin: string;
  teaserX: string;
  hasEdit: boolean;
}) {
  const [v, setV] = useState({ title, post, teaser_linkedin: teaserLinkedin, teaser_x: teaserX });
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();
  const dirty =
    v.title !== title || v.post !== post || v.teaser_linkedin !== teaserLinkedin || v.teaser_x !== teaserX;

  const save = () =>
    start(async () => {
      const res = await saveEdit({ id, ...v });
      setMsg(
        res.ok
          ? { tone: "ok", text: "Saved. It reaches the note when the distributor runs apply_edits.py — and only while the note still matches what you were shown." }
          : { tone: "err", text: res.error },
      );
    });

  const drop = () =>
    start(async () => {
      await discardEdit(id);
      setV({ title, post, teaser_linkedin: teaserLinkedin, teaser_x: teaserX });
      setMsg({ tone: "ok", text: "Edit dropped. The note was never touched." });
    });

  return (
    <div className="panel">
      <h3>Edit in place</h3>
      <p className="why">
        The body prose is Beta&rsquo;s; edit it where you choose to. Your edit is stamped with the note as it is shown
        here, and it is written to the vault only while the note still matches. Where it has moved on, the card says
        so and nothing is written until a person picks a side.
      </p>
      <label className="fl">Hook / title</label>
      <textarea rows={2} value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} />
      <label className="fl">Post</label>
      <textarea rows={14} value={v.post} onChange={(e) => setV({ ...v, post: e.target.value })} />
      <label className="fl">LinkedIn teaser</label>
      <textarea rows={6} value={v.teaser_linkedin} onChange={(e) => setV({ ...v, teaser_linkedin: e.target.value })} />
      <label className="fl">X teaser</label>
      <textarea rows={4} value={v.teaser_x} onChange={(e) => setV({ ...v, teaser_x: e.target.value })} />
      <div className="actions">
        <button className="btn primary" disabled={pending || !dirty} onClick={save}>
          Save edit
        </button>
        {hasEdit && (
          <button className="btn" disabled={pending} onClick={drop}>
            Discard saved edit
          </button>
        )}
      </div>
      {msg && <div className={msg.tone === "err" ? "err" : "ok-msg"}>{msg.text}</div>}
    </div>
  );
}

export function ConflictBox({ id }: { id: string }) {
  const [rationale, setRationale] = useState("");
  const [msg, setMsg] = useState<Msg>(null);
  const [pending, start] = useTransition();

  const run = (prefer: "desk" | "vault") =>
    start(async () => {
      const res = await noteConflictPreference({ id, prefer, rationale });
      setMsg(
        res.ok
          ? {
              tone: "ok",
              text: `Recorded. Nothing is written yet — run \`python3 scripts/apply_edits.py ${id} --prefer ${prefer}\` to make it so.`,
            }
          : { tone: "err", text: res.error },
      );
    });

  return (
    <div className="panel urgent">
      <h3>Conflict — nothing was written</h3>
      <p className="why">
        The note in the vault changed after you were shown it, so the distributor left it untouched and kept your
        edit. Neither version is lost. Say which one stands and why; the resolution itself is an explicit command, not
        something this page does behind you.
      </p>
      <label className="fl">Why this version stands</label>
      <textarea rows={3} value={rationale} onChange={(e) => setRationale(e.target.value)} />
      <div className="actions">
        <button className="btn" disabled={pending} onClick={() => run("desk")}>
          My edit stands
        </button>
        <button className="btn" disabled={pending} onClick={() => run("vault")}>
          The note stands
        </button>
      </div>
      {msg && <div className={msg.tone === "err" ? "err" : "ok-msg"}>{msg.text}</div>}
    </div>
  );
}
