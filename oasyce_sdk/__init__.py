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
from .types import (
    Account,
    Balance,
    Block,
    BondingCurve,
    Capability,
    DataAsset,
    Debt,
    Earnings,
    Escrow,
    Executor,
    Registration,
    Reputation,
    ShareHolder,
    Task,
    TxResult,
)

__version__ = "0.1.0"

__all__ = [
    "OasyceClient",
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
    "Account",
    "Balance",
    "Block",
    "BondingCurve",
    "Capability",
    "DataAsset",
    "Debt",
    "Earnings",
    "Escrow",
    "Executor",
    "Registration",
    "Reputation",
    "ShareHolder",
    "Task",
    "TxResult",
]
