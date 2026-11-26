"""Deterministic transfer scheduling within one time step.

Policy (identical for all algorithms):

1. Candidate transfers are generated from the step's contact list using the
   replica state *at the start of the step* (``available <= t``), so a message
   received in step t can only be forwarded from step t+1. There is no
   multi-hop propagation inside one step.
2. Candidates are processed in order of (priority, key): destination
   deliveries (priority 0) before intermediate replications (priority 1).
3. Within a priority class the order is a pseudo-random key from a
   counter-based hash of (t, message, sender, receiver) seeded by the
   scheduling stream. The key of a given candidate does not depend on the
   algorithm or on node-ID magnitude, so tie-breaks are reproducible, fair
   and common across algorithms.
4. Each node may take part in at most ``capacity`` completed (or link-failed)
   transfers per second, counted for sender and receiver alike.
"""

from __future__ import annotations

import numpy as np

from .rng import hash_keys

PRIORITY_DELIVERY = 0
PRIORITY_REPLICATION = 1


def schedule_order(base_key: np.uint64, t: int, messages: np.ndarray, senders: np.ndarray,
                   receivers: np.ndarray, priority: np.ndarray) -> np.ndarray:
    """Return the processing order (indices into the candidate arrays)."""
    if messages.size == 0:
        return np.empty(0, dtype=np.int64)
    keys = hash_keys(base_key, np.full(messages.shape, t), messages, senders, receivers)
    return np.lexsort((keys, priority))


def uniform_draws(base_key: np.uint64, t: int, messages: np.ndarray, senders: np.ndarray,
                  receivers: np.ndarray) -> np.ndarray:
    """Counter-based U(0,1) draws (used for optional link failures)."""
    keys = hash_keys(base_key, np.full(messages.shape, t), messages, senders, receivers)
    return (keys >> np.uint64(11)).astype(np.float64) / float(1 << 53)
