"""Continuously retrieve pilot evidence and stop compute when its process exits.

No account key handling. Talks to the in-memory local pilot controller.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--relay", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    received = run / "received"
    received.mkdir(exist_ok=True)
    ssh = ["ssh", "-i", str(run / "pilot_ssh"), "-p", args.port,
           "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=yes",
           "-o", 'UserKnownHostsFile="' + str(run / "known_hosts") + '"', "root@" + args.host]
    transport = subprocess.list2cmdline(ssh[:-1])
    # list2cmdline is Windows-style: rsync's shell parsing needs POSIX quoting.
    import shlex
    transport = shlex.join(ssh[:-1])

    def relay(action):
        with urlopen(Request(args.relay + "/" + action, data=b"{}", headers={"Content-Type": "application/json"}), timeout=40) as response:
            return json.load(response)

    def remote(command):
        return subprocess.run(ssh + [command], capture_output=True, text=True, timeout=30)

    while True:
        try:
            status = remote("test -f /workspace/pilot/exit-code && cat /workspace/pilot/exit-code || true")
            # Include only evidence/checkpoints, never base weights, caches, credentials or photos.
            sync = subprocess.run(["rsync", "-az", "--timeout=30", "-e", transport,
                "--include=*/", "--include=*.log", "--include=*.json", "--include=*.csv",
                "--include=*.safetensors", "--exclude=package/images/***", "--exclude=package/cache/***",
                "--exclude=*", "root@" + args.host + ":/workspace/pilot/", str(received) + "/"],
                capture_output=True, text=True, timeout=180)
            if sync.returncode:
                print(json.dumps({"collection": "transfer retry", "code": sync.returncode}), flush=True)
                time.sleep(20)
                continue
            markers = sorted(received.glob("package/adapter/*.complete.json"))
            verified = []
            for marker in markers:
                item = json.loads(marker.read_text())
                path = marker.parent / item["file"]
                if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]:
                    verified.append(item)
            if status.returncode == 0 and status.stdout.strip():
                # All final marker files have reached local storage; no partially copied adapters pass.
                report = {"verified": len(verified) == len(markers), "checkpoint_count": len(verified),
                          "checkpoints": verified, "exit_code": status.stdout.strip(), "collected_at": time.time()}
                (run / "retrieval.json").write_text(json.dumps(report, indent=2))
                relay("pilot-stop")
                print(json.dumps({"training_exit": status.stdout.strip(), "checkpoints": len(verified), "compute_stop_requested": True}), flush=True)
                return
            print(json.dumps({"collection": "ok", "verified_checkpoints": len(verified)}), flush=True)
        except Exception as error:
            print(json.dumps({"collection": "retry", "error_type": type(error).__name__}), flush=True)
        time.sleep(30)


if __name__ == "__main__":
    main()
