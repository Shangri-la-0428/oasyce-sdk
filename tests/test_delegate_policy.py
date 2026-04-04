"""Delegate policy bootstrap tests."""

from __future__ import annotations

import json

import pytest

from oasyce_sdk.crypto.signer import TxResult
from oasyce_sdk.crypto.wallet import Wallet
from oasyce_sdk.delegate_policy import (
    DEFAULT_ALLOWED_MSG_TYPES,
    LocalDelegatePolicy,
    ensure_chain_identity,
    load_local_delegate_policy,
    load_thronglets_delegate_policy_hint,
)
from oasyce_sdk.identity import IdentityResolver, LocalIdentityBinding


@pytest.fixture
def temp_oasyce_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OASYCE_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("OASYCE_MNEMONIC", raising=False)
    return tmp_path


class DummyClient:
    def __init__(self, principal: str = "", root_policy_exists: bool = False):
        self.principal = principal
        self.root_policy_exists = root_policy_exists
        self.queries: list[str] = []
        self.policy_queries: list[str] = []

    def get_principal(self, delegate: str) -> str:
        self.queries.append(delegate)
        return self.principal

    def get_delegate_policy(self, principal: str):
        self.policy_queries.append(principal)
        if self.root_policy_exists:
            return type("DelegatePolicy", (), {"principal": principal})()
        raise RuntimeError("not found")


class TestLocalDelegatePolicy:
    def test_save_and_load_local_delegate_policy(self, temp_oasyce_dir):
        policy = LocalDelegatePolicy(
            principal="oasyce1owner",
            allowed_msgs=["/cosmos.bank.v1beta1.MsgSend"],
            enrollment_token="shared-secret",
        )

        saved_path = policy.save()
        loaded = load_local_delegate_policy()

        assert saved_path.endswith("delegate_policy.v1.json")
        assert loaded == policy

    def test_loads_delegate_policy_hint_from_thronglets_binding(
        self, temp_oasyce_dir, monkeypatch
    ):
        home = temp_oasyce_dir / "home"
        thronglets_dir = home / ".thronglets"
        thronglets_dir.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        (thronglets_dir / "identity.v1.json").write_text(
            json.dumps(
                {
                    "schema_version": "thronglets.identity.v1",
                    "owner_account": "oasyce1owner",
                    "device_identity": "oasyce1device",
                    "oasyce_delegate_policy": {
                        "schema_version": "oasyce.delegate_policy.v1",
                        "principal": "oasyce1owner",
                        "allowed_msgs": ["/cosmos.bank.v1beta1.MsgSend"],
                        "enrollment_token": "shared-secret",
                        "per_tx_limit_uoas": 1000000,
                        "window_limit_uoas": 10000000,
                        "window_seconds": 86400,
                        "expiration_seconds": 0,
                        "updated_at": "2026-04-04T00:00:00Z",
                    },
                }
            )
        )

        hint = load_thronglets_delegate_policy_hint()

        assert hint is not None
        assert hint.principal == "oasyce1owner"
        assert hint.enrollment_token == "shared-secret"

    def test_ensure_chain_identity_auto_enrolls_from_thronglets_hint(
        self, temp_oasyce_dir, monkeypatch
    ):
        home = temp_oasyce_dir / "home"
        thronglets_dir = home / ".thronglets"
        thronglets_dir.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        (thronglets_dir / "identity.v1.json").write_text(
            json.dumps(
                {
                    "schema_version": "thronglets.identity.v1",
                    "owner_account": "oasyce1owner",
                    "device_identity": "oasyce1device",
                    "oasyce_delegate_policy": {
                        "schema_version": "oasyce.delegate_policy.v1",
                        "principal": "oasyce1owner",
                        "allowed_msgs": ["/cosmos.bank.v1beta1.MsgSend"],
                        "enrollment_token": "shared-secret",
                        "per_tx_limit_uoas": 1000000,
                        "window_limit_uoas": 10000000,
                        "window_seconds": 86400,
                        "expiration_seconds": 0,
                        "updated_at": "2026-04-04T00:00:00Z",
                    },
                }
            )
        )

        wallet = Wallet.create()
        identity = IdentityResolver.resolve(wallet=wallet)
        calls = []

        def fake_enroll(self, principal: str, token: str, label: str = ""):
            calls.append((self.wallet.address, principal, token, label))
            return TxResult("txhash", True, 0, "")

        monkeypatch.setattr(
            "oasyce_sdk.delegate_policy.NativeSigner.enroll_delegate",
            fake_enroll,
        )

        resolved = ensure_chain_identity(identity, DummyClient(), "oasyce-testnet-1")

        assert calls == [(wallet.address, "oasyce1owner", "shared-secret", "")]
        assert resolved.principal == "oasyce1owner"
        assert resolved.account == "oasyce1owner"
        loaded = LocalIdentityBinding.load(str(temp_oasyce_dir / "identity.v1.json"))
        assert loaded.principal == "oasyce1owner"
        assert loaded.account == "oasyce1owner"

    def test_ensure_chain_identity_uses_existing_chain_enrollment(
        self, temp_oasyce_dir
    ):
        policy = LocalDelegatePolicy(
            principal="oasyce1owner",
            allowed_msgs=["/cosmos.bank.v1beta1.MsgSend"],
            enrollment_token="shared-secret",
        )
        policy.save()
        wallet = Wallet.create()
        identity = IdentityResolver.resolve(wallet=wallet)
        client = DummyClient(principal="oasyce1owner")

        resolved = ensure_chain_identity(identity, client, "oasyce-testnet-1")

        assert client.queries == [wallet.address]
        assert resolved.principal == "oasyce1owner"
        assert resolved.account == "oasyce1owner"

    def test_ensure_chain_identity_rejects_conflicting_account_binding(
        self, temp_oasyce_dir
    ):
        policy = LocalDelegatePolicy(
            principal="oasyce1owner",
            allowed_msgs=["/cosmos.bank.v1beta1.MsgSend"],
            enrollment_token="shared-secret",
        )
        policy.save()
        wallet = Wallet.create()
        IdentityResolver.ensure_local_binding(wallet, account="oasyce1other")
        identity = IdentityResolver.resolve(wallet=wallet)

        with pytest.raises(RuntimeError) as exc:
            ensure_chain_identity(identity, DummyClient(), "oasyce-testnet-1")

        assert "conflicts with delegate policy principal" in str(exc.value)

    def test_ensure_chain_identity_bootstraps_root_policy_for_first_device(
        self, temp_oasyce_dir, monkeypatch
    ):
        wallet = Wallet.create()
        identity = IdentityResolver.resolve(wallet=wallet)
        calls = []

        def fake_set_policy(
            self,
            token: str,
            allowed_msgs: list[str],
            per_tx_uoas: int = 1_000_000,
            window_uoas: int = 10_000_000,
            window_seconds: int = 86400,
            expiration_seconds: int = 0,
        ):
            calls.append(
                {
                    "wallet": self.wallet.address,
                    "token": token,
                    "allowed_msgs": list(allowed_msgs),
                    "per_tx_uoas": per_tx_uoas,
                    "window_uoas": window_uoas,
                    "window_seconds": window_seconds,
                    "expiration_seconds": expiration_seconds,
                }
            )
            return TxResult("txhash", True, 0, "")

        monkeypatch.setattr(
            "oasyce_sdk.delegate_policy.NativeSigner.set_delegate_policy",
            fake_set_policy,
        )

        resolved = ensure_chain_identity(identity, DummyClient(), "oasyce-testnet-1")

        assert resolved.principal == wallet.address
        assert resolved.account == wallet.address
        assert calls and calls[0]["wallet"] == wallet.address
        assert calls[0]["allowed_msgs"] == DEFAULT_ALLOWED_MSG_TYPES
        saved_policy = load_local_delegate_policy()
        assert saved_policy is not None
        assert saved_policy.principal == wallet.address
        assert saved_policy.allowed_msgs == DEFAULT_ALLOWED_MSG_TYPES

    def test_ensure_chain_identity_bootstraps_root_when_owner_hint_lacks_authority(
        self, temp_oasyce_dir, monkeypatch
    ):
        wallet = Wallet.create()
        IdentityResolver.ensure_local_binding(wallet, account="oasyce1owner")
        identity = IdentityResolver.resolve(wallet=wallet)

        monkeypatch.setattr(
            "oasyce_sdk.delegate_policy.NativeSigner.set_delegate_policy",
            lambda self, **kwargs: TxResult("txhash", True, 0, ""),
        )

        resolved = ensure_chain_identity(identity, DummyClient(), "oasyce-testnet-1")

        assert resolved.principal == wallet.address
        assert resolved.account == wallet.address
        saved_policy = load_local_delegate_policy()
        assert saved_policy is not None
        assert saved_policy.principal == wallet.address
