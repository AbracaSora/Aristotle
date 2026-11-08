import { rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";

// Reset this disposable fixture BEFORE migrations and webServer startup.
// Playwright globalSetup runs after webServer setup and must not unlink a live DB.
const db = fileURLToPath(new URL("../../../../.local/playwright.db", import.meta.url));
await Promise.all(
  [db, `${db}-wal`, `${db}-shm`].map((file) => rm(file, { force: true })),
);
