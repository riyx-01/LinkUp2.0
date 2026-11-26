"""LinkUp Research Simulator - command-line interface.

Examples (PowerShell, from the project root with the venv active)::

    python main.py matrix                       # show the experiment matrix and reuse
    python main.py smoke                        # tiny deterministic end-to-end check
    python main.py simulate --algorithm MWS --nodes 100 --seed 1 --event-log
    python main.py validate                     # mobility validation on pilot seeds
    python main.py benchmark                    # measured runtime + batch estimate
    python main.py pilot --workers 4            # E1-E6 on pilot seeds 101-105 + pilot analysis
    python main.py freeze --approver "Name"     # RESEARCHER ONLY: approve/freeze confirmatory config
    python main.py run --all --workers 4        # confirmatory batch (requires freeze)
    python main.py run --experiment E1 E4 --resume
    python main.py analyze --phase confirmatory
    python main.py export --phase confirmatory
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def cmd_matrix(args) -> None:
    from experiments.matrix import build_matrix
    from experiments.runner import load_phase_config
    from analysis.tables import md_table
    import pandas as pd

    cfg = load_phase_config(args.phase)
    matrix = build_matrix(cfg, include_optional=args.include_optional)
    print(md_table(pd.DataFrame(matrix.rows())))
    print("\nNew configurations per experiment:", matrix.new_configs_per_experiment())
    print(f"Unique configurations: {matrix.unique_count}; seeds: {len(cfg['seeds'])}; "
          f"runs: {matrix.unique_count * len(cfg['seeds'])}")


def cmd_smoke(args) -> None:
    from simulator.config import apply_overrides, variant_label
    from experiments.runner import load_phase_config
    from simulator.engine import run_simulation
    from simulator.scenario import build_scenario

    cfg = apply_overrides(load_phase_config("development"), {"nodes.node_count": 50})
    scen_a = build_scenario(cfg, 1)
    scen_b = build_scenario(cfg, 1)
    assert scen_a.scenario_hash == scen_b.scenario_hash, "scenario not reproducible"
    print(f"Scenario N=50 seed=1 hash={scen_a.scenario_hash} messages={scen_a.messages.count} "
          f"integrity={scen_a.validation['integrity']}")
    for alg in ("DirectDelivery", "Epidemic", "BSW", "MWS"):
        c = apply_overrides(cfg, {"routing.algorithm": alg})
        m1 = run_simulation(c, scen_a).metrics
        m2 = run_simulation(c, scen_b).metrics
        same = all(m1[k] == m2[k] for k in m1 if k != "routing_runtime_s")
        print(f"  {variant_label(c):26s} D5={m1['d5_percent']:6.2f}%  D15={m1['d15_percent']:6.2f}%  "
              f"T={m1['transfers_per_message']:7.2f}  tokens_ok={m1['token_conservation_ok']}  "
              f"reproducible={same}")
        assert same, "metrics not reproducible"
    print("Smoke test passed.")


def cmd_simulate(args) -> None:
    from simulator.config import apply_overrides, variant_label
    from experiments.runner import load_phase_config, phase_dir, _write_csv
    from simulator.engine import EVENT_FIELDS, RoutingEngine
    from simulator.scenario import build_scenario

    overrides = {"nodes.node_count": args.nodes, "routing.algorithm": args.algorithm,
                 "routing.copy_budget": args.copy_budget, "communication.radius_m": args.radius,
                 "traffic.workload_type": args.workload, "motion_classification.error_rate": args.error_rate,
                 "routing.mws.motion_signal": args.motion_signal}
    cfg = apply_overrides(load_phase_config("development"), overrides)
    scen = build_scenario(cfg, args.seed)
    engine = RoutingEngine(cfg, scen, event_log=args.event_log)
    out = engine.run()
    print(f"{variant_label(cfg)} N={args.nodes} seed={args.seed} scenario={scen.scenario_hash}")
    print(json.dumps({k: v for k, v in out.metrics.items()}, indent=1, default=str))
    print("Opportunity decisions:", out.decision_counts)
    print("Completed transfers by rule:", out.transfer_reasons)
    if args.event_log:
        path = phase_dir("development") / "events" / f"{args.algorithm}_N{args.nodes}_s{args.seed}.csv"
        _write_csv(path, out.events, EVENT_FIELDS)
        print(f"Event log written to {path}")


def cmd_validate(args) -> None:
    from experiments.validate_mobility import validate
    df = validate(args.phase, args.seeds, tuple(args.nodes))
    print(f"Validated {len(df)} scenarios -> results/{args.phase}/validation/")


def cmd_benchmark(args) -> None:
    from experiments.benchmark import run_benchmark
    res = run_benchmark(args.seeds, tuple(args.nodes))
    for phase, est in res["estimates"].items():
        print(f"{phase}: {est['runs']} runs, estimated serial {est['estimated_serial_min']:.1f} min")
    print("Details: results/benchmark/benchmark.md")


def cmd_pilot(args) -> None:
    from experiments.runner import run_batch
    summary = run_batch("pilot", None, None, workers=args.workers, resume=args.resume,
                        include_optional=args.include_optional)
    print(json.dumps(summary, indent=1))
    if not args.skip_analysis:
        from analysis.pipeline import analyze_phase
        analyze_phase("pilot", export=True)


def cmd_run(args) -> None:
    from experiments.runner import run_batch
    if not args.all and not args.experiment:
        sys.exit("Specify --experiment E1 [E2 ...] or --all")
    experiments = None if args.all else args.experiment
    summary = run_batch(args.phase, experiments, args.seeds, workers=args.workers, resume=args.resume,
                        include_optional=args.include_optional)
    print(json.dumps(summary, indent=1))


def cmd_analyze(args) -> None:
    from analysis.pipeline import analyze_phase
    analyze_phase(args.phase, export=False)


def cmd_export(args) -> None:
    from analysis.pipeline import analyze_phase
    analyze_phase(args.phase, export=True)


def cmd_explorer(args) -> None:
    from dashboard.explorer_export import write_explorer

    out = Path(args.out) if args.out else ROOT / "results" / "explorer" / f"linkup_explorer_N{args.nodes}_s{args.seed}.html"
    path = write_explorer(out, nodes=args.nodes, seed=args.seed, radius=args.radius, copy_budget=args.copy_budget,
                          workload=args.workload, algorithms=tuple(args.methods), default_style=args.style)
    print(f"LinkUp Explorer written to {path} ({path.stat().st_size / 1e6:.1f} MB). Open it in any web browser.")


def cmd_freeze(args) -> None:
    from experiments.approval import freeze
    record = freeze(args.approver, args.note, force=args.force)
    print("Confirmatory configuration frozen:")
    print(json.dumps(record, indent=1))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="LinkUp Research Simulator")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("matrix", help="show experiment matrix and configuration reuse")
    s.add_argument("--phase", default="confirmatory", choices=["development", "pilot", "confirmatory"])
    s.add_argument("--include-optional", action="store_true")
    s.set_defaults(func=cmd_matrix)

    s = sub.add_parser("smoke", help="tiny deterministic end-to-end test")
    s.set_defaults(func=cmd_smoke)

    s = sub.add_parser("simulate", help="single development run (seeds 1-9)")
    s.add_argument("--algorithm", default="MWS", choices=["DirectDelivery", "Epidemic", "BSW", "MWS"])
    s.add_argument("--nodes", type=int, default=100)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--copy-budget", type=int, default=8)
    s.add_argument("--radius", type=float, default=10)
    s.add_argument("--workload", default="separated_friends", choices=["separated_friends", "random"])
    s.add_argument("--error-rate", type=float, default=0.0)
    s.add_argument("--motion-signal", default="immediate", choices=["immediate", "historical"])
    s.add_argument("--event-log", action="store_true")
    s.set_defaults(func=cmd_simulate)

    s = sub.add_parser("validate", help="mobility/contact/workload validation (no routing)")
    s.add_argument("--phase", default="pilot", choices=["development", "pilot", "confirmatory"])
    s.add_argument("--seeds", type=int, nargs="*")
    s.add_argument("--nodes", type=int, nargs="*", default=[50, 100, 200])
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("benchmark", help="measured runtime benchmark (development seeds)")
    s.add_argument("--seeds", type=int, nargs="*", default=[1, 2])
    s.add_argument("--nodes", type=int, nargs="*", default=[50, 100, 200])
    s.set_defaults(func=cmd_benchmark)

    s = sub.add_parser("pilot", help="run E1-E6 on pilot seeds and produce pilot analysis")
    s.add_argument("--workers", type=int, default=1)
    s.add_argument("--resume", action="store_true")
    s.add_argument("--include-optional", action="store_true")
    s.add_argument("--skip-analysis", action="store_true")
    s.set_defaults(func=cmd_pilot)

    s = sub.add_parser("run", help="run experiments (confirmatory phase requires a frozen approval)")
    s.add_argument("--experiment", nargs="*")
    s.add_argument("--all", action="store_true")
    s.add_argument("--phase", default="confirmatory", choices=["development", "pilot", "confirmatory"])
    s.add_argument("--seeds", type=int, nargs="*")
    s.add_argument("--workers", type=int, default=1)
    s.add_argument("--resume", action="store_true")
    s.add_argument("--include-optional", action="store_true")
    s.set_defaults(func=cmd_run)

    for name, func in (("analyze", cmd_analyze), ("export", cmd_export)):
        s = sub.add_parser(name, help=f"{name} results of a phase")
        s.add_argument("--phase", default="confirmatory", choices=["development", "pilot", "confirmatory"])
        s.set_defaults(func=func)

    s = sub.add_parser("explorer", help="write the plain-language LinkUp Explorer (one HTML file) for a run")
    s.add_argument("--nodes", type=int, default=100)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--radius", type=float, default=10)
    s.add_argument("--copy-budget", type=int, default=8)
    s.add_argument("--workload", default="separated_friends", choices=["separated_friends", "random"])
    s.add_argument("--methods", nargs="+", default=["MWS", "BSW", "DirectDelivery", "Epidemic"],
                   choices=["MWS", "BSW", "DirectDelivery", "Epidemic"])
    s.add_argument("--style", default="minimal", choices=["minimal", "brutalist", "cyberpunk"],
                   help="style shown first (viewers can switch at any time)")
    s.add_argument("--out", default=None)
    s.set_defaults(func=cmd_explorer)

    s = sub.add_parser("freeze", help="RESEARCHER ONLY: approve and freeze the confirmatory config")
    s.add_argument("--approver", required=True)
    s.add_argument("--note", default="")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_freeze)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
