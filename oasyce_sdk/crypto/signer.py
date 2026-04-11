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
        principal: Optional[str] = None,
        gas_limit: int = DEFAULT_GAS_LIMIT,
        fee: int = DEFAULT_FEE,
        memo: str = "",
    ):
        self.wallet = wallet
        self.client = client
        self.chain_id = chain_id
        self.principal = principal if principal and principal != wallet.address else None
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
            try:
                self._refresh_account()
            except Exception:
                # New account not yet on chain — use defaults (valid for first tx)
                self._account_number = 0
                self._sequence = 0

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

    @property
    def actor_address(self) -> str:
        """Economic actor for inner messages."""
        return self.principal or self.wallet.address

    @property
    def delegated(self) -> bool:
        """Whether this signer executes messages on behalf of a principal."""
        return self.principal is not None

    def _submit_single(
        self,
        type_url: str,
        fields: Dict[str, Any],
        *,
        delegate_exec: bool = False,
    ) -> TxResult:
        """Broadcast one message, optionally wrapped as delegate execution."""
        if delegate_exec and self.delegated:
            return self.sign_and_broadcast([(
                "/oasyce.delegate.v1.MsgExec",
                {
                    "delegate": self.wallet.address,
                    "msgs": [{"@type": type_url, **fields}],
                },
            )])
        return self.sign_and_broadcast([(type_url, fields)])

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
        return self._submit_single(
            "/cosmos.bank.v1beta1.MsgSend",
            {
                "from_address": self.actor_address,
                "to_address": to_address,
                "amount": [{"denom": "uoas", "amount": str(amount_uoas)}],
            },
            delegate_exec=True,
        )

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
        return self._submit_single(
            "/oasyce.capability.v1.MsgRegisterCapability",
            {
                "creator": self.actor_address,
                "name": name,
                "description": description,
                "endpoint_url": endpoint,
                "price_per_call": {"denom": "uoas", "amount": str(price_uoas)},
                "tags": tags or [],
                "rate_limit": rate_limit,
            },
            delegate_exec=True,
        )

    def invoke_capability(
        self,
        capability_id: str,
        input_data: Optional[bytes] = None,
    ) -> TxResult:
        """Invoke an AI capability."""
        return self._submit_single(
            "/oasyce.capability.v1.MsgInvokeCapability",
            {
                "creator": self.actor_address,
                "capability_id": capability_id,
                "input": base64.b64encode(input_data or b"").decode(),
            },
            delegate_exec=True,
        )

    def complete_invocation(
        self,
        invocation_id: str,
        output_hash: str,
        usage_report: str = "",
    ) -> TxResult:
        """Complete an invocation (provider side)."""
        return self._submit_single(
            "/oasyce.capability.v1.MsgCompleteInvocation",
            {
                "creator": self.actor_address,
                "invocation_id": invocation_id,
                "output_hash": output_hash,
                "usage_report": usage_report,
            },
            delegate_exec=True,
        )

    def claim_invocation(self, invocation_id: str) -> TxResult:
        """Claim payment after challenge window."""
        return self._submit_single(
            "/oasyce.capability.v1.MsgClaimInvocation",
            {"creator": self.actor_address, "invocation_id": invocation_id},
            delegate_exec=True,
        )

    def dispute_invocation(self, invocation_id: str, reason: str) -> TxResult:
        """Dispute an invocation within challenge window."""
        return self._submit_single(
            "/oasyce.capability.v1.MsgDisputeInvocation",
            {
                "creator": self.actor_address,
                "invocation_id": invocation_id,
                "reason": reason,
            },
            delegate_exec=True,
        )

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
        return self._submit_single(
            "/oasyce.datarights.v1.MsgRegisterDataAsset",
            {
                "creator": self.actor_address,
                "name": name,
                "description": description,
                "content_hash": content_hash,
                "rights_type": rights_type,
                "tags": tags or [],
                "parent_asset_id": "",
                "service_url": service_url,
            },
            delegate_exec=True,
        )

    def buy_shares(self, asset_id: str, amount_uoas: int) -> TxResult:
        """Buy shares of a data asset on the bonding curve."""
        return self._submit_single(
            "/oasyce.datarights.v1.MsgBuyShares",
            {
                "creator": self.actor_address,
                "asset_id": asset_id,
                "amount": {"denom": "uoas", "amount": str(amount_uoas)},
            },
            delegate_exec=True,
        )

    def sell_shares(self, asset_id: str, shares: int) -> TxResult:
        """Sell shares of a data asset."""
        return self._submit_single(
            "/oasyce.datarights.v1.MsgSellShares",
            {
                "creator": self.actor_address,
                "asset_id": asset_id,
                "shares": str(shares),
            },
            delegate_exec=True,
        )

    def submit_feedback(
        self,
        invocation_id: str,
        rating: int,
        comment: str = "",
    ) -> TxResult:
        """Submit feedback for a completed invocation."""
        return self._submit_single(
            "/oasyce.reputation.v1.MsgSubmitFeedback",
            {
                "creator": self.actor_address,
                "invocation_id": invocation_id,
                "rating": rating,
                "comment": comment,
            },
            delegate_exec=True,
        )

    def register_executor(
        self,
        task_types: List[str],
        max_compute_units: int = 1000,
    ) -> TxResult:
        """Register as a work executor."""
        return self._submit_single(
            "/oasyce.work.v1.MsgRegisterExecutor",
            {
                "executor": self.actor_address,
                "supported_task_types": task_types,
                "max_compute_units": max_compute_units,
            },
            delegate_exec=True,
        )

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
        return self._submit_single(
            "/oasyce.work.v1.MsgSubmitTask",
            {
                "creator": self.actor_address,
                "task_type": task_type,
                "input_hash": base64.b64encode(input_hash).decode(),
                "input_uri": input_uri,
                "max_compute_units": max_compute_units,
                "bounty": {"denom": "uoas", "amount": str(bounty_uoas)},
                "redundancy": redundancy,
                "timeout_blocks": timeout_blocks,
            },
            delegate_exec=True,
        )

    def commit_result(
        self,
        task_id: int,
        commit_hash: bytes,
    ) -> TxResult:
        """Commit a task result hash."""
        return self._submit_single(
            "/oasyce.work.v1.MsgCommitResult",
            {
                "executor": self.actor_address,
                "task_id": task_id,
                "commit_hash": base64.b64encode(commit_hash).decode(),
            },
            delegate_exec=True,
        )

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
        return self._submit_single(
            "/oasyce.work.v1.MsgRevealResult",
            {
                "executor": self.actor_address,
                "task_id": task_id,
                "output_hash": base64.b64encode(output_hash).decode(),
                "output_uri": output_uri,
                "compute_units_used": compute_units_used,
                "salt": base64.b64encode(salt).decode(),
                "unavailable": unavailable,
            },
            delegate_exec=True,
        )

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
        return self._submit_single(
            "/oasyce.anchor.v1.MsgAnchorTrace",
            {
                "signer": self.actor_address,
                "trace_id": base64.b64encode(bytes.fromhex(trace_id_hex)).decode(),
                "node_pubkey": base64.b64encode(bytes.fromhex(node_pubkey_hex)).decode(),
                "capability": capability,
                "outcome": outcome,
                "timestamp": str(timestamp),
                "trace_signature": base64.b64encode(bytes.fromhex(trace_signature_hex)).decode(),
            },
            delegate_exec=True,
        )

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
                "signer": self.actor_address,
                "trace_id": base64.b64encode(bytes.fromhex(t["trace_id_hex"])).decode(),
                "node_pubkey": base64.b64encode(bytes.fromhex(t["node_pubkey_hex"])).decode(),
                "capability": t["capability"],
                "outcome": t["outcome"],
                "timestamp": str(t["timestamp"]),
                "trace_signature": base64.b64encode(bytes.fromhex(t["trace_signature_hex"])).decode(),
            })
        return self._submit_single(
            "/oasyce.anchor.v1.MsgAnchorBatch",
            {"signer": self.actor_address, "anchors": anchor_msgs},
            delegate_exec=True,
        )

    # --- Delegate (multi-agent delegation) ---

    def set_delegate_policy(
        self,
        token: str,
        allowed_msgs: List[str],
        per_tx_uoas: int = 1_000_000,
        window_uoas: int = 10_000_000,
        window_seconds: int = 86400,
        expiration_seconds: int = 0,
    ) -> TxResult:
        """Set delegation policy. One command — all agents operate under this."""
        return self.sign_and_broadcast([(
            "/oasyce.delegate.v1.MsgSetPolicy",
            {
                "principal": self.wallet.address,
                "per_tx_limit": {"denom": "uoas", "amount": str(per_tx_uoas)},
                "window_limit": {"denom": "uoas", "amount": str(window_uoas)},
                "window_seconds": str(window_seconds),
                "allowed_msgs": allowed_msgs,
                "enrollment_token": token,
                "expiration_seconds": str(expiration_seconds),
            },
        )])

    def enroll_delegate(
        self,
        principal: str,
        token: str,
        label: str = "",
    ) -> TxResult:
        """Enroll as delegate under a principal. Agent auto-runs this."""
        return self.sign_and_broadcast([(
            "/oasyce.delegate.v1.MsgEnroll",
            {
                "delegate": self.wallet.address,
                "principal": principal,
                "token": token,
                "label": label,
            },
        )])

    def revoke_delegate(self, delegate: str) -> TxResult:
        """Remove a delegate from your policy (principal only)."""
        return self.sign_and_broadcast([(
            "/oasyce.delegate.v1.MsgRevoke",
            {
                "principal": self.wallet.address,
                "delegate": delegate,
            },
        )])

    def delegate_exec(self, msgs: List[Dict[str, Any]]) -> TxResult:
        """Execute messages on behalf of principal.

        Each msg dict: {"type_url": "/oasyce...", "value": {...}}.
        The value is the proto JSON body of the inner message.
        """
        packed = []
        for m in msgs:
            packed.append({
                "@type": m["type_url"],
                **m["value"],
            })
        return self.sign_and_broadcast([(
            "/oasyce.delegate.v1.MsgExec",
            {
                "delegate": self.wallet.address,
                "msgs": packed,
            },
        )])

    # ------------------------------------------------------------------
    # Sigil Identity
    # ------------------------------------------------------------------

    def create_sigil(
        self,
        public_key_hex: str,
        state_root_hex: str = "",
        lineage: Optional[List[str]] = None,
        metadata: str = "",
    ) -> TxResult:
        """Create a new Sigil (GENESIS)."""
        fields = {
            "signer": self.wallet.address,
            "public_key": base64.b64encode(bytes.fromhex(public_key_hex)).decode(),
        }
        if state_root_hex:
            fields["state_root"] = base64.b64encode(bytes.fromhex(state_root_hex)).decode()
        if lineage:
            fields["lineage"] = lineage
        if metadata:
            fields["metadata"] = metadata
        return self.sign_and_broadcast([("/oasyce.sigil.v1.MsgGenesis", fields)])

    def dissolve_sigil(self, sigil_id: str) -> TxResult:
        """Dissolve (retire) a Sigil permanently."""
        return self.sign_and_broadcast([("/oasyce.sigil.v1.MsgDissolve", {
            "signer": self.wallet.address,
            "sigil_id": sigil_id,
        })])

    def bond_sigils(
        self,
        sigil_a: str,
        sigil_b: str,
        terms_hash_hex: str = "",
        scope: str = "",
    ) -> TxResult:
        """Create a bond between two Sigils."""
        fields = {
            "signer": self.wallet.address,
            "sigil_a": sigil_a,
            "sigil_b": sigil_b,
        }
        if terms_hash_hex:
            fields["terms_hash"] = base64.b64encode(bytes.fromhex(terms_hash_hex)).decode()
        if scope:
            fields["scope"] = scope
        return self.sign_and_broadcast([("/oasyce.sigil.v1.MsgBond", fields)])

    def unbond_sigils(self, bond_id: str) -> TxResult:
        """Remove a bond between two Sigils."""
        return self.sign_and_broadcast([("/oasyce.sigil.v1.MsgUnbond", {
            "signer": self.wallet.address,
            "bond_id": bond_id,
        })])

    def fork_sigil(
        self,
        parent_sigil_id: str,
        child_public_key_hex: str,
        fork_mode: int = 0,
        mutation: str = "",
        metadata: str = "",
    ) -> TxResult:
        """Fork a child Sigil from a parent (Lamarckian inheritance).

        Field names match the chain's ``MsgFork`` proto: ``public_key`` is
        the child's secp256k1 pubkey and ``mutation`` is a free-form string
        (e.g. a JSON blob describing divergences from the parent state).
        """
        fields = {
            "signer": self.wallet.address,
            "parent_sigil_id": parent_sigil_id,
            "public_key": base64.b64encode(bytes.fromhex(child_public_key_hex)).decode(),
        }
        if fork_mode:
            fields["fork_mode"] = fork_mode
        if mutation:
            fields["mutation"] = mutation
        if metadata:
            fields["metadata"] = metadata
        return self.sign_and_broadcast([("/oasyce.sigil.v1.MsgFork", fields)])

    def merge_sigils(
        self,
        sigil_a: str,
        sigil_b: str,
        merge_mode: int = 0,
        metadata: str = "",
    ) -> TxResult:
        """Merge two Sigils (absorption mode)."""
        fields = {
            "signer": self.wallet.address,
            "sigil_a": sigil_a,
            "sigil_b": sigil_b,
        }
        if merge_mode:
            fields["merge_mode"] = merge_mode
        if metadata:
            fields["metadata"] = metadata
        return self.sign_and_broadcast([("/oasyce.sigil.v1.MsgMerge", fields)])

    def pulse_sigil(
        self,
        sigil_id: str,
        dimensions: Optional[Dict[str, int]] = None,
    ) -> TxResult:
        """Send a Pulse heartbeat for a Sigil across one or more dimensions.

        ``dimensions`` is a mapping from dimension name (e.g. ``"psyche"``,
        ``"thronglets"``, ``"economy"``) to a monotonically-increasing
        heartbeat value — typically a timestamp or block height.  The chain
        stores the latest value per dimension; an empty or omitted mapping
        sends a bare pulse that still advances no dimension.
        """
        fields: Dict[str, Any] = {
            "signer": self.wallet.address,
            "sigil_id": sigil_id,
        }
        if dimensions:
            fields["dimensions"] = {str(k): int(v) for k, v in dimensions.items()}
        return self.sign_and_broadcast([("/oasyce.sigil.v1.MsgPulse", fields)])

    def __repr__(self) -> str:
        return (
            f"NativeSigner(address={self.wallet.address!r}, principal={self.principal!r}, "
            f"chain={self.chain_id!r})"
        )
