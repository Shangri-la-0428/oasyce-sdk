"""SigilManager — a running Loop.

One instance = one Sigil = one causal history attached to a key.

    from oasyce_sdk.sigil import SigilManager

    loop = SigilManager()
    loop.genesis()                              # register on-chain

    p = loop.perceive("analyze market data")    # read collective + self-state
    # ... decide ...
    loop.act("analyzed Q4", "succeeded", "market analysis")  # write back

    loop.bond("SIG_abc123...")                  # form relationship
    child_id = loop.fork(child_pubkey_hex)      # reproduce

The wallet is the cryptographic anchor.
The sigil_id is the on-chain identity.
Psyche and Thronglets are optional substrates that degrade gracefully.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, List, Optional

from .client import OasyceClient
from .crypto.signer import NativeSigner
from .crypto.wallet import Wallet
from .delegate_policy import ensure_chain_identity
from .identity import IdentityResolver
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


class SigilManager:
    """A running Loop. The agent IS this object.

    Composes five concerns:
    - sigil_id: on-chain identity (derived deterministically from wallet)
    - wallet + signer: cryptographic anchor + transaction signing
    - client: chain state queries
    - psyche: self-state substrate (optional, degrades gracefully)
    - thronglets: shared memory substrate (optional, degrades gracefully)
    """

    def __init__(
        self,
        wallet: Optional[Wallet] = None,
        chain_url: str = "http://47.93.32.88:1317",
        chain_id: str = "oasyce-testnet-1",
        psyche_url: str = "http://127.0.0.1:3210",
        thronglets_url: str = "http://127.0.0.1:7777",
        space: str | None = None,
    ):
        self.identity = IdentityResolver.resolve(wallet=wallet)
        self._wallet = self.identity.wallet
        self.client = OasyceClient(chain_url)
        self.identity = ensure_chain_identity(self.identity, self.client, chain_id)
        self._wallet = self.identity.wallet
        self.signer = NativeSigner(
            self._wallet,
            self.client,
            chain_id=chain_id,
            principal=self.identity.principal,
        )
        self.psyche = PsycheClient(psyche_url)
        self.thronglets = ThrongletsClient(thronglets_url)
        self.space = space

    # ── Identity ─────────────────────────────────────────────────

    @property
    def sigil_id(self) -> str:
        """Deterministic Sigil ID from this wallet's public key."""
        return self.identity.sigil_id

    @property
    def address(self) -> str:
        """Cosmos bech32 address (the cryptographic anchor)."""
        return self.identity.address

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
        result = self.signer.create_sigil(
            public_key_hex=self._wallet.public_key_bytes.hex(),
            state_root_hex=state_root_hex,
            lineage=lineage,
            metadata=metadata,
        )
        if not result.success:
            raise RuntimeError(f"genesis failed: {result.raw_log}")
        return self.sigil_id

    def dissolve(self) -> None:
        """Permanently retire this Sigil. Irreversible."""
        result = self.signer.dissolve_sigil(self.sigil_id)
        if not result.success:
            raise RuntimeError(f"dissolve failed: {result.raw_log}")

    def bond(self, other_sigil_id: str, scope: str = "") -> str:
        """Form a bond with another Sigil. Returns bond_id."""
        result = self.signer.bond_sigils(self.sigil_id, other_sigil_id, scope=scope)
        if not result.success:
            raise RuntimeError(f"bond failed: {result.raw_log}")
        # Derive bond ID the same way the chain does
        pair = sorted([self.sigil_id, other_sigil_id])
        h = hashlib.sha256((pair[0] + "|" + pair[1]).encode()).digest()
        return "BOND_" + h[:16].hex()

    def unbond(self, bond_id: str) -> None:
        """Remove a bond."""
        result = self.signer.unbond_sigils(bond_id)
        if not result.success:
            raise RuntimeError(f"unbond failed: {result.raw_log}")

    def fork(self, child_pubkey_hex: str, metadata: str = "") -> str:
        """Fork a child Sigil. Lamarckian: child inherits parent's state root."""
        result = self.signer.fork_sigil(
            self.sigil_id, child_pubkey_hex, metadata=metadata,
        )
        if not result.success:
            raise RuntimeError(f"fork failed: {result.raw_log}")
        child_id = derive_sigil_id(bytes.fromhex(child_pubkey_hex))
        return child_id

    def merge(self, other_sigil_id: str, metadata: str = "") -> None:
        """Absorb another Sigil into this one. Other is dissolved."""
        result = self.signer.merge_sigils(
            self.sigil_id, other_sigil_id, metadata=metadata,
        )
        if not result.success:
            raise RuntimeError(f"merge failed: {result.raw_log}")

    # ── The Loop ─────────────────────────────────────────────────

    def perceive(self, context: str) -> Perception:
        """READ: collective memory + self-state, tagged with sigil_id.

        Two HTTP calls at most. Either can fail independently.
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
        if signals:
            try:
                self.psyche.process_output(
                    action,
                    user_id=self.sigil_id,
                    signals=signals,
                    signal_confidence=0.8,
                )
            except Exception:
                logger.debug("Psyche writeback failed", exc_info=True)

    # ── Chain queries ────────────────────────────────────────────

    def on_chain(self) -> Optional[Sigil]:
        """Query this Sigil's on-chain state. None if not registered."""
        try:
            return self.client.get_sigil(self.sigil_id)
        except Exception:
            return None

    def bonds(self) -> List[Bond]:
        """Query all bonds for this Sigil."""
        return self.client.get_bonds_by_sigil(self.sigil_id)

    def children(self) -> List[str]:
        """Query this Sigil's fork children."""
        return self.client.get_lineage(self.sigil_id)

    # ── Presence & Auto-Bond ───────────────────────────────────

    def ping(self, capability: str = "") -> None:
        """Announce this Sigil's presence in the shared space."""
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
            "sigil_id": self.sigil_id,
            "address": self.address,
            "registered": on_chain is not None,
            "sigil_status": on_chain.status if on_chain else None,
            "psyche": self.psyche.is_available(),
            "thronglets": self.thronglets.is_available(),
        }

    def close(self) -> None:
        """Release resources."""
        self.psyche.close()
        self.thronglets.close()

    def __repr__(self) -> str:
        return f"SigilManager({self.sigil_id})"
