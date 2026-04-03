"""Oasyce SDK -- Python client for the Oasyce L1 chain REST API.

Usage::

    from oasyce_sdk import OasyceClient

    client = OasyceClient("http://localhost:1317")
    caps = client.list_capabilities(tag="llm")
"""

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
from .sigil import SigilManager, derive_sigil_id
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

__version__ = "0.10.0"

__all__ = [
    "OasyceClient",
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
