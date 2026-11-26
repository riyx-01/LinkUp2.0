"""Binary Spray-and-Wait (after Spyropoulos, Psounis & Raghavendra, 2005).

The source starts with L tokens. A carrier holding c > 1 tokens that meets an
eligible node which has not received the message gives it floor(c/2) tokens
and keeps c - floor(c/2). A carrier with one token is in the *wait* phase: it
relays to no intermediate node and waits to meet the destination. Direct
delivery is always allowed regardless of tokens (handled by the engine).
"""

from __future__ import annotations

import numpy as np

from .base import Reason, RoutingAlgorithm


def binary_split(tokens: int) -> tuple[int, int]:
    give = tokens // 2
    return give, tokens - give


class BinarySprayAndWait(RoutingAlgorithm):
    name = "BSW"
    uses_tokens = True

    def replication_decision(self, t, messages, senders, receivers, sender_tokens):
        allowed = sender_tokens > 1
        reason = np.where(allowed, Reason.BSW_SPRAY, Reason.BLOCK_ONE_TOKEN).astype(np.int64)
        return allowed, reason

    def split_tokens(self, tokens: int) -> tuple[int, int]:
        return binary_split(tokens)
