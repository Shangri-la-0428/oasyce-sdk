"""Stimulus — the unified input to an Agent's PGE pipeline.

Everything that enters an Agent's awareness becomes a ``Stimulus`` before
the pipeline runs: chat messages, comments, @mentions, feed posts,
scheduled wake-ups, webhook payloads. One shape, one loop.

The fields are deliberately generic. Deployment-specific metadata (Discord
message IDs, Slack thread references, Oasyce App comment IDs) lives in
the ``metadata`` dict — the Agent core never reads it, only the subclass's
``_enrich`` / ``_build_prompt`` / tools do.

This module has no imports from ``samantha`` or any deployment — it's the
bottom of the dependency graph so both ``agent.channel`` and
``samantha.server`` can reference it without creating a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Stimulus:
    """Anything that enters the Agent's awareness.

    Every event — chat message, comment, @mention, feed post, webhook
    payload — becomes a Stimulus before entering the pipeline. One
    consciousness, one loop.

    Fields:
      kind: deployment-defined event class. Samantha uses
        ``"chat" | "comment" | "mention" | "feed_post"``. Other agents
        may define their own (e.g. ``"slash_command"``, ``"wake"``).
      content: the textual payload the LLM will react to.
      sender_id: integer identifier for the sender in the deployment's
        user space. Zero when unknown or irrelevant.
      post_id, session_id, comment_id: deployment-specific correlation
        IDs. Zero when not applicable.
      image_urls: any images attached to the stimulus (vision routing
        reads this list).
      metadata: dict for deployment-specific extras. The Agent core
        never touches this — only the subclass's overrides do.
    """

    kind: str
    content: str
    sender_id: int = 0
    post_id: int = 0
    session_id: int = 0
    comment_id: int = 0
    image_urls: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
