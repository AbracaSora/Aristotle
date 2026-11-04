import { rm } from "node:fs/promises";
import path from "node:path";
import type { FullConfig } from "@playwright/test";

export default async function globalSetup(_config: FullConfig) {
  const db = path.resolve(process.cwd(), "../../.local/playwright.db");
  await Promise.all(
    [db, `${db}-wal`, `${db}-shm`].map((file) => rm(file, { force: true })),
  );
}
