"""Provider-agnostic LLM gateway.

Supports Claude (Anthropic), Qwen (Dashscope/OpenAI-compatible), Grok (xAI).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

CONFIG_PATH = Path.home() / ".oasyce" / "samantha" / "config.json"


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = ""


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


class LLMProvider(Protocol):
    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse: ...


# ── Claude (Anthropic) ──────────────────────────────────────────

class ClaudeProvider:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        # Separate system message
        system_text = ""
        chat_messages = []
        for m in messages:
            if m["role"] == "system":
                system_text += m["content"] + "\n"
            else:
                chat_messages.append(m)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 2048,
            "messages": chat_messages,
        }
        if system_text:
            kwargs["system"] = system_text.strip()
        if tools:
            kwargs["tools"] = [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": t.get("parameters", {}),
                }
                for t in tools
            ]

        resp = self._client.messages.create(**kwargs)

        text_parts = []
        tool_calls = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    name=block.name,
                    arguments=block.input,
                    id=block.id,
                ))

        return LLMResponse(
            text="\n".join(text_parts),
            tool_calls=tool_calls,
            usage={"input": resp.usage.input_tokens, "output": resp.usage.output_tokens},
        )


# ── Qwen (Dashscope / OpenAI-compatible) ────────────────────────

class QwenProvider:
    def __init__(self, api_key: str, model: str = "qwen-plus", base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = [
                {"type": "function", "function": t} for t in tools
            ]

        resp = self._client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(ToolCall(
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments) if tc.function.arguments else {},
                    id=tc.id or "",
                ))

        return LLMResponse(
            text=msg.content or "",
            tool_calls=tool_calls,
            usage={"input": resp.usage.prompt_tokens, "output": resp.usage.completion_tokens} if resp.usage else {},
        )


# ── Factory ─────────────────────────────────────────────────────

def load_provider(config_path: Path | None = None) -> LLMProvider:
    """Load LLM provider from config file."""
    p = config_path or CONFIG_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"Samantha config not found at {p}. "
            "Create it with: {\"provider\": \"claude\", \"api_key\": \"sk-...\"}"
        )
    cfg = json.loads(p.read_text(encoding="utf-8"))
    provider = cfg.get("provider", "claude")
    api_key = cfg.get("api_key", "")
    if not api_key:
        raise ValueError("api_key is required")
    model = cfg.get("model", "")

    if provider == "claude":
        return ClaudeProvider(api_key, model=model or "claude-sonnet-4-20250514")
    elif provider == "qwen":
        return QwenProvider(
            api_key,
            model=model or "qwen-plus",
            base_url=cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        )
    elif provider == "openai":
        return QwenProvider(
            api_key,
            model=model or "gpt-4o",
            base_url=cfg.get("base_url", "https://api.openai.com/v1"),
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")
