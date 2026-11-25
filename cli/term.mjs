// term.mjs - the few terminal prompts setup.mjs needs, from Node's standard library alone.
//
// Why: `npx` should start without fetching a prompt library, so the menu is readline plus a
// raw-mode key loop. Each prompt opens and closes its own reader, so stdin is free again
// before a command (engine init, a hidden secret prompt, the console) takes the terminal.

import readline from "node:readline";
import { createInterface } from "node:readline/promises";

const tty = process.stdout.isTTY && !process.env.NO_COLOR;
const paint = (code) => (s) => (tty ? `\x1b[${code}m${s}\x1b[0m` : String(s));
export const bold = paint("1");
export const dim = paint("2");
export const green = paint("32");
export const red = paint("31");
export const yellow = paint("33");
export const cyan = paint("36");

export const ok = (s) => console.log(`  ${green("ok")}    ${s}`);
export const fail = (s) => console.log(`  ${red("FAIL")}  ${s}`);
export const note = (s) => console.log(`  ${yellow("note")}  ${s}`);
export const heading = (s) => console.log(`\n${bold(cyan(s))}`);

export class Cancelled extends Error {}

export async function ask(question, fallback = "") {
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  const stop = new AbortController();
  rl.on("SIGINT", () => stop.abort());
  rl.on("close", () => stop.abort());
  try {
    const hint = fallback ? dim(` [${fallback}]`) : "";
    const answer = await rl.question(`${question}${hint} `, { signal: stop.signal });
    return answer.trim() || fallback;
  } catch {
    process.stdout.write("\n");
    throw new Cancelled();
  } finally {
    rl.close();
  }
}

export async function confirm(question, fallback = true) {
  for (;;) {
    const answer = (await ask(`${question} ${dim(fallback ? "(Y/n)" : "(y/N)")}`)).toLowerCase();
    if (!answer) return fallback;
    if (["y", "yes"].includes(answer)) return true;
    if (["n", "no"].includes(answer)) return false;
  }
}

export async function pause(message = "Press Enter to go back to the menu") {
  await ask(dim(message));
}

// One choice from `options` ([{label, hint?}]) by arrow keys or its number; returns the index.
export async function select(question, options, initial = 0) {
  if (!process.stdin.isTTY || typeof process.stdin.setRawMode !== "function") {
    options.forEach((o, i) => console.log(`  ${i + 1}. ${o.label}${o.hint ? dim(`  ${o.hint}`) : ""}`));
    for (;;) {
      const n = Number(await ask(question, String(initial + 1)));
      if (Number.isInteger(n) && n >= 1 && n <= options.length) return n - 1;
    }
  }
  let at = initial;
  const draw = (first) => {
    if (!first) process.stdout.write(`\x1b[${options.length}A`);
    options.forEach((o, i) => {
      const line = i === at ? `${cyan(">")} ${bold(o.label)}` : `  ${o.label}`;
      process.stdout.write(`\x1b[2K${line}${o.hint ? dim(`  ${o.hint}`) : ""}\n`);
    });
  };
  console.log(question + dim("  (arrows or a number, Enter to choose)"));
  process.stdout.write("\x1b[?25l");
  draw(true);
  readline.emitKeypressEvents(process.stdin);
  process.stdin.setRawMode(true);
  process.stdin.resume();
  try {
    return await new Promise((resolve, reject) => {
      const onKey = (str, key = {}) => {
        if ((key.ctrl && key.name === "c") || key.name === "escape" || str === "q") {
          process.stdin.off("keypress", onKey);
          reject(new Cancelled());
        } else if (key.name === "up" || str === "k") {
          at = (at - 1 + options.length) % options.length;
          draw(false);
        } else if (key.name === "down" || str === "j") {
          at = (at + 1) % options.length;
          draw(false);
        } else if (key.name === "return" || key.name === "enter") {
          process.stdin.off("keypress", onKey);
          resolve(at);
        } else if (/^[1-9]$/.test(str || "") && Number(str) <= options.length) {
          at = Number(str) - 1;
          draw(false);
          process.stdin.off("keypress", onKey);
          resolve(at);
        }
      };
      process.stdin.on("keypress", onKey);
    });
  } finally {
    process.stdin.setRawMode(false);
    process.stdin.pause();
    process.stdout.write("\x1b[?25h");
  }
}
