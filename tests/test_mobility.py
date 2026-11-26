"""Mobility model: physical constraints, groups, separation and reproducibility."""

import numpy as np
import pytest

from tests.helpers import random_scenario
from simulator.config import apply_overrides, load_config
from simulator.groups import assign_groups, draw_group_sizes
from simulator.mobility import FestivalMobility, generate_mobility
from simulator.node import NO_GROUP, SeparationState
from simulator.venue import Venue

CFG = load_config("default.json")


@pytest.fixture(scope="module", params=[(50, 1), (200, 2)])
def trace(request):
    n, seed = request.param
    return generate_mobility(apply_overrides(CFG, {"nodes.node_count": n}), n, seed)


def test_nodes_never_leave_venue(trace):
    venue = Venue(CFG["venue"])
    assert venue.inside(trace.positions.astype(float), tol=1e-6).all()


def test_stationary_nodes_do_not_move(trace):
    pos = trace.positions.astype(float)
    disp = np.hypot(*(pos[1:] - pos[:-1]).transpose(2, 0, 1))
    assert np.all(disp[~trace.walking[:-1]] == 0.0)


def test_speed_limits_respected(trace):
    pos = trace.positions.astype(float)
    disp = np.hypot(*(pos[1:] - pos[:-1]).transpose(2, 0, 1))
    # float32 storage of positions allows ~1e-4 m rounding.
    assert disp.max() <= CFG["mobility"]["speed_max_mps"] + 1e-4
    sampled = np.asarray(trace.trip_speeds)
    assert sampled.min() >= CFG["mobility"]["speed_min_mps"] and sampled.max() <= CFG["mobility"]["speed_max_mps"]


def test_walking_nodes_move_and_states_mix(trace):
    pos = trace.positions.astype(float)
    disp = np.hypot(*(pos[1:] - pos[:-1]).transpose(2, 0, 1))
    assert np.all(disp[trace.walking[:-1]] > 0)
    share = trace.walking.mean()
    assert 0.05 < share < 0.95  # both states occur


def test_group_members_never_perfectly_overlap(trace):
    pos = trace.positions.astype(float)
    for members in trace.groups.members:
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                d = np.hypot(*(pos[:, a] - pos[:, b]).T)
                assert d.min() > 1e-6


def test_group_sizes_and_participation():
    rng = np.random.default_rng(0)
    for target in range(0, 300):
        sizes = draw_group_sizes(target, 2, 6, rng)
        assert all(2 <= s <= 6 for s in sizes)
        assert target - sum(sizes) in (0, 1)
    g = assign_groups(200, CFG["mobility"], np.random.default_rng(1))
    assert abs(g.grouped_fraction - 0.7) <= 0.01
    assert all(2 <= len(m) <= 6 for m in g.members)
    assert np.all(g.offsets[g.group_of == NO_GROUP] == 0)


def test_destination_choice_avoids_current_zone():
    mob = FestivalMobility(CFG, 10, 1)
    rng = np.random.default_rng(3)
    for current in range(len(mob.zone_names)):
        picks = {mob._choose_zone(rng, {current}) for _ in range(300)}
        assert current not in picks


def test_separation_occurs_and_rejoin_is_physical(trace):
    assert len(trace.separation_events) > 0
    sep = trace.sep_state
    # Only grouped nodes are ever separated.
    independent = trace.groups.group_of == NO_GROUP
    assert np.all(sep[:, independent] == SeparationState.WITH_GROUP)
    # Every rejoin happens at least the minimum separation after separating.
    for t, node, start in trace.rejoin_events:
        assert t - start >= CFG["mobility"]["min_separation_s"]
    # Each group always keeps at least one member with the group.
    for members in trace.groups.members:
        assert np.all((sep[:, members] == SeparationState.WITH_GROUP).sum(axis=1) >= 1)


def test_identical_seed_identical_trace_and_different_seed_differs():
    cfg = apply_overrides(CFG, {"nodes.node_count": 50})
    a = generate_mobility(cfg, 50, 7)
    b = generate_mobility(cfg, 50, 7)
    c = generate_mobility(cfg, 50, 8)
    assert np.array_equal(a.positions, b.positions) and np.array_equal(a.walking, b.walking)
    assert np.array_equal(a.groups.group_of, b.groups.group_of)
    assert not np.array_equal(a.positions, c.positions)


def test_rejoin_policy_immediate_shortens_separation():
    cfg = apply_overrides(CFG, {"nodes.node_count": 100,
                                "mobility.rejoin_policy": "immediate_after_minimum"})
    tr = generate_mobility(cfg, 100, 3)
    durations = [t - s for t, _, s in tr.rejoin_events]
    assert durations and min(durations) >= 300
    base = generate_mobility(apply_overrides(CFG, {"nodes.node_count": 100}), 100, 3)
    base_d = [t - s for t, _, s in base.rejoin_events]
    assert np.mean(durations) < np.mean(base_d)


def test_mobility_unaffected_by_routing_runs():
    from simulator.engine import RoutingEngine
    cfg, scen = random_scenario(50, 4)
    before = scen.compute_hash()
    pos_before = scen.mobility.positions.copy()
    for alg in ("DirectDelivery", "Epidemic", "BSW", "MWS"):
        RoutingEngine(apply_overrides(cfg, {"routing.algorithm": alg}), scen).run()
    assert scen.compute_hash() == before
    assert np.array_equal(pos_before, scen.mobility.positions)
