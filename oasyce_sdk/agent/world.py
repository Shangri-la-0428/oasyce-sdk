"""World — unified delivery abstraction for all cognitive modes.

Before World, delivery was scattered across multiple code paths:
  REACTIVE  → channel.deliver
  PROACTIVE → deliver_proactive (with SILENCE filtering)
  OBSERVING → pipeline short-circuit (plan.intent == "observe")
  REFLECTING → MaintenanceStream (never enters pipeline)

World unifies these into a single ``act(mode, stimulus, response, plan)``
method that every pipeline invocation routes through. Deployments implement
the Protocol to define their own mode-aware delivery logic.

DefaultWorld wraps a Channel for basic REACTIVE delivery — the SDK
baseline. Samantha's CompanionWorld adds PROACTIVE intention routing,
SILENCE filtering, and social surface dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .cognitive import CognitiveMode

if TYPE_CHECKING:
    from .channel import Channel
    from .planner import Plan
    from .stimulus import Stimulus


@dataclass
class Outcome:
    """Result of a World.act call."""
    success: bool
    detail: str = ""


@runtime_checkable
class World(Protocol):
    """How the agent acts on the world — mode-aware delivery."""

    def act(
        self,
        mode: CognitiveMode,
        stimulus: "Stimulus",
        response: str | None,
        plan: "Plan",
    ) -> Outcome: ...


class DefaultWorld:
    """Wraps a Channel for basic mode-aware delivery.

    REACTIVE with a response → channel.deliver.
    All other modes → Outcome(success=True) with no side effect.
    """

    def __init__(self, channel: "Channel") -> None:
        self._channel = channel

    def act(
        self,
        mode: CognitiveMode,
        stimulus: "Stimulus",
        response: str | None,
        plan: "Plan",
    ) -> Outcome:
        if mode == CognitiveMode.REACTIVE and response:
            self._channel.deliver(stimulus, response)
            return Outcome(success=True, detail="delivered")
        return Outcome(success=True)
