"""MWS rule behaviour (R1 friend exclusion, R2 walker preference, R3 patience fallback)."""

import numpy as np
import pytest

from algorithms.base import AlgorithmContext
from algorithms.variants import build_algorithm
from simulator.config import apply_overrides, configuration_id
from simulator.motion import historical_walking, observed_walking
from tests.helpers import (handcrafted_scenario, random_scenario, run, same_metrics, small_config, transfers,
                           walking_matrix)

T = 200


def mws_cfg(**kw):
    base = {"routing__algorithm": "MWS"}
    base.update(kw)
    return small_config(duration=T, lifetime=150, generation_end=20, **base)


def test_destination_delivery_overrides_friend_exclusion():
    cfg = mws_cfg()
    scen = handcrafted_scenario(cfg, 2, {2: [(0, 1)]}, [(0, 1, 0)], groups=[[0, 1]])
    out = run(cfg, scen)
    assert out.messages[0]["first_delivery_time_s"] == 2


def test_walking_non_friend_is_eligible():
    cfg = mws_cfg()
    scen = handcrafted_scenario(cfg, 3, {2: [(0, 1)]}, [(0, 2, 0)], walking=walking_matrix(T, 3, [1]))
    out = run(cfg, scen)
    (e,) = transfers(out, "intermediate")
    assert e[3] == 1 and e[12] == "MWS_WALKER" and e[9] is True and e[10] is False


def test_friend_is_ineligible_even_when_walking():
    cfg = mws_cfg()
    contacts = {t: [(0, 1)] for t in range(2, 120)}
    scen = handcrafted_scenario(cfg, 3, contacts, [(0, 2, 0)], walking=walking_matrix(T, 3, [1]),
                                groups=[[0, 1]])
    out = run(cfg, scen)
    assert not transfers(out, "intermediate")
    assert out.decision_counts["BLOCK_FRIEND"] > 0


def test_stationary_stranger_ineligible_before_60s_eligible_at_60s():
    cfg = mws_cfg()
    contacts = {t: [(0, 1)] for t in range(0, 100)}
    scen = handcrafted_scenario(cfg, 3, contacts, [(0, 2, 5)])  # created at 5
    out = run(cfg, scen)
    (e,) = transfers(out, "intermediate")
    assert e[0] == 65 and e[11] == 60 and e[12] == "MWS_FALLBACK"
    assert out.decision_counts["BLOCK_STATIONARY"] == 60  # ages 0..59


def test_friend_stays_ineligible_after_60s():
    cfg = mws_cfg()
    contacts = {t: [(0, 1)] for t in range(0, 150)}
    scen = handcrafted_scenario(cfg, 3, contacts, [(0, 2, 0)], groups=[[0, 1]])
    out = run(cfg, scen)
    assert not transfers(out, "intermediate")


def test_one_token_carrier_cannot_spray_to_walking_stranger():
    cfg = mws_cfg(routing__copy_budget=1)
    scen = handcrafted_scenario(cfg, 3, {2: [(0, 1)]}, [(0, 2, 0)], walking=walking_matrix(T, 3, [1]))
    out = run(cfg, scen)
    assert not transfers(out, "intermediate")
    assert out.decision_counts["BLOCK_ONE_TOKEN"] == 1


def test_duplicate_suppression_runs_before_replication_rules():
    cfg = mws_cfg()
    contacts = {t: [(0, 1)] for t in range(2, 30)}
    scen = handcrafted_scenario(cfg, 3, contacts, [(0, 2, 0)], walking=walking_matrix(T, 3, [0, 1]))
    out = run(cfg, scen)
    assert len(transfers(out, "intermediate")) == 1
    # After t=2 node 1 knows the message: the MWS rules are never consulted again for it.
    assert out.decision_counts == {"MWS_WALKER": 1}
    assert out.metrics["duplicate_opportunities_prevented"] > 0


def test_age_measured_from_original_creation():
    cfg = mws_cfg()
    contacts = {50: [(0, 1)], **{t: [(1, 2)] for t in range(55, 70)}}
    scen = handcrafted_scenario(cfg, 4, contacts, [(0, 3, 0)], walking=walking_matrix(T, 4, [1]))
    out = run(cfg, scen)
    relays = transfers(out, "intermediate")
    assert [(e[0], e[2], e[3]) for e in relays] == [(50, 0, 1), (60, 1, 2)]
    assert relays[1][12] == "MWS_FALLBACK" and relays[1][11] == 60


def test_all_rules_disabled_equals_bsw():
    cfg, scen = random_scenario(100, 1)
    bsw = apply_overrides(cfg, {"routing.algorithm": "BSW"})
    off = apply_overrides(cfg, {"routing.algorithm": "MWS", "routing.mws.friend_exclusion": False,
                                "routing.mws.walker_preference": False, "routing.mws.patience_fallback": False})
    assert configuration_id(bsw) == configuration_id(off)
    m1 = run(bsw, scen, event_log=False).metrics
    m2 = run(off, scen, event_log=False).metrics
    assert {k: v for k, v in m1.items() if k != "routing_runtime_s"} == \
           {k: v for k, v in m2.items() if k != "routing_runtime_s"}


@pytest.mark.parametrize("r1,r2,r3", [(True, False, False), (False, True, False), (True, True, False),
                                      (False, True, True), (True, True, True)])
def test_ablation_rules_behave_as_specified(r1, r2, r3):
    cfg, scen = random_scenario(100, 1)
    c = apply_overrides(cfg, {"routing.algorithm": "MWS", "routing.mws.friend_exclusion": r1,
                              "routing.mws.walker_preference": r2, "routing.mws.patience_fallback": r3})
    out = run(c, scen)
    relays = transfers(out, "intermediate")
    assert relays
    friends = [e for e in relays if e[10]]
    if r1:
        assert not friends
    if r2:
        stationary = [e for e in relays if not e[9]]
        if r3:
            assert all(e[11] >= 60 for e in stationary)
        else:
            assert not stationary
    else:
        assert {e[12] for e in relays} == {"MWS_NO_MOTION_RULE"}


def test_immediate_and_historical_differ_only_in_motion_signal():
    cfg, scen = random_scenario(100, 1)
    imm = apply_overrides(cfg, {"routing.algorithm": "MWS", "routing.mws.motion_signal": "immediate"})
    hist = apply_overrides(cfg, {"routing.algorithm": "MWS", "routing.mws.motion_signal": "historical"})
    a, b = build_algorithm(imm, scen), build_algorithm(hist, scen)
    da, db = a.describe(), b.describe()
    assert da.pop("motion_signal") == "immediate" and db.pop("motion_signal") == "historical"
    assert da == db
    assert a.ctx.friend_group is b.ctx.friend_group and a.ctx.created is b.ctx.created
    sig_a, sig_b = a.ctx.motion._signal, b.ctx.motion._signal
    assert sig_a.shape == sig_b.shape and not np.array_equal(sig_a, sig_b)
    # With motion that never changes, the two signals coincide and so do the results.
    w = walking_matrix(T, 4, [1])
    contacts = {t: [(0, 1), (1, 2)] for t in range(3, 9)}
    c1 = mws_cfg(routing__mws__motion_signal="immediate")
    c2 = mws_cfg(routing__mws__motion_signal="historical")
    s = handcrafted_scenario(c1, 4, contacts, [(0, 3, 0)], walking=w)
    assert run(c1, s).metrics["intermediate_transfers"] == run(c2, s).metrics["intermediate_transfers"]


def test_historical_signal_uses_only_past_observations():
    rng = np.random.default_rng(0)
    obs = rng.random((400, 5)) < 0.3
    h = historical_walking(obs, 300, 0.5)
    obs2 = obs.copy()
    obs2[201:] = ~obs2[201:]  # change the future only
    h2 = historical_walking(obs2, 300, 0.5)
    assert np.array_equal(h[:201], h2[:201])
    # Score is the trailing proportion including t.
    t, n = 350, 2
    assert h[t, n] == (obs[t - 299:t + 1, n].mean() >= 0.5)


def test_motion_errors_shared_nested_and_at_rate():
    rng = np.random.default_rng(1)
    true = rng.random((2000, 50)) < 0.3
    e10 = observed_walking(true, 0.1, "independent", 5, seed=9)
    e20 = observed_walking(true, 0.2, "independent", 5, seed=9)
    f10, f20 = e10 ^ true, e20 ^ true
    assert abs(f10.mean() - 0.1) < 0.01 and abs(f20.mean() - 0.2) < 0.01
    assert np.all(f20[f10])  # 10 % flips are a subset of 20 % flips (common random numbers)
    assert np.array_equal(observed_walking(true, 0.1, "independent", 5, seed=9), e10)
    corr = observed_walking(true, 0.2, "correlated", 5, seed=9) ^ true
    assert abs(corr.mean() - 0.2) < 0.03
    # Correlated errors come in bursts: mean run length > independent case.
    def mean_run(f):
        runs = np.diff(np.flatnonzero(np.diff(np.r_[0, f[:, 0].astype(int), 0])))[::2]
        return runs.mean()
    assert mean_run(corr) > mean_run(f20) * 2


def test_algorithms_cannot_see_delivery_records():
    fields = set(AlgorithmContext.__dataclass_fields__)
    assert fields == {"friend_group", "created", "motion"}
