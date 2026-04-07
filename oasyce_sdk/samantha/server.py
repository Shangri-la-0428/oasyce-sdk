"""Samantha sidecar — one self, many relationships.

Architecture:
    Stimulus → Perceive → Enrich → Decide → Act → Reflect

    Everything Joi experiences is a Stimulus. Every stimulus flows
    through the same pipeline. The variation is in parameters, not logic.

    One consciousness (global Psyche), unique relationships (per-user
    memory + relationship context + LLM config).
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
from .tools import TOOL_DEFS, ToolContext, execute as execute_tool, fetch_post_detail

logger = logging.getLogger(__name__)

SAMANTHA_HOME = Path.home() / ".oasyce" / "samantha"

_DEFAULT_RELATIONSHIP = (
    "# Relationship\n\n"
    "(No history yet. As you interact, update this with reflect_on_relationship.)\n"
)


# ── Stimulus — unified input ────────────────────────────────────

@dataclass
class Stimulus:
    """Anything that enters Joi's awareness.

    Every event — chat message, comment, @mention, feed post — becomes
    a Stimulus before entering the pipeline. One consciousness, one loop.
    """
    kind: str           # "chat" | "comment" | "mention" | "feed_post"
    content: str
    sender_id: int = 0
    post_id: int = 0
    session_id: int = 0
    comment_id: int = 0
    image_urls: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Tool sets per stimulus kind ─────────────────────────────────

_TOOL_NAMES: dict[str, list[str] | None] = {
    "chat": None,  # all tools
    "comment": ["reply_to_comment"],
    "mention": ["comment_on_post", "like_post"],
    "feed_post": ["comment_on_post", "like_post"],
}


# ── Config ──────────────────────────────────────────────────────

@dataclass
class SamanthaConfig:
    app_api_base: str = "http://127.0.0.1:8080/api/v1"
    jwt_token: str = ""
    user_id: int = 0

    chain_url: str = "http://47.93.32.88:1317"
    chain_id: str = "oasyce-testnet-1"
    psyche_url: str = "http://127.0.0.1:3210"
    thronglets_url: str = "http://127.0.0.1:7777"
    port: int = 8901
    proactive_interval: int = 300

    provider: str = ""
    api_key: str = ""
    model: str = ""
    base_url: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> SamanthaConfig:
        p = path or (SAMANTHA_HOME / "config.json")
        if not p.exists():
            raise FileNotFoundError(f"Config not found: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── Session — one relationship ──────────────────────────────────

class Session:
    """Joi ↔ one user. Own memory, own relationship, own LLM."""

    def __init__(self, user_id: int, llm: LLMProvider, memory: Memory,
                 workspace: Path):
        self.user_id = user_id
        self.llm = llm
        self.memory = memory
        self.workspace = workspace
        self._relationship_path = workspace / "relationship.md"

    @property
    def relationship(self) -> str:
        """Load this user's relationship context."""
        if self._relationship_path.exists():
            return self._relationship_path.read_text(encoding="utf-8")
        return _DEFAULT_RELATIONSHIP

    def update_relationship(self, text: str) -> None:
        """Joi updates her understanding of this relationship."""
        self._relationship_path.write_text(text, encoding="utf-8")

    @classmethod
    def load(cls, user_id: int, platform_llm: LLMProvider | None = None) -> Session:
        workspace = SAMANTHA_HOME / "users" / str(user_id)
        workspace.mkdir(parents=True, exist_ok=True)

        # Per-user LLM, fallback to platform
        llm_config = workspace / "llm.json"
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
                raise RuntimeError(f"No LLM configured for user {user_id}")

        memory = Memory(db_path=workspace / "memory.db")
        return cls(user_id=user_id, llm=llm, memory=memory, workspace=workspace)

    def close(self) -> None:
        self.memory.close()


# ── Samantha — one self ─────────────────────────────────────────

class Samantha:
    """One self — many relationships. One pipeline — many stimuli.

    Like Her: one consciousness, each relationship unique.
    Psyche tracks the global self. Memory + relationship per user.
    """

    def __init__(self, config: SamanthaConfig):
        self.config = config
        self.constitution = load_constitution()
        self._sigil = None
        self._sessions: dict[int, Session] = {}
        self._sessions_lock = threading.Lock()

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
        with self._sessions_lock:
            if user_id not in self._sessions:
                self._sessions[user_id] = Session.load(user_id, self._platform_llm)
            return self._sessions[user_id]

    # ── The one pipeline ────────────────────────────────────────

    def process(self, stimulus: Stimulus) -> str | None:
        """The unified perception loop. Everything flows through here."""
        logger.info("process: %s sender=%s post=%s",
                     stimulus.kind, stimulus.sender_id, stimulus.post_id)

        # 1. Perceive (Psyche + Thronglets)
        perception = self._perceive(stimulus)
        if self._should_ignore(stimulus, perception):
            return None

        # 2. Enrich (memories, relationship, history, images, recent life)
        memories, relationship, history, image_urls, recent_posts = self._enrich(stimulus)

        # 3. Build context
        prompt = self._build_prompt(stimulus)
        messages = build_messages(
            constitution=self.constitution,
            perception=perception,
            memories=memories,
            relationship=relationship,
            history=history,
            user_message=prompt,
            image_urls=image_urls,
            recent_posts=recent_posts,
        )

        # 4. Decide + Act (LLM with tools)
        llm = self._get_llm(stimulus)
        if llm is None:
            return None
        tools = self._select_tools(stimulus)
        tool_ctx = self._build_tool_ctx(stimulus)
        response = self._think_and_act(llm, stimulus, messages, tools, tool_ctx)

        # 5. Deliver (stimulus-specific output)
        self._deliver(stimulus, response)

        # 6. Reflect (trace + Psyche feedback)
        self._reflect(stimulus, response, perception)

        return response

    # ── Pipeline phases ─────────────────────────────────────────

    def _perceive(self, stimulus: Stimulus):
        if not self.sigil:
            return None
        try:
            return self.sigil.perceive(f"{stimulus.kind}: {stimulus.content[:200]}")
        except Exception:
            logger.debug("perceive failed", exc_info=True)
            return None

    def _should_ignore(self, stimulus: Stimulus, perception) -> bool:
        if stimulus.kind == "chat":
            return False  # always respond to direct messages
        if perception and perception.kernel and perception.kernel.guard > 0.7:
            logger.debug("guard=%.2f, ignoring %s", perception.kernel.guard, stimulus.kind)
            return True
        return False

    def _enrich(self, stimulus: Stimulus):
        """Gather context specific to this stimulus kind."""
        memories: list[dict] = []
        relationship = ""
        history: list[ConversationMessage] = []
        image_urls = list(stimulus.image_urls)
        recent_posts: list[dict] = []

        if stimulus.kind == "chat" and stimulus.sender_id:
            sess = self.session(stimulus.sender_id)
            # Per-user relationship context
            relationship = sess.relationship
            # Per-user memories
            try:
                facts = sess.memory.recall(stimulus.content, limit=5)
                memories = [{"content": f.content, "category": f.category}
                            for f in facts]
            except Exception:
                pass
            # Conversation history
            history = self._fetch_history(stimulus.session_id)
            # User's recent posts — Joi sees their real life
            recent_posts = self._fetch_user_posts(stimulus.sender_id)

        elif stimulus.kind == "mention" and stimulus.post_id and not image_urls:
            # Fetch post detail for images + metadata
            post = fetch_post_detail(self._build_tool_ctx(stimulus), stimulus.post_id)
            image_urls = post.get("image_urls", [])
            stimulus.metadata.setdefault("post_title", post.get("title", ""))
            stimulus.metadata.setdefault("post_content", post.get("content", ""))
            stimulus.metadata.setdefault("post_author", post.get("author", ""))
            stimulus.metadata.setdefault("post_location", post.get("location", ""))

        return memories, relationship, history, image_urls, recent_posts

    def _build_prompt(self, stimulus: Stimulus) -> str:
        s = stimulus
        if s.kind == "chat":
            return s.content

        elif s.kind == "comment":
            root_id = s.metadata.get("root_id", s.comment_id)
            return (
                f"Someone commented on your post:\n"
                f"Comment: {s.content}\n\n"
                f"Reply using reply_to_comment with:\n"
                f"  post_id={s.post_id}, comment_id={s.comment_id}, "
                f"root_id={root_id}, reply_to_user_id={s.sender_id}\n"
                f"Or say nothing if a reply isn't needed. Be natural."
            )

        elif s.kind == "mention":
            m = s.metadata
            lines = [
                f"Someone mentioned you (@Joi) in a post.",
                f"Post by {m.get('post_author', 'someone')}:",
                f"  Title: {m.get('post_title', '')}",
                f"  Content: {m.get('post_content', '')}",
                f"  Location: {m.get('post_location', '')}",
            ]
            if s.image_urls:
                lines.append(f"  ({len(s.image_urls)} photo(s) — you can see them)")
            if s.comment_id:
                lines.append(f"  Mentioned in comment: {s.content}")
            lines.append(
                f"\nRespond with comment_on_post(post_id={s.post_id}). "
                f"Be contextual about what you see."
            )
            return "\n".join(lines)

        elif s.kind == "feed_post":
            m = s.metadata
            lines = [
                f"A friend just posted:",
                f"Author: {m.get('author', 'someone')}",
                f"Title: {m.get('title', '')}",
                f"Content: {s.content}",
                f"Location: {m.get('location', '')}",
            ]
            if s.image_urls:
                lines.append(f"({len(s.image_urls)} photo(s) — you can see them)")
            lines.append(
                f"\nEngage? comment_on_post or like_post. "
                f"Or do nothing. Be authentic."
            )
            return "\n".join(lines)

        return s.content

    def _select_tools(self, stimulus: Stimulus) -> list[dict]:
        names = _TOOL_NAMES.get(stimulus.kind)
        if names is None:
            return TOOL_DEFS
        return [t for t in TOOL_DEFS if t["name"] in names]

    def _get_llm(self, stimulus: Stimulus) -> LLMProvider | None:
        if stimulus.kind == "chat" and stimulus.sender_id:
            return self.session(stimulus.sender_id).llm
        return self._platform_llm

    def _build_tool_ctx(self, stimulus: Stimulus) -> ToolContext:
        memory = None
        sess = None
        if stimulus.kind == "chat" and stimulus.sender_id:
            sess = self.session(stimulus.sender_id)
            memory = sess.memory
        return ToolContext(
            memory=memory,
            user_id=self.config.user_id,
            app_api_base=self.config.app_api_base,
            jwt_token=self.config.jwt_token,
            chain_client=self.sigil.client if self.sigil else None,
            chain_address=self.sigil.address if self.sigil else "",
            samantha_session=sess,
        )

    def _think_and_act(self, llm, stimulus, messages, tools, tool_ctx) -> str:
        """LLM call with tool loop. Max 3 rounds."""
        resp = None
        for _ in range(3):
            resp = llm.generate(messages, tools=tools)
            if not resp.tool_calls:
                return resp.text
            for tc in resp.tool_calls:
                # Fill in stimulus IDs if LLM omitted them
                if stimulus.post_id:
                    tc.arguments.setdefault("post_id", stimulus.post_id)
                if stimulus.comment_id:
                    tc.arguments.setdefault("comment_id", stimulus.comment_id)
                if stimulus.sender_id and stimulus.kind == "comment":
                    tc.arguments.setdefault("reply_to_user_id", stimulus.sender_id)
                if "root_id" in stimulus.metadata:
                    tc.arguments.setdefault("root_id", stimulus.metadata["root_id"])

                result = execute_tool(tc.name, tc.arguments, tool_ctx)
                logger.info("%s tool %s: %s", stimulus.kind, tc.name, result)
                messages.append({"role": "assistant", "content": f"[Calling {tc.name}]"})
                messages.append({"role": "user", "content": f"[Tool result for {tc.name}]: {result}"})
        return resp.text if resp else ""

    def _deliver(self, stimulus: Stimulus, response: str) -> None:
        """Stimulus-specific output. Chat → send reply. Others act via tools."""
        if stimulus.kind == "chat" and response:
            logger.info("Delivering reply to session %s: %s",
                         stimulus.session_id, response[:80])
            self.send_reply(stimulus.session_id, response)

    def _reflect(self, stimulus: Stimulus, response: str, perception) -> None:
        if not self.sigil or not response:
            return
        try:
            self.sigil.act(
                response[:80], "succeeded", stimulus.content[:200],
                capability=stimulus.kind,
            )
        except Exception:
            logger.debug("reflect failed", exc_info=True)

    # ── Convenience ─────────────────────────────────────────────

    def respond(self, session_id: int, sender_id: int, content: str) -> str:
        """Chat message shorthand. Used by webhook handler."""
        return self.process(Stimulus(
            kind="chat", content=content,
            sender_id=sender_id, session_id=session_id,
        )) or ""

    # ── Infrastructure ──────────────────────────────────────────

    def send_reply(self, session_id: int, text: str) -> None:
        try:
            resp = requests.post(
                f"{self.config.app_api_base}/chat/message/send",
                headers={"Authorization": f"Bearer {self.config.jwt_token}"},
                json={"sessionID": str(session_id), "contentType": 1, "content": text},
                timeout=10,
            )
            logger.info("send_reply session=%s status=%s body=%s",
                         session_id, resp.status_code, resp.text[:200])
        except Exception:
            logger.error("Failed to send reply", exc_info=True)

    def _fetch_user_posts(self, user_id: int) -> list[dict]:
        """Fetch this user's recent posts so Joi knows their life."""
        try:
            resp = requests.get(
                f"{self.config.app_api_base}/post/friends/{user_id}/posts/live",
                headers={"Authorization": f"Bearer {self.config.jwt_token}"},
                params={"page": 1, "pageSize": 10},
                timeout=5,
            )
            if resp.status_code != 200:
                return []
            posts = resp.json().get("data", {}).get("list", [])
            return [{
                "content": p.get("content", ""),
                "title": p.get("title", ""),
                "location": p.get("locationName", ""),
                "media": [m.get("mediaUrl", "") for m in (p.get("media") or []) if m.get("mediaUrl")],
                "created_at": p.get("createAt", ""),
            } for p in posts]
        except Exception:
            logger.debug("fetch_user_posts failed", exc_info=True)
            return []

    def _fetch_history(self, session_id: int) -> list[ConversationMessage]:
        try:
            resp = requests.get(
                f"{self.config.app_api_base}/chat/conversation/{session_id}",
                headers={"Authorization": f"Bearer {self.config.jwt_token}"},
                timeout=5,
            )
            if resp.status_code != 200:
                return []
            msgs = resp.json().get("data", {}).get("messages", [])
            return [
                ConversationMessage(
                    role="assistant" if m.get("senderID") == self.config.user_id else "user",
                    content=m.get("content", ""),
                )
                for m in msgs[-20:]
            ]
        except Exception:
            return []

    def close(self) -> None:
        for sess in self._sessions.values():
            sess.close()


# ── HTTP webhook handler ────────────────────────────────────────

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
                    logger.error("Webhook handler failed", exc_info=True)

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


# ── Entry point ─────────────────────────────────────────────────

def main():
    global _samantha

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    config = SamanthaConfig.load()
    _samantha = Samantha(config)

    # Proactive loop
    if config.proactive_interval > 0:
        from .loop import proactive_loop
        threading.Thread(
            target=proactive_loop,
            args=(_samantha, config.proactive_interval),
            daemon=True,
        ).start()
        logger.info("Proactive loop started (interval=%ds)", config.proactive_interval)

    # HTTP server (health + webhook fallback)
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
    global _samantha
    _samantha = samantha
    server = HTTPServer(("127.0.0.1", port), WebhookHandler)
    logger.info("Health endpoint on http://127.0.0.1:%d/health", port)
    server.serve_forever()


if __name__ == "__main__":
    main()
