import { spawnSync } from "node:child_process";
import { loadEnv } from "vite";

const executable = process.platform === "win32" ? "npx.cmd" : "npx";
// Use the same Vite configuration for the frontend and the Rust sidecar port.
const environment = { ...loadEnv("production", process.cwd(), "VITE_"), ...process.env };
let config = "src-tauri/tauri.release.conf.json";

if (process.platform === "darwin" && !environment.CI) {
  environment.CI = "true";
}
if (process.platform === "darwin") {
  environment.PATH = `/usr/bin:/bin:/usr/sbin:/sbin:${environment.PATH ?? ""}`;
  const signingIdentity = environment.APPLE_SIGNING_IDENTITY?.trim();
  if (!signingIdentity || signingIdentity === "-") {
    config = "src-tauri/tauri.local-release.conf.json";
  } else {
    const requiredUpdaterSecrets = [
      "TAURI_SIGNING_PRIVATE_KEY",
      "TAURI_SIGNING_PRIVATE_KEY_PASSWORD",
      "LORASUITE_UPDATER_PUBLIC_KEY",
    ].filter((name) => !environment[name]?.trim());
    if (requiredUpdaterSecrets.length > 0) {
      throw new Error(
        `Developer ID builds require signed updater configuration: ${requiredUpdaterSecrets.join(", ")}`,
      );
    }
  }
}

const result = spawnSync(
  executable,
  ["tauri", "build", "--config", config],
  {
    cwd: process.cwd(),
    env: environment,
    stdio: "inherit",
  },
);

if (result.error) {
  throw result.error;
}

process.exit(result.status ?? 1);
