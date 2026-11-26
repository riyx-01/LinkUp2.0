"""Epidemic Routing (after Vahdat & Becker, 2000).

On contact, nodes exchange every message the peer has not yet received. There
is no token budget; duplicate suppression (summary-vector equivalent), the
50-message buffer, the per-node transfer capacity and message lifetime still
apply, so 100 % delivery is *not* assumed.
"""

from __future__ import annotations

import numpy as np

from .base import Reason, RoutingAlgorithm


class Epidemic(RoutingAlgorithm):
    name = "Epidemic"
    uses_tokens = False

    def replication_decision(self, t, messages, senders, receivers, sender_tokens):
        allowed = np.ones(messages.shape, dtype=bool)
        reason = np.full(messages.shape, Reason.EPIDEMIC, dtype=np.int64)
        return allowed, reason
