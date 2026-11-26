"""Algorithm-independent mobility, contact and workload validation statistics.

These outputs are reported *before* routing evaluation and must never be tuned
using MWS (or any routing) results. All statistics use the post-warm-up period
``[warmup_s, duration_s)`` unless stated otherwise.
"""

from __future__ import annotations

from collections import Counter

import numpy as np

from .contacts import ContactTrace, contact_events
from .message import MessageTable
from .mobility import MobilityTrace
from .node import SeparationState
from .venue import CIRCULATION, Venue


def _pct(values: np.ndarray, q: float) -> float | None:
    return float(np.percentile(values, q)) if values.size else None


def _mean(values: np.ndarray) -> float | None:
    return float(np.mean(values)) if values.size else None


def integrity_checks(mob: MobilityTrace, venue: Venue, vmax: float) -> dict:
    """Hard physical constraints - every count must be zero."""
    pos = mob.positions.astype(np.float64)
    inside = venue.inside(pos, tol=1e-6)
    disp = np.hypot(*(pos[1:] - pos[:-1]).transpose(2, 0, 1))
    walk = mob.walking[:-1]
    return {
        "positions_outside_venue": int((~inside).sum()),
        "stationary_moves": int((disp[~walk] > 1e-6).sum()),
        "speed_violations": int((disp[walk] > vmax + 1e-4).sum()),
        "max_step_displacement_m": float(disp.max()) if disp.size else 0.0,
    }


def mobility_contact_validation(cfg: dict, mob: MobilityTrace, contacts: ContactTrace,
                                messages: MessageTable) -> dict:
    venue = Venue(cfg["venue"])
    w = int(cfg["simulation"]["warmup_s"])
    T, N = mob.walking.shape
    radius = float(cfg["communication"]["radius_m"])
    walk = mob.walking[w:]
    pos = mob.positions.astype(np.float64)

    # --- motion
    disp = np.hypot(*(pos[w + 1:] - pos[w:-1]).transpose(2, 0, 1))
    walk_disp = disp[mob.walking[w:-1]]
    speed_hist, speed_edges = np.histogram(walk_disp, bins=np.linspace(0, 1.4, 15))
    trip = np.asarray(mob.trip_speeds)

    # --- zones
    zone = mob.zone[w:]
    zone_share = {name: float(np.mean(zone == i)) for i, name in enumerate(venue.zone_names)}
    zone_share["circulation"] = float(np.mean(zone == CIRCULATION))

    # --- contacts and neighbours
    degree_sum = np.zeros(N)
    degree_samples: list[np.ndarray] = []
    zone_deg_sum = np.zeros(len(venue.zone_names) + 1)
    zone_deg_cnt = np.zeros(len(venue.zone_names) + 1)
    contact_seconds = Counter()
    for t in range(contacts.start, contacts.end):
        p = contacts.at(t)
        deg = np.bincount(p.ravel(), minlength=N) if p.size else np.zeros(N, dtype=np.int64)
        degree_sum += deg
        degree_samples.append(deg)
        zi = mob.zone[t].astype(np.int64)
        zi = np.where(zi == CIRCULATION, len(venue.zone_names), zi)
        zone_deg_sum += np.bincount(zi, weights=deg, minlength=len(zone_deg_sum))
        zone_deg_cnt += np.bincount(zi, minlength=len(zone_deg_cnt))
        if p.size:
            wk = mob.walking[t]
            nw = wk[p[:, 0]].astype(int) + wk[p[:, 1]].astype(int)
            for k, c in zip(*np.unique(nw, return_counts=True)):
                contact_seconds[int(k)] += int(c)
    degrees = np.concatenate(degree_samples) if degree_samples else np.zeros(0)
    labels = list(venue.zone_names) + ["circulation"]
    local_neighbours = {labels[i]: (float(zone_deg_sum[i] / zone_deg_cnt[i]) if zone_deg_cnt[i] else None)
                        for i in range(len(labels))}

    events = contact_events(contacts, N)
    durations = np.array([e[3] - e[2] for e in events], dtype=float)
    censored = np.array([e[3] == contacts.end or e[2] == contacts.start for e in events], dtype=bool)
    start_kind = Counter()
    for a, b, s, _ in events:
        start_kind[int(mob.walking[s, a]) + int(mob.walking[s, b])] += 1
    n_events = max(len(events), 1)
    cs_total = max(sum(contact_seconds.values()), 1)
    hours = (contacts.end - contacts.start) / 3600.0

    # --- separation
    sep = mob.sep_state
    sep_events_post = [e for e in mob.separation_events if e[0] >= w]
    durations_sep = np.array([t - s for t, _, s in mob.rejoin_events], dtype=float)
    separated_now = (sep[w:] != SeparationState.WITH_GROUP)
    eligible_pairs = np.zeros(T - w)
    for members in mob.groups.members:
        k = len(members)
        core = (sep[w:, members] == SeparationState.WITH_GROUP).sum(axis=1)
        eligible_pairs += k * (k - 1) - core * (core - 1)
    gen = cfg["traffic"]
    g0, g1 = int(gen["generation_start_s"]) - w, int(gen["generation_end_s"]) - w
    gen_window = eligible_pairs[g0:g1]

    # --- workload
    rel_counts = Counter(messages.relationship.tolist())
    in_range = messages.initial_distance <= radius
    fallback = rel_counts.get("same_group_fallback", 0) + rel_counts.get("random_fallback", 0)

    return {
        "node_count": N,
        "density_per_1000m2": venue.density_per_1000m2(N),
        "friend_groups": mob.groups.group_count,
        "grouped_fraction": mob.groups.grouped_fraction,
        "group_sizes": [int(len(m)) for m in mob.groups.members],
        "pct_time_walking": float(walk.mean() * 100),
        "pct_time_stationary": float((1 - walk.mean()) * 100),
        "walking_speed_realised_mean_mps": _mean(walk_disp),
        "walking_speed_realised_sd_mps": float(np.std(walk_disp, ddof=1)) if walk_disp.size > 1 else None,
        "walking_speed_realised_p10_mps": _pct(walk_disp, 10),
        "walking_speed_realised_p50_mps": _pct(walk_disp, 50),
        "walking_speed_realised_p90_mps": _pct(walk_disp, 90),
        "walking_speed_hist_counts": speed_hist.tolist(),
        "walking_speed_hist_edges": speed_edges.tolist(),
        "trip_speed_sampled_mean_mps": _mean(trip),
        "zone_occupancy_share": zone_share,
        "avg_neighbours_per_node": float(degree_sum.sum() / (N * max(contacts.steps, 1))),
        "neighbours_p50": _pct(degrees, 50),
        "neighbours_p90": _pct(degrees, 90),
        "neighbours_max": int(degrees.max()) if degrees.size else 0,
        "pct_node_time_isolated": float(np.mean(degrees == 0) * 100) if degrees.size else None,
        "local_avg_neighbours_by_zone": local_neighbours,
        "contact_events": len(events),
        "contact_events_per_node_per_hour": len(events) * 2 / N / hours if hours else None,
        "contact_duration_mean_s": _mean(durations),
        "contact_duration_median_s": _pct(durations, 50),
        "contact_duration_p90_s": _pct(durations, 90),
        "contact_events_censored": int(censored.sum()),
        "encounter_start_both_walking_share": start_kind[2] / n_events,
        "encounter_start_one_walking_share": start_kind[1] / n_events,
        "encounter_start_both_stationary_share": start_kind[0] / n_events,
        "encounter_start_involving_walker_share": (start_kind[1] + start_kind[2]) / n_events,
        "contact_seconds_both_walking_share": contact_seconds[2] / cs_total,
        "contact_seconds_one_walking_share": contact_seconds[1] / cs_total,
        "contact_seconds_both_stationary_share": contact_seconds[0] / cs_total,
        "separation_events_total": len(mob.separation_events),
        "separation_events_post_warmup": len(sep_events_post),
        "rejoin_events_total": len(mob.rejoin_events),
        "separation_duration_mean_s": _mean(durations_sep),
        "separation_duration_median_s": _pct(durations_sep, 50),
        "mean_separated_members": float(separated_now.sum(axis=1).mean()),
        "eligible_separated_pairs_mean_in_generation_window": float(gen_window.mean()) if gen_window.size else None,
        "pct_generation_seconds_with_eligible_pair": float(np.mean(gen_window > 0) * 100) if gen_window.size else None,
        "messages_generated": messages.count,
        "workload_relationship_counts": dict(rel_counts),
        "workload_fallback_count": int(fallback),
        "workload_fallback_share": fallback / messages.count if messages.count else None,
        "pairs_in_range_at_creation_share": float(in_range.mean()) if messages.count else None,
        "initial_distance_median_m": _pct(messages.initial_distance, 50),
        "integrity": integrity_checks(mob, venue, float(cfg["mobility"]["speed_max_mps"])),
    }
