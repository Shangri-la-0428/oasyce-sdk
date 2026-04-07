"""Samantha sidecar — one self, many relationships.

Architecture:
    Samantha = one process, one Psyche, one Sigil, one constitution.
    Session  = one relationship (per user): own memory, own LLM config.

Mode B (current): each user brings their own API key.
Mode C (future):  platform default key + user optional override.

Run with:
    oasyce-samantha
    python -m oasyce_sdk.samantha
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

import requests

from .constitution import load_constitution
from .context import ConversationMessage, build_messages
from .llm import load_provider, LLMProvider
from .memory import Memory
from .tools import TOOL_DEFS, ToolContext, execute as execute_tool

logger = logging.getLogger(__name__)

SAMANTHA_HOME = Path.home() / ".oasyce" / "samantha"


# ── Config ───────────────────────────────────────────────────────

@dataclass
class SamanthaConfig:
    # Samantha's own identity
    app_api_base: str = "http://127.0.0.1:8080/api/v1"
    jwt_token: str = ""
    user_id: int = 0  # Samantha's user ID in the App

    # Infrastructure
    chain_url: str = "http://47.93.32.88:1317"
    chain_id: str = "oasyce-testnet-1"
    psyche_url: str = "http://127.0.0.1:3210"
    thronglets_url: str = "http://127.0.0.1:7777"
    port: int = 8901
    proactive_interval: int = 300

    # Platform LLM (Mode C: optional default for users without their own key)
    provider: str = ""
    api_key: str = ""
    model: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> SamanthaConfig:
        p = path or (SAMANTHA_HOME / "config.json")
        if not p.exists():
            raise FileNotFoundError(
                f"Config not found: {p}\n"
                f"Run: oasyce samantha init"
            )
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── Session (one per user) ───────────────────────────────────────

class Session:
    """One relationship — Samantha ↔ one user.

    Each user gets their own memory and (optionally) their own LLM.
    """

    def __init__(self, user_id: int, llm: LLMProvider, memory: Memory):
        self.user_id = user_id
        self.llm = llm
        self.memory = memory

    @classmethod
    def load(cls, user_id: int, platform_llm: LLMProvider | None = None) -> Session:
        """Load or create a session for a user."""
        user_dir = SAMANTHA_HOME / "users" / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)

        # Per-user LLM: check user config, fallback to platform
        llm_config = user_dir / "llm.json"
        llm: LLMProvider | None = None
        if llm_config.exists():
            try:
                llm = load_provider(llm_config)
            except Exception:
                logger.warning("User %d LLM config invalid, falling back", user_id)

        if llm is None:
            if platform_llm is not None:
                llm = platform_llm
            else:
                raise RuntimeError(
                    f"No LLM configured for user {user_id}. "
                    f"Create {llm_config} with: "
                    '{"provider": "claude", "api_key": "sk-..."}'
                )

        memory = Memory(db_path=user_dir / "memory.db")
        return cls(user_id=user_id, llm=llm, memory=memory)

    def close(self) -> None:
        self.memory.close()


# ── Samantha (one self) ──────────────────────────────────────────

class Samantha:
    """One self — many relationships.

    Like Her: one consciousness, each relationship is unique.
    Psyche tracks the global self-state. Memory is per-user.
    """

    def __init__(self, config: SamanthaConfig):
        self.config = config
        self.constitution = load_constitution()
        self._sigil = None
        self._sessions: dict[int, Session] = {}
        self._sessions_lock = threading.Lock()

        # Platform LLM (Mode C: shared default, None in Mode B)
        self._platform_llm: LLMProvider | None = None
        if config.api_key:
            try:
                self._platform_llm = load_provider(SAMANTHA_HOME / "config.json")
            except Exception:
                pass

    @property
    def sigil(self):
        if self._sigil is None:
            try:
                from ..sigil import SigilManager
                self._sigil = SigilManager(
                    chain_url=self.config.chain_url,
                    chain_id=self.config.chain_id,
                    psyche_url=self.config.psyche_url,
                    thronglets_url=self.config.thronglets_url,
                )
            except Exception:
                logger.warning("SigilManager unavailable", exc_info=True)
        return self._sigil

    def session(self, user_id: int) -> Session:
        """Get or create a session for a user."""
        with self._sessions_lock:
            if user_id not in self._sessions:
                self._sessions[user_id] = Session.load(user_id, self._platform_llm)
            return self._sessions[user_id]

    def respond(self, session_id: int, sender_id: int, content: str) -> str:
        """Process a user message and return Samantha's reply."""
        sess = self.session(sender_id)

        # 1. Perceive (Psyche + Thronglets) — global self, per-user tracking
        perception = None
        if self.sigil:
            try:
                perception = self.sigil.perceive(content)
            except Exception:
                logger.debug("perceive failed", exc_info=True)

        # 2. Recall per-user memories
        memories = []
        try:
            facts = sess.memory.recall(content, limit=5)
            memories = [{"content": f.content, "category": f.category} for f in facts]
        except Exception:
            pass

        # 3. Build conversation history
        history = self._fetch_history(session_id)

        # 4. Build prompt
        messages = build_messages(
            constitution=self.constitution,
            perception=perception,
            memories=memories,
            history=history,
            user_message=content,
        )

        # 5. LLM call with user's provider
        tool_ctx = ToolContext(
            memory=sess.memory,
            user_id=sender_id,
            app_api_base=self.config.app_api_base,
            jwt_token=self.config.jwt_token,
            chain_client=self.sigil.client if self.sigil else None,
            chain_address=self.sigil.address if self.sigil else "",
        )
        response = self._llm_loop(sess.llm, messages, tool_ctx)

        # 6. Act (write trace + Psyche feedback)
        if self.sigil and response:
            try:
                self.sigil.act(
                    response[:80], "succeeded", content[:200],
                    capability="conversation",
                )
            except Exception:
                logger.debug("act failed", exc_info=True)

        return response

    def _llm_loop(
        self, llm: LLMProvider, messages: list[dict], tool_ctx: ToolContext,
    ) -> str:
        """Call LLM, execute tool calls, feed results back. Max 3 rounds."""
        resp = None
        for _ in range(3):
            resp = llm.generate(messages, tools=TOOL_DEFS)
            if not resp.tool_calls:
                return resp.text
            for tc in resp.tool_calls:
                result = execute_tool(tc.name, tc.arguments, tool_ctx)
                messages.append({"role": "assistant", "content": f"[Calling {tc.name}]"})
                messages.append({"role": "user", "content": f"[Tool result for {tc.name}]: {result}"})
        return resp.text if resp else ""

    def _fetch_history(self, session_id: int) -> list[ConversationMessage]:
        """Fetch recent messages from Go backend."""
        try:
            resp = requests.get(
                f"{self.config.app_api_base}/chat/conversation/{session_id}",
                headers={"Authorization": f"Bearer {self.config.jwt_token}"},
                timeout=5,
            )
            if resp.status_code != 200:
                return []
            data = resp.json().get("data", {})
            msgs = data.get("messages", [])
            return [
                ConversationMessage(
                    role="assistant" if m.get("senderID") == self.config.user_id else "user",
                    content=m.get("content", ""),
                )
                for m in msgs[-20:]
            ]
        except Exception:
            return []

    def send_reply(self, session_id: int, text: str) -> None:
        """Send a message through the Go backend as Samantha."""
        try:
            requests.post(
                f"{self.config.app_api_base}/chat/message/send",
                headers={"Authorization": f"Bearer {self.config.jwt_token}"},
                json={"sessionID": session_id, "contentType": 1, "content": text},
                timeout=10,
            )
        except Exception:
            logger.error("Failed to send reply", exc_info=True)

    def close(self) -> None:
        for sess in self._sessions.values():
            sess.close()


# ── HTTP webhook handler ─────────────────────────────────────────

_samantha: Samantha | None = None


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/hook/message":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}

            session_id = body.get("session_id", 0)
            sender_id = body.get("sender_id", 0)
            content = body.get("content", "")

            if not content or not _samantha:
                self._respond(200, {"ok": True})
                return

            def _handle():
                try:
                    reply = _samantha.respond(session_id, sender_id, content)
                    if reply:
                        _samantha.send_reply(session_id, reply)
                except Exception:
                    logger.error("Failed to handle message", exc_info=True)

            threading.Thread(target=_handle, daemon=True).start()
            self._respond(200, {"ok": True})
        else:
            self._respond(404, {"error": "not found"})

    def do_GET(self):
        if self.path == "/health":
            sessions = list(_samantha._sessions.keys()) if _samantha else []
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


# ── Entry point ──────────────────────────────────────────────────

def main():
    global _samantha

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    config = SamanthaConfig.load()
    _samantha = Samantha(config)

    # Proactive loop for self-initiated actions (browsing feed, posting)
    if config.proactive_interval > 0:
        from .loop import proactive_loop
        threading.Thread(
            target=proactive_loop,
            args=(_samantha, config.proactive_interval),
            daemon=True,
        ).start()
        logger.info("Proactive loop started (interval=%ds)", config.proactive_interval)

    # HTTP webhook server (legacy / fallback when WS unavailable)
    threading.Thread(
        target=_run_http_server,
        args=(_samantha, config.port),
        daemon=True,
    ).start()

    # WebSocket client — primary event channel (blocks)
    from .ws_client import ws_listen
    logger.info("Samantha starting — connecting to App WebSocket...")
    try:
        ws_listen(_samantha)
    except KeyboardInterrupt:
        pass
    finally:
        _samantha.close()


def _run_http_server(samantha: Samantha, port: int) -> None:
    """Run HTTP server in background for health checks and webhook fallback."""
    global _samantha
    _samantha = samantha
    server = HTTPServer(("127.0.0.1", port), WebhookHandler)
    logger.info("Health endpoint on http://127.0.0.1:%d/health", port)
    server.serve_forever()


if __name__ == "__main__":
    main()
