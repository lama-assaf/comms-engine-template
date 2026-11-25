import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` serves the app on :5173 and sends /api and /media to the
// control server already running on 127.0.0.1:4320 (control.py start).
// `npm run build` writes dist/, which control.py serves; dist/ is committed so
// a fresh clone runs with plain python3.
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: { outDir: "dist", emptyOutDir: true, assetsDir: "assets", sourcemap: false },
  server: {
    host: "127.0.0.1",
    // changeOrigin: the control server answers only a Host of 127.0.0.1:<its port>.
    // In dev the page has no token, so it reads but cannot change anything.
    proxy: {
      "/api": { target: "http://127.0.0.1:4320", changeOrigin: true },
      "/media": { target: "http://127.0.0.1:4320", changeOrigin: true },
    },
  },
});
