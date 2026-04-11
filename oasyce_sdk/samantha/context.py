"""Back-compat shim — context builder lives at ``oasyce_sdk.agent.context``.

Moved in 0.11.6. The 60/30/10 budget allocation and vision-routing
logic is useful for any Agent deployment, not just Samantha.

Re-exports the full public API. Prefer
``from oasyce_sdk.agent.context import ...`` in new code.
"""

from __future__ import annotations

from ..agent.context import (  # noqa: F401
    ConversationMessage,
    DEFAULT_CONTEXT_WINDOW,
    OUTPUT_RESERVE,
    TOKENS_PER_IMAGE,
    TokenBudget,
    _estimate_tokens,
    _fetch_image_as_data_uri,
    _fetch_images_concurrent,
    _fit_history,
    _IMAGE_CACHE_LOCK,
    _IMAGE_CACHE_MAX,
    _image_pool,
    _truncate_text,
    build_messages,
    logger,
)

__all__ = [
    "ConversationMessage",
    "DEFAULT_CONTEXT_WINDOW",
    "TokenBudget",
    "build_messages",
]
