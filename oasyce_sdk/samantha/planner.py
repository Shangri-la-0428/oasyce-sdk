"""Back-compat shim — Planner lives at ``oasyce_sdk.agent.planner``.

Moved in 0.11.6. The rule-engine Planner (Psyche + Thronglets priors
→ Plan) is transport-agnostic: any Agent deployment benefits from
the same Psyche contract ↔ Plan mapping.

Re-exports the full public API. Prefer
``from oasyce_sdk.agent.planner import ...`` in new code.
"""

from __future__ import annotations

from ..agent.planner import (  # noqa: F401
    Plan,
    _apply_ambient_priors,
    plan,
)

__all__ = ["Plan", "plan"]
