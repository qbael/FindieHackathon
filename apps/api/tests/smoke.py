"""Exercise the built API's dependency status without PostgreSQL or model downloads."""

import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


class AiHandler(BaseHTTPRequestHandler):
    ready = False
    saw_token = False

    def do_GET(self):
        assert self.path == "/health/ready"
        AiHandler.saw_token = self.headers.get("X-Service-Token") == "smoke-token"
        self.send_response(200 if self.ready and self.saw_token else 503)
        self.end_headers()

    def log_message(self, *args):
        pass


def get(path):
    try:
        response = urlopen(f"http://127.0.0.1:{api_port}{path}", timeout=10)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


api_directory = Path(__file__).resolve().parents[1]
with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    api_port = listener.getsockname()[1]

with ThreadingHTTPServer(("127.0.0.1", 0), AiHandler) as ai, tempfile.TemporaryFile() as logs:
    threading.Thread(target=ai.serve_forever, daemon=True).start()
    environment = os.environ | {
        "ASPNETCORE_ENVIRONMENT": "Production",
        "ConnectionStrings__Database": "Host=127.0.0.1;Port=1;Database=smoke;Username=smoke;Password=not-a-real-password;Timeout=1;Command Timeout=1",
        "Ai__BaseUrl": f"http://127.0.0.1:{ai.server_port}",
        "Ai__ServiceToken": "smoke-token",
        "Ai__TimeoutSeconds": "1",
    }
    process = subprocess.Popen(
        ["dotnet", "run", "--no-build", "--no-launch-profile", "--urls", f"http://127.0.0.1:{api_port}"],
        cwd=api_directory, env=environment, stdout=logs, stderr=logs,
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                assert get("/health/live") == (200, {"status": "ok", "stage": "scaffold"})
                break
            except URLError:
                if process.poll() is not None or time.monotonic() >= deadline:
                    logs.seek(0)
                    raise AssertionError(logs.read().decode())
                time.sleep(0.1)
        assert get("/health/ready") == (503, {"status": "not_ready", "database": "unavailable"})
        code, status = get("/api/system/status")
        assert code == 200 and status == {
            "name": "Findie API", "stage": "scaffold", "database": "unavailable", "ai": "unavailable",
            "features": {"business": False, "authentication": False, "storage": False},
        }
        assert AiHandler.saw_token
        AiHandler.ready = True
        assert get("/api/system/status")[1]["ai"] == "ready"
        ai.shutdown()
        ai.server_close()
        assert get("/api/system/status")[1]["ai"] == "unavailable"
        print("PASS: liveness, database failure, AI readiness/failure, token header, scaffold flags")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
