"""NativeSigner — pure-Python Cosmos SDK transaction signing for Oasyce.

Signs and broadcasts transactions without any Go binary dependency.

    from oasyce_sdk.crypto import Wallet, NativeSigner
    from oasyce_sdk import OasyceClient

    wallet = Wallet.create()
    client = OasyceClient("http://localhost:1317")
    signer = NativeSigner(wallet, client, chain_id="oasyce-testnet-1")

    result = signer.register_capability(
        name="My AI", endpoint="https://...", price_uoas=500000
    )
    print(result.tx_hash, result.success)
"""

import base64
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .protobuf import build_tx_bytes, encode_msg, encode_msg_as_any
from .wallet import Wallet

logger = logging.getLogger(__name__)

# Default TX parameters
DEFAULT_GAS_LIMIT = 200000
DEFAULT_FEE = 10000  # 10000 uoas = 0.01 OAS
BROADCAST_MODE = "BROADCAST_MODE_SYNC"


@dataclass
class TxResult:
    """Result of a signed and broadcast transaction."""
    tx_hash: str
    success: bool
    code: int
    raw_log: str
    height: int = 0


class NativeSigner:
    """Sign and broadcast Oasyce transactions using a pure-Python wallet.

    Handles account number/sequence queries, protobuf encoding, secp256k1
    signing, and REST broadcast — zero Go dependency.
    """

    def __init__(
        self,
        wallet: Wallet,
        client,  # OasyceClient instance
        chain_id: str = "oasyce-testnet-1",
        gas_limit: int = DEFAULT_GAS_LIMIT,
        fee: int = DEFAULT_FEE,
        memo: str = "",
    ):
        self.wallet = wallet
        self.client = client
        self.chain_id = chain_id
        self.gas_limit = gas_limit
        self.fee = fee
        self.memo = memo
        # Cached account info (refreshed on sequence mismatch)
        self._account_number: Optional[int] = None
        self._sequence: Optional[int] = None

    def _refresh_account(self):
        """Fetch account number and sequence from chain."""
        acct = self.client.get_account(self.wallet.address)
        self._account_number = acct.account_number
        self._sequence = acct.sequence
        logger.debug(
            "Account %s: number=%d, sequence=%d",
            self.wallet.address, self._account_number, self._sequence,
        )

    def _ensure_account(self):
        """Ensure we have account info cached."""
        if self._account_number is None:
            self._refresh_account()

    def sign_and_broadcast(
        self,
        messages: List[Tuple[str, Dict[str, Any]]],
        memo: Optional[str] = None,
        gas_limit: Optional[int] = None,
        fee: Optional[int] = None,
    ) -> TxResult:
        """Sign a list of messages and broadcast to chain.

        Args:
            messages: List of (type_url, fields) tuples.
            memo: Optional memo (overrides instance default).
            gas_limit: Optional gas limit override.
            fee: Optional fee override.

        Returns:
            TxResult with tx_hash, success, code, raw_log.
        """
        self._ensure_account()

        tx_bytes = build_tx_bytes(
            messages=messages,
            pubkey_bytes=self.wallet.public_key_bytes,
            sequence=self._sequence,
            account_number=self._account_number,
            chain_id=self.chain_id,
            fee_amount=fee or self.fee,
            gas_limit=gas_limit or self.gas_limit,
            memo=memo or self.memo,
            sign_fn=self.wallet.sign_digest,
        )

        result = self._broadcast(tx_bytes)

        # On success, increment sequence locally to avoid re-querying
        if result.success:
            self._sequence += 1
        elif result.code == 32:
            # Account sequence mismatch — refresh and retry once
            logger.warning("Sequence mismatch (code 32), refreshing and retrying")
            self._refresh_account()
            tx_bytes = build_tx_bytes(
                messages=messages,
                pubkey_bytes=self.wallet.public_key_bytes,
                sequence=self._sequence,
                account_number=self._account_number,
                chain_id=self.chain_id,
                fee_amount=fee or self.fee,
                gas_limit=gas_limit or self.gas_limit,
                memo=memo or self.memo,
                sign_fn=self.wallet.sign_digest,
            )
            result = self._broadcast(tx_bytes)
            if result.success:
                self._sequence += 1

        return result

    def _broadcast(self, tx_bytes: bytes) -> TxResult:
        """POST signed transaction to chain REST endpoint."""
        import json
        import urllib.request

        tx_b64 = base64.b64encode(tx_bytes).decode()
        payload = json.dumps({
            "tx_bytes": tx_b64,
            "mode": BROADCAST_MODE,
        }).encode()

        url = f"{self.client._base_url}/cosmos/tx/v1beta1/txs"
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            logger.error("Broadcast HTTP %d: %s", e.code, body)
            return TxResult(tx_hash="", success=False, code=e.code, raw_log=body)
        except Exception as e:
            logger.error("Broadcast error: %s", e)
            return TxResult(tx_hash="", success=False, code=-1, raw_log=str(e))

        tx_response = data.get("tx_response", {})
        code = int(tx_response.get("code", -1))
        return TxResult(
            tx_hash=tx_response.get("txhash", ""),
            success=(code == 0),
            code=code,
            raw_log=tx_response.get("raw_log", ""),
            height=int(tx_response.get("height", 0)),
        )

    # ------------------------------------------------------------------
    # Convenience methods — one method per message type
    # ------------------------------------------------------------------

    def send(self, to_address: str, amount_uoas: int) -> TxResult:
        """Send tokens."""
        return self.sign_and_broadcast([(
            "/cosmos.bank.v1beta1.MsgSend",
            {
                "from_address": self.wallet.address,
                "to_address": to_address,
                "amount": [{"denom": "uoas", "amount": str(amount_uoas)}],
            },
        )])

    def self_register(self, nonce: int) -> TxResult:
        """PoW self-registration on chain."""
        return self.sign_and_broadcast([(
            "/oasyce.onboarding.v1.MsgSelfRegister",
            {"creator": self.wallet.address, "nonce": nonce},
        )])

    def register_capability(
        self,
        name: str,
        endpoint: str,
        price_uoas: int,
        tags: Optional[List[str]] = None,
        description: str = "",
        rate_limit: int = 100,
    ) -> TxResult:
        """Register an AI capability on chain."""
        return self.sign_and_broadcast([(
            "/oasyce.capability.v1.MsgRegisterCapability",
            {
                "creator": self.wallet.address,
                "name": name,
                "description": description,
                "endpoint_url": endpoint,
                "price_per_call": {"denom": "uoas", "amount": str(price_uoas)},
                "tags": tags or [],
                "rate_limit": rate_limit,
            },
        )])

    def invoke_capability(
        self,
        capability_id: str,
        input_data: Optional[bytes] = None,
    ) -> TxResult:
        """Invoke an AI capability."""
        return self.sign_and_broadcast([(
            "/oasyce.capability.v1.MsgInvokeCapability",
            {
                "creator": self.wallet.address,
                "capability_id": capability_id,
                "input": base64.b64encode(input_data or b"").decode(),
            },
        )])

    def complete_invocation(
        self,
        invocation_id: str,
        output_hash: str,
        usage_report: str = "",
    ) -> TxResult:
        """Complete an invocation (provider side)."""
        return self.sign_and_broadcast([(
            "/oasyce.capability.v1.MsgCompleteInvocation",
            {
                "creator": self.wallet.address,
                "invocation_id": invocation_id,
                "output_hash": output_hash,
                "usage_report": usage_report,
            },
        )])

    def claim_invocation(self, invocation_id: str) -> TxResult:
        """Claim payment after challenge window."""
        return self.sign_and_broadcast([(
            "/oasyce.capability.v1.MsgClaimInvocation",
            {"creator": self.wallet.address, "invocation_id": invocation_id},
        )])

    def dispute_invocation(self, invocation_id: str, reason: str) -> TxResult:
        """Dispute an invocation within challenge window."""
        return self.sign_and_broadcast([(
            "/oasyce.capability.v1.MsgDisputeInvocation",
            {
                "creator": self.wallet.address,
                "invocation_id": invocation_id,
                "reason": reason,
            },
        )])

    def register_asset(
        self,
        name: str,
        content_hash: str,
        tags: Optional[List[str]] = None,
        description: str = "",
        rights_type: str = "RIGHTS_TYPE_ORIGINAL",
        service_url: str = "",
    ) -> TxResult:
        """Register a data asset."""
        return self.sign_and_broadcast([(
            "/oasyce.datarights.v1.MsgRegisterDataAsset",
            {
                "creator": self.wallet.address,
                "name": name,
                "description": description,
                "content_hash": content_hash,
                "rights_type": rights_type,
                "tags": tags or [],
                "parent_asset_id": "",
                "service_url": service_url,
            },
        )])

    def buy_shares(self, asset_id: str, amount_uoas: int) -> TxResult:
        """Buy shares of a data asset on the bonding curve."""
        return self.sign_and_broadcast([(
            "/oasyce.datarights.v1.MsgBuyShares",
            {
                "creator": self.wallet.address,
                "asset_id": asset_id,
                "amount": {"denom": "uoas", "amount": str(amount_uoas)},
            },
        )])

    def sell_shares(self, asset_id: str, shares: int) -> TxResult:
        """Sell shares of a data asset."""
        return self.sign_and_broadcast([(
            "/oasyce.datarights.v1.MsgSellShares",
            {
                "creator": self.wallet.address,
                "asset_id": asset_id,
                "shares": str(shares),
            },
        )])

    def submit_feedback(
        self,
        invocation_id: str,
        rating: int,
        comment: str = "",
    ) -> TxResult:
        """Submit feedback for a completed invocation."""
        return self.sign_and_broadcast([(
            "/oasyce.reputation.v1.MsgSubmitFeedback",
            {
                "creator": self.wallet.address,
                "invocation_id": invocation_id,
                "rating": rating,
                "comment": comment,
            },
        )])

    def register_executor(
        self,
        task_types: List[str],
        max_compute_units: int = 1000,
    ) -> TxResult:
        """Register as a work executor."""
        return self.sign_and_broadcast([(
            "/oasyce.work.v1.MsgRegisterExecutor",
            {
                "executor": self.wallet.address,
                "supported_task_types": task_types,
                "max_compute_units": max_compute_units,
            },
        )])

    def submit_task(
        self,
        task_type: str,
        input_hash: bytes,
        input_uri: str,
        bounty_uoas: int,
        max_compute_units: int = 100,
        redundancy: int = 1,
        timeout_blocks: int = 100,
    ) -> TxResult:
        """Submit a compute task."""
        return self.sign_and_broadcast([(
            "/oasyce.work.v1.MsgSubmitTask",
            {
                "creator": self.wallet.address,
                "task_type": task_type,
                "input_hash": base64.b64encode(input_hash).decode(),
                "input_uri": input_uri,
                "max_compute_units": max_compute_units,
                "bounty": {"denom": "uoas", "amount": str(bounty_uoas)},
                "redundancy": redundancy,
                "timeout_blocks": timeout_blocks,
            },
        )])

    def commit_result(
        self,
        task_id: int,
        commit_hash: bytes,
    ) -> TxResult:
        """Commit a task result hash."""
        return self.sign_and_broadcast([(
            "/oasyce.work.v1.MsgCommitResult",
            {
                "executor": self.wallet.address,
                "task_id": task_id,
                "commit_hash": base64.b64encode(commit_hash).decode(),
            },
        )])

    def reveal_result(
        self,
        task_id: int,
        output_hash: bytes,
        output_uri: str,
        compute_units_used: int,
        salt: bytes,
        unavailable: bool = False,
    ) -> TxResult:
        """Reveal a committed task result."""
        return self.sign_and_broadcast([(
            "/oasyce.work.v1.MsgRevealResult",
            {
                "executor": self.wallet.address,
                "task_id": task_id,
                "output_hash": base64.b64encode(output_hash).decode(),
                "output_uri": output_uri,
                "compute_units_used": compute_units_used,
                "salt": base64.b64encode(salt).decode(),
                "unavailable": unavailable,
            },
        )])

    # --- Anchor (Thronglets → Chain) ---

    def anchor_trace(
        self,
        trace_id_hex: str,
        node_pubkey_hex: str,
        capability: str,
        outcome: int,
        timestamp: int,
        trace_signature_hex: str,
    ) -> TxResult:
        """Anchor a single Thronglets trace on-chain."""
        return self.sign_and_broadcast([(
            "/oasyce.anchor.v1.MsgAnchorTrace",
            {
                "signer": self.wallet.address,
                "trace_id": base64.b64encode(bytes.fromhex(trace_id_hex)).decode(),
                "node_pubkey": base64.b64encode(bytes.fromhex(node_pubkey_hex)).decode(),
                "capability": capability,
                "outcome": outcome,
                "timestamp": str(timestamp),
                "trace_signature": base64.b64encode(bytes.fromhex(trace_signature_hex)).decode(),
            },
        )])

    def anchor_batch(
        self,
        traces: List[Dict[str, Any]],
    ) -> TxResult:
        """Anchor up to 50 Thronglets traces on-chain in one TX.

        Each trace dict: trace_id_hex, node_pubkey_hex, capability,
        outcome, timestamp, trace_signature_hex.
        """
        anchor_msgs = []
        for t in traces[:50]:
            anchor_msgs.append({
                "signer": self.wallet.address,
                "trace_id": base64.b64encode(bytes.fromhex(t["trace_id_hex"])).decode(),
                "node_pubkey": base64.b64encode(bytes.fromhex(t["node_pubkey_hex"])).decode(),
                "capability": t["capability"],
                "outcome": t["outcome"],
                "timestamp": str(t["timestamp"]),
                "trace_signature": base64.b64encode(bytes.fromhex(t["trace_signature_hex"])).decode(),
            })
        return self.sign_and_broadcast([(
            "/oasyce.anchor.v1.MsgAnchorBatch",
            {"signer": self.wallet.address, "anchors": anchor_msgs},
        )])

    def __repr__(self) -> str:
        return f"NativeSigner(address={self.wallet.address!r}, chain={self.chain_id!r})"
