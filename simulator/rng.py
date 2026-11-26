"""Independent, reproducible random-number streams.

Every source of randomness has its own NumPy ``Generator`` derived from a
``SeedSequence`` whose entropy combines the master seed, a fixed stream code and
the stream's scope (e.g. node count). Consequences:

* Changing the routing algorithm can never change movement or message
  randomness: routing has no access to these streams.
* Streams are density specific (node count is part of the entropy), so the
  same master seed identifies a *block* across densities while each density's
  scenario is statistically independent (see docs/statistical_analysis_plan.md).
* Scheduling tie-breaks use a counter-based hash (see :func:`hash_keys`) so the
  same candidate transfer receives the same random key under every algorithm.
"""

from __future__ import annotations

import numpy as np

# Fixed stream codes. Never renumber: doing so changes every scenario.
STREAMS = {
    "initial_positions": 11,
    "group_assignment": 12,
    "mobility": 13,
    "separation": 14,
    "message_generation": 21,
    "pair_selection": 22,
    "motion_errors": 31,
    "scheduling": 41,
    "transfer_failures": 42,
}

WORKLOAD_CODES = {"separated_friends": 1, "random": 2}


def stream(seed: int, name: str, *scope: int) -> np.random.Generator:
    """Return the generator for stream ``name`` within ``scope``."""
    if name not in STREAMS:
        raise KeyError(f"Unknown RNG stream '{name}'")
    entropy = [int(seed), STREAMS[name], *[int(s) for s in scope]]
    return np.random.default_rng(np.random.SeedSequence(entropy))


def stream_base_key(seed: int, name: str, *scope: int) -> np.uint64:
    """A 64-bit key for counter-based hashing, derived like :func:`stream`."""
    entropy = [int(seed), STREAMS[name], *[int(s) for s in scope]]
    state = np.random.SeedSequence(entropy).generate_state(2, dtype=np.uint32)
    return np.uint64((int(state[0]) << 32) | int(state[1]))


_M1 = np.uint64(0xBF58476D1CE4E5B9)
_M2 = np.uint64(0x94D049BB133111EB)
_GOLDEN = np.uint64(0x9E3779B97F4A7C15)


def _splitmix64(x: np.ndarray) -> np.ndarray:
    """Vectorised SplitMix64 finaliser (wrapping uint64 arithmetic)."""
    x = x + _GOLDEN
    x = (x ^ (x >> np.uint64(30))) * _M1
    x = (x ^ (x >> np.uint64(27))) * _M2
    return x ^ (x >> np.uint64(31))


def hash_keys(base: np.uint64, *fields: np.ndarray) -> np.ndarray:
    """Counter-based pseudo-random uint64 keys for tuples of integer fields.

    ``hash_keys(base, t, m, s, r)`` returns one key per element. The mapping is
    deterministic and independent of how many other candidates exist, which
    makes scheduling tie-breaks identical across algorithms (common random
    numbers) and independent of node IDs' numeric order.
    """
    with np.errstate(over="ignore"):
        acc = np.full(np.broadcast(*fields).shape if fields else (), base, dtype=np.uint64)
        for field in fields:
            acc = _splitmix64(acc ^ np.asarray(field).astype(np.uint64))
    return acc
