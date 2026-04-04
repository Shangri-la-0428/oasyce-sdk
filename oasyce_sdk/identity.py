"""Identity resolution for oasyce-sdk surfaces.

This module keeps the SDK-level identity surface above raw signer material.
`wallet.json` holds secp256k1 signer material. `identity.v1.json` holds the
local semantic binding that sdk-facing surfaces share. When users adopt
Thronglets first, the local Thronglets owner binding may optionally seed the
account hint for the first sdk binding.

It is intentionally not the global identity authority for the whole stack.
Psyche, Thronglets, Babel, and Chain must remain independently adoptable.
This module only defines the shared bridge object that sdk-facing surfaces use
when they need to resolve local execution identity.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Literal

from .crypto.wallet import Wallet, WalletBinding, WalletBindingSource


IdentityBindingSource = Literal["identity_file", "compat_wallet", "explicit"]


def _oasyce_dir() -> str:
    return os.environ.get("OASYCE_DIR", os.path.expanduser("~/.oasyce"))


def _binding_path() -> str:
    return os.path.join(_oasyce_dir(), "identity.v1.json")


def _home_dir() -> str:
    return os.environ.get("HOME", os.path.expanduser("~"))


def _thronglets_binding_path() -> str:
    return os.path.join(_home_dir(), ".thronglets", "identity.v1.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _derive_sigil_id(pubkey_bytes: bytes) -> str:
    digest = hashlib.sha256(pubkey_bytes).digest()
    return "SIG_" + digest[:16].hex()


@dataclass(frozen=True)
class LocalIdentityBinding:
    """Semantic local binding for sdk-facing execution surfaces."""

    signer_address: str
    principal: str | None = None
    account: str | None = None
    delegate: str | None = None
    schema_version: str = "oasyce.identity.v1"
    updated_at: str | None = None

    def __post_init__(self):
        if self.delegate is None:
            object.__setattr__(self, "delegate", self.signer_address)
        if self.updated_at is None:
            object.__setattr__(self, "updated_at", _utc_now())

    @classmethod
    def default_for_wallet(
        cls,
        wallet: Wallet,
        *,
        principal: str | None = None,
        account: str | None = None,
        delegate: str | None = None,
    ) -> "LocalIdentityBinding":
        return cls(
            signer_address=wallet.address,
            principal=principal,
            account=account,
            delegate=delegate,
        )

    @classmethod
    def load(cls, path: str | None = None) -> "LocalIdentityBinding":
        binding_path = path or _binding_path()
        if not os.path.exists(binding_path):
            raise FileNotFoundError(binding_path)

        with open(binding_path) as f:
            data = json.load(f)

        schema_version = data.get("schema_version")
        if schema_version != "oasyce.identity.v1":
            raise ValueError(
                f"{binding_path} has unsupported schema_version: {schema_version!r}"
            )

        signer_address = data.get("signer_address") or data.get("delegate")
        if not signer_address:
            raise ValueError(f"{binding_path} is missing signer_address")

        return cls(
            signer_address=signer_address,
            principal=data.get("principal"),
            account=data.get("account"),
            delegate=data.get("delegate"),
            schema_version=schema_version,
            updated_at=data.get("updated_at"),
        )

    def save(self, path: str | None = None) -> str:
        binding_path = path or _binding_path()
        os.makedirs(os.path.dirname(binding_path), exist_ok=True)
        with open(binding_path, "w") as f:
            json.dump(
                {
                    "schema_version": self.schema_version,
                    "principal": self.principal,
                    "account": self.account,
                    "delegate": self.delegate,
                    "signer_address": self.signer_address,
                    "updated_at": self.updated_at,
                },
                f,
                indent=2,
            )

        if os.name != "nt":
            import stat

            os.chmod(binding_path, stat.S_IRUSR | stat.S_IWUSR)

        return binding_path

    def validate_signer(self, wallet: Wallet, *, path: str | None = None) -> None:
        if self.signer_address != wallet.address:
            source = path or _binding_path()
            raise RuntimeError(
                "Local identity binding does not match the current signer: "
                f"{source} -> {self.signer_address}, signer -> {wallet.address}. "
                "Align the binding or signer before writing."
            )

        if self.delegate != wallet.address:
            source = path or _binding_path()
            raise RuntimeError(
                "Local identity binding delegate must match the current signer: "
                f"{source} delegate -> {self.delegate}, signer -> {wallet.address}."
            )


@dataclass(frozen=True)
class ThrongletsOwnerHint:
    """Optional owner/account hint imported from local Thronglets state."""

    owner_account: str
    source_path: str

    @classmethod
    def load(cls, path: str | None = None) -> "ThrongletsOwnerHint":
        hint_path = path or _thronglets_binding_path()
        if not os.path.exists(hint_path):
            raise FileNotFoundError(hint_path)

        with open(hint_path) as f:
            data = json.load(f)

        if data.get("schema_version") != "thronglets.identity.v1":
            raise ValueError(f"{hint_path} is not a Thronglets identity binding")

        owner_account = data.get("owner_account")
        if not owner_account:
            raise ValueError(f"{hint_path} does not contain owner_account")

        return cls(owner_account=owner_account, source_path=hint_path)


@dataclass(frozen=True)
class IdentityContext:
    """Resolved local execution identity for one runtime surface."""

    wallet: Wallet
    binding_source: IdentityBindingSource
    binding_path: str | None = None
    signer_source: WalletBindingSource = "explicit"
    signer_path: str | None = None
    principal: str | None = None
    account: str | None = None
    delegate: str | None = None
    session_id: str | None = None

    def __post_init__(self):
        if self.delegate is None:
            object.__setattr__(self, "delegate", self.wallet.address)

    @property
    def address(self) -> str:
        return self.wallet.address

    @property
    def sigil_id(self) -> str:
        return _derive_sigil_id(self.wallet.public_key_bytes)

    def with_session(self, session_id: str | None) -> "IdentityContext":
        return replace(self, session_id=session_id)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "address": self.address,
            "principal": self.principal,
            "account": self.account,
            "delegate": self.delegate,
            "session_id": self.session_id,
            "sigil_id": self.sigil_id,
            "binding_source": self.binding_source,
            "binding_path": self.binding_path,
            "signer_source": self.signer_source,
            "signer_path": self.signer_path,
        }


class IdentityResolver:
    """Single identity entrypoint for SDK surfaces."""

    @classmethod
    def load_thronglets_owner_hint(cls) -> ThrongletsOwnerHint | None:
        try:
            return ThrongletsOwnerHint.load()
        except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError):
            return None

    @classmethod
    def binding_path(cls) -> str:
        return _binding_path()

    @classmethod
    def load_local_binding(cls) -> LocalIdentityBinding:
        return LocalIdentityBinding.load(_binding_path())

    @classmethod
    def ensure_local_binding(
        cls,
        wallet: Wallet | None = None,
        *,
        principal: str | None = None,
        account: str | None = None,
        delegate: str | None = None,
    ) -> LocalIdentityBinding:
        wallet_binding = Wallet.resolve_binding(wallet)
        binding_path = _binding_path()
        owner_hint = cls.load_thronglets_owner_hint()

        if os.path.exists(binding_path):
            current = LocalIdentityBinding.load(binding_path)
            current.validate_signer(wallet_binding.wallet, path=binding_path)
            updated = LocalIdentityBinding(
                signer_address=current.signer_address,
                principal=principal if principal is not None else current.principal,
                account=account if account is not None else current.account,
                delegate=delegate if delegate is not None else current.delegate,
            )
            if updated != current:
                updated.save(binding_path)
            return updated

        created = LocalIdentityBinding.default_for_wallet(
            wallet_binding.wallet,
            principal=principal,
            account=account if account is not None else owner_hint.owner_account if owner_hint else None,
            delegate=delegate,
        )
        created.save(binding_path)
        return created

    @classmethod
    def _resolve_with_wallet(
        cls,
        wallet_binding,
        *,
        principal: str | None = None,
        account: str | None = None,
        delegate: str | None = None,
        session_id: str | None = None,
        prefer_local_binding: bool = True,
    ) -> IdentityContext:
        owner_hint = cls.load_thronglets_owner_hint()

        if wallet_binding.source == "explicit" and not prefer_local_binding:
            return IdentityContext(
                wallet=wallet_binding.wallet,
                binding_source="explicit",
                binding_path=None,
                signer_source=wallet_binding.source,
                signer_path=wallet_binding.path,
                principal=principal,
                account=account if account is not None else owner_hint.owner_account if owner_hint else None,
                delegate=delegate,
                session_id=session_id,
            )

        binding_path = _binding_path()
        if os.path.exists(binding_path):
            local = LocalIdentityBinding.load(binding_path)
            local.validate_signer(wallet_binding.wallet, path=binding_path)
            return IdentityContext(
                wallet=wallet_binding.wallet,
                binding_source="identity_file",
                binding_path=binding_path,
                signer_source=wallet_binding.source,
                signer_path=wallet_binding.path,
                principal=principal if principal is not None else local.principal,
                account=account if account is not None else local.account,
                delegate=delegate if delegate is not None else local.delegate,
                session_id=session_id,
            )

        return IdentityContext(
            wallet=wallet_binding.wallet,
            binding_source="explicit" if wallet_binding.source == "explicit" else "compat_wallet",
            binding_path=None,
            signer_source=wallet_binding.source,
            signer_path=wallet_binding.path,
            principal=principal,
            account=account if account is not None else owner_hint.owner_account if owner_hint else None,
            delegate=delegate,
            session_id=session_id,
        )

    @classmethod
    def resolve(
        cls,
        wallet: Wallet | None = None,
        *,
        principal: str | None = None,
        account: str | None = None,
        delegate: str | None = None,
        session_id: str | None = None,
    ) -> IdentityContext:
        wallet_binding = Wallet.resolve_binding(wallet)
        return cls._resolve_with_wallet(
            wallet_binding,
            principal=principal,
            account=account,
            delegate=delegate,
            session_id=session_id,
        )

    @classmethod
    def resolve_local(
        cls,
        *,
        session_id: str | None = None,
        principal: str | None = None,
        account: str | None = None,
        delegate: str | None = None,
    ) -> IdentityContext:
        path = Wallet._wallet_path()
        wallet_binding = WalletBinding(wallet=Wallet.from_file(path), source="file", path=path)
        return cls._resolve_with_wallet(
            wallet_binding,
            principal=principal,
            account=account,
            delegate=delegate,
            session_id=session_id,
            prefer_local_binding=True,
        )


__all__ = ["IdentityContext", "IdentityResolver", "LocalIdentityBinding", "ThrongletsOwnerHint"]
