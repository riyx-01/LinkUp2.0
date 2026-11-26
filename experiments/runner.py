"""Configuration-driven, resumable batch execution.

Execution model
---------------
* Runs are grouped into *tasks* by mobility key (seed, node count, mobility
  parameters). A task generates the mobility trace once, derives each needed
  scenario (radius x workload) once, runs every algorithm configuration on it,
  and releases it - so traces are shared but never all held in RAM.
* Each run writes its own JSON (metrics + provenance) and message CSV as soon
  as it finishes (incremental saving). Completed runs are skipped on resume;
  failed runs are recorded (never silently dropped) and retried on resume.
* Tasks run serially (debug mode, ``workers=1``) or in a process pool.
* Simulated time is virtual: nothing here sleeps.
"""

from __future__ import annotations

import csv
import json
import logging
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from simulator.config import (CONFIG_DIR, PROJECT_ROOT, effective_config, effective_routing,
                              full_config_hash, load_config, mobility_key, stable_hash,
                              validate_config, variant_label)
from simulator.engine import EVENT_FIELDS, RoutingEngine
from simulator.mobility import generate_mobility
from simulator.scenario import build_scenario, scenario_id_for

from .approval import verify_approval
from .matrix import Matrix, build_matrix, check_phase_seeds
from .provenance import code_version, provenance_record

PHASE_CONFIG = {"development": "default.json", "pilot": "pilot.json", "confirmatory": "confirmatory.json"}
RESULTS_ROOT = PROJECT_ROOT / "results"
log = logging.getLogger("linkup.runner")


def phase_dir(phase: str, root: Path | None = None) -> Path:
    return (root or RESULTS_ROOT) / phase


def load_phase_config(phase: str) -> dict:
    cfg = load_config(CONFIG_DIR / PHASE_CONFIG[phase])
    validate_config(cfg)
    if cfg.get("phase") != phase:
        raise ValueError(f"Config for phase '{phase}' declares phase '{cfg.get('phase')}'.")
    return cfg


@dataclass
class RunSpec:
    run_id: str
    configuration_id: str
    seed: int
    cfg: dict
    phase: str


def plan_runs(matrix: Matrix, seeds: list[int], phase: str) -> list[RunSpec]:
    runs = []
    for cid, cfg in matrix.configs.items():
        for seed in seeds:
            runs.append(RunSpec(f"{cid}_s{seed}", cid, int(seed), cfg, phase))
    return runs


def run_json_path(root: Path, run_id: str) -> Path:
    return root / "raw" / "runs" / f"{run_id}.json"


def run_status(root: Path, run_id: str) -> str | None:
    path = run_json_path(root, run_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("run_status")
    except (OSError, json.JSONDecodeError):
        return "corrupt"


def _write_csv(path: Path, rows: list[dict] | list[tuple], header: list[str] | tuple) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for row in rows:
            writer.writerow([row.get(h) for h in header] if isinstance(row, dict) else row)
    tmp.replace(path)


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=_json_default), encoding="utf-8")
    tmp.replace(path)


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def describe_run(spec: RunSpec) -> dict:
    cfg = spec.cfg
    eff = effective_routing(cfg)
    return {
        "run_id": spec.run_id, "configuration_id": spec.configuration_id, "phase": spec.phase,
        "algorithm": eff["algorithm"], "variant": variant_label(cfg), "seed": spec.seed,
        "node_count": cfg["nodes"]["node_count"], "venue_width_m": cfg["venue"]["width_m"],
        "venue_height_m": cfg["venue"]["height_m"], "simulation_duration_s": cfg["simulation"]["duration_s"],
        "communication_radius_m": cfg["communication"]["radius_m"],
        "copy_budget": eff.get("copy_budget"),
        "fallback_s": eff.get("mws", {}).get("fallback_s"),
        "motion_error_rate": eff.get("mws", {}).get("motion_error_rate"),
        "motion_signal": eff.get("mws", {}).get("motion_signal"),
        "workload_type": cfg["traffic"]["workload_type"],
        "mean_interarrival_s": cfg["traffic"]["mean_interarrival_s"],
        "min_separation_s": cfg["mobility"]["min_separation_s"],
        "rejoin_policy": cfg["mobility"]["rejoin_policy"],
    }


# --------------------------------------------------------------------------- #
# Task execution (runs inside worker processes)
# --------------------------------------------------------------------------- #
def execute_task(task: dict) -> list[dict]:
    """Run every RunSpec of one mobility group. Returns status dicts."""
    root = Path(task["root"])
    specs: list[RunSpec] = task["runs"]
    event_log_ids = set(task.get("event_log_run_ids", []))
    prov = provenance_record()
    statuses = []
    seed, cfg0 = specs[0].seed, specs[0].cfg
    mobility, mob_time, mob_error = None, 0.0, None
    try:
        t0 = time.perf_counter()
        mobility = generate_mobility(cfg0, cfg0["nodes"]["node_count"], seed)
        mob_time = time.perf_counter() - t0
    except Exception:  # noqa: BLE001 - recorded as failed runs
        mob_error = traceback.format_exc()

    scenarios: dict[str, tuple] = {}
    for spec in specs:
        base = describe_run(spec)
        record = {**base, "run_status": "failed", "error_message": None, "code_version": prov["code_version"],
                  "provenance": prov, "effective_config": effective_config(spec.cfg),
                  "full_config": spec.cfg, "configuration_hash": spec.configuration_id,
                  "full_config_sha256": full_config_hash(spec.cfg)}
        try:
            if mob_error:
                raise RuntimeError("Mobility generation failed:\n" + mob_error)
            sid = scenario_id_for(spec.cfg, spec.seed)
            if sid not in scenarios:
                t1 = time.perf_counter()
                scen = build_scenario(spec.cfg, spec.seed, mobility)
                scenarios[sid] = (scen, time.perf_counter() - t1 + mob_time, spec.cfg)
            scen, scen_time, _ = scenarios[sid]
            want_events = bool(spec.cfg["output"]["event_log"]) or spec.run_id in event_log_ids
            engine = RoutingEngine(spec.cfg, scen, event_log=want_events)
            out = engine.run()
            record.update(out.metrics)
            record.update({
                "run_status": "ok", "runtime_s": out.metrics["routing_runtime_s"],
                "scenario_generation_s": scen_time, "scenario_id": sid, "scenario_hash": scen.scenario_hash,
                "avg_neighbour_count": scen.validation.get("avg_neighbours_per_node"),
                "workload_fallback_count": scen.validation.get("workload_fallback_count"),
                "decision_counts": out.decision_counts, "transfer_reasons": out.transfer_reasons,
                "motion_oracle": getattr(getattr(engine.algo.ctx, "motion", None), "description", None),
                "algorithm_description": engine.algo.describe(),
            })
            if not out.metrics["token_conservation_ok"]:
                raise AssertionError("Token conservation check failed.")
            if spec.cfg["output"]["message_results"]:
                _write_csv(root / "raw" / "messages" / f"{spec.run_id}.csv", out.messages,
                           list(out.messages[0].keys()) if out.messages else ["message_id"])
            if want_events:
                _write_csv(root / "raw" / "events" / f"{spec.run_id}.csv", out.events, EVENT_FIELDS)
        except Exception as exc:  # noqa: BLE001 - failures are recorded, never hidden
            record["run_status"] = "failed"
            record["error_message"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        _write_json(run_json_path(root, spec.run_id), record)
        statuses.append({"run_id": spec.run_id, "status": record["run_status"],
                         "error": record["error_message"], "runtime_s": record.get("runtime_s")})

    for sid, (scen, gen_time, cfg) in scenarios.items():
        summary = {"scenario_id": sid, "scenario_hash": scen.scenario_hash, "seed": scen.seed,
                   "node_count": scen.node_count, "communication_radius_m": cfg["communication"]["radius_m"],
                   "workload_type": cfg["traffic"]["workload_type"], "generation_s": gen_time,
                   "mean_interarrival_s": cfg["traffic"]["mean_interarrival_s"],
                   "min_separation_s": cfg["mobility"]["min_separation_s"],
                   "rejoin_policy": cfg["mobility"]["rejoin_policy"],
                   "mobility_key": stable_hash(mobility_key(cfg, scen.seed)), "validation": scen.validation}
        _write_json(root / "raw" / "scenarios" / f"{sid}.json", summary)
        if cfg["output"]["save_scenarios"]:
            path = root / "scenarios" / f"{sid}.npz"
            if not path.exists():
                scen.save(path, save_positions=bool(cfg["output"]["save_positions"]))
    return statuses


def group_tasks(runs: list[RunSpec], root: Path, event_log_ids: set[str]) -> list[dict]:
    groups: dict[str, list[RunSpec]] = {}
    for spec in runs:
        key = stable_hash(mobility_key(spec.cfg, spec.seed))
        groups.setdefault(key, []).append(spec)
    # Larger tasks first for better pool load balance.
    ordered = sorted(groups.values(), key=lambda g: (-g[0].cfg["nodes"]["node_count"] * len(g), g[0].seed))
    return [{"root": str(root), "runs": g, "event_log_run_ids": sorted(event_log_ids)} for g in ordered]


# --------------------------------------------------------------------------- #
# Batch entry point
# --------------------------------------------------------------------------- #
def run_batch(phase: str, experiment_ids: list[str] | None = None, seeds: list[int] | None = None,
              workers: int = 1, resume: bool = False, include_optional: bool = False,
              representative_event_logs: bool = True, root: Path | None = None,
              phase_cfg: dict | None = None, progress: bool = True) -> dict:
    """Execute (or resume) a batch. Returns a summary dict."""
    if phase == "confirmatory":
        verify_approval()
    phase_cfg = phase_cfg or load_phase_config(phase)
    seeds = list(seeds or phase_cfg["seeds"])
    check_phase_seeds(phase, seeds)
    out_root = phase_dir(phase, root)
    matrix = build_matrix(phase_cfg, experiment_ids, include_optional=include_optional)
    runs = plan_runs(matrix, seeds, phase)

    existing = list((out_root / "raw" / "runs").glob("*.json")) if (out_root / "raw" / "runs").exists() else []
    if existing and not resume:
        raise RuntimeError(f"{len(existing)} existing run files in {out_root}. Pass --resume to continue or "
                           "extend this batch (completed runs are reused), or move the folder away.")

    _setup_logging(out_root)
    current_code = code_version()
    pending, reused, mixed = [], 0, []
    for spec in runs:
        status = run_status(out_root, spec.run_id)
        if status == "ok":
            reused += 1
            prev = json.loads(run_json_path(out_root, spec.run_id).read_text(encoding="utf-8"))
            if prev.get("code_version") != current_code:
                mixed.append(spec.run_id)
        else:
            pending.append(spec)
    if mixed:
        msg = (f"{len(mixed)} completed runs were produced by a different code version "
               f"(current {current_code}).")
        if phase == "confirmatory":
            raise RuntimeError(msg + " Confirmatory batches must use a single frozen code version.")
        log.warning(msg + " They are reused; the data-quality check will flag mixed versions.")

    _write_plan(out_root, matrix, runs, seeds)
    event_ids: set[str] = set()
    if representative_event_logs and seeds:
        event_ids = {spec.run_id for spec in runs if spec.seed == seeds[0]}
    tasks = group_tasks(pending, out_root, event_ids)
    log.info("Phase %s: %d unique configs, %d planned runs, %d reused, %d to run in %d tasks (workers=%d)",
             phase, matrix.unique_count, len(runs), reused, len(pending), len(tasks), workers)
    if progress:
        print(f"[{phase}] {matrix.unique_count} unique configurations x {len(seeds)} seeds = {len(runs)} runs; "
              f"{reused} already complete, {len(pending)} to run ({len(tasks)} scenario tasks, workers={workers}).")

    t0 = time.perf_counter()
    statuses: list[dict] = []
    done_tasks = 0

    def _collect(res: list[dict]) -> None:
        nonlocal done_tasks
        done_tasks += 1
        statuses.extend(res)
        for st in res:
            if st["status"] != "ok":
                log.error("Run %s failed: %s", st["run_id"], (st["error"] or "").splitlines()[0])
                with open(out_root / "logs" / "failures.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"time": time.time(), **st}) + "\n")
        if progress:
            ok = sum(s["status"] == "ok" for s in statuses)
            print(f"  task {done_tasks}/{len(tasks)} done - runs ok {ok}/{len(statuses)} "
                  f"- elapsed {time.perf_counter() - t0:.0f}s", flush=True)

    if workers <= 1:
        for task in tasks:
            _collect(execute_task(task))
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(execute_task, task) for task in tasks]
            for fut in as_completed(futures):
                _collect(fut.result())

    elapsed = time.perf_counter() - t0
    failed = [s for s in statuses if s["status"] != "ok"]
    summary = {"phase": phase, "planned_runs": len(runs), "reused_runs": reused, "executed_runs": len(statuses),
               "failed_runs": len(failed), "elapsed_s": elapsed, "workers": workers,
               "unique_configurations": matrix.unique_count, "code_version": current_code}
    log.info("Batch finished: %s", summary)
    from .aggregate import aggregate_phase  # local import avoids a cycle at module load
    aggregate_phase(phase, root=root)
    return summary


def _write_plan(out_root: Path, matrix: Matrix, runs: list[RunSpec], seeds: list[int]) -> None:
    proc = out_root / "processed"
    plan_rows = [{"run_id": r.run_id, "configuration_id": r.configuration_id, "seed": r.seed,
                  "experiment_id": "|".join(matrix.experiment_ids_for(r.configuration_id))} for r in runs]
    # Merge with any previous plan so extending a batch never forgets planned runs.
    plan_path = proc / "run_plan.csv"
    if plan_path.exists():
        with open(plan_path, newline="", encoding="utf-8") as fh:
            old = {row["run_id"]: row for row in csv.DictReader(fh)}
        for row in plan_rows:
            old[row["run_id"]] = row
        plan_rows = list(old.values())
    _write_csv(plan_path, plan_rows, ["run_id", "configuration_id", "seed", "experiment_id"])


def _setup_logging(out_root: Path) -> None:
    (out_root / "logs").mkdir(parents=True, exist_ok=True)
    handler_path = out_root / "logs" / "runner.log"
    if not any(isinstance(h, logging.FileHandler) and Path(h.baseFilename) == handler_path
               for h in log.handlers):
        fh = logging.FileHandler(handler_path, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
    log.setLevel(logging.INFO)
