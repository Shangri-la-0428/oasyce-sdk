"""Main client for the Oasyce L1 chain REST API.

Thread-safe, stateless client that wraps the Cosmos SDK REST gateway
(default ``http://localhost:1317``) and returns typed dataclasses
for every response.
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import struct
from typing import Any, Dict, List, Optional

import requests

from .errors import (
    ChainError,
    ConnectionError,
    HTTPError,
    NotFoundError,
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
    DelegatePolicy,
    DelegateRecord,
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
    SpendWindow,
    Task,
    TxResult,
)

_UOAS_PER_OAS = 1_000_000

# Mapping from protobuf enum integers/names to human-readable strings.
_ESCROW_STATUS = {
    "ESCROW_STATUS_UNSPECIFIED": "UNSPECIFIED",
    "ESCROW_STATUS_LOCKED": "LOCKED",
    "ESCROW_STATUS_RELEASED": "RELEASED",
    "ESCROW_STATUS_REFUNDED": "REFUNDED",
    "ESCROW_STATUS_EXPIRED": "EXPIRED",
}

_ASSET_STATUS = {
    "ASSET_STATUS_ACTIVE": "ACTIVE",
    "ASSET_STATUS_SHUTTING_DOWN": "SHUTTING_DOWN",
    "ASSET_STATUS_SETTLED": "SETTLED",
}

_RIGHTS_TYPE = {
    "RIGHTS_TYPE_UNSPECIFIED": "UNSPECIFIED",
    "RIGHTS_TYPE_ORIGINAL": "ORIGINAL",
    "RIGHTS_TYPE_CO_CREATION": "CO_CREATION",
    "RIGHTS_TYPE_LICENSED": "LICENSED",
    "RIGHTS_TYPE_COLLECTION": "COLLECTION",
}

_TASK_STATUS = {
    "TASK_STATUS_UNSPECIFIED": "UNSPECIFIED",
    "TASK_STATUS_SUBMITTED": "SUBMITTED",
    "TASK_STATUS_ASSIGNED": "ASSIGNED",
    "TASK_STATUS_COMMITTED": "COMMITTED",
    "TASK_STATUS_REVEALING": "REVEALING",
    "TASK_STATUS_SETTLED": "SETTLED",
    "TASK_STATUS_EXPIRED": "EXPIRED",
    "TASK_STATUS_DISPUTED": "DISPUTED",
}

_REG_STATUS = {
    "REGISTRATION_STATUS_ACTIVE": "ACTIVE",
    "REGISTRATION_STATUS_REPAID": "REPAID",
    "REGISTRATION_STATUS_DEFAULTED": "DEFAULTED",
}

_INVOCATION_STATUS = {
    "INVOCATION_STATUS_PENDING": "PENDING",
    "INVOCATION_STATUS_COMPLETED": "COMPLETED",
    "INVOCATION_STATUS_SUCCESS": "SUCCESS",
    "INVOCATION_STATUS_FAILED": "FAILED",
    "INVOCATION_STATUS_DISPUTED": "DISPUTED",
}

_DISPUTE_STATUS = {
    "DISPUTE_STATUS_OPEN": "OPEN",
    "DISPUTE_STATUS_RESOLVED": "RESOLVED",
    "DISPUTE_STATUS_REJECTED": "REJECTED",
}


def _leading_zero_bits(data: bytes) -> int:
    """Count leading zero bits in a byte sequence (matches Go bits.LeadingZeros8)."""
    total = 0
    for b in data:
        if b == 0:
            total += 8
        else:
            total += 8 - b.bit_length()
            break
    return total


def _safe_int(val: Any, default: int = 0) -> int:
    """Convert a value to int, handling strings from Cosmos big-int fields."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _coin_uoas(coin: Optional[Dict[str, Any]]) -> int:
    """Extract uoas amount from a Cosmos SDK Coin JSON object."""
    if not coin:
        return 0
    return _safe_int(coin.get("amount", 0))


class OasyceClient:
    """Synchronous client for the Oasyce L1 chain REST API.

    Parameters
    ----------
    base_url : str
        The base URL of the chain's REST API (gRPC-gateway).
        Defaults to ``http://localhost:1317``.
    timeout : float
        Request timeout in seconds.  Defaults to 10.

    Example
    -------
    >>> from oasyce_sdk import OasyceClient
    >>> client = OasyceClient("http://localhost:1317")
    >>> caps = client.list_capabilities(tag="llm")
    >>> print(caps[0].name)
    """

    def __init__(
        self,
        base_url: str = "http://localhost:1317",
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Perform a GET request and return the parsed JSON body."""
        url = f"{self._base_url}{path}"
        try:
            resp = self._session.get(url, params=params, timeout=self._timeout)
        except requests.exceptions.ConnectionError as exc:
            raise ConnectionError(f"Cannot connect to {url}: {exc}") from exc
        except requests.exceptions.Timeout as exc:
            raise TimeoutError(f"Request timed out: {url}") from exc
        except requests.exceptions.RequestException as exc:
            raise ConnectionError(f"Request failed: {url}: {exc}") from exc

        if resp.status_code == 404 or resp.status_code == 501:
            # gRPC-gateway returns 501 for unimplemented, 404 for not found
            return {"_status": resp.status_code, "_body": resp.text}
        if resp.status_code >= 400:
            raise HTTPError(resp.status_code, resp.text)

        try:
            return resp.json()
        except ValueError:
            raise HTTPError(resp.status_code, f"Invalid JSON: {resp.text!r}")

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Perform a POST request and return the parsed JSON body."""
        url = f"{self._base_url}{path}"
        try:
            resp = self._session.post(
                url, json=body, timeout=self._timeout
            )
        except requests.exceptions.ConnectionError as exc:
            raise ConnectionError(f"Cannot connect to {url}: {exc}") from exc
        except requests.exceptions.Timeout as exc:
            raise TimeoutError(f"Request timed out: {url}") from exc
        except requests.exceptions.RequestException as exc:
            raise ConnectionError(f"Request failed: {url}: {exc}") from exc

        if resp.status_code >= 400:
            raise HTTPError(resp.status_code, resp.text)

        try:
            return resp.json()
        except ValueError:
            raise HTTPError(resp.status_code, f"Invalid JSON: {resp.text!r}")

    def _check_not_found(self, data: Dict[str, Any], resource: str, rid: str) -> None:
        """Raise NotFoundError if the response indicates a missing resource."""
        if data.get("_status") in (404, 501):
            raise NotFoundError(resource, rid)
        # gRPC-gateway sometimes wraps errors in {"code": N, "message": "..."}
        if data.get("code") and "not found" in str(data.get("message", "")).lower():
            raise NotFoundError(resource, rid)

    # ------------------------------------------------------------------
    # Capability Marketplace
    # ------------------------------------------------------------------

    def _parse_capability(self, raw: Dict[str, Any]) -> Capability:
        price_coin = raw.get("price_per_call", {})
        return Capability(
            capability_id=raw.get("id", ""),
            name=raw.get("name", ""),
            provider=raw.get("provider", ""),
            description=raw.get("description", ""),
            endpoint_url=raw.get("endpoint_url", ""),
            price_per_call=_coin_uoas(price_coin),
            tags=raw.get("tags", []),
            rate_limit=_safe_int(raw.get("rate_limit")),
            total_calls=_safe_int(raw.get("total_calls")),
            total_earned=_safe_int(raw.get("total_earned")),
            avg_latency_ms=_safe_int(raw.get("avg_latency_ms")),
            success_rate=_safe_int(raw.get("success_rate")),
            active=raw.get("is_active", True),
        )

    def list_capabilities(
        self,
        tag: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> List[Capability]:
        """List registered capabilities, optionally filtered by tag or provider.

        When *provider* is given, the per-provider endpoint is used instead of
        the general listing.
        """
        if provider:
            data = self._get(
                f"/oasyce/capability/v1/capabilities/provider/{provider}"
            )
            items = data.get("capabilities", [])
        else:
            params: Dict[str, Any] = {}
            if tag:
                params["tag"] = tag
            data = self._get("/oasyce/capability/v1/capabilities", params=params)
            items = data.get("capabilities", [])
        return [self._parse_capability(c) for c in items]

    def get_capability(self, capability_id: str) -> Capability:
        """Query a single capability by ID."""
        data = self._get(f"/oasyce/capability/v1/capability/{capability_id}")
        self._check_not_found(data, "Capability", capability_id)
        return self._parse_capability(data.get("capability", data))

    def get_earnings(self, provider: str) -> Earnings:
        """Query total earnings for a capability provider."""
        data = self._get(f"/oasyce/capability/v1/earnings/{provider}")
        self._check_not_found(data, "Earnings", provider)
        coins = data.get("total_earned", [])
        total = 0
        for coin in coins:
            if coin.get("denom") == "uoas":
                total = _safe_int(coin.get("amount"))
                break
        return Earnings(
            provider=provider,
            total_earned_uoas=total,
            total_calls=_safe_int(data.get("total_calls")),
        )

    def _parse_invocation(self, raw: Dict[str, Any]) -> Invocation:
        status_raw = raw.get("status", "INVOCATION_STATUS_PENDING")
        status = _INVOCATION_STATUS.get(status_raw, status_raw)
        return Invocation(
            invocation_id=raw.get("id", ""),
            capability_id=raw.get("capability_id", ""),
            consumer=raw.get("consumer", ""),
            provider=raw.get("provider", ""),
            status=status,
            input_hash=raw.get("input_hash", ""),
            output_hash=raw.get("output_hash", ""),
            completed_height=_safe_int(raw.get("completed_height")),
            usage_report=raw.get("usage_report", ""),
        )

    def get_invocation(self, invocation_id: str) -> Invocation:
        """Query a single capability invocation by ID."""
        data = self._get(f"/oasyce/capability/v1/invocation/{invocation_id}")
        self._check_not_found(data, "Invocation", invocation_id)
        return self._parse_invocation(data.get("invocation", data))

    def get_capability_params(self) -> Dict[str, Any]:
        """Query the capability module parameters."""
        data = self._get("/oasyce/capability/v1/params")
        return data.get("params", data)

    # ------------------------------------------------------------------
    # Data Assets
    # ------------------------------------------------------------------

    def _parse_data_asset(self, raw: Dict[str, Any]) -> DataAsset:
        status_raw = raw.get("status", "ASSET_STATUS_ACTIVE")
        status = _ASSET_STATUS.get(status_raw, status_raw)
        rights_raw = raw.get("rights_type", "RIGHTS_TYPE_UNSPECIFIED")
        rights = _RIGHTS_TYPE.get(rights_raw, rights_raw)
        return DataAsset(
            asset_id=raw.get("id", ""),
            name=raw.get("name", ""),
            owner=raw.get("owner", ""),
            description=raw.get("description", ""),
            content_hash=raw.get("content_hash", ""),
            fingerprint=raw.get("fingerprint", ""),
            rights_type=rights,
            tags=raw.get("tags", []),
            total_shares=_safe_int(raw.get("total_shares")),
            status=status,
            version=_safe_int(raw.get("version", 1)),
            parent_asset_id=raw.get("parent_asset_id", ""),
            service_url=raw.get("service_url", ""),
        )

    def list_assets(
        self,
        tag: Optional[str] = None,
        owner: Optional[str] = None,
    ) -> List[DataAsset]:
        """List data assets, optionally filtered by tag and/or owner."""
        params: Dict[str, Any] = {}
        if tag:
            params["tag"] = tag
        if owner:
            params["owner"] = owner
        data = self._get("/oasyce/datarights/v1/data_assets", params=params)
        items = data.get("data_assets", [])
        return [self._parse_data_asset(a) for a in items]

    def get_asset(self, asset_id: str) -> DataAsset:
        """Query a single data asset by ID."""
        data = self._get(f"/oasyce/datarights/v1/data_asset/{asset_id}")
        self._check_not_found(data, "DataAsset", asset_id)
        return self._parse_data_asset(data.get("data_asset", data))

    def get_shares(self, asset_id: str) -> List[ShareHolder]:
        """Query all shareholders of a data asset."""
        data = self._get(f"/oasyce/datarights/v1/shares/{asset_id}")
        self._check_not_found(data, "Shares", asset_id)
        holders = data.get("shareholders", [])
        return [
            ShareHolder(
                address=h.get("address", ""),
                asset_id=h.get("asset_id", asset_id),
                shares=_safe_int(h.get("shares")),
            )
            for h in holders
        ]

    def get_bonding_curve(self, asset_id: str) -> BondingCurve:
        """Query the bonding curve state for a data asset."""
        data = self._get(f"/oasyce/settlement/v1/bonding_curve/{asset_id}")
        self._check_not_found(data, "BondingCurve", asset_id)
        state = data.get("state", {})
        current_price = data.get("current_price", {})
        return BondingCurve(
            asset_id=state.get("asset_id", asset_id),
            supply=_safe_int(state.get("total_shares")),
            reserve_uoas=_safe_int(state.get("reserve")),
            spot_price_uoas=_coin_uoas(current_price),
            price_factor=state.get("price_factor", ""),
            buyer_count=_safe_int(state.get("buyer_count")),
        )

    def get_access_level(self, asset_id: str, address: str) -> AccessLevel:
        """Query the access level for an address on a data asset."""
        data = self._get(f"/oasyce/datarights/v1/access_level/{asset_id}/{address}")
        self._check_not_found(data, "AccessLevel", f"{asset_id}/{address}")
        return AccessLevel(
            asset_id=asset_id,
            address=address,
            level=data.get("access_level", ""),
            equity_bps=_safe_int(data.get("equity_bps")),
            shares=_safe_int(data.get("shares")),
            total_shares=_safe_int(data.get("total_shares")),
        )

    def get_dispute(self, dispute_id: str) -> Dispute:
        """Query a single data rights dispute by ID."""
        data = self._get(f"/oasyce/datarights/v1/dispute/{dispute_id}")
        self._check_not_found(data, "Dispute", dispute_id)
        d = data.get("dispute", data)
        return Dispute(
            dispute_id=d.get("id", dispute_id),
            asset_id=d.get("asset_id", ""),
            creator=d.get("creator", ""),
            reason=d.get("reason", ""),
            status=_DISPUTE_STATUS.get(d.get("status", ""), d.get("status", "")),
            remedy=d.get("requested_remedy", ""),
        )

    def list_disputes(self, asset_id: Optional[str] = None) -> List[Dispute]:
        """List data rights disputes, optionally filtered by asset."""
        params: Dict[str, Any] = {}
        if asset_id:
            params["asset_id"] = asset_id
        data = self._get("/oasyce/datarights/v1/disputes", params=params)
        items = data.get("disputes", [])
        return [
            Dispute(
                dispute_id=d.get("id", ""),
                asset_id=d.get("asset_id", ""),
                creator=d.get("creator", ""),
                reason=d.get("reason", ""),
                status=_DISPUTE_STATUS.get(d.get("status", ""), d.get("status", "")),
                remedy=d.get("requested_remedy", ""),
            )
            for d in items
        ]

    def get_migration_path(self, source_id: str, target_id: str) -> MigrationPath:
        """Query a migration path between two data asset versions."""
        data = self._get(f"/oasyce/datarights/v1/migration_path/{source_id}/{target_id}")
        self._check_not_found(data, "MigrationPath", f"{source_id}/{target_id}")
        mp = data.get("migration_path", data)
        return MigrationPath(
            source_asset_id=mp.get("source_asset_id", source_id),
            target_asset_id=mp.get("target_asset_id", target_id),
            creator=mp.get("creator", ""),
            exchange_rate_bps=_safe_int(mp.get("exchange_rate_bps")),
            max_migrated_shares=_safe_int(mp.get("max_migrated_shares")),
            migrated_shares=_safe_int(mp.get("migrated_shares")),
            enabled=mp.get("enabled", True),
        )

    def get_asset_children(self, asset_id: str) -> List[DataAsset]:
        """Query child assets (forks) of a data asset."""
        data = self._get(f"/oasyce/datarights/v1/children/{asset_id}")
        items = data.get("data_assets", [])
        return [self._parse_data_asset(a) for a in items]

    def get_datarights_params(self) -> Dict[str, Any]:
        """Query the datarights module parameters."""
        data = self._get("/oasyce/datarights/v1/params")
        return data.get("params", data)

    # ------------------------------------------------------------------
    # Settlement
    # ------------------------------------------------------------------

    def _parse_escrow(self, raw: Dict[str, Any]) -> Escrow:
        status_raw = raw.get("status", "ESCROW_STATUS_UNSPECIFIED")
        status = _ESCROW_STATUS.get(status_raw, status_raw)
        return Escrow(
            escrow_id=raw.get("id", ""),
            creator=raw.get("creator", ""),
            provider=raw.get("provider", ""),
            amount_uoas=_coin_uoas(raw.get("amount", {})),
            status=status,
        )

    def get_escrow(self, escrow_id: str) -> Escrow:
        """Query a single escrow by ID."""
        data = self._get(f"/oasyce/settlement/v1/escrow/{escrow_id}")
        self._check_not_found(data, "Escrow", escrow_id)
        return self._parse_escrow(data.get("escrow", data))

    def list_escrows(self, creator: str) -> List[Escrow]:
        """List all escrows created by the given address."""
        data = self._get(f"/oasyce/settlement/v1/escrows/{creator}")
        items = data.get("escrows", [])
        return [self._parse_escrow(e) for e in items]

    def get_settlement_params(self) -> Dict[str, Any]:
        """Query the settlement module parameters."""
        data = self._get("/oasyce/settlement/v1/params")
        return data.get("params", data)

    # ------------------------------------------------------------------
    # Reputation
    # ------------------------------------------------------------------

    def _parse_reputation(self, raw: Dict[str, Any]) -> Reputation:
        return Reputation(
            address=raw.get("address", ""),
            score=_safe_int(raw.get("total_score")),
            total_feedback=_safe_int(raw.get("total_feedbacks")),
            verified_feedback=_safe_int(raw.get("verified_feedbacks")),
        )

    def get_reputation(self, address: str) -> Reputation:
        """Query the reputation score for an address."""
        data = self._get(f"/oasyce/reputation/v1/reputation/{address}")
        self._check_not_found(data, "Reputation", address)
        return self._parse_reputation(data.get("reputation", data))

    def get_leaderboard(self) -> List[Reputation]:
        """Query the reputation leaderboard (top-rated providers)."""
        data = self._get("/oasyce/reputation/v1/leaderboard")
        items = data.get("scores", [])
        return [self._parse_reputation(r) for r in items]

    def get_reputation_params(self) -> Dict[str, Any]:
        """Query the reputation module parameters."""
        data = self._get("/oasyce/reputation/v1/params")
        return data.get("params", data)

    # ------------------------------------------------------------------
    # Work
    # ------------------------------------------------------------------

    def _parse_task(self, raw: Dict[str, Any]) -> Task:
        status_raw = raw.get("status", "TASK_STATUS_UNSPECIFIED")
        status = _TASK_STATUS.get(status_raw, status_raw)
        assigned = raw.get("assigned_executors", [])
        return Task(
            task_id=str(raw.get("id", "")),
            creator=raw.get("creator", ""),
            task_type=raw.get("task_type", ""),
            bounty_uoas=_coin_uoas(raw.get("bounty", {})),
            deposit_uoas=_coin_uoas(raw.get("deposit", {})),
            status=status,
            redundancy=_safe_int(raw.get("redundancy")),
            assigned_executors=assigned,
            description=raw.get("description", ""),
            executor=assigned[0] if assigned else None,
        )

    def get_task(self, task_id: str) -> Task:
        """Query a single task by ID."""
        data = self._get(f"/oasyce/work/v1/task/{task_id}")
        self._check_not_found(data, "Task", task_id)
        return self._parse_task(data.get("task", data))

    def list_tasks(self, status: Optional[int] = None) -> List[Task]:
        """List tasks, optionally filtered by status integer.

        Status integers: 1=SUBMITTED, 2=ASSIGNED, 3=COMMITTED,
        4=REVEALING, 5=SETTLED, 6=EXPIRED, 7=DISPUTED.
        """
        if status is not None:
            data = self._get(f"/oasyce/work/v1/tasks/status/{status}")
        else:
            # Default to listing submitted tasks if no status given
            data = self._get("/oasyce/work/v1/tasks/status/1")
        items = data.get("tasks", [])
        return [self._parse_task(t) for t in items]

    def _parse_executor(self, raw: Dict[str, Any]) -> Executor:
        return Executor(
            address=raw.get("address", ""),
            supported_task_types=raw.get("supported_task_types", []),
            max_compute_units=_safe_int(raw.get("max_compute_units")),
            tasks_completed=_safe_int(raw.get("tasks_completed")),
            tasks_failed=_safe_int(raw.get("tasks_failed")),
            active=raw.get("active", True),
        )

    def list_executors(self) -> List[Executor]:
        """List all registered executor profiles."""
        data = self._get("/oasyce/work/v1/executors")
        items = data.get("executors", [])
        return [self._parse_executor(e) for e in items]

    def get_executor(self, address: str) -> Executor:
        """Query a single executor profile by address."""
        data = self._get(f"/oasyce/work/v1/executor/{address}")
        self._check_not_found(data, "Executor", address)
        return self._parse_executor(data.get("executor", data))

    def list_tasks_by_creator(self, creator: str) -> List[Task]:
        """List tasks submitted by a specific creator."""
        data = self._get(f"/oasyce/work/v1/tasks/creator/{creator}")
        items = data.get("tasks", [])
        return [self._parse_task(t) for t in items]

    def list_tasks_by_executor(self, executor: str) -> List[Task]:
        """List tasks assigned to a specific executor."""
        data = self._get(f"/oasyce/work/v1/tasks/executor/{executor}")
        items = data.get("tasks", [])
        return [self._parse_task(t) for t in items]

    def get_work_params(self) -> Dict[str, Any]:
        """Query the work module parameters."""
        data = self._get("/oasyce/work/v1/params")
        return data.get("params", data)

    def get_epoch_stats(self, epoch: int) -> EpochStats:
        """Query epoch statistics for the work module."""
        data = self._get(f"/oasyce/work/v1/epoch/{epoch}")
        self._check_not_found(data, "EpochStats", str(epoch))
        stats = data.get("stats", data)
        return EpochStats(
            epoch=_safe_int(stats.get("epoch", epoch)),
            tasks_submitted=_safe_int(stats.get("tasks_submitted")),
            tasks_settled=_safe_int(stats.get("tasks_settled")),
            total_bounty_uoas=_safe_int(stats.get("total_bounty")),
            total_burned_uoas=_safe_int(stats.get("total_burned")),
        )

    # ------------------------------------------------------------------
    # Onboarding
    # ------------------------------------------------------------------

    def _parse_registration(self, raw: Dict[str, Any]) -> Registration:
        status_raw = raw.get("status", "REGISTRATION_STATUS_ACTIVE")
        status = _REG_STATUS.get(status_raw, status_raw)
        return Registration(
            address=raw.get("address", ""),
            airdrop_amount=_safe_int(raw.get("airdrop_amount")),
            repaid_amount=_safe_int(raw.get("repaid_amount")),
            status=status,
        )

    def get_registration(self, address: str) -> Registration:
        """Query a user's onboarding registration."""
        data = self._get(f"/oasyce/onboarding/v1/registration/{address}")
        self._check_not_found(data, "Registration", address)
        return self._parse_registration(data.get("registration", data))

    def get_debt(self, address: str) -> Debt:
        """Query outstanding onboarding debt for an address."""
        data = self._get(f"/oasyce/onboarding/v1/debt/{address}")
        self._check_not_found(data, "Debt", address)
        reg = data.get("registration", data)
        airdrop = _safe_int(reg.get("airdrop_amount"))
        repaid = _safe_int(reg.get("repaid_amount"))
        status_raw = reg.get("status", "REGISTRATION_STATUS_ACTIVE")
        status = _REG_STATUS.get(status_raw, status_raw)
        return Debt(
            address=reg.get("address", address),
            total_debt=airdrop,
            repaid=repaid,
            remaining=max(0, airdrop - repaid),
            status=status,
        )

    def get_onboarding_params(self) -> Dict[str, Any]:
        """Query the onboarding module parameters."""
        data = self._get("/oasyce/onboarding/v1/params")
        return data.get("params", data)

    # ------------------------------------------------------------------
    # Bank / Auth / Tendermint (Cosmos SDK)
    # ------------------------------------------------------------------

    def get_balance(self, address: str) -> Balance:
        """Query all balances for an address, returning the uoas total."""
        data = self._get(f"/cosmos/bank/v1beta1/balances/{address}")
        self._check_not_found(data, "Balance", address)
        total_uoas = 0
        for coin in data.get("balances", []):
            if coin.get("denom") == "uoas":
                total_uoas = _safe_int(coin.get("amount"))
                break
        return Balance(
            address=address,
            amount_uoas=total_uoas,
            amount_oas=total_uoas / _UOAS_PER_OAS,
        )

    def get_account(self, address: str) -> Account:
        """Query account info (account number, sequence) for transaction signing."""
        data = self._get(f"/cosmos/auth/v1beta1/accounts/{address}")
        self._check_not_found(data, "Account", address)
        acct = data.get("account", {})
        # BaseAccount may be nested in a type wrapper
        if "base_account" in acct:
            acct = acct["base_account"]
        return Account(
            address=acct.get("address", address),
            account_number=_safe_int(acct.get("account_number")),
            sequence=_safe_int(acct.get("sequence")),
        )

    def get_latest_block(self) -> Block:
        """Query the latest block from the Tendermint RPC via REST gateway."""
        data = self._get("/cosmos/base/tendermint/v1beta1/blocks/latest")
        block = data.get("block", {})
        header = block.get("header", {})
        block_id = data.get("block_id", {})
        txs = block.get("data", {}).get("txs", [])
        return Block(
            height=_safe_int(header.get("height")),
            time=header.get("time", ""),
            chain_id=header.get("chain_id", ""),
            proposer_address=header.get("proposer_address", ""),
            num_txs=len(txs),
        )

    # ------------------------------------------------------------------
    # Transaction builders
    # ------------------------------------------------------------------
    # These produce unsigned Cosmos SDK tx JSON that can be signed offline
    # and then passed to broadcast_tx().  They do NOT require a private key.

    @staticmethod
    def _cosmos_msg(type_url: str, value: Dict[str, Any]) -> Dict[str, Any]:
        """Wrap a message body in the Cosmos SDK Any envelope."""
        return {"@type": type_url, **value}

    @staticmethod
    def _coin(amount: int, denom: str = "uoas") -> Dict[str, str]:
        return {"denom": denom, "amount": str(amount)}

    def build_register_capability(
        self,
        sender: str,
        name: str,
        endpoint: str,
        price_uoas: int,
        tags: Optional[List[str]] = None,
        description: str = "",
        rate_limit: int = 100,
    ) -> dict:
        """Build an unsigned MsgRegisterCapability transaction body."""
        msg = self._cosmos_msg(
            "/oasyce.capability.v1.MsgRegisterCapability",
            {
                "creator": sender,
                "name": name,
                "description": description,
                "endpoint_url": endpoint,
                "price_per_call": self._coin(price_uoas),
                "tags": tags or [],
                "rate_limit": str(rate_limit),
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_invoke_capability(
        self,
        sender: str,
        capability_id: str,
        input_data: Optional[bytes] = None,
    ) -> dict:
        """Build an unsigned MsgInvokeCapability transaction body."""
        msg = self._cosmos_msg(
            "/oasyce.capability.v1.MsgInvokeCapability",
            {
                "creator": sender,
                "capability_id": capability_id,
                "input": base64.b64encode(input_data or b"").decode(),
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_register_asset(
        self,
        sender: str,
        name: str,
        content_hash: str,
        tags: Optional[List[str]] = None,
        description: str = "",
        rights_type: str = "RIGHTS_TYPE_ORIGINAL",
        service_url: str = "",
    ) -> dict:
        """Build an unsigned MsgRegisterDataAsset transaction body."""
        msg = self._cosmos_msg(
            "/oasyce.datarights.v1.MsgRegisterDataAsset",
            {
                "creator": sender,
                "name": name,
                "description": description,
                "content_hash": content_hash,
                "rights_type": rights_type,
                "tags": tags or [],
                "co_creators": [],
                "parent_asset_id": "",
                "service_url": service_url,
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_update_service_url(
        self,
        sender: str,
        asset_id: str,
        service_url: str,
    ) -> dict:
        """Build an unsigned MsgUpdateServiceUrl transaction body."""
        msg = self._cosmos_msg(
            "/oasyce.datarights.v1.MsgUpdateServiceUrl",
            {
                "creator": sender,
                "asset_id": asset_id,
                "service_url": service_url,
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_buy_shares(
        self,
        sender: str,
        asset_id: str,
        amount_uoas: int,
    ) -> dict:
        """Build an unsigned MsgBuyShares transaction body."""
        msg = self._cosmos_msg(
            "/oasyce.datarights.v1.MsgBuyShares",
            {
                "creator": sender,
                "asset_id": asset_id,
                "amount": self._coin(amount_uoas),
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_sell_shares(
        self,
        sender: str,
        asset_id: str,
        shares: int,
    ) -> dict:
        """Build an unsigned MsgSellShares transaction body."""
        msg = self._cosmos_msg(
            "/oasyce.datarights.v1.MsgSellShares",
            {
                "creator": sender,
                "asset_id": asset_id,
                "shares": str(shares),
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    # --- Capability: challenge window ---

    def build_complete_invocation(
        self,
        sender: str,
        invocation_id: str,
        output_hash: str,
        usage_report: str = "",
    ) -> dict:
        """Build an unsigned MsgCompleteInvocation (starts challenge window)."""
        msg = self._cosmos_msg(
            "/oasyce.capability.v1.MsgCompleteInvocation",
            {
                "creator": sender,
                "invocation_id": invocation_id,
                "output_hash": output_hash,
                "usage_report": usage_report,
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_fail_invocation(
        self, sender: str, invocation_id: str,
    ) -> dict:
        """Build an unsigned MsgFailInvocation."""
        msg = self._cosmos_msg(
            "/oasyce.capability.v1.MsgFailInvocation",
            {"creator": sender, "invocation_id": invocation_id},
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_claim_invocation(
        self, sender: str, invocation_id: str,
    ) -> dict:
        """Build an unsigned MsgClaimInvocation (after challenge window)."""
        msg = self._cosmos_msg(
            "/oasyce.capability.v1.MsgClaimInvocation",
            {"creator": sender, "invocation_id": invocation_id},
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_dispute_invocation(
        self, sender: str, invocation_id: str, reason: str,
    ) -> dict:
        """Build an unsigned MsgDisputeInvocation (within challenge window)."""
        msg = self._cosmos_msg(
            "/oasyce.capability.v1.MsgDisputeInvocation",
            {
                "creator": sender,
                "invocation_id": invocation_id,
                "reason": reason,
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    # --- Reputation ---

    def build_submit_feedback(
        self,
        sender: str,
        invocation_id: str,
        rating: int,
        comment: str = "",
    ) -> dict:
        """Build an unsigned MsgSubmitFeedback (rating 0-500)."""
        msg = self._cosmos_msg(
            "/oasyce.reputation.v1.MsgSubmitFeedback",
            {
                "creator": sender,
                "invocation_id": invocation_id,
                "rating": rating,
                "comment": comment,
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_report_misbehavior(
        self,
        sender: str,
        target: str,
        evidence_type: str,
        evidence: bytes = b"",
    ) -> dict:
        """Build an unsigned MsgReportMisbehavior."""
        msg = self._cosmos_msg(
            "/oasyce.reputation.v1.MsgReportMisbehavior",
            {
                "creator": sender,
                "target": target,
                "evidence_type": evidence_type,
                "evidence": base64.b64encode(evidence).decode() if evidence else "",
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    # --- Work (Proof of Useful Work) ---

    def build_register_executor(
        self,
        sender: str,
        task_types: List[str],
        max_compute_units: int,
    ) -> dict:
        """Build an unsigned MsgRegisterExecutor."""
        msg = self._cosmos_msg(
            "/oasyce.work.v1.MsgRegisterExecutor",
            {
                "executor": sender,
                "supported_task_types": task_types,
                "max_compute_units": str(max_compute_units),
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_update_executor(
        self,
        sender: str,
        task_types: Optional[List[str]] = None,
        max_compute_units: Optional[int] = None,
        active: Optional[bool] = None,
    ) -> dict:
        """Build an unsigned MsgUpdateExecutor."""
        value: Dict[str, Any] = {"executor": sender}
        if task_types is not None:
            value["supported_task_types"] = task_types
        if max_compute_units is not None:
            value["max_compute_units"] = str(max_compute_units)
        if active is not None:
            value["active"] = active
        msg = self._cosmos_msg("/oasyce.work.v1.MsgUpdateExecutor", value)
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_submit_task(
        self,
        sender: str,
        task_type: str,
        input_hash: bytes,
        input_uri: str,
        max_compute_units: int,
        bounty_uoas: int,
        redundancy: int = 1,
        timeout_blocks: int = 100,
    ) -> dict:
        """Build an unsigned MsgSubmitTask."""
        msg = self._cosmos_msg(
            "/oasyce.work.v1.MsgSubmitTask",
            {
                "creator": sender,
                "task_type": task_type,
                "input_hash": base64.b64encode(input_hash).decode(),
                "input_uri": input_uri,
                "max_compute_units": str(max_compute_units),
                "bounty": self._coin(bounty_uoas),
                "redundancy": redundancy,
                "timeout_blocks": str(timeout_blocks),
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_commit_result(
        self,
        sender: str,
        task_id: int,
        commit_hash: bytes,
    ) -> dict:
        """Build an unsigned MsgCommitResult."""
        msg = self._cosmos_msg(
            "/oasyce.work.v1.MsgCommitResult",
            {
                "executor": sender,
                "task_id": str(task_id),
                "commit_hash": base64.b64encode(commit_hash).decode(),
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_reveal_result(
        self,
        sender: str,
        task_id: int,
        output_hash: bytes,
        output_uri: str,
        compute_units_used: int,
        salt: bytes,
        unavailable: bool = False,
    ) -> dict:
        """Build an unsigned MsgRevealResult."""
        msg = self._cosmos_msg(
            "/oasyce.work.v1.MsgRevealResult",
            {
                "executor": sender,
                "task_id": str(task_id),
                "output_hash": base64.b64encode(output_hash).decode(),
                "output_uri": output_uri,
                "compute_units_used": str(compute_units_used),
                "salt": base64.b64encode(salt).decode(),
                "unavailable": unavailable,
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_dispute_result(
        self,
        sender: str,
        task_id: int,
        reason: str,
        bond_uoas: int,
    ) -> dict:
        """Build an unsigned MsgDisputeResult."""
        msg = self._cosmos_msg(
            "/oasyce.work.v1.MsgDisputeResult",
            {
                "challenger": sender,
                "task_id": str(task_id),
                "reason": reason,
                "bond": self._coin(bond_uoas),
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    # --- Settlement ---

    def build_create_escrow(
        self,
        sender: str,
        amount_uoas: int,
        capability_id: str = "",
        asset_id: str = "",
    ) -> dict:
        """Build an unsigned MsgCreateEscrow."""
        msg = self._cosmos_msg(
            "/oasyce.settlement.v1.MsgCreateEscrow",
            {
                "creator": sender,
                "capability_id": capability_id,
                "asset_id": asset_id,
                "amount": self._coin(amount_uoas),
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_release_escrow(self, sender: str, escrow_id: str) -> dict:
        """Build an unsigned MsgReleaseEscrow."""
        msg = self._cosmos_msg(
            "/oasyce.settlement.v1.MsgReleaseEscrow",
            {"creator": sender, "escrow_id": escrow_id},
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_refund_escrow(self, sender: str, escrow_id: str) -> dict:
        """Build an unsigned MsgRefundEscrow."""
        msg = self._cosmos_msg(
            "/oasyce.settlement.v1.MsgRefundEscrow",
            {"creator": sender, "escrow_id": escrow_id},
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    # --- Onboarding ---

    def build_self_register(self, sender: str, nonce: int) -> dict:
        """Build an unsigned MsgSelfRegister (after solving PoW)."""
        msg = self._cosmos_msg(
            "/oasyce.onboarding.v1.MsgSelfRegister",
            {"creator": sender, "nonce": str(nonce)},
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_repay_debt(self, sender: str, amount_uoas: int) -> dict:
        """Build an unsigned MsgRepayDebt."""
        msg = self._cosmos_msg(
            "/oasyce.onboarding.v1.MsgRepayDebt",
            {"creator": sender, "amount": str(amount_uoas)},
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    # --- Datarights: disputes, lifecycle, migration ---

    def build_file_dispute(
        self,
        sender: str,
        asset_id: str,
        reason: str,
        evidence: bytes = b"",
        remedy: str = "DISPUTE_REMEDY_DELIST",
    ) -> dict:
        """Build an unsigned MsgFileDispute."""
        msg = self._cosmos_msg(
            "/oasyce.datarights.v1.MsgFileDispute",
            {
                "creator": sender,
                "asset_id": asset_id,
                "reason": reason,
                "evidence": base64.b64encode(evidence).decode() if evidence else "",
                "requested_remedy": remedy,
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_initiate_shutdown(self, sender: str, asset_id: str) -> dict:
        """Build an unsigned MsgInitiateShutdown (owner graceful shutdown)."""
        msg = self._cosmos_msg(
            "/oasyce.datarights.v1.MsgInitiateShutdown",
            {"creator": sender, "asset_id": asset_id},
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_claim_settlement(self, sender: str, asset_id: str) -> dict:
        """Build an unsigned MsgClaimSettlement (pro-rata reserve payout after shutdown)."""
        msg = self._cosmos_msg(
            "/oasyce.datarights.v1.MsgClaimSettlement",
            {"creator": sender, "asset_id": asset_id},
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_create_migration(
        self,
        sender: str,
        source_asset_id: str,
        target_asset_id: str,
        exchange_rate_bps: int,
        max_migrated_shares: int,
    ) -> dict:
        """Build an unsigned MsgCreateMigrationPath."""
        msg = self._cosmos_msg(
            "/oasyce.datarights.v1.MsgCreateMigrationPath",
            {
                "creator": sender,
                "source_asset_id": source_asset_id,
                "target_asset_id": target_asset_id,
                "exchange_rate_bps": exchange_rate_bps,
                "max_migrated_shares": str(max_migrated_shares),
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_migrate(
        self,
        sender: str,
        source_asset_id: str,
        target_asset_id: str,
        shares: int,
    ) -> dict:
        """Build an unsigned MsgMigrate (burns source shares, mints target)."""
        msg = self._cosmos_msg(
            "/oasyce.datarights.v1.MsgMigrate",
            {
                "creator": sender,
                "source_asset_id": source_asset_id,
                "target_asset_id": target_asset_id,
                "shares": str(shares),
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def broadcast_tx(self, signed_tx: dict) -> TxResult:
        """Broadcast a signed transaction to the chain.

        Parameters
        ----------
        signed_tx : dict
            A fully signed Cosmos SDK transaction in JSON format.
            Pass the output of a signing tool or ``build_*`` after signing.

        Returns
        -------
        TxResult
            The broadcast result including tx_hash and success status.

        Raises
        ------
        ChainError
            If the transaction is rejected at CheckTx stage.
        """
        body = {
            "tx_bytes": signed_tx.get("tx_bytes", ""),
            "mode": signed_tx.get("mode", "BROADCAST_MODE_SYNC"),
        }
        # If the caller passes a full tx object, encode it
        if "tx_bytes" not in signed_tx and "body" in signed_tx:
            body = {
                "tx_bytes": base64.b64encode(
                    json.dumps(signed_tx).encode()
                ).decode(),
                "mode": "BROADCAST_MODE_SYNC",
            }

        data = self._post("/cosmos/tx/v1beta1/txs", body)
        tx_response = data.get("tx_response", {})
        code = _safe_int(tx_response.get("code"))
        raw_log = tx_response.get("raw_log", "")
        tx_hash = tx_response.get("txhash", "")
        return TxResult(
            tx_hash=tx_hash,
            code=code,
            raw_log=raw_log,
            success=(code == 0),
        )

    # ------------------------------------------------------------------
    # Anchor (Thronglets → Chain trace anchoring)
    # ------------------------------------------------------------------

    @staticmethod
    def _bytes_from_b64_or_hex(val: str) -> str:
        """Decode a base64 or hex string to hex.

        Chain REST returns bytes fields as base64; we normalize to hex
        for consistency with Thronglets trace IDs.
        """
        if not val:
            return ""
        try:
            raw = base64.b64decode(val)
            return raw.hex()
        except Exception:
            return val  # already hex or other format

    def _parse_anchor(self, raw: Dict[str, Any]) -> AnchorRecord:
        return AnchorRecord(
            trace_id=self._bytes_from_b64_or_hex(raw.get("trace_id", "")),
            node_pubkey=self._bytes_from_b64_or_hex(raw.get("node_pubkey", "")),
            capability=raw.get("capability", ""),
            outcome=_safe_int(raw.get("outcome")),
            timestamp=_safe_int(raw.get("timestamp")),
            anchor_height=_safe_int(raw.get("anchor_height")),
            trace_signature=self._bytes_from_b64_or_hex(raw.get("trace_signature", "")),
        )

    def get_anchor(self, trace_id_hex: str) -> AnchorRecord:
        """Query an anchor record by trace ID (hex-encoded).

        Uses gRPC directly since anchor module has bytes path params.
        """
        trace_id_b64 = base64.b64encode(bytes.fromhex(trace_id_hex)).decode()
        data = self._get(f"/oasyce/anchor/v1/anchor/{trace_id_b64}")
        self._check_not_found(data, "Anchor", trace_id_hex)
        return self._parse_anchor(data.get("anchor", data))

    def is_anchored(self, trace_id_hex: str) -> bool:
        """Check if a trace has been anchored on-chain."""
        trace_id_b64 = base64.b64encode(bytes.fromhex(trace_id_hex)).decode()
        data = self._get(f"/oasyce/anchor/v1/is_anchored/{trace_id_b64}")
        if data.get("_status") in (404, 501):
            return False
        return data.get("anchored", False)

    def anchors_by_capability(
        self, capability: str, limit: int = 100,
    ) -> List[AnchorRecord]:
        """List anchor records filtered by capability."""
        params: Dict[str, Any] = {}
        if limit != 100:
            params["pagination.limit"] = str(limit)
        data = self._get(
            f"/oasyce/anchor/v1/by_capability/{capability}", params=params,
        )
        items = data.get("anchors", [])
        return [self._parse_anchor(a) for a in items]

    def anchors_by_node(
        self, node_pubkey_hex: str, limit: int = 100,
    ) -> List[AnchorRecord]:
        """List anchor records filtered by node public key (hex-encoded)."""
        node_b64 = base64.b64encode(bytes.fromhex(node_pubkey_hex)).decode()
        params: Dict[str, Any] = {}
        if limit != 100:
            params["pagination.limit"] = str(limit)
        data = self._get(f"/oasyce/anchor/v1/by_node/{node_b64}", params=params)
        items = data.get("anchors", [])
        return [self._parse_anchor(a) for a in items]

    def build_anchor_trace(
        self,
        sender: str,
        trace_id_hex: str,
        node_pubkey_hex: str,
        capability: str,
        outcome: int,
        timestamp: int,
        trace_signature_hex: str,
    ) -> dict:
        """Build an unsigned MsgAnchorTrace transaction body."""
        msg = self._cosmos_msg(
            "/oasyce.anchor.v1.MsgAnchorTrace",
            {
                "signer": sender,
                "trace_id": base64.b64encode(bytes.fromhex(trace_id_hex)).decode(),
                "node_pubkey": base64.b64encode(bytes.fromhex(node_pubkey_hex)).decode(),
                "capability": capability,
                "outcome": outcome,
                "timestamp": str(timestamp),
                "trace_signature": base64.b64encode(bytes.fromhex(trace_signature_hex)).decode(),
            },
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    def build_anchor_batch(
        self,
        sender: str,
        traces: List[Dict[str, Any]],
    ) -> dict:
        """Build an unsigned MsgAnchorBatch transaction body.

        Each trace dict must have: trace_id_hex, node_pubkey_hex,
        capability, outcome, timestamp, trace_signature_hex.
        Max 50 traces per batch.
        """
        anchor_msgs = []
        for t in traces[:50]:
            anchor_msgs.append({
                "signer": sender,
                "trace_id": base64.b64encode(bytes.fromhex(t["trace_id_hex"])).decode(),
                "node_pubkey": base64.b64encode(bytes.fromhex(t["node_pubkey_hex"])).decode(),
                "capability": t["capability"],
                "outcome": t["outcome"],
                "timestamp": str(t["timestamp"]),
                "trace_signature": base64.b64encode(bytes.fromhex(t["trace_signature_hex"])).decode(),
            })
        msg = self._cosmos_msg(
            "/oasyce.anchor.v1.MsgAnchorBatch",
            {"signer": sender, "anchors": anchor_msgs},
        )
        return {"body": {"messages": [msg], "memo": ""}, "auth_info": {}, "signatures": []}

    # ------------------------------------------------------------------
    # Delegate (multi-agent delegation)
    # ------------------------------------------------------------------

    def get_delegate_policy(self, principal: str) -> DelegatePolicy:
        """Query a principal's delegation policy."""
        data = self._get(f"/oasyce/delegate/v1/policy/{principal}")
        self._check_not_found(data, "DelegatePolicy", principal)
        p = data.get("policy", data)
        return DelegatePolicy(
            principal=p.get("principal", ""),
            per_tx_limit_uoas=int(p.get("per_tx_limit", {}).get("amount", "0")),
            window_limit_uoas=int(p.get("window_limit", {}).get("amount", "0")),
            window_seconds=int(p.get("window_seconds", "0")),
            allowed_msgs=p.get("allowed_msgs", []),
            expiration_seconds=int(p.get("expiration_seconds", "0")),
            created_at_seconds=int(p.get("created_at_seconds", "0")),
        )

    def get_delegates(self, principal: str) -> List[DelegateRecord]:
        """List all delegates enrolled under a principal."""
        data = self._get(f"/oasyce/delegate/v1/delegates/{principal}")
        items = data.get("delegates", [])
        return [
            DelegateRecord(
                delegate=d.get("delegate", ""),
                principal=d.get("principal", ""),
                label=d.get("label", ""),
                enrolled_at_seconds=int(d.get("enrolled_at_seconds", "0")),
            )
            for d in items
        ]

    def get_delegate_spend(self, principal: str) -> SpendWindow:
        """Query current spending window for a principal."""
        data = self._get(f"/oasyce/delegate/v1/spend/{principal}")
        w = data.get("spend_window", data)
        return SpendWindow(
            principal=w.get("principal", ""),
            window_start=int(w.get("window_start", "0")),
            spent_uoas=int(w.get("spent", {}).get("amount", "0")),
        )

    def get_principal(self, delegate: str) -> str:
        """Query which principal a delegate belongs to (reverse lookup)."""
        data = self._get(f"/oasyce/delegate/v1/principal/{delegate}")
        return data.get("principal", "")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def health(self) -> bool:
        """Check whether the chain node is reachable by fetching the latest block.

        Returns True if the node responds, False otherwise.
        """
        try:
            block = self.get_latest_block()
            return block.height > 0
        except (ConnectionError, TimeoutError, HTTPError, Exception):
            return False

    @staticmethod
    def solve_pow(address: str, difficulty: int = 16) -> PowResult:
        """Solve a proof-of-work puzzle for self-registration.

        Finds a nonce such that ``sha256(address || nonce_le_bytes)`` has at
        least *difficulty* leading zero bits.  Matches the Go chain verifier
        exactly (little-endian uint64 nonce appended to address string bytes).
        """
        nonce = random.randint(0, 2**64 - 1)
        addr_bytes = address.encode()
        attempts = 0

        while True:
            data = addr_bytes + struct.pack("<Q", nonce)
            h = hashlib.sha256(data).digest()
            if _leading_zero_bits(h) >= difficulty:
                return PowResult(
                    address=address,
                    nonce=nonce,
                    difficulty=difficulty,
                    hash_hex=h.hex(),
                    attempts=attempts,
                )
            nonce = (nonce + 1) & 0xFFFFFFFFFFFFFFFF
            attempts += 1

    @staticmethod
    def oas_to_uoas(oas: float) -> int:
        """Convert OAS to uoas (micro-OAS).

        >>> OasyceClient.oas_to_uoas(1.5)
        1500000
        """
        return int(oas * _UOAS_PER_OAS)

    @staticmethod
    def uoas_to_oas(uoas: int) -> float:
        """Convert uoas (micro-OAS) to OAS.

        >>> OasyceClient.uoas_to_oas(2500000)
        2.5
        """
        return uoas / _UOAS_PER_OAS

    def __repr__(self) -> str:
        return f"OasyceClient(base_url={self._base_url!r}, timeout={self._timeout})"
