"""Non-UI helpers for the dashboard: run a genuine simulation and reconstruct states.

Everything shown by the dashboard is derived from the simulator's own scenario
(positions, walking states, groups) and the engine's event log (transfers,
drops, expiries). Nothing is animated independently of the simulation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from simulator.config import apply_overrides, load_config, validate_config, variant_label
from simulator.engine import RoutingEngine, RunOutput
from simulator.scenario import Scenario, build_scenario


@dataclass
class ReplayRun:
    cfg: dict
    scenario: Scenario
    output: RunOutput
    label: str


def run_for_dashboard(algorithm: str, nodes: int, copy_budget: int, radius: float, seed: int,
                      workload: str = "separated_friends", motion_signal: str = "immediate",
                      error_rate: float = 0.0) -> ReplayRun:
    cfg = apply_overrides(load_config("default.json"), {
        "nodes.node_count": int(nodes), "routing.algorithm": algorithm, "routing.copy_budget": int(copy_budget),
        "communication.radius_m": float(radius), "traffic.workload_type": workload,
        "routing.mws.motion_signal": motion_signal, "motion_classification.error_rate": float(error_rate),
        "output.save_positions": True})
    validate_config(cfg)
    scen = build_scenario(cfg, int(seed))
    out = RoutingEngine(cfg, scen, event_log=True).run()
    return ReplayRun(cfg, scen, out, variant_label(cfg))


def holders_at(run: ReplayRun, message: int, t: int) -> set[int]:
    """Nodes storing a replica of ``message`` at the end of step ``t`` (from the event log)."""
    msgs = run.scenario.messages
    created, expiry = int(msgs.created[message]), int(msgs.expiry[message])
    if t < created or t >= expiry:
        return set()
    holders = {int(msgs.source[message])}
    keep = run.cfg["routing"]["carrier_keeps_replica_after_delivery"]
    for ev in run.output.events:
        ts, kind, snd, rcv, m = ev[0], ev[1], ev[2], ev[3], ev[4]
        if ts > t:
            break
        if m != message:
            continue
        if kind == "transfer" and ev[5] == "intermediate":
            holders.add(rcv)
        elif kind == "transfer" and ev[5] == "destination" and not keep:
            holders.discard(snd)
        elif kind == "drop":
            holders.discard(snd)
    return holders


def transfers_at(run: ReplayRun, t: int, message: int | None = None) -> list[tuple]:
    return [e for e in run.output.events if e[0] == t and e[1] == "transfer"
            and (message is None or e[4] == message)]


def delivered_by(run: ReplayRun, t: int) -> int:
    tl = run.output.timeline
    if not tl["t"] or t < tl["t"][0]:
        return 0
    idx = min(t - tl["t"][0], len(tl["t"]) - 1)
    return int(tl["delivered"][idx])


def replicas_at(run: ReplayRun, t: int) -> int:
    tl = run.output.timeline
    if not tl["t"] or t < tl["t"][0]:
        return 0
    return int(tl["replicas"][min(t - tl["t"][0], len(tl["t"]) - 1)])


def neighbours(run: ReplayRun, node: int, t: int) -> np.ndarray:
    pairs = run.scenario.contacts.at(t)
    if pairs.size == 0:
        return np.empty(0, dtype=int)
    mask = (pairs[:, 0] == node) | (pairs[:, 1] == node)
    p = pairs[mask]
    return np.where(p[:, 0] == node, p[:, 1], p[:, 0])
