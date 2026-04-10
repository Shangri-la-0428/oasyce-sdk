"""Unified HTTP client for the Go backend API.

Consolidates all scattered requests calls into one place:
  - Connection reuse (single requests.Session)
  - Consistent timeout and error handling
  - Media URL extraction (one function, not two)
"""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10


class AppClient:
    """Thin wrapper around the Go backend API. One session, reused everywhere."""

    def __init__(self, base_url: str, jwt_token: str = ""):
        self._base = base_url.rstrip("/")
        self._session = requests.Session()
        if jwt_token:
            self._session.headers["Authorization"] = f"Bearer {jwt_token}"

    def get(self, path: str, *, timeout: int = _DEFAULT_TIMEOUT, **kwargs: Any) -> dict:
        resp = self._session.get(f"{self._base}{path}", timeout=timeout, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, *, timeout: int = _DEFAULT_TIMEOUT, **kwargs: Any) -> dict:
        resp = self._session.post(f"{self._base}{path}", timeout=timeout, **kwargs)
        resp.raise_for_status()
        return resp.json()

    # ── Convenience methods for common endpoints ──────────────

    def send_message(self, session_id: int, content: str) -> dict:
        return self.post("/chat/message/send", json={
            "sessionID": str(session_id), "contentType": 1, "content": content,
        })

    def fetch_history(self, session_id: int, limit: int = 20) -> list[dict]:
        data = self.get("/chat/message/list",
                        params={"sessionID": session_id, "limit": limit},
                        timeout=5)
        return data.get("data", []) or []

    def fetch_user_posts(self, user_id: int, limit: int = 10) -> list[dict]:
        data = self.get(f"/post/friends/{user_id}/posts/live",
                        params={"page": 1, "pageSize": limit},
                        timeout=5)
        return data.get("data", {}).get("items", [])

    def fetch_own_posts(self, limit: int = 5) -> list[dict]:
        data = self.post("/post/own/search", json={"page": 1, "pageSize": limit})
        return (data.get("data") or {}).get("items") or []

    def fetch_friends_feed(self, limit: int = 5) -> dict:
        return self.get(f"/post/friends/feed/overview?pageSize={limit}&page=1")

    def fetch_post_detail(self, post_id: int | str) -> dict:
        data = self.get(f"/post/{post_id}")
        return data.get("data", {})

    def fetch_post_comments(self, post_id: int, page: int = 1,
                            page_size: int = 10) -> list[dict]:
        data = self.get(f"/post/{post_id}/root-comments?page={page}&pageSize={page_size}")
        return (data.get("data") or {}).get("items") or []

    def post_comment(self, post_id: int, content: str,
                     parent_id: int = 0, root_id: int = 0,
                     reply_to_user_id: int = 0) -> dict:
        return self.post("/post/comment", json={
            "postID": str(post_id),
            "content": content,
            "parentID": str(parent_id),
            "rootID": str(root_id),
            "replyToUserID": str(reply_to_user_id),
        })

    def like_post(self, post_id: int) -> dict:
        return self.post(f"/post/{post_id}/like")


# ── Media extraction (single source of truth) ─────────────────

def format_post(raw: dict, *, include_id: bool = False, author: str = "") -> dict:
    """Normalize raw API post into a clean dict. Single source of truth."""
    result: dict = {
        "title": raw.get("title", ""),
        "content": raw.get("content", ""),
        "location": raw.get("locationName", ""),
        "media": extract_media_urls(raw.get("media")),
        "media_cover": raw.get("mediaCover", ""),
        "created_at": raw.get("createAt", ""),
    }
    if include_id:
        result["id"] = raw.get("id")
    if author:
        result["author"] = author
    return result


def extract_media_urls(media_list: list | None) -> list[str]:
    """Extract image URLs from both normal and Live media formats.

    Normal: {"mediaUrl": "..."}
    Live:   {"photo": {"mediaUrl": "..."}, "video": ...}
    """
    if not media_list:
        return []
    urls = []
    for m in media_list:
        photo = m.get("photo")
        if isinstance(photo, dict) and photo.get("mediaUrl"):
            urls.append(photo["mediaUrl"])
            continue
        if m.get("mediaUrl"):
            urls.append(m["mediaUrl"])
    return urls
