// The setup command's answers (which engine, which repository, what is missing) on fixtures,
// and the package that `npx github:...` installs: run with `npm test`.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import * as lib from "../lib.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const ENGINE = path.join(ROOT, "plugins", "comms-engine");

function tmp(t) {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "ce-setup-"));
  t.after(() => fs.rmSync(d, { recursive: true, force: true }));
  return fs.realpathSync(d);
}

function fakeEngine(dir, version = "1.0.0") {
  fs.mkdirSync(path.join(dir, "bin"), { recursive: true });
  fs.mkdirSync(path.join(dir, ".claude-plugin"), { recursive: true });
  fs.writeFileSync(path.join(dir, "bin", "engine"), "#!/usr/bin/env python3\n");
  fs.writeFileSync(path.join(dir, ".claude-plugin", "plugin.json"), JSON.stringify({ name: "comms-engine", version }));
  return dir;
}

function plugins(root, entries, known = {}) {
  fs.mkdirSync(root, { recursive: true });
  fs.writeFileSync(path.join(root, "installed_plugins.json"), JSON.stringify({ version: 2, plugins: { [lib.PLUGIN]: entries } }));
  fs.writeFileSync(path.join(root, "known_marketplaces.json"), JSON.stringify(known));
}

test("the engine is found the way the launchd shim finds it", (t) => {
  const d = tmp(t);
  const env = { HOME: d, CLAUDE_CODE_PLUGIN_CACHE_DIR: path.join(d, "plugins") };
  const user = fakeEngine(path.join(d, "cache", "user"), "1.0.0");
  const mine = fakeEngine(path.join(d, "cache", "mine"), "1.1.0");
  const other = fakeEngine(path.join(d, "cache", "other"));
  const brand = path.join(d, "brand");
  fs.mkdirSync(brand);
  plugins(env.CLAUDE_CODE_PLUGIN_CACHE_DIR, [
    { scope: "local", installPath: other, projectPath: path.join(d, "elsewhere"), lastUpdated: "2026-11-14" },
    { scope: "user", installPath: user, lastUpdated: "2026-11-01" },
    { scope: "project", installPath: mine, projectPath: brand, lastUpdated: "2026-10-01" },
    { scope: "user", installPath: path.join(d, "gone") },
  ]);
  assert.equal(lib.findEngine({ env, instance: brand }).home, mine, "the install for this repository first");
  assert.equal(lib.findEngine({ env, instance: path.join(d, "x") }).home, user, "then the user install");
  assert.equal(lib.findEngine({ env: { ...env, COMMS_ENGINE_HOME: other }, instance: brand }).home, other);
  assert.equal(lib.engineVersion(mine), "1.1.0");

  plugins(env.CLAUDE_CODE_PLUGIN_CACHE_DIR, [
    { scope: "local", installPath: user, projectPath: "/a", lastUpdated: "2026-01-01" },
    { scope: "local", installPath: other, projectPath: "/b", lastUpdated: "2026-11-01" },
  ]);
  const newest = lib.findEngine({ env });
  assert.deepEqual([newest.home, newest.installed, newest.elsewhere], [other, true, "/b"], "and it says where Claude Code loads it");

  plugins(env.CLAUDE_CODE_PLUGIN_CACHE_DIR, []);
  assert.equal(lib.findEngine({ env }), null, "nothing installed and no checkout beside");
  const beside = lib.findEngine({ env, beside: ENGINE });
  assert.deepEqual([beside.home, beside.installed], [ENGINE, false]);
});

test("a new repository is copied from the marketplace's template, never from a bare engine", (t) => {
  const d = tmp(t);
  const env = { HOME: d, CLAUDE_CODE_PLUGIN_CACHE_DIR: path.join(d, "plugins") };
  const market = path.join(d, "market");
  fakeEngine(path.join(market, "plugins", "comms-engine"));
  plugins(env.CLAUDE_CODE_PLUGIN_CACHE_DIR, [], { "comms-engine": { installLocation: market } });
  assert.equal(lib.templateEngine({ env }), null, "an engine without the marketplace manifest around it is no template");
  fs.mkdirSync(path.join(market, ".claude-plugin"));
  fs.writeFileSync(path.join(market, ".claude-plugin", "marketplace.json"), "{}");
  assert.equal(lib.templateEngine({ env }), path.join(market, "plugins", "comms-engine"));
  assert.equal(lib.templateEngine({ env: { ...env, CLAUDE_CODE_PLUGIN_CACHE_DIR: path.join(d, "none") }, beside: ENGINE }), ENGINE);
  assert.ok(lib.knownMarketplace("comms-engine", env));
  assert.ok(!lib.knownMarketplace("atelier", env));
});

test("the repository answered for: the flag, the folder, then the remembered one", (t) => {
  const d = tmp(t);
  const env = { HOME: d, XDG_CONFIG_HOME: path.join(d, "config") };
  const brand = path.join(d, "brand");
  fs.mkdirSync(path.join(brand, "Content", "Calendar"), { recursive: true });
  fs.writeFileSync(path.join(brand, "brand.json"), JSON.stringify({ brand: { slug: "acme", name: "Acme" } }));
  assert.equal(lib.findInstance(path.join(brand, "Content", "Calendar")), brand);
  assert.equal(lib.brandName(brand), "Acme");
  assert.equal(lib.chooseInstance({ cwd: d, env }), null);
  lib.saveConfig({ instance: brand }, env);
  assert.equal(lib.configFile(env), path.join(d, "config", "comms-engine", "setup.json"));
  assert.equal(lib.chooseInstance({ cwd: d, env }), brand);
  assert.equal(lib.chooseInstance({ cwd: path.join(brand, "Content"), env }), brand);
  assert.equal(lib.chooseInstance({ flag: "~/other", cwd: brand, env }), path.join(d, "other"));
  lib.saveConfig({ instance: path.join(d, "deleted") }, env);
  assert.equal(lib.chooseInstance({ cwd: d, env }), null, "a remembered folder that is gone is no answer");
});

test("macOS's protected folders are named", () => {
  const env = { HOME: "/home/x" };
  assert.equal(lib.protectedFolder("~/Desktop/work/brand", env), "Desktop");
  assert.equal(lib.protectedFolder("/home/x/Documents", env), "Documents");
  assert.equal(lib.protectedFolder("~/Downloadsish/brand", env), null);
  assert.equal(lib.protectedFolder("~/comms/brand", env), null);
});

test("versions, secrets, plugins and the runtime line are read from the engine's own output", () => {
  assert.deepEqual(lib.parseVersion("Python 3.12.4"), [3, 12, 4]);
  assert.deepEqual(lib.parseVersion("23.3.0"), [23, 3, 0]);
  assert.equal(lib.parseVersion("none"), null);
  assert.ok(lib.atLeast([3, 11, 0], lib.MIN_PYTHON));
  assert.ok(lib.atLeast([3, 14, 0], lib.MIN_PYTHON));
  assert.ok(!lib.atLeast([3, 9, 18], lib.MIN_PYTHON));
  assert.ok(!lib.atLeast(null, lib.MIN_PYTHON));

  const status = { secrets: [
    { name: "APIFY_TOKEN", required: false, present: false },
    { name: "TWITTERAPI_IO_API_KEY", required: true, present: false },
    { name: "LINKEDIN_ORG_ID", required: false, present: true },
  ] };
  assert.deepEqual(lib.missingSecrets(status), [
    { name: "TWITTERAPI_IO_API_KEY", required: true },
    { name: "APIFY_TOKEN", required: false },
  ]);
  assert.deepEqual(lib.missingSecrets(null), []);

  const plugins = [
    "marketplace: (not set: ...)",
    "atelier@atelier: installed",
    "salon@atelier: not installed  -> claude plugin install salon@atelier --scope project",
    "motion@atelier: unknown (claude not on PATH, ...)",
  ].join("\n");
  assert.deepEqual(lib.missingPlugins(plugins), [{ id: "salon@atelier", market: "atelier", scope: "project" }]);

  const line = "runtime: the jobs' python3 /opt/homebrew/bin/python3 -> /x (3.14.0) cannot import yaml, so every job would fail";
  assert.equal(lib.runtimePython(line), "/opt/homebrew/bin/python3");
  assert.equal(lib.runtimePython("runtime: no python3 on the jobs' PATH"), null);
});

test("the command line", () => {
  assert.deepEqual(lib.parseArgs([]), { cmd: null, instance: null, help: false, version: false, rest: [] });
  assert.equal(lib.parseArgs(["setup", "--instance", "~/b"]).instance, "~/b");
  assert.equal(lib.parseArgs(["--instance=/b", "doctor"]).cmd, "doctor");
  assert.throws(() => lib.parseArgs(["--instance"]), /needs a folder/);
});

test("the package npx installs: one bin, the engine's version, the template's marketplace", () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8"));
  const manifest = JSON.parse(fs.readFileSync(path.join(ENGINE, ".claude-plugin", "plugin.json"), "utf8"));
  const engineJson = JSON.parse(fs.readFileSync(path.join(ENGINE, "engine.json"), "utf8"));
  assert.equal(pkg.version, manifest.version, "the setup command ships with the engine it sets up");
  assert.equal(pkg.commsEngine.marketplace, engineJson.params.instance.marketplace.repo);
  assert.equal(pkg.private, true, "installed from GitHub, never published");
  assert.deepEqual(Object.keys(pkg.dependencies || {}), [], "npx starts with nothing to fetch");
  const bins = Object.values(pkg.bin);
  assert.equal(bins.length, 1);
  assert.ok(fs.statSync(path.join(ROOT, bins[0])).mode & 0o100, "the bin is executable");
  assert.ok(pkg.files.includes("requirements.txt"));
});

test("headless: help, refusal and a command that needs a repository", (t) => {
  const d = tmp(t);
  const env = { ...process.env, HOME: d, XDG_CONFIG_HOME: path.join(d, "c"), CLAUDE_CODE_PLUGIN_CACHE_DIR: path.join(d, "p") };
  delete env.COMMS_ENGINE_INSTANCE;
  const cli = (args) => spawnSync(process.execPath, [path.join(ROOT, "cli", "setup.mjs"), ...args], { cwd: d, env, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  assert.equal(cli(["--help"]).status, 0);
  assert.equal(cli(["--version"]).stdout.trim(), JSON.parse(fs.readFileSync(path.join(ROOT, "package.json"), "utf8")).version);
  const menu = cli([]);
  assert.equal(menu.status, 2);
  assert.match(menu.stderr, /need a terminal/);
  assert.equal(cli(["nope"]).status, 2);
  const doctor = cli(["doctor"]);
  assert.equal(doctor.status, 1);
  assert.match(doctor.stdout, /no brand repository yet/);
});
