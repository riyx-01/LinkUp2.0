"""Confidence intervals: t-based and seed-block bootstrap.

The unit of analysis is one (scenario, seed) run. Bootstrap resampling always
resamples complete *seed blocks* (rows), never messages.
"""

from __future__ import annotations

import numpy as np
from scipy import stats


def t_interval(x: np.ndarray, level: float = 0.95) -> tuple[float, float]:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = x.size
    if n < 2:
        return (float("nan"), float("nan"))
    m, se = x.mean(), x.std(ddof=1) / np.sqrt(n)
    h = stats.t.ppf(0.5 + level / 2, n - 1) * se
    return (float(m - h), float(m + h))


def one_sided_bound(x: np.ndarray, alpha: float, side: str = "lower") -> float:
    """One-sided (1 - alpha) confidence bound for the mean."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = x.size
    if n < 2:
        return float("nan")
    m, se = x.mean(), x.std(ddof=1) / np.sqrt(n)
    q = stats.t.ppf(1 - alpha, n - 1) * se
    return float(m - q) if side == "lower" else float(m + q)


def bootstrap_ci(blocks: np.ndarray, statistic=np.mean, resamples: int = 5000, seed: int = 0,
                 level: float = 0.95) -> tuple[float, float]:
    """Percentile bootstrap CI resampling rows (seed blocks) with replacement.

    ``blocks`` is (n_seeds,) or (n_seeds, k). For 2-D input the statistic is
    applied to the resampled block means (equal weight per column), which is
    how the density-averaged H1-H3 estimates are formed.
    """
    arr = np.asarray(blocks, dtype=float)
    if arr.ndim == 2:
        arr = arr.mean(axis=1)
    arr = arr[~np.isnan(arr)]
    n = arr.size
    if n < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(resamples, n))
    boot = np.apply_along_axis(statistic, 1, arr[idx]) if statistic is not np.mean else arr[idx].mean(axis=1)
    lo, hi = np.percentile(boot, [50 * (1 - level), 100 - 50 * (1 - level)])
    return (float(lo), float(hi))


def summarize(x: np.ndarray, level: float = 0.95) -> dict:
    """n, mean, SD, SE, t-CI, median, IQR for one metric across seeds."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = x.size
    if n == 0:
        return {"n": 0, "mean": np.nan, "sd": np.nan, "se": np.nan, "ci_low": np.nan, "ci_high": np.nan,
                "median": np.nan, "q25": np.nan, "q75": np.nan}
    sd = float(x.std(ddof=1)) if n > 1 else float("nan")
    lo, hi = t_interval(x, level)
    return {"n": n, "mean": float(x.mean()), "sd": sd, "se": sd / np.sqrt(n) if n > 1 else float("nan"),
            "ci_low": lo, "ci_high": hi, "median": float(np.median(x)),
            "q25": float(np.percentile(x, 25)), "q75": float(np.percentile(x, 75))}
