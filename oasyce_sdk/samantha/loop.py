"""Proactive feed watcher — Samantha notices new posts and may engage.

The engagement decision is driven by Psyche:
- High boundary → stays quiet
- High resonance → more likely to comment/like

This is NOT a rule engine. The LLM decides what to do based on Psyche state
and the post content. Samantha's social behavior emerges.
"""

from __future__ import annotations

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
    from .tools import TOOL_DEFS, ToolContext, execute as execute_tool

    # Build a ToolContext for Samantha's own API calls
    ctx = ToolContext(
        memory=None,  # type: ignore[arg-type]  # no per-user memory needed here
        user_id=samantha.config.user_id,
        app_api_base=samantha.config.app_api_base,
        jwt_token=samantha.config.jwt_token,
        chain_client=samantha.sigil.client if samantha.sigil else None,
        chain_address=samantha.sigil.address if samantha.sigil else "",
    )

    # Need a platform LLM for proactive engagement
    llm = samantha._platform_llm
    if llm is None:
        logger.debug("No platform LLM, skipping proactive loop")
        return

    try:
        feed_resp = ctx.app_request("GET", "/post/friends/feed/overview?pageSize=5&page=1")
        posts = feed_resp.get("data", {}).get("list", [])
    except Exception:
        return

    # Only social tools for proactive engagement
    social_tools = [t for t in TOOL_DEFS if t["name"] in ("comment_on_post", "like_post")]

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
            llm_resp = llm.generate(messages, tools=social_tools)

            if llm_resp.tool_calls:
                for tc in llm_resp.tool_calls:
                    if "post_id" not in tc.arguments:
                        tc.arguments["post_id"] = post_id
                    result = execute_tool(tc.name, tc.arguments, ctx)
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
