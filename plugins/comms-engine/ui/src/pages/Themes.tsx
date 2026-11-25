import { Plus } from "lucide-react";
import { useApp } from "../ctx";
import type { ThemeRow } from "../types";
import { DataTable } from "../components/DataTable";
import { About, LicenceChip, PageHead, Section, Theme, licenceWord } from "../components/ui";

export function ThemeTable({ id }: { id: string }) {
  const { S, open } = useApp();
  return (
    <DataTable<ThemeRow> id={id} rows={S.themes?.rows || []} onRow={(r) => open({ kind: "theme", tag: r.tag })}
      filters={[{ label: "Allowed", get: (r) => licenceWord(r.licence) }]} text={(r) => `${r.what} ${r.different}`}
      empty="No themes yet. Add the first one with the button above."
      cols={[
        { id: "tag", label: "Theme", cell: (r) => <div><Theme tag={r.tag} /><div className="excerpt" style={{ maxWidth: 440, marginTop: 6 }}>{r.what}</div></div> },
        { id: "licence", label: "Allowed", get: (r) => licenceWord(r.licence), cell: (r) => (
          <div className="chips">
            <LicenceChip l={r.licence} />
            <button className={`btn small ${r.licence === "held" ? "primary" : "link"}`} onClick={() => open({ kind: "theme", tag: r.tag, grade: true })}>
              {r.licence === "held" ? "Allow…" : "change"}
            </button>
          </div>) },
        { id: "planned", label: "Posts planned", num: true, get: (r) => r.upcoming.length },
        { id: "heard", label: "Heard", num: true, get: (r) => r.findings.length },
        { id: "loud", label: "Loudness", num: true, get: (r) => r.warmth?.relevance ?? null, cell: (r) => String(r.warmth?.relevance ?? "—") },
        { id: "kw", label: "Keywords", num: true, get: (r) => r.keywords.length },
      ]} />
  );
}

export function Themes() {
  const { S, open } = useApp();
  const T = S.themes;
  return (
    <>
      <PageHead page="themes" title="Themes" meta={`${T?.rows.length || 0} topics we want to be known for`}
        actions={<button className="btn primary" onClick={() => open({ kind: "newTheme" })}><Plus aria-hidden />Add a theme</button>} />
      <About words={[["Free to use", "We can talk about this topic freely."], ["Careful wording", "We may talk about it, but only with the careful wording written down for it."],
        ["Not yet", "Only the general idea. Nothing about what we do, no partner, no date."], ["X search", "The words the listener types into X search every day for this theme."],
        ["Keywords", "Words that make a post count as on-topic when the listener scores what it found."], ["Loudness", "How much on-topic talk the last listening run found (higher is louder)."]]}>
        <p>A theme is a topic we want people to connect with us, written as a hashtag. For each one you see how freely we may talk about it, how many posts are planned and what the listener heard about it.</p>
        <p>Click a theme to change what the listener looks for on X. Add a new theme with the button: it starts as <b>not yet</b>, which means posts may only talk about the general idea.</p>
        <p><b>Allow…</b> lets a person move a theme to careful wording or free to use, once they are sure what we can prove; it asks why, and our theme list keeps the reason and the one it replaced. Holding a theme again works the same way.</p>
      </About>
      <ThemeTable id="themes" />
      {T?.mentions ? (
        <Section title="How we listen for our own name" hint="The X search the listener runs to catch anyone mentioning us.">
          <div className="panel pad mono">{T.mentions}</div>
        </Section>
      ) : null}
      {T?.term_log?.length ? (
        <Section title="Recent changes to the searches">
          <div className="panel"><ul className="rows">{T.term_log.map((l, i) => <li key={i}><span className="mark info" /><span className="what small">{l}</span><span /></li>)}</ul></div>
        </Section>
      ) : null}
    </>
  );
}
