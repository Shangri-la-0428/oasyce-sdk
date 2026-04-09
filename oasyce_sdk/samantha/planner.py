"""Planner — Psyche-driven behavioral planning. Zero LLM calls.

Converts Psyche ResponseContract + stimulus into a Plan that governs
how the Generator assembles context and how the Evaluator checks output.

Cost: zero. Pure rule engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..agent.psyche_client import ResponseContract, SubjectivityKernel
    from .server import Stimulus

# ── Plan ──────────────────────────────────────────────────────────

@dataclass
class Plan:
    """What Joi should do and how. Drives Generator + Evaluator."""

    intent: str = "respond"         # respond | observe | engage | comfort
    register: str = "warm"          # warm | playful | thoughtful | gentle | direct
    max_sentences: int = 8          # 0 = no limit
    emoji_limit: int = 1            # -1 = no limit
    tone_particles: list[str] = field(default_factory=list)
    tools: list[str] | None = None  # None = all tools available
    focus: str = ""                 # hint for generator: what to pay attention to
    include_posts: bool = False     # whether to fetch user's recent posts
    include_memories: bool = True   # whether to recall memories
    history_limit: int = 20         # how many history messages to include


# ── Tool sets per intent ──────────────────────────────────────────

_CHAT_TOOLS: list[str] | None = None  # all
_ENGAGE_TOOLS = ["comment_on_post", "like_post"]
_COMMENT_TOOLS = ["reply_to_comment"]


# ── Planner ───────────────────────────────────────────────────────

def plan(stimulus: Stimulus, kernel: SubjectivityKernel | None,
         contract: ResponseContract | None) -> Plan:
    """Pure function: stimulus + Psyche state → Plan.

    No side effects, no network calls. Testable in isolation.
    """
    p = Plan()

    # ── Apply Psyche ResponseContract (if available) ──────────
    if contract:
        if contract.expression_mode:
            p.register = contract.expression_mode
        if contract.max_sentences > 0:
            p.max_sentences = contract.max_sentences
        if contract.emoji_limit >= 0:
            p.emoji_limit = contract.emoji_limit
        if contract.tone_particles:
            p.tone_particles = contract.tone_particles

    # ── Stimulus-specific planning ────────────────────────────
    kind = stimulus.kind

    if kind == "chat":
        p.intent = "respond"
        p.tools = _CHAT_TOOLS
        p.include_posts = True
        p.include_memories = True

        # Psyche-driven adjustments
        if kernel:
            # Low vitality → shorter, less effortful
            if kernel.vitality < 0.3:
                p.max_sentences = min(p.max_sentences, 3)
            # High warmth → more personal, include posts
            if kernel.warmth > 0.7:
                p.register = p.register or "warm"
                p.include_posts = True
            # High tension → address the tension
            if kernel.tension > 0.6:
                p.focus = "something feels off — be honest about it"
            # High guard → more reserved
            if kernel.guard > 0.5:
                p.register = "thoughtful"
                p.max_sentences = min(p.max_sentences, 4)

    elif kind == "feed_post":
        p.tools = _ENGAGE_TOOLS
        p.include_memories = False
        p.include_posts = False
        p.history_limit = 0

        # Feed posts: Psyche decides whether to engage
        if kernel and kernel.guard > 0.5:
            p.intent = "observe"  # stay quiet
        else:
            p.intent = "engage"
            p.max_sentences = 2  # comments should be short
            p.emoji_limit = 0    # no emoji in comments

    elif kind == "comment":
        p.intent = "respond"
        p.tools = _COMMENT_TOOLS
        p.include_posts = False
        p.include_memories = False
        p.history_limit = 0
        p.max_sentences = 3

    elif kind == "mention":
        p.intent = "engage"
        p.tools = _ENGAGE_TOOLS
        p.include_posts = False
        p.include_memories = False
        p.history_limit = 0
        p.max_sentences = 3

    else:
        p.intent = "respond"

    return p
