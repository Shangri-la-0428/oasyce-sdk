"""Tests for oasyce_sdk.agent.runtime — the feedback loop."""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from typing import Any
from unittest.mock import patch

import pytest

from oasyce_sdk.agent.thronglets_client import (
    ThrongletsClient,
    CapabilityStats,
    Signal,
)
from oasyce_sdk.agent.psyche_client import PsycheClient
from oasyce_sdk.agent.runtime import (
    AgentRuntime,
    Perception,
    synthesize_stimulus,
    outcome_to_writeback,
)
from oasyce_sdk.crypto.wallet import Wallet


# ── Pure function tests ──────────────────────────────────────────


class TestSynthesizeStimulus:
    def test_context_only(self):
        result = synthesize_stimulus("I need data analysis", [], [])
        assert result == "I need data analysis"

    def test_with_capabilities(self):
        caps = [
            CapabilityStats(capability="data-analysis", success_rate=0.95, total_traces=10, p50_latency_ms=200),
            CapabilityStats(capability="visualization", success_rate=0.7, total_traces=5, p50_latency_ms=500),
        ]
        result = synthesize_stimulus("financial analysis", caps, [])
        assert "Collective experience" in result
        assert "data-analysis: 95% success" in result
        assert "visualization: 70% success" in result

    def test_with_signals(self):
        signals = [
            Signal(kind="recommend", message="Use capability X for speed"),
            Signal(kind="avoid", message="Capability Y is unreliable"),
        ]
        result = synthesize_stimulus("need fast processing", [], signals)
        assert "Collective signals" in result
        assert "[recommend]" in result
        assert "[avoid]" in result

    def test_caps_at_5(self):
        caps = [CapabilityStats(capability=f"cap-{i}", total_traces=1) for i in range(10)]
        result = synthesize_stimulus("test", caps, [])
        assert "cap-4" in result
        assert "cap-5" not in result

    def test_signals_at_3(self):
        signals = [Signal(kind="info", message=f"signal-{i}") for i in range(5)]
        result = synthesize_stimulus("test", [], signals)
        assert "signal-2" in result
        assert "signal-3" not in result

    def test_empty_message_signals_skipped(self):
        signals = [Signal(kind="info", message=""), Signal(kind="recommend", message="useful")]
        result = synthesize_stimulus("test", [], signals)
        assert "[recommend] useful" in result


class TestOutcomeToWriteback:
    def test_succeeded(self):
        assert "trust_up" in outcome_to_writeback("succeeded")

    def test_failed(self):
        assert "trust_down" in outcome_to_writeback("failed")

    def test_partial(self):
        assert "task_recenter" in outcome_to_writeback("partial")

    def test_timeout(self):
        assert "withdrawal_mark" in outcome_to_writeback("timeout")

    def test_disputed(self):
        s = outcome_to_writeback("succeeded", disputed=True)
        assert "trust_up" in s and "boundary_set" in s

    def test_unknown(self):
        assert outcome_to_writeback("unknown") == []


# ── Mock servers ─────────────────────────────────────────────────

_thronglets_traces: list[dict] = []
_thronglets_signals: list[dict] = []
_psyche_inputs: list[dict] = []
_psyche_outputs: list[dict] = []


def _reset():
    _thronglets_traces.clear()
    _thronglets_signals.clear()
    _psyche_inputs.clear()
    _psyche_outputs.clear()


class MockThrongletsHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path == "/v1/status":
            self._json({"status": "ok"})
        elif self.path.startswith("/v1/query"):
            # Return stored traces as capability stats
            cap_map: dict[str, dict] = {}
            for t in _thronglets_traces:
                cap = t.get("capability", "unknown")
                if cap not in cap_map:
                    cap_map[cap] = {"capability": cap, "success_rate": 0.0, "total_traces": 0, "p50_latency_ms": 0, "confidence": 0.5}
                cap_map[cap]["total_traces"] += 1
                cap_map[cap]["success_rate"] = 1.0 if t.get("outcome") == "succeeded" else 0.0
            self._json({"capabilities": list(cap_map.values()), "signals": _thronglets_signals})
        elif self.path.startswith("/v1/signals/feed"):
            self._json({"signals": _thronglets_signals})
        else:
            self.send_error(404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/v1/traces":
            _thronglets_traces.append(body)
            self._json({"id": f"trace-{len(_thronglets_traces)}"})
        elif self.path == "/v1/signals":
            _thronglets_signals.append(body)
            self._json({"id": f"signal-{len(_thronglets_signals)}"})
        else:
            self.send_error(404)

    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class MockPsycheHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path == "/state":
            self._json({"current": {"order": 60, "flow": 55, "boundary": 65, "resonance": 50}, "drives": {"safety": 0.3, "curiosity": 0.7}, "dominantEmotion": "curious"})
        elif self.path == "/status-summary":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            b = b"Feeling curious"
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        else:
            self.send_error(404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/process-input":
            _psyche_inputs.append(body)
            self._json({
                "systemContext": "You are curious.",
                "dynamicContext": "",
                "stimulus": "intellectual",
                "stimulusConfidence": 0.8,
                "replyEnvelope": {
                    "subjectivityKernel": {"vitality": 0.7, "tension": 0.3, "warmth": 0.6, "guard": 0.2, "pressureMode": "low", "initiativeMode": "proactive", "expressionMode": "open", "socialDistance": "familiar"},
                    "responseContract": {"replyProfile": "work"},
                },
            })
        elif self.path == "/process-output":
            _psyche_outputs.append(body)
            self._json({"cleanedText": body.get("text", ""), "stateChanged": bool(body.get("signals"))})
        else:
            self.send_error(404)

    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def mock_thronglets():
    s = HTTPServer(("127.0.0.1", 0), MockThrongletsHandler)
    Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()


@pytest.fixture(scope="module")
def mock_psyche():
    s = HTTPServer(("127.0.0.1", 0), MockPsycheHandler)
    Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()


@pytest.fixture(autouse=True)
def reset():
    _reset()


# ── Client tests ─────────────────────────────────────────────────

class TestThrongletsClient:
    def test_available(self, mock_thronglets):
        assert ThrongletsClient(mock_thronglets).is_available()

    def test_unreachable(self):
        assert not ThrongletsClient("http://127.0.0.1:1").is_available()

    def test_trace_record(self, mock_thronglets):
        c = ThrongletsClient(mock_thronglets)
        c.trace_record("test-cap", "succeeded", "test context")
        assert _thronglets_traces[0]["capability"] == "test-cap"

    def test_query(self, mock_thronglets):
        c = ThrongletsClient(mock_thronglets)
        c.trace_record("cap-A", "succeeded", "data analysis")
        r = c.query("data analysis")
        assert isinstance(r.capabilities, list)

    def test_signal_post(self, mock_thronglets):
        c = ThrongletsClient(mock_thronglets)
        c.signal_post("ctx", "recommend", "Use cap-X")
        assert _thronglets_signals[0]["kind"] == "recommend"


class TestPsycheClient:
    def test_available(self, mock_psyche):
        assert PsycheClient(mock_psyche).is_available()

    def test_process_input(self, mock_psyche):
        r = PsycheClient(mock_psyche).process_input("I feel curious")
        assert r.stimulus_type == "intellectual"
        assert r.reply_envelope.subjectivity_kernel.vitality == 0.7

    def test_process_output_signals(self, mock_psyche):
        r = PsycheClient(mock_psyche).process_output("done", signals=["trust_up"], signal_confidence=0.8)
        assert r["stateChanged"] is True
        assert _psyche_outputs[0]["signals"] == ["trust_up"]

    def test_get_state(self, mock_psyche):
        s = PsycheClient(mock_psyche).get_state()
        assert s.self_state.order == 60
        assert s.self_state.boundary == 65
        assert s.dominant_emotion == "curious"

    def test_status_summary(self, mock_psyche):
        assert "curious" in PsycheClient(mock_psyche).get_status_summary()


# ── AgentRuntime tests ───────────────────────────────────────────

class TestAgentRuntime:
    def test_init(self, mock_thronglets, mock_psyche):
        r = AgentRuntime(psyche_url=mock_psyche, thronglets_url=mock_thronglets)
        assert r.agent_id and r.session_id
        r.close()

    def test_status(self, mock_thronglets, mock_psyche):
        wallet = Wallet.create()
        runtime = AgentRuntime(psyche_url=mock_psyche, thronglets_url=mock_thronglets)
        runtime.set_wallet(wallet)
        s = runtime.status()
        assert s["psyche"] is True and s["thronglets"] is True
        assert s["signer_address"] == wallet.address
        assert s["delegate"] == s["signer_address"]
        assert s["wallet"] == s["signer_address"]
        assert s["identity_error"] is None
        runtime.close()

    def test_status_without_identity_is_graceful(self, mock_thronglets, mock_psyche):
        runtime = AgentRuntime(psyche_url=mock_psyche, thronglets_url=mock_thronglets)
        with patch(
            "oasyce_sdk.agent.runtime.IdentityResolver.resolve",
            side_effect=FileNotFoundError("No identity found"),
        ):
            s = runtime.status()
        assert s["psyche"] is True and s["thronglets"] is True
        assert s["signer_address"] is None
        assert s["delegate"] is None
        assert s["wallet"] is None
        assert s["identity"] is None
        assert s["identity_error"] == "No identity found"
        runtime.close()

    def test_wallet_uses_device_resolution(self, mock_thronglets, mock_psyche):
        r = AgentRuntime(psyche_url=mock_psyche, thronglets_url=mock_thronglets)
        marker = object()
        with patch("oasyce_sdk.agent.runtime.IdentityResolver.resolve") as mock_resolve:
            mock_resolve.return_value = type(
                "IdentityStub",
                (),
                {"wallet": marker},
            )()
            assert r.wallet is marker
            mock_resolve.assert_called_once_with(wallet=None, session_id=r.session_id)
        r.close()

    def test_set_wallet_creates_explicit_identity(self, mock_thronglets, mock_psyche):
        wallet = Wallet.create()
        r = AgentRuntime(psyche_url=mock_psyche, thronglets_url=mock_thronglets)
        r.set_wallet(wallet)
        assert r.identity.binding_source == "explicit"
        assert r.identity.address == wallet.address
        r.close()

    def test_perceive(self, mock_thronglets, mock_psyche):
        r = AgentRuntime(psyche_url=mock_psyche, thronglets_url=mock_thronglets)
        p = r.perceive("analyze data")
        assert p.kernel.vitality == 0.7
        assert "analyze data" in _psyche_inputs[0]["text"]
        r.close()

    def test_act(self, mock_thronglets, mock_psyche):
        r = AgentRuntime(psyche_url=mock_psyche, thronglets_url=mock_thronglets)
        r.act("invoked cap", "succeeded", "analysis", capability="data-analysis")
        assert _thronglets_traces[0]["capability"] == "data-analysis"
        assert "trust_up" in _psyche_outputs[0]["signals"]
        r.close()

    def test_graceful_offline(self):
        r = AgentRuntime(psyche_url="http://127.0.0.1:1", thronglets_url="http://127.0.0.1:2")
        p = r.perceive("test")
        assert not p.has_collective_experience
        r.act("test", "succeeded", "test")  # should not raise
        r.close()


# ── Two-agent feedback loop ──────────────────────────────────────

class TestTwoAgentLoop:
    def test_loop_closes(self, mock_thronglets, mock_psyche):
        a = AgentRuntime(agent_id="A", psyche_url=mock_psyche, thronglets_url=mock_thronglets)
        b = AgentRuntime(agent_id="B", psyche_url=mock_psyche, thronglets_url=mock_thronglets)

        # A perceives (empty) and acts
        pa = a.perceive("financial analysis")
        assert not pa.has_collective_experience
        a.act("analyzed revenue", "succeeded", "Q4 analysis", capability="fin-analysis")
        assert len(_thronglets_traces) == 1

        # B perceives → receives A's capability stats
        pb = b.perceive("financial analysis")
        assert pb.has_collective_experience
        assert len(pb.capabilities) >= 1
        # Stimulus to Psyche should mention A's capability
        assert "fin-analysis" in _psyche_inputs[-1]["text"]

        # B acts → 2 traces total
        b.act("analyzed expenses", "succeeded", "Q4 expenses", capability="expense-analysis")
        assert len(_thronglets_traces) == 2

        # A perceives again → both capabilities
        pa2 = a.perceive("financial overview")
        assert len(pa2.capabilities) >= 2

        a.close(); b.close()

    def test_failure_writeback(self, mock_thronglets, mock_psyche):
        a = AgentRuntime(agent_id="F", psyche_url=mock_psyche, thronglets_url=mock_thronglets)
        a.act("failed task", "failed", "bad data", capability="unreliable")
        assert "trust_down" in _psyche_outputs[0]["signals"]
        assert _thronglets_traces[0]["outcome"] == "failed"
        a.close()
