import { defineConfig } from "drizzle-kit";
import { DB_PATH } from "./lib/paths";

// One source of DDL. `npm run generate` writes drizzle/*.sql from db/schema.ts,
// and scripts/desk_sync.py applies that same file, so the TypeScript and Python
// runtimes cannot end up with different tables.
export default defineConfig({
  schema: "./db/schema.ts",
  out: "./drizzle",
  dialect: "sqlite",
  dbCredentials: { url: `file:${DB_PATH}` },
});
