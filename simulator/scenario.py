"""Shared, algorithm-independent scenarios.

A scenario bundles everything that must be identical across routing algorithms
for one (seed, node count, radius, workload): friend groups, the mobility trace,
the contact trace, the message workload and (lazily) the observed-motion
traces. Its ``scenario_hash`` fingerprints the routing-relevant inputs and is
stored with every run so that identical inputs can be verified afterwards.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import config as cfgmod
from .contacts import ContactTrace, compute_contact_trace, first_pair_contacts
from .groups import GroupAssignment
from .message import MessageTable
from .mobility import MobilityTrace, generate_mobility
from .motion import historical_walking, observed_walking
from .validation import mobility_contact_validation
from .workload import generate_workload


def _hash_arrays(*arrays: np.ndarray) -> str:
    h = hashlib.sha256()
    for arr in arrays:
        a = np.ascontiguousarray(arr)
        h.update(str(a.dtype).encode())
        h.update(str(a.shape).encode())
        h.update(a.tobytes())
    return h.hexdigest()[:16]


@dataclass
class Scenario:
    seed: int
    node_count: int
    cfg: dict
    scenario_id: str
    mobility: MobilityTrace
    contacts: ContactTrace
    messages: MessageTable
    validation: dict
    scenario_hash: str
    _motion_cache: dict = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------ motion
    def observed_motion(self, error_rate: float, error_model: str, mean_burst_s: float) -> np.ndarray:
        key = ("observed", float(error_rate), error_model if error_rate > 0 else "-",
               float(mean_burst_s) if error_model == "correlated" else 0.0)
        if key not in self._motion_cache:
            self._motion_cache[key] = observed_walking(self.mobility.walking, error_rate,
                                                       error_model, mean_burst_s, self.seed)
        return self._motion_cache[key]

    def motion_signal(self, signal: str, error_rate: float, error_model: str, mean_burst_s: float,
                      window_s: int = 300, threshold: float = 0.5) -> np.ndarray:
        observed = self.observed_motion(error_rate, error_model, mean_burst_s)
        if signal == "immediate":
            return observed
        key = ("historical", float(error_rate), error_model, float(mean_burst_s), int(window_s), float(threshold))
        if key not in self._motion_cache:
            self._motion_cache[key] = historical_walking(observed, window_s, threshold)
        return self._motion_cache[key]

    # ------------------------------------------------------------ persistence
    def save(self, path: Path, save_positions: bool = True) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        mob, msg = self.mobility, self.messages
        arrays = {
            "group_of": mob.groups.group_of,
            "offsets": mob.groups.offsets,
            "speed_factor": mob.groups.speed_factor,
            "walking": np.packbits(mob.walking, axis=None),
            "walking_shape": np.array(mob.walking.shape),
            "sep_state": mob.sep_state,
            "zone": mob.zone,
            "contact_offsets": self.contacts.offsets,
            "contact_pairs": self.contacts.pairs.astype(np.int16 if self.node_count < 32000 else np.int32),
            "msg_source": msg.source, "msg_destination": msg.destination,
            "msg_created": msg.created, "msg_expiry": msg.expiry,
            "msg_relationship": msg.relationship.astype(str),
            "msg_initial_distance": msg.initial_distance,
            "separation_events": np.array(mob.separation_events, dtype=np.int64).reshape(-1, 3),
            "rejoin_events": np.array(mob.rejoin_events, dtype=np.int64).reshape(-1, 3),
            "trip_speeds": np.array(mob.trip_speeds),
        }
        # Save each error condition's observed-motion flips that were used.
        for key, arr in self._motion_cache.items():
            if key[0] == "observed" and key[1] > 0:
                arrays[f"observed_err_{key[1]:.3f}_{key[2]}"] = np.packbits(arr, axis=None)
        if save_positions:
            arrays["positions"] = mob.positions
        meta = {"seed": self.seed, "node_count": self.node_count, "scenario_id": self.scenario_id,
                "scenario_hash": self.scenario_hash, "contact_start": self.contacts.start,
                "payload_bytes": msg.payload_bytes, "config": self.cfg, "validation": self.validation}
        np.savez_compressed(path, meta=np.array(json.dumps(meta, default=str)), **arrays)

    @classmethod
    def load(cls, path: Path) -> "Scenario":
        with np.load(path, allow_pickle=False) as data:
            meta = json.loads(str(data["meta"]))
            shape = tuple(int(x) for x in data["walking_shape"])
            walking = np.unpackbits(data["walking"], count=shape[0] * shape[1]).astype(bool).reshape(shape)
            positions = data["positions"] if "positions" in data.files else None
            groups_of = data["group_of"]
            members = [np.flatnonzero(groups_of == g) for g in range(int(groups_of.max()) + 1)] \
                if groups_of.size and groups_of.max() >= 0 else []
            groups = GroupAssignment(groups_of, members, data["offsets"], data["speed_factor"])
            mob = MobilityTrace(
                positions=positions, walking=walking, zone=data["zone"], sep_state=data["sep_state"],
                groups=groups,
                separation_events=[tuple(int(v) for v in r) for r in data["separation_events"]],
                rejoin_events=[tuple(int(v) for v in r) for r in data["rejoin_events"]],
                trip_speeds=data["trip_speeds"].tolist())
            contacts = ContactTrace(int(meta["contact_start"]), data["contact_offsets"],
                                    data["contact_pairs"].astype(np.int32))
            messages = MessageTable(
                source=data["msg_source"], destination=data["msg_destination"],
                created=data["msg_created"], expiry=data["msg_expiry"],
                relationship=data["msg_relationship"].astype(object),
                payload_bytes=int(meta["payload_bytes"]),
                initial_distance=data["msg_initial_distance"])
        scen = cls(int(meta["seed"]), int(meta["node_count"]), meta["config"], meta["scenario_id"],
                   mob, contacts, messages, meta["validation"], meta["scenario_hash"])
        if scen.compute_hash() != scen.scenario_hash:
            raise ValueError(f"Scenario file {path} failed its integrity hash check.")
        attach_message_diagnostics(scen)
        return scen

    def compute_hash(self) -> str:
        msg = self.messages
        return _hash_arrays(self.mobility.groups.group_of.astype(np.int64),
                            self.mobility.walking, self.contacts.offsets.astype(np.int64),
                            self.contacts.pairs.astype(np.int32),
                            msg.source.astype(np.int64), msg.destination.astype(np.int64),
                            msg.created.astype(np.int64), msg.expiry.astype(np.int64))


def attach_message_diagnostics(scen: "Scenario") -> None:
    """Evaluation-only source-destination contact diagnostics (not part of the scenario hash)."""
    msg = scen.messages
    first = first_pair_contacts(scen.contacts, scen.node_count, msg.source, msg.destination, msg.created, msg.expiry)
    msg.first_direct_contact = first
    msg.in_range_at_creation = first == msg.created


def scenario_id_for(cfg: dict, seed: int) -> str:
    return cfgmod.stable_hash(cfgmod.scenario_key(cfg, seed))


def build_scenario(cfg: dict, seed: int, mobility: MobilityTrace | None = None) -> Scenario:
    """Generate (or complete from a supplied mobility trace) the shared scenario."""
    node_count = int(cfg["nodes"]["node_count"])
    if mobility is None:
        mobility = generate_mobility(cfg, node_count, seed)
    sim = cfg["simulation"]
    contacts = compute_contact_trace(mobility.positions, float(cfg["communication"]["radius_m"]),
                                     int(sim["warmup_s"]), int(sim["duration_s"]))
    messages = generate_workload(cfg, mobility, seed)
    validation = mobility_contact_validation(cfg, mobility, contacts, messages)
    scen = Scenario(seed=int(seed), node_count=node_count, cfg=cfgmod.scenario_key(cfg, seed),
                    scenario_id=scenario_id_for(cfg, seed), mobility=mobility, contacts=contacts,
                    messages=messages, validation=validation, scenario_hash="")
    scen.scenario_hash = scen.compute_hash()
    attach_message_diagnostics(scen)
    return scen


def load_or_build(cfg: dict, seed: int, cache_dir: Path | None) -> Scenario:
    """Load a cached scenario if present and valid, otherwise build it."""
    if cache_dir is not None:
        path = Path(cache_dir) / f"{scenario_id_for(cfg, seed)}.npz"
        if path.exists():
            return Scenario.load(path)
    return build_scenario(cfg, seed)
