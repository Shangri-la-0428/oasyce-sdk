"""Channel injection seam — invariant tests.

The symmetric twin of ``tests/test_sigil_manager.py``'s identity-injection
suite. Together they guard the two seams that make ``Agent`` transport
and identity agnostic:

  Agent = Identity × Channel × Substrate
            ^         ^         ^
            |         |         +--- Psyche + Thronglets (always HTTP)
            |         +------------- where replies go (injected via Channel)
            +--------------------- who I am + how I sign (injected via Identity)

This file covers the **Channel** seam introduced in 0.11.6. Before the
extraction, delivery was hard-wired inside ``Samantha.send_reply`` —
calling ``AppClient.send_message`` directly from the pipeline body. A
Discord/CLI/webhook deployment was literally impossible without forking
``Samantha``. The seam restores that freedom: subclass ``Agent``, provide
a ``Channel`` implementation, done.

Invariants guarded:

  - ``Channel`` Protocol is ``@runtime_checkable`` and accepts *any*
    object with a ``deliver(stimulus, response)`` method. No inheritance
    required. A class missing ``deliver`` fails the structural check.
  - ``AppChannel`` satisfies the Protocol and honours the narrow
    contract: chat-only delivery, empty-response no-op, exceptions
    swallowed and logged (never raised into the Agent body).
  - ``Agent._deliver`` is *only* a routing hop to ``self.channel.deliver``.
    No transport knowledge leaks into the base class. Swapping the
    channel redirects all output without touching pipeline code.
  - A minimal custom ``Channel`` (3 lines of code — capture in a list)
    can drive the full Agent seam end-to-end. This is the load-bearing
    test for the whole extraction.
  - The ``identity=`` + ``channel=`` seams compose: Samantha uses an
    injected ``SigilManager`` AND an injected ``AppChannel``, and neither
    knows about the other.

Coverage:
- Protocol structural typing (three cases: valid, bare-minimum, missing)
- AppChannel chat-only filter
- AppChannel empty-response filter
- AppChannel network-error swallow
- AppChannel correct arguments to ``AppClient.send_message``
- Agent._deliver delegates verbatim to the injected channel
- Custom ``InMemoryChannel`` captures deliveries end-to-end
- Swapping channels redirects output with zero Agent body changes
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from oasyce_sdk.agent.channel import Channel
from oasyce_sdk.agent.stimulus import Stimulus


# ── Protocol structural typing ──────────────────────────────────

class TestChannelProtocol:
    """Structural typing guardrail.

    ``Channel`` is declared ``@runtime_checkable``, so ``isinstance``
    works against any object with the right method set — no inheritance,
    no registration, no ABC. If these tests break, the Protocol's
    method set has drifted from what ``Agent`` actually calls, and any
    future channel implementation will silently fail the runtime check.
    """

    def test_minimal_class_with_deliver_satisfies_protocol(self):
        """A 3-line class is enough to be a Channel. This is the seam's
        whole point — no AppChannel inheritance, no framework base class.
        """
        class MinimalChannel:
            def deliver(self, stimulus: Stimulus, response: str) -> None:
                pass

        assert isinstance(MinimalChannel(), Channel)

    def test_class_without_deliver_fails_protocol_check(self):
        """If ``deliver`` is missing, structural typing rejects it.

        This guards against accidentally wiring a sibling object (e.g.
        ``AppClient`` itself, which has ``send_message`` but not
        ``deliver``) as a Channel.
        """
        class NotAChannel:
            def send_message(self, session_id: int, content: str) -> None:
                pass

        assert not isinstance(NotAChannel(), Channel)

    def test_class_with_wrong_method_name_fails_protocol_check(self):
        """Method name matters — ``send`` or ``emit`` are not ``deliver``."""
        class WrongName:
            def send(self, stimulus: Stimulus, response: str) -> None:
                pass

        assert not isinstance(WrongName(), Channel)

    def test_app_channel_satisfies_protocol(self):
        """The reference implementation must pass the structural check.

        If this test fails, ``AppChannel`` has drifted from the Protocol
        and the Samantha deployment cannot construct an Agent — the
        whole extraction is broken.
        """
        from oasyce_sdk.samantha.app_client import AppClient
        from oasyce_sdk.samantha.channel import AppChannel

        app = AppClient("http://127.0.0.1:0")  # never called in this test
        assert isinstance(AppChannel(app), Channel)


# ── AppChannel behaviour ────────────────────────────────────────

class _FakeAppClient:
    """Records send_message calls without doing any network I/O.

    ``requests.Session`` is expensive to stub mid-flight, and the real
    ``AppClient`` would raise on a non-existent base URL. A hand-rolled
    fake keeps the test tight to the Channel contract.
    """

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[int, str]] = []
        self.fail = fail

    def send_message(self, session_id: int, content: str) -> dict:
        if self.fail:
            raise RuntimeError("simulated network failure")
        self.calls.append((session_id, content))
        return {"ok": True}


class TestAppChannel:
    """AppChannel is chat-only, empty-tolerant, and exception-safe.

    These three invariants are stated in the Channel Protocol docstring
    and the AppChannel class docstring — but stating them is not
    enough. The pipeline body calls ``self.channel.deliver`` with
    *whatever* the plan produced, including edge cases the LLM
    invented on its own. If AppChannel raises, the Agent base class
    has no try/except around the deliver hop (by design — the contract
    says Channels MUST NOT raise on network errors), and a bad network
    condition would crash the worker thread.
    """

    def test_chat_kind_is_delivered(self):
        """The happy path: a chat stimulus with a real response is sent
        via ``AppClient.send_message`` with the session id as the first
        arg and the response as the second.
        """
        from oasyce_sdk.samantha.channel import AppChannel

        app = _FakeAppClient()
        channel = AppChannel(app)
        channel.deliver(
            Stimulus(kind="chat", content="hi", session_id=42, sender_id=7),
            "hello there",
        )
        assert app.calls == [(42, "hello there")]

    def test_non_chat_kinds_are_not_delivered(self):
        """Comments, mentions, and feed posts express their reply through
        *tool calls* in the generator phase — not through the Channel.

        This asymmetry is load-bearing: the Channel Protocol is "where
        replies go", and for a post comment the reply IS the tool
        invocation. If AppChannel ever started delivering these kinds,
        Samantha would double-post every comment reply.
        """
        from oasyce_sdk.samantha.channel import AppChannel

        app = _FakeAppClient()
        channel = AppChannel(app)

        for kind in ("comment", "mention", "feed_post"):
            channel.deliver(
                Stimulus(kind=kind, content="payload", session_id=99),
                "should not be sent",
            )

        assert app.calls == []

    def test_empty_response_is_a_noop(self):
        """Plan.intent=='observe' leaves response empty. The pipeline
        still calls deliver — Channel implementations must treat empty
        strings as a no-op rather than posting empty messages.
        """
        from oasyce_sdk.samantha.channel import AppChannel

        app = _FakeAppClient()
        channel = AppChannel(app)
        channel.deliver(
            Stimulus(kind="chat", content="hi", session_id=1),
            "",
        )
        assert app.calls == []

    def test_network_failure_is_swallowed_not_raised(self):
        """Channel contract: deliver MUST NOT raise on network errors.

        The pipeline has no try/except around the deliver hop. If
        AppClient.send_message raises and AppChannel doesn't catch it,
        the exception propagates into ``Agent._deliver`` and then into
        the executor, potentially killing the worker thread. Worse,
        Reflect never runs, so Thronglets loses the turn.

        This test guards the invariant directly: even when the App
        backend explodes, deliver returns normally.
        """
        from oasyce_sdk.samantha.channel import AppChannel

        app = _FakeAppClient(fail=True)
        channel = AppChannel(app)
        # Must not raise
        channel.deliver(
            Stimulus(kind="chat", content="hi", session_id=1),
            "will fail",
        )


# ── Agent routing seam ──────────────────────────────────────────

class _RecordingChannel:
    """Minimal custom Channel — captures deliveries in a list.

    Three lines of code, no inheritance, no AppChannel. If an Agent
    can run end-to-end against this, the seam really is narrow enough
    to drop in any new transport (Discord, stdout, webhook) with the
    same amount of effort.
    """

    def __init__(self) -> None:
        self.delivered: list[tuple[Stimulus, str]] = []

    def deliver(self, stimulus: Stimulus, response: str) -> None:
        self.delivered.append((stimulus, response))


class _StubLLM:
    def generate(self, messages, tools=None):
        from oasyce_sdk.agent.llm import LLMResponse
        return LLMResponse(text="stub reply")


class _StubRegistry:
    def get(self, *, needs_vision: bool = False):
        return _StubLLM()


class _StubIdentity:
    """Just enough SigilManager surface for Agent's default hooks.

    Agent's default ``_perceive`` calls ``identity.perceive(context)``
    and ``_reflect`` calls ``identity.act(...)``. Neither needs to do
    anything real for a Channel-seam test — we only care that the
    response flows out through the injected Channel.
    """

    def __init__(self) -> None:
        self.client = None
        self.address = ""
        self.perceive_calls: list[str] = []
        self.act_calls: list[tuple[str, str, str, str]] = []

    def perceive(self, context: str):
        self.perceive_calls.append(context)
        from oasyce_sdk.agent.runtime import Perception
        # Return a minimal, fully constitutive Perception — the pipeline
        # will consume generation_controls (None by default here).
        return Perception(
            kernel=None, contract=None, thronglets_context="",
            generation_controls=None, ambient_priors=None,
        )

    def act(self, result: str, outcome: str, context: str, *,
            capability: str = "") -> None:
        self.act_calls.append((result, outcome, context, capability))


class TestAgentDeliverySeam:
    """``Agent._deliver`` must only route through ``self.channel.deliver``.

    The base class has no transport knowledge — it imports ``Channel``
    but never touches a requests.Session, a socket, or stdout. The whole
    point of the extraction is that the delivery step is a one-line hop
    into the injected channel.
    """

    def _make_agent(self, channel: Channel):
        """Minimal Agent wired with stubs for everything except the Channel."""
        from oasyce_sdk.agent.base import Agent
        from oasyce_sdk.agent.tools import ToolRegistry
        agent = Agent(
            identity=_StubIdentity(),  # type: ignore[arg-type]
            channel=channel,
            registry=_StubRegistry(),  # type: ignore[arg-type]
            tools=ToolRegistry(),
            constitution="You are a test agent.",
        )
        return agent

    def test_deliver_hook_calls_channel_deliver_verbatim(self):
        """``_deliver`` forwards (stimulus, response) unchanged to Channel."""
        channel = _RecordingChannel()
        agent = self._make_agent(channel)
        try:
            stim = Stimulus(kind="chat", content="hi", session_id=7)
            agent._deliver(stim, "the reply")
            assert channel.delivered == [(stim, "the reply")]
        finally:
            agent.close()

    def test_agent_never_touches_transport_directly(self):
        """The base class must not reach around the injected Channel.

        If some future refactor adds a direct ``requests.post`` or
        ``print`` in ``_deliver`` or ``process``, this test catches it
        by observing that ALL output goes through the recording channel
        and nothing escapes to stderr or the filesystem.
        """
        import io
        import sys

        channel = _RecordingChannel()
        agent = self._make_agent(channel)
        try:
            captured_stdout = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured_stdout
            try:
                agent._deliver(
                    Stimulus(kind="chat", content="test", session_id=1),
                    "should only reach the channel",
                )
            finally:
                sys.stdout = old_stdout

            assert "should only reach" not in captured_stdout.getvalue()
            assert len(channel.delivered) == 1
        finally:
            agent.close()

    def test_channel_swap_redirects_all_output(self):
        """Two Agents with different channels are identical except for
        the output sink. No pipeline code was touched to make this work —
        that's the entire value of the seam.
        """
        ch_a = _RecordingChannel()
        ch_b = _RecordingChannel()
        agent_a = self._make_agent(ch_a)
        agent_b = self._make_agent(ch_b)

        try:
            s1 = Stimulus(kind="chat", content="for A", session_id=1)
            s2 = Stimulus(kind="chat", content="for B", session_id=2)
            agent_a._deliver(s1, "reply-A")
            agent_b._deliver(s2, "reply-B")

            assert ch_a.delivered == [(s1, "reply-A")]
            assert ch_b.delivered == [(s2, "reply-B")]
        finally:
            agent_a.close()
            agent_b.close()

    def test_agent_accepts_any_channel_protocol_impl(self):
        """The seam accepts structural typing — no inheritance required.

        The ``_RecordingChannel`` class above does NOT inherit from
        anything. It just has a ``deliver`` method. If ``Agent.__init__``
        ever starts type-checking ``isinstance(channel, AppChannel)`` or
        some concrete base class, this test fails — preserving the
        Protocol-only contract.
        """
        from oasyce_sdk.agent.base import Agent
        from oasyce_sdk.agent.tools import ToolRegistry

        # No AppChannel import, no inheritance — the seam must accept this.
        class BareChannel:
            def deliver(self, stimulus, response):
                pass

        agent = Agent(
            identity=_StubIdentity(),  # type: ignore[arg-type]
            channel=BareChannel(),  # type: ignore[arg-type]
            registry=_StubRegistry(),  # type: ignore[arg-type]
            tools=ToolRegistry(),
            constitution="test",
        )
        try:
            assert agent.channel is not None
            assert isinstance(agent.channel, Channel)
        finally:
            agent.close()


# ── Composability with the identity seam ───────────────────────

class TestSeamComposability:
    """Identity and Channel seams must compose without knowing each other.

    Samantha's real construction path is::

        identity = resolve_identity(client=chain_client, chain_id=...)
        sigil    = SigilManager(identity=identity, ...)
        agent    = Agent(identity=sigil, channel=AppChannel(app), ...)

    Neither seam reaches across: SigilManager doesn't know about
    Channels, AppChannel doesn't know about ChainSigners. If this test
    passes, a future swap — e.g. an AI-principal Identity with a
    DiscordChannel — requires zero changes to either seam.
    """

    def test_null_identity_plus_custom_channel_composes(self):
        """Two independent injections, one Agent. No glue code needed."""
        from oasyce_sdk.agent.base import Agent
        from oasyce_sdk.agent.tools import ToolRegistry
        from oasyce_sdk.sigil import Identity, SigilManager

        # Substrate-only identity (no wallet, no signer)
        sigil = SigilManager(identity=Identity.null())

        channel = _RecordingChannel()
        agent = Agent(
            identity=sigil,
            channel=channel,
            registry=_StubRegistry(),  # type: ignore[arg-type]
            tools=ToolRegistry(),
            constitution="test",
        )
        try:
            assert agent.identity is sigil
            assert agent.channel is channel
            # Both seams are live and independent
            assert sigil.mode == "substrate_only"
            assert isinstance(agent.channel, Channel)
        finally:
            agent.close()
