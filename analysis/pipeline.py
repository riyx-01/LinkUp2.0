"""Analysis pipeline: data quality -> descriptives -> tests -> figures -> exports.

``analyze`` writes statistical tables (CSV/JSON) and figures; ``export``
additionally writes the master Excel workbook, the Markdown findings report and
LaTeX tables. All numbers come from the processed run tables of the phase.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import diagnostics as dg
from . import hypothesis_tests as ht
from .data import load_phase
from .descriptive import KEY_METRICS, e1_summary, experiment_summary

EXPERIMENTS = ("E1", "E2", "E3", "E4", "E5", "E6")


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, pd.DataFrame):
        return obj.reset_index().to_dict(orient="records")
    return obj


def run_analysis(phase: str, root: Path | None = None) -> dict:
    d = load_phase(phase, root)
    proc = d.root / "processed"
    res: dict = {"data": d}
    res["summaries"] = {e: experiment_summary(d, e) for e in EXPERIMENTS if not d.arms(e).empty}
    res["e1"] = {m: e1_summary(d, m) for m in ("d2_percent", "d5_percent", "d15_percent", "transfers_per_message",
                                              "median_latency_s", "p90_latency_s", "buffer_drops", "runtime_s",
                                              "intermediate_transfers_per_message", "expired_replicas")}
    res["confirmatory"] = ht.confirmatory_family(d)
    res["secondary"] = ht.secondary_family(d)
    res["exploratory"] = ht.exploratory_comparisons(d)
    res["workload_interaction"] = ht.workload_interaction(d)
    # Sample-size assessment is a planning tool: computed only for pilot/development data. On confirmatory data
    # it would be post-hoc power, which must not be used to judge or extend the study.
    res["sample_size"] = ht.sample_size_assessment(d) if d.phase != "confirmatory" else pd.DataFrame()
    res["efficiency"] = dg.efficiency_table(d)
    res["efficiency_compact"] = dg.per_density_efficiency(d)
    res["rules"] = dg.rule_table(d)
    res["workload_diag"] = dg.workload_table(d)
    res["sensitivity"] = dg.sensitivity_table(d)
    for key, name in (("efficiency", "efficiency_metrics"), ("rules", "rule_diagnostics"),
                      ("workload_diag", "workload_diagnostics"), ("sensitivity", "sensitivity_X1_X4")):
        res[key].to_csv(proc / f"{name}.csv", index=False)

    for e, s in res["summaries"].items():
        s.to_csv(proc / f"summary_{e}.csv", index=False)
    fam = res["confirmatory"]["family"].copy()
    fam["missing_pairs"] = fam["missing_pairs"].astype(str)
    fam.to_csv(proc / "hypothesis_tests.csv", index=False)
    sec = res["secondary"].copy()
    sec["missing_pairs"] = sec["missing_pairs"].astype(str)
    sec.to_csv(proc / "secondary_tests.csv", index=False)
    res["exploratory"].to_csv(proc / "exploratory_tests.csv", index=False)
    res["sample_size"].to_csv(proc / "sample_size_assessment.csv", index=False)
    for key, frame in res["confirmatory"]["per_seed"].items():
        frame.to_csv(proc / f"paired_differences_{key}.csv", index=key in ("H1", "H2", "H3", "H4"))
    (proc / "h4_details.json").write_text(json.dumps(_jsonable(res["confirmatory"]["h4"]), indent=1),
                                          encoding="utf-8")
    pd.DataFrame(d.quality).to_csv(proc / "data_quality.csv", index=False)
    return res


def analyze_phase(phase: str, export: bool = False, root: Path | None = None) -> dict:
    from .visualizations import make_all_figures

    res = run_analysis(phase, root)
    d = res["data"]
    print(f"[{phase}] data quality:")
    for q in d.quality:
        print(f"  {q['status']:4s} {q['check']}: {q['detail']}")
    res["figures"] = make_all_figures(d, d.root / "figures")
    print(f"  {len(res['figures'])} figures -> {d.root / 'figures'}")
    fam = res["confirmatory"]["family"]
    for _, r in fam.iterrows():
        flag = " [zero variance]" if r.get("degenerate_zero_variance") is True else ""
        print(f"  {r['hypothesis']}: mean diff {r.get('mean_diff', float('nan')):.3f}, p_raw {r['p_raw']:.4g}, "
              f"p_holm {r['p_holm']:.4g} -> {r['decision']}{flag}")
    if export:
        from .export_excel import write_workbook
        from .research_summary import write_latex_tables, write_report

        reports = d.root / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        res["workbook"] = write_workbook(res, reports / "LinkUp_Master_Experimental_Data_Analysis.xlsx")
        res["report"] = write_report(res, reports / "findings_report.md")
        res["latex"] = write_latex_tables(res, reports / "tables.tex")
        print(f"  exports -> {reports}")
    return res


__all__ = ["analyze_phase", "run_analysis", "KEY_METRICS"]
