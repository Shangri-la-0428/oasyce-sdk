"""Proactive loop — Joi scans her world for things to notice.

No business logic here. Just: poll feeds → create Stimuli → process().
The perception/decision/action pipeline lives in Samantha.process().
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .server import Samantha

logger = logging.getLogger(__name__)


def proactive_loop(samantha: Samantha, interval: int = 300) -> None:
    """Scan feeds periodically. Blocking."""
    seen_posts: set[int] = set()
    seen_comments: set[int] = set()

    while True:
        try:
            _scan_feed(samantha, seen_posts)
            _scan_own_comments(samantha, seen_comments)
        except Exception:
            logger.debug("Proactive loop error", exc_info=True)
        time.sleep(interval)


def _scan_feed(samantha: Samantha, seen: set[int]) -> None:
    """Turn new friend posts into Stimuli."""
    from .server import Stimulus
    from .tools import ToolContext

    ctx = _ctx(samantha)
    if not ctx:
        return

    try:
        resp = ctx.app_request("GET", "/post/friends/feed/overview?pageSize=5&page=1")
        posts = resp.get("data", {}).get("list", [])
    except Exception:
        return

    for post in posts:
        pid = post.get("id")
        if not pid or pid in seen:
            continue
        seen.add(pid)

        media = post.get("media") or []
        images = [m["mediaUrl"] for m in media if m.get("mediaUrl")]

        samantha.process(Stimulus(
            kind="feed_post",
            content=post.get("content", "")[:200],
            post_id=pid,
            image_urls=images,
            metadata={
                "author": post.get("user", {}).get("name", ""),
                "title": post.get("title", ""),
                "location": post.get("locationName", ""),
            },
        ))

    if len(seen) > 1000:
        seen.clear()


def _scan_own_comments(samantha: Samantha, seen: set[int]) -> None:
    """Turn new comments on Joi's posts into Stimuli."""
    from .server import Stimulus
    from .tools import ToolContext

    ctx = _ctx(samantha)
    if not ctx:
        return

    try:
        own = ctx.app_request("POST", "/post/own/search", json={"page": 1, "pageSize": 3})
        posts = (own.get("data") or {}).get("items") or (own.get("data") or {}).get("list") or []
    except Exception:
        return

    for post in posts:
        pid = post.get("id")
        if not pid:
            continue

        try:
            cr = ctx.app_request("GET", f"/post/{pid}/root-comments?page=1&pageSize=10")
            comments = ((cr.get("data") or {}).get("items")) or []
        except Exception:
            continue

        for c in comments:
            cid = c.get("id")
            uid = c.get("user", {}).get("id")

            if not cid or cid in seen or uid == samantha.config.user_id:
                continue
            seen.add(cid)

            samantha.process(Stimulus(
                kind="comment",
                content=c.get("content", ""),
                sender_id=uid,
                post_id=pid,
                comment_id=cid,
                metadata={"root_id": cid},  # root comments: root_id = self
            ))

    if len(seen) > 5000:
        seen.clear()


def _ctx(samantha: Samantha):
    """Lightweight ToolContext for API calls."""
    from .tools import ToolContext

    if samantha._platform_llm is None:
        return None
    return ToolContext(
        memory=None,  # type: ignore[arg-type]
        user_id=samantha.config.user_id,
        app_api_base=samantha.config.app_api_base,
        jwt_token=samantha.config.jwt_token,
    )
