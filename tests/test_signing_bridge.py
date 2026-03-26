"""Tests for SigningBridge — mocked subprocess, no real chain needed."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, call

import pytest

from oasyce_sdk import OasyceClient
from oasyce_sdk.errors import ChainError, OasyceError
from oasyce_sdk.signing_bridge import SigningBridge
from oasyce_sdk.types import TxResult


@pytest.fixture
def client():
    return OasyceClient("http://testnode:1317", timeout=5)


@pytest.fixture
def bridge(client):
    return SigningBridge(
        client=client,
        oasyced_path="/usr/local/bin/oasyced",
        key_name="test-key",
        chain_id="oasyce-testnet-1",
        node="tcp://testnode:26657",
        block_wait=0,  # no waiting in tests
    )


def _subprocess_ok(stdout: str = "", returncode: int = 0):
    """Create a mock subprocess.CompletedProcess."""
    m = MagicMock()
    m.stdout = stdout
    m.stderr = ""
    m.returncode = returncode
    return m


class TestSenderAddress:

    def test_resolves_key(self, bridge):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _subprocess_ok("oasyce1abc123\n")
            addr = bridge.sender_address
            assert addr == "oasyce1abc123"
            args = mock_run.call_args[0][0]
            assert "keys" in args
            assert "show" in args
            assert "test-key" in args

    def test_raises_on_failure(self, bridge):
        with patch("subprocess.run") as mock_run:
            result = _subprocess_ok(returncode=1)
            result.stderr = "key not found"
            mock_run.return_value = result
            with pytest.raises(OasyceError, match="Cannot resolve key"):
                bridge.sender_address


class TestBroadcast:

    def _mock_sign_broadcast(self, mock_run, txhash="AABB", code=0):
        """Set up subprocess.run to handle sign + broadcast calls."""
        signed_tx = json.dumps({"body": {}, "auth_info": {}, "signatures": ["sig"]})
        broadcast_out = json.dumps({"txhash": txhash, "code": code, "raw_log": ""})

        def side_effect(cmd, **kwargs):
            if "sign" in cmd:
                return _subprocess_ok(signed_tx)
            elif "broadcast" in cmd:
                return _subprocess_ok(broadcast_out)
            elif "keys" in cmd:
                return _subprocess_ok("oasyce1sender\n")
            return _subprocess_ok()

        mock_run.side_effect = side_effect

    def test_broadcast_returns_tx_result(self, bridge):
        with patch("subprocess.run") as mock_run:
            self._mock_sign_broadcast(mock_run, txhash="DEADBEEF", code=0)
            tx_body = {"body": {"messages": []}, "auth_info": {}, "signatures": []}
            result = bridge.broadcast(tx_body)

            assert isinstance(result, TxResult)
            assert result.tx_hash == "DEADBEEF"
            assert result.code == 0
            assert result.success is True

    def test_broadcast_detects_failure_code(self, bridge):
        with patch("subprocess.run") as mock_run:
            self._mock_sign_broadcast(mock_run, txhash="FAIL", code=5)
            tx_body = {"body": {"messages": []}, "auth_info": {}, "signatures": []}
            result = bridge.broadcast(tx_body)

            assert result.success is False
            assert result.code == 5

    def test_sign_failure_raises(self, bridge):
        with patch("subprocess.run") as mock_run:
            result = _subprocess_ok(returncode=1)
            result.stderr = "signing error"
            mock_run.return_value = result

            with pytest.raises(ChainError, match="Sign failed"):
                bridge.broadcast({"body": {"messages": []}})

    def test_sign_cmd_includes_correct_flags(self, bridge):
        with patch("subprocess.run") as mock_run:
            self._mock_sign_broadcast(mock_run)
            bridge.broadcast({"body": {"messages": []}, "auth_info": {}, "signatures": []})

            sign_call = mock_run.call_args_list[0]
            cmd = sign_call[0][0]
            assert f"--from=test-key" in cmd
            assert f"--chain-id=oasyce-testnet-1" in cmd
            assert f"--node=tcp://testnode:26657" in cmd


class TestConvenienceMethods:

    def _setup_mocks(self, mock_run):
        """Common setup for all convenience method tests."""
        signed = json.dumps({"body": {}, "auth_info": {}, "signatures": ["sig"]})
        broadcast = json.dumps({"txhash": "TX123", "code": 0, "raw_log": ""})

        def side_effect(cmd, **kwargs):
            if "keys" in cmd:
                return _subprocess_ok("oasyce1sender\n")
            elif "sign" in cmd:
                return _subprocess_ok(signed)
            elif "broadcast" in cmd:
                return _subprocess_ok(broadcast)
            return _subprocess_ok()

        mock_run.side_effect = side_effect

    def test_create_escrow(self, bridge):
        with patch("subprocess.run") as mock_run:
            self._setup_mocks(mock_run)
            result = bridge.create_escrow(amount_uoas=50000, asset_id="DATA_001")
            assert result.tx_hash == "TX123"
            assert result.success is True

    def test_release_escrow(self, bridge):
        with patch("subprocess.run") as mock_run:
            self._setup_mocks(mock_run)
            result = bridge.release_escrow("ESC_001")
            assert result.tx_hash == "TX123"

    def test_refund_escrow(self, bridge):
        with patch("subprocess.run") as mock_run:
            self._setup_mocks(mock_run)
            result = bridge.refund_escrow("ESC_001")
            assert result.success is True

    def test_register_capability(self, bridge):
        with patch("subprocess.run") as mock_run:
            self._setup_mocks(mock_run)
            result = bridge.register_capability(
                name="TestCap", endpoint="https://x", price_uoas=500,
            )
            assert result.success is True

    def test_invoke_capability(self, bridge):
        with patch("subprocess.run") as mock_run:
            self._setup_mocks(mock_run)
            result = bridge.invoke_capability("CAP_001")
            assert result.success is True

    def test_complete_invocation(self, bridge):
        with patch("subprocess.run") as mock_run:
            self._setup_mocks(mock_run)
            result = bridge.complete_invocation("INV_001", output_hash="abc" * 10)
            assert result.success is True

    def test_submit_feedback(self, bridge):
        with patch("subprocess.run") as mock_run:
            self._setup_mocks(mock_run)
            result = bridge.submit_feedback("INV_001", rating=450)
            assert result.success is True

    def test_self_register(self, bridge):
        with patch("subprocess.run") as mock_run:
            self._setup_mocks(mock_run)
            result = bridge.self_register(nonce=123456)
            assert result.success is True


class TestBroadcastEdgeCases:

    def test_broadcast_invalid_json_output(self, bridge):
        """Broadcast output that isn't valid JSON should raise ChainError."""
        with patch("subprocess.run") as mock_run:
            signed = json.dumps({"body": {}, "auth_info": {}, "signatures": ["sig"]})

            def side_effect(cmd, **kwargs):
                if "sign" in cmd:
                    return _subprocess_ok(signed)
                elif "broadcast" in cmd:
                    return _subprocess_ok("not json at all")
                return _subprocess_ok()

            mock_run.side_effect = side_effect
            with pytest.raises(ChainError, match="Cannot parse broadcast output"):
                bridge.broadcast({"body": {"messages": []}, "auth_info": {}, "signatures": []})

    def test_broadcast_nonzero_exit_with_bad_output(self, bridge):
        """Broadcast returns nonzero exit and non-JSON output."""
        with patch("subprocess.run") as mock_run:
            signed = json.dumps({"body": {}, "auth_info": {}, "signatures": ["sig"]})

            def side_effect(cmd, **kwargs):
                if "sign" in cmd:
                    return _subprocess_ok(signed)
                elif "broadcast" in cmd:
                    r = _subprocess_ok("", returncode=1)
                    r.stderr = "connection refused"
                    return r
                return _subprocess_ok()

            mock_run.side_effect = side_effect
            with pytest.raises(ChainError, match="Broadcast failed"):
                bridge.broadcast({"body": {"messages": []}, "auth_info": {}, "signatures": []})

    def test_broadcast_with_raw_log(self, bridge):
        """Non-zero code TX should carry raw_log through."""
        with patch("subprocess.run") as mock_run:
            signed = json.dumps({"body": {}, "auth_info": {}, "signatures": ["sig"]})
            broadcast = json.dumps({"txhash": "TX", "code": 11, "raw_log": "out of gas"})

            def side_effect(cmd, **kwargs):
                if "sign" in cmd:
                    return _subprocess_ok(signed)
                elif "broadcast" in cmd:
                    return _subprocess_ok(broadcast)
                return _subprocess_ok()

            mock_run.side_effect = side_effect
            result = bridge.broadcast({"body": {"messages": []}, "auth_info": {}, "signatures": []})
            assert result.code == 11
            assert result.raw_log == "out of gas"
            assert result.success is False

    def test_keyring_backend_custom(self, client):
        """Custom keyring backend appears in sign command."""
        bridge = SigningBridge(
            client=client,
            oasyced_path="/bin/oasyced",
            key_name="k",
            chain_id="c",
            node="tcp://n:26657",
            keyring_backend="os",
            block_wait=0,
        )
        with patch("subprocess.run") as mock_run:
            signed = json.dumps({"body": {}, "auth_info": {}, "signatures": ["sig"]})
            broadcast = json.dumps({"txhash": "TX", "code": 0, "raw_log": ""})

            def side_effect(cmd, **kwargs):
                if "sign" in cmd:
                    return _subprocess_ok(signed)
                elif "broadcast" in cmd:
                    return _subprocess_ok(broadcast)
                return _subprocess_ok()

            mock_run.side_effect = side_effect
            bridge.broadcast({"body": {"messages": []}, "auth_info": {}, "signatures": []})
            sign_cmd = mock_run.call_args_list[0][0][0]
            assert "--keyring-backend=os" in sign_cmd


class TestBuyShares:

    def test_buy_shares(self, bridge):
        with patch("subprocess.run") as mock_run:
            signed = json.dumps({"body": {}, "auth_info": {}, "signatures": ["sig"]})
            broadcast = json.dumps({"txhash": "BUY_TX", "code": 0, "raw_log": ""})

            def side_effect(cmd, **kwargs):
                if "keys" in cmd:
                    return _subprocess_ok("oasyce1sender\n")
                elif "sign" in cmd:
                    return _subprocess_ok(signed)
                elif "broadcast" in cmd:
                    return _subprocess_ok(broadcast)
                return _subprocess_ok()

            mock_run.side_effect = side_effect
            result = bridge.buy_shares("DATA_001", 100000)
            assert result.tx_hash == "BUY_TX"
            assert result.success is True

    def test_register_asset(self, bridge):
        with patch("subprocess.run") as mock_run:
            signed = json.dumps({"body": {}, "auth_info": {}, "signatures": ["sig"]})
            broadcast = json.dumps({"txhash": "REG_TX", "code": 0, "raw_log": ""})

            def side_effect(cmd, **kwargs):
                if "keys" in cmd:
                    return _subprocess_ok("oasyce1sender\n")
                elif "sign" in cmd:
                    return _subprocess_ok(signed)
                elif "broadcast" in cmd:
                    return _subprocess_ok(broadcast)
                return _subprocess_ok()

            mock_run.side_effect = side_effect
            result = bridge.register_asset("MyDataset", "sha256:abc")
            assert result.success is True


class TestRepr:

    def test_repr(self, bridge):
        r = repr(bridge)
        assert "test-key" in r
        assert "oasyce-testnet-1" in r
