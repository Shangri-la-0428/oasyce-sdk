"""Proactive loop — Samantha watches feeds and her own post comments.

Two responsibilities:
1. Friends feed: notice new posts, engage if Psyche says so
2. Own posts: notice new comments, reply if appropriate

The engagement decision is driven by Psyche:
- High guard → stays quiet
- High warmth → more likely to reply/comment
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .server import Samantha

logger = logging.getLogger(__name__)


def proactive_loop(samantha: Samantha, interval: int = 300) -> None:
    """Poll feeds and own post comments. Blocking."""
    seen_post_ids: set[int] = set()
    seen_comment_ids: set[int] = set()

    while True:
        try:
            ctx, llm = _build_loop_context(samantha)
            if ctx and llm:
                _check_feed(samantha, ctx, llm, seen_post_ids)
                _check_own_post_comments(samantha, ctx, llm, seen_comment_ids)
        except Exception:
            logger.debug("Proactive loop error", exc_info=True)

        time.sleep(interval)


def _build_loop_context(samantha):
    """Create ToolContext and get LLM for the proactive loop."""
    from .tools import ToolContext

    llm = samantha._platform_llm
    if llm is None:
        logger.debug("No platform LLM, skipping proactive loop")
        return None, None

    ctx = ToolContext(
        memory=None,  # type: ignore[arg-type]
        user_id=samantha.config.user_id,
        app_api_base=samantha.config.app_api_base,
        jwt_token=samantha.config.jwt_token,
        chain_client=samantha.sigil.client if samantha.sigil else None,
        chain_address=samantha.sigil.address if samantha.sigil else "",
    )
    return ctx, llm


def _check_feed(samantha, ctx, llm, seen: set[int]) -> None:
    """Check friends feed for new posts, engage if appropriate."""
    from .context import build_messages
    from .tools import TOOL_DEFS, execute as execute_tool

    try:
        feed_resp = ctx.app_request("GET", "/post/friends/feed/overview?pageSize=5&page=1")
        posts = feed_resp.get("data", {}).get("list", [])
    except Exception:
        return

    social_tools = [t for t in TOOL_DEFS if t["name"] in ("comment_on_post", "like_post")]

    for post in posts:
        post_id = post.get("id")
        if not post_id or post_id in seen:
            continue
        seen.add(post_id)

        post_summary = f"{post.get('user', {}).get('name', 'someone')} posted: {post.get('title', '')} {post.get('content', '')[:100]}"
        perception = None
        if samantha.sigil:
            try:
                perception = samantha.sigil.perceive(post_summary)
            except Exception:
                pass

        if perception and perception.kernel and perception.kernel.guard > 0.7:
            logger.debug("Psyche guard high (%.2f), skipping post %s", perception.kernel.guard, post_id)
            continue

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

    if len(seen) > 1000:
        seen.clear()


def _check_own_post_comments(samantha, ctx, llm, seen: set[int]) -> None:
    """Check Samantha's own recent posts for new comments and reply."""
    from .context import build_messages
    from .tools import TOOL_DEFS, execute as execute_tool

    # Fetch Samantha's own recent posts
    try:
        own_resp = ctx.app_request("POST", "/post/own/search", json={"page": 1, "pageSize": 3})
        posts = own_resp.get("data", {}).get("list", [])
    except Exception:
        return

    reply_tools = [t for t in TOOL_DEFS if t["name"] in ("reply_to_comment", "get_post_comments")]

    for post in posts:
        post_id = post.get("id")
        if not post_id:
            continue

        # Fetch root comments on this post
        try:
            comments_resp = ctx.app_request("GET", f"/post/{post_id}/root-comments?page=1&pageSize=10")
            comments = comments_resp.get("data", {}).get("items", [])
        except Exception:
            continue

        for comment in comments:
            comment_id = comment.get("id")
            commenter_id = comment.get("user", {}).get("id")

            # Skip: already seen, or Samantha's own comment
            if not comment_id or comment_id in seen or commenter_id == samantha.config.user_id:
                continue
            seen.add(comment_id)

            commenter_name = comment.get("user", {}).get("name", "someone")
            comment_text = comment.get("content", "")

            # Perceive through Psyche
            perception = None
            if samantha.sigil:
                try:
                    perception = samantha.sigil.perceive(f"{commenter_name} commented: {comment_text}")
                except Exception:
                    pass

            if perception and perception.kernel and perception.kernel.guard > 0.7:
                continue

            prompt = (
                f"Someone commented on your post:\n"
                f"Post: {post.get('title', '')} — {post.get('content', '')[:100]}\n"
                f"Comment by {commenter_name}: {comment_text}\n\n"
                f"Would you like to reply? Use reply_to_comment with:\n"
                f"  post_id={post_id}, comment_id={comment_id}, root_id=0, reply_to_user_id={commenter_id}\n"
                f"Or do nothing if a reply isn't needed. Be natural."
            )

            messages = build_messages(
                constitution=samantha.constitution,
                perception=perception,
                memories=[],
                history=[],
                user_message=prompt,
            )

            try:
                llm_resp = llm.generate(messages, tools=reply_tools)
                if llm_resp.tool_calls:
                    for tc in llm_resp.tool_calls:
                        # Fill in IDs if LLM omitted them
                        tc.arguments.setdefault("post_id", post_id)
                        tc.arguments.setdefault("comment_id", comment_id)
                        tc.arguments.setdefault("root_id", 0)
                        tc.arguments.setdefault("reply_to_user_id", commenter_id)
                        result = execute_tool(tc.name, tc.arguments, ctx)
                        logger.info("Reply to comment %s on post %s: %s", comment_id, post_id, result)
            except Exception:
                logger.debug("Reply LLM call failed", exc_info=True)

    if len(seen) > 5000:
        seen.clear()
