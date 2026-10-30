"""Run the single pilot process, persist outcome, and enforce its work deadline."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time

root = Path("/workspace/pilot")
deadline = float(os.environ["PILOT_TRAIN_EPOCH"])
env = {k: v for k, v in os.environ.items() if "KEY" not in k and "TOKEN" not in k and "PASSWORD" not in k}
start = time.time()
reason = "process exited"
with (root / "pilot.log").open("x") as log:
    child = subprocess.Popen(["bash", str(root / "h3_pilot_bootstrap.sh")], env=env,
                             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        child.wait(timeout=max(1, deadline - time.time()))
    except subprocess.TimeoutExpired:
        reason = "work deadline reached; saving/retrieval reserve begins"
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
(root / "run-result.json").write_text(json.dumps({"exit_code": child.returncode,
    "reason": reason, "elapsed_seconds": time.time() - start, "finished_at": time.time()}, indent=2))
(root / "exit-code").write_text(str(child.returncode))
