"""Serves spikes/cdp/site on two origins (localhost:8001 and 127.0.0.1:8002 are different sites,
so Chrome puts the iframe into its own process). Accepts POST and logs every received body,
which is the ground truth for the spike."""
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent / "site"


class Handler(SimpleHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", "replace")
        print(f"[server {self.server.server_port}] POST {self.path} {body}", flush=True)
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/px"):
            print(f"[server {self.server.server_port}] GET {self.path}", flush=True)
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()

    def log_message(self, *args):
        pass


def serve(host, port):
    handler = partial(Handler, directory=str(SITE_DIR))
    ThreadingHTTPServer((host, port), handler).serve_forever()


if __name__ == "__main__":
    threads = [threading.Thread(target=serve, args=("localhost", 8001), daemon=True),
               threading.Thread(target=serve, args=("127.0.0.1", 8002), daemon=True)]
    for t in threads:
        t.start()
    print("serving on http://localhost:8001 and http://127.0.0.1:8002", flush=True)
    for t in threads:
        t.join()
