"""WebSocket client — thin adapter that turns WS bytes into Stimuli.

No business logic here. Just: connect, parse, dispatch to samantha.process().
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .server import Samantha

logger = logging.getLogger(__name__)


def ws_listen(samantha: Samantha) -> None:
    """Connect and dispatch. Blocking, auto-reconnects."""
    while True:
        try:
            _connect_and_listen(samantha)
        except Exception:
            logger.warning("WebSocket disconnected, reconnecting in 5s...", exc_info=True)
        time.sleep(5)


def _connect_and_listen(samantha: Samantha) -> None:
    import websocket
    from urllib.parse import urlparse

    parsed = urlparse(samantha.config.app_api_base)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    ws_url = f"{scheme}://{parsed.netloc}/ws/online"

    logger.info("Connecting to %s", ws_url)
    ws = websocket.WebSocket()
    ws.connect(ws_url, header={"Authorization": f"Bearer {samantha.config.jwt_token}"})
    logger.info("WebSocket connected")

    stop_heartbeat = threading.Event()
    threading.Thread(target=_heartbeat, args=(ws, stop_heartbeat), daemon=True).start()

    try:
        while True:
            raw = ws.recv()
            if not raw:
                break
            if raw == "pong":
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if not isinstance(data, dict):
                logger.info("Non-event message: %s", str(data)[:100])
                continue

            stimulus = _parse(samantha, data)
            if stimulus:
                samantha.submit(stimulus)
    finally:
        stop_heartbeat.set()
        ws.close()


def _heartbeat(ws, stop_event: threading.Event) -> None:
    while not stop_event.wait(20):
        try:
            ws.send("ping")
        except Exception:
            break


def _parse(samantha: Samantha, event: dict):
    """Turn a raw WS event into a Stimulus, or None."""
    from .server import Stimulus

    # ── Envelope events: {"type": "...", "data": {...}} ─────────
    if "type" in event:
        etype = event["type"]
        data = event.get("data", {})
        sender = data.get("senderID", 0)

        if sender == samantha.config.user_id:
            return None  # own echo

        if etype == "comment":
            content = data.get("content", "")
            if not content:
                return None
            cid = data.get("commentID", 0)
            rid = data.get("rootID", 0)
            return Stimulus(
                kind="comment", content=content,
                sender_id=sender,
                post_id=data.get("postID", 0),
                comment_id=cid,
                metadata={"root_id": rid if rid else cid},
            )

        if etype == "mention":
            return Stimulus(
                kind="mention",
                content=data.get("content", ""),
                sender_id=sender,
                post_id=data.get("postID", 0),
                comment_id=data.get("commentID", 0),
            )

        if etype == "like":
            logger.info("Like on post %s", data.get("postID"))

        return None

    # ── Legacy bare ChatMessageVO ───────────────────────────────
    if "sessionID" in event:
        content = event.get("content", "")
        session_id = event.get("sessionID")
        sender_id = event.get("senderID")

        if not content or not session_id:
            return None

        if isinstance(sender_id, str):
            sender_id = int(sender_id)
        if isinstance(session_id, str):
            session_id = int(session_id)

        if sender_id == samantha.config.user_id:
            return None

        return Stimulus(
            kind="chat", content=content,
            sender_id=sender_id, session_id=session_id,
        )

    return None
