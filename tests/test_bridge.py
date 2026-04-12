from __future__ import annotations

import requests
import pytest

from oasyce_sdk.agent.bridge import BridgeClient
from oasyce_sdk.agent.psyche_client import PsycheClient, ProcessInputResult
from oasyce_sdk.agent.thronglets_client import QueryResult, ThrongletsClient


class DummyResponse:
    def __init__(self, status_code: int, json_data=None, text: str = ""):
        self.status_code = status_code
        self._json_data = {} if json_data is None else json_data
        self.text = text

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def test_bridge_client_retries_transient_status(monkeypatch):
    client = BridgeClient("http://127.0.0.1:7777", timeout=0.1)
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url))
        if len(calls) == 1:
            return DummyResponse(503, {"ok": False})
        return DummyResponse(200, {"ok": True})

    monkeypatch.setattr(client._session, "request", fake_request)
    monkeypatch.setattr("oasyce_sdk.agent.bridge.random.uniform", lambda *_: 0.0)
    monkeypatch.setattr("oasyce_sdk.agent.bridge.time.sleep", lambda *_: None)

    resp = client.get("/v1/status")

    assert resp is not None
    assert resp.json()["ok"] is True
    assert len(calls) == 2


def test_bridge_client_does_not_retry_4xx(monkeypatch):
    client = BridgeClient("http://127.0.0.1:7777", timeout=0.1)
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url))
        return DummyResponse(404, {"error": "missing"})

    monkeypatch.setattr(client._session, "request", fake_request)
    monkeypatch.setattr("oasyce_sdk.agent.bridge.time.sleep", lambda *_: None)

    with pytest.raises(requests.HTTPError):
        client.get("/v1/status")

    assert len(calls) == 1


def test_bridge_client_circuit_breaker_opens(monkeypatch):
    client = BridgeClient("http://127.0.0.1:7777", timeout=0.1)
    calls = 0

    def fake_request(method, url, **kwargs):
        nonlocal calls
        calls += 1
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(client._session, "request", fake_request)
    monkeypatch.setattr("oasyce_sdk.agent.bridge.random.uniform", lambda *_: 0.0)
    monkeypatch.setattr("oasyce_sdk.agent.bridge.time.sleep", lambda *_: None)

    for _ in range(5):
        assert client.get("/v1/status") is None

    assert calls == 20

    assert client.get("/v1/status") is None
    assert calls == 20


def test_bridge_client_failed_probe_reopens_circuit(monkeypatch):
    client = BridgeClient("http://127.0.0.1:7777", timeout=0.1)
    calls = 0

    def fake_request(method, url, **kwargs):
        nonlocal calls
        calls += 1
        raise requests.ConnectionError("boom")

    client._circuit.open_until = 10.0
    client._circuit.probe_pending = True

    monkeypatch.setattr(client._session, "request", fake_request)
    monkeypatch.setattr("oasyce_sdk.agent.bridge.random.uniform", lambda *_: 0.0)
    monkeypatch.setattr("oasyce_sdk.agent.bridge.time.sleep", lambda *_: None)
    monkeypatch.setattr("oasyce_sdk.agent.bridge.time.monotonic", lambda: 11.0)

    assert client.get("/v1/status") is None
    assert calls == 4
    assert client._circuit.probe_pending is True
    assert client._circuit.open_until > 11.0

    assert client.get("/v1/status") is None
    assert calls == 4


def test_thronglets_client_degrades_when_bridge_is_down():
    client = ThrongletsClient("http://127.0.0.1:7777")
    client._bridge.get = lambda *a, **k: None  # type: ignore[assignment]
    client._bridge.post = lambda *a, **k: None  # type: ignore[assignment]

    assert client.is_available() is False
    assert client.query("context") == QueryResult()
    assert client.signal_feed() == []
    assert client.trace_record("cap", "succeeded", "ctx") == {}
    assert client.presence_ping("SIG_test") == {}
    assert client.presence_feed() == []
    assert client.ambient_priors("ctx") == {}
    assert client.signal_post("ctx", "info", "msg") == {}


def test_psyche_client_degrades_when_bridge_is_down():
    client = PsycheClient("http://127.0.0.1:3210")
    client._bridge.get = lambda *a, **k: None  # type: ignore[assignment]
    client._bridge.post = lambda *a, **k: None  # type: ignore[assignment]

    assert client.is_available() is False
    assert client.process_input("hello") == ProcessInputResult()
    assert client.process_output("done") == {}
    assert client.get_state().self_state.order == 50.0
    assert client.get_status_summary() == ""
