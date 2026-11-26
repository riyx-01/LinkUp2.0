"""Deterministic message workloads, generated before any routing algorithm runs.

Generation times
    A network-wide Poisson process (exponential gaps, mean
    ``mean_interarrival_s``) starting at ``generation_start_s``; arrivals at or
    after ``generation_end_s`` are discarded. Times are floored to the 1 s grid.
    The times depend only on (seed, N) - both workloads share them.

Primary workload ("separated_friends")
    At each creation second, the eligible pairs are all *ordered* pairs (s, d)
    of distinct members of the same stable friend group where at least one of
    the two is currently separated from the group (SEPARATED or REJOINING at that
    second). One pair is drawn uniformly. Only the *current* separation state is
    used - never future mobility or delivery. Fallbacks, logged per message:
    level 1 - any ordered pair of distinct same-group members;
    level 2 - any ordered pair of distinct nodes.

Generalisation workload ("random")
    Uniformly random ordered pair of distinct nodes, no friendship requirement.
"""

from __future__ import annotations

import numpy as np

from .message import MessageTable
from .mobility import MobilityTrace
from .node import SeparationState
from .rng import WORKLOAD_CODES, stream


def generation_times(traffic: dict, seed: int, node_count: int) -> np.ndarray:
    rng = stream(seed, "message_generation", node_count)
    start, end = float(traffic["generation_start_s"]), float(traffic["generation_end_s"])
    times: list[int] = []
    t = start
    while True:
        t += rng.exponential(float(traffic["mean_interarrival_s"]))
        if t >= end:
            break
        times.append(int(np.floor(t)))
    return np.asarray(times, dtype=np.int64)


def _ordered_pairs(members: np.ndarray) -> list[tuple[int, int]]:
    return [(int(a), int(b)) for a in members for b in members if a != b]


def generate_workload(cfg: dict, mobility: MobilityTrace, seed: int) -> MessageTable:
    traffic = cfg["traffic"]
    N = mobility.node_count
    workload_type = traffic["workload_type"]
    times = generation_times(traffic, seed, N)
    rng = stream(seed, "pair_selection", N, WORKLOAD_CODES[workload_type])
    groups = mobility.groups
    all_group_pairs = [p for members in groups.members for p in _ordered_pairs(members)]

    sources, dests, rels, dists = [], [], [], []
    for t in times:
        if workload_type == "random":
            s, d = (int(x) for x in rng.choice(N, size=2, replace=False))
            rel = "random_same_group" if groups.are_friends(np.array([s]), np.array([d]))[0] \
                else "random_different_group"
        else:
            sep_now = mobility.sep_state[t] != SeparationState.WITH_GROUP
            eligible: list[tuple[int, int]] = []
            for members in groups.members:
                if sep_now[members].any():
                    eligible.extend((a, b) for a, b in _ordered_pairs(members)
                                    if sep_now[a] or sep_now[b])
            if eligible:
                s, d = eligible[int(rng.integers(len(eligible)))]
                rel = "separated_friends"
            elif all_group_pairs:
                s, d = all_group_pairs[int(rng.integers(len(all_group_pairs)))]
                rel = "same_group_fallback"
            else:
                s, d = (int(x) for x in rng.choice(N, size=2, replace=False))
                rel = "random_fallback"
        sources.append(s)
        dests.append(d)
        rels.append(rel)
        dists.append(float(np.hypot(*(mobility.positions[t, s].astype(float)
                                      - mobility.positions[t, d].astype(float)))))

    created = times
    return MessageTable(
        source=np.asarray(sources, dtype=np.int64),
        destination=np.asarray(dests, dtype=np.int64),
        created=created,
        expiry=created + int(traffic["message_lifetime_s"]),
        relationship=np.asarray(rels, dtype=object),
        payload_bytes=int(traffic["payload_bytes"]),
        initial_distance=np.asarray(dists, dtype=float),
    )
