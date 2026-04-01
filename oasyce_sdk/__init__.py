"""Oasyce SDK -- Python client for the Oasyce L1 chain REST API.

Usage::

    from oasyce_sdk import OasyceClient

    client = OasyceClient("http://localhost:1317")
    caps = client.list_capabilities(tag="llm")
"""

from .ahrp_adapter import AhrpChainAdapter
from .client import OasyceClient
from .signing_bridge import SigningBridge
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
    Task,
    TxResult,
)

__version__ = "0.5.1"

__all__ = [
    "OasyceClient",
    "SigningBridge",
    "AhrpChainAdapter",
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
    "Task",
    "TxResult",
]
