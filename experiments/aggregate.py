"""Aggregate per-run raw files into the processed CSV tables.

Outputs (``results/<phase>/processed/``):

* ``run_results.csv``      one row per executed run (ok *and* failed)
* ``message_results.csv``  one row per message per run
* ``mobility_validation.csv`` one row per scenario (algorithm independent)
* ``experiment_matrix.csv`` experiment arms -> configuration ids (with reuse)
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .matrix import build_matrix
from .runner import load_phase_config, phase_dir

RUN_COLUMNS = [
    "experiment_id", "run_id", "configuration_id", "phase", "algorithm", "variant", "seed", "node_count",
    "venue_width_m", "venue_height_m", "simulation_duration_s", "communication_radius_m", "copy_budget",
    "fallback_s", "motion_error_rate", "workload_type", "generated_messages", "delivered_2min",
    "delivered_5min", "delivered_15min", "d2_percent", "d5_percent", "d15_percent", "completed_transfers",
    "intermediate_transfers", "destination_transfers", "repeated_destination_receptions",
    "transfers_per_message", "mean_latency_s", "median_latency_s", "p90_latency_s", "mean_delivery_hops",
    "undelivered_messages", "expired_replicas", "buffer_drops", "duplicate_opportunities_prevented",
    "runtime_s", "run_status", "scenario_hash", "code_version",
]
EXTRA_COLUMNS = [
    "motion_signal", "unique_delivered", "q25_latency_s", "q75_latency_s", "intermediate_transfers_per_message",
    "source_replicas", "created_replicas", "peak_simultaneous_replicas", "tokens_lost_buffer_drops",
    "tokens_expired", "failed_transfers", "rejected_transfers", "capacity_blocked_opportunities",
    "token_exhausted_in_step", "sender_replica_lost_in_step", "avg_buffer_occupancy", "max_buffer_occupancy",
    "token_conservation_ok", "avg_neighbour_count", "workload_fallback_count", "scenario_generation_s",
    "scenario_id", "configuration_hash", "full_config_sha256", "error_message",
]


def _flatten(prefix: str, d: dict | None) -> dict:
    return {f"{prefix}{k}": v for k, v in (d or {}).items()}


def load_run_records(root: Path) -> list[dict]:
    records = []
    for path in sorted((root / "raw" / "runs").glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        records.append(rec)
    return records


def aggregate_phase(phase: str, root: Path | None = None) -> dict[str, Path]:
    out_root = phase_dir(phase, root)
    proc = out_root / "processed"
    proc.mkdir(parents=True, exist_ok=True)
    phase_cfg = load_phase_config(phase)
    matrix = build_matrix(phase_cfg, include_optional=True)

    rows = []
    for rec in load_run_records(out_root):
        row = {k: rec.get(k) for k in RUN_COLUMNS + EXTRA_COLUMNS}
        row["experiment_id"] = "|".join(matrix.experiment_ids_for(rec["configuration_id"])) or "unlisted"
        row.update(_flatten("decisions_", rec.get("decision_counts")))
        row.update(_flatten("transfers_", rec.get("transfer_reasons")))
        if row.get("error_message"):
            row["error_message"] = row["error_message"].splitlines()[0][:300]
        rows.append(row)
    runs = pd.DataFrame(rows)
    if not runs.empty:
        ordered = [c for c in RUN_COLUMNS + EXTRA_COLUMNS if c in runs.columns]
        runs = runs[ordered + sorted(c for c in runs.columns if c not in ordered)]
        runs = runs.sort_values(["configuration_id", "seed"]).reset_index(drop=True)
    paths = {"run_results": proc / "run_results.csv"}
    runs.to_csv(paths["run_results"], index=False)

    frames = []
    for path in sorted((out_root / "raw" / "messages").glob("*.csv")):
        df = pd.read_csv(path)
        df.insert(0, "run_id", path.stem)
        frames.append(df)
    msgs = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    paths["message_results"] = proc / "message_results.csv"
    msgs.to_csv(paths["message_results"], index=False)

    vrows = []
    for path in sorted((out_root / "raw" / "scenarios").glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        v = rec.pop("validation")
        flat = {k: val for k, val in v.items() if not isinstance(val, (dict, list))}
        flat.update(_flatten("zone_share_", v.get("zone_occupancy_share")))
        flat.update(_flatten("local_neighbours_", v.get("local_avg_neighbours_by_zone")))
        flat.update(_flatten("integrity_", v.get("integrity")))
        flat.update(_flatten("workload_", v.get("workload_relationship_counts")))
        flat["mean_group_size"] = (sum(v["group_sizes"]) / len(v["group_sizes"])) if v.get("group_sizes") else None
        flat["walking_speed_hist_counts"] = json.dumps(v.get("walking_speed_hist_counts"))
        vrows.append({**rec, **flat})
    paths["mobility_validation"] = proc / "mobility_validation.csv"
    pd.DataFrame(vrows).to_csv(paths["mobility_validation"], index=False)

    paths["experiment_matrix"] = proc / "experiment_matrix.csv"
    pd.DataFrame(matrix.rows()).to_csv(paths["experiment_matrix"], index=False)
    return paths
