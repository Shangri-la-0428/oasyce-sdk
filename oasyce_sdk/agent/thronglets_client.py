"""Thronglets HTTP client for SDK AgentRuntime.

Wraps the Thronglets REST API (``thronglets serve --port 7777``) so that
Python agents can record traces, query collective memory, and read signals
without a Rust dependency.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

import requests

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


def _is_loopback_url(url: str) -> bool:
    host = urlparse(url).hostname
    return host in {"127.0.0.1", "localhost", "::1"}


class ThrongletsClient:
    """Sync HTTP client for Thronglets REST API."""

    def __init__(
        self,
        base_url: str = DEFAULT_THRONGLETS_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        if _is_loopback_url(self._base_url):
            self._session.trust_env = False

    def close(self) -> None:
        self._session.close()

    def is_available(self) -> bool:
        """Check if Thronglets node is reachable."""
        try:
            resp = self._session.get(
                f"{self._base_url}/v1/status",
                timeout=self._timeout,
            )
            return resp.status_code == 200
        except (requests.ConnectionError, requests.Timeout):
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

        resp = self._session.get(
            f"{self._base_url}/v1/query",
            params=params,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()

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

        resp = self._session.get(
            f"{self._base_url}/v1/signals/feed",
            params=params,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()

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

        resp = self._session.post(
            f"{self._base_url}/v1/traces",
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

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
        resp = self._session.post(
            f"{self._base_url}/v1/presence",
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

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
        resp = self._session.get(
            f"{self._base_url}/v1/presence/feed",
            params=params,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
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

        resp = self._session.post(
            f"{self._base_url}/v1/ambient-priors",
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

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

        resp = self._session.post(
            f"{self._base_url}/v1/signals",
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()
