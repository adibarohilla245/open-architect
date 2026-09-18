# web/server.py
"""
Minimal SSE server using only the Python stdlib — no FastAPI/uvicorn needed.
The agent runs in its own threads; this server just streams bus events to the browser.
"""
import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.lib.events import bus


# Bridge: sync bus → per-client queue
_client_queues: list[queue.Queue] = []
_lock = threading.Lock()


def _on_event(event: dict) -> None:
    with _lock:
        for q in list(_client_queues):
            q.put(event)


bus.subscribe(_on_event)

STATIC_DIR = Path(__file__).parent / "static"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        # silence default per-request logging
        return

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._serve_file("index.html", "text/html; charset=utf-8")
        elif self.path == "/events":
            self._serve_sse()
        elif self.path == "/health":
            self._send_text("ok")
        else:
            self.send_error(404)

    def _send_text(self, text: str):
        data = text.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_file(self, name: str, content_type: str):
        p = STATIC_DIR / name
        if not p.exists():
            self.send_error(404)
            return
        data = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        q: queue.Queue = queue.Queue()
        with _lock:
            _client_queues.append(q)

        try:
            # 1. replay history so late joiners see what happened
            for event in bus.snapshot():
                self._send_event(event)
            # 2. live stream
            while True:
                try:
                    event = q.get(timeout=25)
                    self._send_event(event)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with _lock:
                if q in _client_queues:
                    _client_queues.remove(q)

    def _send_event(self, event: dict) -> None:
        payload = f"data: {json.dumps(event)}\n\n".encode("utf-8")
        self.wfile.write(payload)
        self.wfile.flush()


def start_server(port: int = 8000) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"[web] Live dashboard → http://localhost:{port}")
    server.serve_forever()


def start_server_in_background(port: int = 8000) -> threading.Thread:
    t = threading.Thread(target=start_server, args=(port,), daemon=True)
    t.start()
    return t