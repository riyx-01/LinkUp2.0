"""Loading processed results and data-quality checks.

All analyses read the processed CSV tables written by the runner; every summary
is therefore traceable to saved per-run observations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from experiments.matrix import SEED_RANGES
from experiments.runner import load_phase_config, phase_dir

E1_ALGORITHMS = ("DirectDelivery", "Epidemic", "BSW", "MWS")
DENSITIES = (50, 100, 200)


@dataclass
class PhaseData:
    phase: str
    root: Path
    cfg: dict
    runs: pd.DataFrame          # every run record (ok + failed)
    ok: pd.DataFrame            # run_status == ok
    messages: pd.DataFrame
    validation: pd.DataFrame
    matrix: pd.DataFrame
    plan: pd.DataFrame
    quality: list[dict] = field(default_factory=list)

    @property
    def seeds(self) -> list[int]:
        return list(self.cfg["seeds"])

    def arms(self, experiment_id: str) -> pd.DataFrame:
        return self.matrix[self.matrix["experiment_id"] == experiment_id].reset_index(drop=True)

    def config_id(self, experiment_id: str, label: str | None = None, **match) -> str | None:
        arms = self.arms(experiment_id)
        if label is not None:
            arms = arms[arms["arm_label"] == label]
        for key, value in match.items():
            arms = arms[arms[key] == value]
        return None if arms.empty else str(arms.iloc[0]["configuration_id"])

    def runs_for(self, config_id: str | None) -> pd.DataFrame:
        if config_id is None:
            return self.ok.iloc[0:0]
        return self.ok[self.ok["configuration_id"] == config_id]

    def e1_config(self, algorithm: str, node_count: int) -> str | None:
        return self.config_id("E1", algorithm=algorithm, node_count=node_count)


def load_phase(phase: str, root: Path | None = None) -> PhaseData:
    out_root = phase_dir(phase, root)
    proc = out_root / "processed"
    if not (proc / "run_results.csv").exists():
        raise FileNotFoundError(f"No processed results for phase '{phase}' in {proc}. Run the batch first.")
    runs = pd.read_csv(proc / "run_results.csv")
    if runs.empty:
        raise ValueError(f"run_results.csv for phase '{phase}' is empty.")
    ok = runs[runs["run_status"] == "ok"].copy()
    messages = pd.read_csv(proc / "message_results.csv") if (proc / "message_results.csv").exists() else pd.DataFrame()
    validation = pd.read_csv(proc / "mobility_validation.csv") if (proc / "mobility_validation.csv").exists() \
        else pd.DataFrame()
    matrix = pd.read_csv(proc / "experiment_matrix.csv")
    plan = pd.read_csv(proc / "run_plan.csv") if (proc / "run_plan.csv").exists() else pd.DataFrame()
    data = PhaseData(phase, out_root, load_phase_config(phase), runs, ok, messages, validation, matrix, plan)
    data.quality = data_quality_checks(data)
    return data


def _check(name: str, passed: bool | None, detail: str, severity: str = "FAIL") -> dict:
    status = "PASS" if passed else (severity if passed is not None else "N/A")
    return {"check": name, "status": status, "detail": detail}


def data_quality_checks(d: PhaseData) -> list[dict]:
    checks = []
    runs, ok = d.runs, d.ok
    planned = set(d.plan["run_id"]) if not d.plan.empty else set()
    present = set(runs["run_id"])
    missing = sorted(planned - present)
    checks.append(_check("All planned runs present", not missing,
                         f"{len(planned)} planned, {len(present & planned)} present, {len(missing)} missing"
                         + (f": {missing[:10]}" if missing else "")))
    failed = runs[runs["run_status"] != "ok"]
    checks.append(_check("No failed runs", failed.empty,
                         f"{len(failed)} failed" + (f": {failed['run_id'].tolist()[:10]}" if len(failed) else "")))
    versions = sorted(runs["code_version"].dropna().unique())
    checks.append(_check("Single code version", len(versions) == 1, f"versions: {versions}"))
    allowed = SEED_RANGES[d.phase]
    bad_seeds = sorted({int(s) for s in runs["seed"] if int(s) not in allowed})
    checks.append(_check("Seeds within phase range", not bad_seeds,
                         f"allowed {allowed.start}-{allowed.stop - 1}; outside: {bad_seeds}"))
    if "token_conservation_ok" in ok:
        bad = ok[ok["token_conservation_ok"].astype(str) != "True"]
        checks.append(_check("Token conservation (token algorithms)", bad.empty, f"{len(bad)} violations"))
    rep = int(ok["repeated_destination_receptions"].fillna(0).sum())
    checks.append(_check("No repeated destination receptions (duplicate suppression)", rep == 0, f"total {rep}"))
    by_scen = ok.groupby("scenario_id").agg(h=("scenario_hash", "nunique"), g=("generated_messages", "nunique"))
    bad_scen = by_scen[(by_scen["h"] > 1) | (by_scen["g"] > 1)]
    checks.append(_check("Identical inputs across algorithms within each scenario", bad_scen.empty,
                         f"{len(by_scen)} scenarios; {len(bad_scen)} inconsistent"))
    complete = ok.groupby("configuration_id")["seed"].nunique()
    incomplete = complete[complete < len(d.seeds)]
    checks.append(_check("Every configuration has all phase seeds", incomplete.empty,
                         f"{len(incomplete)} incomplete configurations", severity="WARN"))
    if not d.validation.empty:
        integ = d.validation[[c for c in d.validation.columns if c.startswith("integrity_")
                              and c != "integrity_max_step_displacement_m"]].to_numpy().sum()
        checks.append(_check("Mobility integrity (venue, stationary, speed)", integ == 0,
                             f"total violations {int(integ)}"))
        if "workload_fallback_share" in d.validation:
            prim = d.validation[d.validation["workload_type"] == "separated_friends"]
            fb = prim["workload_fallback_share"].max() if not prim.empty else np.nan
            checks.append(_check("Primary workload fallback share <= 5 %", bool(fb <= 0.05) if fb == fb else None,
                                 f"max fallback share {fb:.3f}" if fb == fb else "no primary workload",
                                 severity="WARN"))
    ages_ok = (ok["generated_messages"] > 0).all()
    checks.append(_check("Every run generated messages", bool(ages_ok), f"min {ok['generated_messages'].min()}"))
    return checks


def primary_validation(d: PhaseData) -> pd.DataFrame:
    """Validation rows of the primary scenario only (exploratory X3/X4 scenarios excluded)."""
    v = d.validation
    if v.empty:
        return v
    cfg = d.cfg
    keep = pd.Series(True, index=v.index)
    for col, val in (("workload_type", "separated_friends"), ("communication_radius_m", cfg["communication"]["radius_m"]),
                     ("mean_interarrival_s", cfg["traffic"]["mean_interarrival_s"]),
                     ("min_separation_s", cfg["mobility"]["min_separation_s"]),
                     ("rejoin_policy", cfg["mobility"]["rejoin_policy"])):
        if col in v:
            keep &= v[col] == val
    return v[keep]


def failed_runs_table(d: PhaseData) -> pd.DataFrame:
    cols = ["run_id", "configuration_id", "algorithm", "variant", "seed", "node_count", "error_message"]
    failed = d.runs[d.runs["run_status"] != "ok"]
    return failed[[c for c in cols if c in failed.columns]]


def missing_runs_table(d: PhaseData) -> pd.DataFrame:
    if d.plan.empty:
        return pd.DataFrame(columns=["run_id"])
    return d.plan[~d.plan["run_id"].isin(d.runs["run_id"])]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
