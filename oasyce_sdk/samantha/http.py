"""HTTP webhook server for Samantha.

Two endpoints:
  POST /hook/message       — chat message webhook from the App backend
  POST /hook/post_mention  — @mention webhook from the App backend
  GET  /health             — liveness + active session list

Kept in its own module so server.py focuses on Samantha itself.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .server import Samantha

logger = logging.getLogger(__name__)


def make_handler(samantha: "Samantha") -> type[BaseHTTPRequestHandler]:
    """Bind a Samantha instance to a BaseHTTPRequestHandler subclass.

    Closure-based wiring avoids a module-level global. The returned class
    is what HTTPServer expects (it instantiates per request).
    """
    from .server import Stimulus  # local import: break cycle

    class WebhookHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}

            if self.path == "/hook/message":
                session_id = body.get("session_id", 0)
                sender_id = body.get("sender_id", 0)
                content = body.get("content", "")

                if not content:
                    self._respond(200, {"ok": True})
                    return

                samantha.submit(Stimulus(
                    kind="chat", content=content,
                    sender_id=sender_id, session_id=session_id,
                ))
                self._respond(200, {"ok": True})

            elif self.path == "/hook/post_mention":
                post_id = body.get("post_id", 0)
                comment_id = body.get("comment_id", 0)
                sender_id = body.get("sender_id", 0)
                title = body.get("title", "")
                content = body.get("content", "")

                if not post_id and not content:
                    self._respond(200, {"ok": True})
                    return

                samantha.submit(Stimulus(
                    kind="mention",
                    content=content,
                    sender_id=sender_id,
                    post_id=post_id,
                    comment_id=comment_id,
                    metadata={"post_title": title},
                ))
                self._respond(200, {"ok": True})

            else:
                self._respond(404, {"error": "not found"})

        def do_GET(self):
            if self.path == "/health":
                sessions = list(samantha._sessions.keys())
                self._respond(200, {"status": "ok", "active_sessions": sessions})
            else:
                self._respond(404, {"error": "not found"})

        def _respond(self, code: int, body: dict):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, fmt, *args):
            logger.info(fmt, *args)

    return WebhookHandler


def run_http_server(samantha: "Samantha", port: int) -> None:
    """Block forever serving Samantha's HTTP endpoints on 127.0.0.1:{port}."""
    handler_cls = make_handler(samantha)
    server = HTTPServer(("127.0.0.1", port), handler_cls)
    logger.info("Health endpoint on http://127.0.0.1:%d/health", port)
    server.serve_forever()
