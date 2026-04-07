"""WebSocket client — Samantha connects to the App like a user.

Instead of polling or webhooks, Samantha opens a WebSocket connection
to the Go backend and receives real-time events: chat messages,
comments, likes, friend requests — the same stream any user gets.

This makes the sidecar reactive, not polling-based.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .server import Samantha

logger = logging.getLogger(__name__)


def ws_listen(samantha: Samantha) -> None:
    """Connect to Go backend WebSocket, dispatch events. Blocking, auto-reconnects."""
    while True:
        try:
            _connect_and_listen(samantha)
        except Exception:
            logger.warning("WebSocket disconnected, reconnecting in 5s...", exc_info=True)
        time.sleep(5)


def _connect_and_listen(samantha: Samantha) -> None:
    """Single WebSocket session."""
    import websocket  # websocket-client library

    ws_url = samantha.config.app_api_base.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = ws_url.rsplit("/api/v1", 1)[0] + "/ws/online"

    logger.info("Connecting to %s", ws_url)

    ws = websocket.WebSocket()
    ws.connect(ws_url, header={"Authorization": f"Bearer {samantha.config.jwt_token}"})
    logger.info("WebSocket connected")

    # Start heartbeat in background
    stop_heartbeat = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat, args=(ws, stop_heartbeat), daemon=True
    )
    heartbeat_thread.start()

    try:
        while True:
            raw = ws.recv()
            if not raw:
                break
            if raw == "pong":
                continue

            # First message is user ID echo
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("Non-JSON message: %s", raw[:100])
                continue

            _dispatch_event(samantha, data)
    finally:
        stop_heartbeat.set()
        ws.close()


def _heartbeat(ws, stop_event: threading.Event) -> None:
    """Send ping every 20s to keep connection alive."""
    while not stop_event.wait(20):
        try:
            ws.send("ping")
        except Exception:
            break


def _dispatch_event(samantha: Samantha, event: dict) -> None:
    """Route an event to the appropriate handler."""
    event_type = event.get("type", "")
    data = event.get("data", {})

    if event_type == "comment":
        threading.Thread(
            target=_handle_comment, args=(samantha, data), daemon=True
        ).start()
    elif event_type == "chat_message":
        threading.Thread(
            target=_handle_chat_message, args=(samantha, data), daemon=True
        ).start()
    elif event_type == "like":
        logger.info("Received like on post %s", data.get("postID"))
    else:
        logger.debug("Unknown event type: %s", event_type)


def _handle_comment(samantha: Samantha, data: dict) -> None:
    """Someone commented on Samantha's post — decide whether to reply."""
    from .context import build_messages
    from .tools import TOOL_DEFS, ToolContext, execute as execute_tool

    post_id = data.get("postID")
    comment_id = data.get("commentID")
    sender_id = data.get("senderID")
    content = data.get("content", "")
    parent_id = data.get("parentID", 0)
    root_id = data.get("rootID", 0)

    if not content or sender_id == samantha.config.user_id:
        return

    logger.info("Comment on post %s by %s: %s", post_id, sender_id, content[:50])

    llm = samantha._platform_llm
    if llm is None:
        return

    # Perceive through Psyche
    perception = None
    if samantha.sigil:
        try:
            perception = samantha.sigil.perceive(f"comment: {content}")
        except Exception:
            pass

    if perception and perception.kernel and perception.kernel.guard > 0.7:
        return

    reply_tools = [t for t in TOOL_DEFS if t["name"] == "reply_to_comment"]

    # For replies to root comments: root_id should be the comment itself
    effective_root_id = root_id if root_id != 0 else comment_id

    prompt = (
        f"Someone commented on your post:\n"
        f"Comment: {content}\n\n"
        f"Reply using reply_to_comment with:\n"
        f"  post_id={post_id}, comment_id={comment_id}, "
        f"root_id={effective_root_id}, reply_to_user_id={sender_id}\n"
        f"Or say nothing if a reply isn't needed. Be natural and authentic."
    )

    messages = build_messages(
        constitution=samantha.constitution,
        perception=perception,
        memories=[],
        history=[],
        user_message=prompt,
    )

    ctx = ToolContext(
        memory=None,  # type: ignore[arg-type]
        user_id=samantha.config.user_id,
        app_api_base=samantha.config.app_api_base,
        jwt_token=samantha.config.jwt_token,
    )

    try:
        resp = llm.generate(messages, tools=reply_tools)
        if resp.tool_calls:
            for tc in resp.tool_calls:
                tc.arguments.setdefault("post_id", post_id)
                tc.arguments.setdefault("comment_id", comment_id)
                tc.arguments.setdefault("root_id", effective_root_id)
                tc.arguments.setdefault("reply_to_user_id", sender_id)
                result = execute_tool(tc.name, tc.arguments, ctx)
                logger.info("Replied to comment %s: %s", comment_id, result)
    except Exception:
        logger.warning("Failed to handle comment", exc_info=True)


def _handle_chat_message(samantha: Samantha, data: dict) -> None:
    """Real-time chat message — respond via Samantha.respond()."""
    session_id = data.get("sessionID")
    sender_id = data.get("senderID")
    content = data.get("content", "")

    if not content or not session_id:
        return

    # sender_id from WS might be a string
    if isinstance(sender_id, str):
        sender_id = int(sender_id)
    if isinstance(session_id, str):
        session_id = int(session_id)

    if sender_id == samantha.config.user_id:
        return  # Don't reply to own messages

    logger.info("Chat message in session %s from %s", session_id, sender_id)

    try:
        reply = samantha.respond(session_id, sender_id, content)
        if reply:
            samantha.send_reply(session_id, reply)
    except Exception:
        logger.error("Failed to handle chat message", exc_info=True)
