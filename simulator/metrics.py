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
    eff = efficiency_metrics(engine, counts["d5"], completed)
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
        **eff,
    }


def _mean_age(times: np.ndarray, created: np.ndarray) -> float:
    ok = times >= 0
    return float(np.mean(times[ok] - created[ok])) if ok.any() else float("nan")


def _pct(mask: np.ndarray) -> float:
    return float(100.0 * mask.mean()) if mask.size else float("nan")


def efficiency_metrics(engine: "RoutingEngine", delivered_5min: int, completed: int) -> dict:
    """Supporting efficiency and workload diagnostics (all from actual events / counters).

    Definitions (documented in docs/statistical_analysis_plan.md and the data dictionary):
    * timely_deliveries_per_100_transfers = delivered_5min / completed_transfers x 100 (NaN if 0 transfers).
    * first-relay / half-copies / spray-complete ages are measured from message creation and averaged over
      the messages that reached the event; the matching pct_* column gives the share that reached it.
      half copies = source copy + relays >= ceil(L/2); spray complete = every remaining replica holds a single
      token (token algorithms only; NaN otherwise).
    * copy_budget_utilization = mean over messages of relays / (L - 1) (NaN if not token-based or L = 1).
    * intermediate_transfers_per_delivered_message = all intermediate transfers / unique delivered messages
      (relays on undelivered messages are included in the numerator; NaN if nothing was delivered).
    * relays_before/after_first_delivery: relays of delivered messages before / after their first delivery;
      relays_on_undelivered_messages: relays of messages never delivered.
    * Workload diagnostics use the evaluation-only source-destination contact trace and never reach routing.
    """
    created = engine.created
    msgs = engine.scen.messages
    delivered = engine.delivered_time >= 0
    algo = engine.algo
    L = algo.initial_tokens() if algo.uses_tokens else None
    relays = engine.msg_relays
    out = {
        "timely_deliveries_per_100_transfers": 100.0 * delivered_5min / completed if completed else float("nan"),
        "pct_messages_with_relay": _pct(engine.first_relay_time >= 0),
        "mean_time_to_first_relay_s": _mean_age(engine.first_relay_time, created),
        "relays_before_first_delivery": int(engine.relays_before_delivery[delivered].sum()),
        "relays_after_first_delivery": int(engine.relays_after_delivery[delivered].sum()),
        "relays_on_undelivered_messages": int(relays[~delivered].sum()),
        "intermediate_transfers_per_delivered_message":
            float(relays.sum() / delivered.sum()) if delivered.any() else float("nan"),
    }
    if L is not None:
        out.update({
            "pct_messages_half_copies": _pct(engine.half_copies_time >= 0),
            "mean_time_to_half_copies_s": _mean_age(engine.half_copies_time, created),
            "pct_messages_spray_complete": _pct(engine.spray_complete_time >= 0),
            "mean_time_to_spray_complete_s": _mean_age(engine.spray_complete_time, created),
            "copy_budget_utilization": float(np.mean(relays / (L - 1))) if L > 1 and relays.size else float("nan"),
        })
    else:
        out.update({k: float("nan") for k in ("pct_messages_half_copies", "mean_time_to_half_copies_s",
                                              "pct_messages_spray_complete", "mean_time_to_spray_complete_s",
                                              "copy_budget_utilization")})
    # Workload diagnostics (evaluation only).
    if msgs.in_range_at_creation is not None and engine.M:
        inr = msgs.in_range_at_creation.astype(bool)
        lat = np.where(delivered, engine.delivered_time - created, np.inf)
        d5 = lat <= int(engine.cfg["metrics"]["d5_threshold_s"])
        first = msgs.first_direct_contact
        before_direct = delivered & ((first < 0) | (engine.delivered_time < first))
        via_relay = delivered & (engine.delivered_hops > 1)
        out.update({
            "messages_dest_in_range_at_creation": int(inr.sum()),
            "d5_percent_dest_in_range": _pct(d5[inr]) if inr.any() else float("nan"),
            "d5_percent_dest_out_of_range": _pct(d5[~inr]) if (~inr).any() else float("nan"),
            "pct_messages_with_direct_contact": _pct(first >= 0),
            "pct_delivered_before_direct_contact": _pct(before_direct[delivered]) if delivered.any() else float("nan"),
            "pct_delivered_via_relay": _pct(via_relay[delivered]) if delivered.any() else float("nan"),
        })
    return out


def compute_message_rows(engine: "RoutingEngine") -> list[dict]:
    cfg = engine.cfg["metrics"]
    t2, t5, t15 = int(cfg["d2_threshold_s"]), int(cfg["d5_threshold_s"]), int(cfg["d15_threshold_s"])
    msgs = engine.scen.messages
    rows = []

    def age(arr, m):
        return int(arr[m] - engine.created[m]) if arr[m] >= 0 else None

    for m in range(engine.M):
        dt = int(engine.delivered_time[m])
        lat = dt - int(engine.created[m]) if dt >= 0 else None
        first = int(msgs.first_direct_contact[m]) if msgs.first_direct_contact is not None else None
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
            "relays_for_message": int(engine.msg_relays[m]),
            "first_relay_age_s": age(engine.first_relay_time, m),
            "half_copies_age_s": age(engine.half_copies_time, m),
            "spray_complete_age_s": age(engine.spray_complete_time, m),
            "relays_before_first_delivery": int(engine.relays_before_delivery[m]) if dt >= 0 else None,
            "relays_after_first_delivery": int(engine.relays_after_delivery[m]) if dt >= 0 else None,
            "dest_in_range_at_creation": bool(msgs.in_range_at_creation[m]) if msgs.in_range_at_creation is not None else None,
            "first_direct_contact_age_s": (first - int(engine.created[m])) if first is not None and first >= 0 else None,
            "delivered_before_first_direct_contact": (bool(first is None or first < 0 or dt < first)) if dt >= 0 else None,
            "delivered_via_relay": bool(engine.delivered_hops[m] > 1) if dt >= 0 else None,
        })
    return rows
