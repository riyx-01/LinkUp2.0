"""Confirmatory hypothesis tests (H1-H5), secondary and exploratory families.

Pre-specified plan (docs/statistical_analysis_plan.md):

* Unit of analysis: one (scenario, seed) run; MWS and BSW are paired by seed
  within the same scenario. Messages are never treated as replicates.
* H1-H3 overall: for each master seed the MWS-BSW difference is computed at
  each density and the **equally weighted mean of the three density
  differences** forms the observation (complete blocks only).
* H1: one-sided paired t-test, mean dD5 > 0.
* H2: one-sided paired non-inferiority t-test, mean dD15 > -delta
  (delta = 5 pp, configurable); decision from the Holm-adjusted p-value with
  the matching one-sided confidence bound reported.
* H3: one-sided paired t-test, mean dT < 0.
* H4: does dD5 differ across densities? Primary model chosen in the config
  (``independent_groups_welch``: Welch one-way ANOVA, because density-specific
  RNG streams make density blocks statistically independent; or
  ``repeated_measures_gg``). Sensitivity: Kruskal-Wallis, RM-ANOVA with
  Greenhouse-Geisser correction, Friedman.
* H5: one-sided paired t-test at 100 nodes, D5(immediate) - D5(historical) > 0.
* Holm correction across the five confirmatory tests; density-specific H1-H3
  follow-ups form a separate secondary Holm family; everything else is
  exploratory (unadjusted, labelled).
* Wilcoxon signed-rank is reported as a sensitivity analysis only (it is not a
  test of the mean) and never used to choose a result.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.oneway import anova_oneway
from statsmodels.stats.power import TTestPower

from .confidence_intervals import bootstrap_ci, one_sided_bound, t_interval
from .data import DENSITIES, PhaseData

REJECT = "Reject the null hypothesis"
FAIL_TO_REJECT = "Fail to reject the null hypothesis"
NI_ESTABLISHED = "Non-inferiority established"
NI_NOT_ESTABLISHED = "Non-inferiority not established"
INCONCLUSIVE = "Evidence is statistically inconclusive"
ALLOWED_DECISIONS = (REJECT, FAIL_TO_REJECT, NI_ESTABLISHED, NI_NOT_ESTABLISHED, INCONCLUSIVE)
PILOT_DECISION = "Not applicable - pilot data (no confirmatory decision)"


# --------------------------------------------------------------------------- #
# Pairing
# --------------------------------------------------------------------------- #
def paired_frame(d: PhaseData, cfg_a: str | None, cfg_b: str | None, metric: str) -> tuple[pd.DataFrame, list]:
    """Seed-paired values of ``metric`` for configs a and b; diff = a - b."""
    a = d.runs_for(cfg_a).set_index("seed")[metric]
    b = d.runs_for(cfg_b).set_index("seed")[metric]
    expected = set(d.seeds)
    common = sorted(s for s in expected if s in a.index and s in b.index
                    and not (pd.isna(a.get(s)) or pd.isna(b.get(s))))
    missing = sorted(expected - set(common))
    frame = pd.DataFrame({"seed": common, "a": [float(a[s]) for s in common],
                          "b": [float(b[s]) for s in common]})
    frame["diff"] = frame["a"] - frame["b"]
    return frame, missing


def density_differences(d: PhaseData, metric: str, alg_a: str = "MWS", alg_b: str = "BSW",
                        densities=DENSITIES) -> tuple[pd.DataFrame, dict]:
    """Wide (seed x density) table of E1 paired differences; missing seeds per density."""
    cols, missing = {}, {}
    for n in densities:
        frame, miss = paired_frame(d, d.e1_config(alg_a, n), d.e1_config(alg_b, n), metric)
        cols[n] = frame.set_index("seed")["diff"]
        missing[n] = miss
    wide = pd.DataFrame(cols)
    wide.index.name = "seed"
    return wide, missing


# --------------------------------------------------------------------------- #
# Single-sample machinery
# --------------------------------------------------------------------------- #
def one_sample_test(diffs, alternative: str = "greater", null_value: float = 0.0, alpha: float = 0.05) -> dict:
    x = np.asarray(diffs, dtype=float)
    x = x[~np.isnan(x)]
    n = int(x.size)
    res = {"n": n, "mean_diff": float(x.mean()) if n else np.nan,
           "median_diff": float(np.median(x)) if n else np.nan,
           "sd": float(x.std(ddof=1)) if n > 1 else np.nan, "null_value": null_value,
           "alternative": alternative}
    res["se"] = res["sd"] / np.sqrt(n) if n > 1 else np.nan
    res["dz"] = (res["mean_diff"] - null_value) / res["sd"] if n > 1 and res["sd"] > 0 else np.nan
    computable = n >= 2 and res["sd"] > 0
    res["computable"] = bool(computable)
    res["degenerate_zero_variance"] = bool(n >= 2 and res["sd"] == 0)
    if res["degenerate_zero_variance"]:
        # Every paired difference is identical: the t statistic and its p-value are undefined. The test
        # is flagged as NOT computable (decision: "Evidence is statistically inconclusive"). No p-value
        # is assigned; the observed difference, n and the zero-variance condition are reported instead.
        # Any alternative inferential procedure needs researcher approval before use (see the SAP).
        res.update({"t": np.nan, "df": n - 1, "p_raw": np.nan, "computable": False,
                    "zero_variance_value": res["mean_diff"]})
    elif computable:
        t = (res["mean_diff"] - null_value) / res["se"]
        df = n - 1
        if alternative == "greater":
            p = stats.t.sf(t, df)
        elif alternative == "less":
            p = stats.t.cdf(t, df)
        else:
            p = 2 * stats.t.sf(abs(t), df)
        res.update({"t": float(t), "df": df, "p_raw": float(p)})
    else:
        res.update({"t": np.nan, "df": n - 1 if n else np.nan, "p_raw": np.nan})
    res["ci95_low"], res["ci95_high"] = t_interval(x, 0.95)
    if alternative == "greater":
        res["one_sided_bound"] = one_sided_bound(x, alpha, "lower")
        res["bound_type"] = f"lower {100 * (1 - alpha):.0f}% one-sided"
    elif alternative == "less":
        res["one_sided_bound"] = one_sided_bound(x, alpha, "upper")
        res["bound_type"] = f"upper {100 * (1 - alpha):.0f}% one-sided"
    else:
        res["one_sided_bound"], res["bound_type"] = np.nan, ""
    res.update(assumption_checks(x, null_value, alternative))
    return res


def assumption_checks(x: np.ndarray, null_value: float = 0.0, alternative: str = "two-sided") -> dict:
    out = {"shapiro_p": np.nan, "skewness": np.nan, "excess_kurtosis": np.nan, "outliers_robust_z": 0,
           "wilcoxon_p": np.nan}
    n = x.size
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if n >= 3 and np.ptp(x) > 0:
            out["shapiro_p"] = float(stats.shapiro(x).pvalue)
            out["skewness"] = float(stats.skew(x))
            out["excess_kurtosis"] = float(stats.kurtosis(x))
        if n >= 1:
            med = np.median(x)
            mad = np.median(np.abs(x - med))
            if mad > 0:
                out["outliers_robust_z"] = int(np.sum(np.abs(0.6745 * (x - med) / mad) > 3.5))
        shifted = x - null_value
        if n >= 2 and np.any(shifted != 0):
            try:
                out["wilcoxon_p"] = float(stats.wilcoxon(shifted, alternative=alternative).pvalue)
            except ValueError:
                pass
    return out


def holm(pvals: list[float], alpha: float) -> tuple[np.ndarray, np.ndarray]:
    """Holm-adjusted p-values and per-test step-down levels. NaN is treated as 1."""
    p = np.array([1.0 if (v is None or np.isnan(v)) else v for v in pvals], dtype=float)
    _, p_adj, _, _ = multipletests(p, alpha=alpha, method="holm")
    order = np.argsort(p, kind="stable")
    levels = np.empty(len(p))
    m = len(p)
    for rank, idx in enumerate(order):
        levels[idx] = alpha / (m - rank)
    return p_adj, levels


def decide(kind: str, p_adj: float, computable: bool, phase: str, alpha: float) -> str:
    if phase != "confirmatory":
        return PILOT_DECISION
    if not computable or np.isnan(p_adj):
        return INCONCLUSIVE
    if kind == "noninferiority":
        return NI_ESTABLISHED if p_adj < alpha else NI_NOT_ESTABLISHED
    return REJECT if p_adj < alpha else FAIL_TO_REJECT


def result_category(row: dict, phase: str) -> str:
    """Neutral classification used by the report (never 'supported' on sign alone)."""
    if phase != "confirmatory":
        return "pilot - descriptive only"
    dec = row["decision"]
    if dec in (REJECT, NI_ESTABLISHED):
        return "statistically supported"
    if dec == INCONCLUSIVE:
        return "inconclusive"
    direction = row.get("alternative")
    mean = row.get("mean_diff", np.nan)
    null = row.get("null_value", 0.0)
    if direction == "greater" and mean < null or direction == "less" and mean > null:
        return "not supported; observed difference opposite to the hypothesised direction (negative finding)"
    return "not statistically supported"


def structural_context(d: PhaseData, metric: str, densities=DENSITIES) -> str:
    """Data-derived explanation of ceiling / budget-exhaustion effects for D15 and T comparisons."""
    notes = []
    if metric == "d15_percent":
        means = [d.runs_for(d.e1_config(a, n))["d15_percent"].mean() for a in ("BSW", "MWS") for n in densities]
        means = [m for m in means if m == m]
        if means and min(means) >= 99.0:
            notes.append(f"Ceiling effect: mean D15 of BSW and MWS is {min(means):.2f}-{max(means):.2f} % at every "
                         "density, leaving almost no room for a difference.")
    if metric == "transfers_per_message":
        vals = []
        for a in ("BSW", "MWS"):
            for n in densities:
                runs = d.runs_for(d.e1_config(a, n))
                if not runs.empty and "intermediate_transfers_per_message" in runs:
                    L = runs["copy_budget"].iloc[0]
                    vals.append((runs["intermediate_transfers_per_message"].mean(), L))
        if vals and all(abs(v - (L - 1)) < 0.05 for v, L in vals):
            notes.append("Budget exhaustion: both bounded-copy algorithms create (almost) exactly L-1 relay "
                         "copies per message, so total transfers are fixed by the shared copy budget.")
    return " ".join(notes)


def zero_variance_note(res: dict) -> str:
    if not res.get("degenerate_zero_variance"):
        return ""
    return (f"All {res['n']} paired differences equal {res['mean_diff']:g}; the paired t statistic is undefined, "
            "so no p-value is reported and the test is statistically inconclusive.")


# --------------------------------------------------------------------------- #
# H4 density models
# --------------------------------------------------------------------------- #
def rm_anova_gg(wide: np.ndarray) -> dict:
    """One-way repeated-measures ANOVA with Greenhouse-Geisser correction."""
    y = np.asarray(wide, dtype=float)
    n, k = y.shape
    if n < 2 or k < 2:
        return {"F": np.nan, "df1": np.nan, "df2": np.nan, "p": np.nan, "gg_epsilon": np.nan, "p_gg": np.nan}
    grand = y.mean()
    ss_cond = n * np.sum((y.mean(axis=0) - grand) ** 2)
    ss_subj = k * np.sum((y.mean(axis=1) - grand) ** 2)
    ss_total = np.sum((y - grand) ** 2)
    ss_err = ss_total - ss_cond - ss_subj
    df1, df2 = k - 1, (k - 1) * (n - 1)
    if ss_err <= 0:
        return {"F": np.nan, "df1": df1, "df2": df2, "p": np.nan, "gg_epsilon": np.nan, "p_gg": np.nan}
    F = (ss_cond / df1) / (ss_err / df2)
    S = np.cov(y, rowvar=False)
    P = np.eye(k) - np.ones((k, k)) / k
    Sc = P @ S @ P
    eps = float(np.trace(Sc) ** 2 / ((k - 1) * np.trace(Sc @ Sc))) if np.trace(Sc @ Sc) > 0 else 1.0
    eps = min(max(eps, 1.0 / (k - 1)), 1.0)
    return {"F": float(F), "df1": df1, "df2": df2, "p": float(stats.f.sf(F, df1, df2)), "gg_epsilon": eps,
            "p_gg": float(stats.f.sf(F, eps * df1, eps * df2)),
            "partial_eta_sq": float(ss_cond / (ss_cond + ss_err))}


def h4_tests(wide: pd.DataFrame, model: str) -> dict:
    groups = [wide[c].dropna().to_numpy() for c in wide.columns]
    out = {"model": model, "density_means": {int(c): float(wide[c].mean()) for c in wide.columns},
           "density_sd": {int(c): float(wide[c].std(ddof=1)) for c in wide.columns},
           "density_n": {int(c): int(wide[c].notna().sum()) for c in wide.columns}}
    enough = all(len(g) >= 2 for g in groups) and len(groups) >= 2
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if enough and all(np.ptp(g) > 0 for g in groups):
            w = anova_oneway(groups, use_var="unequal", welch_correction=True)
            out["welch"] = {"F": float(w.statistic), "df1": float(w.df[0]), "df2": float(w.df[1]),
                            "p": float(w.pvalue)}
            allv = np.concatenate(groups)
            ss_b = sum(len(g) * (g.mean() - allv.mean()) ** 2 for g in groups)
            out["eta_sq"] = float(ss_b / np.sum((allv - allv.mean()) ** 2))
            out["kruskal_p"] = float(stats.kruskal(*groups).pvalue)
        else:
            out["welch"] = {"F": np.nan, "df1": np.nan, "df2": np.nan, "p": np.nan}
            out["eta_sq"], out["kruskal_p"] = np.nan, np.nan
        complete = wide.dropna()
        out["complete_blocks"] = int(len(complete))
        out["rm_anova"] = rm_anova_gg(complete.to_numpy())
        try:
            out["friedman_p"] = float(stats.friedmanchisquare(*[complete[c] for c in complete.columns]).pvalue) \
                if len(complete) >= 2 else np.nan
        except ValueError:
            out["friedman_p"] = np.nan
    if model == "repeated_measures_gg":
        out["primary_p"], out["primary_test"] = out["rm_anova"]["p_gg"], "RM-ANOVA (Greenhouse-Geisser)"
        out["computable"] = not np.isnan(out["primary_p"])
    else:
        out["primary_p"], out["primary_test"] = out["welch"]["p"], "Welch one-way ANOVA (independent groups)"
        out["computable"] = not np.isnan(out["primary_p"])
    # Pairwise density contrasts (secondary detail, Holm within this set).
    pairs = [(a, b) for i, a in enumerate(wide.columns) for b in wide.columns[i + 1:]]
    rows = []
    for a, b in pairs:
        ga, gb = wide[a].dropna(), wide[b].dropna()
        if len(ga) >= 2 and len(gb) >= 2 and (ga.std() > 0 or gb.std() > 0):
            r = stats.ttest_ind(ga, gb, equal_var=False)
            rows.append({"contrast": f"N={a} - N={b}", "mean_difference_pp": float(ga.mean() - gb.mean()),
                         "welch_t": float(r.statistic), "p_raw": float(r.pvalue)})
    if rows:
        p_adj, _ = holm([r["p_raw"] for r in rows], 0.05)
        for r, p in zip(rows, p_adj):
            r["p_holm"] = float(p)
    out["pairwise"] = rows
    return out


# --------------------------------------------------------------------------- #
# Confirmatory family
# --------------------------------------------------------------------------- #
def confirmatory_family(d: PhaseData) -> dict:
    st = d.cfg["statistics"]
    alpha, delta = float(st["alpha"]), float(st["h2_noninferiority_margin_pp"])
    B, bseed = int(st["bootstrap_resamples"]), int(st["bootstrap_seed"])
    rows, per_seed = [], {}

    def block_row(hid, title, metric, alternative, null_value, kind, label):
        wide, missing = density_differences(d, metric)
        complete = wide.dropna()
        blocks = complete.mean(axis=1)
        per_seed[hid] = complete.assign(block_mean=blocks)
        res = one_sample_test(blocks.to_numpy(), alternative, null_value, alpha)
        res["boot_ci_low"], res["boot_ci_high"] = bootstrap_ci(complete.to_numpy(), resamples=B, seed=bseed)
        res.update({"hypothesis": hid, "title": title, "metric": label, "comparison": "MWS - BSW",
                    "estimand": "mean over seeds of the equally weighted density-mean paired difference",
                    "kind": kind, "test": "one-sided paired t-test" if kind != "noninferiority"
                    else f"one-sided paired non-inferiority t-test (margin {delta:g} pp)",
                    "incomplete_blocks": int(len(wide) - len(complete)),
                    "missing_pairs": {int(k): v for k, v in missing.items()},
                    "zero_variance_note": zero_variance_note(res),
                    "structural_note": structural_context(d, metric)})
        rows.append(res)

    block_row("H1", "Timely delivery: MWS improves D5 over BSW", "d5_percent", "greater", 0.0, "superiority",
              "D5 (pp)")
    block_row("H2", "Reliability: MWS D15 non-inferior to BSW", "d15_percent", "greater", -delta,
              "noninferiority", "D15 (pp)")
    block_row("H3", "Transfer efficiency: MWS reduces T vs BSW", "transfers_per_message", "less", 0.0,
              "superiority", "T (transfers/message)")

    wide5, _ = density_differences(d, "d5_percent")
    per_seed["H4"] = wide5
    h4 = h4_tests(wide5, st.get("h4_model", "independent_groups_welch"))
    rows.append({"hypothesis": "H4", "title": "Density effect: the 5-min benefit differs across densities",
                 "metric": "dD5 by density (pp)", "comparison": "MWS - BSW across 50/100/200 nodes",
                 "estimand": "difference in mean dD5 between densities", "kind": "omnibus",
                 "test": h4["primary_test"], "alternative": "two-sided", "null_value": 0.0,
                 "n": int(wide5.notna().sum().sum()), "mean_diff": np.nan,
                 "p_raw": h4["primary_p"], "computable": h4["computable"],
                 "effect_size": h4.get("eta_sq"), "kruskal_p": h4.get("kruskal_p"),
                 "rm_anova_p_gg": h4["rm_anova"].get("p_gg"), "friedman_p": h4.get("friedman_p"),
                 "statistic": (h4["welch"]["F"] if h4["model"] != "repeated_measures_gg" else h4["rm_anova"]["F"])})

    imm = d.config_id("E4", label="Full MWS - immediate")
    hist = d.config_id("E4", label="Full MWS - historical 300 s")
    frame5, missing5 = paired_frame(d, imm, hist, "d5_percent")
    per_seed["H5"] = frame5
    res = one_sample_test(frame5["diff"].to_numpy(), "greater", 0.0, alpha)
    res["boot_ci_low"], res["boot_ci_high"] = bootstrap_ci(frame5["diff"].to_numpy(), resamples=B, seed=bseed)
    res.update({"hypothesis": "H5", "title": "Current motion: immediate walking state improves D5 over the "
                "smoothed historical variant (100 nodes)", "metric": "D5 (pp)",
                "comparison": "MWS immediate - MWS historical (300 s)", "estimand": "mean paired difference",
                "kind": "superiority", "test": "one-sided paired t-test", "missing_pairs": missing5})
    rows.append(res)

    p_adj, levels = holm([r.get("p_raw", np.nan) for r in rows], alpha)
    for r, p, lvl in zip(rows, p_adj, levels):
        # A non-computable test keeps its place in the Holm family (m = 5, conservative for the others)
        # but receives no adjusted p-value of its own.
        r["p_holm"] = float(p) if r.get("computable", False) else float("nan")
        r["holm_level"] = float(lvl)
        r["decision"] = decide("noninferiority" if r["kind"] == "noninferiority" else "test", p,
                               r.get("computable", False), d.phase, alpha)
        if r["hypothesis"] in ("H1", "H2", "H3", "H5") and r.get("n", 0) >= 2:
            x = (per_seed[r["hypothesis"]]["block_mean"] if r["hypothesis"] != "H5"
                 else per_seed["H5"]["diff"]).to_numpy()
            side = "upper" if r["alternative"] == "less" else "lower"
            r["one_sided_bound_holm_level"] = one_sided_bound(x, lvl, side)
        r["result_category"] = result_category(r, d.phase)
    return {"family": pd.DataFrame(rows), "h4": h4, "per_seed": per_seed, "alpha": alpha, "delta": delta}


def secondary_family(d: PhaseData) -> pd.DataFrame:
    """Density-specific H1-H3 follow-ups (separate Holm family)."""
    st = d.cfg["statistics"]
    alpha, delta = float(st["alpha"]), float(st["h2_noninferiority_margin_pp"])
    specs = [("H1", "d5_percent", "greater", 0.0, "superiority"),
             ("H2", "d15_percent", "greater", -delta, "noninferiority"),
             ("H3", "transfers_per_message", "less", 0.0, "superiority")]
    rows = []
    for n in DENSITIES:
        for hid, metric, alt, null, kind in specs:
            frame, missing = paired_frame(d, d.e1_config("MWS", n), d.e1_config("BSW", n), metric)
            res = one_sample_test(frame["diff"].to_numpy(), alt, null, alpha)
            res.update({"hypothesis": f"{hid}@N={n}", "node_count": n, "metric": metric, "kind": kind,
                        "comparison": "MWS - BSW", "missing_pairs": missing,
                        "zero_variance_note": zero_variance_note(res),
                        "structural_note": structural_context(d, metric, (n,))})
            rows.append(res)
    p_adj, levels = holm([r["p_raw"] for r in rows], alpha)
    for r, p, lvl in zip(rows, p_adj, levels):
        r["p_holm_secondary"] = float(p) if r["computable"] else float("nan")
        r["decision"] = decide("noninferiority" if r["kind"] == "noninferiority" else "test", p,
                               r["computable"], d.phase, alpha)
        r["family"] = "secondary (density-specific follow-ups)"
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Exploratory comparisons (unadjusted, labelled)
# --------------------------------------------------------------------------- #
EXPLORATORY_METRICS = ("d5_percent", "d15_percent", "transfers_per_message", "median_latency_s")


def _explore(d: PhaseData, exp: str, comparison: str, cfg_a, cfg_b, metrics=EXPLORATORY_METRICS) -> list[dict]:
    rows = []
    for metric in metrics:
        frame, missing = paired_frame(d, cfg_a, cfg_b, metric)
        res = one_sample_test(frame["diff"].to_numpy(), "two-sided", 0.0)
        rows.append({"experiment": exp, "comparison": comparison, "metric": metric, "n": res["n"],
                     "mean_diff": res["mean_diff"], "median_diff": res["median_diff"], "sd": res["sd"],
                     "dz": res["dz"], "ci95_low": res["ci95_low"], "ci95_high": res["ci95_high"],
                     "p_two_sided_unadjusted": res["p_raw"], "wilcoxon_p": res["wilcoxon_p"],
                     "missing_pairs": len(missing), "zero_variance": res["degenerate_zero_variance"],
                     "status": "exploratory (not confirmatory; unadjusted)"})
    return rows


def exploratory_comparisons(d: PhaseData) -> pd.DataFrame:
    rows: list[dict] = []
    for n in DENSITIES:
        for other in ("Epidemic", "DirectDelivery"):
            rows += _explore(d, "E1", f"{other} - BSW @N={n}", d.e1_config(other, n), d.e1_config("BSW", n))
        rows += _explore(d, "E1", f"MWS - Epidemic @N={n}", d.e1_config("MWS", n), d.e1_config("Epidemic", n))
    for L in (4, 8, 16):
        rows += _explore(d, "E2", f"MWS - BSW @L={L}", d.config_id("E2", algorithm="MWS", copy_budget=L),
                         d.config_id("E2", algorithm="BSW", copy_budget=L))
    bsw = d.config_id("E3", label="BSW (no rules)")
    for label in ("R1 only", "R2 only", "R1+R2", "R2+R3", "Full MWS (R1+R2+R3)"):
        rows += _explore(d, "E3", f"{label} - BSW", d.config_id("E3", label=label), bsw)
    rows += _explore(d, "E4", "historical - immediate", d.config_id("E4", label="Full MWS - historical 300 s"),
                     d.config_id("E4", label="Full MWS - immediate"))
    bsw5 = d.config_id("E5", label="BSW")
    mws0 = d.config_id("E5", label="MWS 0% error")
    for label in ("MWS 0% error", "MWS 10% error", "MWS 20% error"):
        rows += _explore(d, "E5", f"{label} - BSW", d.config_id("E5", label=label), bsw5)
        if label != "MWS 0% error":
            rows += _explore(d, "E5", f"{label} - MWS 0% error", d.config_id("E5", label=label), mws0)
    for wl in ("separated_friends", "random"):
        rows += _explore(d, "E6", f"MWS - BSW ({wl})", d.config_id("E6", algorithm="MWS", workload_type=wl),
                         d.config_id("E6", algorithm="BSW", workload_type=wl))
    return pd.DataFrame(rows)


def workload_interaction(d: PhaseData) -> dict:
    """E6 difference-in-differences: (MWS-BSW)_random - (MWS-BSW)_separated, paired by seed."""
    fr, _ = paired_frame(d, d.config_id("E6", algorithm="MWS", workload_type="random"),
                         d.config_id("E6", algorithm="BSW", workload_type="random"), "d5_percent")
    fs, _ = paired_frame(d, d.config_id("E6", algorithm="MWS", workload_type="separated_friends"),
                         d.config_id("E6", algorithm="BSW", workload_type="separated_friends"), "d5_percent")
    merged = fr.set_index("seed")["diff"].to_frame("random").join(fs.set_index("seed")["diff"].rename("separated"),
                                                                    how="inner")
    res = one_sample_test((merged["random"] - merged["separated"]).to_numpy(), "two-sided")
    res["status"] = "exploratory (not confirmatory; unadjusted)"
    return res


# --------------------------------------------------------------------------- #
# Sample-size assessment (pilot)
# --------------------------------------------------------------------------- #
def sample_size_assessment(d: PhaseData, effects=(1.0, 2.0, 3.0, 5.0), power: float = 0.8) -> pd.DataFrame:
    """Repetitions needed for candidate target effects given pilot variability.

    Target effects are researcher choices, not calibrated values. The SD is the
    pilot SD of the analysis unit; an 80 % upper confidence limit of the SD is
    also used because a 5-seed SD is imprecise.
    """
    alpha = float(d.cfg["statistics"]["alpha"])
    fam = confirmatory_family(d)
    units = {
        "H1 block-mean dD5 (pp)": fam["per_seed"]["H1"]["block_mean"].to_numpy(),
        "H5 immediate-historical dD5 (pp)": fam["per_seed"]["H5"]["diff"].to_numpy(),
    }
    for n in DENSITIES:
        units[f"dD5 at N={n} (pp)"] = fam["per_seed"]["H4"][n].dropna().to_numpy()
    rows = []
    solver = TTestPower()
    for name, x in units.items():
        x = x[~np.isnan(x)]
        if x.size < 2 or np.std(x, ddof=1) == 0:
            continue
        sd = float(np.std(x, ddof=1))
        sd_ucl = sd * np.sqrt((x.size - 1) / stats.chi2.ppf(0.20, x.size - 1))
        for level_name, a in (("alpha=0.05", alpha), ("Holm worst case alpha/5", alpha / 5)):
            for sd_name, s in (("pilot SD", sd), ("80% UCL of SD", sd_ucl)):
                row = {"analysis_unit": name, "pilot_n": int(x.size), "pilot_mean": float(x.mean()),
                       "sd_basis": sd_name, "sd": s, "alpha_level": level_name}
                for eff in effects:
                    try:
                        need = solver.solve_power(effect_size=eff / s, alpha=a, power=power,
                                                  alternative="larger")
                        row[f"n_for_{eff:g}pp"] = int(np.ceil(need))
                    except Exception:  # noqa: BLE001
                        row[f"n_for_{eff:g}pp"] = np.nan
                try:
                    mde = solver.solve_power(nobs=30, alpha=a, power=power, alternative="larger") * s
                    row["mde_pp_at_n30"] = float(mde)
                except Exception:  # noqa: BLE001
                    row["mde_pp_at_n30"] = np.nan
                rows.append(row)
    return pd.DataFrame(rows)
