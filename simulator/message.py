"""Global message records (one row per generated unicast message).

Global records are kept separate from per-carrier replica records (see
:mod:`simulator.buffers`). The routing engine writes delivery outcomes here for
*evaluation only*; routing algorithms never receive this table's delivery
fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

RELATIONSHIPS = (
    "separated_friends",      # primary workload, eligible separated pair
    "same_group_fallback",    # primary workload, fallback level 1
    "random_fallback",        # primary workload, fallback level 2
    "random_same_group",      # generalisation workload, pair happens to be friends
    "random_different_group", # generalisation workload
)


@dataclass
class MessageTable:
    """Workload: messages ordered by creation time (ties by draw order)."""

    source: np.ndarray        # (M,) int
    destination: np.ndarray   # (M,) int
    created: np.ndarray       # (M,) int, creation second
    expiry: np.ndarray        # (M,) int, created + lifetime
    relationship: np.ndarray  # (M,) object (str) - see RELATIONSHIPS
    payload_bytes: int
    initial_distance: np.ndarray = field(default_factory=lambda: np.empty(0))  # (M,) metres
    # Evaluation-only diagnostics (computed from the full contact trace; never passed to algorithms):
    in_range_at_creation: np.ndarray | None = None     # (M,) bool: source-destination contact at creation
    first_direct_contact: np.ndarray | None = None     # (M,) int: first source-destination contact second or -1

    @property
    def count(self) -> int:
        return int(self.source.shape[0])

    @property
    def ids(self) -> np.ndarray:
        return np.arange(self.count)

    def to_records(self) -> list[dict]:
        return [
            {"message_id": int(i), "source_id": int(self.source[i]),
             "destination_id": int(self.destination[i]), "creation_time_s": int(self.created[i]),
             "expiry_time_s": int(self.expiry[i]), "relationship": str(self.relationship[i])}
            for i in range(self.count)
        ]
