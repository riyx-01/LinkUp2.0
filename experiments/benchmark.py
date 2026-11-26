"""Measured runtime benchmark and batch-runtime estimate.

Runs the four essential algorithms x {50, 100, 200} nodes on development
seeds, measuring wall-clock time of scenario generation and of each routing
run separately. The batch estimate multiplies *measured* per-run costs by the
planned matrix; nothing is guessed. MWS ablation/robustness variants are
costed with the measured MWS time at the same node count (stated in output).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pandas as pd

from analysis.tables import md_table
from simulator.config import apply_overrides, effective_routing, mobility_key, stable_hash
from simulator.engine import RoutingEngine
from simulator.mobility import generate_mobility
from simulator.scenario import build_scenario, scenario_id_for

from .matrix import build_matrix, check_phase_seeds
from .provenance import provenance_record
from .runner import RESULTS_ROOT, load_phase_config

ALGORITHMS = ("DirectDelivery", "Epidemic", "BSW", "MWS")


def run_benchmark(seeds: list[int] | None = None, node_counts=(50, 100, 200),
                  out_dir: Path | None = None) -> dict:
    seeds = list(seeds or [1, 2])
    check_phase_seeds("development", seeds)
    cfg = load_phase_config("development")
    rows = []
    for n in node_counts:
        for seed in seeds:
            c = apply_overrides(cfg, {"nodes.node_count": n})
            t0 = time.perf_counter()
            mob = generate_mobility(c, n, seed)
            t_mob = time.perf_counter() - t0
            t1 = time.perf_counter()
            scen = build_scenario(c, seed, mob)
            t_scen = time.perf_counter() - t1
            for alg in ALGORITHMS:
                ca = apply_overrides(c, {"routing.algorithm": alg})
                t2 = time.perf_counter()
                out = RoutingEngine(ca, scen).run()
                rows.append({"node_count": n, "seed": seed, "algorithm": alg,
                             "routing_s": time.perf_counter() - t2, "mobility_s": t_mob,
                             "contacts_workload_validation_s": t_scen,
                             "contact_pairs": int(scen.contacts.pairs.shape[0]),
                             "d5_percent": out.metrics["d5_percent"]})
            print(f"  N={n} seed={seed}: mobility {t_mob:.2f}s, scenario {t_scen:.2f}s, routing "
                  + ", ".join(f"{r['algorithm']} {r['routing_s']:.2f}s" for r in rows[-4:]), flush=True)
    df = pd.DataFrame(rows)
    routing = df.groupby(["node_count", "algorithm"])["routing_s"].mean()
    mob_t = df.groupby("node_count")["mobility_s"].mean()
    scen_t = df.groupby("node_count")["contacts_workload_validation_s"].mean()

    estimates = {}
    for phase in ("pilot", "confirmatory"):
        pcfg = load_phase_config(phase)
        matrix = build_matrix(pcfg)
        n_seeds = len(pcfg["seeds"])
        routing_total, scen_ids, mob_ids = 0.0, set(), set()
        for cid, c in matrix.configs.items():
            n = c["nodes"]["node_count"]
            alg = effective_routing(c)["algorithm"]
            routing_total += float(routing[(n, alg)]) * n_seeds
            scen_ids.add((scenario_id_for(c, 0), n))
            mob_ids.add((stable_hash(mobility_key(c, 0)), n))
        scen_total = sum(float(scen_t[n]) for _, n in scen_ids) * n_seeds
        mob_total = sum(float(mob_t[n]) for _, n in mob_ids) * n_seeds
        serial = routing_total + scen_total + mob_total
        cpus = os.cpu_count() or 1
        estimates[phase] = {
            "unique_configurations": matrix.unique_count, "seeds": n_seeds,
            "runs": matrix.unique_count * n_seeds,
            "estimated_serial_s": serial,
            "estimated_serial_min": serial / 60,
            "estimated_parallel_min_ideal": {w: serial / 60 / w for w in (2, 4, max(cpus - 1, 1))},
        }
    result = {
        "provenance": provenance_record(), "seeds": seeds, "cpu_count": os.cpu_count(),
        "measurements": rows,
        "mean_routing_s": {f"{n}|{a}": float(v) for (n, a), v in routing.items()},
        "mean_mobility_s": {int(k): float(v) for k, v in mob_t.items()},
        "mean_contacts_workload_validation_s": {int(k): float(v) for k, v in scen_t.items()},
        "estimates": estimates,
        "notes": ["Estimates multiply measured mean per-run costs by the planned matrix.",
                  "MWS variants (ablation, historical, error) are costed at the measured MWS time.",
                  "Parallel figures assume ideal scaling and are therefore lower bounds; measure "
                  "actual parallel time from the pilot run."],
    }
    out_dir = out_dir or RESULTS_ROOT / "benchmark"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "benchmark.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    df.to_csv(out_dir / "benchmark_runs.csv", index=False)
    _write_md(out_dir / "benchmark.md", df, result)
    return result


def _write_md(path: Path, df: pd.DataFrame, result: dict) -> None:
    pivot = df.pivot_table(index="algorithm", columns="node_count", values="routing_s", aggfunc="mean")
    lines = ["# Runtime benchmark", "",
             f"Development seeds: {result['seeds']}; CPU count: {result['cpu_count']}; "
             f"code version: {result['provenance']['code_version']}", "",
             "## Mean routing wall-clock per run (s)", "", md_table(pivot, digits=3, index=True), "",
             "## Mean scenario generation per (seed, N) (s)", "",
             "| N | mobility | contacts + workload + validation |", "|---|---|---|"]
    for n in sorted(result["mean_mobility_s"]):
        lines.append(f"| {n} | {result['mean_mobility_s'][n]:.2f} | "
                     f"{result['mean_contacts_workload_validation_s'][n]:.2f} |")
    lines += ["", "## Estimated batch runtime (from measurements)", ""]
    for phase, est in result["estimates"].items():
        par = ", ".join(f"{w} workers ~{v:.1f} min" for w, v in est["estimated_parallel_min_ideal"].items())
        lines.append(f"- **{phase}**: {est['unique_configurations']} configs x {est['seeds']} seeds = "
                     f"{est['runs']} runs; serial ~{est['estimated_serial_min']:.1f} min; ideal parallel: {par}.")
    lines += ["", *[f"- {n}" for n in result["notes"]], ""]
    path.write_text("\n".join(lines), encoding="utf-8")
