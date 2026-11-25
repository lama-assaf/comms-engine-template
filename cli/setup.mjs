#!/usr/bin/env node
// setup.mjs - comms-engine-setup: set up the comms engine on a Mac, then run it from one menu.
//
// Why: the engine is a Claude Code plugin and each brand keeps its own repository, so a new
// machine needs a handful of commands in the right order (the tools, the plugin, the brand's
// repository, the Python packages, the role plugins, the secrets, and on the office Mac the
// schedules). This walks them in that order, skips what is already done, and asks before
// each change. Every act is an `engine` command or a `claude plugin` command, shown before it
// runs, so nothing here duplicates the engine and the screen teaches the commands. A secret is
// typed at the engine's own hidden prompt and never passes through this process.
//
//   npx github:lama-assaf/comms-engine-template                   the menu
//   npx github:lama-assaf/comms-engine-template setup             the guided setup, step by step
//   npx github:lama-assaf/comms-engine-template doctor|status     one engine command, then exit
//   npx github:lama-assaf/comms-engine-template console           the engine's console screen
//   ... --instance <dir>                                          the brand's repository to answer for
//
// The repository answered for: --instance, the folder it runs in (or a parent) holding
// brand.json, then the one remembered in ~/.config/comms-engine/setup.json.

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as lib from "./lib.mjs";
import { Cancelled, ask, bold, confirm, dim, fail, heading, note, ok, pause, select } from "./term.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const BESIDE = path.join(ROOT, "plugins", "comms-engine");
const PKG = lib.readJson(path.join(ROOT, "package.json")) || {};
const MARKETPLACE = PKG.commsEngine?.marketplace || "lama-assaf/comms-engine-template";
const TOKEN = "CLAUDE_CODE_OAUTH_TOKEN";
const NPX = `npx github:${MARKETPLACE}`;

const HELP = `comms-engine-setup ${PKG.version || ""}: set up the comms engine, then run it from one menu

  ${NPX}                     the menu: set up, doctor, status, the console
  ${NPX} setup               the guided setup, step by step (asks before each change)
  ${NPX} doctor              engine doctor for the brand's repository
  ${NPX} status              engine status
  ${NPX} console             the engine's console screen (needs 80x24)

  --instance <dir>           the brand's repository (default: the folder you are in, then the last one used)
  -h, --help | -v, --version`;

const tilde = (p) => {
  const home = lib.homeDir();
  return p && (p === home || p.startsWith(home + path.sep)) ? "~" + p.slice(home.length) : p;
};
const quote = (a) => (/^[\w@%+=:,./-]+$/.test(a) ? a : `'${String(a).replace(/'/g, "'\\''")}'`);

function which(name) {
  for (const dir of (process.env.PATH || "").split(path.delimiter)) {
    const full = path.join(dir, name);
    try {
      fs.accessSync(full, fs.constants.X_OK);
      if (fs.statSync(full).isFile()) return full;
    } catch {
      // not here
    }
  }
  return null;
}

// Run one command; `shown` is what the screen prints for it. A Ctrl-C belongs to the command,
// so this process ignores it until the command is done.
function run(argv, { cwd, env, capture = false, shown = argv } = {}) {
  if (!capture) console.log(dim(`$ ${shown.map(quote).join(" ")}`));
  const ignore = () => {};
  process.on("SIGINT", ignore);
  try {
    const r = spawnSync(argv[0], argv.slice(1), {
      cwd, env, encoding: "utf8", stdio: capture ? ["ignore", "pipe", "pipe"] : "inherit",
    });
    return { code: r.error ? 127 : (r.status ?? 1), out: r.stdout || "", err: r.stderr || (r.error ? String(r.error.message) : "") };
  } finally {
    process.off("SIGINT", ignore);
  }
}

class Context {
  constructor(instance) {
    this.instance = instance;
    this.python = which("python3") || "python3";
  }

  get engine() {
    return lib.findEngine({ instance: this.instance, beside: BESIDE });
  }

  use(instance) {
    this.instance = instance;
    lib.saveConfig({ instance });
  }

  env() {
    const env = { ...process.env };
    delete env.CLAUDE_PROJECT_DIR; // set when this runs inside Claude Code, and names that project
    if (this.instance) env.COMMS_ENGINE_INSTANCE = this.instance;
    return env;
  }

  // `engine <args>` from `home` (the engine found for the instance, unless named).
  engine_(args, { home = this.engine?.home, capture = false } = {}) {
    if (!home) return { code: 1, out: "", err: "no engine: install the comms-engine plugin (setup, step 2)" };
    return run([this.python, path.join(home, "bin", "engine"), ...args], {
      cwd: this.instance || process.cwd(), env: this.env(), capture, shown: ["engine", ...args],
    });
  }
}

// ---- the steps of the guided setup; each returns false only when the next cannot run ----

function stepTools(ctx) {
  heading("1. The tools");
  let fine = true;
  const need = (label, found, hint) => {
    if (found) ok(`${label}: ${found}`);
    else {
      fail(`${label}: missing  -> ${hint}`);
      fine = false;
    }
  };
  if (process.platform !== "darwin") note("the schedules (launchd) and the secrets (the login keychain) are macOS only");
  need("git", which("git") && run(["git", "--version"], { capture: true }).out.trim(), "xcode-select --install");
  const pyText = which("python3") && run([ctx.python, "--version"], { capture: true });
  const pyVersion = pyText && lib.parseVersion(pyText.out + pyText.err);
  if (pyVersion && !lib.atLeast(pyVersion, lib.MIN_PYTHON)) {
    fail(`python3: ${pyVersion.join(".")} at ${ctx.python}, the engine needs ${lib.MIN_PYTHON.join(".")} or newer  -> brew install python@3.13`);
    fine = false;
  } else need("python3", pyVersion && `${pyVersion.join(".")} (${ctx.python})`, "brew install python@3.13");
  const nodeVersion = lib.parseVersion(process.versions.node);
  need("node", lib.atLeast(nodeVersion, [lib.MIN_NODE]) && process.versions.node, `Node ${lib.MIN_NODE} or newer: brew install node`);
  const claude = which("claude") && run(["claude", "--version"], { capture: true }).out.trim();
  need("claude", claude, "install Claude Code (https://claude.com/claude-code), then run `claude` once to log in");
  for (const [bin, what, hint] of [["pdftoppm", "the deck reader renders", "brew install poppler"],
    ["soffice", "rendering .pptx sources", "brew install --cask libreoffice"],
    ["tesseract", "image-only slides", "brew install tesseract"]]) {
    if (which(bin)) ok(`${bin}: found`);
    else note(`${bin}: missing, for ${what} (optional)  -> ${hint}`);
  }
  if (!fine) console.log(`\nInstall what is missing, then run ${bold("setup")} again.`);
  return fine;
}

async function stepPlugin(ctx) {
  heading("2. The comms-engine plugin in Claude Code");
  const found = ctx.engine;
  if (found?.installed) {
    ok(`comms-engine ${lib.engineVersion(found.home) || "?"}, ${found.why} (${tilde(found.home)})`);
    if (found.elsewhere) {
      note(`Claude Code loads that install only in ${tilde(found.elsewhere)}; a brand's repository offers the plugin on its first \`claude\`, or install it for this user with: claude plugin install ${lib.PLUGIN} --scope user`);
    }
    return true;
  }
  if (found) note(`using ${found.why}; Claude Code has no install of the plugin yet`);
  if (!(await confirm(`Install comms-engine in Claude Code for this user, from ${MARKETPLACE}?`))) return Boolean(found);
  if (!lib.knownMarketplace(lib.MARKET)) {
    const r = run(["claude", "plugin", "marketplace", "add", MARKETPLACE]);
    if (r.code !== 0) {
      fail(`the marketplace was not added. ${MARKETPLACE} is a private repository: log in to GitHub with an account that can read it (gh auth login, or an SSH key), then try again`);
      return Boolean(found);
    }
  }
  const r = run(["claude", "plugin", "install", lib.PLUGIN, "--scope", "user"]);
  const now = ctx.engine;
  if (r.code !== 0 || !now?.installed) {
    fail("the plugin did not install; the lines above say why");
    return Boolean(now);
  }
  ok(`comms-engine ${lib.engineVersion(now.home) || "?"} installed (${tilde(now.home)})`);
  return true;
}

async function chooseFolder(ctx) {
  for (;;) {
    const given = await ask("The brand's repository (a folder holding brand.json; blank goes back)", "");
    if (!given) return false;
    const dir = path.resolve(lib.expandHome(given));
    if (lib.isInstance(dir)) {
      ctx.use(dir);
      ok(`using ${tilde(dir)} (${lib.brandName(dir) || "no brand name yet"})`);
      return true;
    }
    fail(`${tilde(dir)} holds no brand.json`);
  }
}

async function createInstance(ctx) {
  const template = lib.templateEngine({ beside: BESIDE });
  if (!template) {
    fail(`no template to copy from: add the comms-engine marketplace first (step 2: claude plugin marketplace add ${MARKETPLACE})`);
    return false;
  }
  let dir;
  for (;;) {
    dir = path.resolve(lib.expandHome(await ask("Folder for the new repository", "~/comms/brand")));
    if (fs.existsSync(dir) && (!fs.statSync(dir).isDirectory() || fs.readdirSync(dir).length)) {
      fail(`${tilde(dir)} is not an empty folder; a new repository starts in an empty one`);
      continue;
    }
    const inside = lib.protectedFolder(dir);
    if (inside && !(await confirm(`${tilde(dir)} is inside ~/${inside}, which macOS keeps from scheduled jobs, so the office Mac could not run it. Use it anyway?`, false))) continue;
    break;
  }
  const from = await ask("A brand.json to set it up from (blank: answer the brand questions instead)", "");
  const args = ["new-instance", dir];
  if (from) args.push("--from", path.resolve(lib.expandHome(from)));
  const made = new Context(null);
  if (made.engine_(args, { home: template }).code !== 0) {
    fail("new-instance refused; the line above says why");
    return false;
  }
  ctx.use(dir);
  if (!from && ctx.engine_(["init"]).code !== 0) note("the brand questions did not finish: run setup again, or `engine init` in the folder");
  ok(`${tilde(dir)} (${lib.brandName(dir) || "no brand name yet"}): open it with claude once and trust the folder`);
  return true;
}

async function stepInstance(ctx) {
  heading("3. The brand's repository");
  if (ctx.instance && lib.isInstance(ctx.instance)) {
    const pick = await select(`Use ${tilde(ctx.instance)} (${lib.brandName(ctx.instance) || "no brand name yet"})?`, [
      { label: "Yes, keep using it" },
      { label: "Create a new one", hint: "engine new-instance, then the brand questions" },
      { label: "Use another folder", hint: "one that holds brand.json" },
    ]);
    if (pick === 0) {
      lib.saveConfig({ instance: ctx.instance });
      return true;
    }
    return pick === 1 ? createInstance(ctx) : chooseFolder(ctx);
  }
  const pick = await select("There is no brand repository yet.", [
    { label: "Create a new one", hint: "engine new-instance, then the brand questions" },
    { label: "Use a folder that has one", hint: "one that holds brand.json" },
  ]);
  return pick === 0 ? createInstance(ctx) : chooseFolder(ctx);
}

function requirementsFile() {
  const template = lib.templateEngine({ beside: BESIDE });
  const candidates = [path.join(ROOT, "requirements.txt"), template && path.join(template, "..", "..", "requirements.txt")];
  return candidates.find((c) => c && fs.existsSync(c)) || null;
}

async function stepPackages(ctx) {
  heading("4. The Python packages");
  const check = () => {
    const r = ctx.engine_(["runtime"], { capture: true });
    return { good: r.code === 0, line: (r.out + r.err).trim() };
  };
  let { good, line } = check();
  if (good) {
    ok(line.replace(/^runtime: /, ""));
    return true;
  }
  fail(line.replace(/^runtime: /, ""));
  const req = requirementsFile();
  if (!req) {
    note("no requirements.txt beside this command or in the template: install the packages by hand (docs/01-setup.md, 1.8)");
    return true;
  }
  const py = lib.runtimePython(line) || ctx.python;
  if (!(await confirm(`Install the pinned packages into ${py}?`))) return true;
  run([py, "-m", "pip", "install", "-r", req]);
  ({ good, line } = check());
  if (good) ok(line.replace(/^runtime: /, ""));
  else {
    fail(line.replace(/^runtime: /, ""));
    note("a Homebrew Python refuses pip (externally managed): put a python.org or pyenv Python first on the jobs' PATH, or install the packages for it by hand");
  }
  return true;
}

async function stepRolePlugins(ctx) {
  heading("5. The plugins the roles call");
  const r = ctx.engine_(["plugins"], { capture: true });
  const missing = lib.missingPlugins(r.out);
  if (!missing.length) {
    for (const l of r.out.trim().split("\n").filter((l) => /: installed$/.test(l))) ok(l);
    if (r.code !== 0 && !r.out.trim()) fail((r.err || "engine plugins said nothing").trim());
    return true;
  }
  for (const market of [...new Set(missing.map((m) => m.market))]) {
    if (lib.knownMarketplace(market)) continue;
    const source = await ask(`Where the "${market}" marketplace comes from (owner/repo or a git URL; blank skips)`, "");
    if (!source) {
      note(`skipped the ${market} plugins: the roles fall back to their briefs until they are installed`);
      continue;
    }
    run(["claude", "plugin", "marketplace", "add", source]);
  }
  for (const m of missing.filter((x) => lib.knownMarketplace(x.market))) {
    if (await confirm(`Install ${m.id} (${m.scope} scope)?`)) {
      run(["claude", "plugin", "install", m.id, "--scope", m.scope], { cwd: ctx.instance, env: ctx.env() });
    }
  }
  return true;
}

function readStatus(ctx) {
  const r = ctx.engine_(["status", "--json"], { capture: true });
  try {
    return JSON.parse(r.out);
  } catch {
    fail(`engine status --json gave nothing readable: ${(r.err || r.out).trim().split("\n").slice(-1)[0] || "no output"}`);
    return null;
  }
}

async function stepSecrets(ctx) {
  heading("6. The secrets");
  const status = readStatus(ctx);
  if (!status) return true;
  const missing = lib.missingSecrets(status).filter((s) => s.name !== TOKEN);
  const present = (status.secrets || []).filter((s) => s.present);
  if (present.length) ok(`present: ${present.map((s) => s.name).join(", ")}`);
  if (!missing.length) ok("every secret the engine names is set");
  const ask1 = (s) => confirm(`Set ${s.name} now? (${s.required ? "required" : "optional"}, typed at a hidden prompt)`, s.required);
  for (const s of missing.filter((x) => x.required)) if (await ask1(s)) ctx.engine_(["secrets", "--set", s.name]);
  const optional = missing.filter((x) => !x.required);
  if (optional.length && (await confirm(`${optional.length} optional secrets are not set (${optional.map((s) => s.name).join(", ")}). Go through them?`, false))) {
    for (const s of optional) if (await ask1(s)) ctx.engine_(["secrets", "--set", s.name]);
  }
  note("each stream's channel accounts connect through Composio: engine setup composio <stream>");
  return true;
}

async function stepHost(ctx) {
  heading("7. The office Mac");
  if (!(await confirm("Is this the Mac that runs the schedules (the office Mac)?", false))) {
    note("skipped: on the office Mac, run setup again and answer yes");
    return true;
  }
  if (process.platform !== "darwin") {
    fail("the schedules are launchd jobs: macOS only");
    return true;
  }
  const inside = lib.protectedFolder(ctx.instance);
  if (inside) {
    fail(`${tilde(ctx.instance)} is inside ~/${inside}, which macOS keeps from launchd jobs: create the repository elsewhere (step 3), then come back`);
    return true;
  }
  const status = readStatus(ctx);
  const token = (status?.secrets || []).find((s) => s.name === TOKEN);
  if (token?.present) ok(`${TOKEN}: present`);
  else {
    console.log("The scheduled runs sign in to Claude with a subscription token that lasts a year.");
    if (await confirm("Run `claude setup-token` now? It opens a browser and prints the token")) run(["claude", "setup-token"]);
    if (await confirm(`Paste the token as ${TOKEN} now (a hidden prompt)?`)) ctx.engine_(["secrets", "--set", TOKEN]);
  }
  if (await confirm("Install the fixed path the schedules run (~/.local/bin/comms-engine)?")) ctx.engine_(["shim", "--install"]);
  if (await confirm("Show the schedules this Mac would load (nothing is loaded)?")) {
    ctx.engine_(["install", "--dry-run"]);
    if (await confirm("Load them into launchd now?", false)) ctx.engine_(["install"]);
  }
  ctx.engine_(["host-check"]);
  note("automatic login, pmset, Tailscale Serve, handles.private.md and the backup deploy key are set by hand: docs/07-hosting.md in the template");
  return true;
}

async function setup(ctx) {
  console.log(bold("The guided setup: each step says what it found and asks before it changes anything."));
  if (!stepTools(ctx)) return 1;
  if (!(await stepPlugin(ctx)) && !ctx.engine) {
    fail("without the engine the rest cannot run");
    return 1;
  }
  if (!(await stepInstance(ctx))) return 1;
  await stepPackages(ctx);
  await stepRolePlugins(ctx);
  await stepSecrets(ctx);
  await stepHost(ctx);
  heading("Done");
  if (await confirm("Run engine doctor now (one ok/FAIL line per check)?")) return ctx.engine_(["doctor"]).code;
  return 0;
}

// ---- the menu ----

function needs(ctx) {
  if (!ctx.engine) fail("no engine yet: choose Set up (step 2 installs the plugin)");
  else if (!lib.isInstance(ctx.instance)) fail("no brand repository yet: choose Set up, or Choose the brand repository");
  else return true;
  return false;
}

function header(ctx) {
  const found = ctx.engine;
  console.log(`\n${bold("comms-engine")} ${dim(`setup ${PKG.version || ""}`)}`);
  console.log(`  engine      ${found ? `${lib.engineVersion(found.home) || "?"}, ${found.why}` : "not installed (Set up, step 2)"}`);
  console.log(`  repository  ${lib.isInstance(ctx.instance) ? `${tilde(ctx.instance)} (${lib.brandName(ctx.instance) || "no brand name yet"})` : "none yet (Set up, step 3)"}`);
}

async function menu(ctx) {
  for (;;) {
    header(ctx);
    const ready = Boolean(ctx.engine) && lib.isInstance(ctx.instance);
    const items = [
      { label: "Set up, step by step", hint: "tools, plugin, repository, packages, plugins, secrets, office Mac", act: () => setup(ctx) },
      { label: "Doctor", hint: "one ok/FAIL line per check", act: () => needs(ctx) && ctx.engine_(["doctor"]) },
      { label: "Status", hint: "jobs, secrets, plugins, the last cycle", act: () => needs(ctx) && ctx.engine_(["status"]) },
      { label: "Open the console", hint: "the engine's own screen: jobs, logs, runs", act: () => needs(ctx) && ctx.engine_(["engine_tui"]), back: true },
      { label: "Choose the brand repository", hint: "a folder holding brand.json", act: () => chooseFolder(ctx) },
      { label: "Quit" },
    ];
    let pick;
    try {
      pick = await select("\nWhat next?", items, ready ? 1 : 0);
    } catch (e) {
      if (e instanceof Cancelled) return 0;
      throw e;
    }
    const item = items[pick];
    if (!item.act) return 0;
    try {
      await item.act();
      if (!item.back) await pause();
    } catch (e) {
      if (!(e instanceof Cancelled)) throw e;
    }
  }
}

export async function main(argv = process.argv.slice(2)) {
  let args;
  try {
    args = lib.parseArgs(argv);
  } catch (e) {
    console.error(`comms-engine-setup: ${e.message}`);
    return 2;
  }
  if (args.help) {
    console.log(HELP);
    return 0;
  }
  if (args.version) {
    console.log(PKG.version || "?");
    return 0;
  }
  const ctx = new Context(lib.chooseInstance({ flag: args.instance }));
  const interactive = process.stdin.isTTY && process.stdout.isTTY;
  const direct = { doctor: ["doctor"], status: ["status"], console: ["engine_tui"] };
  if (direct[args.cmd]) return needs(ctx) ? ctx.engine_([...direct[args.cmd], ...args.rest]).code : 1;
  if (args.cmd && args.cmd !== "setup") {
    console.error(`comms-engine-setup: no command ${JSON.stringify(args.cmd)}\n\n${HELP}`);
    return 2;
  }
  if (!interactive) {
    console.error(`comms-engine-setup: the menu and the setup need a terminal; without one, run doctor or status\n\n${HELP}`);
    return 2;
  }
  try {
    return args.cmd === "setup" ? await setup(ctx) : await menu(ctx);
  } catch (e) {
    if (e instanceof Cancelled) return 130;
    throw e;
  }
}

if (process.argv[1] && fs.realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().then((code) => process.exit(code ?? 0));
}
