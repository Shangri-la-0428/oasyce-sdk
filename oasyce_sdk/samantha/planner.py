"""Planner — Psyche + Thronglets-driven behavioral planning. Zero LLM calls.

Converts Perception (Psyche kernel/contract + Thronglets ambient priors)
into a Plan that governs how the Generator assembles context and how the
Evaluator checks output.

Cost: zero. Pure rule engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..agent.runtime import Perception
    from .server import Stimulus

# ── Plan ──────────────────────────────────────────────────────────

@dataclass
class Plan:
    """What Joi should do and how. Drives Generator + Evaluator."""

    intent: str = "respond"         # respond | observe | engage | comfort
    register: str = "warm"          # warm | playful | thoughtful | gentle | direct
    max_sentences: int = 8          # 0 = no limit
    max_tokens: int | None = None   # hard limit from Psyche GenerationControls
    emoji_limit: int = 1            # -1 = no limit
    tone_style: str = ""            # "match" | "avoid" | "natural" (Psyche v11.8)
    tools: list[str] | None = None  # None = all tools available
    focus: str = ""                 # hint for generator: what to pay attention to
    include_posts: bool = False     # whether to fetch user's recent posts
    include_memories: bool = True   # whether to recall memories
    history_limit: int = 20         # how many history messages to include
    require_confirmation: bool = False  # from Psyche GenerationControls/boundaryMode


# ── Tool sets per intent ──────────────────────────────────────────

_CHAT_TOOLS: list[str] | None = None  # all
_ENGAGE_TOOLS = ["comment_on_post", "like_post"]
_COMMENT_TOOLS = ["reply_to_comment"]


# ── Ambient priors → Plan adjustments ─────────────────────────────

def _apply_ambient_priors(p: Plan, priors: dict) -> None:
    """Let collective experience (Thronglets priors) steer the Plan.

    Three prior kinds from `ambient.rs`:
      - failure-residue : similar contexts have failed before
      - mixed-residue   : success + failure both present (method contested)
      - success-prior   : stable success path

    Policy state may flag "policy-conflict" or "method-conflict".
    Confidence is in [0, 1].

    Defensive: the payload is external JSON. We accept anything dict-shaped
    and skip silently on malformed items rather than crashing the pipeline.
    """
    if not isinstance(priors, dict):
        return
    items = priors.get("priors") or []
    if not isinstance(items, list):
        return

    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind", "")
        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        summary = (item.get("summary") or "").strip()
        policy = item.get("policy_state")

        if kind == "failure-residue" and confidence >= 0.6:
            # Collective has burned fingers here — slow down, confirm first.
            if not p.focus:
                p.focus = (
                    f"collective experience flags risk — {summary}"
                    if summary else
                    "collective experience flags this path as risky"
                )
            if policy == "policy-conflict":
                p.require_confirmation = True
            # Keep the response tighter when walking a risky path
            if p.max_sentences == 0 or p.max_sentences > 4:
                p.max_sentences = 4

        elif kind == "mixed-residue":
            # Method is contested — don't project false confidence.
            if not p.focus and summary:
                p.focus = f"method is contested — {summary}"
            if policy in ("policy-conflict", "method-conflict"):
                p.require_confirmation = True

        elif kind == "success-prior" and confidence >= 0.7:
            # Stable success path — allow slightly more ambition.
            if 0 < p.max_sentences < 6:
                p.max_sentences = min(8, p.max_sentences + 2)


# ── Planner ───────────────────────────────────────────────────────

def plan(stimulus: Stimulus, perception: Perception | None = None) -> Plan:
    """Pure function: stimulus + Perception → Plan.

    No side effects, no network calls. Testable in isolation.
    Perception may be None for tests/standalone calls; a Perception with
    default fields is equivalent to "baseline self-state, no priors".
    """
    p = Plan()

    kernel = perception.kernel if perception else None
    contract = perception.response_contract if perception else None
    priors = perception.ambient_priors if perception else None

    # ── Apply Psyche ResponseContract (if available) ──────────
    if contract:
        if contract.expression_mode:
            p.register = contract.expression_mode
        if contract.max_sentences > 0:
            p.max_sentences = contract.max_sentences
        if contract.emoji_limit >= 0:
            p.emoji_limit = contract.emoji_limit
        if contract.tone_style:
            p.tone_style = contract.tone_style
        if contract.boundary_mode == "confirm-first":
            p.require_confirmation = True

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
            # Attention anchor steers focus
            if kernel.attention_anchor == "threat" and not p.focus:
                p.focus = "address the concern directly"
            elif kernel.attention_anchor == "bond":
                p.include_posts = True
            # Boundary mode from kernel
            if kernel.boundary_mode == "confirm-first":
                p.require_confirmation = True

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

    # ── Ambient priors (collective experience) ─────────────────
    # Applied after stimulus-specific rules so they can refine focus/caps.
    if priors:
        _apply_ambient_priors(p, priors)

    return p
