// lib.mjs - what the setup command knows about this machine, with no terminal and no side effect.
//
// Why: the menu and the guided setup in setup.mjs ask questions and run commands; every
// answer they act on (which engine, which instance, what is missing) is worked out here, so
// the tests read it without a terminal. The engine is found the way the launchd shim finds
// it (schedule/comms_engine_shim.py), so the menu, the schedules and Claude Code agree.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const PLUGIN = "comms-engine@comms-engine";
export const MARKET = "comms-engine";
export const MIN_PYTHON = [3, 11];
export const MIN_NODE = 20;
// Folders macOS protects from a launchd job; an instance the schedules run must live elsewhere.
export const PROTECTED = ["Desktop", "Documents", "Downloads"];

export function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

const engineBin = (root) => path.join(root, "bin", "engine");
const isEngine = (root) => Boolean(root) && fs.existsSync(engineBin(root));
const real = (p) => {
  try {
    return fs.realpathSync(p);
  } catch {
    return path.resolve(p);
  }
};

export function pluginsRoot(env = process.env) {
  const given = (env.CLAUDE_CODE_PLUGIN_CACHE_DIR || "").trim();
  if (given) return expandHome(given, env);
  const config = (env.CLAUDE_CONFIG_DIR || "").trim();
  return path.join(expandHome(config || "~/.claude", env), "plugins");
}

export function homeDir(env = process.env) {
  return env.HOME || os.homedir();
}

export function expandHome(p, env = process.env) {
  if (p === "~") return homeDir(env);
  if (p.startsWith("~/")) return path.join(homeDir(env), p.slice(2));
  return p;
}

export function engineVersion(root) {
  return readJson(path.join(root, ".claude-plugin", "plugin.json"))?.version || null;
}

// {home, why} for the engine to run against `instance`, or null; first hit wins:
// COMMS_ENGINE_HOME, the install for this instance, a user-scope install, the newest
// install, then the engine beside this command in a template checkout.
export function findEngine({ env = process.env, instance = null, beside = null } = {}) {
  const home = (env.COMMS_ENGINE_HOME || "").trim();
  if (isEngine(home)) return { home, why: "COMMS_ENGINE_HOME", installed: false };
  const installed = readJson(path.join(pluginsRoot(env), "installed_plugins.json"));
  const entries = ((installed?.plugins || {})[PLUGIN] || []).filter(
    (e) => e && typeof e === "object" && isEngine(String(e.installPath || "")),
  );
  if (instance) {
    const want = real(instance);
    const mine = entries.find((e) => e.projectPath && real(e.projectPath) === want);
    if (mine) return { home: mine.installPath, why: `the ${mine.scope || "project"} install for this repository`, installed: true };
  }
  const user = entries.find((e) => e.scope === "user");
  if (user) return { home: user.installPath, why: "the user install", installed: true };
  if (entries.length) {
    const stamp = (e) => String(e.lastUpdated || e.installedAt || "");
    const newest = entries.reduce((a, b) => (stamp(b) > stamp(a) ? b : a));
    return { home: newest.installPath, why: "the most recent install", installed: true, elsewhere: newest.projectPath || null };
  }
  if (isEngine(beside)) return { home: beside, why: "the template checkout this command runs from", installed: false };
  return null;
}

// The engine inside the template Claude Code keeps as the comms-engine marketplace (or the
// checkout beside this command): `new-instance` copies a brand's files from there.
export function templateEngine({ env = process.env, beside = null } = {}) {
  const known = readJson(path.join(pluginsRoot(env), "known_marketplaces.json")) || {};
  const loc = known[MARKET]?.installLocation;
  const candidates = [loc && path.join(loc, "plugins", "comms-engine"), beside];
  return candidates.find((c) => isEngine(c) && fs.existsSync(path.join(c, "..", "..", ".claude-plugin", "marketplace.json"))) || null;
}

export function knownMarketplace(name, env = process.env) {
  const known = readJson(path.join(pluginsRoot(env), "known_marketplaces.json")) || {};
  return Object.prototype.hasOwnProperty.call(known, name);
}

// The nearest folder at or above `start` that holds brand.json, or null.
export function findInstance(start) {
  let dir = path.resolve(start);
  for (;;) {
    if (fs.existsSync(path.join(dir, "brand.json"))) return dir;
    const up = path.dirname(dir);
    if (up === dir) return null;
    dir = up;
  }
}

export function isInstance(dir) {
  return Boolean(dir) && fs.existsSync(path.join(dir, "brand.json"));
}

export function brandName(instance) {
  const brand = readJson(path.join(instance, "brand.json"))?.brand || {};
  return brand.name || brand.slug || null;
}

// The one remembered answer: which instance the menu opens on.
export function configFile(env = process.env) {
  const base = (env.XDG_CONFIG_HOME || "").trim() || path.join(homeDir(env), ".config");
  return path.join(base, "comms-engine", "setup.json");
}

export function loadConfig(env = process.env) {
  return readJson(configFile(env)) || {};
}

export function saveConfig(patch, env = process.env) {
  const file = configFile(env);
  const doc = { ...loadConfig(env), ...patch };
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(doc, null, 2) + "\n");
  return doc;
}

// The instance the menu answers for: the flag, the folder it runs in, then the remembered one.
export function chooseInstance({ flag = null, cwd = process.cwd(), env = process.env } = {}) {
  if (flag) return path.resolve(expandHome(flag, env));
  const here = findInstance(cwd);
  if (here) return here;
  const saved = loadConfig(env).instance;
  return isInstance(saved) ? saved : null;
}

// "Desktop" when `dir` is inside ~/Desktop (and so on), else null.
export function protectedFolder(dir, env = process.env) {
  const home = path.resolve(homeDir(env));
  const target = path.resolve(expandHome(dir, env));
  for (const name of PROTECTED) {
    const root = path.join(home, name);
    if (target === root || target.startsWith(root + path.sep)) return name;
  }
  return null;
}

// "Python 3.12.4" or "3.12.4" -> [3, 12, 4]; null when there is no version in it.
export function parseVersion(text) {
  const m = String(text || "").match(/(\d+)\.(\d+)(?:\.(\d+))?/);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3] || 0)] : null;
}

export function atLeast(version, min) {
  if (!version) return false;
  for (let i = 0; i < min.length; i++) {
    if ((version[i] || 0) !== min[i]) return (version[i] || 0) > min[i];
  }
  return true;
}

// The secrets `engine status --json` reports missing: [{name, required}], required first.
export function missingSecrets(status) {
  return (status?.secrets || [])
    .filter((s) => !s.present)
    .map((s) => ({ name: s.name, required: Boolean(s.required) }))
    .sort((a, b) => Number(b.required) - Number(a.required));
}

// The plugins `engine plugins` reports not installed: [{id, market, scope}], e.g. salon@atelier.
export function missingPlugins(text) {
  return String(text || "")
    .split("\n")
    .map((l) => l.match(/^(\S+)@(\S+): not installed(?:.*--scope (\S+))?/))
    .filter(Boolean)
    .map((m) => ({ id: `${m[1]}@${m[2]}`, market: m[2], scope: m[3] || "project" }));
}

// The python3 `engine runtime` names in its line, so pip installs into the one the jobs start.
export function runtimePython(line) {
  return String(line || "").match(/the jobs' python3 (\S+)/)?.[1] || null;
}

// A marketplace source as `claude plugin marketplace add` takes it: owner/repo or a git URL.
export function marketplaceArg(source) {
  if (!source) return null;
  if (typeof source === "string") return source.trim() || null;
  return source.repo || source.url || source.path || null;
}

export function parseArgs(argv) {
  const out = { cmd: null, instance: null, help: false, version: false, rest: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "-h" || a === "--help") out.help = true;
    else if (a === "-v" || a === "--version") out.version = true;
    else if (a === "--instance") {
      if (i + 1 >= argv.length) throw new Error("--instance needs a folder");
      out.instance = argv[++i];
    } else if (a.startsWith("--instance=")) out.instance = a.slice("--instance=".length);
    else if (!out.cmd) out.cmd = a;
    else out.rest.push(a);
  }
  return out;
}
