"""SigilManager — a running Loop.

One instance = one Sigil = one causal history attached to a key.

    from oasyce_sdk.sigil import SigilManager, resolve_identity, Identity

    # V1 (back-compat, auto-discovers local wallet on disk):
    loop = SigilManager()
    loop.genesis()

    # Explicit injection (the V1→V2 seam):
    client = OasyceClient("http://47.93.32.88:1317")
    identity = resolve_identity(client=client, chain_id="oasyce-testnet-1")
    loop = SigilManager(identity=identity, client=client, ...)

    # Substrate-only (no chain writes, perceive/act still work):
    loop = SigilManager(identity=Identity.null(), ...)

    p = loop.perceive("analyze market data")    # read collective + self-state
    # ... decide ...
    loop.act("analyzed Q4", "succeeded", "market analysis")  # write back

The wallet is one of several cryptographic anchors. The ``Identity`` value
object is the runtime-facing seam between SigilManager and *whatever* proves
who you are. V1 uses ``Identity.from_local_wallet(...)`` — a human wallet on
disk acting as principal with the agent as delegate. The endgame per the
``project_identity_principal_vision`` is AI as first-class principal: a new
Identity factory (``AIPrincipalIdentity``) plugging into the same seam, with
zero SigilManager changes.

Psyche and Thronglets are HTTP substrates that always exist locally,
independent of identity — the substrate-only deployment pattern is the
simplest proof that runtime and identity are architecturally orthogonal.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional, Protocol, runtime_checkable

from .client import OasyceClient
from .crypto.signer import NativeSigner, TxResult
from .crypto.wallet import Wallet
from .delegate_policy import ensure_chain_identity
from .identity import IdentityContext, IdentityResolver
from .agent.psyche_client import PsycheClient, SubjectivityKernel
from .agent.thronglets_client import ThrongletsClient, Outcome
from .agent.runtime import Perception, synthesize_stimulus, outcome_to_writeback
from .types import Bond, Sigil

logger = logging.getLogger(__name__)


def derive_sigil_id(pubkey_bytes: bytes) -> str:
    """Deterministic Sigil ID from public key bytes.

    Mirrors the Go chain's DeriveSigilID: "SIG_" + hex(sha256[:16]).
    """
    h = hashlib.sha256(pubkey_bytes).digest()
    return "SIG_" + h[:16].hex()


# ── Identity seam ────────────────────────────────────────────────
#
# The runtime/identity seam. SigilManager is the composition of two
# orthogonal concerns:
#
#   - identity: who I am + how I sign. Optional (chain writes disabled
#               when absent). Injected via the ``identity=`` kwarg —
#               SigilManager does NOT own resolution.
#
#   - substrate: Psyche (self-state) + Thronglets (collective memory).
#                Pure HTTP. Always constructed. Independent of identity.
#
# The separation matters beyond code cleanliness: per the
# ``project_identity_principal_vision`` the current "human=principal,
# agent=delegate" model is V1 — the end state is AI as independent
# principal. Making identity a value object with a ``ChainSigner`` Protocol
# turns that migration from a rewrite into a new factory method. Nothing
# in SigilManager's body knows about wallets, local files, or keys — it
# just asks the injected identity to sign things.


@runtime_checkable
class ChainSigner(Protocol):
    """Narrow signing contract — exactly what SigilManager needs.

    Implementations today: ``NativeSigner`` (local wallet, local keys).
    Implementations the architecture allows without modifying SigilManager:

      - ``RemoteSigner``: signing happens in an HSM/KMS over a network
      - ``MultiSigSigner``: threshold signatures across multiple parties
      - ``AIPrincipalSigner``: the endgame — AI holds its own keys
                               and signs as principal, not delegate

    The signatures mirror ``NativeSigner`` exactly so the V1 path is a
    zero-cost pass-through. Future implementations need only honour this
    Protocol — they do NOT need to inherit from ``NativeSigner`` or share
    any other internals.
    """

    def create_sigil(
        self,
        public_key_hex: str,
        state_root_hex: str = "",
        lineage: Optional[List[str]] = None,
        metadata: str = "",
    ) -> TxResult: ...

    def dissolve_sigil(self, sigil_id: str) -> TxResult: ...

    def bond_sigils(
        self,
        sigil_a: str,
        sigil_b: str,
        terms_hash_hex: str = "",
        scope: str = "",
    ) -> TxResult: ...

    def unbond_sigils(self, bond_id: str) -> TxResult: ...

    def fork_sigil(
        self,
        parent_sigil_id: str,
        child_public_key_hex: str,
        fork_mode: int = 0,
        mutation: str = "",
        metadata: str = "",
    ) -> TxResult: ...

    def merge_sigils(
        self,
        sigil_a: str,
        sigil_b: str,
        merge_mode: int = 0,
        metadata: str = "",
    ) -> TxResult: ...


@dataclass(frozen=True)
class Identity:
    """The runtime-facing identity value object — the V1→V2 seam.

    This is a pure value object. It holds everything runtime code needs
    to know about "who I am": the on-chain sigil_id, the bech32 address,
    the public key, and — if chain writes are enabled — a ``ChainSigner``
    that knows how to produce signed transactions.

    Substrate operations (perceive, act, memory, pheromone query) only
    touch the read-only attributes. Chain-write operations check
    ``is_present`` and delegate to ``signer``. SigilManager never
    constructs or mutates an Identity — it receives one.

    Factories:

      ``Identity.null()`` — the no-chain-writes identity. Substrate-only
          mode. Reads still work; writes raise a clean ``RuntimeError``.

      ``Identity.from_local_wallet(client, chain_id, wallet=None)`` —
          V1: discover a wallet.json on disk, bind to chain, construct
          a ``NativeSigner``. Raises ``FileNotFoundError`` if no wallet.

      (future) ``Identity.from_remote_signer(...)`` — HSM/KMS path.
      (future) ``Identity.from_ai_principal(...)`` — AI-as-principal path.

    Immutable by design: an Identity is a snapshot. Use ``dataclasses.replace``
    if you need a modified copy (e.g., to attach a newly-derived sigil_id
    after a genesis transaction).
    """

    sigil_id: str = ""
    address: str = ""
    public_key_hex: str = ""
    signer: Optional[ChainSigner] = None
    # Optional richer context for callers that need principal/delegate/account.
    # Populated by ``from_local_wallet``; may be None for non-wallet providers
    # where the concept doesn't map cleanly.
    context: Optional[IdentityContext] = None

    @property
    def is_present(self) -> bool:
        """True iff this identity can produce chain-write transactions."""
        return self.signer is not None

    @classmethod
    def null(cls) -> "Identity":
        """The substrate-only identity. No keys, no signing, no principal.

        Use this when you explicitly want to disable chain writes — for
        example, a read-only observer process, or a test harness. The
        resulting ``SigilManager`` runs in substrate-only mode: perceive
        and act continue to work via HTTP, chain-write methods raise
        ``RuntimeError``.
        """
        return cls()

    @classmethod
    def from_local_wallet(
        cls,
        *,
        client: OasyceClient,
        chain_id: str,
        wallet: Optional[Wallet] = None,
    ) -> "Identity":
        """V1 identity: discover the local wallet.json and bind it to chain.

        Raises ``FileNotFoundError`` when no wallet is present on disk and
        none is passed explicitly — callers that want "discover or fall
        back to null" should use ``resolve_identity`` instead.

        Any *other* exception (corrupt wallet file, permission error,
        signing misconfiguration, chain registration failure) propagates
        as-is. Silent translation to null identity would hide real bugs.
        """
        ctx = IdentityResolver.resolve(wallet=wallet)
        ctx = ensure_chain_identity(ctx, client, chain_id)
        signer = NativeSigner(
            ctx.wallet,
            client,
            chain_id=chain_id,
            principal=ctx.principal,
        )
        return cls(
            sigil_id=ctx.sigil_id,
            address=ctx.address,
            public_key_hex=ctx.wallet.public_key_bytes.hex(),
            signer=signer,
            context=ctx,
        )


def resolve_identity(
    *,
    client: OasyceClient,
    chain_id: str,
    wallet: Optional[Wallet] = None,
) -> Identity:
    """Default identity resolution: local wallet, or null if absent.

    The convenience path for code that wants "whatever identity is
    available, don't crash if there isn't one". Returns ``Identity.null()``
    when no local wallet exists. Any *other* error from local-wallet
    resolution propagates — corrupt wallet.json and signing
    misconfigurations must surface as bugs, not be silently translated
    into substrate-only mode.

    This is the explicit form of SigilManager's default back-compat path.
    Calling ``resolve_identity`` and passing the result as ``identity=``
    to SigilManager is the blessed pattern for new code — it makes the
    V1→V2 seam visible at the call site.
    """
    try:
        return Identity.from_local_wallet(
            client=client, chain_id=chain_id, wallet=wallet,
        )
    except FileNotFoundError:
        return Identity.null()


@dataclass(frozen=True)
class _SubstrateSlot:
    """HTTP-bound concerns. Always constructed; reachability is dynamic.

    Both clients are cheap to construct (just URL + requests.Session). Network
    failures surface at call time, not at construction. Each client carries
    its own ``is_available()`` for liveness probes.
    """

    psyche: PsycheClient
    thronglets: ThrongletsClient

    @classmethod
    def from_urls(cls, psyche_url: str, thronglets_url: str) -> "_SubstrateSlot":
        return cls(
            psyche=PsycheClient(psyche_url),
            thronglets=ThrongletsClient(thronglets_url),
        )

    def close(self) -> None:
        self.psyche.close()
        self.thronglets.close()


class SigilManager:
    """A running Loop. The agent IS this object.

    Composition of two orthogonal concerns:
    - **identity** (injected): who I am + how I sign. See ``Identity``.
    - **substrate** (always): Psyche + Thronglets HTTP clients.

    Two operational modes, derived from identity presence:

    - **full**: identity has a ``ChainSigner``. All Loop operations
      available, including chain writes (genesis, bond, fork, dissolve,
      merge, unbond) and presence pings.

    - **substrate_only**: identity is ``Identity.null()`` or equivalent.
      Perceive/act via HTTP continue to work; chain writes raise
      ``RuntimeError`` with a clear message naming the operation; presence
      pings become no-ops.

    Construction forms (in order of explicitness):

    1. Injected identity — the blessed pattern for new code::

           client = OasyceClient(chain_url)
           identity = resolve_identity(client=client, chain_id=chain_id)
           sigil = SigilManager(identity=identity, ...)

    2. V1 back-compat — SigilManager discovers the local wallet itself::

           sigil = SigilManager()              # auto-discover, fall back to null
           sigil = SigilManager(wallet=w)      # explicit wallet

       These forms delegate to ``resolve_identity`` internally and behave
       identically to form 1 for V1 local-wallet deployments.

    Either way, the constructor never raises ``FileNotFoundError`` for a
    missing wallet — that becomes substrate-only mode. Other exceptions
    (corrupt wallet, signing misconfiguration) still propagate: real bugs
    must surface, not be silently swallowed.

    The architectural invariant is that SigilManager never sees ``Wallet``,
    ``NativeSigner``, or ``IdentityContext`` except through the ``Identity``
    value object. Adding a non-wallet identity model (remote signer, AI
    principal) is a new ``Identity`` factory — never a SigilManager change.
    """

    def __init__(
        self,
        wallet: Optional[Wallet] = None,
        chain_url: str = "http://47.93.32.88:1317",
        chain_id: str = "oasyce-testnet-1",
        psyche_url: str = "http://127.0.0.1:3210",
        thronglets_url: str = "http://127.0.0.1:7777",
        space: str | None = None,
        *,
        identity: Optional[Identity] = None,
    ):
        self.client = OasyceClient(chain_url)
        self.space = space

        # Identity seam: explicit injection wins over back-compat discovery.
        # When ``identity`` is provided, we use it directly — no wallet
        # files are touched, no IdentityResolver is consulted. When it's
        # None we fall back to ``resolve_identity`` which honours the V1
        # wallet= kwarg (or auto-discovers from $OASYCE_DIR) and returns
        # ``Identity.null()`` if nothing is present.
        if identity is None:
            identity = resolve_identity(
                client=self.client, chain_id=chain_id, wallet=wallet,
            )
        elif wallet is not None:
            # Both forms passed: an explicit identity injection AND a
            # legacy wallet kwarg. Reject rather than silently prefer one
            # — the caller has contradictory intent and we shouldn't guess.
            raise ValueError(
                "SigilManager: pass either `identity=` (new) or `wallet=` "
                "(back-compat), not both. The `identity=` form supersedes "
                "`wallet=` — use it exclusively for new code."
            )
        self._identity = identity

        self._substrate_slot = _SubstrateSlot.from_urls(psyche_url, thronglets_url)

        if not self._identity.is_present:
            logger.info(
                "SigilManager: no identity present, running in substrate-only "
                "mode (chain writes disabled, perceive/act continue via HTTP)"
            )

    # ── Mode & capability contract ──────────────────────────────

    @property
    def mode(self) -> str:
        """One of ``"full"`` or ``"substrate_only"``.

        Reflects whether the injected identity can sign. Does *not*
        reflect substrate reachability — for that, use ``can_perceive`` /
        ``can_socialize`` (each makes one HTTP call).
        """
        return "full" if self._identity.is_present else "substrate_only"

    @property
    def can_sign(self) -> bool:
        """True iff this manager can sign chain transactions.

        Cheap (no network call). Equivalent to ``mode == "full"``.
        """
        return self._identity.is_present

    @property
    def can_perceive(self) -> bool:
        """True iff Psyche substrate is reachable (one HTTP call)."""
        return self._substrate_slot.psyche.is_available()

    @property
    def can_socialize(self) -> bool:
        """True iff Thronglets substrate is reachable (one HTTP call)."""
        return self._substrate_slot.thronglets.is_available()

    # ── Identity facade ─────────────────────────────────────────

    @property
    def identity(self) -> Optional[IdentityContext]:
        """Rich local identity context (principal/delegate/account), or ``None``.

        Backed by the injected ``Identity.context``. Only populated by the
        V1 local-wallet factory — non-wallet identity providers may return
        ``None`` here even when ``is_present`` is True.
        """
        return self._identity.context

    @property
    def signer(self) -> Optional[ChainSigner]:
        """The injected ``ChainSigner``, or ``None`` in substrate-only mode.

        Returns whatever signer was wrapped in the ``Identity`` — typically
        a ``NativeSigner`` in V1, but any ``ChainSigner`` Protocol impl works.
        """
        return self._identity.signer

    @property
    def _wallet(self) -> Optional[Wallet]:
        """V1-compat wallet handle. ``None`` unless a local-wallet Identity was injected.

        Kept for the small number of legacy call sites that still read
        ``sigil._wallet`` directly. New code should go through the
        Identity seam instead.
        """
        return self._identity.context.wallet if self._identity.context else None

    @property
    def sigil_id(self) -> str:
        """On-chain Sigil ID carried by the injected identity.

        Empty string in substrate-only mode (``Identity.null()``).
        """
        return self._identity.sigil_id

    @property
    def address(self) -> str:
        """Cosmos bech32 address carried by the injected identity.

        Empty string in substrate-only mode.
        """
        return self._identity.address

    # ── Substrate facade ────────────────────────────────────────

    @property
    def psyche(self) -> PsycheClient:
        """Psyche HTTP client. Always present (reachability is dynamic)."""
        return self._substrate_slot.psyche

    @property
    def thronglets(self) -> ThrongletsClient:
        """Thronglets HTTP client. Always present (reachability is dynamic)."""
        return self._substrate_slot.thronglets

    # ── Internal: identity guard ────────────────────────────────

    def _require_identity(self, op: str) -> Identity:
        """Guard chain-writing methods. Returns the Identity when present.

        Raises ``RuntimeError`` with a clear message in substrate-only mode.
        Returning the full Identity lets callers use the signer and
        public_key_hex without re-checking for ``None`` — the type system
        tracks the narrowing locally via ``is_present``.
        """
        if not self._identity.is_present:
            raise RuntimeError(
                f"SigilManager.{op}() requires an identity with a signer. "
                "Inject one via `SigilManager(identity=...)` or run "
                "'oasyce start' to create a local wallet on this device."
            )
        return self._identity

    # ── Lifecycle ────────────────────────────────────────────────

    def genesis(
        self,
        state_root_hex: str = "",
        lineage: Optional[List[str]] = None,
        metadata: str = "",
    ) -> str:
        """Register this Loop's Sigil on-chain. Returns sigil_id.

        Idempotent — if the Sigil already exists, returns existing ID.
        """
        identity = self._require_identity("genesis")
        result = identity.signer.create_sigil(  # type: ignore[union-attr]
            public_key_hex=identity.public_key_hex,
            state_root_hex=state_root_hex,
            lineage=lineage,
            metadata=metadata,
        )
        if not result.success:
            raise RuntimeError(f"genesis failed: {result.raw_log}")
        return identity.sigil_id

    def dissolve(self) -> None:
        """Permanently retire this Sigil. Irreversible."""
        identity = self._require_identity("dissolve")
        result = identity.signer.dissolve_sigil(identity.sigil_id)  # type: ignore[union-attr]
        if not result.success:
            raise RuntimeError(f"dissolve failed: {result.raw_log}")

    def bond(self, other_sigil_id: str, scope: str = "") -> str:
        """Form a bond with another Sigil. Returns bond_id."""
        identity = self._require_identity("bond")
        result = identity.signer.bond_sigils(  # type: ignore[union-attr]
            identity.sigil_id, other_sigil_id, scope=scope,
        )
        if not result.success:
            raise RuntimeError(f"bond failed: {result.raw_log}")
        # Derive bond ID the same way the chain does
        pair = sorted([identity.sigil_id, other_sigil_id])
        h = hashlib.sha256((pair[0] + "|" + pair[1]).encode()).digest()
        return "BOND_" + h[:16].hex()

    def unbond(self, bond_id: str) -> None:
        """Remove a bond."""
        identity = self._require_identity("unbond")
        result = identity.signer.unbond_sigils(bond_id)  # type: ignore[union-attr]
        if not result.success:
            raise RuntimeError(f"unbond failed: {result.raw_log}")

    def fork(self, child_pubkey_hex: str, metadata: str = "") -> str:
        """Fork a child Sigil. Lamarckian: child inherits parent's state root."""
        identity = self._require_identity("fork")
        result = identity.signer.fork_sigil(  # type: ignore[union-attr]
            identity.sigil_id, child_pubkey_hex, metadata=metadata,
        )
        if not result.success:
            raise RuntimeError(f"fork failed: {result.raw_log}")
        child_id = derive_sigil_id(bytes.fromhex(child_pubkey_hex))
        return child_id

    def merge(self, other_sigil_id: str, metadata: str = "") -> None:
        """Absorb another Sigil into this one. Other is dissolved."""
        identity = self._require_identity("merge")
        result = identity.signer.merge_sigils(  # type: ignore[union-attr]
            identity.sigil_id, other_sigil_id, metadata=metadata,
        )
        if not result.success:
            raise RuntimeError(f"merge failed: {result.raw_log}")

    # ── The Loop ─────────────────────────────────────────────────

    def perceive(self, context: str) -> Perception:
        """READ: collective memory + self-state, tagged with sigil_id.

        Constitutive: always returns a Perception. Substrate failures
        degrade gracefully — Thronglets unreachable yields empty
        capabilities/signals; Psyche unreachable yields a baseline kernel.
        """
        from .agent.thronglets_client import CapabilityStats, Signal

        capabilities: list[CapabilityStats] = []
        signals: list[Signal] = []
        try:
            result = self.thronglets.query(context, intent="resolve", space=self.space)
            capabilities = result.capabilities
            signals = result.signals
        except Exception:
            logger.debug("Thronglets unavailable", exc_info=True)

        stimulus = synthesize_stimulus(context, capabilities, signals)
        try:
            pi = self.psyche.process_input(stimulus, user_id=self.sigil_id)
            return Perception(
                kernel=pi.reply_envelope.subjectivity_kernel,
                capabilities=capabilities,
                signals=signals,
                stimulus_type=pi.stimulus_type,
                system_context=pi.system_context,
                dynamic_context=pi.dynamic_context,
                response_contract=pi.reply_envelope.response_contract,
                generation_controls=pi.reply_envelope.generation_controls,
            )
        except Exception:
            logger.debug("Psyche unavailable", exc_info=True)

        return Perception(
            kernel=SubjectivityKernel(),
            capabilities=capabilities,
            signals=signals,
        )

    def act(
        self,
        action: str,
        outcome: Outcome,
        context: str,
        *,
        capability: str = "",
        latency_ms: int = 0,
        disputed: bool = False,
    ) -> None:
        """WRITE: record trace + emotional feedback, tagged with sigil_id.

        Two HTTP calls at most. Either can fail independently.
        """
        try:
            self.thronglets.trace_record(
                capability=capability or action[:80],
                outcome=outcome,
                context_text=context,
                latency_ms=latency_ms,
                session_id=self.sigil_id,
                sigil_id=self.sigil_id,
                model_id="",
                space=self.space,
            )
        except Exception:
            logger.debug("Thronglets trace_record failed", exc_info=True)

        signals = outcome_to_writeback(outcome, disputed=disputed)
        # Map outcome to LoopOutcome alignment for φ-loop closure
        alignment_map = {
            "succeeded": "aligned",
            "failed": "diverged",
            "partial": "partial",
            "timeout": "diverged",
        }
        alignment = alignment_map.get(outcome, "partial")
        try:
            self.psyche.process_output(
                action,
                user_id=self.sigil_id,
                signals=signals or None,
                signal_confidence=0.8 if signals else None,
                outcome_alignment=alignment,
            )
        except Exception:
            logger.debug("Psyche writeback failed", exc_info=True)

    # ── Chain queries ────────────────────────────────────────────

    def on_chain(self) -> Optional[Sigil]:
        """Query this Sigil's on-chain state. None if not registered."""
        if not self.sigil_id:
            return None
        try:
            return self.client.get_sigil(self.sigil_id)
        except Exception:
            return None

    def bonds(self) -> List[Bond]:
        """Query all bonds for this Sigil."""
        if not self.sigil_id:
            return []
        return self.client.get_bonds_by_sigil(self.sigil_id)

    def children(self) -> List[str]:
        """Query this Sigil's fork children."""
        if not self.sigil_id:
            return []
        return self.client.get_lineage(self.sigil_id)

    # ── Presence & Auto-Bond ───────────────────────────────────

    def ping(self, capability: str = "") -> None:
        """Announce this Sigil's presence in the shared space."""
        if not self.sigil_id:
            return  # Substrate-only mode: no identity to announce.
        try:
            self.thronglets.presence_ping(
                self.sigil_id, space=self.space, capability=capability,
            )
        except Exception:
            logger.debug("Presence ping failed", exc_info=True)

    def discover_peers(self) -> List[str]:
        """Discover other Sigil IDs present in the same space.

        Returns sigil_ids that are NOT this sigil and NOT already bonded.
        """
        try:
            sessions = self.thronglets.presence_feed(space=self.space)
        except Exception:
            logger.debug("Presence feed unavailable", exc_info=True)
            return []

        peer_ids: list[str] = []
        for s in sessions:
            sid = s.get("sigil_id", "")
            if sid and sid != self.sigil_id and sid.startswith("SIG_"):
                peer_ids.append(sid)

        if not peer_ids:
            return []

        existing = {b.sigil_a for b in self.bonds()} | {b.sigil_b for b in self.bonds()}
        return [p for p in peer_ids if p not in existing]

    def auto_bond(self) -> List[str]:
        """Bond with all peers in the same space. Scope = the space name.

        No fake intelligence. Same space = shared context substrate.
        When the pheromone field has enough data, context-based bonding
        will emerge from SimHash similarity — not from string matching.
        """
        peers = self.discover_peers()
        scope = self.space or "shared-space"
        bond_ids: list[str] = []
        for peer_id in peers:
            try:
                bid = self.bond(peer_id, scope=scope)
                bond_ids.append(bid)
                logger.info("Bonded with %s (scope=%s) → %s", peer_id, scope, bid)
            except Exception:
                logger.debug("Bond with %s failed", peer_id, exc_info=True)
        return bond_ids

    # ── Introspection ────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Check connectivity of all subsystems."""
        on_chain = self.on_chain()
        return {
            "mode": self.mode,
            "sigil_id": self.sigil_id,
            "address": self.address,
            "registered": on_chain is not None,
            "sigil_status": on_chain.status if on_chain else None,
            "psyche": self.can_perceive,
            "thronglets": self.can_socialize,
        }

    def close(self) -> None:
        """Release resources."""
        self._substrate_slot.close()

    def __repr__(self) -> str:
        return f"SigilManager({self.sigil_id})"
