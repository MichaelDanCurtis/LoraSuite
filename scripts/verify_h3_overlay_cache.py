"""Verify reuse with a previously captured real stack, without launching a render."""
import argparse
import json
from pathlib import Path
import time
from lorasuite_engine.h3_lora import cached_overlay

parser = argparse.ArgumentParser()
parser.add_argument("--vault", type=Path, required=True)
parser.add_argument("--run-id", required=True)
parser.add_argument("--report", type=Path, required=True)
args = parser.parse_args()
if args.report.exists():
    raise SystemExit("Use a new report path; preserve earlier evidence")
data = json.loads((args.vault / "h3_native_runs.json").read_text())["runs"]
run = next(r for r in (data.values() if isinstance(data, dict) else data) if r["id"] == args.run_id)
results = []
for attempt in range(2):
    started = time.monotonic()
    result = cached_overlay(run["lora_adapters"], Path(run["config"]["model_dir"]),
                            "Ref2VA" if run.get("snapshot_id") else "FL2VA",
                            args.vault / "h3_overlay_cache",
                            lambda message: print(message, flush=True))
    results.append({"elapsed_seconds": time.monotonic() - started, **result})
assert results[1]["cache_hit"]
assert results[0]["path"] == results[1]["path"]
assert results[0]["sha256"] == results[1]["sha256"] == run["lora_overlay"]["sha256"]
args.report.parent.mkdir(parents=True, exist_ok=True)
args.report.write_text(json.dumps({"run_id": args.run_id, "attempts": results,
                                  "matches_previous_render_overlay": True}, indent=2) + "\n")
print(json.dumps({"seconds": [r["elapsed_seconds"] for r in results], "bytes": results[0]["bytes"], "verified": True}))
