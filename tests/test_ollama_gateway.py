import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ollama_gateway", ROOT / "scripts/ollama_gateway.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
TOKEN = "a" * 48


class GatewayTests(unittest.TestCase):
    def test_auth_allowlist_limits_and_private_errors(self):
        calls = []

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                calls.append(self.path)
                body = json.dumps({"models": [{"name": "allowed", "digest": "a" * 64}, {"name": "private"}]}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                calls.append(self.path)
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'secret upstream prompt/credential')

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        proxy = module.gateway(TOKEN, ["allowed"], address=("127.0.0.1", 0),
                               upstream=f"http://127.0.0.1:{upstream.server_port}")
        servers = [upstream, proxy]
        threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
        for thread in threads:
            thread.start()
        try:
            def request(path, payload=None, token=TOKEN, headers=None, method=None):
                data = None if payload is None else json.dumps(payload).encode()
                req = Request(f"http://127.0.0.1:{proxy.server_port}" + path, data=data, method=method,
                              headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", **(headers or {})})
                try:
                    with urlopen(req, timeout=3) as response:
                        return response.status, json.load(response)
                except HTTPError as error:
                    with error:
                        return error.code, json.load(error)

            self.assertEqual(request("/api/tags", token="bad")[0], 401)
            self.assertEqual(request("/api/pull", {"model": "allowed"})[0], 404)
            self.assertEqual(request("/api/tags?token=bad")[0], 404)
            self.assertEqual(request("/api/embed", {"model": "private"})[0], 400)
            self.assertEqual(request("/api/embed", {"model": "allowed", "stream": True})[0], 400)
            self.assertEqual(request("/api/embed", {"model": "allowed"}, headers={"Content-Length": str(module.MAX_REQUEST + 1)})[0], 413)
            self.assertEqual(calls, [])
            status, body = request("/api/tags")
            self.assertEqual(status, 200)
            self.assertEqual([m["name"] for m in body["models"]], ["allowed"])
            status, body = request("/api/generate", {"model": "allowed"})
            self.assertEqual(status, 502)
            self.assertNotIn("secret", json.dumps(body))
        finally:
            for server in servers:
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=2)

    def test_notebook_proxy_matches_tested_source_and_has_no_saved_outputs(self):
        notebook = json.loads((ROOT / "notebooks/colab/04_full_stack_ollama_ngrok.ipynb").read_text())
        source = next("".join(c["source"]) for c in notebook["cells"]
                      if "gateway-source" in c["metadata"].get("tags", []))
        self.assertEqual(source, (ROOT / "scripts/ollama_gateway.py").read_text())
        for i, cell in enumerate(notebook["cells"]):
            if cell["cell_type"] == "code":
                self.assertEqual(cell["outputs"], [])
                self.assertIsNone(cell["execution_count"])
                compile("".join(cell["source"]), f"cell{i}", "exec")


if __name__ == "__main__":
    unittest.main()
