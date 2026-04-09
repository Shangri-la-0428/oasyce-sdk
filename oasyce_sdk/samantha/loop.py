"""Proactive loop — Joi scans her world and maintains her memory.

Two cycles:
  Fast (every interval): poll feeds → create Stimuli → process()
  Slow (every 10 intervals): memory maintenance → prune + dream
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .server import Samantha

logger = logging.getLogger(__name__)


def proactive_loop(samantha: Samantha, interval: int = 300) -> None:
    """Scan feeds and maintain memory. Blocking."""
    seen_posts: set[int] = set()
    seen_comments: set[int] = set()
    cycle = 0

    while True:
        try:
            _scan_feed(samantha, seen_posts)
            _scan_own_comments(samantha, seen_comments)
        except Exception:
            logger.debug("Proactive loop error", exc_info=True)

        cycle += 1
        if cycle % 10 == 0:
            try:
                _memory_maintenance(samantha)
            except Exception:
                logger.debug("Memory maintenance error", exc_info=True)

        time.sleep(interval)


def _memory_maintenance(samantha: Samantha) -> None:
    """Prune stale facts + Dream consolidation across all active sessions."""
    for user_id, sess in list(samantha._sessions.items()):
        try:
            pruned = sess.memory.prune(max_age_days=90, min_access=0)
            if pruned:
                logger.info("User %d: pruned %d stale memories", user_id, pruned)
        except Exception:
            logger.debug("Prune failed for user %d", user_id, exc_info=True)

        try:
            samantha.dream(user_id, sess)
        except Exception:
            logger.debug("Dream failed for user %d", user_id, exc_info=True)


def _scan_feed(samantha: Samantha, seen: set[int]) -> None:
    """Turn new friend posts into Stimuli."""
    from .app_client import extract_media_urls
    from .server import Stimulus

    if not samantha._registry.slot_names:
        return

    try:
        data = samantha.app.fetch_friends_feed(limit=5)
        groups = data.get("data", {}).get("postGroups", [])
    except Exception:
        return

    for group in groups:
        author = group.get("user", {}).get("name", "")
        for post in group.get("items", []):
            pid = post.get("id")
            if not pid or pid in seen:
                continue
            seen.add(pid)

            samantha.process(Stimulus(
                kind="feed_post",
                content=post.get("content", "")[:200],
                post_id=pid,
                image_urls=extract_media_urls(post.get("media")),
                metadata={
                    "author": author,
                    "title": post.get("title", ""),
                    "location": post.get("locationName", ""),
                },
            ))

    if len(seen) > 1000:
        seen.clear()


def _scan_own_comments(samantha: Samantha, seen: set[int]) -> None:
    """Turn new comments on Joi's posts into Stimuli."""
    from .server import Stimulus

    if not samantha._registry.slot_names:
        return

    try:
        posts = samantha.app.fetch_own_posts(limit=3)
    except Exception:
        return

    for post in posts:
        pid = post.get("id")
        if not pid:
            continue

        try:
            comments = samantha.app.fetch_post_comments(pid)
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
                metadata={"root_id": cid},
            ))

    if len(seen) > 5000:
        seen.clear()
