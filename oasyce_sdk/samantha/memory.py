"""Back-compat shim — memory lives at ``oasyce_sdk.agent.memory``.

Historically Samantha's memory layer lived here. In 0.11.6 it moved
to the generic ``agent/`` package so every Agent deployment can use
the same Fact/Message/CoreMemory store, not just Samantha.

This module re-exports the full public (and private, for tests) API
so existing ``from oasyce_sdk.samantha.memory import ...`` imports
keep working. Prefer ``from oasyce_sdk.agent.memory import ...`` in
new code.
"""

from __future__ import annotations

from ..agent.memory import (  # noqa: F401
    CoreMemory,
    DEFAULT_DB_PATH,
    Fact,
    HistorySummary,
    Memory,
    Message,
    _FTS_TOKEN,
    _SCHEMA,
    _fts5_query,
    logger,
)

__all__ = [
    "CoreMemory",
    "DEFAULT_DB_PATH",
    "Fact",
    "HistorySummary",
    "Memory",
    "Message",
]
