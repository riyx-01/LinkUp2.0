"""Expansion of ``configs/experiments.json`` into arms, unique configurations and runs.

Each arm = phase config + experiment ``base`` overrides + arm overrides. Arms
whose *effective* configuration is identical share a ``configuration_id``
(see :func:`simulator.config.configuration_id`) and are executed once; the
experiment membership of each configuration is recorded so analyses can reuse
it (e.g. Full MWS at 100 nodes appears in E1, E2, E3, E4 and E5).
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path

from simulator.config import (CONFIG_DIR, apply_overrides, configuration_id, effective_routing,
                              validate_config, variant_label)

SEED_RANGES = {
    "development": range(1, 10),
    "pilot": range(101, 106),
    "confirmatory": range(1001, 1031),
}

_SHORT = {
    "nodes.node_count": "N", "routing.algorithm": "", "routing.copy_budget": "L",
    "traffic.workload_type": "workload", "communication.radius_m": "r",
    "motion_classification.error_rate": "err",
}


def load_experiments(path: Path | None = None) -> dict:
    with open(path or CONFIG_DIR / "experiments.json", "r", encoding="utf-8") as fh:
        return json.load(fh)["experiments"]


def _grid_label(assign: dict) -> str:
    parts = []
    for key, value in assign.items():
        short = _SHORT.get(key, key.split(".")[-1])
        parts.append(str(value) if short == "" else f"{short}={value}")
    return " | ".join(parts)


@dataclass
class Arm:
    experiment_id: str
    label: str
    overrides: dict
    cfg: dict
    configuration_id: str

    @property
    def algorithm(self) -> str:
        return effective_routing(self.cfg)["algorithm"]

    @property
    def variant(self) -> str:
        return variant_label(self.cfg)


@dataclass
class Matrix:
    arms: list[Arm]
    configs: dict[str, dict] = field(default_factory=dict)          # configuration_id -> cfg
    memberships: dict[str, list[tuple[str, str]]] = field(default_factory=dict)

    @property
    def unique_count(self) -> int:
        return len(self.configs)

    def new_configs_per_experiment(self) -> dict[str, int]:
        seen: set[str] = set()
        out: dict[str, int] = {}
        for arm in self.arms:
            out.setdefault(arm.experiment_id, 0)
            if arm.configuration_id not in seen:
                seen.add(arm.configuration_id)
                out[arm.experiment_id] += 1
        return out

    def experiment_ids_for(self, config_id: str) -> list[str]:
        return sorted({e for e, _ in self.memberships.get(config_id, [])},
                      key=lambda e: (e[0] != "E", e))

    def rows(self) -> list[dict]:
        """Experiment-arm table (one row per arm) for export."""
        first: dict[str, str] = {}
        rows = []
        for arm in self.arms:
            reused = arm.configuration_id in first
            first.setdefault(arm.configuration_id, arm.experiment_id)
            cfg = arm.cfg
            rows.append({
                "experiment_id": arm.experiment_id, "arm_label": arm.label,
                "configuration_id": arm.configuration_id, "algorithm": arm.algorithm,
                "variant": arm.variant, "node_count": cfg["nodes"]["node_count"],
                "copy_budget": cfg["routing"]["copy_budget"] if arm.algorithm in ("BSW", "MWS") else None,
                "communication_radius_m": cfg["communication"]["radius_m"],
                "motion_error_rate": cfg["motion_classification"]["error_rate"],
                "workload_type": cfg["traffic"]["workload_type"],
                "reused_from": first[arm.configuration_id] if reused else "",
            })
        return rows


def expand_experiment(exp_id: str, spec: dict, phase_cfg: dict) -> list[Arm]:
    base = dict(spec.get("base", {}))
    arms: list[tuple[str, dict]] = []
    if "grid" in spec:
        keys = list(spec["grid"])
        for values in itertools.product(*(spec["grid"][k] for k in keys)):
            assign = dict(zip(keys, values))
            arms.append((_grid_label(assign), assign))
    for arm in spec.get("arms", []):
        arm = dict(arm)
        label = arm.pop("label")
        arms.append((label, arm))
    out = []
    for label, overrides in arms:
        merged = {**base, **overrides}
        cfg = apply_overrides(phase_cfg, merged)
        validate_config(cfg)
        out.append(Arm(exp_id, label, merged, cfg, configuration_id(cfg)))
    return out


def build_matrix(phase_cfg: dict, experiment_ids: list[str] | None = None,
                 include_optional: bool = False, experiments: dict | None = None) -> Matrix:
    experiments = experiments or load_experiments()
    if experiment_ids is None:
        experiment_ids = [e for e, s in experiments.items() if include_optional or not s.get("optional")]
    unknown = set(experiment_ids) - set(experiments)
    if unknown:
        raise KeyError(f"Unknown experiment(s): {sorted(unknown)}")
    arms: list[Arm] = []
    for exp_id in experiment_ids:
        arms.extend(expand_experiment(exp_id, experiments[exp_id], phase_cfg))
    matrix = Matrix(arms)
    for arm in arms:
        matrix.configs.setdefault(arm.configuration_id, arm.cfg)
        matrix.memberships.setdefault(arm.configuration_id, []).append((arm.experiment_id, arm.label))
    return matrix


def check_phase_seeds(phase: str, seeds: list[int]) -> None:
    """Refuse seeds outside the phase's reserved range (keeps phases separate)."""
    allowed = SEED_RANGES.get(phase)
    if allowed is None:
        raise ValueError(f"Unknown phase '{phase}'")
    bad = [s for s in seeds if s not in allowed]
    if bad:
        raise ValueError(f"Seeds {bad} are not reserved for phase '{phase}' "
                         f"(allowed {allowed.start}-{allowed.stop - 1}).")
