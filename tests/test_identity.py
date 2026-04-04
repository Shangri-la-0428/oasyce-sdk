"""Identity resolution tests for device wallet behavior."""

from __future__ import annotations

import importlib
import json
import sys

import pytest

from oasyce_sdk.crypto.wallet import Wallet
from oasyce_sdk.identity import IdentityResolver, LocalIdentityBinding


@pytest.fixture
def temp_oasyce_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OASYCE_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("OASYCE_MNEMONIC", raising=False)
    return tmp_path


class TestWalletAuto:
    def test_reads_wallet_file_when_env_missing(self, temp_oasyce_dir):
        wallet = Wallet.create()
        wallet_path = temp_oasyce_dir / "wallet.json"
        wallet_path.write_text(
            json.dumps({"mnemonic": wallet.mnemonic, "address": wallet.address})
        )

        resolved = Wallet.auto()
        assert resolved.address == wallet.address

    def test_rejects_conflicting_env_and_wallet_file(self, temp_oasyce_dir, monkeypatch):
        file_wallet = Wallet.create()
        env_wallet = Wallet.create()
        wallet_path = temp_oasyce_dir / "wallet.json"
        wallet_path.write_text(
            json.dumps({"mnemonic": file_wallet.mnemonic, "address": file_wallet.address})
        )
        monkeypatch.setenv("OASYCE_MNEMONIC", env_wallet.mnemonic)

        with pytest.raises(RuntimeError) as exc:
            Wallet.auto()

        assert file_wallet.address in str(exc.value)
        assert env_wallet.address in str(exc.value)


class TestIdentityResolver:
    def test_resolve_uses_identity_file_when_present(self, temp_oasyce_dir):
        wallet = Wallet.create()
        wallet_path = temp_oasyce_dir / "wallet.json"
        identity_path = temp_oasyce_dir / "identity.v1.json"
        wallet_path.write_text(
            json.dumps({"mnemonic": wallet.mnemonic, "address": wallet.address})
        )
        identity_path.write_text(
            json.dumps(
                {
                    "schema_version": "oasyce.identity.v1",
                    "principal": "SIG_demo",
                    "account": "oasyce1owneraccount",
                    "delegate": wallet.address,
                    "signer_address": wallet.address,
                    "updated_at": "2026-04-04T00:00:00Z",
                }
            )
        )

        identity = IdentityResolver.resolve(session_id="abc123")

        assert identity.address == wallet.address
        assert identity.principal == "SIG_demo"
        assert identity.account == "oasyce1owneraccount"
        assert identity.delegate == wallet.address
        assert identity.binding_source == "identity_file"
        assert identity.binding_path == str(identity_path)
        assert identity.signer_source == "file"
        assert identity.signer_path == str(wallet_path)
        assert identity.session_id == "abc123"
        assert identity.sigil_id.startswith("SIG_")

    def test_resolve_explicit_wallet_marks_override(self, temp_oasyce_dir):
        wallet = Wallet.create()

        identity = IdentityResolver.resolve(wallet=wallet)

        assert identity.address == wallet.address
        assert identity.binding_source == "explicit"
        assert identity.binding_path is None
        assert identity.signer_source == "explicit"
        assert identity.account is None
        assert identity.delegate == wallet.address

    def test_resolve_falls_back_to_wallet_compat_when_binding_missing(self, temp_oasyce_dir):
        wallet = Wallet.create()
        wallet_path = temp_oasyce_dir / "wallet.json"
        wallet_path.write_text(
            json.dumps({"mnemonic": wallet.mnemonic, "address": wallet.address})
        )

        identity = IdentityResolver.resolve(session_id="abc123")

        assert identity.binding_source == "compat_wallet"
        assert identity.binding_path is None
        assert identity.signer_source == "file"
        assert identity.signer_path == str(wallet_path)
        assert identity.account is None
        assert identity.delegate == wallet.address

    def test_resolve_imports_thronglets_owner_hint_when_binding_missing(
        self, temp_oasyce_dir, monkeypatch
    ):
        home = temp_oasyce_dir / "home"
        thronglets_dir = home / ".thronglets"
        thronglets_dir.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))

        wallet = Wallet.create()
        wallet_path = temp_oasyce_dir / "wallet.json"
        wallet_path.write_text(
            json.dumps({"mnemonic": wallet.mnemonic, "address": wallet.address})
        )
        (thronglets_dir / "identity.v1.json").write_text(
            json.dumps(
                {
                    "schema_version": "thronglets.identity.v1",
                    "owner_account": "oasyce1owneraccount",
                    "device_identity": "oasyce1deviceidentity",
                    "binding_source": "manual",
                    "updated_at": 123,
                }
            )
        )

        identity = IdentityResolver.resolve(session_id="abc123")

        assert identity.binding_source == "compat_wallet"
        assert identity.account == "oasyce1owneraccount"
        assert identity.delegate == wallet.address

    def test_resolve_local_ignores_env_override(self, temp_oasyce_dir, monkeypatch):
        file_wallet = Wallet.create()
        env_wallet = Wallet.create()
        wallet_path = temp_oasyce_dir / "wallet.json"
        identity_path = temp_oasyce_dir / "identity.v1.json"
        wallet_path.write_text(
            json.dumps({"mnemonic": file_wallet.mnemonic, "address": file_wallet.address})
        )
        identity_path.write_text(
            json.dumps(
                {
                    "schema_version": "oasyce.identity.v1",
                    "account": "oasyce1owneraccount",
                    "delegate": file_wallet.address,
                    "signer_address": file_wallet.address,
                    "updated_at": "2026-04-04T00:00:00Z",
                }
            )
        )
        monkeypatch.setenv("OASYCE_MNEMONIC", env_wallet.mnemonic)

        identity = IdentityResolver.resolve_local()

        assert identity.address == file_wallet.address
        assert identity.binding_source == "identity_file"
        assert identity.signer_source == "file"
        assert identity.account == "oasyce1owneraccount"

    def test_ensure_local_binding_writes_identity_file(self, temp_oasyce_dir):
        wallet = Wallet.create()

        binding = IdentityResolver.ensure_local_binding(wallet)

        assert binding.account is None
        assert binding.delegate == wallet.address
        assert (temp_oasyce_dir / "identity.v1.json").exists()
        loaded = LocalIdentityBinding.load(str(temp_oasyce_dir / "identity.v1.json"))
        assert loaded.signer_address == wallet.address
        assert loaded.account is None

    def test_ensure_local_binding_imports_thronglets_owner_hint(
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
                    "owner_account": "oasyce1owneraccount",
                    "device_identity": "oasyce1deviceidentity",
                    "binding_source": "manual",
                    "updated_at": 123,
                }
            )
        )

        wallet = Wallet.create()
        binding = IdentityResolver.ensure_local_binding(wallet)

        assert binding.account == "oasyce1owneraccount"
        assert binding.delegate == wallet.address
        loaded = LocalIdentityBinding.load(str(temp_oasyce_dir / "identity.v1.json"))
        assert loaded.account == "oasyce1owneraccount"

    def test_rejects_identity_file_delegate_signer_mismatch(self, temp_oasyce_dir):
        wallet = Wallet.create()
        other = Wallet.create()
        wallet_path = temp_oasyce_dir / "wallet.json"
        identity_path = temp_oasyce_dir / "identity.v1.json"
        wallet_path.write_text(
            json.dumps({"mnemonic": wallet.mnemonic, "address": wallet.address})
        )
        identity_path.write_text(
            json.dumps(
                {
                    "schema_version": "oasyce.identity.v1",
                    "account": wallet.address,
                    "delegate": other.address,
                    "signer_address": other.address,
                    "updated_at": "2026-04-04T00:00:00Z",
                }
            )
        )

        with pytest.raises(RuntimeError) as exc:
            IdentityResolver.resolve()

        assert wallet.address in str(exc.value)
        assert other.address in str(exc.value)


class TestTopLevelImports:
    def test_sigil_exports_are_lazy(self):
        sys.modules.pop("oasyce_sdk", None)
        mod = importlib.import_module("oasyce_sdk")

        assert "SigilManager" not in mod.__dict__
        assert "IdentityResolver" not in mod.__dict__
        assert mod.OasyceClient is not None
        assert mod.IdentityResolver is not None
        assert mod.SigilManager is not None
