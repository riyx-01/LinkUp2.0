"""Helpers shared by test modules."""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from simulator.config import apply_overrides, load_config
from simulator.engine import RoutingEngine
from simulator.handcrafted import handcrafted_scenario, small_config
from simulator.scenario import build_scenario

__all__ = ["handcrafted_scenario", "small_config", "run", "walking_matrix", "transfers", "random_scenario",
           "same_metrics"]


@lru_cache(maxsize=None)
def random_scenario(node_count: int, seed: int, workload: str = "separated_friends"):
    """(cfg, scenario) for a generated scenario (cached across tests)."""
    cfg = apply_overrides(load_config("default.json"),
                          {"nodes.node_count": node_count, "traffic.workload_type": workload})
    return cfg, build_scenario(cfg, seed)


def run(cfg, scen, event_log=True):
    return RoutingEngine(cfg, scen, event_log=event_log).run()


def walking_matrix(T: int, N: int, walkers=()) -> np.ndarray:
    w = np.zeros((T, N), dtype=bool)
    for n in walkers:
        w[:, n] = True
    return w


def transfers(out, kind=None):
    """Completed transfer events, optionally filtered by 'intermediate'/'destination'."""
    rows = [e for e in out.events if e[1] == "transfer"]
    if kind:
        rows = [e for e in rows if e[5] == kind]
    return rows


def same_metrics(a: dict, b: dict, ignore=("routing_runtime_s",)) -> bool:
    """Metric dicts equal, treating NaN == NaN (undefined metrics) and ignoring wall-clock fields."""
    if set(a) != set(b):
        return False
    for k in a:
        if k in ignore:
            continue
        x, y = a[k], b[k]
        if isinstance(x, float) and isinstance(y, float) and x != x and y != y:
            continue
        if x != y:
            return False
    return True
