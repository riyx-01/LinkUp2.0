"""Descriptive summaries per configuration/experiment and cumulative delivery curves."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .confidence_intervals import summarize
from .data import DENSITIES, E1_ALGORITHMS, PhaseData

KEY_METRICS = [
    "d2_percent", "d5_percent", "d15_percent", "transfers_per_message", "intermediate_transfers_per_message",
    "median_latency_s", "mean_latency_s", "p90_latency_s", "mean_delivery_hops", "undelivered_messages",
    "expired_replicas", "buffer_drops", "peak_simultaneous_replicas", "avg_buffer_occupancy",
    "duplicate_opportunities_prevented", "runtime_s",
]
METRIC_LABELS = {
    "d2_percent": "D2 (%)", "d5_percent": "D5 (%)", "d15_percent": "D15 (%)",
    "transfers_per_message": "Transfers per message", "median_latency_s": "Median latency (s)",
    "mean_latency_s": "Mean latency (s)", "p90_latency_s": "P90 latency (s)",
    "buffer_drops": "Buffer drops", "runtime_s": "Routing runtime (s)",
}


def config_summary(d: PhaseData, config_id: str, metrics=KEY_METRICS) -> dict:
    runs = d.runs_for(config_id)
    out = {"configuration_id": config_id, "n_runs": len(runs)}
    for m in metrics:
        s = summarize(runs[m].to_numpy()) if m in runs else summarize(np.array([]))
        out.update({f"{m}_mean": s["mean"], f"{m}_sd": s["sd"], f"{m}_ci_low": s["ci_low"],
                    f"{m}_ci_high": s["ci_high"], f"{m}_median": s["median"]})
    return out


def experiment_summary(d: PhaseData, experiment_id: str, metrics=KEY_METRICS) -> pd.DataFrame:
    rows = []
    for _, arm in d.arms(experiment_id).iterrows():
        row = {"experiment_id": experiment_id, "arm_label": arm["arm_label"], "algorithm": arm["algorithm"],
               "variant": arm["variant"], "node_count": arm["node_count"], "copy_budget": arm["copy_budget"],
               "motion_error_rate": arm["motion_error_rate"], "workload_type": arm["workload_type"]}
        row.update(config_summary(d, arm["configuration_id"], metrics))
        rows.append(row)
    return pd.DataFrame(rows)


def compact_table(summary: pd.DataFrame, metrics: list[str], digits: int = 1) -> pd.DataFrame:
    """Readable 'mean (SD)' table for reports."""
    out = summary[["arm_label", "n_runs"]].copy()
    for m in metrics:
        label = METRIC_LABELS.get(m, m)
        out[label] = [f"{a:.{digits}f} ({b:.{digits}f})" if a == a else "missing"
                      for a, b in zip(summary[f"{m}_mean"], summary[f"{m}_sd"].fillna(np.nan))]
    return out


def cumulative_delivery(d: PhaseData, config_id: str, ages=np.arange(0, 901, 10)) -> pd.DataFrame:
    """Mean (and 95 % t-CI across seeds) % of *all generated* messages delivered by each age."""
    runs = d.runs_for(config_id)
    msgs = d.messages[d.messages["run_id"].isin(runs["run_id"])]
    curves = []
    for run_id, grp in msgs.groupby("run_id"):
        lat = grp["delivery_latency_s"].to_numpy(dtype=float)
        total = len(grp)
        curves.append([100.0 * np.sum(lat <= a) / total for a in ages])  # NaN (undelivered) never <= a
    if not curves:
        return pd.DataFrame({"age_s": ages, "mean": np.nan, "ci_low": np.nan, "ci_high": np.nan, "n": 0})
    arr = np.array(curves)
    rows = []
    for j, a in enumerate(ages):
        s = summarize(arr[:, j])
        rows.append({"age_s": int(a), "mean": s["mean"], "ci_low": s["ci_low"], "ci_high": s["ci_high"],
                     "n": s["n"]})
    return pd.DataFrame(rows)


def e1_long(d: PhaseData, metric: str) -> pd.DataFrame:
    """Per-run values of a metric for E1 (algorithm x density)."""
    rows = []
    for n in DENSITIES:
        for alg in E1_ALGORITHMS:
            runs = d.runs_for(d.e1_config(alg, n))
            for _, r in runs.iterrows():
                rows.append({"node_count": n, "algorithm": alg, "seed": r["seed"], metric: r[metric]})
    return pd.DataFrame(rows)


def e1_summary(d: PhaseData, metric: str) -> pd.DataFrame:
    long = e1_long(d, metric)
    rows = []
    for n in DENSITIES:
        for alg in E1_ALGORITHMS:
            vals = long[(long.node_count == n) & (long.algorithm == alg)][metric].to_numpy() \
                if not long.empty else np.array([])
            s = summarize(vals)
            rows.append({"node_count": n, "algorithm": alg, **s})
    return pd.DataFrame(rows)


def relationship_breakdown(d: PhaseData) -> pd.DataFrame:
    """Workload relationship counts per run (for the workload-validity check)."""
    if d.messages.empty:
        return pd.DataFrame()
    return (d.messages.groupby(["run_id", "source_destination_relationship"]).size()
            .unstack(fill_value=0).reset_index())
