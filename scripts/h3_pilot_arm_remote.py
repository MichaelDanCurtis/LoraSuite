"""One-shot RAM-only browser-to-SSH watchdog authorization; no key persistence."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import secrets
import subprocess

run = Path(__file__).resolve().parents[1] / ".lorasuite/qualification/example-subject-h3-cloud-20260907-r1"
nonce = secrets.token_urlsafe(32)
origin = "http://127.0.0.1:5173"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST")
        self.end_headers()

    def do_POST(self):
        if self.path != "/" + nonce or self.headers.get("Origin") != origin:
            self.send_error(403)
            return
        value = {"armed": False}
        try:
            size = int(self.headers["Content-Length"])
            if not 0 < size < 8192:
                raise ValueError()
            key = json.loads(self.rfile.read(size))["token"].strip()
            result = subprocess.run(["ssh", "-i", str(run / "pilot_ssh"), "-p", "11660", "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=yes", "-o", 'UserKnownHostsFile="' + str(run / "known_hosts") + '"',
                "root@103.207.149.173", "source /etc/rp_environment; python /workspace/pilot/h3_pilot_watchdog.py --stdin-key"],
                input=key + "\n", text=True, capture_output=True, timeout=40)
            key = None
            try:
                receipt = json.loads(result.stdout.strip())
            except ValueError:
                receipt = {"watchdog": "SSH worker did not return JSON", "error_type": str(result.returncode)}
                print(json.dumps({"code": result.returncode, "stdout_bytes": len(result.stdout),
                    "stderr_flags": {s: s in result.stderr for s in ("KeyError", "RUNPOD_POD_ID", "PILOT_STOP_EPOCH", "Permission denied", "No such file", "SyntaxError", "EOFError", "Traceback")}}), flush=True)
            value = {"armed": receipt.get("authenticated") is True, "pid": receipt.get("pid"),
                     "reason": receipt.get("watchdog"), "error_type": receipt.get("error_type"), "http_status": receipt.get("http_status")}
            (run / "remote-watchdog-receipt.json").write_text(json.dumps(value))
        except Exception as error:
            value["error_type"] = type(error).__name__
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(value).encode())


server = HTTPServer(("127.0.0.1", 0), Handler)
print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/{nonce}"}), flush=True)
server.serve_forever()
