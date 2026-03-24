"""Typed response dataclasses for the Oasyce SDK.

Every query method on OasyceClient returns one of these dataclasses
rather than raw dicts, giving callers auto-complete, type safety, and
a stable interface even if the underlying REST JSON changes shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Capability Marketplace
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Capability:
    """A registered AI capability endpoint on the Oasyce network."""
    capability_id: str
    name: str
    provider: str
    description: str
    endpoint_url: str
    price_per_call: int  # in uoas
    tags: List[str]
    rate_limit: int
    total_calls: int
    total_earned: int  # in uoas
    avg_latency_ms: int
    success_rate: int  # basis points 0-10000
    active: bool


@dataclass(frozen=True)
class Earnings:
    """Aggregated earnings for a capability provider."""
    provider: str
    total_earned_uoas: int
    total_calls: int


# ---------------------------------------------------------------------------
# Data Assets
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DataAsset:
    """A registered data asset on the Oasyce chain."""
    asset_id: str
    name: str
    owner: str
    description: str
    content_hash: str
    fingerprint: str
    rights_type: str  # ORIGINAL, CO_CREATION, LICENSED, COLLECTION
    tags: List[str]
    total_shares: int
    status: str  # ACTIVE, SHUTTING_DOWN, SETTLED
    version: int
    parent_asset_id: str


@dataclass(frozen=True)
class ShareHolder:
    """A holder of shares in a data asset."""
    address: str
    asset_id: str
    shares: int


@dataclass(frozen=True)
class BondingCurve:
    """Current bonding curve state for a data asset."""
    asset_id: str
    supply: int
    reserve_uoas: int
    spot_price_uoas: int
    price_factor: str
    buyer_count: int


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Escrow:
    """A locked-fund escrow backing a capability invocation or data purchase."""
    escrow_id: str
    creator: str
    provider: str
    amount_uoas: int
    status: str  # LOCKED, RELEASED, REFUNDED, EXPIRED


# ---------------------------------------------------------------------------
# Reputation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Reputation:
    """Aggregated reputation score for an on-chain address."""
    address: str
    score: int  # total_score (scaled by 100)
    total_feedback: int
    verified_feedback: int


# ---------------------------------------------------------------------------
# Work (Proof of Useful Work)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Task:
    """An AI compute task submitted to the network."""
    task_id: str
    creator: str
    task_type: str
    bounty_uoas: int
    deposit_uoas: int
    status: str
    redundancy: int
    assigned_executors: List[str]
    description: str = ""
    executor: Optional[str] = None


@dataclass(frozen=True)
class Executor:
    """An executor profile registered for Proof-of-Useful-Work tasks."""
    address: str
    supported_task_types: List[str]
    max_compute_units: int
    tasks_completed: int
    tasks_failed: int
    active: bool


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Registration:
    """A user's onboarding registration record."""
    address: str
    airdrop_amount: int  # in uoas
    repaid_amount: int  # in uoas
    status: str  # ACTIVE, REPAID, DEFAULTED


@dataclass(frozen=True)
class Debt:
    """Outstanding onboarding debt for an address."""
    address: str
    total_debt: int  # in uoas
    repaid: int  # in uoas
    remaining: int  # in uoas
    status: str


# ---------------------------------------------------------------------------
# Cosmos Bank / Auth / Tendermint
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Balance:
    """Account balance on the Oasyce chain."""
    address: str
    amount_uoas: int
    amount_oas: float


@dataclass(frozen=True)
class Account:
    """Cosmos account information."""
    address: str
    account_number: int
    sequence: int


@dataclass(frozen=True)
class Block:
    """Latest block summary."""
    height: int
    time: str
    chain_id: str
    proposer_address: str
    num_txs: int


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TxResult:
    """Result of broadcasting a signed transaction."""
    tx_hash: str
    code: int
    raw_log: str
    success: bool
