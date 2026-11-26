"""Automated Markdown findings report, key findings and LaTeX tables.

Every number is read from the analysis results of the phase; nothing is
hard-coded and no conclusion is favourable by default. Each statement is
labelled with its evidential status:

* observed descriptive difference - a difference in sample means, no inference;
* statistically supported - a confirmatory test rejected its null after Holm;
* non-inferiority established / not established - H2 wording;
* inconclusive - test not computable or data incomplete;
* negative finding - observed difference opposite to the hypothesised direction;
* exploratory - unadjusted, not confirmatory evidence;
* pilot - descriptive only, no confirmatory decision.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import numpy as np
import pandas as pd

from experiments.provenance import provenance_record

from .data import DENSITIES, E1_ALGORITHMS, failed_runs_table, missing_runs_table
from .descriptive import compact_table
from .hypothesis_tests import PILOT_DECISION
from .tables import latex_table, md_table

LIMITATIONS = [
    "The mobility model and venue layout are synthetic; they are not based on a measured venue.",
    "Nodes represent participating smartphones, not all attendees; densities are relative, not crowd densities.",
    "Radio communication is abstracted and idealised (unit-disc range, no interference, no connection setup, "
    "no OS background restrictions); it is not a Bluetooth, Wi-Fi Direct or Nearby Connections model.",
    "Motion classification is simulated (independent or bursty flips), not derived from real sensors.",
    "Friend groups are synthetic; survey respondents are not simulation nodes and survey data are not used as targets.",
    "Completed transfers are an activity indicator only; they are not battery consumption, discovery energy, "
    "control overhead or interference.",
    "Results cannot automatically be generalised to real festivals; there is no Android validation.",
    "MWS is not claimed to be the first mobility-aware algorithm; no unimplemented published algorithm is compared.",
    "The historical-motion variant is an internal controlled ablation, not a reproduction of Kawecki & Schoeneich.",
    "Separated group members rejoin physically within the model, so many separated pairs are reunited within a "
    "message lifetime; this bounds achievable D15 differences.",
    "With an equal copy budget, BSW and MWS normally distribute all tokens within the lifetime, so transfer "
    "counts (T) can be structurally identical; a lower T would not prove lower energy use.",
    "Exploratory results (E2, E3, E5, E6 and optional extensions) are not confirmatory evidence.",
]

OBJECTIVE_MAP = [
    ("O3 / RQ2", "E1 (all four algorithms across densities)", "Sections 5-6 and figures 1-6"),
    ("O4 / RQ3", "H1 (D5, MWS vs BSW at equal budget)", "Section 13, figure 7"),
    ("O4 / RQ4", "H2 (D15 non-inferiority) and H3 (transfers)", "Section 13, figures 2, 3, 7"),
    ("O5 / RQ5", "H4 (density), E2 (budget), E3 (rules), E5 (classification errors), E6 (workload)",
     "Sections 7-12, figures 8, 9, 11, 12"),
    ("O6 / RQ6", "H5 (immediate vs historical motion), limitations", "Sections 10 and 16, figure 10"),
]


def _f(x, digits: int = 2) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return f"{x:.{digits}f}"


def _p(x) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "n/a"
    return "<0.001" if x < 0.001 else f"{x:.3f}"


# --------------------------------------------------------------------------- key findings
def key_findings(res: dict) -> pd.DataFrame:
    d = res["data"]
    phase = d.phase
    rows = []
    e1 = res["e1"]["d5_percent"]
    for n in DENSITIES:
        sub = e1[e1.node_count == n].set_index("algorithm")
        if {"BSW", "MWS"} <= set(sub.index) and sub.loc["BSW", "n"] and sub.loc["MWS", "n"]:
            rows.append({"category": "observed descriptive difference", "source": f"E1, {n} nodes",
                         "finding": f"Mean D5: BSW {_f(sub.loc['BSW', 'mean'], 1)} %, MWS {_f(sub.loc['MWS', 'mean'], 1)} %, "
                                    f"Epidemic {_f(sub.loc['Epidemic', 'mean'], 1)} %, Direct "
                                    f"{_f(sub.loc['DirectDelivery', 'mean'], 1)} % (n = {int(sub.loc['MWS', 'n'])} seeds)."})
    fam = res["confirmatory"]["family"]
    for _, r in fam.iterrows():
        if phase == "confirmatory":
            cat = r["result_category"]
        else:
            cat = "pilot - descriptive only"
        est = (f"mean difference {_f(r.get('mean_diff'))} (95% CI {_f(r.get('ci95_low'))} to {_f(r.get('ci95_high'))}), "
               if r["hypothesis"] != "H4" else
               f"density means of dD5: {res['confirmatory']['h4']['density_means']}, ")
        flag = " All paired differences identical (zero variance)." if r.get("degenerate_zero_variance") is True else ""
        rows.append({"category": cat, "source": r["hypothesis"],
                     "finding": f"{r['title']}: {est}raw p {_p(r['p_raw'])}, Holm p {_p(r['p_holm'])}, n = "
                                f"{int(r['n']) if r['n'] == r['n'] else 'n/a'}. Decision: {r['decision']}.{flag}"})
    # Structural observations detected from data (not asserted a priori).
    t = res["e1"]["transfers_per_message"]
    bsw_t, mws_t = t[t.algorithm == "BSW"]["mean"].to_numpy(), t[t.algorithm == "MWS"]["mean"].to_numpy()
    if bsw_t.size and np.allclose(bsw_t, mws_t, atol=0.01):
        rows.append({"category": "observed descriptive difference", "source": "E1",
                     "finding": "Transfers per message are (near-)identical for BSW and MWS at every density "
                                f"(BSW {', '.join(_f(v) for v in bsw_t)}; MWS {', '.join(_f(v) for v in mws_t)}), "
                                "consistent with both algorithms spending the same copy budget."})
    d15 = res["e1"]["d15_percent"]
    ceiling = d15[d15.algorithm.isin(["BSW", "MWS"])]["mean"]
    if ceiling.size and (ceiling >= 99).all():
        rows.append({"category": "observed descriptive difference", "source": "E1",
                     "finding": f"D15 is at or near ceiling for BSW and MWS (all means >= 99 %); D15 therefore has "
                                "little room to discriminate between them in this scenario."})
    ex = res["exploratory"]
    for _, r in ex[ex.metric == "d5_percent"].iterrows():
        if r["experiment"] in ("E2", "E3", "E5", "E6", "E4") and r["n"] >= 2:
            rows.append({"category": "exploratory", "source": r["experiment"],
                         "finding": f"{r['comparison']}: dD5 {_f(r['mean_diff'])} pp (95% CI {_f(r['ci95_low'])} to "
                                    f"{_f(r['ci95_high'])}; unadjusted p {_p(r['p_two_sided_unadjusted'])})."})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- report
def _config_table(cfg: dict) -> pd.DataFrame:
    sim, tr, comm, mob, rt, st = (cfg["simulation"], cfg["traffic"], cfg["communication"], cfg["mobility"],
                                  cfg["routing"], cfg["statistics"])
    items = [
        ("Venue", f"{cfg['venue']['width_m']} x {cfg['venue']['height_m']} m, 5 zones"),
        ("Duration / warm-up / step", f"{sim['duration_s']} s / {sim['warmup_s']} s / {sim['time_step_s']} s"),
        ("Message generation", f"{tr['generation_start_s']} <= t < {tr['generation_end_s']} s, mean interval "
                               f"{tr['mean_interarrival_s']} s"),
        ("Lifetime / D5 threshold", f"{tr['message_lifetime_s']} s / {cfg['metrics']['d5_threshold_s']} s"),
        ("Radius / capacity", f"{comm['radius_m']} m / {comm['transfer_capacity_per_node_per_s']} transfers/node/s"),
        ("Buffer", f"{cfg['buffer']['capacity_messages']} messages, {cfg['buffer']['drop_policy']}"),
        ("Copy budget (primary)", str(rt["copy_budget"])),
        ("MWS fallback", f"{rt['mws']['fallback_s']} s"),
        ("Walking speed", f"{mob['speed_min_mps']}-{mob['speed_max_mps']} m/s"),
        ("Groups", f"{mob['group_participation']:.0%} participation, sizes {mob['group_size_min']}-{mob['group_size_max']}"),
        ("Separation", f"hazard {mob['separation_hazard_per_s']:.6f}/s, minimum {mob['min_separation_s']} s, "
                       f"rejoin policy {mob['rejoin_policy']}"),
        ("Seeds", f"{cfg['seeds'][0]}-{cfg['seeds'][-1]} ({len(cfg['seeds'])})"),
        ("alpha / H2 margin / bootstrap", f"{st['alpha']} / {st['h2_noninferiority_margin_pp']} pp / "
                                          f"{st['bootstrap_resamples']} resamples (seed {st['bootstrap_seed']})"),
        ("H4 model", st["h4_model"]),
    ]
    return pd.DataFrame(items, columns=["parameter", "value"])


def _experiment_status(d) -> pd.DataFrame:
    rows = []
    planned_ids = set(d.plan["configuration_id"]) if not d.plan.empty else set()
    for exp in sorted(d.matrix["experiment_id"].unique()):
        ids = set(d.matrix[d.matrix["experiment_id"] == exp]["configuration_id"])
        runs = d.runs[d.runs["configuration_id"].isin(ids)]
        in_plan = ids & planned_ids
        if not in_plan:
            rows.append({"experiment": exp, "configurations": len(ids), "planned runs": 0, "ok": 0, "failed": 0,
                         "missing": 0, "note": "not executed (optional extension, not in this batch)"})
            continue
        planned = len(in_plan) * len(d.seeds)
        note = "" if in_plan == ids else f"{len(ids - in_plan)} optional configuration(s) not in this batch"
        rows.append({"experiment": exp, "configurations": len(ids), "planned runs": planned,
                     "ok": int((runs["run_status"] == "ok").sum()), "failed": int((runs["run_status"] != "ok").sum()),
                     "missing": planned - int(runs["configuration_id"].isin(in_plan).sum()), "note": note})
    return pd.DataFrame(rows)


def _e1_table(res: dict) -> pd.DataFrame:
    rows = []
    for n in DENSITIES:
        for alg in E1_ALGORITHMS:
            row = {"nodes": n, "algorithm": alg}
            for key, label, dg in (("d5_percent", "D5 %", 1), ("d15_percent", "D15 %", 1),
                                   ("transfers_per_message", "T", 2), ("median_latency_s", "median latency s", 0),
                                   ("buffer_drops", "buffer drops", 0)):
                s = res["e1"][key]
                r = s[(s.node_count == n) & (s.algorithm == alg)].iloc[0]
                row[label] = f"{_f(r['mean'], dg)} [{_f(r['ci_low'], dg)}, {_f(r['ci_high'], dg)}]" if r["n"] else "missing"
            rows.append(row)
    return pd.DataFrame(rows)


def _hyp_table(res: dict) -> pd.DataFrame:
    fam = res["confirmatory"]["family"]
    out = []
    for _, r in fam.iterrows():
        out.append({"H": r["hypothesis"], "test": r["test"], "n": int(r["n"]) if r["n"] == r["n"] else None,
                    "mean diff": _f(r.get("mean_diff")), "SD": _f(r.get("sd")), "dz": _f(r.get("dz")),
                    "95% CI": f"{_f(r.get('ci95_low'))} to {_f(r.get('ci95_high'))}",
                    "bootstrap 95% CI": f"{_f(r.get('boot_ci_low'))} to {_f(r.get('boot_ci_high'))}",
                    "p raw": _p(r["p_raw"]), "p Holm": _p(r["p_holm"]), "decision": r["decision"]})
    return pd.DataFrame(out)


def _exploratory_md(res: dict, exp: str, metrics=("d5_percent", "d15_percent", "transfers_per_message")) -> str:
    ex = res["exploratory"]
    sub = ex[(ex.experiment == exp) & (ex.metric.isin(metrics))]
    if sub.empty:
        return "_(no data)_"
    t = sub[["comparison", "metric", "n", "mean_diff", "ci95_low", "ci95_high", "p_two_sided_unadjusted"]].copy()
    t.columns = ["comparison", "metric", "n", "mean diff", "CI low", "CI high", "p (unadjusted)"]
    return md_table(t, digits=3)


def write_report(res: dict, path: Path) -> Path:
    d = res["data"]
    phase = d.phase
    prov = provenance_record()
    fam = res["confirmatory"]["family"]
    h4 = res["confirmatory"]["h4"]
    L = []
    add = L.append
    add(f"# LinkUp Research Simulator - findings report ({phase})")
    add("")
    add(f"Generated {_dt.datetime.now().isoformat(timespec='seconds')} from `results/{phase}/processed/`. "
        f"Code version `{prov['code_version']}`.")
    if phase != "confirmatory":
        add("")
        add(f"> **{phase.upper()} DATA ({len(d.seeds)} seeds). This report verifies the pipeline and informs the "
            "repetition count. It contains no confirmatory decisions, and pilot results must not be used to tune "
            "MWS or any model parameter.**")
    add("")
    add("Evidence labels: *observed descriptive difference* (sample means only), *statistically supported* "
        "(confirmatory test, Holm-adjusted), *non-inferiority established / not established*, *inconclusive*, "
        "*negative finding* (difference opposite to the hypothesis), *exploratory* (unadjusted).")
    add("\n## 1. Research configuration\n")
    add(md_table(_config_table(d.cfg)))
    add("\n## 2. Completed and failed experiments\n")
    add(md_table(_experiment_status(d)))
    failed = failed_runs_table(d)
    missing = missing_runs_table(d)
    add(f"\nFailed runs: {len(failed)}. Missing runs: {len(missing)}.")
    if len(failed):
        add(md_table(failed))
    add("\n## 3. Data-quality checks\n")
    add(md_table(pd.DataFrame(d.quality)))
    add("\n## 4. Mobility validation (algorithm independent)\n")
    if not d.validation.empty:
        v = d.validation[(d.validation.workload_type == "separated_friends") & (d.validation.communication_radius_m == 10)]
        cols = ["pct_time_walking", "walking_speed_realised_mean_mps", "avg_neighbours_per_node",
                "contact_events_per_node_per_hour", "contact_duration_median_s", "encounter_start_involving_walker_share",
                "separation_events_total", "separation_duration_mean_s", "mean_separated_members",
                "pct_generation_seconds_with_eligible_pair", "workload_fallback_share", "pairs_in_range_at_creation_share"]
        cols = [c for c in cols if c in v.columns]
        add(md_table(v.groupby("node_count")[cols].mean().T.reset_index().rename(columns={"index": "metric"}), 3))
        add("\nSee figure 15. Validation statistics were computed before and independently of routing results.")
    add("\n## 5. Algorithm performance (E1)\n")
    add("Mean [95% CI across seeds]. T = completed transfers per generated message (activity, not energy). "
        "Latency is for delivered messages only (selection bias); see the cumulative-delivery figure. "
        "t-based intervals are reported unclipped, so with few seeds they can extend beyond a metric's "
        "natural range (e.g. above 100 % or below 0); bootstrap intervals (section 14) are range-respecting.\n")
    add(md_table(_e1_table(res)))
    add("\n## 6. D5, D15 and transfer-efficiency findings (H1-H3)\n")
    for hid in ("H1", "H2", "H3"):
        r = fam[fam.hypothesis == hid].iloc[0]
        flag = " **All paired differences were identical (zero variance); the pre-specified degenerate-case rule " \
               "was applied.**" if r.get("degenerate_zero_variance") is True else ""
        add(f"- **{hid}** ({r['title']}): mean of density-averaged paired differences {_f(r['mean_diff'], 3)} "
            f"(SD {_f(r['sd'], 3)}, n = {int(r['n'])}), 95% CI {_f(r['ci95_low'], 3)} to {_f(r['ci95_high'], 3)}, "
            f"{r['bound_type']} bound {_f(r['one_sided_bound'], 3)}; raw p {_p(r['p_raw'])}, Holm p "
            f"{_p(r['p_holm'])}. Decision: *{r['decision']}*. Status: {r['result_category']}.{flag}")
    sec = res["secondary"]
    add("\nDensity-specific follow-ups (secondary Holm family):\n")
    s2 = sec[["hypothesis", "n", "mean_diff", "sd", "ci95_low", "ci95_high", "p_raw", "p_holm_secondary", "decision"]]
    add(md_table(s2, 3))
    add("\n## 7. Density effects (H4)\n")
    add(f"Primary model: {h4['primary_test']} on per-seed dD5 at 50/100/200 nodes. Density means (pp): "
        f"{ {k: round(v, 3) for k, v in h4['density_means'].items()} }; SDs: "
        f"{ {k: round(v, 3) for k, v in h4['density_sd'].items()} }.")
    add(f"Welch F = {_f(h4['welch']['F'], 3)} (df {_f(h4['welch']['df1'], 1)}, {_f(h4['welch']['df2'], 1)}), "
        f"p = {_p(h4['welch']['p'])}; eta^2 = {_f(h4.get('eta_sq'), 3)}. Sensitivity: Kruskal-Wallis p = "
        f"{_p(h4.get('kruskal_p'))}; RM-ANOVA (GG eps = {_f(h4['rm_anova'].get('gg_epsilon'), 3)}) p = "
        f"{_p(h4['rm_anova'].get('p_gg'))}; Friedman p = {_p(h4.get('friedman_p'))}.")
    r4 = fam[fam.hypothesis == "H4"].iloc[0]
    add(f"\nHolm p = {_p(r4['p_holm'])}. Decision: *{r4['decision']}*. Density differences are tested directly; "
        "no interaction is inferred from separate per-density significance.")
    if h4.get("pairwise"):
        add("\n" + md_table(pd.DataFrame(h4["pairwise"]), 3))
    add("\n## 8. Copy budget (E2, exploratory)\n")
    add(md_table(compact_table(res["summaries"]["E2"], ["d5_percent", "d15_percent", "transfers_per_message"])))
    add("\n" + _exploratory_md(res, "E2"))
    add("\n## 9. Ablation (E3, exploratory)\n")
    add(md_table(compact_table(res["summaries"]["E3"], ["d5_percent", "d15_percent", "transfers_per_message",
                                                        "median_latency_s"])))
    add("\n" + _exploratory_md(res, "E3"))
    tr_cols = [c for c in d.ok.columns if c.startswith("transfers_MWS_")]
    if tr_cols:
        e3_ids = d.arms("E3")
        tr = []
        for _, arm in e3_ids.iterrows():
            runs = d.runs_for(arm["configuration_id"])
            tr.append({"variant": arm["arm_label"], **{c.replace("transfers_", ""): runs[c].mean() for c in tr_cols}})
        add("\nMean completed relay transfers per run by the MWS rule that permitted them:\n")
        add(md_table(pd.DataFrame(tr), 1))
    add("\n## 10. Motion comparison (E4 / H5)\n")
    r5 = fam[fam.hypothesis == "H5"].iloc[0]
    add(f"Immediate minus historical (300 s window) D5 at 100 nodes: mean {_f(r5['mean_diff'], 3)} pp "
        f"(SD {_f(r5['sd'], 3)}, n = {int(r5['n'])}), 95% CI {_f(r5['ci95_low'], 3)} to {_f(r5['ci95_high'], 3)}, "
        f"bootstrap CI {_f(r5['boot_ci_low'], 3)} to {_f(r5['boot_ci_high'], 3)}; raw p {_p(r5['p_raw'])}, Holm p "
        f"{_p(r5['p_holm'])}. Decision: *{r5['decision']}*. The two variants differ only in the motion signal.")
    add("\n" + _exploratory_md(res, "E4"))
    add("\n## 11. Robustness to classification errors (E5, exploratory)\n")
    add(md_table(compact_table(res["summaries"]["E5"], ["d5_percent", "d15_percent", "transfers_per_message"])))
    add("\n" + _exploratory_md(res, "E5", ("d5_percent",)))
    add("\n## 12. Generalisation (E6, exploratory)\n")
    add(md_table(compact_table(res["summaries"]["E6"], ["d5_percent", "d15_percent", "transfers_per_message"])))
    add("\n" + _exploratory_md(res, "E6", ("d5_percent", "d15_percent")))
    wi = res["workload_interaction"]
    add(f"\nDifference-in-differences (random minus separated-friends workload) of dD5: {_f(wi['mean_diff'], 3)} pp, "
        f"95% CI {_f(wi['ci95_low'], 3)} to {_f(wi['ci95_high'], 3)}, unadjusted p {_p(wi['p_raw'])} (exploratory).")
    add("\n## 13. Hypothesis results (confirmatory family, Holm across H1-H5)\n")
    add(md_table(_hyp_table(res)))
    if phase != "confirmatory":
        add(f"\nDecision column reads '{PILOT_DECISION}' because these are pilot data.")
    add("\n## 14. Effect sizes and confidence intervals\n")
    es = fam[["hypothesis", "mean_diff", "median_diff", "sd", "dz", "ci95_low", "ci95_high", "boot_ci_low",
              "boot_ci_high", "one_sided_bound", "holm_level", "one_sided_bound_holm_level", "shapiro_p",
              "wilcoxon_p", "outliers_robust_z"]].copy()
    add(md_table(es, 3))
    add("\ndz = standardised mean paired difference (mean/SD). Bootstrap CIs resample complete seed blocks "
        f"({d.cfg['statistics']['bootstrap_resamples']} resamples). Shapiro-Wilk and Wilcoxon are assumption/"
        "sensitivity checks only; the Wilcoxon test is not a test of the mean.")
    add("\n## 15. Computational performance\n")
    rt = res["e1"]["runtime_s"]
    add(md_table(rt.pivot(index="algorithm", columns="node_count", values="mean").reset_index(), 3))
    add("\nMean routing wall-clock seconds per run (excluding shared scenario generation).")
    if phase != "confirmatory" and not res["sample_size"].empty:
        add("\n## Pilot: repetition-count assessment\n")
        add("Required seeds for 80% power (one-sided paired t-test) for candidate target effects. Target effects "
            "are researcher choices, not calibrated values; the 5-seed SD is imprecise, so an 80% upper confidence "
            "limit of the SD is also shown. 'mde_pp_at_n30' is the minimal detectable effect with 30 seeds.\n")
        add(md_table(res["sample_size"], 2))
    add("\n## 16. Limitations\n")
    for item in LIMITATIONS:
        add(f"- {item}")
    add("\n## 17. Mapping of findings to objectives\n")
    add(md_table(pd.DataFrame(OBJECTIVE_MAP, columns=["objective / question", "evidence", "where"])))
    add("\n## Key findings (auto-generated, labelled)\n")
    for _, k in key_findings(res).iterrows():
        add(f"- [{k['category']}] {k['source']}: {k['finding']}")
    add("\n## Figures\n")
    for f in res.get("figures", []):
        add(f"- `{f['png']}` - {f['title']}: {f['caption']}")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------- LaTeX
def write_latex_tables(res: dict, path: Path) -> Path:
    phase = res["data"].phase
    note = "" if phase == "confirmatory" else f" ({phase} data, not confirmatory)"
    parts = [f"% Auto-generated from results/{phase}/processed - do not edit by hand.",
             latex_table(_e1_table(res), f"Algorithm performance by density (mean [95% CI]){note}", "tab:e1"),
             latex_table(_hyp_table(res).drop(columns=["test"]), f"Confirmatory hypothesis tests{note}", "tab:hyp")]
    for exp, metrics in (("E2", ["d5_percent", "transfers_per_message"]), ("E3", ["d5_percent", "d15_percent"]),
                         ("E5", ["d5_percent"]), ("E6", ["d5_percent", "d15_percent"])):
        if exp in res["summaries"]:
            parts.append(latex_table(compact_table(res["summaries"][exp], metrics),
                                     f"{exp} summary, mean (SD){note}", f"tab:{exp.lower()}"))
    path.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    return path
