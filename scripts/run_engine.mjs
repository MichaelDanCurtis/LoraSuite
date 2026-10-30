import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { loadEnv } from "vite";

const root = process.cwd();
const configured = process.env.LORASUITE_ENGINE_PYTHON?.trim();
const python = configured || path.join(
  root,
  "engine",
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);

if (!existsSync(python)) {
  console.error(`LoraSuite engine Python was not found at ${python}.`);
  console.error("Create engine/.venv and install engine[dev].");
  process.exit(1);
}

const mode = process.argv[2];
const extra = process.argv.slice(3);
let commandArguments;
switch (mode) {
  case "serve": {
    const settings = { ...loadEnv("development", root, "VITE_"), ...process.env };
    const address = new URL(settings.VITE_LORASUITE_ENGINE_URL || "http://127.0.0.1:8765");
    if (address.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(address.hostname) || !address.port) {
      throw new Error("The development engine must use a loopback HTTP address with an explicit port.");
    }
    commandArguments = [
      "-m", "uvicorn", "lorasuite_engine.main:app",
      "--app-dir", "engine/src",
      "--host", "127.0.0.1",
      "--port", address.port,
      "--reload",
      ...extra,
    ];
    break;
  }
  case "test":
    commandArguments = ["-m", "pytest", "engine/tests", "-q", ...extra];
    break;
  case "build-sidecar":
    commandArguments = ["scripts/build_engine_sidecar.py", ...extra];
    break;
  case "smoke-sidecar":
    commandArguments = ["scripts/smoke_engine_sidecar.py", ...extra];
    break;
  default:
    console.error("Usage: node scripts/run_engine.mjs <serve|test|build-sidecar|smoke-sidecar> [arguments]");
    process.exit(2);
}

const child = spawn(python, commandArguments, {
  cwd: root,
  env: { ...process.env, LORASUITE_ENGINE_PYTHON: python },
  stdio: "inherit",
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}

child.on("error", (error) => {
  console.error(error.message);
  process.exit(1);
});

child.on("close", (code, signal) => {
  if (signal) process.exit(1);
  process.exit(code ?? 1);
});
