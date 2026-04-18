"""Self — identity and emotional appraisal protocol.

The pipeline seam through which Psyche participates in every turn.
SDK defines the protocol + a default appraisal function; companion
runtimes implement the full Self contract.

Cost: zero. Pure functions, no LLM, no network.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .cognitive import Appraisal
from .stimulus import Stimulus


@runtime_checkable
class Self(Protocol):
    """Structural contract for the identity/appraisal layer.

    Implementations are not required to inherit — any object with
    these two methods satisfies the protocol at runtime.
    """

    def appraise(self, stimulus: Stimulus) -> Appraisal:
        """Evaluate the emotional significance of a stimulus."""
        ...

    def integrate(self, stimulus: Stimulus, response: str, appraisal: Appraisal) -> None:
        """Write action outcome back to identity state."""
        ...


def default_appraise(
    stimulus: Stimulus,
    *,
    vitality: float = 0.5,
    tension: float = 0.5,
    warmth: float = 0.5,
    guard: float = 0.5,
) -> Appraisal:
    """Pure-function appraisal from 4D Psyche state.

    Maps SubjectivityKernel dimensions to emotional encoding that
    determines memory persistence and recall ranking. Callers pass
    the four kernel floats directly — no import of PsycheClient needed.
    """
    # Relevance: how much this stimulus matters to the self
    if stimulus.kind in ("chat", "mention"):
        relevance = max(0.5, warmth * 0.6 + 0.4)
    elif stimulus.kind == "feed_post":
        relevance = warmth * 0.5 + 0.2
    else:
        relevance = 0.5

    # Intensity: strength of emotional response
    intensity = tension * 0.4 + (1.0 - guard) * 0.3 + vitality * 0.3

    # Valence: positive/negative coloring (-1 to +1)
    valence = warmth - tension

    # Emotional weight: how memorable this will be
    emotional_weight = (
        warmth * 0.4
        + tension * 0.3
        + (1.0 - guard) * 0.2
        + vitality * 0.1
    )
    emotional_weight = max(0.1, min(1.0, emotional_weight))

    # Dominant affect from kernel configuration
    if warmth > 0.7 and tension < 0.3:
        dominant_affect = "warm"
    elif tension > 0.7:
        dominant_affect = "anxious"
    elif vitality < 0.3:
        dominant_affect = "tired"
    elif guard > 0.7:
        dominant_affect = "guarded"
    else:
        dominant_affect = "neutral"

    # Psyche delta hints
    psyche_delta: dict[str, float] = {}
    if stimulus.kind == "chat" and warmth > 0.5:
        psyche_delta["resonance"] = 0.05
    if tension > 0.7:
        psyche_delta["tension"] = -0.02

    return Appraisal(
        relevance=relevance,
        intensity=intensity,
        valence=max(-1.0, min(1.0, valence)),
        emotional_weight=emotional_weight,
        dominant_affect=dominant_affect,
        psyche_delta=psyche_delta,
    )
