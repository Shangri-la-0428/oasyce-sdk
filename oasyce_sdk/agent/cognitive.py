"""Cognitive primitives — v2 type definitions.

Five data types that underpin Samantha's unified cognitive pipeline.
Zero external dependencies; everything else builds on these.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class CognitiveMode(enum.Enum):
    """How the agent is thinking right now.

    Two axes — stimulus source (external/internal) × action target
    (external/internal) — yield exactly four modes. Every pipeline
    invocation carries one.
    """

    REACTIVE = "reactive"
    PROACTIVE = "proactive"
    OBSERVING = "observing"
    REFLECTING = "reflecting"


@dataclass
class Appraisal:
    """Emotional encoding of a stimulus — Psyche integration point.

    Affects memory persistence (emotional_weight → recall ranking)
    and planning (intensity/valence steer register and focus).
    """

    relevance: float = 0.5
    intensity: float = 0.5
    valence: float = 0.0
    emotional_weight: float = 0.5
    dominant_affect: str = ""
    psyche_delta: dict[str, float] = field(default_factory=dict)


@dataclass
class Observation:
    """Verbatim record of something the agent perceived.

    Captures full content (not truncated), media, location, and the
    agent's emotional state at observation time. One observation per
    external event (post, comment, message).
    """

    source_type: str = ""
    source_id: int = 0
    author_id: int = 0
    content: str = ""
    media_urls: list[str] = field(default_factory=list)
    location: str = ""
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    emotional_weight: float = 0.5
    psyche_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass
class Annotation:
    """Structured understanding layered on an Observation.

    Topics, entities, sentiment — extracted by rule or LLM. Serves as
    a secondary index for retrieval (closet boost pattern: ranking
    signal, never gate).
    """

    target_type: str = ""
    target_id: int = 0
    topics: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    sentiment: str = "neutral"
    summary: str = ""
    confidence: float = 0.8
    source: str = "auto"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class KnowledgeTriple:
    """Subject–predicate–object with temporal validity.

    ADD-only: new facts append; old facts expire via valid_to. Never
    update or delete — the full history is the truth.
    """

    subject: str = ""
    predicate: str = ""
    object: str = ""
    valid_from: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    valid_to: str = ""
    source_type: str = ""
    source_id: int = 0
    confidence: float = 0.8
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
