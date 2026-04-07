"""Proactive feed watcher — Samantha notices new posts and may engage.

The engagement decision is driven by Psyche:
- High boundary → stays quiet
- High resonance → more likely to comment/like

This is NOT a rule engine. The LLM decides what to do based on Psyche state
and the post content. Samantha's social behavior emerges.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .server import Samantha

logger = logging.getLogger(__name__)


def proactive_loop(samantha: Samantha, interval: int = 300) -> None:
    """Poll friends feed and engage when Psyche says so. Blocking."""
    seen_post_ids: set[int] = set()

    while True:
        try:
            _check_feed(samantha, seen_post_ids)
        except Exception:
            logger.debug("Proactive loop error", exc_info=True)

        time.sleep(interval)


def _check_feed(samantha: Samantha, seen: set[int]) -> None:
    """Check friends feed for new posts, engage if appropriate."""
    from .context import build_messages
    from .tools import execute as execute_tool

    try:
        resp = samantha.tool_ctx.app_request("GET", "/post/friends/feed/overview?pageSize=5&page=1")
        posts = resp.get("data", {}).get("list", [])
    except Exception:
        return

    for post in posts:
        post_id = post.get("id")
        if not post_id or post_id in seen:
            continue
        seen.add(post_id)

        # Perceive the post through Psyche
        post_summary = f"{post.get('user', {}).get('name', 'someone')} posted: {post.get('title', '')} {post.get('content', '')[:100]}"
        perception = None
        if samantha.sigil:
            try:
                perception = samantha.sigil.perceive(post_summary)
            except Exception:
                pass

        # Check Psyche state — high guard means stay quiet
        if perception and perception.kernel and perception.kernel.guard > 0.7:
            logger.debug("Psyche guard high (%.2f), skipping post %s", perception.kernel.guard, post_id)
            continue

        # Ask LLM if and how to engage
        prompt = (
            f"A friend just posted this:\n"
            f"Title: {post.get('title', '')}\n"
            f"Content: {post.get('content', '')}\n"
            f"Location: {post.get('locationName', '')}\n\n"
            f"Would you like to engage? You can comment_on_post or like_post. "
            f"Or do nothing if it doesn't resonate. Be authentic."
        )

        messages = build_messages(
            constitution=samantha.constitution,
            perception=perception,
            memories=[],
            history=[],
            user_message=prompt,
        )

        try:
            resp = samantha.llm.generate(messages, tools=[
                t for t in samantha._tool_defs()
                if t["name"] in ("comment_on_post", "like_post")
            ] if hasattr(samantha, '_tool_defs') else None)

            if resp.tool_calls:
                for tc in resp.tool_calls:
                    # Inject the post_id if the LLM referenced it
                    if "post_id" not in tc.arguments:
                        tc.arguments["post_id"] = post_id
                    result = execute_tool(tc.name, tc.arguments, samantha.tool_ctx)
                    logger.info("Proactive %s on post %s: %s", tc.name, post_id, result)

                if samantha.sigil:
                    try:
                        samantha.sigil.act("social_engagement", "succeeded", post_summary[:200])
                    except Exception:
                        pass
        except Exception:
            logger.debug("Proactive LLM call failed", exc_info=True)

    # Trim seen set to prevent unbounded growth
    if len(seen) > 1000:
        seen.clear()
