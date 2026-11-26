"""Factory that turns a resolved config into a bound routing algorithm.

The factory works from the *effective* routing config (see
``simulator.config.effective_routing``), so an MWS config with every rule
disabled builds plain BSW - the ablation baseline is the real BSW code path.
The immediate and historical MWS variants differ **only** in the motion oracle
they receive; every other input is identical.
"""

from __future__ import annotations

from simulator.config import effective_routing
from simulator.motion import MotionOracle
from simulator.scenario import Scenario

from .base import AlgorithmContext, RoutingAlgorithm
from .binary_spray_wait import BinarySprayAndWait
from .direct_delivery import DirectDelivery
from .epidemic import Epidemic
from .mws import MotionAwareSprayAndWait


def build_motion_oracle(cfg: dict, scenario: Scenario) -> MotionOracle:
    mws = cfg["routing"]["mws"]
    motion = cfg["motion_classification"]
    signal = scenario.motion_signal(mws["motion_signal"], motion["error_rate"], motion["error_model"],
                                    motion["mean_burst_s"], mws["history_window_s"],
                                    mws["history_threshold"])
    desc = f"{mws['motion_signal']} (error {motion['error_rate']:.0%}, {motion['error_model']})"
    return MotionOracle(signal, desc)


def build_algorithm(cfg: dict, scenario: Scenario) -> RoutingAlgorithm:
    eff = effective_routing(cfg)
    name = eff["algorithm"]
    motion = None
    if name == "DirectDelivery":
        algo: RoutingAlgorithm = DirectDelivery()
    elif name == "Epidemic":
        algo = Epidemic()
    elif name == "BSW":
        algo = BinarySprayAndWait(eff["copy_budget"])
    elif name == "MWS":
        rules = eff["mws"]
        algo = MotionAwareSprayAndWait(
            eff["copy_budget"],
            friend_exclusion=rules["R1_friend_exclusion"],
            walker_preference=rules["R2_walker_preference"],
            patience_fallback=rules["R3_patience_fallback"],
            fallback_s=rules.get("fallback_s", cfg["routing"]["mws"]["fallback_s"]),
            motion_signal=rules.get("motion_signal", "none"),
        )
        if rules["R2_walker_preference"]:
            motion = build_motion_oracle(cfg, scenario)
    else:  # pragma: no cover - guarded by config validation
        raise ValueError(f"Unknown algorithm {name}")
    algo.bind(AlgorithmContext(friend_group=scenario.mobility.groups.group_of,
                               created=scenario.messages.created, motion=motion))
    return algo
