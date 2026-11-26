"""Direct Delivery, Epidemic and Binary Spray-and-Wait behaviour on handcrafted scenarios."""

import numpy as np
import pytest

from algorithms.binary_spray_wait import binary_split
from tests.helpers import handcrafted_scenario, random_scenario, run, small_config, transfers
from simulator.config import apply_overrides


@pytest.mark.parametrize("tokens,give,keep", [(8, 4, 4), (5, 2, 3), (2, 1, 1), (16, 8, 8), (3, 1, 2)])
def test_binary_split(tokens, give, keep):
    assert binary_split(tokens) == (give, keep)


def test_bsw_eight_tokens_transfers_four():
    cfg = small_config(**{"routing__algorithm": "BSW"})
    scen = handcrafted_scenario(cfg, 3, {2: [(0, 1)]}, [(0, 2, 0)])
    out = run(cfg, scen)
    (e,) = transfers(out, "intermediate")
    assert (e[6], e[7], e[8]) == (8, 4, 4)


def test_bsw_five_tokens_transfers_two():
    cfg = small_config(**{"routing__algorithm": "BSW", "routing__copy_budget": 5})
    scen = handcrafted_scenario(cfg, 3, {2: [(0, 1)]}, [(0, 2, 0)])
    (e,) = transfers(run(cfg, scen), "intermediate")
    assert (e[6], e[7], e[8]) == (5, 3, 2)


def test_bsw_one_token_waits_but_still_delivers():
    cfg = small_config(**{"routing__algorithm": "BSW", "routing__copy_budget": 1})
    scen = handcrafted_scenario(cfg, 3, {2: [(0, 1)], 5: [(0, 2)]}, [(0, 2, 0)])
    out = run(cfg, scen)
    assert not transfers(out, "intermediate")
    assert out.messages[0]["first_delivery_time_s"] == 5
    assert out.decision_counts.get("BLOCK_ONE_TOKEN", 0) >= 1


def test_tokens_never_created_random_runs():
    for n, seed in ((50, 1), (100, 2)):
        cfg, scen = random_scenario(n, seed)
        for alg in ("BSW", "MWS"):
            for budget in (4, 8, 16):
                c = apply_overrides(cfg, {"routing.algorithm": alg, "routing.copy_budget": budget})
                m = run(c, scen, event_log=False).metrics
                assert m["token_conservation_ok"]
                # Each message can create at most budget-1 intermediate replicas.
                assert m["intermediate_transfers"] <= (budget - 1) * m["generated_messages"]


def test_failed_transfers_do_not_consume_tokens():
    cfg = small_config(**{"routing__algorithm": "BSW", "communication__transfer_failure_prob": 0.6})
    contacts = {t: [(0, 1)] for t in range(1, 25)}
    saw_failure_then_success = False
    for seed in range(10):
        scen = handcrafted_scenario(cfg, 3, contacts, [(0, 2, 0)], seed=seed)
        out = run(cfg, scen)
        relays = transfers(out, "intermediate")
        assert len(relays) <= 1
        if relays:
            # Whatever failed before, the success still splits the full 8 tokens.
            assert (relays[0][6], relays[0][7], relays[0][8]) == (8, 4, 4)
            assert out.metrics["failed_transfers"] == relays[0][0] - 1
            saw_failure_then_success |= out.metrics["failed_transfers"] > 0
        assert out.metrics["token_conservation_ok"]
    assert saw_failure_then_success


def test_store_carry_forward_without_end_to_end_path():
    """0 meets 1 at t=2, 1 walks away and meets 2 at t=10; 0 and 2 are never connected."""
    contacts = {2: [(0, 1)], 10: [(1, 2)]}
    for alg, delivered in (("DirectDelivery", False), ("Epidemic", True), ("BSW", True), ("MWS", True)):
        cfg = small_config(**{"routing__algorithm": alg})
        walking = np.ones((60, 3), dtype=bool)
        scen = handcrafted_scenario(cfg, 3, contacts, [(0, 2, 0)], walking=walking)
        out = run(cfg, scen)
        assert (out.messages[0]["first_delivery_time_s"] == 10) is delivered, alg
        if delivered:
            assert out.messages[0]["first_delivery_hops"] == 2


def test_no_multihop_within_one_step():
    """0-1 and 1-2 are in contact simultaneously: delivery to 2 takes at least two steps."""
    contacts = {t: [(0, 1), (1, 2)] for t in range(0, 10)}
    for alg in ("Epidemic", "BSW"):
        cfg = small_config(**{"routing__algorithm": alg})
        scen = handcrafted_scenario(cfg, 3, contacts, [(0, 2, 0)])
        out = run(cfg, scen)
        assert out.messages[0]["first_delivery_time_s"] == 1


def test_expired_messages_never_forwarded():
    cfg = small_config(**{"routing__algorithm": "Epidemic"})  # lifetime 30
    contacts = {t: [(0, 1), (1, 2)] for t in range(31, 60)}
    scen = handcrafted_scenario(cfg, 3, contacts, [(0, 2, 0)])
    out = run(cfg, scen)
    assert not transfers(out)
    assert out.metrics["expired_replicas"] == 1


def test_known_messages_not_rereplicated():
    cfg = small_config(**{"routing__algorithm": "Epidemic"})
    contacts = {t: [(0, 1)] for t in range(0, 20)}
    scen = handcrafted_scenario(cfg, 3, contacts, [(0, 2, 0)])
    out = run(cfg, scen)
    assert len(transfers(out)) == 1
    assert out.metrics["duplicate_opportunities_prevented"] > 0


def test_known_message_not_rereplicated_after_drop():
    cfg = small_config(**{"routing__algorithm": "Epidemic", "buffer__capacity_messages": 1})
    # Node 1 gets msg 0, then msg 1 evicts it; meeting node 0 again must not re-send msg 0.
    contacts = {2: [(0, 1)], 4: [(1, 3)], 8: [(0, 1)]}
    scen = handcrafted_scenario(cfg, 5, contacts, [(0, 4, 0), (3, 4, 1)])
    out = run(cfg, scen)
    sent_m0_to_1 = [e for e in transfers(out) if e[4] == 0 and e[3] == 1]
    assert len(sent_m0_to_1) == 1


def test_epidemic_floods_direct_only_delivers():
    cfg, scen = random_scenario(100, 1)
    epi = run(apply_overrides(cfg, {"routing.algorithm": "Epidemic"}), scen, event_log=False).metrics
    direct = run(apply_overrides(cfg, {"routing.algorithm": "DirectDelivery"}), scen, event_log=False).metrics
    assert direct["intermediate_transfers"] == 0
    assert direct["completed_transfers"] == direct["destination_transfers"] == direct["unique_delivered"]
    assert epi["intermediate_transfers"] > 10 * epi["generated_messages"]


def test_all_algorithms_receive_identical_inputs():
    from experiments.runner import RunSpec, execute_task
    import tempfile, json
    from pathlib import Path
    cfg, _ = random_scenario(50, 1)
    cfg = apply_overrides(cfg, {"output.save_scenarios": False})
    specs = [RunSpec(f"r{i}", f"c{i}", 1, apply_overrides(cfg, {"routing.algorithm": a}), "development")
             for i, a in enumerate(("DirectDelivery", "Epidemic", "BSW", "MWS"))]
    with tempfile.TemporaryDirectory() as tmp:
        res = execute_task({"root": tmp, "runs": specs})
        assert all(r["status"] == "ok" for r in res)
        hashes = {json.loads((Path(tmp) / "raw" / "runs" / f"r{i}.json").read_text())["scenario_hash"]
                  for i in range(4)}
    assert len(hashes) == 1
