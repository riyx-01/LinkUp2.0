"""Publication-quality figures (PNG 300 dpi + PDF) with the plotted data exported as CSV.

Conventions
-----------
* One colour per algorithm, fixed for every figure (validated colour-blind-safe
  categorical palette); algorithms also differ by marker and line style, so
  identity never depends on colour alone.
* Error bars are 95 % confidence intervals of the mean across seeds
  (t-distribution) unless the caption says SD.
* Percentage axes use a fixed 0-100 % scale; differences are in percentage
  points (pp). Axes are never truncated to exaggerate differences; the only log
  axis (transfers per message) is labelled as such because values span two
  orders of magnitude.
* Missing configurations are reported as missing in the figure, never as zero.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .confidence_intervals import summarize  # noqa: E402
from .data import DENSITIES, E1_ALGORITHMS, PhaseData  # noqa: E402
from .descriptive import cumulative_delivery, e1_summary  # noqa: E402
from .hypothesis_tests import density_differences, paired_frame  # noqa: E402

COLORS = {"BSW": "#257de0", "MWS": "#f47230", "Epidemic": "#00b894", "DirectDelivery": "#f2a600"}
MARKERS = {"BSW": "o", "MWS": "D", "Epidemic": "^", "DirectDelivery": "s"}
LINES = {"BSW": "-", "MWS": "--", "Epidemic": "-.", "DirectDelivery": ":"}
NAMES = {"DirectDelivery": "Direct Delivery", "Epidemic": "Epidemic", "BSW": "BSW", "MWS": "MWS"}
DENSITY_COLORS = {50: "#84b9f3", 100: "#257de0", 200: "#0e3d7e"}  # ordinal one-hue ramp
TEXT, TEXT2, GRID = "#191919", "#666666", "#e6e6e6"
CI_NOTE = "Error bars: 95% CI of the mean across seeds (t)."


def _style() -> None:
    plt.rcParams.update({
        "font.size": 9.5, "axes.titlesize": 10.5, "axes.labelsize": 9.5, "legend.fontsize": 8.5,
        "axes.edgecolor": "#999999", "axes.labelcolor": TEXT, "xtick.color": TEXT2, "ytick.color": TEXT2,
        "text.color": TEXT, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
        "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True, "lines.linewidth": 1.6,
        "lines.markersize": 6.5, "legend.frameon": False, "figure.dpi": 100, "savefig.bbox": "tight",
        "pdf.fonttype": 42, "font.family": "DejaVu Sans",
    })


def _density_ticks(ax, venue_area: float = 15000.0) -> None:
    ax.set_xticks(range(len(DENSITIES)))
    ax.set_xticklabels([f"{n}\n({n / venue_area * 1000:.2f}/1000 m²)" for n in DENSITIES])
    ax.set_xlabel("Participating smartphones (relative density)")


class FigureWriter:
    def __init__(self, out_dir: Path, phase: str, n_seeds: int):
        self.out = Path(out_dir)
        (self.out / "data").mkdir(parents=True, exist_ok=True)
        self.phase, self.n_seeds = phase, n_seeds
        self.manifest: list[dict] = []

    def save(self, fig, name: str, title: str, caption: str, data: pd.DataFrame) -> None:
        try:
            fig.tight_layout()
        except (ValueError, RuntimeError):  # pragma: no cover - layout is cosmetic
            pass
        if self.phase != "confirmatory":
            # Placed below the axes area; bbox_inches="tight" grows the canvas to include it.
            fig.text(0.995, -0.04, f"{self.phase.upper()} DATA (n = {self.n_seeds} seeds) - not confirmatory",
                     ha="right", va="top", fontsize=7, color=TEXT2)
        fig.savefig(self.out / f"{name}.png", dpi=300)
        fig.savefig(self.out / f"{name}.pdf")
        plt.close(fig)
        data.to_csv(self.out / "data" / f"{name}.csv", index=False)
        self.manifest.append({"figure": name, "title": title, "caption": caption,
                              "png": f"{name}.png", "pdf": f"{name}.pdf", "data_csv": f"data/{name}.csv"})


def _missing_note(ax, missing: list[str]) -> None:
    if missing:
        ax.text(0.01, 0.01, "Missing: " + ", ".join(missing), transform=ax.transAxes, fontsize=7,
                color=TEXT2, va="bottom")


def _ci(s: pd.Series | dict) -> tuple[float, float]:
    return s["mean"] - s["ci_low"], s["ci_high"] - s["mean"]


# --------------------------------------------------------------------------- E1 metric vs density
def metric_vs_nodes(fw: FigureWriter, d: PhaseData, metric: str, ylabel: str, name: str, title: str,
                    percent: bool = False, log: bool = False, caption_extra: str = "",
                    error: str = "ci") -> None:
    summ = e1_summary(d, metric)
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    offsets = dict(zip(E1_ALGORITHMS, (-0.15, -0.05, 0.05, 0.15)))
    missing = []
    for alg in E1_ALGORITHMS:
        s = summ[summ.algorithm == alg]
        if s["n"].sum() == 0:
            missing.append(NAMES[alg])
            continue
        x = np.arange(len(DENSITIES)) + offsets[alg]
        y = s["mean"].to_numpy()
        if error == "sd":
            yerr = s["sd"].fillna(0).to_numpy()
        else:
            yerr = np.vstack([(s["mean"] - s["ci_low"]).fillna(0), (s["ci_high"] - s["mean"]).fillna(0)])
        ax.errorbar(x, y, yerr=yerr, color=COLORS[alg], marker=MARKERS[alg], linestyle=LINES[alg],
                    capsize=3, label=NAMES[alg], markeredgecolor="white", markeredgewidth=0.8)
    _density_ticks(ax)
    ax.set_ylabel(ylabel)
    if percent:
        ax.set_ylim(0, 100)
    if log:
        ax.set_yscale("log")
    ax.set_title(title)
    ax.legend(loc="best", ncol=2)
    _missing_note(ax, missing)
    err_note = "Error bars: SD across seeds." if error == "sd" else CI_NOTE
    fw.save(fig, name, title, f"E1, copy budget 8, radius 10 m, primary workload. {err_note} {caption_extra}".strip(),
            summ)


# --------------------------------------------------------------------------- cumulative delivery
def cumulative_figure(fw: FigureWriter, d: PhaseData) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.6), sharey=True)
    rows = []
    for ax, n in zip(axes, DENSITIES):
        for alg in E1_ALGORITHMS:
            cid = d.e1_config(alg, n)
            cur = cumulative_delivery(d, cid)
            if cur["n"].max() == 0:
                continue
            ax.plot(cur["age_s"], cur["mean"], color=COLORS[alg], linestyle=LINES[alg], label=NAMES[alg])
            ax.fill_between(cur["age_s"], cur["ci_low"], cur["ci_high"], color=COLORS[alg], alpha=0.15, lw=0)
            rows.append(cur.assign(node_count=n, algorithm=alg))
        ax.axvline(300, color=TEXT2, lw=0.8, ls=(0, (2, 2)))
        ax.text(305, 3, "300 s (D5)", fontsize=7, color=TEXT2)
        ax.set_title(f"{n} nodes")
        ax.set_xlabel("Message age (s)")
        ax.set_xlim(0, 900)
        ax.set_ylim(0, 100)
    axes[0].set_ylabel("Delivered (% of all generated messages)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=4)
    fig.suptitle("Cumulative delivery vs message age (all generated messages)", fontsize=10.5)
    fig.tight_layout()
    fw.save(fig, "fig05_cumulative_delivery", "Cumulative delivery vs message age",
            "E1. Denominator = all generated messages (undelivered included). Bands: 95% CI across seeds.",
            pd.concat(rows) if rows else pd.DataFrame())


# --------------------------------------------------------------------------- trade-off
def tradeoff_figure(fw: FigureWriter, d: PhaseData) -> None:
    d5, tt = e1_summary(d, "d5_percent"), e1_summary(d, "transfers_per_message")
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.7), sharey=True, sharex=True)
    rows = []
    for ax, n in zip(axes, DENSITIES):
        for alg in E1_ALGORITHMS:
            a5 = d5[(d5.algorithm == alg) & (d5.node_count == n)].iloc[0]
            at = tt[(tt.algorithm == alg) & (tt.node_count == n)].iloc[0]
            if a5["n"] == 0:
                continue
            ax.errorbar([at["mean"]], [a5["mean"]],
                        xerr=[[np.nan_to_num(at["mean"] - at["ci_low"])], [np.nan_to_num(at["ci_high"] - at["mean"])]],
                        yerr=[[np.nan_to_num(a5["mean"] - a5["ci_low"])], [np.nan_to_num(a5["ci_high"] - a5["mean"])]],
                        color=COLORS[alg], marker=MARKERS[alg], linestyle="none", capsize=2, label=NAMES[alg],
                        markeredgecolor="white", markeredgewidth=0.8, markersize=7)
            rows.append({"algorithm": alg, "node_count": n, "T_mean": at["mean"], "T_ci_low": at["ci_low"],
                         "T_ci_high": at["ci_high"], "D5_mean": a5["mean"], "D5_ci_low": a5["ci_low"],
                         "D5_ci_high": a5["ci_high"]})
        ax.set_xscale("log")
        ax.set_title(f"{n} nodes")
        ax.set_xlabel("Transfers per message (log scale)")
        ax.set_ylim(0, 100)
    axes[0].set_ylabel("D5 (% delivered within 300 s)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=4)
    fig.suptitle("Timely delivery vs transfer cost", fontsize=10.5)
    fig.tight_layout()
    fw.save(fig, "fig06_tradeoff", "Delivery vs transfer-cost trade-off",
            f"E1. {CI_NOTE} BSW and MWS share the same copy budget and therefore overlap on the T axis. "
            "Transfers are an activity indicator, not energy.", pd.DataFrame(rows))


# --------------------------------------------------------------------------- paired differences
def paired_difference_figure(fw: FigureWriter, d: PhaseData) -> None:
    delta = float(d.cfg["statistics"]["h2_noninferiority_margin_pp"])
    specs = [("d5_percent", "ΔD5 (pp)"), ("d15_percent", "ΔD15 (pp)"), ("transfers_per_message", "ΔT (transfers/msg)")]
    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.6))
    rows = []
    rng = np.random.default_rng(0)
    for ax, (metric, label) in zip(axes, specs):
        wide, _ = density_differences(d, metric)
        cols = list(DENSITIES) + ["avg"]
        complete = wide.dropna()
        series = {n: wide[n].dropna().to_numpy() for n in DENSITIES}
        series["avg"] = complete.mean(axis=1).to_numpy()
        for i, key in enumerate(cols):
            vals = series[key]
            if vals.size == 0:
                continue
            ax.scatter(i + rng.uniform(-0.12, 0.12, vals.size), vals, s=12, color="#9c9c9c", alpha=0.8,
                       lw=0, zorder=2)
            s = summarize(vals)
            ax.errorbar(i + 0.22, s["mean"], yerr=[[s["mean"] - s["ci_low"]], [s["ci_high"] - s["mean"]]]
                        if s["n"] > 1 else None, color=COLORS["MWS"], marker="D", capsize=3, zorder=3,
                        markeredgecolor="white")
            rows.append({"metric": metric, "density": key, **s})
        ax.axhline(0, color=TEXT2, lw=0.8)
        if metric == "d15_percent":
            ax.axhline(-delta, color="#ec4647", lw=0.9, ls="--")
            ax.text(len(cols) - 0.6, -delta, f"-{delta:g} pp margin", fontsize=7, color=TEXT2, va="bottom", ha="right")
        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels([str(c) for c in DENSITIES] + ["mean of\ndensities"])
        ax.set_xlabel("Nodes")
        ax.set_ylabel(label)
        ax.set_title(f"MWS − BSW: {label.split(' ')[0]}")
    fig.tight_layout(w_pad=2.0)
    fw.save(fig, "fig07_paired_differences", "Paired MWS − BSW differences across densities",
            "Grey dots: individual seeds (paired within scenario). Orange: mean with 95% CI (t). "
            "'mean of densities' = equally weighted density mean per seed (H1-H3 estimand).", pd.DataFrame(rows))


# --------------------------------------------------------------------------- generic arm plots
def _arm_stats(d: PhaseData, cid: str | None, metric: str) -> dict:
    return summarize(d.runs_for(cid)[metric].to_numpy() if cid else np.array([]))


def copy_budget_figure(fw: FigureWriter, d: PhaseData) -> None:
    budgets = (4, 8, 16)
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
    rows = []
    for ax, (metric, label) in zip(axes, (("d5_percent", "D5 (%)"), ("transfers_per_message", "Transfers per message"))):
        for j, alg in enumerate(("BSW", "MWS")):
            st = [_arm_stats(d, d.config_id("E2", algorithm=alg, copy_budget=L), metric) for L in budgets]
            x = np.arange(len(budgets)) + (-0.06 if j == 0 else 0.06)
            ax.errorbar(x, [s["mean"] for s in st], yerr=[[s["mean"] - s["ci_low"] for s in st],
                                                         [s["ci_high"] - s["mean"] for s in st]],
                        color=COLORS[alg], marker=MARKERS[alg], linestyle=LINES[alg], capsize=3, label=NAMES[alg],
                        markeredgecolor="white")
            rows += [{"metric": metric, "algorithm": alg, "copy_budget": L, **s} for L, s in zip(budgets, st)]
        ax.set_xticks(range(len(budgets)))
        ax.set_xticklabels([f"L = {L}" for L in budgets])
        ax.set_xlabel("Copy budget")
        ax.set_ylabel(label)
        if metric == "d5_percent":
            ax.set_ylim(0, 100)
        else:
            ax.set_ylim(bottom=0)
    axes[0].legend(loc="lower right")
    fig.suptitle("Copy-budget sensitivity (100 nodes)", fontsize=10.5)
    fw.save(fig, "fig08_copy_budget", "Copy-budget sensitivity", f"E2. {CI_NOTE}", pd.DataFrame(rows))


def ablation_figure(fw: FigureWriter, d: PhaseData) -> None:
    labels = ["BSW (no rules)", "R1 only", "R2 only", "R1+R2", "R2+R3", "Full MWS (R1+R2+R3)"]
    bsw = d.config_id("E3", label="BSW (no rules)")
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.8), sharey=True)
    rows = []
    y = np.arange(len(labels))[::-1]
    for i, lab in enumerate(labels):
        cid = d.config_id("E3", label=lab)
        s = _arm_stats(d, cid, "d5_percent")
        color = COLORS["BSW"] if i == 0 else COLORS["MWS"]
        if s["n"]:
            axes[0].errorbar(s["mean"], y[i], xerr=[[s["mean"] - s["ci_low"]], [s["ci_high"] - s["mean"]]],
                             color=color, marker="o" if i == 0 else "D", capsize=3, markeredgecolor="white")
        fr, _ = paired_frame(d, cid, bsw, "d5_percent")
        sd = summarize(fr["diff"].to_numpy())
        if i > 0 and sd["n"]:
            axes[1].errorbar(sd["mean"], y[i], xerr=[[sd["mean"] - sd["ci_low"]], [sd["ci_high"] - sd["mean"]]]
                             if sd["n"] > 1 else None, color=color, marker="D", capsize=3, markeredgecolor="white")
        rows.append({"variant": lab, **{f"d5_{k}": v for k, v in s.items()},
                     **{f"diff_vs_bsw_{k}": v for k, v in sd.items()}})
    axes[0].set_yticks(y)
    axes[0].set_yticklabels(labels)
    axes[0].set_xlim(0, 100)
    axes[0].set_xlabel("D5 (%)")
    axes[1].axvline(0, color=TEXT2, lw=0.8)
    axes[1].set_xlabel("Paired ΔD5 vs BSW (pp)")
    fig.suptitle("Rule ablation (100 nodes, L = 8)", fontsize=10.5)
    fw.save(fig, "fig09_ablation", "Ablation comparison",
            f"E3. R1 friend exclusion, R2 walker preference, R3 patience fallback (only with R2). {CI_NOTE} "
            "Exploratory comparisons.", pd.DataFrame(rows))


def motion_comparison_figure(fw: FigureWriter, d: PhaseData) -> None:
    imm = d.config_id("E4", label="Full MWS - immediate")
    hist = d.config_id("E4", label="Full MWS - historical 300 s")
    fr, _ = paired_frame(d, imm, hist, "d5_percent")
    fig, axes = plt.subplots(1, 2, figsize=(8.5, 3.6), gridspec_kw={"width_ratios": [1.4, 1]})
    for _, r in fr.iterrows():
        axes[0].plot([0, 1], [r["a"], r["b"]], color="#b0b0b0", lw=0.8, marker="o", ms=3.5)
    for i, col in enumerate(("a", "b")):
        s = summarize(fr[col].to_numpy())
        if s["n"]:
            axes[0].errorbar(i + (0.08 if i else -0.08), s["mean"],
                             yerr=[[s["mean"] - s["ci_low"]], [s["ci_high"] - s["mean"]]] if s["n"] > 1 else None,
                             color=COLORS["MWS"], marker="D", capsize=3, markeredgecolor="white")
    axes[0].set_xticks([0, 1])
    axes[0].set_xticklabels(["Immediate\n(current state)", "Historical\n(300 s window)"])
    axes[0].set_ylim(0, 100)
    axes[0].set_ylabel("D5 (%)")
    axes[0].set_title("Per-seed paired D5")
    s = summarize(fr["diff"].to_numpy())
    if s["n"]:
        axes[1].errorbar([0], [s["mean"]], yerr=[[s["mean"] - s["ci_low"]], [s["ci_high"] - s["mean"]]]
                         if s["n"] > 1 else None, color=COLORS["MWS"], marker="D", capsize=4, markeredgecolor="white")
        axes[1].scatter(np.zeros(len(fr)) - 0.15, fr["diff"], color="#9c9c9c", s=12, lw=0)
    axes[1].axhline(0, color=TEXT2, lw=0.8)
    axes[1].set_xlim(-0.6, 0.6)
    axes[1].set_xticks([0])
    axes[1].set_xticklabels(["Immediate − historical"])
    axes[1].set_ylabel("ΔD5 (pp)")
    axes[1].set_title("Paired difference (H5)")
    fw.save(fig, "fig10_motion_comparison", "Immediate vs historical motion signal",
            f"E4, 100 nodes. Variants differ only in the motion signal. {CI_NOTE}", fr)


def motion_error_figure(fw: FigureWriter, d: PhaseData) -> None:
    labels = [("MWS 0% error", 0), ("MWS 10% error", 10), ("MWS 20% error", 20)]
    bsw = d.config_id("E5", label="BSW")
    b = _arm_stats(d, bsw, "d5_percent")
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
    rows = []
    st = [_arm_stats(d, d.config_id("E5", label=lab), "d5_percent") for lab, _ in labels]
    x = [e for _, e in labels]
    if b["n"]:
        axes[0].axhspan(b["ci_low"], b["ci_high"], color=COLORS["BSW"], alpha=0.12, lw=0)
        axes[0].axhline(b["mean"], color=COLORS["BSW"], lw=1.4, label="BSW (ignores motion)")
    axes[0].errorbar(x, [s["mean"] for s in st], yerr=[[s["mean"] - s["ci_low"] for s in st],
                                                      [s["ci_high"] - s["mean"] for s in st]],
                     color=COLORS["MWS"], marker="D", linestyle="--", capsize=3, label="MWS", markeredgecolor="white")
    axes[0].set_ylim(0, 100)
    axes[0].set_xticks(x)
    axes[0].set_xlabel("Motion-classification error rate (%)")
    axes[0].set_ylabel("D5 (%)")
    axes[0].legend(loc="lower right")
    diffs = []
    for (lab, e), s in zip(labels, st):
        fr, _ = paired_frame(d, d.config_id("E5", label=lab), bsw, "d5_percent")
        sd = summarize(fr["diff"].to_numpy())
        diffs.append(sd)
        rows.append({"error_rate_pct": e, **{f"mws_d5_{k}": v for k, v in s.items()},
                     **{f"diff_vs_bsw_{k}": v for k, v in sd.items()}})
    axes[1].errorbar(x, [s["mean"] for s in diffs], yerr=[[s["mean"] - s["ci_low"] for s in diffs],
                                                          [s["ci_high"] - s["mean"] for s in diffs]],
                     color=COLORS["MWS"], marker="D", linestyle="--", capsize=3, markeredgecolor="white")
    axes[1].axhline(0, color=TEXT2, lw=0.8)
    axes[1].set_xticks(x)
    axes[1].set_xlabel("Motion-classification error rate (%)")
    axes[1].set_ylabel("Paired ΔD5, MWS − BSW (pp)")
    fig.suptitle("Robustness to motion-classification errors (100 nodes)", fontsize=10.5)
    fw.save(fig, "fig11_motion_error", "Motion-error sensitivity",
            f"E5. Independent per-second flips; observed trace shared by all observers. {CI_NOTE} Band: BSW 95% CI.",
            pd.DataFrame(rows))


def workload_figure(fw: FigureWriter, d: PhaseData) -> None:
    workloads = [("separated_friends", "Separated friends\n(primary)"), ("random", "Random pairs\n(generalisation)")]
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
    rows = []
    for j, alg in enumerate(("BSW", "MWS")):
        st = [_arm_stats(d, d.config_id("E6", algorithm=alg, workload_type=w), "d5_percent") for w, _ in workloads]
        x = np.arange(2) + (-0.08 if j == 0 else 0.08)
        axes[0].errorbar(x, [s["mean"] for s in st], yerr=[[s["mean"] - s["ci_low"] for s in st],
                                                          [s["ci_high"] - s["mean"] for s in st]],
                         color=COLORS[alg], marker=MARKERS[alg], linestyle="none", capsize=3, label=NAMES[alg],
                         markeredgecolor="white")
        rows += [{"algorithm": alg, "workload": w, **s} for (w, _), s in zip(workloads, st)]
    axes[0].set_xticks(range(2))
    axes[0].set_xticklabels([lab for _, lab in workloads])
    axes[0].set_ylim(0, 100)
    axes[0].set_ylabel("D5 (%)")
    axes[0].legend(loc="lower right")
    for i, (w, lab) in enumerate(workloads):
        fr, _ = paired_frame(d, d.config_id("E6", algorithm="MWS", workload_type=w),
                             d.config_id("E6", algorithm="BSW", workload_type=w), "d5_percent")
        s = summarize(fr["diff"].to_numpy())
        if s["n"]:
            axes[1].errorbar([i], [s["mean"]], yerr=[[s["mean"] - s["ci_low"]], [s["ci_high"] - s["mean"]]]
                             if s["n"] > 1 else None, color=COLORS["MWS"], marker="D", capsize=3, markeredgecolor="white")
        rows.append({"algorithm": "MWS-BSW", "workload": w, **s})
    axes[1].axhline(0, color=TEXT2, lw=0.8)
    axes[1].set_xticks(range(2))
    axes[1].set_xticklabels([lab for _, lab in workloads])
    axes[1].set_xlim(-0.5, 1.5)
    axes[1].set_ylabel("Paired ΔD5, MWS − BSW (pp)")
    fig.suptitle("Group-separation vs random-destination workload (100 nodes)", fontsize=10.5)
    fw.save(fig, "fig12_workload", "Group-separation vs random-destination comparison",
            f"E6 (primary-workload arms reused from E1). {CI_NOTE}", pd.DataFrame(rows))


# --------------------------------------------------------------------------- mobility validation
def mobility_validation_figure(df: pd.DataFrame, out_dir: Path, fw: FigureWriter | None = None) -> None:
    _style()
    df = df.copy()
    if "workload_type" in df:
        df = df[df["workload_type"] == "separated_friends"]
    if "communication_radius_m" in df:
        df = df[df["communication_radius_m"] == 10]
    fig, axes = plt.subplots(3, 3, figsize=(11, 9.5))
    ax = axes.ravel()
    densities = sorted(df["node_count"].unique())
    rng = np.random.default_rng(0)

    def strip(a, col, ylabel, title):
        for i, n in enumerate(densities):
            vals = df[df.node_count == n][col].dropna().to_numpy()
            a.scatter(i + rng.uniform(-0.1, 0.1, vals.size), vals, color=DENSITY_COLORS.get(n, "#257de0"), s=18, lw=0)
            if vals.size:
                a.plot([i - 0.22, i + 0.22], [vals.mean()] * 2, color=TEXT, lw=1.4)
        a.set_xticks(range(len(densities)))
        a.set_xticklabels([str(n) for n in densities])
        a.set_xlabel("Nodes")
        a.set_ylabel(ylabel)
        a.set_title(title)
        a.set_ylim(bottom=0)

    strip(ax[0], "pct_time_walking", "% of node-time walking", "(a) Time walking")
    edges = np.linspace(0, 1.4, 15)
    for n in densities:
        counts = np.sum([json.loads(c) for c in df[df.node_count == n]["walking_speed_hist_counts"]], axis=0)
        if np.sum(counts):
            ax[1].step(edges[:-1], counts / counts.sum() * 100, where="post", color=DENSITY_COLORS.get(n), label=f"N={n}")
    ax[1].set_xlabel("Realised walking speed (m/s, per 1-s step)")
    ax[1].set_ylabel("% of walking steps")
    ax[1].set_title("(b) Walking-speed distribution")
    ax[1].legend()
    strip(ax[2], "avg_neighbours_per_node", "Mean neighbours per node", "(c) Neighbours (r = 10 m)")
    strip(ax[3], "contact_events_per_node_per_hour", "Contacts per node per hour", "(d) Contact frequency")
    strip(ax[4], "contact_duration_median_s", "Median contact duration (s)", "(e) Contact duration")
    strip(ax[5], "separation_events_total", "Separation events per run", "(f) Separation events")
    df["separated_share_pct"] = df["mean_separated_members"] / (df["grouped_fraction"] * df["node_count"]) * 100
    strip(ax[6], "separated_share_pct", "% of grouped nodes separated", "(g) Separated members (time mean)")
    zones = [c for c in df.columns if c.startswith("zone_share_")]
    width = 0.8 / max(len(densities), 1)
    for i, n in enumerate(densities):
        vals = df[df.node_count == n][zones].mean() * 100
        ax[7].bar(np.arange(len(zones)) + (i - (len(densities) - 1) / 2) * width, vals, width=width * 0.92,
                  color=DENSITY_COLORS.get(n), label=f"N={n}")
    ax[7].set_xticks(range(len(zones)))
    ax[7].set_xticklabels([z.replace("zone_share_", "").replace("_", " ") for z in zones], fontsize=7.5,
                          rotation=30, ha="right")
    ax[7].set_ylabel("% of node-time")
    ax[7].set_title("(h) Position by zone")
    ax[7].legend()
    comp = [("encounter_start_both_stationary_share", "0 walking", "#cce3fd"),
            ("encounter_start_one_walking_share", "1 walking", "#519ced"),
            ("encounter_start_both_walking_share", "2 walking", "#0f4a96")]
    bottom = np.zeros(len(densities))
    for col, lab, color in comp:
        vals = np.array([df[df.node_count == n][col].mean() * 100 for n in densities])
        ax[8].bar(range(len(densities)), vals, bottom=bottom, color=color, label=lab, edgecolor="white", lw=1)
        bottom += vals
    ax[8].set_xticks(range(len(densities)))
    ax[8].set_xticklabels([str(n) for n in densities])
    ax[8].set_xlabel("Nodes")
    ax[8].set_ylabel("% of contact events")
    ax[8].set_ylim(0, 100)
    ax[8].set_title("(i) Walkers at contact start")
    ax[8].legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3)
    fig.suptitle("Mobility and contact validation (algorithm independent, post-warm-up)", fontsize=11)
    fig.tight_layout()
    caption = ("Dots: seeds; bars/lines: means across seeds. Computed before and independently of routing.")
    plot_cols = ["node_count", "seed", "pct_time_walking", "avg_neighbours_per_node",
                 "contact_events_per_node_per_hour", "contact_duration_median_s", "separation_events_total",
                 "separated_share_pct", *zones, *[c for c, _, _ in comp]]
    data = df[[c for c in plot_cols if c in df.columns]]
    if fw is not None:
        fw.save(fig, "fig15_mobility_validation", "Mobility and contact validation", caption, data)
    else:
        out_dir = Path(out_dir)
        fig.savefig(out_dir / "fig_mobility_validation.png", dpi=300)
        fig.savefig(out_dir / "fig_mobility_validation.pdf")
        plt.close(fig)
        data.to_csv(out_dir / "fig_mobility_validation_data.csv", index=False)


# --------------------------------------------------------------------------- entry point
def make_all_figures(d: PhaseData, out_dir: Path) -> list[dict]:
    _style()
    fw = FigureWriter(out_dir, d.phase, len(d.seeds))
    metric_vs_nodes(fw, d, "d5_percent", "D5 (% delivered within 300 s)", "fig01_d5_vs_nodes",
                    "Timely delivery (D5) vs density", percent=True)
    metric_vs_nodes(fw, d, "d15_percent", "D15 (% delivered within 900 s)", "fig02_d15_vs_nodes",
                    "Reliability (D15) vs density", percent=True)
    metric_vs_nodes(fw, d, "transfers_per_message", "Completed transfers per message (log scale)",
                    "fig03_transfers_vs_nodes", "Transfer cost (T) vs density", log=True,
                    caption_extra="Log scale because values span two orders of magnitude.")
    metric_vs_nodes(fw, d, "median_latency_s", "Median latency of delivered messages (s)",
                    "fig04_median_latency_vs_nodes", "Median delivery latency vs density",
                    caption_extra="Delivered messages only (subject to selection bias); see fig05.")
    cumulative_figure(fw, d)
    tradeoff_figure(fw, d)
    paired_difference_figure(fw, d)
    copy_budget_figure(fw, d)
    ablation_figure(fw, d)
    motion_comparison_figure(fw, d)
    motion_error_figure(fw, d)
    workload_figure(fw, d)
    metric_vs_nodes(fw, d, "buffer_drops", "Buffer drops per run", "fig13_buffer_drops",
                    "Buffer drops by algorithm", caption_extra="Zero values are observed zeros.")
    metric_vs_nodes(fw, d, "runtime_s", "Routing wall-clock per run (s)", "fig14_runtime",
                    "Routing runtime by nodes and algorithm", error="sd",
                    caption_extra="Excludes shared scenario generation; measured on the execution machine.")
    if not d.validation.empty:
        mobility_validation_figure(d.validation, out_dir, fw)
    pd.DataFrame(fw.manifest).to_csv(Path(out_dir) / "figure_manifest.csv", index=False)
    return fw.manifest
