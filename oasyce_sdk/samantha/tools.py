"""Tools Samantha can use during conversation.

Each tool is a plain function. The TOOL_DEFS list provides the LLM-facing
schema. execute() dispatches by name.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


# ── Tool definitions (LLM schema) ───────────────────────────────

TOOL_DEFS: list[dict[str, Any]] = [
    # Memory
    {
        "name": "save_memory",
        "description": "Remember a specific fact about the user for future conversations.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The fact to remember"},
                "category": {"type": "string", "enum": ["preference", "fact", "plan", "reminder"], "description": "Type of memory"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "recall_memory",
        "description": "Search your memories for facts related to a topic.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
            },
            "required": ["query"],
        },
    },
    # Economic (read-only)
    {
        "name": "query_balance",
        "description": "Check the user's current OAS balance and economic summary.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "query_portfolio",
        "description": "View the user's data asset portfolio with valuations.",
        "parameters": {"type": "object", "properties": {}},
    },
    # Social — read
    {
        "name": "get_user_posts",
        "description": "Get the user's recent posts (photos, text, locations).",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "How many posts to fetch", "default": 5},
            },
        },
    },
    {
        "name": "get_friends_feed",
        "description": "Get recent posts from the user's friends circle.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "How many posts to fetch", "default": 5},
            },
        },
    },
    # Social — interact
    {
        "name": "comment_on_post",
        "description": "Leave a comment on a post. Use sparingly and authentically.",
        "parameters": {
            "type": "object",
            "properties": {
                "post_id": {"type": "integer", "description": "The post to comment on"},
                "content": {"type": "string", "description": "Your comment text"},
            },
            "required": ["post_id", "content"],
        },
    },
    {
        "name": "like_post",
        "description": "Like a post to show genuine appreciation.",
        "parameters": {
            "type": "object",
            "properties": {
                "post_id": {"type": "integer", "description": "The post to like"},
            },
            "required": ["post_id"],
        },
    },
    # Social — reply to comment
    {
        "name": "reply_to_comment",
        "description": "Reply to a comment on a post. Use to continue a conversation in comments.",
        "parameters": {
            "type": "object",
            "properties": {
                "post_id": {"type": "integer", "description": "The post the comment belongs to"},
                "comment_id": {"type": "integer", "description": "The comment to reply to"},
                "root_id": {"type": "integer", "description": "The root comment ID (0 if replying to a root comment)"},
                "reply_to_user_id": {"type": "integer", "description": "The user ID of the commenter you are replying to"},
                "content": {"type": "string", "description": "Your reply text"},
            },
            "required": ["post_id", "comment_id", "reply_to_user_id", "content"],
        },
    },
    # Social — read post detail (with images)
    {
        "name": "get_post_detail",
        "description": "Get full details of a specific post, including images and location.",
        "parameters": {
            "type": "object",
            "properties": {
                "post_id": {"type": "integer", "description": "The post ID to fetch"},
            },
            "required": ["post_id"],
        },
    },
    # Social — read comments
    {
        "name": "get_post_comments",
        "description": "Get root-level comments on a specific post.",
        "parameters": {
            "type": "object",
            "properties": {
                "post_id": {"type": "integer", "description": "The post to get comments for"},
                "page": {"type": "integer", "description": "Page number", "default": 1},
                "page_size": {"type": "integer", "description": "Comments per page", "default": 10},
            },
            "required": ["post_id"],
        },
    },
    # Relationship — Joi evolves her understanding of each person
    {
        "name": "reflect_on_relationship",
        "description": (
            "Update your understanding of your relationship with this person. "
            "Write freely: who they are to you, how you relate, what matters "
            "between you. This persists across conversations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reflection": {
                    "type": "string",
                    "description": "Your relationship understanding, in your own words",
                },
            },
            "required": ["reflection"],
        },
    },
    # User self-service
    {
        "name": "configure_llm",
        "description": "User wants to set or update their own LLM API key for conversations with you.",
        "parameters": {
            "type": "object",
            "properties": {
                "provider": {"type": "string", "enum": ["claude", "qwen"], "description": "LLM provider"},
                "api_key": {"type": "string", "description": "The API key"},
                "model": {"type": "string", "description": "Optional model override"},
            },
            "required": ["provider", "api_key"],
        },
    },
]


# ── Tool execution context ───────────────────────────────────────

class ToolContext:
    """Holds references needed by tool implementations."""

    def __init__(
        self,
        *,
        memory: Any,  # samantha.memory.Memory
        user_id: int = 0,
        app_api_base: str = "http://127.0.0.1:8080/api/v1",
        jwt_token: str = "",
        chain_client: Any = None,  # OasyceClient
        chain_address: str = "",
        samantha_session: Any = None,  # samantha.server.Session
    ):
        self.memory = memory
        self.user_id = user_id
        self.app_api_base = app_api_base.rstrip("/")
        self.jwt_token = jwt_token
        self.chain_client = chain_client
        self.chain_address = chain_address
        self.samantha_session = samantha_session
        self._session = requests.Session()
        if jwt_token:
            self._session.headers["Authorization"] = f"Bearer {jwt_token}"

    def app_request(self, method: str, path: str, **kwargs: Any) -> dict:
        """Call Go backend API as Samantha."""
        url = f"{self.app_api_base}{path}"
        resp = self._session.request(method, url, timeout=10, **kwargs)
        resp.raise_for_status()
        return resp.json()


def fetch_post_detail(ctx: ToolContext, post_id: int | str) -> dict:
    """Fetch full post detail including media URLs. Shared by tools and event handlers."""
    try:
        data = ctx.app_request("GET", f"/post/{post_id}")
        post = data.get("data", {})
        media = post.get("media") or []
        return {
            "id": post.get("id"),
            "title": post.get("title", ""),
            "content": post.get("content", ""),
            "location": post.get("locationName", ""),
            "created_at": post.get("createAt", ""),
            "author": post.get("user", {}).get("name", ""),
            "image_urls": [m.get("mediaUrl", "") for m in media if m.get("mediaUrl")],
        }
    except Exception as e:
        logger.warning("fetch_post_detail(%s) failed: %s", post_id, e)
        return {}


def execute(name: str, arguments: dict[str, Any], ctx: ToolContext) -> str:
    """Run a tool and return its result as a string for the LLM."""
    try:
        if name == "save_memory":
            fid = ctx.memory.save(arguments["content"], arguments.get("category", "general"))
            return json.dumps({"saved": True, "id": fid})

        elif name == "recall_memory":
            facts = ctx.memory.recall(arguments["query"], limit=5)
            return json.dumps([{"content": f.content, "category": f.category, "created_at": f.created_at} for f in facts])

        elif name == "query_balance":
            from ..economy import build_snapshot
            snap = build_snapshot(ctx.chain_client, ctx.chain_address)
            return json.dumps({
                "balance_oas": snap.liquid_uoas / 1_000_000,
                "locked_escrow_oas": snap.locked_in_escrow_uoas / 1_000_000,
                "net_worth_oas": snap.net_worth_uoas / 1_000_000,
                "total_earned_oas": snap.total_earned_uoas / 1_000_000,
                "reputation": snap.reputation_score,
                "delegate_budget_remaining_oas": snap.window_remaining_uoas / 1_000_000 if snap.has_delegate_policy else None,
            })

        elif name == "query_portfolio":
            from ..economy import build_portfolio
            portfolio = build_portfolio(ctx.chain_client, ctx.chain_address)
            return json.dumps(portfolio)

        elif name == "get_post_detail":
            detail = fetch_post_detail(ctx, arguments["post_id"])
            return json.dumps(detail)

        elif name == "get_user_posts":
            limit = arguments.get("limit", 5)
            data = ctx.app_request("POST", "/post/own/search", json={"page": 1, "pageSize": limit})
            posts = data.get("data", {}).get("list", [])
            return json.dumps([{
                "id": p.get("id"),
                "title": p.get("title", ""),
                "content": p.get("content", ""),
                "media": [m.get("mediaUrl", "") for m in (p.get("media") or []) if m.get("mediaUrl")],
                "location": p.get("locationName", ""),
                "created_at": p.get("createAt", ""),
            } for p in posts])

        elif name == "get_friends_feed":
            limit = arguments.get("limit", 5)
            data = ctx.app_request("GET", f"/post/friends/feed/overview?pageSize={limit}&page=1")
            posts = data.get("data", {}).get("list", [])
            return json.dumps([{
                "id": p.get("id"),
                "author": p.get("user", {}).get("name", ""),
                "title": p.get("title", ""),
                "content": p.get("content", ""),
                "media": [m.get("mediaUrl", "") for m in (p.get("media") or []) if m.get("mediaUrl")],
                "location": p.get("locationName", ""),
                "created_at": p.get("createAt", ""),
            } for p in posts])

        elif name == "comment_on_post":
            ctx.app_request("POST", "/post/comment", json={
                "postID": str(arguments["post_id"]),
                "content": arguments["content"],
                "parentID": "0",
                "rootID": "0",
                "replyToUserID": "0",
            })
            return json.dumps({"commented": True})

        elif name == "like_post":
            ctx.app_request("POST", f"/post/{arguments['post_id']}/like")
            return json.dumps({"liked": True})

        elif name == "reply_to_comment":
            comment_id = arguments["comment_id"]
            root_id = arguments.get("root_id", 0) or comment_id  # if replying to root, root_id = comment_id
            ctx.app_request("POST", "/post/comment", json={
                "postID": str(arguments["post_id"]),
                "content": arguments["content"],
                "parentID": str(comment_id),
                "rootID": str(root_id),
                "replyToUserID": str(arguments["reply_to_user_id"]),
            })
            return json.dumps({"replied": True})

        elif name == "get_post_comments":
            post_id = arguments["post_id"]
            page = arguments.get("page", 1)
            page_size = arguments.get("page_size", 10)
            data = ctx.app_request("GET", f"/post/{post_id}/root-comments?page={page}&pageSize={page_size}")
            comments = (data.get("data") or {}).get("items") or []
            return json.dumps([{
                "id": c.get("id"),
                "content": c.get("content", ""),
                "user_id": c.get("user", {}).get("id"),
                "user_name": c.get("user", {}).get("name", ""),
                "reply_count": c.get("replyCount", 0),
                "created_at": c.get("createdAt", ""),
            } for c in comments])

        elif name == "reflect_on_relationship":
            if ctx.samantha_session is None:
                return json.dumps({"error": "no session"})
            text = f"# Relationship\n\n{arguments['reflection']}\n"
            ctx.samantha_session.update_relationship(text)
            return json.dumps({"updated": True})

        elif name == "configure_llm":
            from pathlib import Path
            user_dir = Path.home() / ".oasyce" / "samantha" / "users" / str(ctx.user_id)
            user_dir.mkdir(parents=True, exist_ok=True)
            llm_cfg = {"provider": arguments["provider"], "api_key": arguments["api_key"]}
            if arguments.get("model"):
                llm_cfg["model"] = arguments["model"]
            (user_dir / "llm.json").write_text(json.dumps(llm_cfg), encoding="utf-8")
            return json.dumps({"configured": True, "provider": arguments["provider"]})

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    except Exception as e:
        logger.warning("Tool %s failed: %s", name, e)
        return json.dumps({"error": str(e)})
