"""Provider-agnostic LLM gateway with multi-model routing.

Supports:
  - OpenAI-compatible APIs (xAI/Grok, Dashscope/Qwen, OpenAI, DeepSeek)
  - Anthropic-compatible APIs (Claude, Tencent Cloud proxy for Kimi/Hunyuan)

Architecture:
  ModelSlot      -- one configured endpoint (name, provider, key, model, caps)
  ModelRegistry  -- routes to the right slot based on needs (vision, speed)
  LLMProvider    -- protocol abstraction (OpenAI vs Anthropic wire format)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

CONFIG_PATH = Path.home() / ".oasyce" / "samantha" / "config.json"


# ── Data types ─────────────────────────────────────────────────

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


# ── OpenAI-compatible provider ─────────────────────────────────

class OpenAICompatProvider:
    """OpenAI Chat Completions protocol.

    Works with: xAI (Grok), Dashscope (Qwen), OpenAI, DeepSeek, etc.
    """

    def __init__(self, api_key: str, model: str = "gpt-4o",
                 base_url: str = "https://api.openai.com/v1"):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in tools]

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
            usage={
                "input": resp.usage.prompt_tokens,
                "output": resp.usage.completion_tokens,
            } if resp.usage else {},
        )


# ── Anthropic-compatible provider ──────────────────────────────

class AnthropicProvider:
    """Anthropic Messages protocol.

    Works with: Claude (api.anthropic.com), Tencent Cloud proxy (Kimi, Hunyuan).
    Automatically converts OpenAI-style image blocks to Anthropic format.
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514",
                 base_url: str = ""):
        import anthropic
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = anthropic.Anthropic(**kwargs)
        self._model = model

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        system_text = ""
        chat_messages = []
        for m in messages:
            if m["role"] == "system":
                system_text += m["content"] + "\n"
            else:
                content = m["content"]
                if isinstance(content, list):
                    content = self._convert_content_blocks(content)
                chat_messages.append({"role": m["role"], "content": content})

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

    @staticmethod
    def _convert_content_blocks(blocks: list) -> list:
        """Convert OpenAI-style vision blocks to Anthropic format.

        context.py builds messages in OpenAI format (image_url with data URI).
        This converts to Anthropic format (image with base64 source) so the
        Anthropic SDK can send it correctly.
        """
        result = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "image_url":
                data_uri = b.get("image_url", {}).get("url", "")
                if data_uri.startswith("data:"):
                    # "data:image/jpeg;base64,/9j/4AAQ..." → media_type + raw base64
                    header, data = data_uri.split(",", 1)
                    media_type = header.split(":")[1].split(";")[0]
                    result.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": data,
                        },
                    })
                # Skip non-data-URI image URLs (provider can't fetch external URLs)
            else:
                result.append(b)
        return result


# ── Model slot + registry ──────────────────────────────────────

@dataclass
class ModelSlot:
    """One configured model endpoint."""
    name: str
    provider: str       # "openai" | "anthropic"
    api_key: str
    model: str
    base_url: str = ""
    vision: bool = False


class ModelRegistry:
    """Routes to the right model based on task needs.

    Two named slots: default (text) and vision (multimodal).
    Can be the same model if it handles both.
    """

    def __init__(self, slots: dict[str, ModelSlot], default: str, vision: str = ""):
        self._slots = slots
        self._default = default
        self._vision = vision or default
        self._cache: dict[str, LLMProvider] = {}

    def get(self, *, needs_vision: bool = False) -> LLMProvider:
        """Get provider for task. Routes to vision model when images present."""
        name = self._vision if needs_vision else self._default
        return self._resolve(name)

    def get_by_name(self, name: str) -> LLMProvider:
        """Get specific named provider."""
        return self._resolve(name)

    @property
    def default_name(self) -> str:
        return self._default

    @property
    def slot_names(self) -> list[str]:
        return list(self._slots.keys())

    def _resolve(self, name: str) -> LLMProvider:
        if name not in self._cache:
            slot = self._slots.get(name)
            if not slot:
                raise ValueError(f"Unknown model slot: {name}. Available: {list(self._slots)}")
            self._cache[name] = _create_provider(slot)
        return self._cache[name]


def _create_provider(slot: ModelSlot) -> LLMProvider:
    """Create LLMProvider from a ModelSlot."""
    if slot.provider == "anthropic":
        return AnthropicProvider(
            slot.api_key,
            model=slot.model,
            base_url=slot.base_url,
        )
    else:
        # "openai" and everything else → OpenAI Chat Completions protocol
        return OpenAICompatProvider(
            slot.api_key,
            model=slot.model,
            base_url=slot.base_url or "https://api.openai.com/v1",
        )


# ── Config loaders ─────────────────────────────────────────────

def load_registry(config_path: Path | None = None) -> ModelRegistry:
    """Load multi-model registry from config.

    Supports two formats:
      New: {"models": {"name": {provider, api_key, model, ...}}, "default_model": "name"}
      Legacy: {"provider": "openai", "api_key": "...", "model": "..."}
    """
    p = config_path or CONFIG_PATH
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {p}")
    cfg = json.loads(p.read_text(encoding="utf-8"))

    if "models" in cfg:
        slots = {}
        for name, m in cfg["models"].items():
            slots[name] = ModelSlot(
                name=name,
                provider=m.get("provider", "openai"),
                api_key=m["api_key"],
                model=m["model"],
                base_url=m.get("base_url", ""),
                vision=m.get("vision", False),
            )
        if not slots:
            raise ValueError("No models configured")
        return ModelRegistry(
            slots=slots,
            default=cfg.get("default_model", next(iter(slots))),
            vision=cfg.get("vision_model", ""),
        )

    # Legacy flat format → single-model registry
    api_key = cfg.get("api_key", "")
    if not api_key:
        raise ValueError("api_key is required")
    provider_name = cfg.get("provider", "openai")

    slot = ModelSlot(
        name="default",
        provider="anthropic" if provider_name == "claude" else "openai",
        api_key=api_key,
        model=cfg.get("model", "gpt-4o"),
        base_url=cfg.get("base_url", ""),
        vision=True,
    )
    return ModelRegistry(slots={"default": slot}, default="default")


def load_provider(config_path: Path | None = None) -> LLMProvider:
    """Load single provider from config. Used for per-user LLM overrides."""
    p = config_path or CONFIG_PATH
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {p}")
    cfg = json.loads(p.read_text(encoding="utf-8"))

    api_key = cfg.get("api_key", "")
    if not api_key:
        raise ValueError("api_key is required")
    provider_name = cfg.get("provider", "openai")

    slot = ModelSlot(
        name="user",
        provider="anthropic" if provider_name == "claude" else "openai",
        api_key=api_key,
        model=cfg.get("model", "gpt-4o"),
        base_url=cfg.get("base_url", ""),
    )
    return _create_provider(slot)


# Backward-compat aliases
ClaudeProvider = AnthropicProvider
QwenProvider = OpenAICompatProvider
