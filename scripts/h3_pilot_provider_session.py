"""Temporary loopback-only RunPod session. Secrets live only in process memory.

One-shot approved pilot relay. Account credentials are never written to disk.
"""
import json
import secrets
import ssl
import time
import base64
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode

import certifi


def main():
    nonce = secrets.token_urlsafe(32)
    state = {"token": None, "pod_id": None, "stop_epoch": None}
    origin = "http://127.0.0.1:5173"
    run = Path(__file__).resolve().parents[1] / ".lorasuite/qualification/example-subject-h3-cloud-20260907-r1"
    lock = threading.Lock()

    def api(path, method="GET", data=None):
        request = Request("https://rest.runpod.io/v1/" + path, method=method,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Authorization": "Bearer " + state["token"], "User-Agent": "LoraSuite-H3-Pilot/1.0",
                     "Accept": "application/json", "Content-Type": "application/json"})
        with urlopen(request, timeout=30, context=ssl.create_default_context(cafile=certifi.where())) as response:
            body = response.read()
            return json.loads(body) if body else {"http_status": response.status}

    def clean(pod):
        return {k: pod.get(k) for k in ("id", "name", "desiredStatus", "costPerHr", "adjustedCostPerHr",
            "publicIp", "portMappings", "lastStartedAt", "machineId", "gpuCount", "gpuTypeId", "dataCenterId")}

    def watch():
        while state["pod_id"]:
            if time.time() >= state["stop_epoch"]:
                try:
                    api("pods/" + state["pod_id"] + "/stop", "POST", {})
                    (run / "local-stop-receipt.json").write_text(json.dumps({"pod_id": state["pod_id"], "at": time.time()}))
                    return
                except Exception:
                    pass  # Retry stop, never retry create or expose credentials.
            time.sleep(5)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log request bodies, credentials or authorization headers.

        def send_json(self, value, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def do_OPTIONS(self):
            if self.headers.get("Origin") != origin:
                self.send_json({"error": "origin denied"}, 403)
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            if self.path != f"/{nonce}/status":
                return self.send_json({"error": "not found"}, 404)
            self.send_json({"credential_present": bool(state["token"]), "provisioning_enabled": True,
                            "pod_id": state["pod_id"], "stop_epoch": state["stop_epoch"]})

        def do_POST(self):
            if self.headers.get("Origin") not in (None, origin):
                return self.send_json({"error": "origin denied"}, 403)
            if not self.path.startswith(f"/{nonce}/"):
                return self.send_json({"error": "not found"}, 404)
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 65536:
                return self.send_json({"error": "invalid size"}, 400)
            try:
                data = json.loads(self.rfile.read(size))
                if self.path.endswith("/credential"):
                    key = data.get("token", "").strip()
                    if not key:
                        raise ValueError()
                    state["token"] = key
                    return self.send_json({"credential_present": True})
                if self.path.endswith("/pods") and state["token"]:
                    request = Request("https://rest.runpod.io/v1/pods", headers={"Authorization": "Bearer " + state["token"], "User-Agent": "LoraSuite-H3-Pilot/1.0", "Accept": "application/json"})
                    with urlopen(request, timeout=30, context=ssl.create_default_context(cafile=certifi.where())) as response:
                        pods = json.load(response)
                    # Never relay env vars or arbitrary provider payloads.
                    return self.send_json({"authenticated": True, "pods": [{k: p.get(k) for k in ("id", "name", "desiredStatus", "costPerHr")} for p in pods]})
                if self.path.endswith("/pilot-create") and state["token"]:
                    with lock:
                        if (run / "create-attempt.json").exists():
                            return self.send_json({"error": "Single paid attempt already used; no retry"}, 409)
                        ready = json.loads((run / "readiness.json").read_text())
                        if ready.get("qualified_for_one_attempt") is not True:
                            raise ValueError("Not qualified")
                        if api("pods"):
                            raise ValueError("Existing Pods require reconciliation")
                        now = time.time()
                        state["stop_epoch"] = now + 3.75 * 3600
                        guard = Path(__file__).with_name("h3_pilot_watchdog.py").read_bytes()
                        encoded = base64.b64encode(guard).decode()
                        boot = "python -u -c \"import base64;exec(base64.b64decode('" + encoded + "'))\" >/workspace/pilot-watchdog.log 2>&1 & exec /start.sh"
                        payload = {"name": "lorasuite-example-subject-h3-pilot-r1", "cloudType": "SECURE", "computeType": "GPU",
                            "gpuCount": 1, "gpuTypeIds": ["NVIDIA H100 80GB HBM3"], "interruptible": False,
                            "imageName": "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404", "containerDiskInGb": 30,
                            "volumeInGb": 200, "volumeMountPath": "/workspace", "ports": ["22/tcp"],
                            "supportPublicIp": True, "dockerEntrypoint": ["bash", "-lc"], "dockerStartCmd": [boot],
                            "env": {"PUBLIC_KEY": (run / "pilot_ssh.pub").read_text().strip(),
                                    "PILOT_STOP_EPOCH": str(state["stop_epoch"]), "PILOT_TRAIN_EPOCH": str(now + 3.5 * 3600)}}
                        (run / "create-attempt.json").write_text(json.dumps({"at": now, "stop_epoch": state["stop_epoch"], "request": payload}, indent=2))
                        pod = api("pods", "POST", payload)
                        state["pod_id"] = pod["id"]
                        (run / "pod-receipt.json").write_text(json.dumps(clean(pod), indent=2))
                        threading.Thread(target=watch, daemon=True).start()
                        if float(pod.get("costPerHr") or 99) > 4:
                            api("pods/" + state["pod_id"] + "/stop", "POST", {})
                            return self.send_json({"error": "Rate exceeded guard; stopped", "pod_id": state["pod_id"]}, 409)
                        return self.send_json(clean(pod))
                if self.path.endswith("/pilot-get") and state["pod_id"]:
                    return self.send_json(clean(api("pods/" + state["pod_id"])))
                if self.path.endswith("/pilot-stop") and state["pod_id"]:
                    return self.send_json(api("pods/" + state["pod_id"] + "/stop", "POST", {}))
                if self.path.endswith("/pilot-delete") and state["pod_id"]:
                    if not json.loads((run / "retrieval.json").read_text()).get("verified"):
                        raise ValueError("Local retrieval must be verified before deletion")
                    result = api("pods/" + state["pod_id"], "DELETE")
                    state["pod_id"] = None
                    return self.send_json(result)
                if self.path.endswith("/graphql-preflight") and state["token"]:
                    query = 'query { myself { id pods { id name desiredStatus } } gpuTypes(input: {id: "NVIDIA H100 80GB HBM3"}) { id displayName memoryInGb lowestPrice(input: {gpuCount: 1, secureCloud: true}) { stockStatus uninterruptablePrice availableGpuCounts } } }'
                    request = Request("https://api.runpod.io/graphql?" + urlencode({"api_key": state["token"]}), data=json.dumps({"query": query}).encode(), headers={"Content-Type": "application/json", "User-Agent": "LoraSuite-H3-Pilot/1.0"})
                    with urlopen(request, timeout=30, context=ssl.create_default_context(cafile=certifi.where())) as response:
                        result = json.load(response)
                    value = result.get("data") or {}
                    myself = value.get("myself") or {}
                    return self.send_json({"authenticated": bool(myself.get("id")), "graphql_error": bool(result.get("errors")), "pods": myself.get("pods"), "gpu_types": value.get("gpuTypes")})
                return self.send_json({"error": "unsupported action or missing key"}, 400)
            except HTTPError as error:
                body = error.read(8192).decode(errors="replace").lower()
                return self.send_json({"provider_http_status": error.code, "response_is_html": "<html" in body, "cloudflare": "cloudflare" in body, "invalid_key_message": "invalid api key" in body or "invalid token" in body}, 502)
            except Exception:
                return self.send_json({"error": "request failed; credential and response suppressed"}, 400)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 1
    print(json.dumps({"session_url": f"http://127.0.0.1:{server.server_port}/{nonce}", "secret_persistence": False}), flush=True)
    deadline = time.monotonic() + 8 * 3600
    try:
        while time.monotonic() < deadline:
            server.handle_request()
    finally:
        if state["pod_id"]:
            try:
                api("pods/" + state["pod_id"] + "/stop", "POST", {})
            except Exception:
                pass
        state["token"] = None
        server.server_close()


if __name__ == "__main__":
    main()
