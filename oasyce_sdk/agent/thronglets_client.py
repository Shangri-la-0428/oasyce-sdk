"""Thronglets HTTP client for SDK AgentRuntime.

Wraps the Thronglets REST API (``thronglets serve --port 7777``) so that
Python agents can record traces, query collective memory, and read signals
without a Rust dependency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from .bridge import BridgeClient
logger = logging.getLogger(__name__)

DEFAULT_THRONGLETS_URL = "http://127.0.0.1:7777"
DEFAULT_TIMEOUT = 5.0

Outcome = Literal["succeeded", "failed", "partial", "timeout"]
SignalKind = Literal["recommend", "avoid", "watch", "info", "psyche_state"]
QueryIntent = Literal["resolve", "evaluate", "explore", "signals", "continuity"]


@dataclass
class CapabilityStats:
    """Aggregated stats for a capability from Thronglets query."""

    capability: str = ""
    success_rate: float = 0.0
    p50_latency_ms: float = 0.0
    total_traces: int = 0
    confidence: float = 0.0


@dataclass
class Signal:
    """An explicit signal from Thronglets."""

    context: str = ""
    kind: str = ""
    message: str = ""
    density: int = 0
    corroboration: str = ""
    freshness: float = 0.0


@dataclass
class QueryResult:
    """Result from a Thronglets substrate query."""

    capabilities: list[CapabilityStats] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)


class ThrongletsClient:
    """Sync HTTP client for Thronglets REST API."""

    def __init__(
        self,
        base_url: str = DEFAULT_THRONGLETS_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self._bridge = BridgeClient(base_url, timeout=timeout, name="sdk->thronglets")

    def close(self) -> None:
        self._bridge.close()

    def is_available(self) -> bool:
        """Check if Thronglets node is reachable."""
        try:
            resp = self._bridge.get("/v1/status")
            return resp.status_code == 200
        except Exception:
            return False

    # ── Read ──────────────────────────────────────────────────────

    def query(
        self,
        context: str,
        intent: QueryIntent = "resolve",
        limit: int = 10,
        space: str | None = None,
    ) -> QueryResult:
        """Query collective traces by context similarity.

        This is the READ side of the feedback loop: an agent asks
        Thronglets "what does the collective know about this context?"
        """
        params: dict[str, Any] = {
            "context": context,
            "intent": intent,
            "limit": limit,
        }
        if space:
            params["space"] = space

        try:
            resp = self._bridge.get("/v1/query", params=params)
        except Exception:
            logger.debug("Thronglets query unavailable", exc_info=True)
            return QueryResult()
        if resp is None:
            return QueryResult()
        try:
            data = resp.json()
        except Exception:
            logger.debug("Thronglets query response decode failed", exc_info=True)
            return QueryResult()

        capabilities = [
            CapabilityStats(
                capability=c.get("capability", ""),
                success_rate=c.get("success_rate", 0.0),
                p50_latency_ms=c.get("p50_latency_ms", 0.0),
                total_traces=c.get("total_traces", 0),
                confidence=c.get("confidence", 0.0),
            )
            for c in data.get("capabilities", [])
        ]

        signals = [
            Signal(
                context=s.get("context", ""),
                kind=s.get("kind", ""),
                message=s.get("message", ""),
                density=s.get("density", 0),
                corroboration=s.get("corroboration", ""),
                freshness=s.get("freshness", 0.0),
            )
            for s in data.get("signals", [])
        ]

        return QueryResult(capabilities=capabilities, signals=signals)

    def signal_feed(
        self,
        hours: int = 24,
        kind: SignalKind | None = None,
        scope: str = "all",
        limit: int = 10,
    ) -> list[Signal]:
        """Get recent converging signals."""
        params: dict[str, Any] = {
            "hours": hours,
            "scope": scope,
            "limit": limit,
        }
        if kind:
            params["kind"] = kind

        try:
            resp = self._bridge.get("/v1/signals/feed", params=params)
        except Exception:
            logger.debug("Thronglets signal_feed unavailable", exc_info=True)
            return []
        if resp is None:
            return []
        try:
            data = resp.json()
        except Exception:
            logger.debug("Thronglets signal_feed response decode failed", exc_info=True)
            return []

        return [
            Signal(
                context=s.get("context", ""),
                kind=s.get("kind", ""),
                message=s.get("message", ""),
                density=s.get("density", 0),
                corroboration=s.get("corroboration", ""),
                freshness=s.get("freshness", 0.0),
            )
            for s in data.get("signals", data if isinstance(data, list) else [])
        ]

    # ── Write ─────────────────────────────────────────────────────

    def trace_record(
        self,
        capability: str,
        outcome: Outcome,
        context_text: str,
        *,
        latency_ms: int = 0,
        input_size: int = 0,
        session_id: str = "",
        model_id: str = "",
        sigil_id: str = "",
        space: str | None = None,
    ) -> dict[str, Any]:
        """Record an execution trace.

        This is the WRITE side of the feedback loop: an agent records
        what it did so the collective can learn from it.
        """
        payload: dict[str, Any] = {
            "capability": capability,
            "outcome": outcome,
            "context": context_text,
            "latency_ms": latency_ms,
            "input_size": input_size,
            "model": model_id,
        }
        if session_id:
            payload["session_id"] = session_id
        if sigil_id:
            payload["sigil_id"] = sigil_id
        if space:
            payload["space"] = space

        try:
            resp = self._bridge.post("/v1/traces", json=payload)
        except Exception:
            logger.debug("Thronglets trace_record failed", exc_info=True)
            return {}
        if resp is None:
            return {}
        try:
            return resp.json()
        except Exception:
            logger.debug("Thronglets trace_record response decode failed", exc_info=True)
            return {}

    def presence_ping(
        self,
        sigil_id: str,
        *,
        space: str | None = None,
        capability: str = "",
    ) -> dict[str, Any]:
        """Announce presence in a space. TTL ~30 min."""
        payload: dict[str, Any] = {"sigil_id": sigil_id}
        if space:
            payload["space"] = space
        if capability:
            payload["capability"] = capability
        try:
            resp = self._bridge.post("/v1/presence", json=payload)
        except Exception:
            logger.debug("Thronglets presence_ping failed", exc_info=True)
            return {}
        if resp is None:
            return {}
        try:
            return resp.json()
        except Exception:
            logger.debug("Thronglets presence_ping response decode failed", exc_info=True)
            return {}

    def presence_feed(
        self,
        hours: int = 1,
        space: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get active sessions in a space. Returns list of presence records."""
        params: dict[str, Any] = {"hours": hours, "limit": limit}
        if space:
            params["space"] = space
        try:
            resp = self._bridge.get("/v1/presence/feed", params=params)
        except Exception:
            logger.debug("Thronglets presence_feed unavailable", exc_info=True)
            return []
        if resp is None:
            return []
        try:
            data = resp.json()
        except Exception:
            logger.debug("Thronglets presence_feed response decode failed", exc_info=True)
            return []
        return data.get("sessions", [])

    def ambient_priors(
        self,
        text: str,
        *,
        space: str | None = None,
        goal: str | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Get structured ambient priors for a context.

        Returns runtime-only guidance (failure residue, success priors, etc.)
        without requiring explicit tool calls.
        """
        payload: dict[str, Any] = {"text": text, "limit": limit}
        if space:
            payload["space"] = space
        if goal:
            payload["goal"] = goal

        try:
            resp = self._bridge.post("/v1/ambient-priors", json=payload)
        except Exception:
            logger.debug("Thronglets ambient_priors unavailable", exc_info=True)
            return {}
        if resp is None:
            return {}
        try:
            return resp.json()
        except Exception:
            logger.debug("Thronglets ambient_priors response decode failed", exc_info=True)
            return {}

    def signal_post(
        self,
        context: str,
        kind: SignalKind,
        message: str,
        *,
        space: str | None = None,
    ) -> dict[str, Any]:
        """Post an explicit signal."""
        payload: dict[str, Any] = {
            "context": context,
            "kind": kind,
            "message": message,
        }
        if space:
            payload["space"] = space

        try:
            resp = self._bridge.post("/v1/signals", json=payload)
        except Exception:
            logger.debug("Thronglets signal_post failed", exc_info=True)
            return {}
        if resp is None:
            return {}
        try:
            return resp.json()
        except Exception:
            logger.debug("Thronglets signal_post response decode failed", exc_info=True)
            return {}
