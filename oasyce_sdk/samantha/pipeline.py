"""Pipeline — the PGE cognitive loop as pure orchestration.

Extracted from Samantha so the loop can be:
  - tested without a full Samantha/HTTP/DB stack
  - audited as a single readable flow
  - replaced or wrapped without touching phase implementations

All I/O (Psyche, Thronglets, App API, LLM, Memory) is delegated to
callables passed in by the caller. The pipeline itself is deterministic
given its inputs — no side effects beyond what the phases do.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from .context import ConversationMessage, build_messages
from .evaluator import evaluate as evaluate_response
from .planner import Plan, plan as make_plan

if TYPE_CHECKING:
    from ..agent.runtime import Perception
    from .llm import LLMProvider
    from .memory import CoreMemory
    from .server import Stimulus
    from .tools import ToolContext, ToolRegistry

logger = logging.getLogger(__name__)


# ── Enrich result ────────────────────────────────────────────────

@dataclass
class EnrichContext:
    """Everything the Enrich phase gathers. Plan decides what's fetched.

    Beats a naked tuple: adds names, stable field order, default values.
    """
    memories: list[dict] = field(default_factory=list)
    message_matches: list[dict] = field(default_factory=list)
    core_memory: "CoreMemory | None" = None
    history: list[ConversationMessage] = field(default_factory=list)
    image_urls: list[str] = field(default_factory=list)
    recent_posts: list[dict] = field(default_factory=list)
    hist_summary: str = ""


# ── Pipeline orchestration ───────────────────────────────────────

def run_pipeline(
    stimulus: "Stimulus",
    *,
    perceive: Callable[["Stimulus"], "Perception"],
    enrich: Callable[["Stimulus", Plan], EnrichContext],
    build_prompt: Callable[["Stimulus"], str],
    get_llm: Callable[..., "LLMProvider | None"],
    build_tool_ctx: Callable[["Stimulus"], "ToolContext"],
    generate: Callable[..., str],
    deliver: Callable[["Stimulus", str], None],
    log_turn: Callable[["Stimulus", str], None],
    reflect: Callable[["Stimulus", str, "Perception"], None],
    constitution: str,
    tool_registry: "ToolRegistry",
) -> str | None:
    """Run Perceive → Plan → Enrich → Generate → Evaluate → Deliver → Reflect.

    Returns the final response text, or None if the pipeline decided
    (via Plan.intent == "observe") or was unable to run to completion.

    The Plan is derived from the Perception — Psyche ResponseContract +
    Thronglets ambient priors — and then refined by GenerationControls.
    """
    logger.info(
        "pipeline: %s sender=%s post=%s",
        stimulus.kind, stimulus.sender_id, stimulus.post_id,
    )

    # 1. Perceive — constitutive, always returns a Perception
    perception = perceive(stimulus)

    # 2. Plan — zero cost, rule engine driven by Psyche + Thronglets
    plan = make_plan(stimulus, perception)

    # Psyche GenerationControls are hard limits layered over the Plan
    gc = perception.generation_controls
    if gc:
        if gc.max_tokens:
            plan.max_tokens = gc.max_tokens
        if gc.require_confirmation:
            plan.require_confirmation = True

    if plan.intent == "observe":
        logger.debug("Plan: observe, skipping %s", stimulus.kind)
        return None

    # 3. Enrich — Plan-driven context gathering
    ctx = enrich(stimulus, plan)

    # 4. Generate — one LLM call with Plan-constrained context
    prompt = build_prompt(stimulus)
    messages = build_messages(
        constitution=constitution,
        perception=perception,
        plan=plan,
        memories=ctx.memories,
        core_memory=ctx.core_memory,
        history=ctx.history,
        user_message=prompt,
        history_summary=ctx.hist_summary,
        image_urls=ctx.image_urls,
        recent_posts=ctx.recent_posts,
        message_matches=ctx.message_matches,
    )

    # Vision routing: only when user explicitly sends images
    user_has_images = bool(stimulus.image_urls)
    llm = get_llm(stimulus, needs_vision=user_has_images)
    if llm is None:
        return None

    tool_defs = tool_registry.select(plan.tools)
    tool_ctx = build_tool_ctx(stimulus)
    response = generate(llm, stimulus, messages, tool_defs, tool_ctx)

    # 5. Evaluate — rule-based quality gate
    verdict = evaluate_response(response, plan)
    if not verdict.passed:
        logger.info("Evaluator rejected: %s", verdict.issues)
        messages.append({"role": "assistant", "content": response})
        messages.append({"role": "user", "content": verdict.feedback})
        try:
            resp = llm.generate(messages, tools=tool_defs)
            response = resp.text or response  # keep original if regen empty
        except Exception:
            pass  # use original response

    # 6. Deliver + Reflect
    deliver(stimulus, response)
    log_turn(stimulus, response)
    reflect(stimulus, response, perception)

    return response
