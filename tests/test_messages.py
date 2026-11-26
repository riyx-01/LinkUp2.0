"""Workload generation, lifetime observation and expiry semantics."""

import numpy as np

from tests.helpers import handcrafted_scenario, random_scenario, run, small_config, transfers
from simulator.config import ConfigError, apply_overrides, load_config, validate_config
from simulator.node import SeparationState
from simulator.workload import generation_times


def test_messages_generated_only_within_interval():
    cfg, scen = random_scenario(100, 1)
    created = scen.messages.created
    assert created.min() >= 300 and created.max() < 900
    assert np.all(np.diff(created) >= 0)


def test_generation_rate_close_to_configured_mean():
    traffic = load_config("default.json")["traffic"]
    counts = [len(generation_times(traffic, s, 100)) for s in range(1, 41)]
    # Poisson(60): mean of 40 draws lies within +-5 with overwhelming probability.
    assert abs(np.mean(counts) - 60) < 5


def test_every_message_lifetime_is_observed():
    cfg, scen = random_scenario(100, 1)
    msgs = scen.messages
    assert np.all(msgs.expiry - msgs.created == 900)
    assert msgs.expiry.max() <= cfg["simulation"]["duration_s"] - 1
    bad = apply_overrides(cfg, {"simulation.duration_s": 1700})
    try:
        validate_config(bad)
    except ConfigError:
        pass
    else:  # pragma: no cover
        raise AssertionError("config allowing truncated lifetimes was accepted")


def test_primary_workload_pairs_are_separated_friends():
    cfg, scen = random_scenario(100, 2)
    mob, msgs = scen.mobility, scen.messages
    for i in range(msgs.count):
        s, d, t = int(msgs.source[i]), int(msgs.destination[i]), int(msgs.created[i])
        assert s != d
        if msgs.relationship[i] == "separated_friends":
            assert mob.groups.group_of[s] == mob.groups.group_of[d] != -1
            assert (mob.sep_state[t, s] != SeparationState.WITH_GROUP
                    or mob.sep_state[t, d] != SeparationState.WITH_GROUP)


def test_random_workload_distinct_nodes_and_same_times():
    _, scen_r = random_scenario(100, 2, "random")
    _, scen_g = random_scenario(100, 2)
    assert np.array_equal(scen_r.messages.created, scen_g.messages.created)
    assert np.all(scen_r.messages.source != scen_r.messages.destination)
    assert set(scen_r.messages.relationship) <= {"random_same_group", "random_different_group"}
    # Mobility is shared between workloads.
    assert np.array_equal(scen_r.mobility.positions, scen_g.mobility.positions)


def test_workload_is_reproducible():
    from simulator.scenario import build_scenario
    cfg, scen = random_scenario(50, 3)
    again = build_scenario(cfg, 3)
    for f in ("source", "destination", "created"):
        assert np.array_equal(getattr(scen.messages, f), getattr(again.messages, f))


def test_delivery_at_expiry_boundary_counts_and_no_forwarding_after():
    cfg = small_config(duration=60, lifetime=30, generation_end=20, **{"routing__algorithm": "BSW"})
    # Message created at 5 expires at 35. Destination met exactly at 35 -> delivered (D15-style inclusive).
    scen = handcrafted_scenario(cfg, 3, {35: [(0, 2)]}, [(0, 2, 5)])
    out = run(cfg, scen)
    assert out.messages[0]["delivery_latency_s"] == 30
    # Contact one second after expiry -> never delivered.
    scen2 = handcrafted_scenario(cfg, 3, {36: [(0, 2)]}, [(0, 2, 5)])
    out2 = run(cfg, scen2)
    assert out2.messages[0]["first_delivery_time_s"] is None
    assert not transfers(out2)


def test_no_replication_at_expiry_second():
    cfg = small_config(**{"routing__algorithm": "Epidemic"})
    scen = handcrafted_scenario(cfg, 3, {35: [(0, 1)]}, [(0, 2, 5)])
    out = run(cfg, scen)
    assert out.metrics["intermediate_transfers"] == 0
    assert out.metrics["expired_replicas"] == 1
