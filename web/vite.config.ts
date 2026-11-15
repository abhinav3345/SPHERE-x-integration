import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * Where the FastAPI service listens during development (see the repo CLAUDE.md, section 0).
 * Set TOMBAUGH_API_URL to point the dev proxy elsewhere, e.g. when port 8080 is taken.
 */
const API_TARGET = process.env.TOMBAUGH_API_URL ?? "http://localhost:8080";

const apiProxy = { "/api": { target: API_TARGET, changeOrigin: true } };

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: apiProxy },
  preview: { proxy: apiProxy },
  build: {
    target: "es2022",
    // Two pages, so static hosting needs no rewrite rule: / is the landing page (small, no player
    // code) and /look/ is the comparator.
    rollupOptions: {
      input: {
        landing: fileURLToPath(new URL("./index.html", import.meta.url)),
        look: fileURLToPath(new URL("./look/index.html", import.meta.url)),
      },
    },
  },
  test: {
    // Pure maths and fetch logic only: no DOM emulation.
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
