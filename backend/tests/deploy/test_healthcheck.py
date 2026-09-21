"""The image healthcheck probes the configured listener and rejects unready JSON."""
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


@pytest.mark.parametrize("body,success", [({"ready": True}, True), ({"ready": False}, False), ({"status": "ok"}, False)])
def test_image_healthcheck(body, success):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/api/ready"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(["python", str(Path(__file__).resolve().parents[3] / "deploy/healthcheck.py")],
                                env={**os.environ, "ONESHELF_HOST": "0.0.0.0", "ONESHELF_PORT": str(server.server_port)},
                                capture_output=True, timeout=10)
        assert (result.returncode == 0) == success
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
