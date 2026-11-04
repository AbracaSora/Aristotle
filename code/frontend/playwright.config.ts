import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const repoRoot = path.resolve(process.cwd(), "../..");
const uv = process.env.UV_BIN || path.join(process.env.HOME || ".", ".local/bin/uv");

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  reporter: "list",
  globalSetup: "./tests/e2e/global-setup.ts",
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:5180",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: [
    {
      command: `ARISTOTLE_DATABASE_URL=sqlite:///./.local/playwright.db ${uv} run python -m aristotle_backend.seed --demo --design-flow && ARISTOTLE_DATABASE_URL=sqlite:///./.local/playwright.db ${uv} run uvicorn aristotle_backend.app:create_app --factory --host 127.0.0.1 --port 8021`,
      cwd: repoRoot,
      url: "http://127.0.0.1:8021/health",
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "ARISTOTLE_BACKEND_URL=http://127.0.0.1:8021 npm run dev -- --host 127.0.0.1 --port 5180 --strictPort",
      cwd: ".",
      url: "http://127.0.0.1:5180",
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
