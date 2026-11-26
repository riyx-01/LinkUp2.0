"""Observed (advertised) motion state and derived motion signals.

* The *true* state is the mobility model's ``walking[t, n]``.
* The *observed* state simulates an on-device activity classifier. Each true
  binary classification is flipped with probability ``error_rate``. The trace
  is generated **once per scenario and error condition**; every observer sees
  the same advertised state for a peer at a given second (no per-attempt draw).
* Errors use common random numbers: one uniform matrix per (seed, N, error
  model), flipping where ``u < error_rate``. The 10 % flips are therefore a
  subset of the 20 % flips, which reduces noise when comparing error levels.
* ``correlated`` errors (exploratory) use a two-state Markov (Gilbert-Elliott)
  process per node with stationary error probability ``error_rate`` and mean
  burst length ``mean_burst_s``.
* The *historical* signal (H5 variant B) is the proportion of observed-walking
  samples in the trailing window ``(t - W, t]`` (only observations at or before
  t), classified walking when the score >= threshold. Before W samples exist
  the available samples are used; warm-up provides the initial history.
"""

from __future__ import annotations

import numpy as np

from .rng import stream

ERROR_MODEL_CODES = {"independent": 1, "correlated": 2}


def error_flips(shape: tuple[int, int], error_rate: float, error_model: str,
                mean_burst_s: float, seed: int) -> np.ndarray:
    """Boolean (T, N) matrix of classification flips."""
    T, N = shape
    if error_rate <= 0:
        return np.zeros(shape, dtype=bool)
    rng = stream(seed, "motion_errors", N, ERROR_MODEL_CODES[error_model])
    u = rng.random(shape)
    if error_model == "independent":
        return u < error_rate
    # Two-state Markov chain: P(exit error) = 1/burst, P(enter) chosen so that
    # the stationary error probability equals error_rate.
    p_exit = 1.0 / float(mean_burst_s)
    p_enter = error_rate * p_exit / (1.0 - error_rate)
    flips = np.zeros(shape, dtype=bool)
    state = u[0] < error_rate
    flips[0] = state
    for t in range(1, T):
        state = np.where(state, u[t] >= p_exit, u[t] < p_enter)
        flips[t] = state
    return flips


def observed_walking(true_walking: np.ndarray, error_rate: float, error_model: str,
                     mean_burst_s: float, seed: int) -> np.ndarray:
    """Advertised walking state seen by all peers."""
    flips = error_flips(true_walking.shape, error_rate, error_model, mean_burst_s, seed)
    return np.logical_xor(true_walking, flips)


def historical_walking(observed: np.ndarray, window_s: int, threshold: float) -> np.ndarray:
    """Trailing-window walking classification (uses samples at or before t only)."""
    T = observed.shape[0]
    csum = np.zeros((T + 1,) + observed.shape[1:], dtype=np.int64)
    np.cumsum(observed, axis=0, out=csum[1:])
    t = np.arange(T)
    lo = np.maximum(0, t + 1 - int(window_s))
    counts = csum[t + 1] - csum[lo]
    n = (t + 1 - lo).astype(float)
    score = counts / n[:, None]
    return score >= threshold


class MotionOracle:
    """Restricted per-time accessor given to routing algorithms.

    Algorithms may only query the advertised state at the *current* time; the
    engine passes ``t`` and the oracle never exposes future rows.
    """

    def __init__(self, signal: np.ndarray, description: str):
        self._signal = signal
        self.description = description

    def walking(self, t: int, nodes: np.ndarray) -> np.ndarray:
        return self._signal[t, nodes]
