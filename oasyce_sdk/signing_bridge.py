"""CLI signing bridge — combines SDK TX builders with oasyced subprocess signing.

Usage::

    from oasyce_sdk import OasyceClient
    from oasyce_sdk.signing_bridge import SigningBridge

    client = OasyceClient("http://localhost:1317")
    bridge = SigningBridge(
        client=client,
        oasyced_path="../oasyce-chain/build/oasyced",
        key_name="my-key",
        chain_id="oasyce-testnet-1",
        node="tcp://localhost:26657",
    )

    # Build + sign + broadcast in one call
    result = bridge.create_escrow(amount_uoas=50000, asset_id="DATA_001")
    print(result.tx_hash, result.success)
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional

from .client import OasyceClient
from .errors import ChainError, OasyceError
from .types import TxResult


class SigningBridge:
    """Wraps :class:`OasyceClient` TX builders with CLI-based signing.

    The SDK builds unsigned transaction JSON; this bridge writes it to a
    temp file, signs it via ``oasyced tx sign``, and broadcasts via
    ``oasyced tx broadcast``.

    Parameters
    ----------
    client : OasyceClient
        SDK client for queries and TX body construction.
    oasyced_path : str
        Path to the ``oasyced`` binary.
    key_name : str
        Keyring key name used for signing (e.g. ``"my-agent"``).
    chain_id : str
        Chain ID (e.g. ``"oasyce-testnet-1"``).
    node : str
        Tendermint RPC endpoint (e.g. ``"tcp://localhost:26657"``).
    fees : str
        Default transaction fee string (e.g. ``"10000uoas"``).
    keyring_backend : str
        Keyring backend.  Defaults to ``"test"``.
    block_wait : float
        Seconds to wait for block inclusion after broadcast.
    """

    def __init__(
        self,
        client: OasyceClient,
        oasyced_path: str,
        key_name: str,
        chain_id: str,
        node: str,
        fees: str = "10000uoas",
        keyring_backend: str = "test",
        block_wait: float = 7.0,
    ) -> None:
        self.client = client
        self._bin = oasyced_path
        self._key = key_name
        self._chain_id = chain_id
        self._node = node
        self._fees = fees
        self._kb = f"--keyring-backend={keyring_backend}"
        self._block_wait = block_wait

    # ------------------------------------------------------------------
    # Core: sign + broadcast
    # ------------------------------------------------------------------

    @property
    def sender_address(self) -> str:
        """Resolve the bech32 address of the configured key."""
        result = subprocess.run(
            [self._bin, "keys", "show", self._key, "-a", self._kb],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            raise OasyceError(f"Cannot resolve key {self._key!r}: {result.stderr}")
        return result.stdout.strip()

    def broadcast(self, tx_body: dict) -> TxResult:
        """Sign and broadcast an unsigned TX body built by the SDK.

        Parameters
        ----------
        tx_body : dict
            Output of any ``client.build_*()`` method.

        Returns
        -------
        TxResult
            Broadcast result with tx_hash, code, and success flag.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(tx_body, f)
            unsigned_path = f.name

        # Sign
        sign_cmd = [
            self._bin, "tx", "sign", unsigned_path,
            f"--from={self._key}",
            f"--chain-id={self._chain_id}",
            f"--node={self._node}",
            self._kb,
            "--output-document=-",
            "--output=json",
        ]
        sign_result = subprocess.run(
            sign_cmd, capture_output=True, text=True, timeout=30,
        )
        if sign_result.returncode != 0:
            raise ChainError(-1, f"Sign failed: {sign_result.stderr}")

        # Write signed TX
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write(sign_result.stdout)
            signed_path = f.name

        # Broadcast
        broadcast_cmd = [
            self._bin, "tx", "broadcast", signed_path,
            f"--node={self._node}",
            f"--chain-id={self._chain_id}",
            self._kb,
            "--output=json",
        ]
        bc_result = subprocess.run(
            broadcast_cmd, capture_output=True, text=True, timeout=30,
        )

        # Wait for block inclusion
        if self._block_wait > 0:
            time.sleep(self._block_wait)

        # Parse result
        try:
            data = json.loads(bc_result.stdout)
        except (json.JSONDecodeError, ValueError):
            if bc_result.returncode != 0:
                raise ChainError(-1, f"Broadcast failed: {bc_result.stderr}")
            raise ChainError(-1, f"Cannot parse broadcast output: {bc_result.stdout}")

        code = int(data.get("code", 0))
        return TxResult(
            tx_hash=data.get("txhash", ""),
            code=code,
            raw_log=data.get("raw_log", ""),
            success=(code == 0),
        )

    # ------------------------------------------------------------------
    # Convenience: build + sign + broadcast
    # ------------------------------------------------------------------

    def _broadcast_build(self, builder_name: str, **kwargs: Any) -> TxResult:
        """Call a client.build_* method and broadcast the result."""
        fn = getattr(self.client, builder_name)
        tx_body = fn(**kwargs)
        return self.broadcast(tx_body)

    # --- Settlement ---

    def create_escrow(
        self,
        amount_uoas: int,
        capability_id: str = "",
        asset_id: str = "",
    ) -> TxResult:
        """Build, sign, and broadcast MsgCreateEscrow."""
        return self._broadcast_build(
            "build_create_escrow",
            sender=self.sender_address,
            amount_uoas=amount_uoas,
            capability_id=capability_id,
            asset_id=asset_id,
        )

    def release_escrow(self, escrow_id: str) -> TxResult:
        """Build, sign, and broadcast MsgReleaseEscrow."""
        return self._broadcast_build(
            "build_release_escrow",
            sender=self.sender_address,
            escrow_id=escrow_id,
        )

    def refund_escrow(self, escrow_id: str) -> TxResult:
        """Build, sign, and broadcast MsgRefundEscrow."""
        return self._broadcast_build(
            "build_refund_escrow",
            sender=self.sender_address,
            escrow_id=escrow_id,
        )

    # --- Capability ---

    def register_capability(
        self,
        name: str,
        endpoint: str,
        price_uoas: int,
        description: str = "",
        tags: Optional[List[str]] = None,
    ) -> TxResult:
        """Build, sign, and broadcast MsgRegisterCapability."""
        return self._broadcast_build(
            "build_register_capability",
            sender=self.sender_address,
            name=name,
            endpoint=endpoint,
            price_uoas=price_uoas,
            description=description,
            tags=tags or [],
        )

    def invoke_capability(
        self,
        capability_id: str,
        input_data: str = "",
    ) -> TxResult:
        """Build, sign, and broadcast MsgInvokeCapability."""
        return self._broadcast_build(
            "build_invoke_capability",
            sender=self.sender_address,
            capability_id=capability_id,
            input_data=input_data,
        )

    def complete_invocation(
        self,
        invocation_id: str,
        output_hash: str,
        usage_report: str = "",
    ) -> TxResult:
        """Build, sign, and broadcast MsgCompleteInvocation."""
        return self._broadcast_build(
            "build_complete_invocation",
            sender=self.sender_address,
            invocation_id=invocation_id,
            output_hash=output_hash,
            usage_report=usage_report,
        )

    def claim_invocation(self, invocation_id: str) -> TxResult:
        """Build, sign, and broadcast MsgClaimInvocation."""
        return self._broadcast_build(
            "build_claim_invocation",
            sender=self.sender_address,
            invocation_id=invocation_id,
        )

    # --- Reputation ---

    def submit_feedback(
        self,
        invocation_id: str,
        rating: int,
        comment: str = "",
    ) -> TxResult:
        """Build, sign, and broadcast MsgSubmitFeedback."""
        return self._broadcast_build(
            "build_submit_feedback",
            sender=self.sender_address,
            invocation_id=invocation_id,
            rating=rating,
            comment=comment,
        )

    # --- Data Assets ---

    def register_asset(
        self,
        name: str,
        content_hash: str,
        description: str = "",
        tags: Optional[List[str]] = None,
    ) -> TxResult:
        """Build, sign, and broadcast MsgRegisterDataAsset."""
        return self._broadcast_build(
            "build_register_asset",
            sender=self.sender_address,
            name=name,
            content_hash=content_hash,
            description=description,
            tags=tags or [],
        )

    def buy_shares(self, asset_id: str, amount_uoas: int) -> TxResult:
        """Build, sign, and broadcast MsgBuyShares."""
        return self._broadcast_build(
            "build_buy_shares",
            sender=self.sender_address,
            asset_id=asset_id,
            amount_uoas=amount_uoas,
        )

    # --- Onboarding ---

    def self_register(self, nonce: int) -> TxResult:
        """Build, sign, and broadcast MsgSelfRegister."""
        return self._broadcast_build(
            "build_self_register",
            sender=self.sender_address,
            nonce=nonce,
        )

    def __repr__(self) -> str:
        return (
            f"SigningBridge(key={self._key!r}, "
            f"chain_id={self._chain_id!r}, node={self._node!r})"
        )
