"""AppChannel — Samantha's output sink, wired to the Oasyce App backend.

Implements the narrow ``agent.channel.Channel`` Protocol by delegating
to ``AppClient.send_message``. This is the symmetric twin of
``AppClient``-as-tool-transport in ``samantha.tools``: the *input side*
of App integration lives in ``ws_client.py`` (WebSocket listener that
enqueues Stimuli), and the *output side* for chat replies lives here.

Why only chat:

Samantha handles four stimulus kinds — ``chat``, ``comment``,
``mention``, and ``feed_post``. Only ``chat`` has a direct reply;
the other three express their response through *tool calls*
(comment_on_post, reply_to_comment, like_post) executed during the
generator phase. Those tool calls use ``AppClient`` directly via the
tool handlers. They never reach the Channel.

That asymmetry is deliberate. The Channel Protocol is "where replies
go" — and for a post comment, the "reply" *is* the tool invocation,
not a separate delivery step. Trying to force both through one seam
would couple Channel to tool-call semantics and break the narrow
contract.

If a future stimulus kind has a direct reply, add a case here. Don't
widen the Channel Protocol.
"""

from __future__ import annotations

import logging

from ..agent.stimulus import Stimulus
from .app_client import AppClient

logger = logging.getLogger(__name__)


class AppChannel:
    """Deliver Samantha chat replies via the Oasyce App backend.

    Satisfies ``oasyce_sdk.agent.channel.Channel`` structurally:
    exactly one public method, ``deliver(stimulus, response)``.

    Invariants (from the Channel Protocol):

      - Empty responses are a no-op (pipeline may decide mid-flight
        that nothing should be said).
      - Network failures are logged and swallowed, never raised.
        Reflect still runs on the caller's thread so Thronglets
        records the turn even when delivery fails.
      - May be called from any thread. ``AppClient`` is a thin wrapper
        over ``requests.Session`` which is thread-safe for the operations
        Samantha uses.
    """

    def __init__(self, app: AppClient) -> None:
        self.app = app

    def deliver(self, stimulus: Stimulus, response: str) -> None:
        """Send ``response`` back to the user via AppClient.

        Only ``chat`` stimuli with non-empty responses are delivered.
        ``comment`` / ``mention`` / ``feed_post`` stimuli are handled
        by tool calls within the generator phase — see class docstring.
        """
        if stimulus.kind != "chat":
            return
        if not response:
            return
        try:
            self.app.send_message(stimulus.session_id, response)
            logger.info(
                "AppChannel delivered: session=%s len=%d",
                stimulus.session_id, len(response),
            )
        except Exception:
            # Channel Protocol invariant: never raise on network errors.
            logger.error("AppChannel delivery failed", exc_info=True)
