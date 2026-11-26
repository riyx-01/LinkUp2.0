"""Contact detection and the compact per-step contact trace.

Two nodes are in contact at time t when their Euclidean distance is <= the
communication radius (boundary inclusive). Pairs are found with SciPy's
``cKDTree.query_pairs`` - no nested Python loops over all node pairs.

The trace stores, for each routing step, the sorted list of unordered pairs
``(a, b)`` with ``a < b`` in one concatenated integer array plus offsets, which
keeps memory small and makes hashing/caching straightforward.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree


def pairs_within(positions: np.ndarray, radius: float) -> np.ndarray:
    """Sorted unordered pairs (a < b) with distance <= radius."""
    if positions.shape[0] < 2:
        return np.empty((0, 2), dtype=np.int32)
    tree = cKDTree(positions)
    pairs = tree.query_pairs(r=radius, p=2.0, output_type="ndarray")
    if pairs.size == 0:
        return np.empty((0, 2), dtype=np.int32)
    pairs = np.sort(pairs.astype(np.int32), axis=1)
    order = np.lexsort((pairs[:, 1], pairs[:, 0]))
    return pairs[order]


@dataclass
class ContactTrace:
    """Contacts for steps ``start .. start + len(offsets) - 2``."""

    start: int
    offsets: np.ndarray   # (steps + 1,) int64
    pairs: np.ndarray     # (K, 2) int32, a < b, sorted within each step

    @property
    def steps(self) -> int:
        return len(self.offsets) - 1

    @property
    def end(self) -> int:
        return self.start + self.steps

    def at(self, t: int) -> np.ndarray:
        """Pairs in contact at time ``t`` (empty array outside the trace)."""
        i = t - self.start
        if i < 0 or i >= self.steps:
            return np.empty((0, 2), dtype=np.int32)
        return self.pairs[self.offsets[i]:self.offsets[i + 1]]

    def counts(self) -> np.ndarray:
        return np.diff(self.offsets)


def compute_contact_trace(positions: np.ndarray, radius: float, start: int, end: int) -> ContactTrace:
    """Compute contacts for ``start <= t < end`` from a (T, N, 2) position array."""
    chunks: list[np.ndarray] = []
    offsets = [0]
    for t in range(start, end):
        pairs = pairs_within(positions[t].astype(np.float64), radius)
        chunks.append(pairs)
        offsets.append(offsets[-1] + len(pairs))
    data = np.concatenate(chunks) if chunks else np.empty((0, 2), dtype=np.int32)
    return ContactTrace(start, np.asarray(offsets, dtype=np.int64), data.astype(np.int32))


def contact_events(trace: ContactTrace, node_count: int) -> list[tuple[int, int, int, int]]:
    """Maximal contact intervals as ``(a, b, start_t, end_t_exclusive)``.

    Contacts still active at the end of the trace are closed at ``trace.end``
    (right-censored); callers can identify them via ``end == trace.end``.
    """
    events: list[tuple[int, int, int, int]] = []
    active: dict[int, int] = {}
    prev = np.empty(0, dtype=np.int64)
    for i in range(trace.steps):
        t = trace.start + i
        p = trace.at(t)
        codes = p[:, 0].astype(np.int64) * node_count + p[:, 1]
        new = np.setdiff1d(codes, prev, assume_unique=True)
        ended = np.setdiff1d(prev, codes, assume_unique=True)
        for c in ended.tolist():
            s = active.pop(c)
            events.append((c // node_count, c % node_count, s, t))
        for c in new.tolist():
            active[c] = t
        prev = codes
    for c, s in active.items():
        events.append((c // node_count, c % node_count, s, trace.end))
    events.sort(key=lambda e: (e[2], e[0], e[1]))
    return events
