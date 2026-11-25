import { useCallback, useEffect, useMemo, useState, type ComponentType, type CSSProperties } from "react";
import { LoaderCircle, Menu, SquareArrowOutUpRight } from "lucide-react";
import { DESK, loadState, postAct } from "./api";
import { AppCtx, type Ctx, type DrawerSpec } from "./ctx";
import { applyGenome, onColor, pageColor, swatch, tone } from "./genome";
import { needs, upcoming, when } from "./format";
import { PAGES, TABS, meta } from "./nav";
import type { State } from "./types";
import { NavDock, PageMenu } from "./components/NavDock";
import { Drawers } from "./drawers/Drawers";
import { Story, storySlides } from "./pages/Story";
import { Today } from "./pages/Today";
import { Posts } from "./pages/Posts";
import { Themes } from "./pages/Themes";
import { Accounts } from "./pages/Accounts";
import { Suggestions } from "./pages/Suggestions";
import { Heard } from "./pages/Heard";
import { Replies } from "./pages/Replies";
import { Claims } from "./pages/Claims";
import { Results } from "./pages/Results";
import { System } from "./pages/System";
import { Autonomy } from "./pages/Autonomy";
import { Engagement } from "./pages/Engagement";
import { Setup } from "./pages/Setup";

const VIEWS: Record<string, ComponentType> = {
  story: Story, today: Today, posts: Posts, themes: Themes, heard: Heard, replies: Replies,
  accounts: Accounts, suggestions: Suggestions, claims: Claims, results: Results, system: System,
  autonomy: Autonomy, setup: Setup, engagement: Engagement,
};
// The old page's names, so a bookmark from it still lands.
const OLD: Record<string, string> = { overview: "today", content: "posts", suggested: "suggestions", listening: "heard", learning: "results", engine: "system" };

const pageFromHash = () => {
  const k = (location.hash.replace(/^#\/?/, "").split("/")[0] || "story").toLowerCase();
  const key = OLD[k] || k;
  return VIEWS[key] ? key : "story";
};

function Logo({ svg, name }: { svg?: string; name: string }) {
  return svg ? <div className="logo" aria-label={name} dangerouslySetInnerHTML={{ __html: svg }} /> : <div className="logo"><div className="word">{name}</div></div>;
}

export default function App() {
  const [S, setS] = useState<State | null>(null);
  const [failed, setFailed] = useState("");
  const [page, setPage] = useState(pageFromHash);
  const [drawer, setDrawer] = useState<DrawerSpec | null>(null);
  const [toastMsg, setToast] = useState("");
  const [sheet, setSheet] = useState(false);
  const [slide, setSlide] = useState(0);

  const reload = useCallback(async () => {
    try { const s = await loadState(); applyGenome(s.genome); setS(s); setFailed(""); }
    catch (e) { setFailed(String(e)); }
  }, []);
  useEffect(() => { reload(); }, [reload]);
  useEffect(() => {
    const h = () => { setPage(pageFromHash()); setDrawer(null); setSheet(false); };
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  useEffect(() => { if (!toastMsg) return; const t = setTimeout(() => setToast(""), 3600); return () => clearTimeout(t); }, [toastMsg]);

  const ctx = useMemo<Ctx | null>(() => {
    if (!S) return null;
    const navigate = (key: string) => { setSheet(false); setDrawer(null); if (location.hash !== `#/${key}`) location.hash = `#/${key}`; setPage(key); window.scrollTo(0, 0); };
    return {
      S, reload, slide,
      toast: setToast,
      open: setDrawer,
      close: () => setDrawer(null),
      act: async (path, body, done) => {
        const r = await postAct(path, body);
        if (!r.ok) { setToast(r.error || "that did not work"); if (r.conflict) await reload(); return false; }
        setToast(done); await reload(); return true;
      },
      go: (target) => {
        const [kind, id] = target.split(":");
        if (id === undefined) return navigate(OLD[kind] || kind);
        if (kind === "view") return navigate(OLD[id] || id);
        if (kind === "post") return setDrawer({ kind: "post", id });
        if (kind === "q") { const i = storySlides(S).findIndex((s) => s.id === id); setSlide(i < 0 ? 0 : i); return navigate("story"); }
        if (kind === "slide") { setSlide(Number(id) || 0); return navigate("story"); }
      },
    };
  }, [S, reload, slide]);

  if (!S || !ctx) {
    return (
      <div className="boot">
        {failed ? <p>Could not read the engine: {failed}. Is <code>control.py</code> running?</p> : <LoaderCircle className="spin" aria-label="Loading" />}
      </div>
    );
  }

  const n: Record<string, number> = {
    story: (S.story?.questions || []).filter((q) => q.status === "open").length, today: needs(S).length, posts: upcoming(S).length,
    themes: S.themes?.rows.length || 0, accounts: S.accounts?.watched.length || 0, suggestions: S.suggested?.rows.length || 0,
    heard: S.listening?.findings.length || 0, replies: S.replies?.proposals.length || 0, claims: S.claims?.watch.length || 0,
    autonomy: (S.policy?.unreviewed || []).filter((u) => !u.taken_down).length,
    engagement: S.reactions?.waiting.length || 0,
  };
  const hot = new Set(["story", "today", "replies", "engagement"]);
  const here = meta(page);
  const View = VIEWS[page] || Today;
  const name = S.genome?.name || S.stream;
  const hereColor = pageColor(page);
  const hereTone = tone(hereColor);
  const pageVars = { "--page": hereColor, "--on-page": onColor(hereColor), "--page-soft": hereTone.soft, "--page-ink": hereTone.deep } as CSSProperties;

  return (
    <AppCtx.Provider value={ctx}>
      {page === "story" ? <Story /> : (
        <div className="app" style={pageVars}>
          <aside className="rail">
            <Logo svg={S.genome?.logo?.on_light} name={name} />
            <div className="sub">Control · read {when(S.built_at)}</div>
            <PageMenu className="side-menu" label="Pages" page={page} counts={n} hot={hot} go={ctx.go} />
            <div className="foot">Only on this computer (127.0.0.1).<br />Nothing here posts; the sender does, on the day.</div>
          </aside>
          <div style={{ minWidth: 0 }}>
            <header className="topbar">
              <Logo svg={S.genome?.logo?.on_light} name={name} />
              <span className="t">{here.label}</span>
              <span className="m">{when(S.built_at)}</span>
            </header>
            <main className="page">
              <div className="wrap">
                {S.errors?.length ? <div className="errors">Some files could not be read: {S.errors.join(" · ")}</div> : null}
                <View />
              </div>
            </main>
          </div>
          <nav className="tabbar" aria-label="Main">
            {TABS.map((k) => { const p = meta(k); return (
              <button key={k} aria-current={k === page ? "page" : undefined} onClick={() => ctx.go(k)}>
                <p.icon aria-hidden />{p.label}{hot.has(k) && n[k] ? <span className="badge">{n[k]}</span> : null}
              </button>); })}
            <button aria-current={!TABS.includes(page) ? "page" : undefined} onClick={() => setSheet(true)}><Menu aria-hidden />More</button>
          </nav>
          {sheet ? (
            <>
              <div className="veil" onClick={() => setSheet(false)} />
              <div className="sheet" role="dialog" aria-label="More pages">
                <div className="grab" />
                <h3>Everything else</h3>
                <div className="grid">
                  {PAGES.filter((p) => !TABS.includes(p.key)).map((p) => (
                    <button key={p.key} style={swatch(pageColor(p.key))} onClick={() => ctx.go(p.key)}>
                      <p.icon aria-hidden />{p.label}{n[p.key] ? <span className="n">{n[p.key]}</span> : null}
                    </button>
                  ))}
                  <button style={{ background: "var(--grey)" }} onClick={() => { setSheet(false); window.open(DESK, "_blank", "noopener"); }}>
                    <SquareArrowOutUpRight aria-hidden />The desk
                  </button>
                </div>
              </div>
            </>
          ) : null}
        </div>
      )}
      <NavDock page={page} counts={n} hot={hot} go={ctx.go} />
      {drawer ? <Drawers spec={drawer} /> : null}
      {toastMsg ? <div className="toast" role="status">{toastMsg}</div> : null}
    </AppCtx.Provider>
  );
}
