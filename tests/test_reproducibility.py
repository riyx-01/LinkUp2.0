"""Seeds, scenario sharing, configuration equivalence, phase separation and resumable batches."""

import json

import numpy as np
import pandas as pd
import pytest

from experiments import approval
from experiments.matrix import build_matrix, check_phase_seeds
from experiments.runner import load_phase_config, run_batch
from simulator.config import apply_overrides, configuration_id, load_config
from simulator.rng import hash_keys, stream
from simulator.scenario import Scenario, build_scenario
from tests.helpers import random_scenario, run


def test_scenario_independent_of_algorithm_choice():
    cfg = apply_overrides(load_config("default.json"), {"nodes.node_count": 50})
    hashes = {build_scenario(apply_overrides(cfg, {"routing.algorithm": a}), 5).scenario_hash
              for a in ("DirectDelivery", "Epidemic", "BSW", "MWS")}
    assert len(hashes) == 1


def test_density_specific_independent_streams():
    a = stream(1, "mobility", 50).random(5)
    b = stream(1, "mobility", 100).random(5)
    c = stream(1, "separation", 50).random(5)
    assert not np.allclose(a, b) and not np.allclose(a, c)
    assert np.array_equal(a, stream(1, "mobility", 50).random(5))


def test_scheduling_keys_deterministic_and_algorithm_free():
    base = np.uint64(12345)
    k1 = hash_keys(base, np.array([3, 3]), np.array([1, 2]), np.array([4, 4]), np.array([5, 5]))
    k2 = hash_keys(base, np.array([3]), np.array([2]), np.array([4]), np.array([5]))
    assert k1[1] == k2[0] and k1[0] != k1[1]


def test_scenario_save_load_roundtrip(tmp_path):
    cfg, scen = random_scenario(50, 2)
    scen.observed_motion(0.1, "independent", 5)
    path = tmp_path / "s.npz"
    scen.save(path)
    loaded = Scenario.load(path)
    assert loaded.scenario_hash == scen.scenario_hash
    c = apply_overrides(cfg, {"routing.algorithm": "MWS"})
    a, b = run(c, scen, event_log=False).metrics, run(c, loaded, event_log=False).metrics
    assert a["d5_percent"] == b["d5_percent"] and a["completed_transfers"] == b["completed_transfers"]


def test_equivalent_configurations_share_ids():
    cfg = load_phase_config("confirmatory")
    matrix = build_matrix(cfg)
    assert matrix.unique_count == 25
    assert matrix.new_configs_per_experiment() == {"E1": 12, "E2": 4, "E3": 4, "E4": 1, "E5": 2, "E6": 2}
    full = apply_overrides(cfg, {"nodes.node_count": 100, "routing.algorithm": "MWS"})
    assert set(matrix.experiment_ids_for(configuration_id(full))) == {"E1", "E2", "E3", "E4", "E5", "E6"}
    # Fallback without walker preference has no effect and is normalised away.
    r1_only = apply_overrides(full, {"routing.mws.walker_preference": False, "routing.mws.patience_fallback": False})
    r1_r3 = apply_overrides(full, {"routing.mws.walker_preference": False, "routing.mws.patience_fallback": True})
    assert configuration_id(r1_only) == configuration_id(r1_r3)
    # BSW ignores the motion error rate; MWS does not.
    bsw = apply_overrides(full, {"routing.algorithm": "BSW"})
    assert configuration_id(bsw) == configuration_id(apply_overrides(bsw, {"motion_classification.error_rate": 0.2}))
    assert configuration_id(full) != configuration_id(apply_overrides(full, {"motion_classification.error_rate": 0.2}))


def test_phase_seed_ranges_are_enforced():
    check_phase_seeds("pilot", [101, 105])
    check_phase_seeds("confirmatory", [1001, 1030])
    with pytest.raises(ValueError):
        check_phase_seeds("confirmatory", [101])
    with pytest.raises(ValueError):
        check_phase_seeds("pilot", [1001])
    assert not set(load_config("pilot.json")["seeds"]) & set(load_config("confirmatory.json")["seeds"])


def test_confirmatory_requires_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(approval, "APPROVAL_PATH", tmp_path / "missing.json")
    with pytest.raises(approval.ApprovalError):
        run_batch("confirmatory", ["E4"], root=tmp_path, progress=False)


def test_approval_detects_config_change(tmp_path, monkeypatch):
    path = tmp_path / "approval.json"
    monkeypatch.setattr(approval, "APPROVAL_PATH", path)
    record = approval.freeze("Test Approver")
    assert path.exists() and record["approved_by"] == "Test Approver"
    approval.verify_approval()
    tampered = dict(record, confirmatory_config_sha256="0" * 64)
    path.write_text(json.dumps(tampered))
    with pytest.raises(approval.ApprovalError):
        approval.verify_approval()


def test_batch_is_resumable_and_detects_missing_runs(tmp_path):
    summary = run_batch("development", ["E4"], seeds=[1], root=tmp_path, progress=False,
                        representative_event_logs=False)
    assert summary["executed_runs"] == 2 and summary["failed_runs"] == 0
    with pytest.raises(RuntimeError):
        run_batch("development", ["E4"], seeds=[1], root=tmp_path, progress=False)
    again = run_batch("development", ["E4"], seeds=[1], root=tmp_path, resume=True, progress=False)
    assert again["executed_runs"] == 0 and again["reused_runs"] == 2
    runs_dir = tmp_path / "development" / "raw" / "runs"
    victim = sorted(runs_dir.glob("*.json"))[0]
    victim.unlink()
    third = run_batch("development", ["E4"], seeds=[1], root=tmp_path, resume=True, progress=False)
    assert third["executed_runs"] == 1
    df = pd.read_csv(tmp_path / "development" / "processed" / "run_results.csv")
    assert len(df) == 2 and set(df["run_status"]) == {"ok"}
    assert df["scenario_hash"].nunique() == 1
    memberships = [set(e.split("|")) for e in df["experiment_id"]]
    assert all("E4" in m for m in memberships)
    assert any({"E1", "E2", "E3", "E5", "E6"} <= m for m in memberships)  # shared Full-MWS config
