import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const cwd = fileURLToPath(new URL("../../../../", import.meta.url));
const backend = new URL(
  process.env.ARISTOTLE_E2E_BACKEND_URL || "http://127.0.0.1:8021",
);
// Explicit Python supports preinstalled environments without requiring uv.
const python = process.env.ARISTOTLE_E2E_PYTHON;
let executable = python;
let prefix = [];
if (!executable && spawnSync("uv", ["--version"]).status === 0) {
  executable = "uv";
  prefix = ["run", "--locked", "python"];
}
if (!executable) {
  executable = ["python3", "python"].find(
    (candidate) => spawnSync(candidate, ["--version"]).status === 0,
  );
}
if (!executable)
  throw new Error(
    "Install uv or set ARISTOTLE_E2E_PYTHON to a Python executable.",
  );

const directory = mkdtempSync(join(tmpdir(), "aristotle-e2e-"));
const env = {
  ...process.env,
  ARISTOTLE_DATABASE_URL: `sqlite:///${join(directory, "aristotle.db")}`,
};
process.on("exit", () => rmSync(directory, { recursive: true, force: true }));
const seeded = spawnSync(
  executable,
  [...prefix, "-m", "aristotle_backend.seed", "--demo", "--design-flow"],
  {
    cwd,
    env,
    stdio: "inherit",
  },
);
if (seeded.error) throw seeded.error;
if (seeded.status !== 0) process.exit(seeded.status || 1);

const server = spawn(
  executable,
  [
    ...prefix,
    "-m",
    "uvicorn",
    "aristotle_backend.app:create_app",
    "--factory",
    "--host",
    backend.hostname,
    "--port",
    backend.port || "80",
  ],
  {
    cwd,
    env,
    stdio: "inherit",
  },
);
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.kill(signal));
}
server.on("error", (error) => {
  console.error(error);
  process.exit(1);
});
server.on("exit", (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
