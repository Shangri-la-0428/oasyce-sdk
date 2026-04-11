"""Back-compat shim — LLM gateway lives at ``oasyce_sdk.agent.llm``.

Moved in 0.11.6 so every Agent deployment can share one provider
abstraction (OpenAI-compat + Anthropic-compat, multi-slot routing)
instead of copying it per deployment.

Re-exports the full public API. Prefer
``from oasyce_sdk.agent.llm import ...`` in new code.
"""

from __future__ import annotations

from ..agent.llm import (  # noqa: F401
    CONFIG_PATH,
    AnthropicProvider,
    ClaudeProvider,
    LLMProvider,
    LLMResponse,
    ModelRegistry,
    ModelSlot,
    OpenAICompatProvider,
    QwenProvider,
    ToolCall,
    _create_provider,
    load_provider,
    load_registry,
    logger,
)

__all__ = [
    "AnthropicProvider",
    "ClaudeProvider",
    "CONFIG_PATH",
    "LLMProvider",
    "LLMResponse",
    "ModelRegistry",
    "ModelSlot",
    "OpenAICompatProvider",
    "QwenProvider",
    "ToolCall",
    "load_provider",
    "load_registry",
]
