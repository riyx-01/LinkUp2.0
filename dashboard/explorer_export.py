"""Build the self-contained "LinkUp Explorer" HTML page from a genuine simulator run.

One scenario (crowd, friend groups, movement, messages) is generated once and every selected routing
method is run on it with the event log enabled. The page receives:

* positions (centimetre precision) and walking / separation states for every person and second,
* the message workload, and
* for each method: every completed hand-over, delivery and buffer drop from the engine's event log,
  the per-second delivered / stored-copies counters and the run's final metrics.

Nothing in the page is simulated or animated independently: the browser only replays these records
(linearly interpolating positions inside a second, which matches the model's straight-line motion).
"""

from __future__ import annotations

import base64
import datetime as _dt
import json
from pathlib import Path

import numpy as np

from experiments.matrix import check_phase_seeds
from experiments.provenance import code_version
from experiments.runner import load_phase_config
from simulator.config import apply_overrides, effective_routing, validate_config
from simulator.engine import RoutingEngine
from simulator.scenario import build_scenario

TEMPLATE = Path(__file__).resolve().parent / "explorer" / "template.html"
PLACEHOLDER = "/*__LINKUP_DATA__*/null"

METHODS = {
    "DirectDelivery": {
        "name": "Hand-delivery only", "technical": "Direct Delivery",
        "oneLine": "Only the sender carries it, until they meet the friend.",
        "summary": "The sender keeps the message until they personally meet their friend. Nobody else helps.",
    },
    "Epidemic": {
        "name": "Copy to everyone", "technical": "Epidemic routing",
        "oneLine": "Every phone copies it to every phone it meets.",
        "summary": "Every phone that has the message gives a copy to every phone it meets that does not have "
                   "it yet. Usually fast, but it needs a huge number of hand-overs.",
    },
    "BSW": {
        "name": "Limited copies", "technical": "Binary Spray-and-Wait (BSW)",
        "oneLine": "At most {L} copies; spare copies go to anyone new who is met.",
        "summary": "The sender may create at most {L} copies. A phone with spare copies hands half of them to "
                   "anyone it meets who does not have the message. A phone left with a single copy keeps it "
                   "and waits to meet the friend.",
    },
    "MWS": {
        "name": "Walker-first limited copies", "technical": "Motion-aware Walker-preferential Spray-and-Wait (MWS)",
        "oneLine": "At most {L} copies; walkers first, never the sender's friends.",
        "summary": "Same {L}-copy limit, but copies go first to people who are walking (they move around and "
                   "meet more people), never to the sender's own friends (they are usually together), and once "
                   "the message is {F} seconds old also to people standing still.",
    },
}
STYLES = ("minimal", "brutalist", "cyberpunk")
RULE_CODES = {"DELIVERY": 0, "EPIDEMIC": 1, "BSW_SPRAY": 2, "MWS_WALKER": 3, "MWS_FALLBACK": 4,
              "MWS_NO_MOTION_RULE": 5}
ZONE_LABELS = {"main_stage": "Main stage", "second_stage": "Second stage", "food_court": "Food court",
               "facilities": "Toilets & water", "entrance": "Entrance"}


def _b64(arr: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(arr).tobytes()).decode("ascii")


def build_payload(nodes: int = 100, seed: int = 1, radius: float = 10.0, copy_budget: int = 8,
                  workload: str = "separated_friends",
                  algorithms: tuple[str, ...] = ("BSW", "MWS", "DirectDelivery", "Epidemic"),
                  motion_signal: str = "immediate", error_rate: float = 0.0,
                  default_style: str = "minimal", include_results: bool = True) -> dict:
    """Run the simulator and return the explorer payload (JSON-serialisable)."""
    check_phase_seeds("development", [seed])
    base = apply_overrides(load_phase_config("development"), {
        "nodes.node_count": int(nodes), "communication.radius_m": float(radius),
        "routing.copy_budget": int(copy_budget), "traffic.workload_type": workload,
        "routing.mws.motion_signal": motion_signal, "motion_classification.error_rate": float(error_rate)})
    validate_config(base)
    scen = build_scenario(base, int(seed))
    t0, t1 = int(base["simulation"]["warmup_s"]), int(base["simulation"]["duration_s"])
    mob = scen.mobility
    pos_cm = np.clip(np.round(mob.positions[t0:t1].astype(np.float64) * 100.0), 0, 65535).astype("<u2")
    msgs = scen.messages

    runs = []
    for alg in algorithms:
        cfg = apply_overrides(base, {"routing.algorithm": alg})
        engine = RoutingEngine(cfg, scen, event_log=True)
        out = engine.run()
        events = []
        for e in out.events:
            t, kind = int(e[0]), e[1]
            if kind == "transfer":
                code = 2 if e[5] == "destination" else 1
                give = int(e[8] or 0)
                keep = int(e[7] if e[7] is not None else 0)
                events.append([t, code, int(e[2]), int(e[3]), int(e[4]), give, keep, RULE_CODES.get(e[12], 0)])
            elif kind == "drop":
                events.append([t, 3, int(e[2]), -1, int(e[4]), int(e[6] or 0), 0, -1])
        eff = effective_routing(cfg)
        info = METHODS[alg]
        L, F = cfg["routing"]["copy_budget"], cfg["routing"]["mws"]["fallback_s"]
        m = out.metrics
        runs.append({
            "key": alg, "name": info["name"], "technical": info["technical"],
            "summary": info["summary"].format(L=L, F=int(F)), "oneLine": info["oneLine"].format(L=L),
            "usesTokens": engine.algo.uses_tokens, "budget": int(engine.algo.initial_tokens()),
            "keepAfterDelivery": bool(cfg["routing"]["carrier_keeps_replica_after_delivery"]),
            "variant": eff["algorithm"], "events": events,
            "timeline": {"delivered": out.timeline["delivered"], "replicas": out.timeline["replicas"]},
            "delivered": [r["first_delivery_time_s"] if r["first_delivery_time_s"] is not None else -1
                          for r in out.messages],
            "hops": [r["first_delivery_hops"] if r["first_delivery_hops"] is not None else -1 for r in out.messages],
            "metrics": {"d5": m["d5_percent"], "d15": m["d15_percent"], "t": m["transfers_per_message"],
                        "median_latency": m["median_latency_s"], "generated": m["generated_messages"],
                        "delivered": m["unique_delivered"], "relays": m["intermediate_transfers"]},
        })

    venue = base["venue"]
    return {
        "meta": {
            "nodes": int(nodes), "seed": int(seed), "radius": float(radius), "copyBudget": int(copy_budget),
            "fallback": float(base["routing"]["mws"]["fallback_s"]), "t0": t0, "t1": t1,
            "d5": int(base["metrics"]["d5_threshold_s"]), "lifetime": int(base["traffic"]["message_lifetime_s"]),
            "workload": workload, "motionSignal": motion_signal, "errorRate": float(error_rate),
            "dwell": {k: list(v) for k, v in base["mobility"]["dwell_s"].items()},
            "minSeparation": float(base["mobility"]["min_separation_s"]),
            "defaultStyle": default_style if default_style in STYLES else "minimal",
            "venue": {"w": venue["width_m"], "h": venue["height_m"],
                      "zones": [{"key": k, "label": ZONE_LABELS.get(k, k), "x0": z["x"][0], "x1": z["x"][1],
                                 "y0": z["y"][0], "y1": z["y"][1]} for k, z in venue["zones"].items()]},
            "codeVersion": code_version(), "scenarioHash": scen.scenario_hash,
            "generatedAt": _dt.datetime.now().isoformat(timespec="seconds"),
        },
        "groups": [int(g) for g in mob.groups.group_of],
        "pos": _b64(pos_cm),
        "walk": _b64(np.packbits(mob.walking[t0:t1].ravel())),
        "sep": _b64(mob.sep_state[t0:t1].astype(np.int8)),
        "messages": [[i, int(msgs.source[i]), int(msgs.destination[i]), int(msgs.created[i]), int(msgs.expiry[i]),
                      str(msgs.relationship[i])] for i in range(msgs.count)],
        "runs": runs,
        "results": load_results_summary("confirmatory") if include_results else None,
    }


ROOT = Path(__file__).resolve().parent.parent
ALG_ORDER = ("DirectDelivery", "Epidemic", "BSW", "MWS")


def _num(x) -> float | None:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if x != x else round(x, 4)  # NaN -> None (JSON null)


def _sig(x) -> float | None:
    """Keep small p-values (e.g. 1e-43) instead of rounding them to 0."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if x != x else float(f"{x:.3g}")


def load_results_summary(phase: str = "confirmatory", root: Path | None = None) -> dict | None:
    """Plain summary of a finished batch for the explorer's "What we found" tab.

    Every number is read from the batch's own processed CSVs (run_results, hypothesis_tests,
    data_quality); nothing is typed in by hand. Returns None if the batch has not been run.
    """
    import pandas as pd

    proc = (root or ROOT) / "results" / phase / "processed"
    runs_csv, tests_csv = proc / "run_results.csv", proc / "hypothesis_tests.csv"
    if not runs_csv.exists() or not tests_csv.exists():
        return None
    r = pd.read_csv(runs_csv)
    ok = r[r["run_status"] == "ok"]

    def has(exp):
        return ok[ok["experiment_id"].astype(str).str.split("|").apply(lambda ids: exp in ids)]

    e1 = []
    for (n, alg), g in has("E1").groupby(["node_count", "algorithm"]):
        e1.append({"n": int(n), "alg": alg, "d5": _num(g["d5_percent"].mean()), "d15": _num(g["d15_percent"].mean()),
                   "t": _num(g["transfers_per_message"].mean()), "lat": _num(g["median_latency_s"].mean()),
                   "drops": _num(g["buffer_drops"].mean()), "runs": int(len(g))})
    e2 = [{"alg": a, "budget": int(b), "d5": _num(g["d5_percent"].mean())}
          for (a, b), g in has("E2").groupby(["algorithm", "copy_budget"])]
    e4 = [{"signal": s, "d5": _num(g["d5_percent"].mean())}
          for s, g in has("E4").groupby(has("E4")["motion_signal"].fillna("immediate"))]
    e5x = has("E5")
    e5 = [{"alg": a, "err": _num(e), "d5": _num(g["d5_percent"].mean())}
          for (a, e), g in e5x.groupby([e5x["algorithm"], e5x["motion_error_rate"].fillna(0.0)])]
    e6 = [{"alg": a, "workload": w, "d5": _num(g["d5_percent"].mean())}
          for (a, w), g in has("E6").groupby(["algorithm", "workload_type"])]

    t = pd.read_csv(tests_csv)
    tests = []
    for _, row in t.iterrows():
        tests.append({"h": row["hypothesis"], "title": row.get("title"), "diff": _num(row.get("mean_diff")),
                      "lo": _num(row.get("ci95_low")), "hi": _num(row.get("ci95_high")),
                      "pHolm": _sig(row.get("p_holm")), "decision": str(row.get("decision")),
                      "note": "" if pd.isna(row.get("structural_note")) else str(row.get("structural_note")),
                      "zeroVar": bool(row.get("degenerate_zero_variance") is True or
                                      str(row.get("degenerate_zero_variance")) == "True")})
    quality = {"pass": 0, "total": 0}
    dq = proc / "data_quality.csv"
    if dq.exists():
        q = pd.read_csv(dq)
        quality = {"pass": int((q["status"] == "PASS").sum()), "total": int(len(q))}
    targets = None
    try:
        from simulator.config import load_config
        targets = load_config(f"{phase}.json")["statistics"].get("meaningful_target_effects_pp")
    except Exception:  # config optional for the page
        targets = None
    return {
        "phase": phase, "runs": int(len(r)), "ok": int(len(ok)), "failed": int(len(r) - len(ok)),
        "seeds": [int(r["seed"].min()), int(r["seed"].max())], "nSeeds": int(r["seed"].nunique()),
        "codeVersions": sorted(map(str, r["code_version"].unique())), "quality": quality,
        "targets": targets, "e1": e1, "e2": e2, "e4": e4, "e5": e5, "e6": e6, "tests": tests,
    }


def render_html(payload: dict) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise ValueError("Explorer template is missing the data placeholder.")
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    return template.replace(PLACEHOLDER, data)


def write_explorer(out_path: Path, **kwargs) -> Path:
    payload = build_payload(**kwargs)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_html(payload), encoding="utf-8")
    return out_path
