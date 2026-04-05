"""Oasyce SDK -- Python client for the Oasyce L1 chain REST API.

Usage::

    from oasyce_sdk import OasyceClient

    client = OasyceClient("http://localhost:1317")
    caps = client.list_capabilities(tag="llm")
"""

import importlib
import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .client import OasyceClient
from .errors import (
    ChainError,
    ConnectionError,
    HTTPError,
    NotFoundError,
    OasyceError,
    TimeoutError,
    ValidationError,
)
from .types import (
    AccessLevel,
    Account,
    AnchorRecord,
    Balance,
    Block,
    Bond,
    BondingCurve,
    Capability,
    DataAsset,
    Debt,
    Dispute,
    Earnings,
    EpochStats,
    Escrow,
    Executor,
    Invocation,
    MigrationPath,
    PowResult,
    Registration,
    Reputation,
    ShareHolder,
    Sigil,
    SigilParams,
    Task,
    TxResult,
)

def _package_version() -> str:
    try:
        return version("oasyce-sdk")
    except PackageNotFoundError:
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        if pyproject.exists():
            match = re.search(
                r'^version\s*=\s*"([^"]+)"',
                pyproject.read_text(encoding="utf-8"),
                re.MULTILINE,
            )
            if match:
                return match.group(1)
        return "0+unknown"


__version__ = _package_version()


def __getattr__(name: str):
    if name == "agent":
        agent_module = importlib.import_module(".agent", __name__)

        globals()["agent"] = agent_module
        return agent_module
    if name in {"IdentityContext", "IdentityResolver"}:
        from .identity import IdentityContext, IdentityResolver

        globals()["IdentityContext"] = IdentityContext
        globals()["IdentityResolver"] = IdentityResolver
        return globals()[name]
    if name in {"SigilManager", "derive_sigil_id"}:
        from .sigil import SigilManager, derive_sigil_id

        globals()["SigilManager"] = SigilManager
        globals()["derive_sigil_id"] = derive_sigil_id
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "OasyceClient",
    "agent",
    "IdentityContext",
    "IdentityResolver",
    "SigilManager",
    "derive_sigil_id",
    "__version__",
    # Errors
    "OasyceError",
    "NotFoundError",
    "ChainError",
    "ConnectionError",
    "HTTPError",
    "TimeoutError",
    "ValidationError",
    # Types
    "AccessLevel",
    "Account",
    "AnchorRecord",
    "Balance",
    "Block",
    "Bond",
    "BondingCurve",
    "Capability",
    "DataAsset",
    "Debt",
    "Dispute",
    "Earnings",
    "EpochStats",
    "Escrow",
    "Executor",
    "Invocation",
    "MigrationPath",
    "PowResult",
    "Registration",
    "Reputation",
    "ShareHolder",
    "Sigil",
    "SigilParams",
    "Task",
    "TxResult",
]
