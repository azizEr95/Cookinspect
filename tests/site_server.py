"""Local test site for capture.py (Phase 3), on two sites: localhost:8001 (first party) and
127.0.0.1:8002 (third party; Chrome puts its iframes into their own process). Every request
that reaches the server is written to received.jsonl in the given directory: the ground truth
against which tests/check_capture.py compares what capture.py saw.

    venv/bin/python tests/site_server.py OUTPUT_DIR
"""
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent / "site"
LOG_LOCK = threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    log_path = None

    def record(self, body=None):
        with LOG_LOCK, open(self.log_path, "a") as log:
            log.write(json.dumps({"port": self.server.server_port, "method": self.command,
                                  "path": self.path, "body": body}) + "\n")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8", "replace")
        self.record(body)
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/px"):
            self.record()
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass


def serve(host, port, log_path):
    handler = partial(type("LoggingHandler", (Handler,), {"log_path": log_path}), directory=str(SITE_DIR))
    ThreadingHTTPServer((host, port), handler).serve_forever()


if __name__ == "__main__":
    log_path = Path(sys.argv[1]) / "received.jsonl"
    threads = [threading.Thread(target=serve, args=(host, port, log_path), daemon=True)
               for host, port in (("localhost", 8001), ("127.0.0.1", 8002))]
    for thread in threads:
        thread.start()
    print("serving on http://localhost:8001 and http://127.0.0.1:8002", flush=True)
    for thread in threads:
        thread.join()
