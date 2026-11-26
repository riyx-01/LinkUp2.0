"""Run-level and message-level metrics with explicit, consistent definitions.

* D2/D5/D15 = unique messages first delivered with latency <= 120/300/900 s,
  divided by **all generated messages** x 100 (undelivered messages stay in the
  denominator).
* T (transfers_per_message) = completed payload transfers / generated
  messages. Completed transfers = intermediate replications + destination
  deliveries. Prevented duplicates, rejected and failed transfers are *not*
  completed transfers.
* Latency statistics use delivered messages only (subject to selection bias);
  the cumulative-delivery curve over all messages is computed in the analysis.
* Hop count = transfers on the path of the replica that first delivered.
* Completed transfers are an activity indicator, not an energy measurement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # pragma: no cover
    from .engine import RoutingEngine


def delivery_counts(created: np.ndarray, delivered_time: np.ndarray, thresholds: dict[str, int]) -> dict:
    latency = np.where(delivered_time >= 0, delivered_time - created, np.inf)
    return {name: int(np.sum(latency <= thr)) for name, thr in thresholds.items()}


def percent(count: int, total: int) -> float:
    return 100.0 * count / total if total else float("nan")


def compute_run_metrics(engine: "RoutingEngine", runtime: float, steps: int, peak_replicas: int,
                        occ_max: int) -> dict:
    cfg, c = engine.cfg, engine.c
    m_cfg = cfg["metrics"]
    thresholds = {"d2": int(m_cfg["d2_threshold_s"]), "d5": int(m_cfg["d5_threshold_s"]),
                  "d15": int(m_cfg["d15_threshold_s"])}
    M = engine.M
    counts = delivery_counts(engine.created, engine.delivered_time, thresholds)
    delivered = engine.delivered_time >= 0
    latency = (engine.delivered_time - engine.created)[delivered].astype(float)
    hops = engine.delivered_hops[delivered].astype(float)
    completed = int(c["completed_transfers"])

    def stat(fn, arr):
        return float(fn(arr)) if arr.size else float("nan")

    algo = engine.algo
    token_total = algo.copy_budget * M if algo.uses_tokens else 0
    token_accounted = (c["tokens_lost_buffer_drops"] + c["tokens_expired"]
                       + c["tokens_retired_after_delivery"])
    return {
        "generated_messages": M,
        "delivered_2min": counts["d2"],
        "delivered_5min": counts["d5"],
        "delivered_15min": counts["d15"],
        "d2_percent": percent(counts["d2"], M),
        "d5_percent": percent(counts["d5"], M),
        "d15_percent": percent(counts["d15"], M),
        "unique_delivered": int(delivered.sum()),
        "completed_transfers": completed,
        "intermediate_transfers": int(c["intermediate_transfers"]),
        "destination_transfers": int(c["destination_transfers"]),
        "repeated_destination_receptions": int(c["repeated_destination_receptions"]),
        "transfers_per_message": completed / M if M else float("nan"),
        "intermediate_transfers_per_message": c["intermediate_transfers"] / M if M else float("nan"),
        "mean_latency_s": stat(np.mean, latency),
        "median_latency_s": stat(np.median, latency),
        "q25_latency_s": stat(lambda x: np.percentile(x, 25), latency),
        "q75_latency_s": stat(lambda x: np.percentile(x, 75), latency),
        "p90_latency_s": stat(lambda x: np.percentile(x, 90), latency),
        "mean_delivery_hops": stat(np.mean, hops),
        "undelivered_messages": int(M - delivered.sum()),
        "expired_replicas": int(c["expired_replicas"]),
        "source_replicas": int(c["source_replicas"]),
        "created_replicas": int(c["source_replicas"] + c["intermediate_transfers"]),
        "peak_simultaneous_replicas": int(peak_replicas),
        "buffer_drops": int(c["buffer_drops"]),
        "tokens_lost_buffer_drops": int(c["tokens_lost_buffer_drops"]),
        "tokens_expired": int(c["tokens_expired"]),
        "duplicate_opportunities_prevented": int(c["duplicate_opportunities_prevented"]),
        "failed_transfers": int(c["failed_transfers"]),
        "rejected_transfers": int(c["rejected_transfers"]),
        "capacity_blocked_opportunities": int(c["capacity_blocked"]),
        "token_exhausted_in_step": int(c["token_exhausted_in_step"]),
        "sender_replica_lost_in_step": int(c["sender_replica_lost_in_step"]),
        "avg_buffer_occupancy": c["buffer_occupancy_sum"] / (steps * engine.N) if steps else float("nan"),
        "max_buffer_occupancy": int(occ_max),
        "token_conservation_ok": bool(token_accounted == token_total) if algo.uses_tokens else True,
        "routing_runtime_s": runtime,
    }


def compute_message_rows(engine: "RoutingEngine") -> list[dict]:
    cfg = engine.cfg["metrics"]
    t2, t5, t15 = int(cfg["d2_threshold_s"]), int(cfg["d5_threshold_s"]), int(cfg["d15_threshold_s"])
    msgs = engine.scen.messages
    rows = []
    for m in range(engine.M):
        dt = int(engine.delivered_time[m])
        lat = dt - int(engine.created[m]) if dt >= 0 else None
        rows.append({
            "message_id": m,
            "source_id": int(engine.src[m]),
            "destination_id": int(engine.dst[m]),
            "source_destination_relationship": str(msgs.relationship[m]),
            "creation_time_s": int(engine.created[m]),
            "expiry_time_s": int(engine.expiry[m]),
            "first_delivery_time_s": dt if dt >= 0 else None,
            "delivery_latency_s": lat,
            "delivered_within_2min": bool(lat is not None and lat <= t2),
            "delivered_within_5min": bool(lat is not None and lat <= t5),
            "delivered_within_15min": bool(lat is not None and lat <= t15),
            "first_delivery_hops": int(engine.delivered_hops[m]) if dt >= 0 else None,
            "completed_transfers_for_message": int(engine.msg_transfers[m]),
            "final_status": "delivered" if dt >= 0 else "undelivered_expired",
        })
    return rows
