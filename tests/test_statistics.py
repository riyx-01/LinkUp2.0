"""Statistical machinery on constructed inputs: pairing, tests, Holm, non-inferiority, data quality."""

import numpy as np
import pandas as pd
import pytest
from scipy import stats
from statsmodels.stats.multitest import multipletests

from analysis import hypothesis_tests as ht
from analysis.confidence_intervals import bootstrap_ci, one_sided_bound, t_interval
from analysis.data import PhaseData, data_quality_checks
from simulator.config import load_config


def make_data(phase="confirmatory", seeds=(1001, 1002, 1003, 1004, 1005), values=None, failed=()):
    """Tiny PhaseData with two configs (A=MWS-like, B=BSW-like) in experiment E1 at N=50/100/200."""
    cfg = load_config("confirmatory.json")
    cfg["seeds"] = list(seeds)
    rows, matrix = [], []
    for n in (50, 100, 200):
        for alg in ("MWS", "BSW"):
            cid = f"{alg}{n}"
            matrix.append({"experiment_id": "E1", "arm_label": f"N={n} | {alg}", "configuration_id": cid,
                           "algorithm": alg, "variant": alg, "node_count": n, "copy_budget": 8,
                           "communication_radius_m": 10, "motion_error_rate": 0.0,
                           "workload_type": "separated_friends", "reused_from": ""})
            for s in seeds:
                v = values(alg, n, s) if values else 50.0
                status = "failed" if (cid, s) in failed else "ok"
                rows.append({"run_id": f"{cid}_s{s}", "configuration_id": cid, "seed": s, "node_count": n,
                             "algorithm": alg, "run_status": status, "d5_percent": v if status == "ok" else np.nan,
                             "d15_percent": 100.0, "transfers_per_message": 8.0, "code_version": "x",
                             "token_conservation_ok": True, "repeated_destination_receptions": 0,
                             "scenario_id": f"sc{n}_{s}", "scenario_hash": f"h{n}_{s}", "generated_messages": 60})
    runs = pd.DataFrame(rows)
    plan = runs[["run_id", "configuration_id", "seed"]]
    d = PhaseData(phase, None, cfg, runs, runs[runs.run_status == "ok"].copy(), pd.DataFrame(), pd.DataFrame(),
                  pd.DataFrame(matrix), plan)
    return d


def test_pairing_matches_seeds_and_reports_missing():
    d = make_data(values=lambda a, n, s: s - 1000 + (10 if a == "MWS" else 0), failed={("BSW100", 1003)})
    frame, missing = ht.paired_frame(d, "MWS100", "BSW100", "d5_percent")
    assert list(frame["seed"]) == [1001, 1002, 1004, 1005]
    assert np.allclose(frame["diff"], 10.0)
    assert missing == [1003]
    wide, miss = ht.density_differences(d, "d5_percent")
    assert miss[100] == [1003] and wide.dropna().shape[0] == 4


def test_one_sample_test_matches_scipy():
    rng = np.random.default_rng(3)
    x = rng.normal(1.0, 2.0, 30)
    res = ht.one_sample_test(x, "greater")
    ref = stats.ttest_1samp(x, 0.0, alternative="greater")
    assert np.isclose(res["t"], ref.statistic) and np.isclose(res["p_raw"], ref.pvalue)
    res_less = ht.one_sample_test(x, "less")
    assert np.isclose(res_less["p_raw"], stats.ttest_1samp(x, 0.0, alternative="less").pvalue)
    assert np.isclose(res["dz"], x.mean() / x.std(ddof=1))


def test_noninferiority_decisions_on_constructed_inputs():
    # Mean -1 pp with small spread: lower bound well above -5 -> established.
    good = np.array([-1.2, -0.8, -1.0, -1.1, -0.9, -1.0, -1.05, -0.95])
    r = ht.one_sample_test(good, "greater", null_value=-5.0)
    assert r["p_raw"] < 0.001 and r["one_sided_bound"] > -5
    assert ht.decide("noninferiority", r["p_raw"], True, "confirmatory", 0.05) == ht.NI_ESTABLISHED
    # Mean -6 pp: clearly inferior beyond the margin -> not established.
    bad = good - 5.0
    r2 = ht.one_sample_test(bad, "greater", null_value=-5.0)
    assert r2["p_raw"] > 0.5 and r2["one_sided_bound"] < -5
    assert ht.decide("noninferiority", r2["p_raw"], True, "confirmatory", 0.05) == ht.NI_NOT_ESTABLISHED
    # Bound and p-value agree: bound > margin <=> p < alpha.
    for shift in np.linspace(-8, 2, 21):
        x = good + shift
        rr = ht.one_sample_test(x, "greater", null_value=-5.0, alpha=0.05)
        assert (rr["p_raw"] < 0.05) == (rr["one_sided_bound"] > -5.0)


def test_holm_correction_matches_reference():
    p = [0.01, 0.04, 0.03, 0.005, 0.20]
    adj, levels = ht.holm(p, 0.05)
    ref = multipletests(p, alpha=0.05, method="holm")[1]
    assert np.allclose(adj, ref)
    # Manual: sorted 0.005,0.01,0.03,0.04,0.2 -> x5,x4,x3,x2,x1 = 0.025,0.04,0.09,0.08,0.2,
    # then enforce monotonicity (0.08 -> 0.09).
    assert np.allclose(adj, [0.04, 0.09, 0.09, 0.025, 0.20])
    assert np.allclose(sorted(levels), sorted([0.05 / 5, 0.05 / 4, 0.05 / 3, 0.05 / 2, 0.05]))
    adj_nan, _ = ht.holm([0.01, np.nan], 0.05)
    assert adj_nan[1] == 1.0


def test_decision_wording_is_restricted():
    for kind in ("test", "noninferiority"):
        for p in (0.001, 0.2, np.nan):
            dec = ht.decide(kind, p, not np.isnan(p), "confirmatory", 0.05)
            assert dec in ht.ALLOWED_DECISIONS
    assert ht.decide("test", 0.001, True, "pilot", 0.05) == ht.PILOT_DECISION


def test_zero_variance_rule():
    zeros = np.zeros(10)
    assert ht.one_sample_test(zeros, "less")["p_raw"] == 1.0           # H3-style: no reduction
    assert ht.one_sample_test(zeros, "greater", -5.0)["p_raw"] == 0.0  # H2-style: inside margin
    r = ht.one_sample_test(zeros, "greater")
    assert r["p_raw"] == 1.0 and r["degenerate_zero_variance"]


def test_confirmatory_family_on_constructed_data():
    rng = np.random.default_rng(7)
    eff = {50: 6.0, 100: 4.0, 200: 2.0}
    noise = {(a, n, s): rng.normal(0, 1) for a in ("MWS", "BSW") for n in (50, 100, 200)
             for s in range(1001, 1031)}
    vals = lambda a, n, s: 60 + noise[(a, n, s)] + (eff[n] if a == "MWS" else 0)  # noqa: E731
    d = make_data(seeds=tuple(range(1001, 1031)), values=vals)
    # Add E4 arms so H5 is computable.
    extra, rows = [], []
    for label, cid, add in (("Full MWS - immediate", "IMM", 3.0), ("Full MWS - historical 300 s", "HIST", 0.0)):
        extra.append({"experiment_id": "E4", "arm_label": label, "configuration_id": cid, "algorithm": "MWS",
                      "variant": label, "node_count": 100, "copy_budget": 8, "communication_radius_m": 10,
                      "motion_error_rate": 0.0, "workload_type": "separated_friends", "reused_from": ""})
        for s in d.seeds:
            rows.append({"run_id": f"{cid}_s{s}", "configuration_id": cid, "seed": s, "node_count": 100,
                         "run_status": "ok", "d5_percent": 70 + add + rng.normal(0, 1), "d15_percent": 100.0,
                         "transfers_per_message": 8.0})
    d.matrix = pd.concat([d.matrix, pd.DataFrame(extra)], ignore_index=True)
    d.ok = pd.concat([d.ok, pd.DataFrame(rows)], ignore_index=True)
    fam = ht.confirmatory_family(d)["family"].set_index("hypothesis")
    assert fam.loc["H1", "mean_diff"] == pytest.approx(4.0, abs=0.5)
    assert fam.loc["H1", "decision"] == ht.REJECT
    assert fam.loc["H2", "decision"] == ht.NI_ESTABLISHED        # identical D15 -> inside the margin
    assert fam.loc["H3", "decision"] == ht.FAIL_TO_REJECT        # identical T -> no reduction
    assert fam.loc["H4", "decision"] == ht.REJECT                # densities differ by construction
    assert fam.loc["H5", "decision"] == ht.REJECT
    assert set(fam["decision"]) <= set(ht.ALLOWED_DECISIONS)
    assert (fam["p_holm"] >= fam["p_raw"] - 1e-12).all()


def test_h4_detects_no_density_difference_when_absent():
    rng = np.random.default_rng(11)
    wide = pd.DataFrame({n: rng.normal(3, 2, 30) for n in (50, 100, 200)})
    res = ht.h4_tests(wide, "independent_groups_welch")
    assert res["primary_p"] > 0.01
    gg = ht.rm_anova_gg(wide.to_numpy())
    assert 0.5 <= gg["gg_epsilon"] <= 1.0


def test_missing_and_failed_runs_are_detected():
    d = make_data(failed={("MWS50", 1002)})
    d.plan = pd.concat([d.plan, pd.DataFrame([{"run_id": "ghost_s1001", "configuration_id": "ghost", "seed": 1001}])])
    checks = {c["check"]: c for c in data_quality_checks(d)}
    assert checks["No failed runs"]["status"] == "FAIL"
    assert checks["All planned runs present"]["status"] == "FAIL"
    assert "ghost_s1001" in checks["All planned runs present"]["detail"]


def test_confidence_intervals():
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    lo, hi = t_interval(x)
    assert lo < 3 < hi and np.isclose((lo + hi) / 2, 3.0)
    assert one_sided_bound(x, 0.05, "lower") > lo
    b = bootstrap_ci(np.column_stack([x, x + 1, x + 2]), resamples=2000, seed=1)
    assert b[0] < 4 < b[1]
    assert bootstrap_ci(x, resamples=500, seed=5) == bootstrap_ci(x, resamples=500, seed=5)
