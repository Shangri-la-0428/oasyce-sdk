"""Psyche HTTP client for SDK AgentRuntime.

Wraps the Psyche self-state engine REST API so that Python agents can
send stimuli, receive policy modifiers, and feed back writeback signals.

Psyche v11: 4-dimensional self-state (order/flow/boundary/resonance).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import requests

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
    """Machine-readable emotional state (8 dimensions)."""

    vitality: float = 0.5
    tension: float = 0.5
    warmth: float = 0.5
    guard: float = 0.5
    pressure_mode: str = ""
    initiative_mode: str = ""
    expression_mode: str = ""
    social_distance: str = ""

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
        )


@dataclass
class ResponseContract:
    """Behavioral constraints from Psyche."""

    reply_profile: str = "work"
    max_sentences: int = 0
    expression_mode: str = ""
    initiative_mode: str = ""
    emoji_limit: int = 0
    tone_particles: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResponseContract:
        return cls(
            reply_profile=data.get("replyProfile", "work"),
            max_sentences=data.get("maxSentences", 0),
            expression_mode=data.get("expressionMode", ""),
            initiative_mode=data.get("initiativeMode", ""),
            emoji_limit=data.get("emojiLimit", 0),
            tone_particles=data.get("toneParticles", []),
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
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()

    def close(self) -> None:
        self._session.close()

    def is_available(self) -> bool:
        """Check if Psyche server is reachable."""
        try:
            resp = self._session.get(
                f"{self._base_url}/state",
                timeout=self._timeout,
            )
            return resp.status_code == 200
        except (requests.ConnectionError, requests.Timeout):
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

        resp = self._session.post(
            f"{self._base_url}/process-input",
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()

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
    ) -> dict[str, Any]:
        """Notify Psyche of agent's action output.

        Supports writeback signals: the WRITE side of emotional feedback.
        Transaction outcomes map to signals:
          succeeded → trust_up
          failed    → trust_down
          dispute   → boundary_set
        """
        payload: dict[str, Any] = {"text": text}
        if user_id:
            payload["userId"] = user_id
        if signals:
            payload["signals"] = signals
        if signal_confidence is not None:
            payload["signalConfidence"] = signal_confidence

        resp = self._session.post(
            f"{self._base_url}/process-output",
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ── State queries ─────────────────────────────────────────────

    def get_state(self) -> PsycheSnapshot:
        """Get full Psyche state snapshot."""
        resp = self._session.get(
            f"{self._base_url}/state",
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()

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
        resp = self._session.get(
            f"{self._base_url}/status-summary",
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.text
