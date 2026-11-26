"""Direct Delivery: the source holds the message until it meets the destination.

No relaying. Destination delivery itself is handled by the engine (common to
all algorithms), so this algorithm simply refuses every intermediate transfer.
It provides a minimal-transfer reference point.
"""

from __future__ import annotations

import numpy as np

from .base import Reason, RoutingAlgorithm


class DirectDelivery(RoutingAlgorithm):
    name = "DirectDelivery"
    uses_tokens = False

    def replication_decision(self, t, messages, senders, receivers, sender_tokens):
        allowed = np.zeros(messages.shape, dtype=bool)
        reason = np.full(messages.shape, Reason.BLOCK_NO_RELAY, dtype=np.int64)
        return allowed, reason
