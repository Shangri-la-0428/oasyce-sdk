"""SigilManager tests — identity/runtime seam + substrate-only regression guard.

The Loop is the composition of two orthogonal concerns:

- **identity** (injected): a public ``Identity`` value object carrying the
  on-chain sigil_id, bech32 address, public key, and a ``ChainSigner``
  Protocol implementation — or ``Identity.null()`` for substrate-only mode.
  SigilManager never constructs an Identity; it receives one.

- **substrate** (always): Psyche + Thronglets HTTP clients, orthogonal to
  identity — they need URLs, not keys.

This file covers two generations of regression guards:

1. **Substrate-only mode (0.11.2/0.11.3 root cause).** Phase 0 deployment
   surfaced a bug where ``SigilManager.__init__`` raised ``FileNotFoundError``
   when no local wallet existed, taking down the entire Loop on server-side
   deployments where chain signing happens elsewhere (per Chain.Creator
   constraint). Result: even with Psyche+Thronglets running on the server,
   Samantha never called them — ``self.sigil`` was ``None``.

2. **Identity injection seam (0.11.5).** The V1 back-compat path was only
   a minimal patch — the real architectural separation (identity and
   runtime must be decoupled per ``project_identity_principal_vision``'s
   "V1 principal=human is temporary") landed in 0.11.5 by promoting
   ``Identity`` to a public, injectable value object and narrowing the
   signing contract to a ``ChainSigner`` Protocol.

Invariants guarded:

  - ``SigilManager.__init__`` never raises ``FileNotFoundError`` for the
    no-wallet case (substrate-only mode). Other exceptions still propagate.
  - Substrate clients are always constructed regardless of identity branch.
  - A pre-built ``Identity`` passed via ``identity=`` bypasses wallet
    discovery entirely (no filesystem or IdentityResolver call).
  - Any object satisfying the ``ChainSigner`` Protocol can drive chain
    writes — no inheritance, no wallet, no ``NativeSigner`` required.
  - ``SigilManager(identity=X, wallet=Y)`` is rejected: contradictory intent
    must not be silently resolved by preferring one over the other.

Coverage:
- mode contract: "full" with identity, "substrate_only" without
- can_sign mirrors mode (cheap, no network call)
- substrate clients are always constructed (psyche/thronglets non-None)
- sigil_id/address fall back to "" in substrate-only mode
- chain-writing methods raise a clean RuntimeError naming the operation
- query/presence methods short-circuit gracefully
- with-wallet path is unaffected (regression guard)
- injected Identity (populated or null) short-circuits discovery
- custom ChainSigner Protocol drives full chain writes end-to-end
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import List, Optional

import pytest

from oasyce_sdk.crypto.signer import TxResult
from oasyce_sdk.crypto.wallet import Wallet
from oasyce_sdk.sigil import (
    ChainSigner,
    Identity,
    SigilManager,
    resolve_identity,
)


@pytest.fixture
def no_identity_dir(tmp_path, monkeypatch):
    """Make Wallet.resolve_binding raise FileNotFoundError."""
    monkeypatch.setenv("OASYCE_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("OASYCE_MNEMONIC", raising=False)
    return tmp_path


@pytest.fixture
def with_identity_dir(tmp_path, monkeypatch):
    """Place a real wallet.json so identity resolution succeeds."""
    monkeypatch.setenv("OASYCE_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("OASYCE_MNEMONIC", raising=False)
    wallet = Wallet.create()
    (tmp_path / "wallet.json").write_text(
        json.dumps({"mnemonic": wallet.mnemonic, "address": wallet.address})
    )
    return tmp_path


class TestSubstrateOnlyMode:
    def test_init_succeeds_when_no_wallet(self, no_identity_dir):
        sm = SigilManager(
            chain_url="http://127.0.0.1:1317",
            psyche_url="http://127.0.0.1:3210",
            thronglets_url="http://127.0.0.1:7777",
        )
        assert sm.identity is None
        assert sm._wallet is None
        assert sm.signer is None
        # HTTP substrates always present
        assert sm.psyche is not None
        assert sm.thronglets is not None
        assert sm.client is not None  # read-only chain queries still possible

    def test_mode_is_substrate_only_without_wallet(self, no_identity_dir):
        sm = SigilManager()
        assert sm.mode == "substrate_only"
        assert sm.can_sign is False

    def test_sigil_id_and_address_are_empty_strings(self, no_identity_dir):
        sm = SigilManager()
        assert sm.sigil_id == ""
        assert sm.address == ""

    def test_chain_write_methods_raise_clean_error(self, no_identity_dir):
        sm = SigilManager()
        for op, call in [
            ("genesis", lambda: sm.genesis()),
            ("dissolve", lambda: sm.dissolve()),
            ("bond", lambda: sm.bond("SIG_other")),
            ("unbond", lambda: sm.unbond("BOND_x")),
            ("fork", lambda: sm.fork("02" + "11" * 32)),
            ("merge", lambda: sm.merge("SIG_other")),
        ]:
            with pytest.raises(RuntimeError) as exc:
                call()
            assert op in str(exc.value)
            assert "wallet" in str(exc.value).lower()

    def test_on_chain_returns_none_without_identity(self, no_identity_dir):
        sm = SigilManager()
        # Must NOT make any HTTP call — short-circuit before client.get_sigil
        assert sm.on_chain() is None

    def test_bonds_and_children_return_empty(self, no_identity_dir):
        sm = SigilManager()
        assert sm.bonds() == []
        assert sm.children() == []

    def test_ping_is_noop_without_identity(self, no_identity_dir):
        sm = SigilManager()
        # Should not raise, should not call thronglets at all
        called = {"presence_ping": False}

        def _spy(*args, **kwargs):
            called["presence_ping"] = True

        sm.thronglets.presence_ping = _spy  # type: ignore[assignment]
        sm.ping(capability="test")
        assert called["presence_ping"] is False

    def test_repr_includes_empty_id(self, no_identity_dir):
        sm = SigilManager()
        assert "SigilManager()" == repr(sm) or repr(sm) == "SigilManager()"

    def test_status_reports_substrate_only_mode(self, no_identity_dir):
        sm = SigilManager()
        st = sm.status()
        assert st["mode"] == "substrate_only"
        assert st["sigil_id"] == ""
        assert st["address"] == ""
        assert st["registered"] is False
        # psyche/thronglets reachability fields are bools (they make HTTP
        # probes — values depend on whether anything is listening, which we
        # don't assert here; just that they're present and bool-typed).
        assert isinstance(st["psyche"], bool)
        assert isinstance(st["thronglets"], bool)


class TestArchitecturalInvariants:
    """The contract that prevents this whole class of bug from coming back.

    These are not feature tests — they are *invariants* the rest of the
    codebase relies on. If any of them break, the substrate-only deployment
    pattern silently regresses to the original "naked Loop" failure mode.
    """

    def test_init_never_raises_filenotfound_for_missing_wallet(
        self, no_identity_dir
    ):
        """The whole point of the decoupling fix.

        ``FileNotFoundError`` from ``IdentityResolver`` MUST be caught
        inside ``resolve_identity`` and translated into ``Identity.null()``.
        If this ever leaks out again, samantha's eager construction will
        crash and the silent-degradation pattern will return.
        """
        # No try/except — failure here IS the test failing.
        SigilManager()

    def test_substrate_clients_are_independent_of_identity(self, no_identity_dir):
        """psyche/thronglets must not be gated on identity presence.

        The whole reason the Loop runs in substrate-only mode is that
        Psyche/Thronglets are pure HTTP — they need URLs, not wallets.
        Construction order in __init__ must reflect that: substrate
        construction happens unconditionally after identity resolution,
        regardless of which branch identity took.
        """
        sm = SigilManager()
        assert sm._identity.is_present is False
        # Substrate construction reached this point in __init__
        assert sm._substrate_slot.psyche is sm.psyche
        assert sm._substrate_slot.thronglets is sm.thronglets

    def test_unrelated_exceptions_still_propagate(self, no_identity_dir, monkeypatch):
        """Only FileNotFoundError gets the substrate-only translation.

        If IdentityResolver.resolve raises something else (corrupt JSON,
        permission error, signing misconfiguration), the constructor MUST
        let it through. Catching ``Exception`` would re-introduce the
        original silent-degradation bug at a different layer.
        """
        from oasyce_sdk import sigil as sigil_mod

        class CorruptIdentity(ValueError):
            pass

        def _boom(*_a, **_k):
            raise CorruptIdentity("identity.v1.json is corrupt")

        monkeypatch.setattr(sigil_mod.IdentityResolver, "resolve", _boom)
        with pytest.raises(CorruptIdentity):
            SigilManager()


class TestWithIdentity:
    """Sanity check: the fix doesn't break the with-wallet path."""

    def test_init_succeeds_with_wallet_and_populates_identity(
        self, with_identity_dir, monkeypatch
    ):
        # Skip ensure_chain_identity's network call by monkeypatching it.
        from oasyce_sdk import sigil as sigil_mod

        monkeypatch.setattr(
            sigil_mod, "ensure_chain_identity", lambda identity, *_a, **_k: identity
        )
        sm = SigilManager(
            chain_url="http://127.0.0.1:1317",
            psyche_url="http://127.0.0.1:3210",
            thronglets_url="http://127.0.0.1:7777",
        )
        assert sm.identity is not None
        assert sm._wallet is not None
        assert sm.signer is not None
        assert sm.sigil_id.startswith("SIG_")
        assert sm.address.startswith("oasyce1")

    def test_mode_is_full_with_wallet(self, with_identity_dir, monkeypatch):
        from oasyce_sdk import sigil as sigil_mod

        monkeypatch.setattr(
            sigil_mod, "ensure_chain_identity", lambda identity, *_a, **_k: identity
        )
        sm = SigilManager()
        assert sm.mode == "full"
        assert sm.can_sign is True


class TestPerceiveAmbientPriors:
    def test_perceive_includes_ambient_priors(self, no_identity_dir):
        sm = SigilManager()
        sm.thronglets.query = lambda *a, **k: SimpleNamespace(capabilities=[], signals=[])  # type: ignore[assignment]
        sm.thronglets.ambient_priors = lambda *a, **k: {  # type: ignore[assignment]
            "priors": [{"kind": "watch", "message": "slow path nearby"}]
        }
        sm.psyche.process_input = lambda *a, **k: SimpleNamespace(  # type: ignore[assignment]
            stimulus_type="analysis",
            system_context="",
            dynamic_context="",
            reply_envelope=SimpleNamespace(
                subjectivity_kernel=SimpleNamespace(vitality=0.5),
                response_contract=None,
                generation_controls=None,
            ),
        )

        perception = sm.perceive("analyze data")

        assert perception.ambient_priors == {
            "priors": [{"kind": "watch", "message": "slow path nearby"}]
        }


# ── Identity injection seam (0.11.5) ────────────────────────────────


class _FakeChainSigner:
    """In-process ``ChainSigner`` Protocol implementation for tests.

    Records every call. Satisfies the Protocol structurally — no
    inheritance, no wallet, no network. This is the whole point of
    the seam: any object shaped like ``ChainSigner`` drives SigilManager
    without modifying a single line of it.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def create_sigil(
        self,
        public_key_hex: str,
        state_root_hex: str = "",
        lineage: Optional[List[str]] = None,
        metadata: str = "",
    ) -> TxResult:
        self.calls.append(("create_sigil", {
            "public_key_hex": public_key_hex,
            "state_root_hex": state_root_hex,
            "lineage": lineage,
            "metadata": metadata,
        }))
        return TxResult(tx_hash="0xfake_create", success=True, code=0, raw_log="ok")

    def dissolve_sigil(self, sigil_id: str) -> TxResult:
        self.calls.append(("dissolve_sigil", {"sigil_id": sigil_id}))
        return TxResult(tx_hash="0xfake_dissolve", success=True, code=0, raw_log="ok")

    def bond_sigils(
        self,
        sigil_a: str,
        sigil_b: str,
        terms_hash_hex: str = "",
        scope: str = "",
    ) -> TxResult:
        self.calls.append(("bond_sigils", {
            "sigil_a": sigil_a, "sigil_b": sigil_b,
            "terms_hash_hex": terms_hash_hex, "scope": scope,
        }))
        return TxResult(tx_hash="0xfake_bond", success=True, code=0, raw_log="ok")

    def unbond_sigils(self, bond_id: str) -> TxResult:
        self.calls.append(("unbond_sigils", {"bond_id": bond_id}))
        return TxResult(tx_hash="0xfake_unbond", success=True, code=0, raw_log="ok")

    def fork_sigil(
        self,
        parent_sigil_id: str,
        child_public_key_hex: str,
        fork_mode: int = 0,
        mutation: str = "",
        metadata: str = "",
    ) -> TxResult:
        self.calls.append(("fork_sigil", {
            "parent_sigil_id": parent_sigil_id,
            "child_public_key_hex": child_public_key_hex,
            "fork_mode": fork_mode,
            "mutation": mutation,
            "metadata": metadata,
        }))
        return TxResult(tx_hash="0xfake_fork", success=True, code=0, raw_log="ok")

    def merge_sigils(
        self,
        sigil_a: str,
        sigil_b: str,
        merge_mode: int = 0,
        metadata: str = "",
    ) -> TxResult:
        self.calls.append(("merge_sigils", {
            "sigil_a": sigil_a, "sigil_b": sigil_b,
            "merge_mode": merge_mode, "metadata": metadata,
        }))
        return TxResult(tx_hash="0xfake_merge", success=True, code=0, raw_log="ok")


class TestIdentityInjection:
    """The V1→V2 architectural seam.

    The test for whether identity and runtime are really separated is
    whether you can run SigilManager with a custom identity that has
    nothing to do with a local wallet. If these tests pass, an
    AI-principal identity factory can be added in a future version
    without touching SigilManager's body.
    """

    def test_inject_null_identity_runs_in_substrate_only_mode(self, no_identity_dir):
        """``Identity.null()`` is the explicit substrate-only switch.

        Passing ``identity=Identity.null()`` must behave identically to
        the back-compat no-wallet path: mode substrate_only, no signer,
        empty sigil_id, chain writes raise, substrate clients present.
        """
        sm = SigilManager(identity=Identity.null())
        assert sm.mode == "substrate_only"
        assert sm.can_sign is False
        assert sm.signer is None
        assert sm.sigil_id == ""
        assert sm.address == ""
        assert sm.psyche is not None
        assert sm.thronglets is not None
        with pytest.raises(RuntimeError, match="genesis"):
            sm.genesis()

    def test_inject_populated_identity_skips_wallet_discovery(
        self, no_identity_dir, monkeypatch
    ):
        """An injected Identity must bypass ``resolve_identity`` entirely.

        This is the load-bearing invariant of the seam. If callers can
        provide an Identity, the runtime MUST NOT reach into the
        filesystem or the IdentityResolver — otherwise the alternative
        identity backends the seam exists for (AI principal, HSM, remote
        signer) cannot work without also making local wallet files exist.
        """
        from oasyce_sdk import sigil as sigil_mod

        def _boom(*_a, **_k):
            raise AssertionError(
                "resolve_identity was called despite explicit identity= injection"
            )

        monkeypatch.setattr(sigil_mod, "resolve_identity", _boom)

        fake = _FakeChainSigner()
        injected = Identity(
            sigil_id="SIG_ab" + "cd" * 7,
            address="oasyce1testaddress000000000000000000000000",
            public_key_hex="02" + "11" * 32,
            signer=fake,
        )
        sm = SigilManager(identity=injected)
        assert sm.mode == "full"
        assert sm.can_sign is True
        assert sm.sigil_id == "SIG_ab" + "cd" * 7
        assert sm.address.startswith("oasyce1")
        assert sm.signer is fake
        # identity context is intentionally None — non-wallet identities
        # may not have a principal/delegate distinction.
        assert sm.identity is None
        assert sm._wallet is None

    def test_injected_identity_drives_chain_writes_end_to_end(self, no_identity_dir):
        """A custom signer satisfying the Protocol must drive all 6 writes.

        This proves the signing contract is truly Protocol-narrow —
        ``genesis``, ``dissolve``, ``bond``, ``unbond``, ``fork``, ``merge``
        all route through whatever the caller passed, with zero
        ``NativeSigner`` or ``Wallet`` inheritance.
        """
        fake = _FakeChainSigner()
        injected = Identity(
            sigil_id="SIG_" + "ab" * 8,
            address="oasyce1fakeaddr0000000000000000000000000000",
            public_key_hex="03" + "22" * 32,
            signer=fake,
        )
        sm = SigilManager(identity=injected)

        # genesis → create_sigil
        sigil_id = sm.genesis(metadata="hello")
        assert sigil_id == "SIG_" + "ab" * 8

        # bond → bond_sigils (also exercises bond_id derivation)
        bid = sm.bond("SIG_" + "ef" * 8, scope="test-space")
        assert bid.startswith("BOND_")

        # unbond → unbond_sigils
        sm.unbond(bid)

        # fork → fork_sigil (child_public_key_hex argument)
        child_pk = "02" + "33" * 32
        child_id = sm.fork(child_pk, metadata="child")
        assert child_id.startswith("SIG_")

        # merge → merge_sigils
        sm.merge("SIG_" + "cd" * 8, metadata="absorb")

        # dissolve → dissolve_sigil (last because it's conceptually final)
        sm.dissolve()

        call_names = [c[0] for c in fake.calls]
        assert call_names == [
            "create_sigil",
            "bond_sigils",
            "unbond_sigils",
            "fork_sigil",
            "merge_sigils",
            "dissolve_sigil",
        ]
        # Spot-check that arguments flowed through unchanged
        create_args = fake.calls[0][1]
        assert create_args["public_key_hex"] == "03" + "22" * 32
        assert create_args["metadata"] == "hello"

    def test_fake_signer_satisfies_chain_signer_protocol_check(self):
        """Structural typing guardrail.

        ``ChainSigner`` is declared ``@runtime_checkable``, so
        ``isinstance(fake, ChainSigner)`` must return True. If this
        test breaks, the Protocol's method set has drifted from what
        SigilManager actually calls, and any future identity backend
        will silently fail the runtime check.
        """
        assert isinstance(_FakeChainSigner(), ChainSigner)

    def test_contradictory_wallet_and_identity_kwargs_rejected(self, no_identity_dir):
        """``identity=`` and ``wallet=`` together is a caller bug.

        Silently preferring one over the other would hide the intent
        mismatch at the call site. Rejecting it loudly forces the
        caller to delete the legacy ``wallet=`` kwarg when migrating
        to the new seam.
        """
        w = Wallet.create()
        with pytest.raises(ValueError, match="identity.*wallet.*not both"):
            SigilManager(identity=Identity.null(), wallet=w)

    def test_resolve_identity_returns_null_when_no_wallet(self, no_identity_dir):
        """The module-level helper is the explicit form of the back-compat path.

        New code should prefer ``resolve_identity(...)`` + ``identity=``
        over the implicit ``SigilManager()``, because it makes the seam
        visible at the call site. Both must behave identically for V1
        local-wallet deployments.
        """
        from oasyce_sdk.client import OasyceClient

        client = OasyceClient("http://127.0.0.1:1317")
        identity = resolve_identity(client=client, chain_id="oasyce-testnet-1")
        assert isinstance(identity, Identity)
        assert identity.is_present is False
        assert identity.signer is None

    def test_resolve_identity_propagates_non_filenotfound_errors(
        self, no_identity_dir, monkeypatch
    ):
        """Corrupt-wallet and signing-misconfig bugs must NOT become null identity.

        ``resolve_identity`` only swallows ``FileNotFoundError``. Everything
        else propagates. Silent translation of arbitrary exceptions to
        null identity would re-introduce the silent-degradation bug that
        0.11.2/0.11.3 fixed, at the helper level instead of the class level.
        """
        from oasyce_sdk import sigil as sigil_mod
        from oasyce_sdk.client import OasyceClient

        class CorruptWallet(ValueError):
            pass

        def _boom(*_a, **_k):
            raise CorruptWallet("wallet.json has invalid JSON")

        monkeypatch.setattr(sigil_mod.IdentityResolver, "resolve", _boom)
        client = OasyceClient("http://127.0.0.1:1317")
        with pytest.raises(CorruptWallet):
            resolve_identity(client=client, chain_id="oasyce-testnet-1")

    def test_identity_null_factory_is_immutable_value(self):
        """``Identity.null()`` returns an empty-but-valid Identity.

        Frozen dataclass; no signer; ``is_present`` False. This is a
        cheap smoke test that catches accidental factory regressions
        (e.g., returning a mock, raising, stripping the frozen flag).
        """
        null_id = Identity.null()
        assert null_id.is_present is False
        assert null_id.signer is None
        assert null_id.sigil_id == ""
        assert null_id.address == ""
        # Frozen — assignment must raise
        with pytest.raises((AttributeError, TypeError)):
            null_id.sigil_id = "SIG_should_fail"  # type: ignore[misc]
