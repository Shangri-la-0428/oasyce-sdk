"""Back-compat shim — Evaluator lives at ``oasyce_sdk.agent.evaluator``.

Moved in 0.11.6. Anti-pattern detection and sentence/emoji limits
are transport-agnostic quality gates; every Agent deployment can
reuse them without copying.

Re-exports the full public API. Prefer
``from oasyce_sdk.agent.evaluator import ...`` in new code.
"""

from __future__ import annotations

from ..agent.evaluator import (  # noqa: F401
    ANTI_PATTERNS,
    GENERIC_OPENERS,
    Verdict,
    count_emojis,
    count_sentences,
    evaluate,
)

__all__ = [
    "ANTI_PATTERNS",
    "GENERIC_OPENERS",
    "Verdict",
    "count_emojis",
    "count_sentences",
    "evaluate",
]
