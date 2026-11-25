// The shapes scripts/views.py returns, as the page reads them from /api/state.
// Hand-written for now; PLAN-surfaces.md step 3 generates them from contract/v1.

export type Gate = "pass" | "pass-with-edits" | "block" | "" | string;

export interface Motion { storyboard: boolean; poster: string | null; video: string | null }

/** The last approve act on a post and where the lifecycle has it (views.post_acts). */
export interface PostAct { decision: string | null; outcome: string | null; at: string | null; by: string | null; source: string | null; state: string | null; date: string | null }
export interface Post {
  act?: PostAct | null; published_to?: string[];
  /** The hook and the claim as the card shows them; `argument.current` is true once a person confirmed exactly these. */
  hook?: string; claim?: string; argument?: { current: boolean; by: string | null; at: string | null };
  id: string; title: string; theme: string; date: string | null; platform: string; campaign: string;
  status: string; alpha_status: string; decision: string | null; gate: Gate; note_for_alpha: string;
  cta: string; teaser_x: string; teaser_linkedin: string; post: string; hypothesis: string; predicted: string;
  motion: Motion;
  /** The article's URL once a person marked it live (the blog-live act); a team post has no article. */
  live?: string | null; by_team?: boolean;
}

export interface CalendarRow { date: string | null; platform: string; status: string; stream: string; title: string; pillar?: string; engine?: unknown; body: string; url?: string | null }
export interface Send { at: string; platform: string; title: string; url: string; state: string; body: string }
export interface Pick { slot?: string; theme?: string; why?: string; predicted?: string; finding_id?: string }
export interface Calendar {
  taken_at: string | null; ahead: CalendarRow[]; open_past: CalendarRow[]; open_past_total: number; undated: number;
  sends: Send[]; strategy: { week?: string; summary?: string; picks?: Pick[]; not_this_week?: unknown[]; held_slot?: unknown };
}

export interface Warmth { theme: string; relevance: number | string; count: number; why: string }
export interface ThemeRow {
  tag: string; what: string; different: string; licence: string; licence_basis?: string; plain?: { now: string; not: string; why: string; next?: string; current: boolean; written?: string } | null; layer: string; fact: string;
  x_search: string; linkedin_search: string; keywords: string[];
  planning: unknown; signal: { note?: string } | null; warmth: Warmth | null; findings: string[]; upcoming: string[];
}
export interface Themes {
  rows: ThemeRow[]; terms_file: string; terms_base: string; x_query_max: number; themes_md: string; md_base: string;
  mentions: string; term_log: string[];
}

export interface HandleRow { [k: string]: string | undefined }
export interface Watched { handle: string; platform?: string; themes?: string[]; note?: string; from?: string; added?: string }
export interface Accounts {
  own: HandleRow[]; partners: HandleRow[]; standards: HandleRow[]; private: { present: boolean; terms: number };
  ledger: unknown[]; watched: Watched[]; dismissed: { handle: string; at?: string }[]; watch_base: string; watch_max: number;
  switches?: SwitchRow[];
}
/** The auto-reply switch of a stream and channel (switches.py): live value, what streams.md allows, who last changed it and why. */
export interface SwitchRow {
  stream: string; name: string; channel: string; label: string; value: boolean; on: boolean; allowed: boolean; why: string;
  stored: boolean; by: string | null; at: string | null; reason: string;
}

/** One kind of send on one channel (switches.policy): the mode asked for, the mode in force, and whether the setup allows `auto`. */
export interface ModeRow {
  kind: string; wanted: "review" | "auto"; mode: "review" | "auto"; allowed: boolean; why: string; stored: boolean;
  default: string; by: string | null; at: string | null; reason: string;
}
export interface PolicyStream {
  stream: string; name: string; autopilot: string; by_switch: boolean; owner: string; paused: boolean;
  pause: { by: string | null; at: string | null; reason: string }; preset: string | null;
  channels: { channel: string; label: string; kinds: ModeRow[] }[];
}
/** Something that went out with no person in the loop (views.unreviewed_sends). */
export interface Unreviewed { id: string; kind: string; channel: string; stream: string; at: string; url: string; title: string; taken_down: string | null }
export interface Policy { streams: PolicyStream[]; kinds: string[]; presets: string[]; unreviewed: Unreviewed[] }

/** A like or a repost the engine planned (reactions.summary): a post id, a tier and a theme, never a handle. */
export interface Reaction {
  id: string; kind: string; channel: string; target_id: string; tier: string; theme: string; source: string; rank: number;
  stream: string; planned_at: string; done_at?: string | null; check?: string | null; reason?: string | null; undone?: string | null;
}
export interface ReactionRule { stream: string; name: string; channel: string; label: string; kind: string; cap: number; mode: string; click_only: boolean }
export interface Reactions {
  planned_at: string | null; stream: string | null; queued: Reaction[]; waiting: Reaction[]; done: Reaction[]; refused: Reaction[];
  rules: ReactionRule[]; earned: Record<string, Record<string, number>>; live: boolean;
}

export interface SetupStep { id: string; title: string; done: boolean; detail: string; command: string; why: string; optional?: boolean }
/** One stream of brand.json, as the Setup page edits it. `channels` and `posts_per_day` may be the cell's own text. */
export interface SetupStream {
  name?: string; narrator?: string; owner?: string; objectives?: string; autopilot?: string;
  channels?: Record<string, string> | string; review?: Record<string, string | Record<string, string>>;
  drafts_only?: string | string[]; posts_per_day?: Record<string, number> | string;
  reactions_per_day?: Record<string, Record<string, number>>; quiet_hours?: string;
}
export interface SetupFile {
  path?: string; present: boolean; base: string; problems: string[]; in_sync: boolean; diff: string[];
  brand: Record<string, string>; streams: Record<string, SetupStream>; drivers: Record<string, string>; jobs: Record<string, boolean>;
  options: { kinds?: string[]; modes?: string[]; channels?: string[]; drivers?: Record<string, string[]>; autopilot?: string[]; owner?: string[] };
}
export interface Setup { complete: boolean; done: number; total: number; next: SetupStep | null; steps: SetupStep[]; file: SetupFile; error?: string }

export interface Sample { url: string; text: string; theme: string }
export interface Suggestion { handle: string; name: string; hits: number; themes: string[]; followers: number; engagement: number; samples: Sample[]; last: string }

export interface Evidence { url?: string; title?: string; quote?: string; text?: string; source?: string }
export interface Finding {
  id: string; theme: string; shape: string; finding: string; relevance: number | string; sentiment: string;
  content: string; content_note: string; conversation: string; conversation_note: string;
  freshness_deadline: string; at: string; evidence: Evidence[];
}
export interface Listening {
  run_id: string; window: { from: string; to: string } | null; summary: string; mentions_note: string;
  held_slot: { triggered?: boolean; reason?: string } | null; warmest: Warmth[]; sources: unknown[];
  findings: Finding[]; held_for_person: unknown[]; pass: Record<string, unknown>; terms: number;
}

export interface Proposal {
  theme: string; platform: string; tier?: string; target_title?: string; target_text: string; target_url?: string;
  draft_comment: string; why: string; finding_id?: string; author?: string;
  id?: string; send?: SendOutcome | null;
}
/** The latest attempt to send a reply, read from state/sends.jsonl. */
export interface SendOutcome { outcome: string; check?: string; reason?: string; url?: string; at?: string }
export interface Replies { pass_at: string; proposals: Proposal[]; inbound: { note?: string }; skipped: number }

export interface ClaimIdea { date?: string; theme?: string; claim?: string; source?: string; url?: string; tier?: string; grade?: string; corroboration?: string }
export interface Claims { register: number; watch: ClaimIdea[]; review: Record<string, string>[] }

export interface Prediction { predicted_at?: string; theme?: string; platform?: string; hypothesis?: string; predicted?: string; actual?: string | null }
export interface ScoreRow { row: string; value: unknown; records: number; status: string; note: string }
export interface Learning { predictions: Prediction[]; rows: ScoreRow[]; key_results: { objective: string; key_result: string }[]; computed_at: string }

export interface Job { job?: string; label?: string; loaded?: boolean; last_run?: string; what?: string }
export interface Run { at: string; step: string; detail: string }
export interface Engine { jobs: Job[]; runs: Run[]; motion_owed: { id: string; action: string; reason: string }[] }

export interface SlideItem { text: string; why?: string; source?: string; kind?: string; handle?: string; tag?: string }
export interface Slide {
  kind: string; title?: string; subtitle?: string; question?: string; why?: string; id?: string;
  figure?: { value: string; label: string }; points?: string[]; items?: (SlideItem | string)[];
  options?: string[]; actions?: string[];
}
export interface Question { id: string; question: string; why?: string; status: string; answer?: string; answered_at?: string }
export interface Response { run_id: string; slide: number; item: number | null; action: string; text: string }
export interface Story {
  latest: { run_id?: string; date?: string; slides?: Slide[]; published_at?: string };
  questions: Question[]; questions_base: string; responses: Response[]; responses_base: string;
  feedback: { rating?: string; remember?: string; next?: string } | null; feedback_base: string; ratings: string[];
}

export interface Genome {
  name: string;
  colors: Record<string, string>;
  type: { family?: string; stack?: string; display_weight?: number; body_weight?: number };
  shape: { radius?: number; ui_radius?: number; gradients?: string };
  logo: { on_light?: string; on_dark?: string };
  palette?: { colors: { name: string; hex: string }[]; roles: Record<string, string>; style?: "pastel" | "solid" };
}

export interface State {
  built_at: string; stream: string; today: string; errors: string[];
  genome: Genome | null; story: Story | null; posts: { upcoming: Post[]; past: Post[] } | null; calendar: Calendar | null;
  themes: Themes | null; accounts: Accounts | null; suggested: { rows: Suggestion[]; days: number; min_hits: number } | null;
  listening: Listening | null; replies: Replies | null; claims: Claims | null; learning: Learning | null; engine: Engine | null;
  setup?: Setup | null; policy?: Policy | null; reactions?: Reactions | null;
}
