"""Configuration loading, merging, validation and hashing.

All experimental parameters live in JSON files under ``configs/``. A config file
may ``"extends"`` another file; values are deep-merged (child wins). Experiment
arms apply *dotted-path overrides* such as ``{"routing.copy_budget": 16}``.

Two hashes are used:

* ``configuration_id`` - hash of the *effective* configuration, i.e. only the
  fields that can change a run's outcome, after normalising fields that an
  algorithm ignores (e.g. the copy budget for Epidemic, or the motion error rate
  for BSW). Equivalent configurations therefore share an id and are run once.
* ``full_config_hash`` - hash of the complete resolved config (provenance).
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "configs"

ALGORITHMS = ("DirectDelivery", "Epidemic", "BSW", "MWS")
TOKEN_ALGORITHMS = ("BSW", "MWS")
WORKLOAD_TYPES = ("separated_friends", "random")
MOTION_SIGNALS = ("immediate", "historical")
ERROR_MODELS = ("independent", "correlated")
DROP_POLICIES = ("drop_oldest_created",)


class ConfigError(ValueError):
    """Raised when a configuration is inconsistent or invalid."""


# --------------------------------------------------------------------------- #
# Loading and merging
# --------------------------------------------------------------------------- #
def deep_merge(base: dict, override: dict) -> dict:
    """Return a new dict where ``override`` is recursively merged into ``base``."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(path: str | Path) -> dict:
    """Load a JSON config, resolving ``extends`` chains relative to the file."""
    path = Path(path)
    if not path.is_absolute() and not path.exists():
        candidate = CONFIG_DIR / path
        if candidate.exists():
            path = candidate
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    parent = data.pop("extends", None)
    if parent:
        parent_cfg = load_config(path.parent / parent)
        data = deep_merge(parent_cfg, data)
    return data


def set_dotted(cfg: dict, dotted_key: str, value: Any) -> None:
    """Set ``cfg['a']['b']['c'] = value`` for ``dotted_key='a.b.c'``."""
    parts = dotted_key.split(".")
    node = cfg
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], dict):
            raise ConfigError(f"Unknown config section in override '{dotted_key}'")
        node = node[part]
    if parts[-1] not in node:
        raise ConfigError(f"Unknown config key in override '{dotted_key}'")
    node[parts[-1]] = copy.deepcopy(value)


def get_dotted(cfg: dict, dotted_key: str) -> Any:
    node = cfg
    for part in dotted_key.split("."):
        node = node[part]
    return node


def apply_overrides(cfg: dict, overrides: dict[str, Any]) -> dict:
    """Return a copy of ``cfg`` with dotted-path overrides applied."""
    result = copy.deepcopy(cfg)
    for key, value in overrides.items():
        set_dotted(result, key, value)
    return result


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def validate_config(cfg: dict) -> None:
    """Raise :class:`ConfigError` if the config is internally inconsistent."""
    sim = cfg["simulation"]
    traffic = cfg["traffic"]
    venue = cfg["venue"]
    mob = cfg["mobility"]
    comm = cfg["communication"]
    routing = cfg["routing"]
    motion = cfg["motion_classification"]

    if sim["time_step_s"] != 1:
        raise ConfigError("Only a 1 s time step is supported.")
    if not 0 <= sim["warmup_s"] < sim["duration_s"]:
        raise ConfigError("warmup_s must be within the simulation duration.")
    if traffic["generation_start_s"] < sim["warmup_s"]:
        raise ConfigError("Messages must not be generated during warm-up.")
    if traffic["generation_end_s"] <= traffic["generation_start_s"]:
        raise ConfigError("generation_end_s must exceed generation_start_s.")
    # Every message must have its full lifetime observed. The last possible
    # creation second is generation_end_s - 1 and it expires lifetime later; the
    # final simulated step is duration_s - 1.
    last_expiry = traffic["generation_end_s"] - 1 + traffic["message_lifetime_s"]
    if last_expiry > sim["duration_s"] - 1:
        raise ConfigError(
            "Simulation too short to observe every message's full lifetime "
            f"(last expiry {last_expiry} s > final step {sim['duration_s'] - 1} s)."
        )
    if cfg["nodes"]["node_count"] < 2:
        raise ConfigError("At least two nodes are required.")

    width, height = venue["width_m"], venue["height_m"]
    for name, zone in venue["zones"].items():
        x0, x1 = zone["x"]
        y0, y1 = zone["y"]
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
            raise ConfigError(f"Zone '{name}' lies outside the venue.")
    zone_names = set(venue["zones"])
    if set(mob["destination_probabilities"]) != zone_names:
        raise ConfigError("destination_probabilities must list exactly the venue zones.")
    if set(mob["dwell_s"]) != zone_names:
        raise ConfigError("dwell_s must list exactly the venue zones.")
    prob_sum = sum(mob["destination_probabilities"].values())
    if abs(prob_sum - 1.0) > 1e-9:
        raise ConfigError(f"destination_probabilities must sum to 1 (got {prob_sum}).")
    if not 0 < mob["speed_min_mps"] <= mob["speed_max_mps"]:
        raise ConfigError("Invalid walking speed range.")
    if not 0.0 <= mob["group_participation"] <= 1.0:
        raise ConfigError("group_participation must be in [0, 1].")
    if not 2 <= mob["group_size_min"] <= mob["group_size_max"]:
        raise ConfigError("Invalid friend group size range.")

    if comm["radius_m"] <= 0:
        raise ConfigError("radius_m must be positive.")
    if comm["transfer_capacity_per_node_per_s"] < 1:
        raise ConfigError("transfer capacity must be >= 1.")
    if not 0.0 <= comm["transfer_failure_prob"] < 1.0:
        raise ConfigError("transfer_failure_prob must be in [0, 1).")
    if comm["contact_setup_delay_s"] < 0:
        raise ConfigError("contact_setup_delay_s must be >= 0.")

    if cfg["buffer"]["capacity_messages"] < 1:
        raise ConfigError("Buffer capacity must be >= 1.")
    if cfg["buffer"]["drop_policy"] not in DROP_POLICIES:
        raise ConfigError(f"drop_policy must be one of {DROP_POLICIES}.")
    if traffic["workload_type"] not in WORKLOAD_TYPES:
        raise ConfigError(f"workload_type must be one of {WORKLOAD_TYPES}.")

    if routing["algorithm"] not in ALGORITHMS:
        raise ConfigError(f"algorithm must be one of {ALGORITHMS}.")
    if routing["algorithm"] in TOKEN_ALGORITHMS and routing["copy_budget"] < 1:
        raise ConfigError("copy_budget must be >= 1.")
    mws = routing["mws"]
    if mws["motion_signal"] not in MOTION_SIGNALS:
        raise ConfigError(f"motion_signal must be one of {MOTION_SIGNALS}.")
    if mws["fallback_s"] < 0:
        raise ConfigError("fallback_s must be >= 0.")
    if not 0 < mws["history_threshold"] <= 1:
        raise ConfigError("history_threshold must be in (0, 1].")
    if mws["history_window_s"] < 1:
        raise ConfigError("history_window_s must be >= 1.")

    if not 0.0 <= motion["error_rate"] < 0.5:
        raise ConfigError("motion error_rate must be in [0, 0.5).")
    if motion["error_model"] not in ERROR_MODELS:
        raise ConfigError(f"error_model must be one of {ERROR_MODELS}.")
    if motion["mean_burst_s"] < 1:
        raise ConfigError("mean_burst_s must be >= 1.")


# --------------------------------------------------------------------------- #
# Effective configuration (canonical form used for equivalence detection)
# --------------------------------------------------------------------------- #
def effective_routing(cfg: dict) -> dict:
    """Return the canonical routing description of a config.

    Parameters an algorithm ignores are removed so that behaviourally identical
    configurations hash identically:

    * MWS with no rule enabled is exactly BSW.
    * Patience fallback (R3) only relaxes walker preference (R2); without R2 it
      has no effect and is dropped.
    * History parameters matter only for the historical motion signal.
    * Motion-classification settings matter only when R2 is active.
    * The copy budget matters only for token-based algorithms.
    """
    routing = cfg["routing"]
    algorithm = routing["algorithm"]
    out: dict[str, Any] = {
        "algorithm": algorithm,
        "carrier_keeps_replica_after_delivery": routing["carrier_keeps_replica_after_delivery"],
    }
    if algorithm == "MWS":
        mws = routing["mws"]
        r1, r2 = bool(mws["friend_exclusion"]), bool(mws["walker_preference"])
        r3 = bool(mws["patience_fallback"]) and r2
        if not (r1 or r2):
            algorithm = "BSW"
            out["algorithm"] = "BSW"
        else:
            rules: dict[str, Any] = {"R1_friend_exclusion": r1, "R2_walker_preference": r2,
                                     "R3_patience_fallback": r3}
            if r3:
                rules["fallback_s"] = mws["fallback_s"]
            if r2:
                rules["motion_signal"] = mws["motion_signal"]
                if mws["motion_signal"] == "historical":
                    rules["history_window_s"] = mws["history_window_s"]
                    rules["history_threshold"] = mws["history_threshold"]
                motion = cfg["motion_classification"]
                rules["motion_error_rate"] = motion["error_rate"]
                if motion["error_rate"] > 0:
                    rules["motion_error_model"] = motion["error_model"]
                    if motion["error_model"] == "correlated":
                        rules["motion_mean_burst_s"] = motion["mean_burst_s"]
            out["mws"] = rules
    if algorithm in TOKEN_ALGORITHMS:
        out["copy_budget"] = routing["copy_budget"]
    return out


def effective_config(cfg: dict) -> dict:
    """Everything that can influence a run's outcome, excluding the seed."""
    return {
        "simulation": cfg["simulation"],
        "venue": cfg["venue"],
        "node_count": cfg["nodes"]["node_count"],
        "mobility": cfg["mobility"],
        "communication": cfg["communication"],
        "traffic": cfg["traffic"],
        "buffer": cfg["buffer"],
        "routing": effective_routing(cfg),
        "metrics": cfg["metrics"],
    }


def stable_hash(obj: Any, length: int = 16) -> str:
    """Deterministic SHA-256 hash of a JSON-serialisable object."""
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def configuration_id(cfg: dict) -> str:
    return stable_hash(effective_config(cfg))


def full_config_hash(cfg: dict) -> str:
    return stable_hash(cfg, length=64)


def variant_label(cfg: dict) -> str:
    """Human-readable variant name derived from the effective routing config."""
    eff = effective_routing(cfg)
    algorithm = eff["algorithm"]
    if algorithm == "MWS":
        rules = eff["mws"]
        parts = [name for name, flag in (("R1", rules["R1_friend_exclusion"]),
                                         ("R2", rules["R2_walker_preference"]),
                                         ("R3", rules["R3_patience_fallback"])) if flag]
        label = "MWS[" + "+".join(parts)
        if rules.get("motion_signal") == "historical":
            label += f"|hist{rules['history_window_s']}s"
        elif rules.get("motion_signal") == "immediate":
            label += "|immediate"
        label += "]"
        if rules.get("motion_error_rate", 0) > 0:
            label += f"@err{int(round(rules['motion_error_rate'] * 100))}%"
            if rules.get("motion_error_model") == "correlated":
                label += "-corr"
        return label
    if algorithm == "BSW":
        return "BSW"
    return algorithm


def scenario_key(cfg: dict, seed: int) -> dict:
    """Inputs that determine the shared scenario (independent of routing)."""
    return {
        "seed": int(seed),
        "node_count": cfg["nodes"]["node_count"],
        "simulation": cfg["simulation"],
        "venue": cfg["venue"],
        "mobility": cfg["mobility"],
        "radius_m": cfg["communication"]["radius_m"],
        "traffic": cfg["traffic"],
    }


def mobility_key(cfg: dict, seed: int) -> dict:
    """Inputs that determine the mobility trace (independent of radius/workload)."""
    return {
        "seed": int(seed),
        "node_count": cfg["nodes"]["node_count"],
        "simulation": cfg["simulation"],
        "venue": cfg["venue"],
        "mobility": cfg["mobility"],
    }
