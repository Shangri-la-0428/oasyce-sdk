"""Phase 7 contract tests — Streaming + Performance (SDK layer).

Validates:
  - LLMChunk dataclass defaults and mutable independence
  - Agent._generate with on_token callback (streaming path)
  - Agent._generate falls back when provider lacks generate_stream
  - Agent.process_stream skips delivery (already streamed)
  - _stream_one_round collects text + tool calls correctly
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from oasyce_sdk.agent.base import Agent
from oasyce_sdk.agent.llm import LLMChunk, LLMResponse, ToolCall
from oasyce_sdk.agent.stimulus import Stimulus
from oasyce_sdk.agent.tools import ToolContext


# ── LLMChunk ────────────────────────────────────────────────

class TestLLMChunk:
    def test_defaults(self):
        chunk = LLMChunk()
        assert chunk.text == ""
        assert chunk.done is False
        assert chunk.tool_calls == []

    def test_text_chunk(self):
        chunk = LLMChunk(text="Hello")
        assert chunk.text == "Hello"
        assert chunk.done is False

    def test_final_chunk_with_tools(self):
        tc = ToolCall(name="search", arguments={"q": "snow"})
        chunk = LLMChunk(done=True, tool_calls=[tc])
        assert chunk.done is True
        assert len(chunk.tool_calls) == 1
        assert chunk.tool_calls[0].name == "search"

    def test_independent_mutable_defaults(self):
        a = LLMChunk()
        b = LLMChunk()
        a.tool_calls.append(ToolCall(name="x", arguments={}))
        assert len(b.tool_calls) == 0


# ── _stream_one_round ───────────────────────────────────────

class TestStreamOneRound:
    def test_collects_text_and_calls_callback(self):
        chunks = [
            LLMChunk(text="Hello"),
            LLMChunk(text=" world"),
            LLMChunk(done=True),
        ]
        llm = MagicMock()
        llm.generate_stream.return_value = iter(chunks)

        received: list[str] = []
        text, tool_calls = Agent._stream_one_round(
            llm,
            [{"role": "user", "content": "hi"}],
            [],
            received.append,
        )
        assert text == "Hello world"
        assert received == ["Hello", " world"]
        assert tool_calls == []

    def test_collects_tool_calls(self):
        tc = ToolCall(name="search", arguments={"q": "snow"}, id="call_1")
        chunks = [
            LLMChunk(text="Let me check"),
            LLMChunk(done=True, tool_calls=[tc]),
        ]
        llm = MagicMock()
        llm.generate_stream.return_value = iter(chunks)

        received: list[str] = []
        text, tool_calls = Agent._stream_one_round(
            llm,
            [{"role": "user", "content": "weather?"}],
            [{"name": "search", "parameters": {}}],
            received.append,
        )
        assert text == "Let me check"
        assert len(tool_calls) == 1
        assert tool_calls[0].name == "search"

    def test_empty_stream(self):
        chunks = [LLMChunk(done=True)]
        llm = MagicMock()
        llm.generate_stream.return_value = iter(chunks)

        received: list[str] = []
        text, tool_calls = Agent._stream_one_round(
            llm, [], [], received.append,
        )
        assert text == ""
        assert received == []
        assert tool_calls == []


# ── _generate with on_token ─────────────────────────────────

def _make_agent():
    """Create a minimal Agent for testing _generate."""
    identity = MagicMock()
    channel = MagicMock()
    registry = MagicMock()
    tools = MagicMock()
    tools.select.return_value = []
    return Agent(
        identity=identity,
        channel=channel,
        registry=registry,
        tools=tools,
        constitution="test",
    )


class TestGenerateStreaming:
    def test_streaming_text_response(self):
        agent = _make_agent()
        chunks = [
            LLMChunk(text="Hello"),
            LLMChunk(text=" there"),
            LLMChunk(done=True),
        ]
        llm = MagicMock()
        llm.generate_stream.return_value = iter(chunks)

        received: list[str] = []
        result = agent._generate(
            llm,
            Stimulus(kind="chat", content="hi", sender_id=1),
            [{"role": "user", "content": "hi"}],
            [],
            MagicMock(spec=ToolContext),
            on_token=received.append,
        )

        assert result == "Hello there"
        assert received == ["Hello", " there"]
        llm.generate.assert_not_called()

    def test_streaming_with_tool_loop(self):
        agent = _make_agent()
        agent._tools.execute.return_value = "tool result"
        agent._tools.is_terminal.return_value = False
        agent._tools.result_is_error.return_value = False

        round1 = [
            LLMChunk(text="Checking..."),
            LLMChunk(done=True, tool_calls=[
                ToolCall(name="search", arguments={"q": "test"}, id="c1"),
            ]),
        ]
        round2 = [
            LLMChunk(text="Found it!"),
            LLMChunk(done=True),
        ]
        call_count = {"n": 0}

        def fake_stream(messages, tools=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return iter(round1)
            return iter(round2)

        llm = MagicMock()
        llm.generate_stream.side_effect = fake_stream

        received: list[str] = []
        result = agent._generate(
            llm,
            Stimulus(kind="chat", content="search", sender_id=1),
            [{"role": "user", "content": "search"}],
            [{"name": "search", "parameters": {}}],
            MagicMock(spec=ToolContext),
            on_token=received.append,
        )

        assert result == "Found it!"
        assert "Checking..." in "".join(received)
        assert "Found it!" in "".join(received)
        assert call_count["n"] == 2

    def test_falls_back_without_generate_stream(self):
        agent = _make_agent()
        llm = MagicMock(spec=["generate"])
        llm.generate.return_value = LLMResponse(text="fallback response")

        received: list[str] = []
        result = agent._generate(
            llm,
            Stimulus(kind="chat", content="hi", sender_id=1),
            [{"role": "user", "content": "hi"}],
            [],
            MagicMock(spec=ToolContext),
            on_token=received.append,
        )

        assert result == "fallback response"
        assert received == []
        llm.generate.assert_called_once()

    def test_no_on_token_uses_blocking(self):
        agent = _make_agent()
        llm = MagicMock()
        llm.generate.return_value = LLMResponse(text="blocking response")

        result = agent._generate(
            llm,
            Stimulus(kind="chat", content="hi", sender_id=1),
            [{"role": "user", "content": "hi"}],
            [],
            MagicMock(spec=ToolContext),
        )

        assert result == "blocking response"
        llm.generate.assert_called_once()
        llm.generate_stream.assert_not_called()


# ── process_stream ──────────────────────────────────────────

class TestProcessStream:
    def test_skips_deliver(self):
        chunks = [
            LLMChunk(text="streamed"),
            LLMChunk(done=True),
        ]
        llm = MagicMock()
        llm.generate_stream.return_value = iter(chunks)

        identity = MagicMock()
        perception = MagicMock()
        perception = MagicMock()
        perception.generation_controls = None
        perception.ambient_priors = None
        perception.kernel = None
        perception.response_contract = None
        perception.system_context = ""
        perception.dynamic_context = ""
        identity.perceive.return_value = perception

        channel = MagicMock()
        registry = MagicMock()
        registry.get.return_value = llm

        tools = MagicMock()
        tools.select.return_value = []

        agent = Agent(
            identity=identity,
            channel=channel,
            registry=registry,
            tools=tools,
            constitution="test",
        )

        received: list[str] = []
        result = agent.process_stream(
            Stimulus(kind="chat", content="hi", sender_id=1),
            on_token=received.append,
        )

        assert result == "streamed"
        assert received == ["streamed"]
        channel.deliver.assert_not_called()

    def test_returns_full_text(self):
        chunks = [
            LLMChunk(text="part1"),
            LLMChunk(text=" part2"),
            LLMChunk(done=True),
        ]
        llm = MagicMock()
        llm.generate_stream.return_value = iter(chunks)

        identity = MagicMock()
        perception = MagicMock()
        perception = MagicMock()
        perception.generation_controls = None
        perception.ambient_priors = None
        perception.kernel = None
        perception.response_contract = None
        perception.system_context = ""
        perception.dynamic_context = ""
        identity.perceive.return_value = perception

        channel = MagicMock()
        registry = MagicMock()
        registry.get.return_value = llm

        tools = MagicMock()
        tools.select.return_value = []

        agent = Agent(
            identity=identity,
            channel=channel,
            registry=registry,
            tools=tools,
            constitution="test",
        )

        result = agent.process_stream(
            Stimulus(kind="chat", content="hi", sender_id=1),
            on_token=lambda _: None,
        )

        assert result == "part1 part2"


# ── Export check ────────────────────────────────────────────

class TestPhase7Exports:
    def test_llm_chunk_importable(self):
        from oasyce_sdk.agent import LLMChunk
        chunk = LLMChunk(text="test")
        assert chunk.text == "test"
