"""Channel — the runtime/transport seam for the Agent pipeline.

``Channel`` is the symmetric twin of ``ChainSigner`` (see ``oasyce_sdk.sigil``):

- ``ChainSigner``: narrow Protocol for signing on-chain transactions. Any
  implementation that honours the method signatures can be dropped into
  ``SigilManager`` without the manager knowing about wallets, HSMs, or
  AI-principal key storage.

- ``Channel``: narrow Protocol for emitting a stimulus response into the
  world. Any implementation that honours ``deliver(stimulus, response)``
  can be dropped into ``Agent`` without the Agent knowing about App
  backends, Discord sockets, stdout, or Slack webhooks.

Why these two seams are the whole story:

    Agent = Identity × Channel × Substrate
              ^         ^        ^
              |         |        +--- Psyche + Thronglets (always HTTP)
              |         +------------ where replies go (injected)
              +---------------------- who I am + how I sign (injected)

Everything else in the Agent class — the PGE pipeline, the tool loop, the
perception/reflection wiring — is transport-agnostic. Swap Channel and the
same Agent becomes a Discord bot, a CLI tool, or a webhook responder
without touching pipeline code.

The deliberate narrowness matters. An earlier draft considered putting
``fetch_history``, ``fetch_user_posts``, ``post_comment`` on Channel —
but those are App-backend concepts that have no meaning for a Discord
bot or a CLI. Keeping Channel at exactly one method keeps the seam
honest: it's the output sink, nothing more. Input arrives via the
deployment's own threads calling ``agent.submit(stimulus)``. Enrichment
is deployment-specific (override ``_enrich`` on the subclass). Social
actions live in tools — which are themselves deployment-specific.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .stimulus import Stimulus


@runtime_checkable
class Channel(Protocol):
    """Narrow output contract — exactly what ``Agent`` needs to deliver a reply.

    Implementations today: ``AppChannel`` (Oasyce App backend, used by
    Samantha). Implementations the architecture allows without modifying
    ``Agent``:

      - ``StdoutChannel``: prints responses to the terminal (CLI agents)
      - ``DiscordChannel``: posts responses to a Discord channel
      - ``WebhookChannel``: writes responses into an HTTP response body
      - ``InMemoryChannel``: captures responses in a list for tests

    Required semantics:

    - ``deliver`` MUST be idempotent-friendly: the Agent may call it with
      an empty response (rare, but possible when a plan intent decides
      mid-pipeline that nothing should be said). Implementations should
      treat empty responses as a no-op.

    - ``deliver`` MUST NOT raise on network errors. Delivery failures are
      logged by the implementation and swallowed — the pipeline continues
      to the reflect phase so Thronglets still records the turn. Raising
      here would leak transport concerns into the Agent body and break
      the ``ChainSigner``/``Channel`` symmetry.

    - ``deliver`` MAY be called from any thread. Agent dispatches stimuli
      through a bounded ``ThreadPoolExecutor``, so implementations that
      rely on thread-local state (e.g. asyncio loops) must handle the
      hand-off themselves.
    """

    def deliver(self, stimulus: Stimulus, response: str) -> None:
        """Emit ``response`` into the world for this ``stimulus``.

        Called once per completed pipeline run, after evaluate and before
        reflect. See the class docstring for the invariants implementations
        must honour.
        """
        ...
