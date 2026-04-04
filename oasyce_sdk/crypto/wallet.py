"""Oasyce Wallet — secp256k1 keypair with BIP39/BIP32 derivation.

Designed for AI agents: create from mnemonic or raw key, derive
Cosmos-compatible bech32 address, sign arbitrary bytes.

    wallet = Wallet.create()
    wallet = Wallet.from_mnemonic("abandon abandon ... art")
    wallet = Wallet.from_private_key("a1b2c3...")
    wallet = Wallet.from_env()  # reads OASYCE_MNEMONIC
    binding = Wallet.resolve_binding()  # wallet + source metadata
    wallet = Wallet.auto()      # device wallet with conflict detection
"""

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import struct
from typing import Literal, Optional

from .bech32 import bech32_encode

# Cosmos HD path: m/44'/118'/0'/0/0
_BIP44_PATH = [44 + 0x80000000, 118 + 0x80000000, 0 + 0x80000000, 0, 0]
_ADDRESS_PREFIX = "oasyce"

# ---------------------------------------------------------------------------
# secp256k1 backend abstraction
# ---------------------------------------------------------------------------

try:
    import coincurve

    def _privkey_to_pubkey(privkey_bytes: bytes) -> bytes:
        """Compressed public key (33 bytes) from private key."""
        pk = coincurve.PublicKey.from_valid_secret(privkey_bytes)
        return pk.format(compressed=True)

    def _sign_digest(privkey_bytes: bytes, digest: bytes) -> bytes:
        """Sign a 32-byte digest, return 64-byte compact signature (r || s)."""
        pk = coincurve.PrivateKey(privkey_bytes)
        sig = pk.sign_recoverable(digest, hasher=None)
        # sig is 65 bytes: r(32) + s(32) + recovery_id(1)
        return sig[:64]

    _BACKEND = "coincurve"

except ImportError:
    from ecdsa import SECP256k1, SigningKey as _EcdsaSK
    from ecdsa.util import sigencode_string

    def _privkey_to_pubkey(privkey_bytes: bytes) -> bytes:
        sk = _EcdsaSK.from_string(privkey_bytes, curve=SECP256k1)
        vk = sk.get_verifying_key()
        # Compress: 02 + x if y is even, 03 + x if y is odd
        x = vk.to_string()[:32]
        y = vk.to_string()[32:]
        prefix = b"\x02" if y[-1] % 2 == 0 else b"\x03"
        return prefix + x

    def _sign_digest(privkey_bytes: bytes, digest: bytes) -> bytes:
        sk = _EcdsaSK.from_string(privkey_bytes, curve=SECP256k1)
        return sk.sign_digest(digest, sigencode=sigencode_string)

    _BACKEND = "ecdsa"


# ---------------------------------------------------------------------------
# BIP32 key derivation (minimal, only what we need)
# ---------------------------------------------------------------------------

_SECP256K1_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def _bip32_derive_child(key: bytes, chain_code: bytes, index: int) -> tuple:
    """Derive a single child key (hardened if index >= 0x80000000)."""
    if index >= 0x80000000:
        # Hardened: HMAC-SHA512(chain_code, 0x00 + key + index)
        data = b"\x00" + key + struct.pack(">I", index)
    else:
        # Normal: HMAC-SHA512(chain_code, pubkey + index)
        pubkey = _privkey_to_pubkey(key)
        data = pubkey + struct.pack(">I", index)

    h = hmac.new(chain_code, data, hashlib.sha512).digest()
    child_key_int = (int.from_bytes(h[:32], "big") + int.from_bytes(key, "big")) % _SECP256K1_ORDER
    child_key = child_key_int.to_bytes(32, "big")
    child_chain = h[32:]
    return child_key, child_chain


def _derive_from_seed(seed: bytes) -> bytes:
    """Derive private key from BIP39 seed using Cosmos BIP44 path."""
    h = hmac.new(b"Bitcoin seed", seed, hashlib.sha512).digest()
    key, chain_code = h[:32], h[32:]

    for index in _BIP44_PATH:
        key, chain_code = _bip32_derive_child(key, chain_code, index)

    return key


def _address_from_pubkey(pubkey: bytes) -> str:
    """Cosmos address: bech32(prefix, sha256(pubkey)[:20])."""
    addr_bytes = hashlib.sha256(pubkey).digest()[:20]
    return bech32_encode(_ADDRESS_PREFIX, addr_bytes)


# ---------------------------------------------------------------------------
# Wallet class
# ---------------------------------------------------------------------------


WalletBindingSource = Literal["explicit", "env", "file"]


@dataclass(frozen=True)
class WalletBinding:
    """Resolved signer material plus where that binding came from."""

    wallet: "Wallet"
    source: WalletBindingSource
    path: str | None = None


class Wallet:
    """Oasyce wallet holding a secp256k1 keypair."""

    def __init__(self, private_key: bytes, mnemonic_phrase: Optional[str] = None):
        if len(private_key) != 32:
            raise ValueError("Private key must be 32 bytes")
        self._privkey = private_key
        self._pubkey = _privkey_to_pubkey(private_key)
        self._address = _address_from_pubkey(self._pubkey)
        self._mnemonic = mnemonic_phrase

    @classmethod
    def create(cls) -> "Wallet":
        """Generate a new wallet with a random 24-word mnemonic."""
        from mnemonic import Mnemonic
        m = Mnemonic("english")
        phrase = m.generate(strength=256)  # 24 words
        seed = m.to_seed(phrase)
        privkey = _derive_from_seed(seed)
        return cls(privkey, mnemonic_phrase=phrase)

    @classmethod
    def from_mnemonic(cls, phrase: str, passphrase: str = "") -> "Wallet":
        """Restore wallet from a BIP39 mnemonic."""
        from mnemonic import Mnemonic
        m = Mnemonic("english")
        if not m.check(phrase):
            raise ValueError("Invalid mnemonic phrase")
        seed = m.to_seed(phrase, passphrase)
        privkey = _derive_from_seed(seed)
        return cls(privkey, mnemonic_phrase=phrase)

    @classmethod
    def from_private_key(cls, hex_key: str) -> "Wallet":
        """Create wallet from a raw hex-encoded private key."""
        privkey = bytes.fromhex(hex_key)
        return cls(privkey)

    @classmethod
    def from_env(cls, env_var: str = "OASYCE_MNEMONIC") -> "Wallet":
        """Load wallet from environment variable (mnemonic or hex private key)."""
        value = os.environ.get(env_var, "")
        if not value:
            raise ValueError(f"Environment variable {env_var} is not set")
        # If it looks like a hex key (64 hex chars), treat as private key
        if len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value):
            return cls.from_private_key(value)
        # Otherwise treat as mnemonic
        return cls.from_mnemonic(value)

    @classmethod
    def _wallet_path(cls) -> str:
        return os.path.join(
            os.environ.get("OASYCE_DIR", os.path.expanduser("~/.oasyce")),
            "wallet.json",
        )

    @classmethod
    def from_file(cls, path: Optional[str] = None) -> "Wallet":
        """Load wallet from wallet.json (mnemonic or private_key)."""
        wallet_path = path or cls._wallet_path()
        if not os.path.exists(wallet_path):
            raise FileNotFoundError(wallet_path)

        with open(wallet_path) as f:
            data = json.load(f)

        if "mnemonic" in data:
            return cls.from_mnemonic(data["mnemonic"])
        if "private_key" in data:
            return cls.from_private_key(data["private_key"])

        raise ValueError(
            f"{wallet_path} does not contain 'mnemonic' or 'private_key'"
        )

    @classmethod
    def resolve_binding(cls, wallet: Optional["Wallet"] = None) -> WalletBinding:
        """Resolve signer material plus binding source metadata.

        Resolution order:
        1. Explicit Wallet passed by code
        2. OASYCE_MNEMONIC
        3. ~/.oasyce/wallet.json

        If env and file both exist but resolve to different addresses, fail fast.
        """
        if wallet is not None:
            return WalletBinding(wallet=wallet, source="explicit")

        wallet_path = cls._wallet_path()
        file_wallet = None
        if os.path.exists(wallet_path):
            file_wallet = cls.from_file(wallet_path)

        mnemonic = os.environ.get("OASYCE_MNEMONIC", "").strip()
        if mnemonic:
            env_wallet = cls.from_env("OASYCE_MNEMONIC")
            if file_wallet and env_wallet.address != file_wallet.address:
                raise RuntimeError(
                    "Identity conflict on this device: "
                    f"OASYCE_MNEMONIC -> {env_wallet.address}, "
                    f"{wallet_path} -> {file_wallet.address}. "
                    "Align them or pass an explicit Wallet to override."
                )
            return WalletBinding(wallet=env_wallet, source="env")

        if file_wallet:
            return WalletBinding(wallet=file_wallet, source="file", path=wallet_path)

        raise FileNotFoundError(
            "No identity found. Run 'oasyce start' to create one."
        )

    @classmethod
    def auto(cls) -> "Wallet":
        """Resolve the device wallet.

        Resolution order:
        1. OASYCE_MNEMONIC
        2. ~/.oasyce/wallet.json

        If both exist but resolve to different addresses, fail fast. A single
        device should not silently switch between two chain identities.
        """
        return cls.resolve_binding().wallet

    @property
    def address(self) -> str:
        """Bech32 address (oasyce1...)."""
        return self._address

    @property
    def public_key_bytes(self) -> bytes:
        """33-byte compressed secp256k1 public key."""
        return self._pubkey

    @property
    def mnemonic(self) -> Optional[str]:
        """The mnemonic phrase (None if created from raw key)."""
        return self._mnemonic

    def sign_digest(self, digest: bytes) -> bytes:
        """Sign a 32-byte SHA256 digest. Returns 64-byte compact signature."""
        if len(digest) != 32:
            raise ValueError("Digest must be 32 bytes (SHA256)")
        return _sign_digest(self._privkey, digest)

    def export_private_key(self) -> str:
        """Hex-encoded private key. Handle with care."""
        return self._privkey.hex()

    def __repr__(self) -> str:
        return f"Wallet(address={self._address!r}, backend={_BACKEND!r})"
