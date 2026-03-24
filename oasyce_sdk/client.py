"""Main client for the Oasyce L1 chain REST API.

Thread-safe, stateless client that wraps the Cosmos SDK REST gateway
(default ``http://localhost:1317``) and returns typed dataclasses
for every response.
"""

from __future__ import annotations

import base64
import json
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
