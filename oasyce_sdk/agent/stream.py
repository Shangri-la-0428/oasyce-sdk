"""Stream — the symmetric input counterpart to Channel.

Channel delivers output to the world; Stream brings the world in.
A Stream is anything that can be polled for stimuli at a declared
interval, carrying a default cognitive mode so the Loop knows how
to process what it yields.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .cognitive import CognitiveMode
from .stimulus import Stimulus


@runtime_checkable
class Stream(Protocol):
    """Structural contract for stimulus sources.

    Implementations are not required to inherit — any object with
    these three members satisfies the protocol at runtime.
    """

    def poll(self) -> list[Stimulus]:
        ...

    @property
    def interval(self) -> int:
        ...

    @property
    def default_mode(self) -> CognitiveMode:
        ...
