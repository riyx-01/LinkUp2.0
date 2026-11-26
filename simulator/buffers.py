"""Per-carrier replica records and the common buffer policy.

Replica state is kept separately from the global message records. Arrays are
indexed ``[message, node]``:

``holds``       node currently stores a replica (occupies one buffer slot)
``knows``       node holds or has ever received/created the message
                (duplicate-suppression memory, kept until the message expires)
``tokens``      replication tokens held with the replica (copy budget, not copies)
``available``   earliest step at which the replica may be forwarded
                (creation step for the source; receive step + 1 otherwise)
``stored_at``   step at which the replica entered this buffer
``hops``        transfers between the source and this replica

Buffer policy ``drop_oldest_created`` (identical for every algorithm): when a
replica must be stored in a full buffer, the incoming replica and the stored
replicas are ranked by (message creation time, time stored, message id); the
oldest is dropped. If the oldest is the *incoming* replica, the transfer is
rejected atomically: the sender keeps its replica and tokens and no capacity
is consumed. A dropped replica's tokens are lost (never recreated); the node
still remembers the message ID, so it is never re-replicated to that node.
"""

from __future__ import annotations

import numpy as np


class ReplicaStore:
    def __init__(self, message_count: int, node_count: int, capacity: int):
        shape = (message_count, node_count)
        self.holds = np.zeros(shape, dtype=bool)
        self.knows = np.zeros(shape, dtype=bool)
        self.tokens = np.zeros(shape, dtype=np.int64)
        self.available = np.full(shape, np.iinfo(np.int64).max, dtype=np.int64)
        self.stored_at = np.full(shape, -1, dtype=np.int64)
        self.hops = np.zeros(shape, dtype=np.int64)
        self.occupancy = np.zeros(node_count, dtype=np.int64)
        self.capacity = int(capacity)

    def is_full(self, node: int) -> bool:
        return self.occupancy[node] >= self.capacity

    def eviction_victim(self, node: int, incoming: int, created: np.ndarray, now: int) -> int:
        """Replica to drop so ``incoming`` fits, or -1 if ``incoming`` is the oldest."""
        stored = np.flatnonzero(self.holds[:, node])
        if stored.size == 0:
            return -1
        order = np.lexsort((stored, self.stored_at[stored, node], created[stored]))
        victim = int(stored[order[0]])
        if (created[incoming], now, incoming) < (created[victim], self.stored_at[victim, node], victim):
            return -1
        return victim

    def store(self, m: int, node: int, tokens: int, available: int, now: int, hops: int) -> None:
        self.holds[m, node] = True
        self.knows[m, node] = True
        self.tokens[m, node] = tokens
        self.available[m, node] = available
        self.stored_at[m, node] = now
        self.hops[m, node] = hops
        self.occupancy[node] += 1

    def remove(self, m: int, node: int) -> int:
        """Remove a replica (drop/expiry); returns the tokens it carried."""
        tokens = int(self.tokens[m, node])
        self.holds[m, node] = False
        self.tokens[m, node] = 0
        self.available[m, node] = np.iinfo(np.int64).max
        self.occupancy[node] -= 1
        return tokens

    def purge_message(self, m: int) -> tuple[int, int]:
        """Expire every replica of message ``m``; returns (replicas, tokens) removed."""
        holders = np.flatnonzero(self.holds[m])
        tokens = int(self.tokens[m, holders].sum())
        self.holds[m, holders] = False
        self.tokens[m, holders] = 0
        self.available[m, holders] = np.iinfo(np.int64).max
        self.occupancy[holders] -= 1
        # Duplicate-suppression memory can be released after expiry.
        self.knows[m, :] = False
        return int(holders.size), tokens
