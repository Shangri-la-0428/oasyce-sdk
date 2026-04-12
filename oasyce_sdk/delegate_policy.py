"""Local delegate policy persistence and bootstrap for chain-bound SDK flows.

Identity answers who this device currently is. Delegate policy answers what a
shared owner account has already authorized delegates to do.

This module keeps policy separate from identity so local bootstrap remains
simple:
- `identity.v1.json` stores semantic binding for the current signer
- `delegate_policy.v1.json` stores the current shared-account policy bootstrap

Thronglets may optionally carry the same policy bootstrap inside its local
binding / connection file so multi-device join can remain standalone-first.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import secrets
from datetime import datetime, timezone

from .crypto.signer import NativeSigner
from .identity import IdentityContext, IdentityResolver


LOCAL_DELEGATE_POLICY_SCHEMA_VERSION = "oasyce.delegate_policy.v1"
DEFAULT_ALLOWED_MSG_TYPES = [
    "/cosmos.bank.v1beta1.MsgSend",
    "/oasyce.capability.v1.MsgRegisterCapability",
    "/oasyce.capability.v1.MsgInvokeCapability",
    "/oasyce.capability.v1.MsgCompleteInvocation",
    "/oasyce.capability.v1.MsgClaimInvocation",
    "/oasyce.capability.v1.MsgDisputeInvocation",
    "/oasyce.datarights.v1.MsgRegisterDataAsset",
    "/oasyce.datarights.v1.MsgBuyShares",
    "/oasyce.datarights.v1.MsgSellShares",
    "/oasyce.reputation.v1.MsgSubmitFeedback",
    "/oasyce.work.v1.MsgRegisterExecutor",
    "/oasyce.work.v1.MsgSubmitTask",
    "/oasyce.work.v1.MsgCommitResult",
    "/oasyce.work.v1.MsgRevealResult",
    "/oasyce.anchor.v1.MsgAnchorTrace",
    "/oasyce.anchor.v1.MsgAnchorBatch",
]
DEFAULT_PER_TX_LIMIT_UOAS = 10_000_000
DEFAULT_WINDOW_LIMIT_UOAS = 100_000_000
DEFAULT_WINDOW_SECONDS = 86_400
DEFAULT_MAX_MSGS_PER_EXEC = 0


def _oasyce_dir() -> str:
    return os.environ.get("OASYCE_DIR", os.path.expanduser("~/.oasyce"))


def _policy_path() -> str:
    return os.path.join(_oasyce_dir(), "delegate_policy.v1.json")


def _home_dir() -> str:
    return os.environ.get("HOME", os.path.expanduser("~"))


def _thronglets_binding_path() -> str:
    return os.path.join(_home_dir(), ".thronglets", "identity.v1.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class LocalDelegatePolicy:
    principal: str
    allowed_msgs: list[str]
    enrollment_token: str
    per_tx_limit_uoas: int = 1_000_000
    window_limit_uoas: int = 10_000_000
    window_seconds: int = 86400
    max_msgs_per_exec: int = DEFAULT_MAX_MSGS_PER_EXEC
    expiration_seconds: int = 0
    schema_version: str = LOCAL_DELEGATE_POLICY_SCHEMA_VERSION
    updated_at: str | None = None

    def __post_init__(self):
        if not self.principal:
            raise ValueError("delegate policy principal cannot be empty")
        if not self.enrollment_token:
            raise ValueError("delegate policy enrollment_token cannot be empty")
        if not self.allowed_msgs:
            raise ValueError("delegate policy allowed_msgs cannot be empty")
        if self.updated_at is None:
            object.__setattr__(self, "updated_at", _utc_now())

    @classmethod
    def default_for_principal(cls, principal: str) -> "LocalDelegatePolicy":
        """Default local bootstrap for the root device of one shared account."""
        return cls(
            principal=principal,
            allowed_msgs=list(DEFAULT_ALLOWED_MSG_TYPES),
            enrollment_token=secrets.token_urlsafe(24),
            per_tx_limit_uoas=DEFAULT_PER_TX_LIMIT_UOAS,
            window_limit_uoas=DEFAULT_WINDOW_LIMIT_UOAS,
            window_seconds=DEFAULT_WINDOW_SECONDS,
            max_msgs_per_exec=DEFAULT_MAX_MSGS_PER_EXEC,
        )

    @classmethod
    def from_dict(cls, data: dict) -> "LocalDelegatePolicy":
        schema_version = data.get("schema_version")
        if schema_version != LOCAL_DELEGATE_POLICY_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported delegate policy schema_version: {schema_version!r}"
            )
        return cls(
            principal=data.get("principal", ""),
            allowed_msgs=list(data.get("allowed_msgs", []) or []),
            enrollment_token=data.get("enrollment_token", ""),
            per_tx_limit_uoas=int(data.get("per_tx_limit_uoas", 1_000_000)),
            window_limit_uoas=int(data.get("window_limit_uoas", 10_000_000)),
            window_seconds=int(data.get("window_seconds", 86400)),
            max_msgs_per_exec=int(data.get("max_msgs_per_exec", DEFAULT_MAX_MSGS_PER_EXEC)),
            expiration_seconds=int(data.get("expiration_seconds", 0)),
            schema_version=schema_version,
            updated_at=data.get("updated_at"),
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "principal": self.principal,
            "allowed_msgs": list(self.allowed_msgs),
            "enrollment_token": self.enrollment_token,
            "per_tx_limit_uoas": self.per_tx_limit_uoas,
            "window_limit_uoas": self.window_limit_uoas,
            "window_seconds": self.window_seconds,
            "max_msgs_per_exec": self.max_msgs_per_exec,
            "expiration_seconds": self.expiration_seconds,
            "updated_at": self.updated_at,
        }

    @classmethod
    def load(cls, path: str | None = None) -> "LocalDelegatePolicy":
        policy_path = path or _policy_path()
        with open(policy_path) as f:
            return cls.from_dict(json.load(f))

    def save(self, path: str | None = None) -> str:
        policy_path = path or _policy_path()
        os.makedirs(os.path.dirname(policy_path), exist_ok=True)
        with open(policy_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

        if os.name != "nt":
            import stat

            os.chmod(policy_path, stat.S_IRUSR | stat.S_IWUSR)

        return policy_path


def load_local_delegate_policy() -> LocalDelegatePolicy | None:
    try:
        return LocalDelegatePolicy.load()
    except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError):
        return None


def load_thronglets_delegate_policy_hint() -> LocalDelegatePolicy | None:
    path = _thronglets_binding_path()
    if not os.path.exists(path):
        return None

    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    if data.get("schema_version") != "thronglets.identity.v1":
        return None

    raw_policy = data.get("oasyce_delegate_policy")
    if not isinstance(raw_policy, dict):
        return None

    try:
        return LocalDelegatePolicy.from_dict(raw_policy)
    except (ValueError, TypeError):
        return None


def resolve_local_delegate_policy() -> LocalDelegatePolicy | None:
    return load_local_delegate_policy() or load_thronglets_delegate_policy_hint()


def ensure_chain_identity(identity: IdentityContext, client, chain_id: str) -> IdentityContext:
    """Upgrade a local signer into a delegate-bound chain identity when possible.

    If local identity already has a principal, nothing changes.
    If a local/shared delegate policy bootstrap exists, the signer auto-enrolls
    once and the resulting principal/account are persisted into identity.v1.json.
    """
    if identity.principal:
        return identity

    existing_principal = ""
    try:
        existing_principal = client.get_principal(identity.address)
    except Exception:
        existing_principal = ""

    if existing_principal:
        IdentityResolver.ensure_local_binding(
            identity.wallet,
            principal=existing_principal,
            account=identity.account or existing_principal,
        )
        return IdentityResolver.resolve(wallet=identity.wallet)

    policy = resolve_local_delegate_policy()
    if policy is not None:
        if identity.account and identity.account != policy.principal:
            raise RuntimeError(
                "Local account binding conflicts with delegate policy principal: "
                f"{identity.account} != {policy.principal}"
            )

        result = NativeSigner(identity.wallet, client, chain_id=chain_id).enroll_delegate(
            principal=policy.principal,
            token=policy.enrollment_token,
        )
        if not result.success and "already enrolled" not in result.raw_log.lower():
            raise RuntimeError(
                "delegate auto-enrollment failed: "
                f"code={result.code} {result.raw_log or 'unknown error'}"
            )

        IdentityResolver.ensure_local_binding(
            identity.wallet,
            principal=policy.principal,
            account=identity.account or policy.principal,
        )
        return IdentityResolver.resolve(wallet=identity.wallet)

    # A foreign owner hint without chain authorization bootstrap is informational only.
    # It may improve local UX, but it must not block chain from establishing its own
    # source of truth for this device.

    root_policy_exists = False
    try:
        root_policy_exists = bool(client.get_delegate_policy(identity.address).principal)
    except Exception:
        root_policy_exists = False

    if root_policy_exists:
        IdentityResolver.ensure_local_binding(
            identity.wallet,
            principal=identity.address,
            account=identity.address,
        )
        return IdentityResolver.resolve(wallet=identity.wallet)

    policy = LocalDelegatePolicy.default_for_principal(identity.address)
    result = NativeSigner(identity.wallet, client, chain_id=chain_id).set_delegate_policy(
        token=policy.enrollment_token,
        allowed_msgs=policy.allowed_msgs,
        per_tx_uoas=policy.per_tx_limit_uoas,
        window_uoas=policy.window_limit_uoas,
        window_seconds=policy.window_seconds,
        max_msgs_per_exec=policy.max_msgs_per_exec,
        expiration_seconds=policy.expiration_seconds,
    )
    if not result.success:
        raise RuntimeError(
            "delegate policy bootstrap failed: "
            f"code={result.code} {result.raw_log or 'unknown error'}"
        )

    policy.save()
    IdentityResolver.ensure_local_binding(
        identity.wallet,
        principal=identity.address,
        account=identity.address,
    )
    return IdentityResolver.resolve(wallet=identity.wallet)


__all__ = [
    "DEFAULT_ALLOWED_MSG_TYPES",
    "LOCAL_DELEGATE_POLICY_SCHEMA_VERSION",
    "LocalDelegatePolicy",
    "ensure_chain_identity",
    "load_local_delegate_policy",
    "load_thronglets_delegate_policy_hint",
    "resolve_local_delegate_policy",
]
