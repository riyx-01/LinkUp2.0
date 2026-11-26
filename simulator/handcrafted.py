"""Small hand-specified scenarios for deterministic tests and demonstrations.

A handcrafted scenario fixes the contact list per second, the walking states,
friend groups and the message workload explicitly, bypassing the mobility
model. It goes through exactly the same routing engine as generated scenarios.
"""

from __future__ import annotations

import copy

import numpy as np

from .config import load_config, set_dotted
from .contacts import ContactTrace
from .groups import GroupAssignment
from .message import MessageTable
from .mobility import MobilityTrace
from .scenario import Scenario, attach_message_diagnostics


def small_config(duration: int = 60, lifetime: int = 30, generation_end: int = 20,
                 **overrides) -> dict:
    """Default config shrunk for handcrafted tests (no warm-up)."""
    cfg = copy.deepcopy(load_config("default.json"))
    cfg["simulation"].update({"duration_s": duration, "warmup_s": 0})
    cfg["traffic"].update({"generation_start_s": 0, "generation_end_s": generation_end,
                           "message_lifetime_s": lifetime})
    for key, value in overrides.items():
        set_dotted(cfg, key.replace("__", "."), value)
    return cfg


def handcrafted_scenario(cfg: dict, node_count: int, contacts: dict[int, list[tuple[int, int]]],
                         messages: list[tuple[int, int, int]], walking: np.ndarray | None = None,
                         groups: list[list[int]] | None = None, seed: int = 0) -> Scenario:
    """Build a scenario from explicit contacts ``{t: [(a, b), ...]}``.

    ``messages`` is a list of ``(source, destination, created_s)``. ``walking``
    is a (T, N) bool matrix (default: everybody stationary).
    """
    T = int(cfg["simulation"]["duration_s"])
    start = int(cfg["simulation"]["warmup_s"])
    chunks, offsets = [], [0]
    for t in range(start, T):
        pairs = sorted({(min(a, b), max(a, b)) for a, b in contacts.get(t, [])})
        arr = np.array(pairs, dtype=np.int32).reshape(-1, 2)
        chunks.append(arr)
        offsets.append(offsets[-1] + len(arr))
    trace = ContactTrace(start, np.array(offsets, dtype=np.int64),
                         np.concatenate(chunks) if chunks else np.empty((0, 2), np.int32))

    group_of = np.full(node_count, -1, dtype=np.int32)
    members = []
    for gid, g in enumerate(groups or []):
        group_of[list(g)] = gid
        members.append(np.array(sorted(g)))
    ga = GroupAssignment(group_of, members, np.zeros((node_count, 2)), np.ones(node_count))
    if walking is None:
        walking = np.zeros((T, node_count), dtype=bool)
    mob = MobilityTrace(positions=np.zeros((T, node_count, 2), dtype=np.float32), walking=walking,
                        zone=np.full((T, node_count), -1, dtype=np.int8),
                        sep_state=np.zeros((T, node_count), dtype=np.int8), groups=ga)
    lifetime = int(cfg["traffic"]["message_lifetime_s"])
    src = np.array([m[0] for m in messages], dtype=np.int64)
    dst = np.array([m[1] for m in messages], dtype=np.int64)
    created = np.array([m[2] for m in messages], dtype=np.int64)
    table = MessageTable(src, dst, created, created + lifetime,
                         np.array(["handcrafted"] * len(messages), dtype=object),
                         int(cfg["traffic"]["payload_bytes"]), np.zeros(len(messages)))
    scen = Scenario(seed=seed, node_count=node_count, cfg={"handcrafted": True}, scenario_id="handcrafted",
                    mobility=mob, contacts=trace, messages=table, validation={}, scenario_hash="")
    scen.scenario_hash = scen.compute_hash()
    attach_message_diagnostics(scen)
    return scen
