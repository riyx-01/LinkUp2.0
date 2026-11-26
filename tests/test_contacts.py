"""Contact detection: exact radius boundary and agreement with brute force."""

import numpy as np

from simulator.contacts import ContactTrace, compute_contact_trace, contact_events, pairs_within


def test_contact_at_exact_radius_boundary_is_inclusive():
    pos = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0], [20.0, 0.0]])
    pairs = {tuple(p) for p in pairs_within(pos, 10.0)}
    assert (0, 1) in pairs and (0, 2) in pairs and (1, 3) in pairs
    assert (0, 3) not in pairs


def test_contact_just_beyond_radius_excluded():
    pos = np.array([[0.0, 0.0], [10.000001, 0.0], [6.0, 8.0]])  # (0,2) exactly 10 m (3-4-5)
    pairs = {tuple(p) for p in pairs_within(pos, 10.0)}
    assert (0, 1) not in pairs
    assert (0, 2) in pairs


def test_contacts_match_brute_force():
    rng = np.random.default_rng(42)
    for _ in range(20):
        pos = rng.uniform(0, 60, size=(80, 2))
        fast = {tuple(p) for p in pairs_within(pos, 10.0)}
        d = np.hypot(pos[:, None, 0] - pos[None, :, 0], pos[:, None, 1] - pos[None, :, 1])
        brute = {(i, j) for i in range(80) for j in range(i + 1, 80) if d[i, j] <= 10.0}
        assert fast == brute


def test_trace_storage_and_events():
    T, N = 6, 3
    pos = np.zeros((T, N, 2), dtype=np.float32)
    pos[:, 1, 0] = [50, 5, 5, 5, 50, 5]   # node 1 near node 0 at t=1..3 and t=5
    pos[:, 2, 0] = 100
    trace = compute_contact_trace(pos, 10.0, 0, T)
    assert isinstance(trace, ContactTrace)
    assert [len(trace.at(t)) for t in range(T)] == [0, 1, 1, 1, 0, 1]
    ev = contact_events(trace, N)
    assert ev == [(0, 1, 1, 4), (0, 1, 5, 6)]  # second one right-censored at trace end
    assert len(trace.at(-1)) == 0 and len(trace.at(T)) == 0
