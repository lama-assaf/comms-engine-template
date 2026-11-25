import { createClient, type Client } from "@libsql/client";
import { drizzle, type LibSQLDatabase } from "drizzle-orm/libsql";
import { DB_PATH } from "@/lib/paths";
import * as schema from "./schema";

/*
 * One connection per process, held on globalThis so Next's dev server does not
 * open a new one on every hot reload.
 *
 * The driver is libSQL in local-file mode, which writes an ordinary SQLite
 * file: `sqlite3.connect(state/desk.db)` in `scripts/desk_sync.py` reads the
 * same bytes. That shared file is the whole integration between the two
 * runtimes — there is no API between the app and the engine, which is why the
 * app can be stopped, restarted or redeployed without the cycle noticing.
 *
 * (better-sqlite3 is the more usual Drizzle driver for this and would work
 * unchanged; it segfaults on the Node 23 build this machine runs, so libSQL is
 * the one that actually opens the file here.)
 */
declare global {
  // eslint-disable-next-line no-var
  var __deskClient: Client | undefined;
}

const client = globalThis.__deskClient ?? createClient({ url: `file:${DB_PATH}` });
if (process.env.NODE_ENV !== "production") globalThis.__deskClient = client;

export const db: LibSQLDatabase<typeof schema> = drizzle(client, { schema });
export { schema };
