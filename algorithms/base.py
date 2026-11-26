"""Common interface for routing algorithms.

The engine (not the algorithm) performs the steps shared by every algorithm,
in this order, for each (carrier, message, peer) opportunity:

1. message validity / expiry;
2. **destination delivery** - always allowed regardless of tokens or rules;
3. **duplicate suppression** - never replicate to a peer that knows the message;
4. the algorithm's :meth:`replication_decision` (token, friend, motion rules);
5. buffer acceptance and per-node transfer capacity;
6. on success, :meth:`split_tokens` divides the copy budget.

Algorithms receive only information a real device could have *now*: the
carrier's tokens, message creation time/destination, stable friend-group
membership and the advertised motion state at the current second (via a
:class:`~simulator.motion.MotionOracle`). They never see global delivery
records, future movement or future encounters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import IntEnum

import numpy as np

from simulator.motion import MotionOracle


class Reason(IntEnum):
    """Decision labels recorded for every replication opportunity/transfer."""

    DELIVERY = 0            # direct delivery to the destination
    EPIDEMIC = 1            # epidemic exchange
    BSW_SPRAY = 2           # binary spray (no MWS rule restricting it)
    MWS_WALKER = 3          # R2: peer advertised as walking
    MWS_FALLBACK = 4        # R3: stationary non-friend after fallback age
    MWS_NO_MOTION_RULE = 5  # MWS variant without R2: non-friend peer accepted
    BLOCK_ONE_TOKEN = 10    # carrier holds a single token -> wait phase
    BLOCK_FRIEND = 11       # R1: peer is in the carrier's friend group
    BLOCK_STATIONARY = 12   # R2: peer stationary and fallback not (yet) allowed
    BLOCK_NO_RELAY = 13     # Direct Delivery never relays


@dataclass
class AlgorithmContext:
    """Information an algorithm may legitimately use."""

    friend_group: np.ndarray        # (N,) stable friend-group id or -1
    created: np.ndarray             # (M,) creation second of each message
    motion: MotionOracle | None     # advertised motion state at the current time


class RoutingAlgorithm(ABC):
    name: str = "abstract"
    uses_tokens: bool = False

    def __init__(self, copy_budget: int = 1):
        self.copy_budget = int(copy_budget)
        self.ctx: AlgorithmContext | None = None

    def bind(self, ctx: AlgorithmContext) -> None:
        self.ctx = ctx

    def initial_tokens(self) -> int:
        return self.copy_budget if self.uses_tokens else 0

    @abstractmethod
    def replication_decision(self, t: int, messages: np.ndarray, senders: np.ndarray,
                             receivers: np.ndarray, sender_tokens: np.ndarray
                             ) -> tuple[np.ndarray, np.ndarray]:
        """Vectorised decision for intermediate (non-destination) peers.

        Inputs are aligned arrays of candidate opportunities where the peer is
        *not* the destination and does *not* know the message. Returns
        ``(allowed, reason)`` arrays.
        """

    def split_tokens(self, tokens: int) -> tuple[int, int]:
        """Return (tokens given to receiver, tokens kept by carrier)."""
        return 0, tokens

    def describe(self) -> dict:
        return {"name": self.name, "uses_tokens": self.uses_tokens, "copy_budget": self.copy_budget}
