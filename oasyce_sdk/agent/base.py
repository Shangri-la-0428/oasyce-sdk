"""Agent — transport-agnostic PGE runtime.

``Agent`` is the symmetric twin of ``SigilManager``:

  SigilManager = Identity × ChainSigner × Substrate (Psyche + Thronglets)
  Agent        = Identity × Channel × LLM × Tools + PGE pipeline

Both are thin composition over injected dependencies. Neither knows
about concrete backends — ``SigilManager`` treats wallets and HSMs
alike (via the ``ChainSigner`` Protocol), and ``Agent`` treats App
backends, Discord sockets, and stdout alike (via the ``Channel``
Protocol).

Why this seam matters:

    Samantha    = Agent + AppChannel      + Joi constitution     + Samantha tools
    OpenClaw    = Agent + StdoutChannel   + dev constitution     + dev tools
    DiscordBot  = Agent + DiscordChannel  + persona              + Discord tools

    Each deployment is a thin subclass: provide the Channel, the
    constitution, the tool set, and any hook overrides. The pipeline,
    PGE loop, tool-calling loop, and observability are all shared.

Overridable hooks (all prefixed with ``_``):

  ``_perceive``       : stimulus → Perception (default: identity.perceive)
  ``_enrich``         : Plan-driven context gathering (default: images only)
  ``_build_prompt``   : format the stimulus for the LLM (default: raw content)
  ``_get_llm``        : pick an LLM slot for this stimulus (default: registry)
  ``_build_tool_ctx`` : assemble the ToolContext (default: generic fields)
  ``_generate``       : LLM call with tool loop (default: 3-round loop)
  ``_inject_tool_defaults`` : inject stimulus fields into tool calls (default: no-op)
  ``_log_turn``       : persistent verbatim logging (default: no-op)
  ``_reflect``        : post-turn Psyche/Thronglets writeback (default: identity.act)

Delivery is **not** a hook — it always goes through
``self.channel.deliver``. That is the whole point of the Channel
Protocol: keep the output sink narrow, keep it injected, and keep
transport concerns out of the Agent body.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from .channel import Channel
from .pipeline import EnrichContext, run_pipeline
from .planner import Plan
from .stimulus import Stimulus
from .tools import ToolContext, ToolRegistry

if TYPE_CHECKING:
    from ..sigil import SigilManager
    from .llm import LLMProvider, ModelRegistry, ToolCall
    from .runtime import Perception

logger = logging.getLogger(__name__)


class Agent:
    """Transport-agnostic PGE runtime.

    Composition (all injected via ``__init__``):

      identity     -- ``SigilManager`` (on-chain Sigil + Psyche + Thronglets)
      channel      -- ``Channel`` Protocol implementation (output sink)
      registry     -- ``ModelRegistry`` (LLM router)
      tools        -- ``ToolRegistry`` (tool dispatch)
      constitution -- system prompt string

    Lifecycle:

      1. ``submit(stimulus)`` → bounded ThreadPoolExecutor → ``_safe_process``
      2. ``_safe_process`` → ``process`` with top-level exception logging
      3. ``process`` → ``run_pipeline`` with all hooks bound to ``self.*``
      4. ``close()`` → shutdown executor (subclasses extend to release state)

    Subclasses override hooks, never the pipeline body.
    """

    DEFAULT_MAX_WORKERS = 4
    TOOL_LOOP_MAX_ROUNDS = 3

    def __init__(
        self,
        *,
        identity: "SigilManager",
        channel: Channel,
        registry: "ModelRegistry",
        tools: ToolRegistry,
        constitution: str,
        max_workers: int | None = None,
        thread_name_prefix: str = "agent",
    ) -> None:
        self.identity = identity
        self.channel = channel
        self._registry = registry
        self._tools = tools
        self.constitution = constitution
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers or self.DEFAULT_MAX_WORKERS,
            thread_name_prefix=thread_name_prefix,
        )

    # ── Public API ──────────────────────────────────────────────

    def submit(self, stimulus: Stimulus) -> None:
        """Dispatch a stimulus for async processing. Bounded pool.

        Returns immediately; the pipeline runs on a worker thread.
        Use ``process`` directly for synchronous execution (tests,
        proactive loops).
        """
        self._executor.submit(self._safe_process, stimulus)

    def process(self, stimulus: Stimulus) -> str | None:
        """Run one stimulus through the PGE pipeline.

        All phases are delegated to ``run_pipeline``; this method is
        purely the wiring from ``self.*`` hooks to the pipeline
        signature. Subclasses override hooks, not this method.
        """
        return run_pipeline(
            stimulus,
            perceive=self._perceive,
            enrich=self._enrich,
            build_prompt=self._build_prompt,
            get_llm=self._get_llm,
            build_tool_ctx=self._build_tool_ctx,
            generate=self._generate,
            deliver=self._deliver,
            log_turn=self._log_turn,
            reflect=self._reflect,
            constitution=self.constitution,
            tool_registry=self._tools,
        )

    def close(self) -> None:
        """Shut down the executor. Subclasses extend to close sessions."""
        self._executor.shutdown(wait=False)

    # ── Internals ───────────────────────────────────────────────

    def _safe_process(self, stimulus: Stimulus) -> None:
        """``process`` wrapped in a top-level catch so one bad stimulus
        never kills the worker pool."""
        try:
            self.process(stimulus)
        except Exception:
            logger.error("process failed: %s", stimulus.kind, exc_info=True)

    # ── Pipeline hooks (overridable) ────────────────────────────

    def _perceive(self, stimulus: Stimulus) -> "Perception":
        """Stimulus → Perception. Constitutive: always returns.

        Default delegates to ``identity.perceive(context)``, which
        itself is constitutive (baseline kernel when Psyche/Thronglets
        are unreachable). Subclasses override to add ambient priors,
        richer context strings, or deployment-specific signals.
        """
        context = f"{stimulus.kind}: {stimulus.content[:200]}"
        return self.identity.perceive(context)

    def _enrich(self, stimulus: Stimulus, plan: Plan) -> EnrichContext:
        """Gather per-stimulus context. Default: images only.

        Deployments with memory, history, or social data override this
        to populate EnrichContext fields based on what ``plan`` requests.
        The ``plan`` is already Psyche + Thronglets-driven, so this
        method only decides *how* to satisfy it, not *what* to fetch.
        """
        return EnrichContext(image_urls=list(stimulus.image_urls))

    def _build_prompt(self, stimulus: Stimulus) -> str:
        """Format the stimulus for the LLM. Default: raw content.

        Deployments with structured event kinds (comments, mentions,
        feed posts, etc.) override to inject metadata and hints.
        """
        return stimulus.content

    def _get_llm(
        self,
        stimulus: Stimulus,
        *,
        needs_vision: bool = False,
    ) -> "LLMProvider":
        """Pick an LLM for this stimulus. Default: registry routing.

        Deployments with per-user LLM override (e.g. a BYO-key flow)
        override to check session-specific config first.
        """
        return self._registry.get(needs_vision=needs_vision)

    def _build_tool_ctx(self, stimulus: Stimulus) -> ToolContext:
        """Build the ToolContext for this stimulus. Default: generic.

        Deployments with additional tool dependencies (e.g. an App
        client) override to populate their ToolContext subclass with
        deployment-specific fields.
        """
        return ToolContext(
            chain_client=self.identity.client,
            chain_address=self.identity.address,
        )

    def _generate(
        self,
        llm: "LLMProvider",
        stimulus: Stimulus,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_ctx: ToolContext,
    ) -> str:
        """Generator phase: LLM call with tool loop.

        Default behaviour:

          1. Call LLM with ``messages`` + ``tools``
          2. If no tool calls, return the text
          3. Else execute each tool call via ``self._tools.execute``,
             append results as messages, and loop
          4. Bail after ``TOOL_LOOP_MAX_ROUNDS`` iterations

        On LLM exception while images are in the prompt, retry once
        text-only — a common OpenAI-compat failure mode where the
        image format doesn't match the model's expected MIME. If the
        retry also fails, the exception propagates.
        """
        resp = None
        for _ in range(self.TOOL_LOOP_MAX_ROUNDS):
            try:
                resp = llm.generate(messages, tools=tools)
            except Exception as e:
                has_images = any(
                    isinstance(m.get("content"), list) for m in messages
                )
                if has_images:
                    logger.warning(
                        "LLM call failed with images, retrying text-only: %s", e,
                    )
                    messages = _strip_images(messages)
                    resp = llm.generate(messages, tools=tools)
                else:
                    raise
            if not resp.tool_calls:
                return resp.text
            for tc in resp.tool_calls:
                self._inject_tool_defaults(tc, stimulus)
                result = self._tools.execute(tc.name, tc.arguments, tool_ctx)
                logger.info("%s tool %s: %s", stimulus.kind, tc.name, result)
                messages.append({
                    "role": "assistant",
                    "content": f"[Calling {tc.name}]",
                })
                messages.append({
                    "role": "user",
                    "content": f"[Tool result for {tc.name}]: {result}",
                })
        return resp.text if resp else ""

    def _inject_tool_defaults(
        self,
        tool_call: "ToolCall",
        stimulus: Stimulus,
    ) -> None:
        """Inject stimulus fields into tool call arguments where absent.

        Default: no-op. Deployments with structured stimuli (comments,
        mentions) override to wire ``post_id``, ``comment_id``,
        ``reply_to_user_id``, etc. into every tool call automatically,
        so the LLM doesn't have to re-echo them.
        """
        return

    def _deliver(self, stimulus: Stimulus, response: str) -> None:
        """Route the response through the injected ``channel``.

        This is **the** seam. Never touch the transport here — all
        output goes through ``self.channel.deliver``, which is the
        narrow Protocol defined in ``agent.channel``. Subclasses
        should almost never override this; override the Channel
        implementation instead.
        """
        self.channel.deliver(stimulus, response)

    def _log_turn(self, stimulus: Stimulus, response: str) -> None:
        """Persist the turn to verbatim storage. Default: no-op.

        Deployments with a per-user message log (the MemPalace insight)
        override to append both sides of the exchange.
        """
        return

    def _reflect(
        self,
        stimulus: Stimulus,
        response: str,
        perception: "Perception",
    ) -> None:
        """Post-turn writeback: Psyche signals + Thronglets trace.

        Default uses ``identity.act`` so the Loop closes properly
        (collective experience recorded, Psyche receives signals).
        Failures are swallowed — reflection must never sit on the
        critical path, since the response has already been delivered.
        """
        if not response:
            return
        try:
            self.identity.act(
                response[:80],
                "succeeded",
                stimulus.content[:200],
                capability=stimulus.kind,
            )
        except Exception:
            logger.debug("reflect failed", exc_info=True)


# ── Helpers ────────────────────────────────────────────────────

def _strip_images(messages: list[dict]) -> list[dict]:
    """Strip image blocks from messages for text-only retry."""
    result: list[dict] = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            text = next(
                (
                    b["text"] for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ),
                str(content),
            )
            result.append({**m, "content": text})
        else:
            result.append(m)
    return result
