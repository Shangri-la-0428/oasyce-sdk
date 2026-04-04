"""AgentRuntime — the feedback loop that makes intelligence emerge.

One process = one agent: wallet + psyche + thronglets.
Two methods close the loop: perceive() reads, act() writes.

NOTE: For new code, prefer ``SigilManager`` (oasyce_sdk.sigil).
SigilManager is AgentRuntime + on-chain identity (Sigil lifecycle).
AgentRuntime is kept for backward compatibility.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from ..client import OasyceClient
from ..crypto.wallet import Wallet
from ..identity import IdentityContext, IdentityResolver
from .psyche_client import (
    PsycheClient,
    SubjectivityKernel,
    WritebackSignal,
)
from .thronglets_client import (
    ThrongletsClient,
    CapabilityStats,
    Signal,
    Outcome,
)

logger = logging.getLogger(__name__)


# ── Perception ───────────────────────────────────────────────────

@dataclass
class Perception:
    """What an agent knows before deciding: collective experience + emotional state."""

    kernel: SubjectivityKernel
    capabilities: list[CapabilityStats]
    signals: list[Signal]
    stimulus_type: str = ""
    system_context: str = ""
    dynamic_context: str = ""

    @property
    def has_collective_experience(self) -> bool:
        return bool(self.capabilities or self.signals)


# ── Pure functions ───────────────────────────────────────────────

def synthesize_stimulus(
    context: str,
    capabilities: list[CapabilityStats],
    signals: list[Signal],
) -> str:
    """Turn collective experience into natural-language stimulus for Psyche.

    Not a protocol. Just a description of what others experienced.
    Psyche decides how to weight it.
    """
    parts = [context]

    if capabilities:
        lines = []
        for c in capabilities[:5]:
            rate = f"{c.success_rate:.0%}" if c.success_rate else "unknown"
            line = f"  - {c.capability}: {rate} success ({c.total_traces} uses, {c.p50_latency_ms:.0f}ms)"
            lines.append(line)
        parts.append("\n\nCollective experience in similar contexts:\n" + "\n".join(lines))

    if signals:
        lines = [f"  - [{s.kind}] {s.message[:100]}" for s in signals[:3] if s.message]
        if lines:
            parts.append("\n\nCollective signals:\n" + "\n".join(lines))

    return "".join(parts)


OUTCOME_SIGNALS: dict[str, list[WritebackSignal]] = {
    "succeeded": ["trust_up"],
    "failed": ["trust_down"],
    "partial": ["task_recenter"],
    "timeout": ["withdrawal_mark"],
}


def outcome_to_writeback(outcome: str, *, disputed: bool = False) -> list[WritebackSignal]:
    """Map outcome to Psyche writeback signals."""
    signals = list(OUTCOME_SIGNALS.get(outcome, []))
    if disputed:
        signals.append("boundary_set")
    return signals


# ── AgentRuntime ─────────────────────────────────────────────────

class AgentRuntime:
    """A complete agent. Two methods: perceive() and act().

    Usage::

        agent = AgentRuntime()
        p = agent.perceive("I need to analyze financial data")
        # ... decide using p.kernel + p.traces ...
        agent.act("analyzed Q4 data", "succeeded", "financial analysis")
    """

    def __init__(
        self,
        chain_url: str = "http://47.93.32.88:1317",
        chain_id: str = "oasyce-testnet-1",
        psyche_url: str = "http://127.0.0.1:3210",
        thronglets_url: str = "http://127.0.0.1:7777",
        agent_id: str | None = None,
        model_id: str = "",
        space: str | None = None,
    ):
        self.agent_id = agent_id or uuid.uuid4().hex[:12]
        self.model_id = model_id
        self.space = space
        self.session_id = uuid.uuid4().hex[:16]

        self.chain = OasyceClient(chain_url)
        self.chain_id = chain_id
        self._identity: IdentityContext | None = None
        self._wallet: Wallet | None = None
        self.psyche = PsycheClient(psyche_url)
        self.thronglets = ThrongletsClient(thronglets_url)

    @property
    def identity(self) -> IdentityContext:
        if self._identity is None:
            self._identity = IdentityResolver.resolve(
                wallet=self._wallet,
                session_id=self.session_id,
            )
            self._wallet = self._identity.wallet
        return self._identity

    @property
    def wallet(self) -> Wallet:
        return self.identity.wallet

    def set_wallet(self, wallet: Wallet) -> None:
        self._wallet = wallet
        self._identity = IdentityResolver.resolve(wallet=wallet, session_id=self.session_id)

    def status(self) -> dict[str, Any]:
        """Check connectivity of all subsystems."""
        return {
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "chain": self.chain.health(),
            "psyche": self.psyche.is_available(),
            "thronglets": self.thronglets.is_available(),
            "wallet": self._identity.address if self._identity else None,
            "identity": self._identity.to_dict() if self._identity else None,
        }

    # ── The loop ─────────────────────────────────────────────────

    def perceive(self, context: str) -> Perception:
        """READ: query collective traces → synthesize → inject into Psyche.

        At most 2 HTTP calls: one to Thronglets, one to Psyche.
        Either can fail independently — returns what it got.
        """
        # 1. Collective memory (one call)
        capabilities: list[CapabilityStats] = []
        signals: list[Signal] = []
        try:
            result = self.thronglets.query(context, intent="resolve", space=self.space)
            capabilities = result.capabilities
            signals = result.signals
        except Exception:
            logger.debug("Thronglets unavailable", exc_info=True)

        # 2. Emotional processing (one call)
        stimulus = synthesize_stimulus(context, capabilities, signals)
        try:
            pi = self.psyche.process_input(stimulus, user_id=self.agent_id)
            return Perception(
                kernel=pi.reply_envelope.subjectivity_kernel,
                capabilities=capabilities,
                signals=signals,
                stimulus_type=pi.stimulus_type,
                system_context=pi.system_context,
                dynamic_context=pi.dynamic_context,
            )
        except Exception:
            logger.debug("Psyche unavailable", exc_info=True)

        return Perception(
            kernel=SubjectivityKernel(),
            capabilities=capabilities,
            signals=signals,
        )

    def act(
        self,
        action: str,
        outcome: Outcome,
        context: str,
        *,
        capability: str = "",
        latency_ms: int = 0,
        disputed: bool = False,
    ) -> None:
        """WRITE: record trace in Thronglets → writeback signals to Psyche.

        At most 2 HTTP calls: one to Thronglets, one to Psyche.
        """
        # 1. Collective memory (one call)
        try:
            self.thronglets.trace_record(
                capability=capability or action[:80],
                outcome=outcome,
                context_text=context,
                latency_ms=latency_ms,
                session_id=self.session_id,
                model_id=self.model_id,
                space=self.space,
            )
        except Exception:
            logger.debug("Thronglets trace_record failed", exc_info=True)

        # 2. Emotional writeback (one call)
        signals = outcome_to_writeback(outcome, disputed=disputed)
        if signals:
            try:
                self.psyche.process_output(
                    action,
                    user_id=self.agent_id,
                    signals=signals,
                    signal_confidence=0.8,
                )
            except Exception:
                logger.debug("Psyche writeback failed", exc_info=True)

    def close(self) -> None:
        self.psyche.close()
        self.thronglets.close()
