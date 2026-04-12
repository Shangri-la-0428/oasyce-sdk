"""Psyche HTTP client for SDK AgentRuntime.

Wraps the Psyche self-state engine REST API so that Python agents can
send stimuli, receive policy modifiers, and feed back writeback signals.

Psyche v11: 4-dimensional self-state (order/flow/boundary/resonance).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from .bridge import BridgeClient

logger = logging.getLogger(__name__)

DEFAULT_PSYCHE_URL = "http://127.0.0.1:3210"
DEFAULT_TIMEOUT = 5.0

WritebackSignal = Literal[
    "trust_up",
    "trust_down",
    "boundary_set",
    "boundary_soften",
    "repair_attempt",
    "repair_landed",
    "closeness_invite",
    "withdrawal_mark",
    "self_assertion",
    "task_recenter",
]


@dataclass
class SubjectivityKernel:
    """Machine-readable subjective state."""

    vitality: float = 0.5
    tension: float = 0.5
    warmth: float = 0.5
    guard: float = 0.5
    pressure_mode: str = ""
    initiative_mode: str = ""
    expression_mode: str = ""
    social_distance: str = ""
    boundary_mode: str = ""
    attention_anchor: str = ""
    dominant_need: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubjectivityKernel:
        return cls(
            vitality=data.get("vitality", 0.5),
            tension=data.get("tension", 0.5),
            warmth=data.get("warmth", 0.5),
            guard=data.get("guard", 0.5),
            pressure_mode=data.get("pressureMode", ""),
            initiative_mode=data.get("initiativeMode", ""),
            expression_mode=data.get("expressionMode", ""),
            social_distance=data.get("socialDistance", ""),
            boundary_mode=data.get("boundaryMode", ""),
            attention_anchor=data.get("attentionAnchor", ""),
            dominant_need=data.get("dominantNeed"),
        )


@dataclass
class GenerationControls:
    """Host-executable generation constraints from Psyche."""

    max_tokens: int | None = None
    require_confirmation: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GenerationControls:
        return cls(
            max_tokens=data.get("maxTokens"),
            require_confirmation=data.get("requireConfirmation", False),
        )


@dataclass
class ResponseContract:
    """Behavioral constraints from Psyche."""

    reply_profile: str = "work"
    max_sentences: int = 0
    max_chars: int | None = None
    expression_mode: str = ""
    initiative_mode: str = ""
    emoji_limit: int = 0
    tone_style: str = ""
    boundary_mode: str = ""
    authenticity_mode: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResponseContract:
        # toneParticles changed from list[str] to string enum in Psyche v11.8
        raw_tone = data.get("toneParticles", "")
        if isinstance(raw_tone, list):
            tone = ", ".join(raw_tone) if raw_tone else ""
        else:
            tone = str(raw_tone) if raw_tone else ""

        return cls(
            reply_profile=data.get("replyProfile", "work"),
            max_sentences=data.get("maxSentences", 0),
            max_chars=data.get("maxChars"),
            expression_mode=data.get("expressionMode", ""),
            initiative_mode=data.get("initiativeMode", ""),
            emoji_limit=data.get("emojiLimit", 0),
            tone_style=tone,
            boundary_mode=data.get("boundaryMode", ""),
            authenticity_mode=data.get("authenticityMode", ""),
        )


@dataclass
class ReplyEnvelope:
    """The canonical host-facing control surface from Psyche."""

    subjectivity_kernel: SubjectivityKernel = field(
        default_factory=SubjectivityKernel
    )
    response_contract: ResponseContract = field(
        default_factory=ResponseContract
    )
    generation_controls: GenerationControls = field(
        default_factory=GenerationControls
    )
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReplyEnvelope:
        return cls(
            subjectivity_kernel=SubjectivityKernel.from_dict(
                data.get("subjectivityKernel", {})
            ),
            response_contract=ResponseContract.from_dict(
                data.get("responseContract", {})
            ),
            generation_controls=GenerationControls.from_dict(
                data.get("generationControls", {})
            ),
            raw=data,
        )


@dataclass
class PsycheOverlay:
    """Semantic-stable effect signals derived from 4D self-state (v11.4+).

    These are the "hormones" Psyche secretes — broadcast signals any
    external system can consume. Pure linear projection from dimension
    deviations, not a consumer-specific API.

    All values [-1, 1]. 0 = at baseline (no effect).

    Projection matrix (each signal reads exactly 2 dimensions):
        arousal       = -0.4×Δorder + 0.6×Δflow
        valence       =  0.5×Δorder + 0.5×Δresonance
        agency        =  0.4×Δflow  + 0.6×Δboundary
        vulnerability = -0.4×Δorder - 0.6×Δboundary
    """

    arousal: float = 0.0
    valence: float = 0.0
    agency: float = 0.0
    vulnerability: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PsycheOverlay:
        return cls(
            arousal=data.get("arousal", 0.0),
            valence=data.get("valence", 0.0),
            agency=data.get("agency", 0.0),
            vulnerability=data.get("vulnerability", 0.0),
        )

    @classmethod
    def compute(cls, current: SelfState, baseline: SelfState) -> PsycheOverlay:
        """Compute overlay locally from current and baseline self-state.

        Pure function — mirrors the TypeScript computeOverlay() exactly.
        Use this when Psyche server is unavailable or for offline agents.
        """
        rng = 50.0
        d_o = (current.order - baseline.order) / rng
        d_f = (current.flow - baseline.flow) / rng
        d_b = (current.boundary - baseline.boundary) / rng
        d_r = (current.resonance - baseline.resonance) / rng

        def clamp(v: float) -> float:
            return max(-1.0, min(1.0, v)) or 0.0

        return cls(
            arousal=clamp(-0.4 * d_o + 0.6 * d_f),
            valence=clamp(0.5 * d_o + 0.5 * d_r),
            agency=clamp(0.4 * d_f + 0.6 * d_b),
            vulnerability=clamp(-0.4 * d_o - 0.6 * d_b),
        )


@dataclass
class ProcessInputResult:
    """Result from Psyche's processInput endpoint."""

    system_context: str = ""
    dynamic_context: str = ""
    stimulus_type: str = ""
    stimulus_confidence: float = 0.0
    reply_envelope: ReplyEnvelope = field(default_factory=ReplyEnvelope)
    overlay: PsycheOverlay = field(default_factory=PsycheOverlay)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SelfState:
    """4-dimensional self-state (Psyche v11).

    | Dimension   | Meaning                          |
    |-------------|----------------------------------|
    | order       | Internal coherence (entropy↓)    |
    | flow        | Exchange with environment        |
    | boundary    | Self/non-self distinction        |
    | resonance   | Attunement with interlocutor     |
    """

    order: float = 50.0
    flow: float = 50.0
    boundary: float = 50.0
    resonance: float = 50.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SelfState:
        return cls(
            order=data.get("order", 50.0),
            flow=data.get("flow", 50.0),
            boundary=data.get("boundary", 50.0),
            resonance=data.get("resonance", 50.0),
        )


@dataclass
class PsycheSnapshot:
    """Full Psyche state at a point in time."""

    self_state: SelfState = field(default_factory=SelfState)
    baseline: SelfState = field(default_factory=SelfState)
    overlay: PsycheOverlay = field(default_factory=PsycheOverlay)
    dominant_emotion: str = ""
    drives: dict[str, float] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


class PsycheClient:
    """Sync HTTP client for Psyche emotional engine."""

    def __init__(
        self,
        base_url: str = DEFAULT_PSYCHE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self._bridge = BridgeClient(base_url, timeout=timeout, name="sdk->psyche")

    def close(self) -> None:
        self._bridge.close()

    def is_available(self) -> bool:
        """Check if Psyche server is reachable."""
        try:
            resp = self._bridge.get("/state")
            return resp.status_code == 200
        except Exception:
            return False

    # ── Core cycle ────────────────────────────────────────────────

    def process_input(
        self,
        text: str,
        user_id: str | None = None,
    ) -> ProcessInputResult:
        """Send stimulus text, get reply envelope + classification.

        This is the integration point where collective experience
        (synthesized as stimulus text) enters Psyche's processing.
        """
        payload: dict[str, Any] = {"text": text}
        if user_id:
            payload["userId"] = user_id

        try:
            resp = self._bridge.post("/process-input", json=payload)
        except Exception:
            logger.debug("Psyche process_input unavailable", exc_info=True)
            return ProcessInputResult()
        if resp is None:
            return ProcessInputResult()
        try:
            data = resp.json()
        except Exception:
            logger.debug("Psyche process_input response decode failed", exc_info=True)
            return ProcessInputResult()

        # Stimulus is a string or dict, confidence is top-level
        stimulus_raw = data.get("stimulus")
        if isinstance(stimulus_raw, dict):
            stim_type = stimulus_raw.get("type", "")
            stim_conf = stimulus_raw.get("confidence", 0.0)
        else:
            stim_type = stimulus_raw or ""
            stim_conf = data.get("stimulusConfidence", 0.0)

        envelope = ReplyEnvelope.from_dict(data.get("replyEnvelope", {}))
        overlay = PsycheOverlay.from_dict(data.get("overlay", {}))

        return ProcessInputResult(
            system_context=data.get("systemContext", ""),
            dynamic_context=data.get("dynamicContext", ""),
            stimulus_type=stim_type,
            stimulus_confidence=stim_conf,
            reply_envelope=envelope,
            overlay=overlay,
            raw=data,
        )

    def process_output(
        self,
        text: str,
        user_id: str | None = None,
        signals: list[WritebackSignal] | None = None,
        signal_confidence: float | None = None,
        outcome_alignment: str | None = None,
        outcome_effort: float | None = None,
    ) -> dict[str, Any]:
        """Notify Psyche of agent's action output.

        Supports two feedback paths:
        1. Writeback signals (legacy): trust_up, trust_down, etc.
        2. LoopOutcome (v11.8): structured φ-loop feedback.
           alignment: "aligned" | "diverged" | "partial"
           effort: 0-1, modulates flow dimension
        """
        payload: dict[str, Any] = {"text": text}
        if user_id:
            payload["userId"] = user_id
        if signals:
            payload["signals"] = signals
        if signal_confidence is not None:
            payload["signalConfidence"] = signal_confidence
        if outcome_alignment:
            outcome: dict[str, Any] = {"alignment": outcome_alignment}
            if outcome_effort is not None:
                outcome["effort"] = outcome_effort
            payload["outcome"] = outcome

        try:
            resp = self._bridge.post("/process-output", json=payload)
        except Exception:
            logger.debug("Psyche process_output unavailable", exc_info=True)
            return {}
        if resp is None:
            return {}
        try:
            return resp.json()
        except Exception:
            logger.debug("Psyche process_output response decode failed", exc_info=True)
            return {}

    # ── State queries ─────────────────────────────────────────────

    def get_state(self) -> PsycheSnapshot:
        """Get full Psyche state snapshot."""
        try:
            resp = self._bridge.get("/state")
        except Exception:
            logger.debug("Psyche get_state unavailable", exc_info=True)
            return PsycheSnapshot()
        if resp is None:
            return PsycheSnapshot()
        try:
            data = resp.json()
        except Exception:
            logger.debug("Psyche get_state response decode failed", exc_info=True)
            return PsycheSnapshot()

        self_state = SelfState.from_dict(data.get("current", {}))
        baseline = SelfState.from_dict(data.get("baseline", {}))
        overlay = PsycheOverlay.from_dict(data.get("overlay", {}))
        drives_raw = data.get("drives", {})
        dominant = data.get("dominantEmotion", "")

        return PsycheSnapshot(
            self_state=self_state,
            baseline=baseline,
            overlay=overlay,
            dominant_emotion=dominant,
            drives=drives_raw,
            raw=data,
        )

    def get_status_summary(self) -> str:
        """Get human-readable status summary."""
        try:
            resp = self._bridge.get("/status-summary")
        except Exception:
            logger.debug("Psyche status_summary unavailable", exc_info=True)
            return ""
        if resp is None:
            return ""
        return resp.text
