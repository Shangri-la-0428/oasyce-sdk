"""Back-compat shim — Pipeline lives at ``oasyce_sdk.agent.pipeline``.

Moved in 0.11.6. The PGE cognitive loop (Perceive → Plan → Enrich →
Generate → Evaluate → Deliver → Reflect) is the heart of the Agent
base class and is transport-agnostic by construction.

Re-exports the full public API. Prefer
``from oasyce_sdk.agent.pipeline import ...`` in new code.
"""

from __future__ import annotations

from ..agent.pipeline import (  # noqa: F401
    EnrichContext,
    logger,
    run_pipeline,
)

__all__ = ["EnrichContext", "run_pipeline"]
