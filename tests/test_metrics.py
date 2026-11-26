"""Metric definitions on known inputs."""

import math

import numpy as np

from simulator.config import apply_overrides
from simulator.metrics import delivery_counts, percent
from tests.helpers import handcrafted_scenario, random_scenario, run, small_config


def test_known_timestamps_give_correct_d2_d5_d15():
    created = np.array([0, 10, 20, 30, 40, 50])
    delivered = np.array([100, 130, 141, 330, 940, -1])  # latencies 100,120,121,300,900,undelivered
    c = delivery_counts(created, delivered, {"d2": 120, "d5": 300, "d15": 900})
    assert c == {"d2": 2, "d5": 4, "d15": 5}
    # Undelivered messages remain in the denominator.
    assert math.isclose(percent(c["d5"], 6), 66.6666666, rel_tol=1e-6)
    assert math.isclose(percent(c["d15"], 6), 83.3333333, rel_tol=1e-6)


def test_engine_metrics_on_handcrafted_chain():
    cfg = small_config(**{"routing__algorithm": "Epidemic"})
    # msg0: 0 -> 1 (t=2) -> 2 (t=10); msg1 never delivered.
    scen = handcrafted_scenario(cfg, 4, {2: [(0, 1)], 10: [(1, 2)]}, [(0, 2, 0), (3, 2, 0)])
    out = run(cfg, scen)
    m = out.metrics
    assert m["generated_messages"] == 2 and m["unique_delivered"] == 1
    assert m["d5_percent"] == 50.0 and m["d15_percent"] == 50.0
    assert m["completed_transfers"] == 2
    assert m["intermediate_transfers"] == 1 and m["destination_transfers"] == 1
    assert m["transfers_per_message"] == 1.0
    assert m["mean_latency_s"] == 10 and m["mean_delivery_hops"] == 2
    rows = out.messages
    assert rows[0]["delivered_within_5min"] and rows[0]["completed_transfers_for_message"] == 2
    assert rows[1]["final_status"] == "undelivered_expired" and rows[1]["delivery_latency_s"] is None
    assert m["undelivered_messages"] == 1


def test_unique_deliveries_not_double_counted():
    cfg = small_config(**{"routing__algorithm": "Epidemic"})
    # Two carriers (0 and 1) meet the destination 2 in the same second.
    scen = handcrafted_scenario(cfg, 3, {2: [(0, 1)], 5: [(0, 2), (1, 2)], 6: [(0, 2)]}, [(0, 2, 0)])
    m = run(cfg, scen).metrics
    assert m["unique_delivered"] == 1 and m["destination_transfers"] == 1
    assert m["repeated_destination_receptions"] == 0
    assert m["duplicate_opportunities_prevented"] >= 2


def test_prevented_duplicates_are_not_transfers():
    cfg = small_config(**{"routing__algorithm": "Epidemic"})
    scen = handcrafted_scenario(cfg, 3, {t: [(0, 1)] for t in range(0, 25)}, [(0, 2, 0)])
    m = run(cfg, scen).metrics
    assert m["completed_transfers"] == 1
    assert m["duplicate_opportunities_prevented"] > 20


def test_identical_config_and_seed_reproduce_identical_metrics():
    cfg, scen = random_scenario(50, 3)
    from simulator.scenario import build_scenario
    scen2 = build_scenario(cfg, 3)
    for alg in ("DirectDelivery", "Epidemic", "BSW", "MWS"):
        c = apply_overrides(cfg, {"routing.algorithm": alg})
        a = run(c, scen, event_log=False)
        b = run(c, scen2, event_log=False)
        strip = lambda d: {k: v for k, v in d.items() if k != "routing_runtime_s"}  # noqa: E731
        assert strip(a.metrics) == strip(b.metrics)
        assert a.messages == b.messages


def test_t_counts_both_transfer_kinds_and_matches_message_rows():
    cfg, scen = random_scenario(100, 2)
    out = run(apply_overrides(cfg, {"routing.algorithm": "BSW"}), scen, event_log=False)
    m = out.metrics
    assert m["completed_transfers"] == m["intermediate_transfers"] + m["destination_transfers"]
    assert sum(r["completed_transfers_for_message"] for r in out.messages) == m["completed_transfers"]
    assert m["destination_transfers"] == m["unique_delivered"]
    delivered = [r for r in out.messages if r["first_delivery_time_s"] is not None]
    assert sum(r["delivered_within_5min"] for r in out.messages) == m["delivered_5min"]
    assert len(delivered) == m["unique_delivered"]
