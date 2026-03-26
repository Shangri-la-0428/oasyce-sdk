"""Tests for AhrpChainAdapter — mocked SigningBridge, no real chain needed."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from oasyce_sdk import OasyceClient
from oasyce_sdk.ahrp_adapter import AhrpChainAdapter, _ChainProxy
from oasyce_sdk.signing_bridge import SigningBridge
from oasyce_sdk.types import TxResult


@pytest.fixture
def mock_bridge():
    bridge = MagicMock(spec=SigningBridge)
    bridge.client = MagicMock(spec=OasyceClient)
    return bridge


@pytest.fixture
def adapter(mock_bridge):
    return AhrpChainAdapter(mock_bridge)


class TestChainProperty:

    def test_chain_returns_proxy(self, adapter):
        assert isinstance(adapter.chain, _ChainProxy)

    def test_chain_is_same_instance(self, adapter):
        assert adapter.chain is adapter.chain


class TestIsChainMode:

    def test_returns_true_when_healthy(self, adapter, mock_bridge):
        mock_bridge.client.health.return_value = True
        assert adapter.is_chain_mode is True

    def test_returns_false_when_unhealthy(self, adapter, mock_bridge):
        mock_bridge.client.health.return_value = False
        assert adapter.is_chain_mode is False


class TestCreateEscrow:

    def test_calls_bridge_and_returns_dict(self, adapter, mock_bridge):
        mock_bridge.create_escrow.return_value = TxResult(
            tx_hash="ABCDEF123456",
            code=0,
            raw_log="",
            success=True,
        )

        result = adapter.chain.create_escrow(
            creator="oasyce1buyer",
            provider="oasyce1seller",
            amount_uoas=50000,
            capability_id="CAP_001",
        )

        # Verify return shape matches Plugin Engine's expectation
        assert "tx_response" in result
        assert result["tx_response"]["txhash"] == "ABCDEF123456"
        assert result["tx_response"]["code"] == 0

        # Verify bridge was called correctly
        mock_bridge.create_escrow.assert_called_once_with(
            amount_uoas=50000,
            capability_id="CAP_001",
            asset_id="",
        )

    def test_with_asset_id(self, adapter, mock_bridge):
        mock_bridge.create_escrow.return_value = TxResult(
            tx_hash="TX_ASSET", code=0, raw_log="", success=True,
        )

        result = adapter.chain.create_escrow(
            creator="oasyce1a",
            provider="oasyce1b",
            amount_uoas=100000,
            asset_id="DATA_001",
        )

        assert result["tx_response"]["txhash"] == "TX_ASSET"
        mock_bridge.create_escrow.assert_called_once_with(
            amount_uoas=100000,
            capability_id="",
            asset_id="DATA_001",
        )

    def test_optional_params_have_defaults(self, adapter, mock_bridge):
        mock_bridge.create_escrow.return_value = TxResult(
            tx_hash="TX", code=0, raw_log="", success=True,
        )

        # AHRP calls with only required params
        result = adapter.chain.create_escrow(
            creator="oasyce1a",
            provider="oasyce1b",
            amount_uoas=10000,
            capability_id="CAP_X",
        )

        assert result["tx_response"]["txhash"] == "TX"


class TestReleaseEscrow:

    def test_calls_bridge_and_returns_dict(self, adapter, mock_bridge):
        mock_bridge.release_escrow.return_value = TxResult(
            tx_hash="RELEASE_TX",
            code=0,
            raw_log="",
            success=True,
        )

        result = adapter.chain.release_escrow(
            escrow_id="ESC_001",
            releaser="oasyce1buyer",
        )

        assert result["tx_response"]["txhash"] == "RELEASE_TX"
        assert result["tx_response"]["code"] == 0
        mock_bridge.release_escrow.assert_called_once_with("ESC_001")

    def test_failed_release(self, adapter, mock_bridge):
        mock_bridge.release_escrow.return_value = TxResult(
            tx_hash="FAIL_TX",
            code=5,
            raw_log="unauthorized",
            success=False,
        )

        result = adapter.chain.release_escrow(
            escrow_id="ESC_002",
            releaser="oasyce1wrong",
        )

        assert result["tx_response"]["code"] == 5
        assert result["tx_response"]["raw_log"] == "unauthorized"


class TestFullHandshakeFlow:
    """Simulates the AHRP ACCEPT -> CONFIRM flow through the adapter."""

    def test_escrow_lifecycle(self, adapter, mock_bridge):
        """create_escrow then release_escrow — the AHRP happy path."""
        mock_bridge.create_escrow.return_value = TxResult(
            tx_hash="ESC_HASH_001", code=0, raw_log="", success=True,
        )
        mock_bridge.release_escrow.return_value = TxResult(
            tx_hash="REL_HASH_001", code=0, raw_log="", success=True,
        )

        # ACCEPT: create escrow
        create_result = adapter.chain.create_escrow(
            creator="oasyce1buyer",
            provider="oasyce1seller",
            amount_uoas=50000,
            capability_id="CAP_001",
        )
        escrow_hash = create_result["tx_response"]["txhash"]
        assert escrow_hash == "ESC_HASH_001"

        # CONFIRM: release escrow
        release_result = adapter.chain.release_escrow(
            escrow_id=escrow_hash,
            releaser="oasyce1buyer",
        )
        assert release_result["tx_response"]["code"] == 0

    def test_local_fallback_on_chain_error(self, adapter, mock_bridge):
        """When chain call raises, AHRP falls back to local escrow."""
        from oasyce_sdk.errors import ChainError
        mock_bridge.create_escrow.side_effect = ChainError(-1, "node down")

        with pytest.raises(ChainError):
            adapter.chain.create_escrow(
                creator="oasyce1a",
                provider="oasyce1b",
                amount_uoas=10000,
                capability_id="CAP_X",
            )


class TestRepr:

    def test_repr(self, adapter):
        r = repr(adapter)
        assert "AhrpChainAdapter" in r
