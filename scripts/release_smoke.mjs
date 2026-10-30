import { spawnSync } from "node:child_process";

const checks = [
  {
    label: "Guided project, jobs, and target handoffs",
    command: "npm",
    args: ["test", "--", "--run", "src/components/ProjectHome.test.tsx", "src/components/JobCenter.test.tsx", "src/components/GuidedExperience.test.tsx", "src/components/VideoDatasetCompiler.test.tsx", "src/App.test.tsx", "src/lib/api.test.ts"],
  },
  {
    label: "Image, video, voice, Living Identity, and workflow engine contracts",
    command: "node",
    args: ["scripts/run_engine.mjs", "test"],
  },
  {
    label: "Production web build",
    command: "npm",
    args: ["run", "build"],
  },
];

for (const check of checks) {
  process.stdout.write(`\n[release smoke] ${check.label}\n`);
  const result = spawnSync(check.command, check.args, { cwd: process.cwd(), stdio: "inherit" });
  if (result.error) {
    process.stderr.write(`${result.error.message}\n`);
    process.exit(1);
  }
  if (result.status !== 0) process.exit(result.status ?? 1);
}

process.stdout.write("\n[release smoke] All Guided and Advanced workflow checks passed.\n");
