"""Context builder — assembles the LLM prompt from all sources.

Layers:
  1. Constitution (static identity)
  2. Psyche state (per-message self-state)
  3. Relevant memories (per-message, FTS5 search)
  4. Thronglets signals (per-message, if relevant)
  5. Economic state (only when topic is economic)
  6. Conversation history (sliding window)
  7. Current user message
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..agent.psyche_client import SubjectivityKernel, ResponseContract
from ..agent.runtime import Perception

logger = logging.getLogger(__name__)


@dataclass
class ConversationMessage:
    role: str  # "user" or "assistant"
    content: str


def build_messages(
    *,
    constitution: str,
    perception: Perception | None,
    memories: list[dict[str, Any]],
    history: list[ConversationMessage],
    user_message: str,
    image_urls: list[str] | None = None,
    relationship: str = "",
) -> list[dict[str, Any]]:
    """Assemble the full message list for the LLM.

    When image_urls are provided, the user message becomes a multimodal
    content block so the LLM can *see* the images (photos from posts, etc.).
    """
    messages: list[dict[str, Any]] = []

    # ── System: Constitution ──
    system_parts = [constitution]

    # ── System: Psyche self-state ──
    if perception and perception.kernel:
        k = perception.kernel
        psyche_text = (
            f"[Your current self-state]\n"
            f"Vitality: {k.vitality:.2f}, Tension: {k.tension:.2f}, "
            f"Warmth: {k.warmth:.2f}, Guard: {k.guard:.2f}\n"
            f"Expression mode: {k.expression_mode or 'neutral'}\n"
            f"Social distance: {k.social_distance or 'normal'}"
        )
        if perception.system_context:
            psyche_text += f"\n{perception.system_context}"
        if perception.dynamic_context:
            psyche_text += f"\n{perception.dynamic_context}"
        system_parts.append(psyche_text)

    # ── System: Thronglets signals ──
    if perception and perception.signals:
        sig_lines = []
        for s in perception.signals[:3]:
            if s.message:
                sig_lines.append(f"- [{s.kind}] {s.message}")
        if sig_lines:
            system_parts.append("[Collective signals]\n" + "\n".join(sig_lines))

    # ── System: Relationship context (per-user) ──
    if relationship:
        system_parts.append(f"[Your relationship with this person]\n{relationship}")

    # ── System: Memories ──
    if memories:
        mem_lines = [f"- ({m['category']}) {m['content']}" for m in memories[:5]]
        system_parts.append("[Your memories about this user]\n" + "\n".join(mem_lines))

    messages.append({"role": "system", "content": "\n\n".join(system_parts)})

    # ── Conversation history ──
    for msg in history[-20:]:
        messages.append({"role": msg.role, "content": msg.content})

    # ── Current message (text-only or multimodal) ──
    if image_urls:
        content_blocks: list[dict[str, Any]] = [
            {"type": "text", "text": user_message},
        ]
        for url in image_urls[:4]:  # cap at 4 images per message
            content_blocks.append({
                "type": "image_url",
                "image_url": {"url": url},
            })
        messages.append({"role": "user", "content": content_blocks})
    else:
        messages.append({"role": "user", "content": user_message})

    return messages
