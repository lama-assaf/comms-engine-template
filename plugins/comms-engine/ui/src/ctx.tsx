import { createContext, useContext } from "react";
import type { State } from "./types";

export type DrawerSpec =
  | { kind: "post"; id: string }
  | { kind: "theme"; tag: string; grade?: boolean }
  | { kind: "newTheme"; tag?: string; what?: string }
  | { kind: "suggestion"; handle: string }
  | { kind: "finding"; id: string }
  | { kind: "text"; title: string; kicker?: string; text: string; chips?: string[]; url?: string };

export interface Ctx {
  S: State;
  /** Read every view again. */
  reload: () => Promise<void>;
  /** Ask the engine for one change; says how it went, reloads on success or on a conflict. */
  act: (path: string, body: unknown, done: string) => Promise<boolean>;
  toast: (m: string) => void;
  open: (d: DrawerSpec) => void;
  close: () => void;
  /** A page (`themes`), a post (`post:<id>`), a story question (`q:<id>`) or a slide (`slide:<n>`). */
  go: (target: string) => void;
  slide: number;
}

export const AppCtx = createContext<Ctx | null>(null);
export const useApp = () => {
  const c = useContext(AppCtx);
  if (!c) throw new Error("outside the app");
  return c;
};
