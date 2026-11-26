"""Supporting (exploratory) diagnostics: efficiency metrics, MWS rule counters, workload subgroups and the
X1/X3/X3b/X4 sensitivity experiments. None of these replace the primary metrics or hypotheses.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from experiments.aggregate import RULE_RATES

from .confidence_intervals import summarize
from .data import DENSITIES, PhaseData
from .hypothesis_tests import one_sample_test, paired_frame

EFFICIENCY_METRICS = [
    ("timely_deliveries_per_100_transfers", "Timely (5-min) deliveries per 100 completed transfers"),
    ("mean_time_to_first_relay_s", "Mean time from creation to first relay copy (s; messages with a relay)"),
    ("pct_messages_with_relay", "% messages with at least one relay copy"),
    ("mean_time_to_half_copies_s", "Mean time until ceil(L/2) copies exist (s; messages reaching it)"),
    ("pct_messages_half_copies", "% messages reaching ceil(L/2) copies"),
    ("mean_time_to_spray_complete_s", "Mean time to complete the spray phase (s; messages completing it)"),
    ("pct_messages_spray_complete", "% messages completing the spray phase before expiry"),
    ("copy_budget_utilization", "Copy-budget utilisation: mean relays / (L - 1)"),
    ("relays_before_first_delivery", "Relays of delivered messages before their first delivery (per run)"),
    ("relays_after_first_delivery", "Relays of delivered messages after their first delivery (per run)"),
    ("relays_on_undelivered_messages", "Relays of messages that were never delivered (per run)"),
    ("intermediate_transfers_per_delivered_message", "All relays / unique delivered messages"),
]
WORKLOAD_METRICS = [
    ("messages_dest_in_range_at_creation", "Messages whose destination was in range at creation (per run)"),
    ("d5_percent_dest_in_range", "D5 (%) - destination in range at creation"),
    ("d5_percent_dest_out_of_range", "D5 (%) - destination out of range at creation"),
    ("pct_messages_with_direct_contact", "% messages whose source and destination met directly before expiry"),
    ("pct_delivered_before_direct_contact", "% of delivered messages delivered before any direct contact"),
    ("pct_delivered_via_relay", "% of delivered messages delivered by a relay (hops > 1)"),
]
SENSITIVITY = ("X1", "X3", "X3b", "X4")
SHORT = {
    "timely_deliveries_per_100_transfers": "D5 deliveries /100 transfers",
    "mean_time_to_first_relay_s": "first relay (s)",
    "mean_time_to_half_copies_s": "half copies (s)",
    "mean_time_to_spray_complete_s": "spray complete (s)",
    "pct_messages_spray_complete": "% spray complete",
    "copy_budget_utilization": "budget used",
    "relays_after_first_delivery": "relays after delivery /run",
    "intermediate_transfers_per_delivered_message": "relays per delivered msg",
}


def _arm_rows(d: PhaseData, experiments=("E1",), algorithms=None) -> list[tuple[str, pd.Series]]:
    out = []
    for exp in experiments:
        for _, arm in d.arms(exp).iterrows():
            if algorithms and arm["algorithm"] not in algorithms:
                continue
            out.append((exp, arm))
    return out


def metric_table(d: PhaseData, metrics, experiments=("E1",), algorithms=None) -> pd.DataFrame:
    rows = []
    for exp, arm in _arm_rows(d, experiments, algorithms):
        runs = d.runs_for(arm["configuration_id"])
        row = {"experiment": exp, "arm": arm["arm_label"], "algorithm": arm["algorithm"],
               "node_count": arm["node_count"], "n_runs": len(runs)}
        for col, _ in metrics:
            if col in runs:
                s = summarize(runs[col].to_numpy(dtype=float))
                row[f"{col}_mean"] = s["mean"]
                row[f"{col}_sd"] = s["sd"]
                row[f"{col}_n_defined"] = s["n"]  # runs where the metric is defined (NaN = undefined)
            else:
                row[f"{col}_mean"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def efficiency_table(d: PhaseData) -> pd.DataFrame:
    return metric_table(d, EFFICIENCY_METRICS, ("E1",))


def workload_table(d: PhaseData) -> pd.DataFrame:
    return metric_table(d, WORKLOAD_METRICS, ("E1", "E6"))


def rule_table(d: PhaseData) -> pd.DataFrame:
    cols = [(c, desc) for c, _, _, desc in RULE_RATES] + [("token_exhausted_in_step", "within-second token exhaustion")]
    return metric_table(d, cols, ("E1", "E3", "E5"), algorithms=("BSW", "MWS"))


def _condition(label: str, algorithm: str) -> str:
    parts = [p.strip() for p in label.split("|")]
    if parts and parts[-1] == algorithm:
        parts = parts[:-1]
    text = " | ".join(parts)
    return text.replace("communication.radius_m", "radius").replace("mean_interarrival_s", "mean interval (s)")


def sensitivity_table(d: PhaseData) -> pd.DataFrame:
    """Per condition: BSW and MWS levels and the paired MWS - BSW D5 difference (exploratory)."""
    rows = []
    for exp in SENSITIVITY:
        arms = d.arms(exp)
        if arms.empty:
            continue
        arms = arms.assign(condition=[_condition(lbl, alg) for lbl, alg in zip(arms["arm_label"], arms["algorithm"])])
        for cond, grp in arms.groupby("condition", sort=False):
            ids = {r["algorithm"]: r["configuration_id"] for _, r in grp.iterrows()}
            if not {"BSW", "MWS"} <= set(ids):
                continue
            row = {"experiment": exp, "condition": cond}
            for alg in ("BSW", "MWS"):
                runs = d.runs_for(ids[alg])
                row[f"n_{alg}"] = len(runs)
                for col in ("d5_percent", "d15_percent", "transfers_per_message", "capacity_blocked_per_message",
                            "buffer_drops", "generated_messages"):
                    row[f"{col}_{alg}"] = runs[col].mean() if col in runs and len(runs) else np.nan
            fr, missing = paired_frame(d, ids["MWS"], ids["BSW"], "d5_percent")
            res = one_sample_test(fr["diff"].to_numpy(), "two-sided")
            row.update({"dD5_mean_pp": res["mean_diff"], "dD5_ci95_low": res["ci95_low"],
                        "dD5_ci95_high": res["ci95_high"], "dD5_p_unadjusted": res["p_raw"], "pairs": res["n"],
                        "missing_pairs": len(missing), "status": "exploratory (not confirmatory; unadjusted)"})
            rows.append(row)
    return pd.DataFrame(rows)


def per_density_efficiency(d: PhaseData) -> pd.DataFrame:
    """Compact E1 efficiency view for the report (BSW and MWS only)."""
    rows = []
    for n in DENSITIES:
        for alg in ("BSW", "MWS"):
            runs = d.runs_for(d.e1_config(alg, n))
            if runs.empty:
                continue
            row = {"nodes": n, "algorithm": alg}
            for col, short in SHORT.items():
                row[short] = runs[col].mean() if col in runs else np.nan
            rows.append(row)
    return pd.DataFrame(rows)
