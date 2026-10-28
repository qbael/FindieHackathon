"""Small authenticated, inference-only gateway for an interactive Ollama session."""

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler


MAX_REQUEST = 16 * 1024 * 1024
MAX_RESPONSE = 2 * 1024 * 1024


def gateway(token, models, *, address=("127.0.0.1", 11435), upstream="http://127.0.0.1:11434"):
    if not isinstance(token, str) or len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
        raise ValueError("Use an ASCII token of at least 32 characters without whitespace.")
    if not models or any(not isinstance(m, str) or not m for m in models):
        raise ValueError("Explicit model names are required.")
    if not upstream.startswith("http://127.0.0.1:"):
        raise ValueError("The upstream must be the private loopback Ollama server.")
    allowed_models = frozenset(models)
    capacity = threading.BoundedSemaphore(1)
    opener = build_opener(ProxyHandler({}))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Request headers/bodies and model output must never enter logs.

        def respond(self, status, payload):
            body = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def handle_api(self):
            self.connection.settimeout(10)
            supplied = self.headers.get("Authorization", "").encode("utf-8")
            if not hmac.compare_digest(supplied, ("Bearer " + token).encode("ascii")):
                return self.respond(401, {"error": "unauthorized"})
            if (self.command, self.path) not in {("GET", "/api/tags"), ("POST", "/api/show"),
                                               ("POST", "/api/embed"), ("POST", "/api/generate")}:
                return self.respond(404, {"error": "unsupported_route"})
            if self.headers.get("Transfer-Encoding"):
                return self.respond(400, {"error": "content_length_required"})
            body = None
            if self.command == "POST":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= MAX_REQUEST:
                        return self.respond(413, {"error": "request_too_large"})
                    if self.headers.get_content_type() != "application/json":
                        return self.respond(415, {"error": "json_required"})
                    body = self.rfile.read(length)
                    if len(body) != length:
                        raise ValueError()
                    payload = json.loads(body)
                    if not isinstance(payload, dict) or payload.get("model") not in allowed_models:
                        return self.respond(400, {"error": "model_not_allowed"})
                    if payload.get("stream", False) is not False:
                        return self.respond(400, {"error": "streaming_not_supported"})
                except (ValueError, TypeError, TimeoutError, OSError):
                    return self.respond(400, {"error": "invalid_request"})
            inference = self.path in {"/api/embed", "/api/generate"}
            if inference and not capacity.acquire(blocking=False):
                return self.respond(429, {"error": "model_busy"})
            try:
                request = Request(upstream + self.path, data=body,
                                  headers={"Content-Type": "application/json"}, method=self.command)
                with opener.open(request, timeout=25) as response:
                    data = response.read(MAX_RESPONSE + 1)
                    if len(data) > MAX_RESPONSE:
                        raise ValueError()
                    result = json.loads(data)
                if self.path == "/api/tags":
                    result = {"models": [m for m in result["models"] if m.get("name") in allowed_models]}
                return self.respond(200, result)
            except HTTPError as error:
                error.close()
                return self.respond(502, {"error": "ollama_unavailable"})
            except (URLError, OSError, ValueError, KeyError, TypeError):
                return self.respond(502, {"error": "ollama_unavailable"})
            finally:
                if inference:
                    capacity.release()

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = handle_api

    return ThreadingHTTPServer(address, Handler)
