"""Reusable HTTP bridge with retry and circuit-breaker policy."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 5.0
MAX_RETRIES = 3
RETRYABLE_STATUSES = {502, 503, 504}
BACKOFF_BASE_SECONDS = 0.2
BACKOFF_CEILING_SECONDS = 5.0
JITTER_SECONDS = 0.1
CIRCUIT_FAILURE_THRESHOLD = 5
CIRCUIT_OPEN_SECONDS = 30.0


@dataclass
class _CircuitState:
    failures: int = 0
    open_until: float = 0.0
    probe_pending: bool = False

    def is_open(self, now: float) -> bool:
        return now < self.open_until

    def allow_probe(self, now: float) -> bool:
        return self.open_until > 0.0 and now >= self.open_until and self.probe_pending

    def record_success(self) -> None:
        self.failures = 0
        self.open_until = 0.0
        self.probe_pending = False

    def record_failure(self, now: float, *, from_probe: bool = False) -> None:
        if from_probe:
            self.failures = 0
            self.open_until = now + CIRCUIT_OPEN_SECONDS
            self.probe_pending = True
            return
        self.failures += 1
        if self.failures >= CIRCUIT_FAILURE_THRESHOLD:
            self.failures = 0
            self.open_until = now + CIRCUIT_OPEN_SECONDS
            self.probe_pending = True


class BridgeClient:
    """Small HTTP bridge with retry, backoff, and circuit breaking."""

    def __init__(
        self,
        base_url: str,
        timeout: float = DEFAULT_TIMEOUT,
        *,
        name: str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._name = name or self._base_url
        self._session = session or requests.Session()
        if self._is_loopback_url(self._base_url):
            self._session.trust_env = False
        self._circuit = _CircuitState()

    @staticmethod
    def _is_loopback_url(url: str) -> bool:
        host = urlparse(url).hostname
        return host in {"127.0.0.1", "localhost", "::1"}

    def close(self) -> None:
        self._session.close()

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> requests.Response | None:
        return self.request("GET", path, params=params, timeout=timeout)

    def post(
        self,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> requests.Response | None:
        return self.request("POST", path, json=json, timeout=timeout)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> requests.Response | None:
        now = time.monotonic()
        url = self._build_url(path)
        probe_call = False
        if self._circuit.is_open(now):
            self._log_event(method, url, "degraded", latency_ms=0, reason="circuit_open")
            return None
        if self._circuit.allow_probe(now):
            probe_call = True
            self._circuit.probe_pending = False

        deadline_timeout = timeout if timeout is not None else self._timeout

        for attempt in range(MAX_RETRIES + 1):
            call_started = time.monotonic()
            try:
                response = self._session.request(
                    method.upper(),
                    url,
                    params=params,
                    json=json,
                    timeout=deadline_timeout,
                )
                status = getattr(response, "status_code", 0)
                if status in RETRYABLE_STATUSES:
                    if attempt < MAX_RETRIES:
                        self._log_event(
                            method,
                            url,
                            "retry",
                            latency_ms=self._elapsed_ms(call_started),
                            attempt=attempt + 1,
                            status=status,
                        )
                        self._sleep_for_attempt(attempt)
                        continue
                    self._circuit.record_failure(now, from_probe=probe_call)
                    self._log_event(
                        method,
                        url,
                        "degraded",
                        latency_ms=self._elapsed_ms(call_started),
                        attempt=attempt + 1,
                        status=status,
                    )
                    return None
                response.raise_for_status()
                self._circuit.record_success()
                self._log_event(
                    method,
                    url,
                    "ok",
                    latency_ms=self._elapsed_ms(call_started),
                    attempt=attempt + 1,
                    status=status,
                )
                return response
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt < MAX_RETRIES:
                    self._log_event(
                        method,
                        url,
                        "retry",
                        latency_ms=self._elapsed_ms(call_started),
                        attempt=attempt + 1,
                        reason=type(exc).__name__,
                    )
                    self._sleep_for_attempt(attempt)
                    continue
                self._circuit.record_failure(now, from_probe=probe_call)
                self._log_event(
                    method,
                    url,
                    "degraded",
                    latency_ms=self._elapsed_ms(call_started),
                    attempt=attempt + 1,
                    reason=type(exc).__name__,
                )
                return None
            except requests.HTTPError as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                self._log_event(
                    method,
                    url,
                    "error",
                    latency_ms=self._elapsed_ms(call_started),
                    attempt=attempt + 1,
                    status=status,
                    reason=type(exc).__name__,
                )
                raise
            except Exception as exc:  # pragma: no cover - defensive guard
                self._log_event(
                    method,
                    url,
                    "error",
                    latency_ms=self._elapsed_ms(call_started),
                    attempt=attempt + 1,
                    reason=type(exc).__name__,
                )
                raise

        raise RuntimeError(f"Bridge call failed: {method} {url}")

    def _sleep_for_attempt(self, attempt: int) -> None:
        delay = min(
            BACKOFF_CEILING_SECONDS,
            BACKOFF_BASE_SECONDS * (2**attempt),
        ) + random.uniform(0.0, JITTER_SECONDS)
        time.sleep(delay)

    def _elapsed_ms(self, started: float) -> int:
        return int((time.monotonic() - started) * 1000)

    def _log_event(
        self,
        method: str,
        url: str,
        outcome: str,
        *,
        latency_ms: int,
        attempt: int | None = None,
        status: int | None = None,
        reason: str | None = None,
    ) -> None:
        extra: dict[str, Any] = {
            "bridge": self._name,
            "target": url,
            "outcome": outcome,
            "latency_ms": latency_ms,
            "method": method.upper(),
        }
        if attempt is not None:
            extra["attempt"] = attempt
        if status is not None:
            extra["status"] = status
        if reason:
            extra["reason"] = reason
        logger.info("bridge_call", extra=extra)

    def _build_url(self, path: str) -> str:
        return f"{self._base_url}/{path.lstrip('/')}"
