import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const repoRoot = path.resolve(process.cwd(), "../..");
const uv = process.env.UV_BIN || path.join(process.env.HOME || ".", ".local/bin/uv");
// A dedicated database: E2E must never seed or mutate the developer's business DB.
const apiPort = 18021;
const uiPort = 15180;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  fullyParallel: false,
  retries: process.env.CI ? 2 : 0,
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${uiPort}`,
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
    ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}),
  },
  webServer: [
    {
      command: `${uv} run python code/frontend/tests/e2e/server.py ${apiPort}`,
      cwd: repoRoot,
      url: `http://127.0.0.1:${apiPort}/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `ARISTOTLE_BACKEND_URL=http://127.0.0.1:${apiPort} npm run dev -- --host 127.0.0.1 --port ${uiPort} --strictPort`,
      cwd: ".",
      url: `http://127.0.0.1:${uiPort}`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
