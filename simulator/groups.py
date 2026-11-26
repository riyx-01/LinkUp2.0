"""Stable friend-group assignment.

About ``group_participation`` x N nodes are placed into friend groups whose sizes
are drawn uniformly from ``[group_size_min, group_size_max]``. Group sizes are
adjusted at the end so that no single node is left over as a "group" of one
(a leftover node becomes independent instead). Membership is random with
respect to node IDs. Friendship is *stable* (never changes during a run) but
does not imply permanent co-movement: members can separate (see mobility.py).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .node import NO_GROUP


@dataclass
class GroupAssignment:
    group_of: np.ndarray          # (N,) friend-group id or NO_GROUP
    members: list[np.ndarray]     # members of each friend group
    offsets: np.ndarray           # (N, 2) personal spatial offset from the group anchor (m)
    speed_factor: np.ndarray      # (N,) multiplicative speed difference within a group

    @property
    def group_count(self) -> int:
        return len(self.members)

    @property
    def grouped_fraction(self) -> float:
        return float(np.mean(self.group_of != NO_GROUP))

    def are_friends(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        ga, gb = self.group_of[a], self.group_of[b]
        return (ga != NO_GROUP) & (ga == gb)


def draw_group_sizes(target: int, size_min: int, size_max: int,
                     rng: np.random.Generator) -> list[int]:
    """Draw group sizes summing to at most ``target`` with no remainder of one."""
    sizes: list[int] = []
    remaining = target
    while remaining >= size_min:
        size = int(min(rng.integers(size_min, size_max + 1), remaining))
        leftover = remaining - size
        if 0 < leftover < size_min:
            # Avoid an unusable leftover: absorb it if possible, else shrink.
            if size + leftover <= size_max:
                size += leftover
            elif size - (size_min - leftover) >= size_min:
                size -= size_min - leftover
        sizes.append(size)
        remaining -= size
    return sizes


def assign_groups(node_count: int, mobility_cfg: dict, rng: np.random.Generator) -> GroupAssignment:
    """Randomly assign nodes to stable friend groups (group_assignment stream)."""
    participation = mobility_cfg["group_participation"]
    size_min, size_max = mobility_cfg["group_size_min"], mobility_cfg["group_size_max"]
    target = int(round(participation * node_count))
    sizes = draw_group_sizes(target, size_min, size_max, rng)

    order = rng.permutation(node_count)
    group_of = np.full(node_count, NO_GROUP, dtype=np.int32)
    members: list[np.ndarray] = []
    cursor = 0
    for gid, size in enumerate(sizes):
        idx = np.sort(order[cursor:cursor + size])
        group_of[idx] = gid
        members.append(idx)
        cursor += size

    off_min, off_max = mobility_cfg["member_offset_m"]
    radius = rng.uniform(off_min, off_max, size=node_count)
    angle = rng.uniform(0.0, 2.0 * np.pi, size=node_count)
    offsets = np.column_stack([radius * np.cos(angle), radius * np.sin(angle)])
    offsets[group_of == NO_GROUP] = 0.0  # independent nodes walk to their own point

    variation = mobility_cfg["member_speed_variation"]
    speed_factor = rng.uniform(1.0 - variation, 1.0 + variation, size=node_count)
    speed_factor[group_of == NO_GROUP] = 1.0
    return GroupAssignment(group_of, members, offsets, speed_factor)
