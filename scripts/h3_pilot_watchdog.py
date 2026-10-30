"""Pod-local billing watchdog, independent of trainer and local controller.

Uses RunPod's injected pod-scoped key, never the account key. No secret logging.
"""
import json
import os
import time
import subprocess
import sys
from urllib.request import Request, urlopen


def stop_request(pod_id, key):
    if not pod_id.isalnum() or not key:
        raise ValueError("Missing scoped Pod identity")
    return Request(f"https://rest.runpod.io/v1/pods/{pod_id}/stop", data=b"{}",
                   headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                            "User-Agent": "LoraSuite-H3-Pilot/1.0"}, method="POST")


def main():
    deadline = float(os.environ["PILOT_STOP_EPOCH"])
    pod_id = os.environ["RUNPOD_POD_ID"]
    key = os.environ.get("RUNPOD_API_KEY", "")
    if "--stdin-key" in sys.argv:
        # Temporary fallback when the provider-injected scoped key is unusable.
        # Receive over authenticated SSH stdin, keep only in the detached child's RAM.
        key = sys.stdin.readline().strip()
        check = Request(f"https://rest.runpod.io/v1/pods/{pod_id}",
                        headers={"Authorization": "Bearer " + key, "User-Agent": "LoraSuite-H3-Pilot/1.0"})
        try:
            with urlopen(check, timeout=20) as response:
                if response.status != 200:
                    raise ValueError("Authorization check failed")
        except Exception as error:
            print(json.dumps({"watchdog": "authorization failed", "error_type": type(error).__name__,
                              "http_status": getattr(error, "code", None)}), flush=True)
            return
        pid = os.fork()
        if pid:
            print(json.dumps({"watchdog": "detached", "pid": pid, "authenticated": True}), flush=True)
            return
        os.setsid()
        with open(os.devnull) as null, open("/workspace/pilot-watchdog-fallback.log", "a") as log:
            os.dup2(null.fileno(), 0)
            os.dup2(log.fileno(), 1)
            os.dup2(log.fileno(), 2)
    request = stop_request(pod_id, key)
    print(json.dumps({"watchdog": "armed", "pod_id": pod_id, "stop_epoch": deadline}), flush=True)
    while time.time() < deadline:
        time.sleep(min(10, deadline - time.time()))
    while True:
        try:
            with urlopen(request, timeout=15) as response:
                print(json.dumps({"stop_http_status": response.status}), flush=True)
        except Exception:
            # A failed connection can mean the stop succeeded. Never leak URLs or keys.
            print('{"stop_request":"retrying"}', flush=True)
            # Runpodctl carries its own pod-scoped configuration on official Pods.
            try:
                subprocess.run(["runpodctl", "stop", "pod", pod_id], timeout=20,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
        time.sleep(5)


if __name__ == "__main__":
    main()
