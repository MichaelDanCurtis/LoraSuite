/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { configDefaults } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    allowedHosts: ["host.docker.internal"],
    port: 5173,
    strictPort: true,
    watch: {
      ignored: ["**/src-tauri/**", "**/engine/.venv/**", "**/.lorasuite/**", "**/archive/**"],
    },
  },
  test: {
    exclude: [...configDefaults.exclude, "**/.lorasuite/**", "**/archive/**"],
    environment: "jsdom",
    setupFiles: ["src/setupTests.ts"],
  },
});
