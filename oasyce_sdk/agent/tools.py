"""Tool system — generic registry pattern for Agent capabilities.

Defines the *transport-agnostic* tool layer that the Agent pipeline
depends on:

  ``ToolContext`` — minimal per-stimulus bundle (memory, chain client,
      user id). Deployments extend this with their own fields — for
      example ``samantha.tools.ToolContext`` adds an ``app`` field for
      the App backend client.

  ``Tool``, ``ToolRegistry`` — the dispatch table. A tool is a
      ``(schema, handler)`` pair; the registry turns a list of names
      into LLM-ready schema dicts, and executes handlers by name.

  ``schema`` — shorthand for building a tool schema dict.

This module has **no** imports from any deployment (samantha, openclaw,
etc.) and no imports from ``agent.runtime`` or ``agent.stimulus``. It
is at the bottom of the agent dependency graph so ``agent.pipeline``
can reference it via ``TYPE_CHECKING`` without cycles.

Why generic here and specific in samantha/tools.py:

  The Agent base class needs a *type* for ToolContext (it passes one
  around during the pipeline), but it never reads any field on it —
  only the deployment's handlers do. So the base type exists for
  structural compatibility and nothing else. Concrete deployments
  subclass or re-declare ``ToolContext`` with whatever fields their
  handlers need, and register their own handlers into a
  ``ToolRegistry`` instance.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ── Tool context (generic base) ────────────────────────────────

@dataclass
class ToolContext:
    """Minimal per-stimulus bundle passed to every tool handler.

    Deployments subclass this to add their own fields (e.g.
    ``samantha.tools.ToolContext`` adds ``app: AppClient``). All base
    fields have defaults so subclasses can add required fields without
    dataclass inheritance errors.

    Fields:
      memory: the agent's memory store (typically ``agent.memory.Memory``).
      user_id: integer id of the user the handler is acting on behalf of.
      chain_client: ``OasyceClient`` for on-chain queries. None when the
        agent has no chain wiring.
      chain_address: bech32 address for economic queries. Empty when
        the agent has no on-chain identity.
      session: opaque reference to the per-user agent session. Concrete
        type is deployment-specific (e.g. ``samantha.server.Session``).
    """

    memory: Any = None
    user_id: int = 0
    chain_client: Any = None
    chain_address: str = ""
    session: Any = None


# ── Tool & Registry ─────────────────────────────────────────────

@dataclass
class Tool:
    """One tool: a schema the LLM sees, and a handler we execute.

    Fields:
      name, schema, handler — the dispatch triple.
      terminal — write-side actions that complete the turn. The
        Generator's tool loop breaks immediately after a successful
        terminal call, preventing the LLM from re-emitting the same
        action across rounds (e.g. posting the same comment 2-3 times
        on a single mention). Read tools (memory recall, balance query)
        stay non-terminal so the LLM can synthesise a final answer
        from the result.
    """

    name: str
    schema: dict[str, Any]
    handler: Callable[[dict[str, Any], ToolContext], str]
    terminal: bool = False


class ToolRegistry:
    """Tool dispatch by name lookup, not switch. Extensible."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name: str,
        schema: dict[str, Any],
        handler: Callable[[dict[str, Any], ToolContext], str],
        *,
        terminal: bool = False,
    ) -> None:
        self._tools[name] = Tool(
            name=name, schema=schema, handler=handler, terminal=terminal,
        )

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return [t.schema for t in self._tools.values()]

    def select(self, names: list[str] | None) -> list[dict[str, Any]]:
        """Return tool schemas filtered by name list. None = all."""
        if names is None:
            return self.definitions
        return [t.schema for t in self._tools.values() if t.name in names]

    def is_terminal(self, name: str) -> bool:
        """Whether ``name`` is a terminal (turn-completing) tool.

        Unknown names return False — the loop continues, the unknown-tool
        error is surfaced to the LLM via ``execute``.
        """
        tool = self._tools.get(name)
        return bool(tool and tool.terminal)

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        ctx: ToolContext,
    ) -> str:
        """Run a tool by name. Returns JSON string for the LLM.

        Exceptions are caught and serialised as ``{"error": ...}`` so
        a broken tool cannot crash the pipeline.
        """
        tool = self._tools.get(name)
        if tool is None:
            return json.dumps({"error": f"Unknown tool: {name}"})
        try:
            return tool.handler(arguments, ctx)
        except Exception as e:
            logger.warning("Tool %s failed: %s", name, e)
            return json.dumps({"error": str(e)})

    def result_is_error(self, result: str) -> bool:
        """Whether a tool result represents a structured failure payload."""
        try:
            payload = json.loads(result)
        except (TypeError, ValueError):
            return False
        return isinstance(payload, dict) and bool(payload.get("error"))


# ── Schema helper ──────────────────────────────────────────────

def schema(
    name: str,
    description: str,
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    """Shorthand for building an OpenAI-style tool schema dict."""
    params: dict[str, Any] = {"type": "object", "properties": properties or {}}
    if required:
        params["required"] = required
    return {"name": name, "description": description, "parameters": params}
