/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// VITE_BASE_PATH lets the UI be hosted under an intranet sub-path, e.g. /apps/attendance-mis/
// VITE_API_TARGET is the FastAPI server the dev server proxies /api to.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    base: env.VITE_BASE_PATH || "/",
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": { target: env.VITE_API_TARGET || "http://127.0.0.1:8000", changeOrigin: false },
      },
    },
    // assetsInlineLimit 0: never inline fonts/images as data: URLs (blocked by the API's CSP).
    build: { outDir: "dist", sourcemap: false, assetsInlineLimit: 0 },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test-setup.ts"],
    },
  };
});
