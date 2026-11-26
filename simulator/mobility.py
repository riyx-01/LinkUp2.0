"""Festival-inspired mobility model (algorithm independent).

Model summary (full specification in docs/simulation_assumptions.md):

* **Mobility units.** Each friend group is one unit; every independent node is a
  unit of size one. A unit alternates between DWELLING at a zone and MOVING to a
  new zone. Destinations are drawn from the configured zone probabilities,
  excluding the zone just visited. Dwell times are uniform in the zone's range.
* **Group movement.** Members share the unit's destination *anchor* point but
  each walks to ``anchor + personal offset`` at ``unit speed x personal factor``
  (clipped to the speed range), so members are close but never overlapping and
  arrive at slightly different times. The unit's dwell timer starts when all
  members currently with the group have arrived.
* **Separation.** Each eligible member (in a group, currently with it, and the
  group would keep at least one member) separates with probability
  ``1 - exp(-hazard)`` per second. A separated member walks to a different
  zone, dwells, and keeps roaming independently until at least
  ``min_separation_s`` has elapsed *and* its current dwell ends. It then
  walks physically towards the current centroid of the members still with the
  group, rejoining when within ``rejoin_distance_m``. No teleporting.
  (``rejoin_policy = "immediate_after_minimum"`` instead starts rejoining as
  soon as ``min_separation_s`` has elapsed, interrupting the current activity.)
* **Time semantics.** ``positions[t]`` is the location at integer time t;
  ``walking[t]`` is True when the node moves during ``[t, t+1)``. Hence a
  stationary node satisfies ``positions[t+1] == positions[t]`` and a walking
  node moves at most ``speed`` metres in that second.

Randomness uses four independent streams (initial positions, group assignment,
mobility decisions, separation) so that nothing about routing can affect it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .groups import GroupAssignment, assign_groups
from .node import NO_GROUP, SeparationState
from .rng import stream
from .venue import Venue

DWELLING, MOVING = 0, 1


@dataclass
class MobilityTrace:
    """Recorded mobility for one (seed, node count)."""

    positions: np.ndarray            # (T, N, 2) float32 (metres)
    walking: np.ndarray              # (T, N) bool - moves during [t, t+1)
    zone: np.ndarray                 # (T, N) int8 - zone index or -1 (circulation)
    sep_state: np.ndarray            # (T, N) int8 - SeparationState codes
    groups: GroupAssignment
    separation_events: list[tuple[int, int, int]] = field(default_factory=list)  # (t, node, group)
    rejoin_events: list[tuple[int, int, int]] = field(default_factory=list)      # (t, node, sep_start)
    trip_speeds: list[float] = field(default_factory=list)

    @property
    def duration(self) -> int:
        return self.walking.shape[0]

    @property
    def node_count(self) -> int:
        return self.walking.shape[1]


class FestivalMobility:
    """Generates a :class:`MobilityTrace` from a config and master seed."""

    def __init__(self, cfg: dict, node_count: int, seed: int):
        self.cfg = cfg
        self.mob = cfg["mobility"]
        self.venue = Venue(cfg["venue"])
        self.N = int(node_count)
        self.T = int(cfg["simulation"]["duration_s"])
        self.seed = int(seed)
        scope = (self.N,)
        self.rng_pos = stream(seed, "initial_positions", *scope)
        self.rng_grp = stream(seed, "group_assignment", *scope)
        self.rng_mob = stream(seed, "mobility", *scope)
        self.rng_sep = stream(seed, "separation", *scope)

        self.zone_names = self.venue.zone_names
        self.zone_probs = np.array([self.mob["destination_probabilities"][z] for z in self.zone_names])
        self.dwell = np.array([self.mob["dwell_s"][z] for z in self.zone_names], dtype=float)
        self.vmin, self.vmax = float(self.mob["speed_min_mps"]), float(self.mob["speed_max_mps"])
        self.p_sep = 1.0 - np.exp(-float(self.mob["separation_hazard_per_s"]))
        self.min_sep = float(self.mob["min_separation_s"])
        self.rejoin_dist = float(self.mob["rejoin_distance_m"])
        self.margin = float(self.mob["zone_point_margin_m"])
        self.rejoin_policy = self.mob["rejoin_policy"]
        if self.rejoin_policy not in ("after_current_activity", "immediate_after_minimum"):
            raise ValueError(f"Unknown rejoin_policy '{self.rejoin_policy}'")

    # ------------------------------------------------------------------ helpers
    def _choose_zone(self, rng: np.random.Generator, exclude: set[int]) -> int:
        probs = self.zone_probs.copy()
        for z in exclude:
            if z >= 0:
                probs[z] = 0.0
        if probs.sum() <= 0:  # pragma: no cover - only if every zone excluded
            probs = self.zone_probs.copy()
        return int(rng.choice(len(probs), p=probs / probs.sum()))

    def _dwell(self, rng: np.random.Generator, zone: int) -> float:
        lo, hi = self.dwell[zone]
        return float(rng.uniform(lo, hi))

    def _point(self, rng: np.random.Generator, zone: int) -> np.ndarray:
        return self.venue.zones[zone].sample_point(rng, self.margin)

    def _member_speed(self, base: float, factor: np.ndarray) -> np.ndarray:
        return np.clip(base * factor, self.vmin, self.vmax)

    # --------------------------------------------------------------------- run
    def run(self) -> MobilityTrace:
        N, T = self.N, self.T
        groups = assign_groups(N, self.mob, self.rng_grp)
        group_of = groups.group_of

        # Mobility units: friend groups first, then one unit per independent node.
        unit_of = np.empty(N, dtype=np.int64)
        unit_members: list[np.ndarray] = []
        for gid, members in enumerate(groups.members):
            unit_of[members] = gid
            unit_members.append(members)
        for node in np.flatnonzero(group_of == NO_GROUP):
            unit_of[node] = len(unit_members)
            unit_members.append(np.array([node]))
        U = len(unit_members)

        unit_phase = np.full(U, DWELLING, dtype=np.int8)
        unit_zone = np.zeros(U, dtype=np.int64)
        unit_anchor = np.zeros((U, 2))
        unit_dwell_end = np.zeros(U)

        pos = np.zeros((N, 2))
        target = np.zeros((N, 2))
        speed = np.full(N, self.vmin)
        walking = np.zeros(N, dtype=bool)
        sep = np.zeros(N, dtype=np.int8)
        sep_start = np.zeros(N)
        own_zone = np.full(N, -1, dtype=np.int64)
        own_phase = np.full(N, DWELLING, dtype=np.int8)
        own_dwell_end = np.zeros(N)

        # Initial state: every unit is part-way through a dwell at a zone, so
        # departures are staggered rather than simultaneous.
        for u, members in enumerate(unit_members):
            z = self._choose_zone(self.rng_pos, set())
            anchor = self._point(self.rng_pos, z)
            full = self._dwell(self.rng_pos, z)
            unit_zone[u], unit_anchor[u] = z, anchor
            unit_dwell_end[u] = self.rng_pos.uniform(0.0, 1.0) * full
            pts = self.venue.clip(anchor + groups.offsets[members])
            pos[members] = pts
            target[members] = pts

        core = (sep == SeparationState.WITH_GROUP)
        core_size = np.array([len(m) for m in groups.members], dtype=np.int64)

        rec_pos = np.zeros((T, N, 2), dtype=np.float32)
        rec_walk = np.zeros((T, N), dtype=bool)
        rec_sep = np.zeros((T, N), dtype=np.int8)
        sep_events: list[tuple[int, int, int]] = []
        rejoin_events: list[tuple[int, int, int]] = []
        trip_speeds: list[float] = []
        in_group = group_of != NO_GROUP

        for t in range(T):
            # (a) Separation hazard: a fixed N draws per step keeps the stream aligned.
            draws = self.rng_sep.random(N)
            eligible = in_group & (sep == SeparationState.WITH_GROUP) & (draws < self.p_sep)
            for node in np.flatnonzero(eligible):
                g = group_of[node]
                if core_size[g] < 2:
                    continue  # the group must keep at least one member
                u = unit_of[node]
                z = self._choose_zone(self.rng_sep, {int(unit_zone[u])})
                sep[node] = SeparationState.SEPARATED
                sep_start[node] = t
                own_zone[node] = z
                own_phase[node] = MOVING
                target[node] = self._point(self.rng_sep, z)
                speed[node] = self.rng_sep.uniform(self.vmin, self.vmax)
                trip_speeds.append(float(speed[node]))
                walking[node] = True
                core_size[g] -= 1
                sep_events.append((t, int(node), int(g)))

            core = sep == SeparationState.WITH_GROUP

            # (b) Units whose dwell has ended choose a new destination.
            for u in np.flatnonzero((unit_phase == DWELLING) & (unit_dwell_end <= t)):
                z = self._choose_zone(self.rng_mob, {int(unit_zone[u])})
                anchor = self._point(self.rng_mob, z)
                base = self.rng_mob.uniform(self.vmin, self.vmax)
                trip_speeds.append(float(base))
                unit_phase[u], unit_zone[u], unit_anchor[u] = MOVING, z, anchor
                members = unit_members[u]
                members = members[core[members]]
                target[members] = self.venue.clip(anchor + groups.offsets[members])
                speed[members] = self._member_speed(base, groups.speed_factor[members])
                walking[members] = True

            # (c) Separated members at a decision point: rejoin or roam on.
            #     after_current_activity: decision point = end of own dwell.
            #     immediate_after_minimum: rejoin as soon as min_separation_s elapsed.
            is_sep = sep == SeparationState.SEPARATED
            done = is_sep & (own_phase == DWELLING) & (own_dwell_end <= t)
            if self.rejoin_policy == "immediate_after_minimum":
                done |= is_sep & (t - sep_start >= self.min_sep)
            for node in np.flatnonzero(done):
                if t - sep_start[node] >= self.min_sep:
                    sep[node] = SeparationState.REJOINING
                    speed[node] = self.rng_sep.uniform(self.vmin, self.vmax)
                    trip_speeds.append(float(speed[node]))
                else:
                    z = self._choose_zone(self.rng_sep, {int(own_zone[node])})
                    own_zone[node] = z
                    own_phase[node] = MOVING
                    target[node] = self._point(self.rng_sep, z)
                    speed[node] = self.rng_sep.uniform(self.vmin, self.vmax)
                    trip_speeds.append(float(speed[node]))
                    walking[node] = True

            # (d) Rejoining members chase the centroid of the group's core.
            rejoining = np.flatnonzero(sep == SeparationState.REJOINING)
            if rejoining.size:
                for node in rejoining:
                    g = group_of[node]
                    core_members = groups.members[g][core[groups.members[g]]]
                    centroid = pos[core_members].mean(axis=0)
                    goal = self.venue.clip(centroid + groups.offsets[node])
                    if np.hypot(*(goal - pos[node])) <= self.rejoin_dist:
                        sep[node] = SeparationState.WITH_GROUP
                        core[node] = True
                        core_size[g] += 1
                        rejoin_events.append((t, int(node), int(sep_start[node])))
                        u = unit_of[node]
                        target[node] = self.venue.clip(unit_anchor[u] + groups.offsets[node])
                        walking[node] = True
                    else:
                        target[node] = goal
                        walking[node] = True

            # Nodes asked to walk but already at their target do not move.
            delta = target - pos
            dist = np.hypot(delta[:, 0], delta[:, 1])
            walking &= dist > 1e-9

            rec_pos[t] = pos
            rec_walk[t] = walking
            rec_sep[t] = sep

            # (e) Movement during [t, t+1).
            if walking.any():
                idx = np.flatnonzero(walking)
                step = np.minimum(speed[idx], dist[idx])
                pos[idx] += delta[idx] / dist[idx, None] * step[:, None]
                arrived = idx[dist[idx] <= speed[idx]]
                pos[arrived] = target[arrived]
                walking[arrived] = False
                pos[:] = self.venue.clip(pos)

                # (f) Separated members reaching their own zone start dwelling.
                for node in arrived:
                    if sep[node] == SeparationState.SEPARATED and own_phase[node] == MOVING:
                        own_phase[node] = DWELLING
                        own_dwell_end[node] = t + 1 + self._dwell(self.rng_sep, int(own_zone[node]))

            # (g) Units whose core members have all arrived start dwelling.
            moving_units = np.flatnonzero(unit_phase == MOVING)
            if moving_units.size:
                still = np.bincount(unit_of[core & walking], minlength=U)
                for u in moving_units[still[moving_units] == 0]:
                    unit_phase[u] = DWELLING
                    unit_dwell_end[u] = t + 1 + self._dwell(self.rng_mob, int(unit_zone[u]))

        zone = self.venue.zone_of(rec_pos.astype(np.float64))
        return MobilityTrace(rec_pos, rec_walk, zone, rec_sep, groups,
                             sep_events, rejoin_events, trip_speeds)


def generate_mobility(cfg: dict, node_count: int, seed: int) -> MobilityTrace:
    """Convenience wrapper: run the festival mobility model."""
    return FestivalMobility(cfg, node_count, seed).run()
