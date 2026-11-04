import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "node:url";

const frontend = new URL(
  process.env.ARISTOTLE_E2E_BASE_URL || "http://127.0.0.1:5180",
);
const backend = new URL(
  process.env.ARISTOTLE_E2E_BACKEND_URL || "http://127.0.0.1:8021",
);
const reuseExistingServer =
  process.env.ARISTOTLE_E2E_REUSE_SERVER === "1" ||
  (!process.env.CI && process.env.ARISTOTLE_E2E_REUSE_SERVER !== "0");

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: frontend.origin, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer:
    process.env.ARISTOTLE_E2E_SKIP_WEBSERVER === "1"
      ? undefined
      : [
          {
            command: "node tests/e2e/start-backend.mjs",
            cwd: fileURLToPath(new URL(".", import.meta.url)),
            url: new URL("/health", backend).href,
            env: { ARISTOTLE_E2E_BACKEND_URL: backend.origin },
            reuseExistingServer,
            timeout: 120_000,
            gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
          },
          {
            command: "npm run dev -- --strictPort",
            cwd: fileURLToPath(new URL(".", import.meta.url)),
            url: frontend.origin,
            env: {
              ARISTOTLE_BACKEND_URL: backend.origin,
              ARISTOTLE_E2E_FRONTEND_HOST: frontend.hostname,
              ARISTOTLE_E2E_FRONTEND_PORT: frontend.port || "80",
              // Tests exercise the same-origin Vite proxy, even with a local .env override.
              VITE_API_BASE_URL: "/api/v1",
            },
            reuseExistingServer,
            timeout: 60_000,
          },
        ],
});
