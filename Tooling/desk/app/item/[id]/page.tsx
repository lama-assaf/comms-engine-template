import Link from "next/link";
import { notFound } from "next/navigation";
import { loadRow, loadContext } from "@/lib/desk";
import { RowTags } from "@/components/tags";
import { DecideBox, ArgumentBox, EditBox, ConflictBox } from "@/components/quick-actions";

export default async function ItemPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const row = await loadRow(decodeURIComponent(id));
  if (!row) notFound();
  const { findings } = await loadContext();
  const finding = findings.find((f) => f.id === row.item.findingId);
  const checks = row.item.gate?.checks ?? [];

  const approveWhy = row.blocked
    ? "The claim gate blocked this one. Fix the line and let the gatekeeper re-read it before approving."
    : !row.argCurrent
      ? "Approve is closed until the argument line is confirmed or rewritten."
      : undefined;

  return (
    <>
      <p className="lede" style={{ margin: "16px 0 4px" }}>
        <Link href="/">← Calendar</Link> · <Link href="/queue">Waiting on you</Link>
      </p>

      <div className="itemhead">
        <h1>{row.view.title}</h1>
        <RowTags row={row} />
      </div>

      <div className="cols">
        <div>
          {row.editState === "conflict" && <ConflictBox id={row.item.id} />}

          <ArgumentBox
            id={row.item.id}
            hook={row.view.title}
            claim={row.item.excerpt}
            current={row.argCurrent}
            act={row.argument?.act}
          />

          <DecideBox
            id={row.item.id}
            kind="post"
            canApprove={row.canApprove}
            approveBlockedWhy={approveWhy}
          />

          <div className="panel">
            <h3>The post as it stands</h3>
            <p className="why">
              {row.edit
                ? "Your saved edit, laid over the note. The note itself is unchanged until the distributor applies it."
                : "The draft as written, with the gate's edits already applied."}
            </p>
            <div className="prose">{row.view.post}</div>
            <hr className="rule" />
            <h3>LinkedIn teaser</h3>
            <div className="prose">{row.view.teaser_linkedin || <span className="empty">None drafted.</span>}</div>
            <hr className="rule" />
            <h3>X teaser</h3>
            <div className="prose">{row.view.teaser_x || <span className="empty">None drafted.</span>}</div>
          </div>

          <EditBox
            id={row.item.id}
            title={row.view.title}
            post={row.view.post}
            teaserLinkedin={row.view.teaser_linkedin}
            teaserX={row.view.teaser_x}
            hasEdit={!!row.edit}
          />
        </div>

        <aside>
          <div className="panel">
            <h3>Record</h3>
            <dl className="kv">
              <dt>engine id</dt>
              <dd className="mono">{row.item.id}</dd>
              <dt>slot</dt>
              <dd>
                {row.item.date ?? "no date on the note"} · {row.item.platform}
              </dd>
              <dt>calendar status</dt>
              <dd>{row.item.status}</dd>
              <dt>stream / type</dt>
              <dd>
                {row.item.stream} · {row.item.type}
              </dd>
              <dt>pillar / format</dt>
              <dd>
                {row.item.pillar} · {row.item.format}
              </dd>
              <dt>logic</dt>
              <dd>{row.item.logic || "—"}</dd>
              <dt>campaign</dt>
              <dd>{row.item.campaign || "—"}</dd>
              <dt>owner</dt>
              <dd>{row.item.owner || "—"}</dd>
              <dt>drafted by</dt>
              <dd>
                {row.item.draftedBy || "—"} {row.item.draftedAt ? `· ${row.item.draftedAt.slice(0, 10)}` : ""}
              </dd>
              <dt>partner tags</dt>
              <dd>{row.item.partnerTags?.length ? row.item.partnerTags.join(", ") : "none"}</dd>
              <dt>cites</dt>
              <dd className="mono">
                {row.item.cites?.length ? row.item.cites.join(", ") : "none: the gate marks it for an edit"}
              </dd>
              <dt>planning query</dt>
              <dd>{row.item.query || "—"}</dd>
              <dt>hypothesis</dt>
              <dd>{row.item.hypothesis || "— (none: the gate marks it for an edit)"}</dd>
              <dt>predicted / test</dt>
              <dd>
                {row.item.predicted || "—"} · {row.item.testId || "—"}
              </dd>
              <dt>CTA</dt>
              <dd>
                {row.item.cta ? (
                  <a href={row.item.cta} target="_blank" rel="noreferrer">
                    {row.item.slug || row.item.cta}
                  </a>
                ) : (
                  "—"
                )}
              </dd>
              <dt>note</dt>
              <dd className="mono">{row.item.notePath}</dd>
            </dl>
            <p className="note">
              The note is the record. Nothing on this page writes it — <code className="mono">scripts/repo.py</code>{" "}
              does, once <code className="mono">desk_sync.py --pull</code> has carried your acts out.
            </p>
          </div>

          <div className="panel">
            <h3>Anchor</h3>
            <p className="note">{row.item.anchor || "No proof-gate line on the note."}</p>
            {finding && (
              <>
                <hr className="rule" />
                <h3>
                  Signal {finding.id} · {finding.theme}
                </h3>
                <p className="note">{finding.summary.slice(0, 420)}…</p>
                {finding.url && (
                  <a className="mono" href={finding.url} target="_blank" rel="noreferrer">
                    source
                  </a>
                )}
              </>
            )}
          </div>

          <div className="panel">
            <h3>The claim gate</h3>
            {checks.length ? (
              <ul className="checks">
                {checks.map((c, i) => (
                  <li key={i}>
                    <span className={`tag ${c.result === "pass" ? "ok" : c.result === "block" ? "stop" : "warn"}`}>
                      {c.result}
                    </span>{" "}
                    <span className="name">{c.check}</span>
                    {c.line ? <div className="note">“{c.line}”</div> : null}
                    {c.fix ? <div className="note">{c.fix}</div> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty">The gate has not run on this item.</p>
            )}
          </div>

          {row.item.hooksConsidered?.length ? (
            <div className="panel">
              <h3>Hooks considered</h3>
              <ul className="checks">
                {row.item.hooksConsidered.map((h, i) => (
                  <li key={i} className={h === row.view.title ? "" : "note"}>
                    {h === row.view.title ? <b>{h}</b> : h}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {row.reviews.length > 0 && (
            <div className="panel">
              <h3>Reviews on this item</h3>
              {row.reviews.map((r) => (
                <div key={r.rowid} style={{ marginBottom: 12 }}>
                  <div className="tags">
                    <span className="tag">{r.verdict}</span>
                    {r.scope === "standing" && <span className="tag accent">standing</span>}
                    {r.syncedAt && <span className="tag ok">in memory</span>}
                  </div>
                  <p className="note" style={{ whiteSpace: "pre-wrap" }}>
                    {r.rationale}
                  </p>
                  <span className="mono">
                    {r.by} · {r.at.slice(0, 16).replace("T", " ")}
                  </span>
                </div>
              ))}
            </div>
          )}
        </aside>
      </div>
    </>
  );
}
