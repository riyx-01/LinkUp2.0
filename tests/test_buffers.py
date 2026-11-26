"""Buffer policy, transfer capacity, atomic acceptance and token loss on drops."""

from collections import Counter

from tests.helpers import handcrafted_scenario, random_scenario, run, small_config, transfers
from simulator.config import apply_overrides


def test_buffer_capacity_never_exceeded_epidemic():
    cfg, scen = random_scenario(100, 1)
    c = apply_overrides(cfg, {"routing.algorithm": "Epidemic", "buffer.capacity_messages": 10})
    out = run(c, scen, event_log=False)
    assert out.metrics["max_buffer_occupancy"] <= 10
    assert out.metrics["buffer_drops"] > 0


def test_transfer_capacity_never_exceeded():
    cfg, scen = random_scenario(100, 1)
    for alg in ("Epidemic", "BSW", "MWS"):
        c = apply_overrides(cfg, {"routing.algorithm": alg})
        out = run(c, scen)
        per_node_step = Counter()
        for e in transfers(out):
            per_node_step[(e[0], e[2])] += 1
            per_node_step[(e[0], e[3])] += 1
        assert max(per_node_step.values()) <= 5


def test_capacity_one_limits_transfers_and_delivery_has_priority():
    cfg = small_config(**{"routing__algorithm": "Epidemic", "communication__transfer_capacity_per_node_per_s": 1})
    # Node 0 holds msg A (to node 1) and msg B (to node 3). At t=10 it meets 1 (destination of A)
    # and 2 (a relay for B). Capacity 1: the destination delivery must win.
    scen = handcrafted_scenario(cfg, 4, {10: [(0, 1), (0, 2)]}, [(0, 1, 0), (0, 3, 0)])
    out = run(cfg, scen)
    xs = transfers(out)
    assert len(xs) == 1 and xs[0][5] == "destination" and xs[0][3] == 1
    assert out.metrics["capacity_blocked_opportunities"] >= 1


def test_drop_oldest_created_and_tokens_lost():
    cfg = small_config(**{"routing__algorithm": "BSW", "buffer__capacity_messages": 2})
    # Node 1 sources msgs 0 (created 0) and 1 (created 1), both destined to node 2, so its buffer
    # is full. At t=8 it meets node 2: both deliveries happen first (priority), then node 2 sprays
    # msg 2 (created 2) to node 1, which must evict the oldest-created replica (msg 0, 8 tokens).
    contacts = {8: [(1, 2)]}
    msgs = [(1, 2, 0), (1, 2, 1), (2, 3, 2)]
    scen = handcrafted_scenario(cfg, 4, contacts, msgs)
    out = run(cfg, scen)
    drops = [e for e in out.events if e[1] == "drop"]
    assert len(drops) == 1
    t, _, node, _, m, cause, tokens = drops[0][:7]
    assert (t, node, m, cause, tokens) == (8, 1, 0, "incoming_transfer", 8)
    assert out.metrics["tokens_lost_buffer_drops"] == 8
    assert out.metrics["token_conservation_ok"]
    # Tokens of the dropped replica are not recreated anywhere.
    assert out.metrics["delivered_15min"] == 2


def test_rejected_incoming_does_not_cost_sender():
    cfg = small_config(**{"routing__algorithm": "BSW", "buffer__capacity_messages": 1})
    # Node 1 stores a *newer* message (msg 1, created 3, destined to node 0). At t=6 node 1 delivers
    # msg 1 to node 0 (priority), then the older msg 0 (created 0) from node 0 is rejected by node 1.
    contacts = {4: [(2, 1)], 6: [(0, 1)], 8: [(0, 4)]}
    msgs = [(0, 3, 0), (2, 0, 3)]
    scen = handcrafted_scenario(cfg, 5, contacts, msgs)
    out = run(cfg, scen)
    assert out.metrics["rejected_transfers"] == 1
    # Sender 0 kept its full 8 tokens: at t=8 it sprays to node 4 giving 4 tokens.
    t8 = [e for e in transfers(out) if e[0] == 8]
    assert len(t8) == 1 and t8[0][6] == 8 and t8[0][8] == 4


def test_source_injection_evicts_when_full():
    cfg = small_config(**{"routing__algorithm": "Epidemic", "buffer__capacity_messages": 1})
    scen = handcrafted_scenario(cfg, 3, {}, [(0, 1, 0), (0, 2, 3)])
    out = run(cfg, scen)
    assert out.metrics["buffer_drops"] == 1
    assert out.metrics["max_buffer_occupancy"] == 1
