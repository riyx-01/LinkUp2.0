"""Stand-alone mobility/contact/workload validation (no routing involved).

Run *before* routing evaluation. The adequacy criteria below are
algorithm-independent and pre-specified; they must never be tuned with MWS or
any other routing results.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.tables import md_table
from simulator.config import apply_overrides
from simulator.scenario import build_scenario

from .matrix import check_phase_seeds
from .provenance import provenance_record
from .runner import load_phase_config, phase_dir

ADEQUACY_CRITERIA = {
    "integrity": "positions outside venue, stationary moves and speed violations are all zero",
    "workload_fallback_share": "<= 5 % of primary-workload messages use a fallback pair",
    "eligible_pair_coverage": ">= 95 % of generation-window seconds have an eligible separated pair",
    "grouped_fraction": "within 5 percentage points of the configured group participation",
}

KEY_METRICS = [
    "pct_time_walking", "walking_speed_realised_mean_mps", "avg_neighbours_per_node", "neighbours_p90",
    "pct_node_time_isolated", "contact_events_per_node_per_hour", "contact_duration_median_s",
    "encounter_start_involving_walker_share", "contact_seconds_both_stationary_share",
    "separation_events_total", "separation_duration_mean_s", "mean_separated_members",
    "pct_generation_seconds_with_eligible_pair", "messages_generated", "workload_fallback_share",
    "pairs_in_range_at_creation_share", "grouped_fraction",
]


def validate(phase: str = "pilot", seeds: list[int] | None = None, node_counts=(50, 100, 200),
             root: Path | None = None) -> pd.DataFrame:
    cfg = load_phase_config(phase)
    seeds = list(seeds or cfg["seeds"])
    check_phase_seeds(phase, seeds)
    rows = []
    for n in node_counts:
        for seed in seeds:
            c = apply_overrides(cfg, {"nodes.node_count": n})
            scen = build_scenario(c, seed)
            v = scen.validation
            row = {"node_count": n, "seed": seed, "scenario_hash": scen.scenario_hash}
            row.update({k: v[k] for k in v if not isinstance(v[k], (dict, list))})
            row.update({f"zone_share_{k}": val for k, val in v["zone_occupancy_share"].items()})
            row.update({f"local_neighbours_{k}": val for k, val in v["local_avg_neighbours_by_zone"].items()})
            row.update({f"integrity_{k}": val for k, val in v["integrity"].items()})
            row["walking_speed_hist_counts"] = json.dumps(v["walking_speed_hist_counts"])
            row["walking_speed_hist_edges"] = json.dumps(v["walking_speed_hist_edges"])
            rows.append(row)
            print(f"  validated N={n} seed={seed}", flush=True)
    df = pd.DataFrame(rows)
    out = phase_dir(phase, root) / "validation"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "mobility_validation.csv", index=False)
    checks = adequacy_checks(df, cfg)
    (out / "mobility_validation.md").write_text(render_markdown(df, checks, phase, seeds), encoding="utf-8")
    try:
        from analysis.visualizations import mobility_validation_figure
        mobility_validation_figure(df, out)
    except Exception as exc:  # noqa: BLE001 - figure is optional for validation
        print(f"  (validation figure skipped: {exc})")
    return df


def adequacy_checks(df: pd.DataFrame, cfg: dict) -> list[dict]:
    target = cfg["mobility"]["group_participation"]
    integ = df[["integrity_positions_outside_venue", "integrity_stationary_moves",
                "integrity_speed_violations"]].to_numpy().sum()
    return [
        {"criterion": "integrity", "rule": ADEQUACY_CRITERIA["integrity"],
         "observed": f"total violations = {int(integ)}", "pass": bool(integ == 0)},
        {"criterion": "workload_fallback_share", "rule": ADEQUACY_CRITERIA["workload_fallback_share"],
         "observed": f"max = {df['workload_fallback_share'].max():.3f}",
         "pass": bool(df["workload_fallback_share"].max() <= 0.05)},
        {"criterion": "eligible_pair_coverage", "rule": ADEQUACY_CRITERIA["eligible_pair_coverage"],
         "observed": f"min = {df['pct_generation_seconds_with_eligible_pair'].min():.1f} %",
         "pass": bool(df["pct_generation_seconds_with_eligible_pair"].min() >= 95)},
        {"criterion": "grouped_fraction", "rule": ADEQUACY_CRITERIA["grouped_fraction"],
         "observed": f"range {df['grouped_fraction'].min():.3f}-{df['grouped_fraction'].max():.3f}",
         "pass": bool((df["grouped_fraction"] - target).abs().max() <= 0.05)},
    ]


def render_markdown(df: pd.DataFrame, checks: list[dict], phase: str, seeds: list[int]) -> str:
    summary = df.groupby("node_count")[KEY_METRICS].agg(["mean", "std"])
    table = []
    for metric in KEY_METRICS:
        row = {"metric": metric}
        for n in sorted(df["node_count"].unique()):
            m, s = summary.loc[n, (metric, "mean")], summary.loc[n, (metric, "std")]
            row[f"N={n} mean (SD)"] = f"{m:.3f} ({s:.3f})" if not np.isnan(s) else f"{m:.3f}"
        table.append(row)
    zone_cols = [c for c in df.columns if c.startswith("zone_share_")]
    zones = df.groupby("node_count")[zone_cols].mean().round(3)
    zones.columns = [c.replace("zone_share_", "") for c in zones.columns]
    prov = provenance_record()
    lines = [
        f"# Mobility, contact and workload validation ({phase})", "",
        f"Seeds: {seeds}. Code version: {prov['code_version']}. Statistics use the post-warm-up period.",
        "These outputs are algorithm-independent and were produced before any routing evaluation.", "",
        "## Adequacy checks (pre-specified, algorithm-independent)", "",
        md_table(pd.DataFrame(checks)), "",
        "## Key statistics across seeds (mean and SD across seeds)", "",
        md_table(pd.DataFrame(table)), "",
        "## Share of node-time per zone (mean across seeds)", "",
        md_table(zones, digits=3, index=True), "",
        "Interpretation notes:",
        "- Densities are relative densities of participating smartphones, not total crowd density.",
        "- 'encounter_start_involving_walker_share' is the share of contact events whose first second "
        "involves at least one walking node; contacts between two stationary nodes can only start when "
        "a node arrives, so this share is expected to be high under any mobility model with dwelling.",
        "- Separated members rejoin their group physically, so many separated pairs are reunited within "
        "a message lifetime; this bounds how much any forwarding algorithm can improve D15.",
        "",
    ]
    return "\n".join(lines)
