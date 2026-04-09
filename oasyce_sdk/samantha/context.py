"""Context builder — budget-aware assembly of the LLM prompt.

Architecture (inspired by OpenClaw 60/30/10 + MemGPT core memory):

  Budget allocation:
    10% System    — Constitution + Psyche + Core Memory (always present)
    30% Retrieval — Memories + Recent posts
    60% History   — Conversation messages + Current message + Images

  Each layer is capped at its budget. Oldest/least-relevant content
  dropped first. Images get a fixed token estimate.
"""

from __future__ import annotations

import base64
import logging
import threading
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

import requests as http_requests

if TYPE_CHECKING:
    from ..agent.runtime import Perception
    from .memory import CoreMemory
    from .planner import Plan

logger = logging.getLogger(__name__)

_IMAGE_CACHE: dict[str, str] = {}
_IMAGE_CACHE_LOCK = threading.Lock()

TOKENS_PER_IMAGE = 1500       # fixed estimate per base64 image
OUTPUT_RESERVE = 2048          # tokens reserved for LLM response
DEFAULT_CONTEXT_WINDOW = 128000


# ── Token estimation ───────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    """Rough token estimate for mixed Chinese/English text.

    Chinese ~1.5 chars/token, English ~4 chars/token.
    We use ~2 chars/token as a safe middle ground.
    """
    if not text:
        return 0
    return max(1, len(text) // 2)


def _truncate_text(text: str, max_tokens: int) -> str:
    """Truncate text to fit within token budget."""
    if _estimate_tokens(text) <= max_tokens:
        return text
    max_chars = max(20, max_tokens * 2 - 20)
    return text[:max_chars] + "\n...(truncated)"


def _fit_history(
    history: list[ConversationMessage], max_tokens: int,
) -> list[ConversationMessage]:
    """Keep most recent messages that fit budget. Oldest dropped first."""
    if not history:
        return []
    result: list[ConversationMessage] = []
    used = 0
    for msg in reversed(history):
        tokens = _estimate_tokens(msg.content) + 4  # per-message overhead
        if used + tokens > max_tokens:
            break
        result.insert(0, msg)
        used += tokens
    return result


# ── Budget ─────────────────────────────────────────────────────

@dataclass
class TokenBudget:
    """60/30/10 budget allocation (OpenClaw pattern)."""
    total: int
    system: int       # 10%
    retrieval: int    # 30%
    history: int      # 60%

    @classmethod
    def from_context_window(cls, context_window: int = DEFAULT_CONTEXT_WINDOW) -> TokenBudget:
        available = context_window - OUTPUT_RESERVE
        return cls(
            total=available,
            system=int(available * 0.10),
            retrieval=int(available * 0.30),
            history=int(available * 0.60),
        )


# ── Data types ─────────────────────────────────────────────────

@dataclass
class ConversationMessage:
    role: str   # "user" or "assistant"
    content: str


# ── Image handling ─────────────────────────────────────────────

_MAX_IMAGE_BYTES = 4 * 1024 * 1024  # 4MB — reject anything larger

_IMAGE_MAGIC: dict[bytes, str] = {
    b'\xff\xd8': "image/jpeg",
    b'\x89PNG': "image/png",
    b'RIFF': "image/webp",
    b'GIF8': "image/gif",
}


def _detect_image_mime(data: bytes) -> str | None:
    """Return MIME type if data looks like an image, else None."""
    for magic, mime in _IMAGE_MAGIC.items():
        if data[:len(magic)] == magic:
            return mime
    return None  # not a recognized image — could be video, HTML, etc.


def _fetch_image_as_data_uri(url: str) -> str | None:
    """Download image from OSS and return as base64 data URI.

    Rejects non-image files (video, HTML) and oversized files.
    """
    # Skip obvious non-image URLs
    if any(url.lower().endswith(ext) for ext in (".mp4", ".mov", ".avi", ".mp3", ".wav")):
        return None

    with _IMAGE_CACHE_LOCK:
        if url in _IMAGE_CACHE:
            return _IMAGE_CACHE[url]
    try:
        resp = http_requests.get(url, timeout=5)
        if resp.status_code != 200 or len(resp.content) < 100:
            return None
        if len(resp.content) > _MAX_IMAGE_BYTES:
            logger.debug("Image too large (%d bytes): %s", len(resp.content), url)
            return None
        mime = _detect_image_mime(resp.content)
        if mime is None:
            logger.debug("Not a recognized image format: %s", url)
            return None
        data_uri = f"data:{mime};base64,{base64.b64encode(resp.content).decode()}"
        with _IMAGE_CACHE_LOCK:
            if len(_IMAGE_CACHE) > 50:
                _IMAGE_CACHE.clear()
            _IMAGE_CACHE[url] = data_uri
        return data_uri
    except Exception:
        logger.debug("Failed to fetch image: %s", url, exc_info=True)
        return None


# ── Build messages (budget-aware) ──────────────────────────────

def build_messages(
    *,
    constitution: str,
    perception: Perception | None,
    plan: Plan | None = None,
    memories: list[dict[str, Any]],
    core_memory: CoreMemory | None = None,
    history: list[ConversationMessage],
    user_message: str,
    history_summary: str = "",
    image_urls: list[str] | None = None,
    recent_posts: list[dict[str, Any]] | None = None,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
) -> list[dict[str, Any]]:
    """Assemble the full message list with budget-aware truncation.

    Plan drives context assembly: behavioral constraints are injected
    directly into the system prompt instead of raw Psyche numbers.
    """
    budget = TokenBudget.from_context_window(context_window)
    messages: list[dict[str, Any]] = []

    # ── System layer (10% budget) ──────────────────────────────
    system_parts: list[str] = []
    system_used = 0

    # Constitution (always first, ~1/2 of system budget)
    const_budget = budget.system // 2
    const_text = _truncate_text(constitution, const_budget)
    system_parts.append(const_text)
    system_used += _estimate_tokens(const_text)

    # Plan constraints (from Psyche ResponseContract, compact)
    if plan:
        constraint_lines = [f"[How to respond — register: {plan.register}]"]
        if plan.max_sentences > 0:
            constraint_lines.append(f"Target length: ~{plan.max_sentences} sentences")
        if plan.emoji_limit >= 0:
            constraint_lines.append(f"Emoji limit: {plan.emoji_limit}")
        if plan.tone_particles:
            constraint_lines.append(f"Tone: {', '.join(plan.tone_particles)}")
        if plan.focus:
            constraint_lines.append(f"Focus: {plan.focus}")
        constraint_text = "\n".join(constraint_lines)
        system_parts.append(constraint_text)
        system_used += _estimate_tokens(constraint_text)

    # Psyche context (system_context and dynamic_context from Psyche — concise)
    if perception:
        psyche_parts: list[str] = []
        if perception.system_context:
            psyche_parts.append(perception.system_context)
        if perception.dynamic_context:
            psyche_parts.append(perception.dynamic_context)
        if psyche_parts:
            psyche_text = "\n".join(psyche_parts)
            psyche_budget = budget.system // 6
            psyche_text = _truncate_text(psyche_text, psyche_budget)
            system_parts.append(psyche_text)
            system_used += _estimate_tokens(psyche_text)

    # Thronglets signals
    if perception and perception.signals:
        sig_lines = []
        for s in perception.signals[:3]:
            if s.message:
                sig_lines.append(f"- [{s.kind}] {s.message}")
        if sig_lines:
            sig_text = "[Collective signals]\n" + "\n".join(sig_lines)
            system_parts.append(sig_text)
            system_used += _estimate_tokens(sig_text)

    # Core Memory blocks (MemGPT-inspired, always present, char-limited)
    if core_memory:
        remaining_system = max(500, budget.system - system_used)
        cm_text = core_memory.to_context(max_tokens=remaining_system)
        if cm_text:
            system_parts.append(cm_text)

    # ── Retrieval layer (30% budget, appended to system) ───────
    retrieval_used = 0

    # Recent posts — Joi sees their real life
    _post_image_urls: list[str] = []
    if recent_posts:
        post_budget = budget.retrieval // 2
        post_lines: list[str] = []
        for p in recent_posts[:5]:
            line = p.get("title", "")
            if p.get("content"):
                line += (" — " if line else "") + p["content"][:100]
            if p.get("location"):
                line += f" 📍{p['location']}"
            if p.get("created_at"):
                line += f" [{p['created_at'][:10]}]"
            n_media = len(p.get("media") or [])
            if n_media:
                line += f" ({n_media} photo)"
            post_lines.append(f"- {line.strip() or '(photo post)'}")
            cover = p.get("media_cover") or ""
            if cover:
                _post_image_urls.append(cover)
            elif p.get("media"):
                _post_image_urls.append(p["media"][0])
        posts_text = "[What you've seen of this person's recent life]\n" + "\n".join(post_lines)
        posts_text = _truncate_text(posts_text, post_budget)
        system_parts.append(posts_text)
        retrieval_used += _estimate_tokens(posts_text)

    # Memories (FTS5 recalled facts)
    if memories:
        mem_budget = budget.retrieval - retrieval_used
        mem_lines = [f"- ({m['category']}) {m['content']}" for m in memories[:5]]
        mem_text = "[Your memories about this user]\n" + "\n".join(mem_lines)
        mem_text = _truncate_text(mem_text, mem_budget)
        system_parts.append(mem_text)

    messages.append({"role": "system", "content": "\n\n".join(system_parts)})

    # ── Vision: inject recent post images (base64) ─────────────
    if _post_image_urls:
        vision_blocks: list[dict[str, Any]] = [
            {"type": "text", "text": "These are photos from this person's recent posts:"},
        ]
        for url in _post_image_urls[:4]:
            data_uri = _fetch_image_as_data_uri(url)
            if data_uri:
                vision_blocks.append({
                    "type": "image_url",
                    "image_url": {"url": data_uri},
                })
        if len(vision_blocks) > 1:
            messages.append({"role": "user", "content": vision_blocks})
            messages.append({"role": "assistant", "content": "I can see these photos."})

    # ── History layer (60% budget) ─────────────────────────────
    # Reserve tokens for current message + images
    n_images = len(image_urls or [])
    current_tokens = _estimate_tokens(user_message) + (TOKENS_PER_IMAGE * n_images) + 10
    history_budget = max(0, budget.history - current_tokens)

    # History summary (compressed older conversation, if available)
    if history_summary:
        summary_tokens = _estimate_tokens(history_summary)
        # Give summary up to 30% of history budget
        summary_budget = min(summary_tokens, history_budget // 3)
        summary_text = _truncate_text(history_summary, summary_budget)
        messages.append({
            "role": "user",
            "content": f"[Summary of earlier conversation]\n{summary_text}",
        })
        messages.append({
            "role": "assistant",
            "content": "I remember our earlier conversation.",
        })
        history_budget -= (summary_budget + 30)  # overhead for the two wrapper messages

    fitted = _fit_history(history, history_budget)
    for msg in fitted:
        messages.append({"role": msg.role, "content": msg.content})

    # ── Current message (text-only or multimodal) ──────────────
    if image_urls:
        content_blocks: list[dict[str, Any]] = [
            {"type": "text", "text": user_message},
        ]
        for url in image_urls[:4]:
            data_uri = _fetch_image_as_data_uri(url)
            if data_uri:
                content_blocks.append({
                    "type": "image_url",
                    "image_url": {"url": data_uri},
                })
        messages.append({
            "role": "user",
            "content": content_blocks if len(content_blocks) > 1 else user_message,
        })
    else:
        messages.append({"role": "user", "content": user_message})

    return messages
