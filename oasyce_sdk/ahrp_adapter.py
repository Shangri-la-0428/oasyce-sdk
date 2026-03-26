"""AHRP ↔ Chain adapter — bridges Plugin Engine's AHRP to the live chain.

The AHRP Executor in the Plugin Engine calls::

    self._chain.chain.create_escrow(creator, provider, amount_uoas, capability_id)
    self._chain.chain.release_escrow(escrow_id, releaser)
    self._chain.is_chain_mode  # bool property

This module provides :class:`AhrpChainAdapter` which satisfies that interface
using :class:`SigningBridge` for signing and :class:`OasyceClient` for queries.

Usage::

    from oasyce_sdk import OasyceClient
    from oasyce_sdk.signing_bridge import SigningBridge
    from oasyce_sdk.ahrp_adapter import AhrpChainAdapter

    client = OasyceClient("http://47.93.32.88:1317")
    bridge = SigningBridge(client, "./oasyced", "my-key", "oasyce-testnet-1", "tcp://47.93.32.88:26657")
    adapter = AhrpChainAdapter(bridge)

    # Pass to AHRP Executor as chain_client:
    # executor = AHRPExecutor(chain_client=adapter)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .errors import ChainError, OasyceError
from .signing_bridge import SigningBridge


class _ChainProxy:
    """Inner object satisfying ``adapter.chain.create_escrow(...)`` calls.

    The AHRP Executor accesses chain methods via ``self._chain.chain.*``.
    This proxy is what ``.chain`` returns.
    """

    def __init__(self, bridge: SigningBridge) -> None:
        self._bridge = bridge

    def create_escrow(
        self,
        creator: str,
        provider: str,
        amount_uoas: int,
        timeout_seconds: int = 3600,
        capability_id: str = "",
        asset_id: str = "",
        from_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create an escrow on-chain via SigningBridge.

        Returns a dict matching the Plugin Engine's expected shape::

            {"tx_response": {"txhash": "ABC..."}}
        """
        result = self._bridge.create_escrow(
            amount_uoas=amount_uoas,
            capability_id=capability_id,
            asset_id=asset_id,
        )
        return {
            "tx_response": {
                "txhash": result.tx_hash,
                "code": result.code,
                "raw_log": result.raw_log,
            }
        }

    def release_escrow(
        self,
        escrow_id: str,
        releaser: str,
        from_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Release escrowed funds on-chain via SigningBridge.

        Returns a dict with the TX response.
        """
        result = self._bridge.release_escrow(escrow_id)
        return {
            "tx_response": {
                "txhash": result.tx_hash,
                "code": result.code,
                "raw_log": result.raw_log,
            }
        }


class AhrpChainAdapter:
    """Drop-in replacement for Plugin Engine's ``OasyceClient`` in AHRP context.

    Provides the ``.chain`` property and ``.is_chain_mode`` property that
    the AHRP Executor expects, backed by :class:`SigningBridge`.

    Parameters
    ----------
    bridge : SigningBridge
        A configured signing bridge with key, chain ID, and node set.
    """

    def __init__(self, bridge: SigningBridge) -> None:
        self._bridge = bridge
        self._chain_proxy = _ChainProxy(bridge)

    @property
    def chain(self) -> _ChainProxy:
        """Access the chain proxy (satisfies ``self._chain.chain.*`` calls)."""
        return self._chain_proxy

    @property
    def is_chain_mode(self) -> bool:
        """Whether the chain is reachable."""
        return self._bridge.client.health()

    def __repr__(self) -> str:
        return f"AhrpChainAdapter(bridge={self._bridge!r})"
