"""Metric definitions on known inputs."""

import math

import numpy as np

from simulator.config import apply_overrides
from simulator.metrics import delivery_counts, percent
from tests.helpers import handcrafted_scenario, random_scenario, run, same_metrics, small_config


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
        assert same_metrics(a.metrics, b.metrics)
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


def test_spray_efficiency_metrics_on_handcrafted_chain():
    """L = 4: relays at t=2 (4->2+2), t=4 and t=6 (2->1+1); delivery at t=10."""
    cfg = small_config(**{"routing__algorithm": "BSW", "routing__copy_budget": 4})
    contacts = {2: [(0, 1)], 4: [(0, 2)], 6: [(1, 4)], 10: [(4, 3)]}
    out = run(cfg, handcrafted_scenario(cfg, 6, contacts, [(0, 3, 0)]))
    m, row = out.metrics, out.messages[0]
    assert row["first_relay_age_s"] == 2 and m["mean_time_to_first_relay_s"] == 2
    assert row["half_copies_age_s"] == 2          # ceil(4/2) = 2 copies after the first relay
    assert row["spray_complete_age_s"] == 6       # every remaining replica holds one token from t=6
    assert m["pct_messages_spray_complete"] == 100.0 and m["copy_budget_utilization"] == 1.0
    assert row["relays_before_first_delivery"] == 3 and row["relays_after_first_delivery"] == 0
    assert m["timely_deliveries_per_100_transfers"] == 25.0   # 1 timely delivery / 4 completed transfers
    assert m["intermediate_transfers_per_delivered_message"] == 3.0


def test_relays_after_delivery_and_undefined_metrics():
    cfg = small_config(**{"routing__algorithm": "Epidemic"})
    contacts = {2: [(0, 3)], 4: [(0, 1)]}
    out = run(cfg, handcrafted_scenario(cfg, 5, contacts, [(0, 3, 0), (2, 4, 0)]))
    m = out.metrics
    assert m["relays_after_first_delivery"] == 1          # copy to node 1 after the friend already had it
    assert m["relays_on_undelivered_messages"] == 0
    assert math.isnan(m["copy_budget_utilization"])        # not a token algorithm: undefined, never 0
    assert math.isnan(m["mean_time_to_spray_complete_s"])
    none = run(cfg, handcrafted_scenario(cfg, 3, {}, [(0, 2, 0)])).metrics
    assert math.isnan(none["intermediate_transfers_per_delivered_message"])   # no delivered message
    assert math.isnan(none["timely_deliveries_per_100_transfers"])            # no completed transfer


def test_workload_diagnostics_are_evaluation_only():
    from algorithms.base import AlgorithmContext
    cfg = small_config(**{"routing__algorithm": "Epidemic"})
    contacts = {0: [(0, 3)], 3: [(1, 2)], 6: [(2, 4)]}
    scen = handcrafted_scenario(cfg, 5, contacts, [(0, 3, 0), (1, 4, 0)])
    assert scen.messages.in_range_at_creation.tolist() == [True, False]
    assert scen.messages.first_direct_contact.tolist() == [0, -1]
    out = run(cfg, scen)
    r0, r1 = out.messages
    assert r0["dest_in_range_at_creation"] and not r0["delivered_via_relay"]
    assert not r1["dest_in_range_at_creation"] and r1["delivered_via_relay"] and r1["delivered_before_first_direct_contact"]
    assert out.metrics["d5_percent_dest_in_range"] == 100.0 and out.metrics["pct_delivered_via_relay"] == 50.0
    assert set(AlgorithmContext.__dataclass_fields__) == {"friend_group", "created", "motion"}  # no future info
