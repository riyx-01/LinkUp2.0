"""Discrete-time store-carry-and-forward routing engine.

The engine replays a shared :class:`~simulator.scenario.Scenario` and applies
one routing algorithm. Everything except the algorithm's
``replication_decision``/``split_tokens`` is common to all algorithms: message
injection, contact handling, destination delivery, duplicate suppression,
scheduling, transfer capacity, buffer policy, expiry and metric collection.

Time-step semantics (step t = simulated second t, t = warmup .. duration-1):

1. **Inject** messages created at t into their source's buffer (available for
   forwarding in the same step).
2. **Exchange** over the contact list at t. Candidates use replica state at the
   start of the step; replicas received during step t become forwardable at
   t+1 (no multi-hop propagation within a step). Destination deliveries are
   scheduled before replications; capacity is shared by sending and receiving.
3. **Purge** messages whose expiry equals t, *after* the exchange, so a
   delivery exactly at the lifetime boundary counts (D15 inclusive of 900 s).
   Replication requires ``t < expiry``; destination delivery ``t <= expiry``.

Algorithms never see ``delivered_time`` or any other global delivery record.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from algorithms.base import Reason, RoutingAlgorithm
from algorithms.variants import build_algorithm

from .buffers import ReplicaStore
from .metrics import compute_message_rows, compute_run_metrics
from .rng import stream_base_key
from .scenario import Scenario
from .scheduler import PRIORITY_DELIVERY, PRIORITY_REPLICATION, schedule_order, uniform_draws

EVENT_FIELDS = ("timestamp_s", "event", "sender", "receiver", "message_id", "transfer_type",
                "sender_tokens_before", "sender_tokens_after", "receiver_tokens",
                "observed_receiver_walking", "friend_relationship", "message_age_s", "rule")


@dataclass
class RunOutput:
    metrics: dict
    messages: list[dict]
    events: list[tuple] = field(default_factory=list)
    decision_counts: dict = field(default_factory=dict)
    transfer_reasons: dict = field(default_factory=dict)
    timeline: dict = field(default_factory=dict)


class RoutingEngine:
    def __init__(self, cfg: dict, scenario: Scenario, algorithm: RoutingAlgorithm | None = None,
                 event_log: bool = False, strict_checks: bool = True):
        self.cfg = cfg
        self.scen = scenario
        self.algo = algorithm if algorithm is not None else build_algorithm(cfg, scenario)
        self.event_log = event_log
        self.strict = strict_checks

        sim, comm = cfg["simulation"], cfg["communication"]
        self.start = int(sim["warmup_s"])
        self.end = int(sim["duration_s"])
        self.capacity = int(comm["transfer_capacity_per_node_per_s"])
        self.p_fail = float(comm["transfer_failure_prob"])
        self.setup_delay = int(comm["contact_setup_delay_s"])
        self.keep_after_delivery = bool(cfg["routing"]["carrier_keeps_replica_after_delivery"])

        msgs = scenario.messages
        self.M, self.N = msgs.count, scenario.node_count
        self.store = ReplicaStore(self.M, self.N, cfg["buffer"]["capacity_messages"])
        self.created = msgs.created.astype(np.int64)
        self.expiry = msgs.expiry.astype(np.int64)
        self.src = msgs.source.astype(np.int64)
        self.dst = msgs.destination.astype(np.int64)
        if self.M and (self.created.min() < self.start or self.expiry.max() > self.end - 1):
            raise ValueError("Workload lies outside the observable routing window.")

        self.delivered_time = np.full(self.M, -1, dtype=np.int64)
        self.delivered_hops = np.full(self.M, -1, dtype=np.int64)
        self.msg_transfers = np.zeros(self.M, dtype=np.int64)
        # Efficiency diagnostics (from actual transfer events; -1 = not reached).
        self.msg_relays = np.zeros(self.M, dtype=np.int64)
        self.first_relay_time = np.full(self.M, -1, dtype=np.int64)
        self.half_copies_time = np.full(self.M, -1, dtype=np.int64)
        self.spray_complete_time = np.full(self.M, -1, dtype=np.int64)
        self.relays_before_delivery = np.zeros(self.M, dtype=np.int64)
        self.relays_after_delivery = np.zeros(self.M, dtype=np.int64)
        budget = self.algo.initial_tokens()
        self.half_copies_target = int(np.ceil(budget / 2)) if self.algo.uses_tokens else None
        self.injected = np.zeros(self.M, dtype=bool)
        self.purged = np.zeros(self.M, dtype=bool)
        self.c: Counter = Counter()
        self.reason_opps = np.zeros(16, dtype=np.int64)
        self.reason_xfers = np.zeros(16, dtype=np.int64)
        self.events: list[tuple] = []
        seed = scenario.seed
        self.sched_key = stream_base_key(seed, "scheduling", self.N)
        self.fail_key = stream_base_key(seed, "transfer_failures", self.N)
        self.group_of = scenario.mobility.groups.group_of
        self._contact_prev_codes = np.empty(0, dtype=np.int64)
        self._contact_prev_start = np.empty(0, dtype=np.int64)
        self.timeline = {"t": [], "delivered": [], "replicas": []}

    # ------------------------------------------------------------------ run
    def run(self) -> RunOutput:
        wall0 = time.perf_counter()
        order = np.argsort(self.created, kind="stable")
        ptr = 0
        expiring: dict[int, list[int]] = {}
        for m in range(self.M):
            expiring.setdefault(int(self.expiry[m]), []).append(m)

        occ_sum, occ_max, peak_replicas, steps = 0, 0, 0, 0
        for t in range(self.start, self.end):
            while ptr < self.M and self.created[order[ptr]] <= t:
                self._inject(int(order[ptr]), t)
                ptr += 1

            pairs = self.scen.contacts.at(t)
            if self.setup_delay > 0:
                pairs = self._apply_setup_delay(pairs, t)
            live = np.flatnonzero(self.injected & ~self.purged)
            if live.size and pairs.size:
                self._exchange(t, pairs, live)

            total = int(self.store.occupancy.sum())
            peak_replicas = max(peak_replicas, total)
            occ_sum += total
            occ_max = max(occ_max, int(self.store.occupancy.max()))
            steps += 1
            if self.strict and self.algo.uses_tokens:
                self._check_tokens()
            if self.algo.uses_tokens and live.size:
                self._update_spray_completion(t, live)

            self.timeline["t"].append(t)
            self.timeline["delivered"].append(int((self.delivered_time >= 0).sum()))
            self.timeline["replicas"].append(total)

            for m in expiring.get(t, ()):
                replicas, tokens = self.store.purge_message(m)
                self.purged[m] = True
                self.c["expired_replicas"] += replicas
                self.c["tokens_expired"] += tokens
                if self.event_log and replicas:
                    self.events.append((t, "expire", -1, -1, m, "expiry", None, None, None, None, None,
                                        t - int(self.created[m]), f"{replicas} replicas"))

        if not self.purged.all():
            raise RuntimeError("Not every message reached expiry inside the simulation window.")
        runtime = time.perf_counter() - wall0
        self.c["buffer_occupancy_sum"] = occ_sum
        metrics = compute_run_metrics(self, runtime=runtime, steps=steps, peak_replicas=peak_replicas,
                                      occ_max=occ_max)
        return RunOutput(metrics=metrics, messages=compute_message_rows(self), events=self.events,
                         decision_counts=self._reason_dict(self.reason_opps),
                         transfer_reasons=self._reason_dict(self.reason_xfers), timeline=self.timeline)

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _reason_dict(arr: np.ndarray) -> dict:
        return {Reason(i).name: int(v) for i, v in enumerate(arr) if v and i in Reason._value2member_map_}

    def _update_spray_completion(self, t: int, live: np.ndarray) -> None:
        """Spray phase complete = every remaining replica holds a single token (wait phase only).

        A message whose replicas were all lost to buffer drops never completes its spray phase.
        """
        pending = live[self.spray_complete_time[live] < 0]
        if pending.size == 0:
            return
        holds = self.store.holds[pending]
        max_tok = self.store.tokens[pending].max(axis=1)
        done = holds.any(axis=1) & (max_tok <= 1)
        self.spray_complete_time[pending[done]] = t

    def _check_tokens(self) -> None:
        held = self.store.tokens.sum(axis=1)
        if (held > self.algo.copy_budget).any() or (self.store.tokens < 0).any():
            raise AssertionError("Token budget violated: tokens were created.")

    def _apply_setup_delay(self, pairs: np.ndarray, t: int) -> np.ndarray:
        """Keep pairs whose contact has lasted at least ``setup_delay`` seconds."""
        codes = pairs[:, 0].astype(np.int64) * self.N + pairs[:, 1]
        prev, prev_start = self._contact_prev_codes, self._contact_prev_start
        idx = np.searchsorted(prev, codes)
        idx_c = np.minimum(idx, max(len(prev) - 1, 0))
        present = (idx < len(prev)) & (prev[idx_c] == codes) if len(prev) else np.zeros(len(codes), bool)
        starts = np.where(present, prev_start[idx_c] if len(prev) else t, t)
        self._contact_prev_codes, self._contact_prev_start = codes, starts
        return pairs[(t - starts) >= self.setup_delay]

    def _inject(self, m: int, t: int) -> None:
        s = int(self.src[m])
        self.injected[m] = True
        if self.store.is_full(s):
            victim = self.store.eviction_victim(s, m, self.created, t)
            if victim < 0:  # pragma: no cover - a new message is never the oldest
                self.c["source_rejections"] += 1
                self.store.knows[m, s] = True
                return
            self._drop(victim, s, t, cause="source_injection")
        self.store.store(m, s, self.algo.initial_tokens(), available=t, now=t, hops=0)
        self.c["source_replicas"] += 1
        if self.half_copies_target is not None and self.half_copies_target <= 1:
            self.half_copies_time[m] = t

    def _drop(self, m: int, node: int, t: int, cause: str) -> None:
        tokens = self.store.remove(m, node)
        self.c["buffer_drops"] += 1
        self.c["tokens_lost_buffer_drops"] += tokens
        if self.event_log:
            self.events.append((t, "drop", node, -1, m, cause, tokens, 0, None, None, None,
                                t - int(self.created[m]), "buffer_full"))

    # ------------------------------------------------------------ exchange
    def _exchange(self, t: int, pairs: np.ndarray, live: np.ndarray) -> None:
        store = self.store
        a = pairs[:, 0].astype(np.int64)
        b = pairs[:, 1].astype(np.int64)
        holds_l = store.holds[live]
        any_holder = holds_l.any(axis=0)
        keep = any_holder[a] | any_holder[b]
        if not keep.any():
            return
        a, b = a[keep], b[keep]
        can_send = holds_l & (store.available[live] <= t)
        knows_l = store.knows[live]

        ms, ss, rs = [], [], []
        for snd, rcv in ((a, b), (b, a)):
            S = can_send[:, snd]
            if not S.any():
                continue
            K = knows_l[:, rcv]
            self.c["duplicate_opportunities_prevented"] += int(np.count_nonzero(S & K))
            li, pi = np.nonzero(S & ~K)
            if li.size:
                ms.append(live[li])
                ss.append(snd[pi])
                rs.append(rcv[pi])
        if not ms:
            return
        m = np.concatenate(ms)
        s = np.concatenate(ss)
        r = np.concatenate(rs)

        is_del = r == self.dst[m]
        rep_idx = np.flatnonzero(~is_del & (t < self.expiry[m]))
        del_idx = np.flatnonzero(is_del)
        rep_keep = np.empty(0, dtype=np.int64)
        rep_reason = np.empty(0, dtype=np.int64)
        if rep_idx.size:
            allowed, reason = self.algo.replication_decision(
                t, m[rep_idx], s[rep_idx], r[rep_idx], store.tokens[m[rep_idx], s[rep_idx]])
            self.reason_opps += np.bincount(reason, minlength=16)[:16]
            rep_keep = rep_idx[allowed]
            rep_reason = reason[allowed]
        self.reason_opps[Reason.DELIVERY] += del_idx.size
        cand = np.concatenate([del_idx, rep_keep])
        if cand.size == 0:
            return
        prio = np.concatenate([np.full(del_idx.size, PRIORITY_DELIVERY),
                               np.full(rep_keep.size, PRIORITY_REPLICATION)])
        reasons = np.concatenate([np.full(del_idx.size, Reason.DELIVERY, dtype=np.int64), rep_reason])
        cm, cs, cr = m[cand], s[cand], r[cand]
        order = schedule_order(self.sched_key, t, cm, cs, cr, prio)
        fail_u = uniform_draws(self.fail_key, t, cm, cs, cr) if self.p_fail > 0 else None
        self._process(t, order, cm.tolist(), cs.tolist(), cr.tolist(), prio.tolist(), reasons.tolist(),
                      fail_u)

    def _process(self, t, order, cm, cs, cr, prio, reasons, fail_u) -> None:
        store, algo, c = self.store, self.algo, self.c
        holds, knows, tokens, hops = store.holds, store.knows, store.tokens, store.hops
        cap = Counter()
        capacity = self.capacity
        uses_tokens = algo.uses_tokens
        for k in order.tolist():
            mm, snd, rcv = cm[k], cs[k], cr[k]
            if cap[snd] >= capacity or cap[rcv] >= capacity:
                c["capacity_blocked"] += 1
                continue
            if not holds[mm, snd]:
                c["sender_replica_lost_in_step"] += 1
                continue
            if knows[mm, rcv]:
                c["duplicate_opportunities_prevented"] += 1
                continue
            if fail_u is not None and fail_u[k] < self.p_fail:
                c["failed_transfers"] += 1
                cap[snd] += 1
                cap[rcv] += 1
                continue

            if prio[k] == PRIORITY_DELIVERY:
                knows[mm, rcv] = True
                cap[snd] += 1
                cap[rcv] += 1
                c["completed_transfers"] += 1
                c["destination_transfers"] += 1
                self.msg_transfers[mm] += 1
                self.reason_xfers[Reason.DELIVERY] += 1
                if self.delivered_time[mm] < 0:
                    self.delivered_time[mm] = t
                    self.delivered_hops[mm] = int(hops[mm, snd]) + 1
                else:  # pragma: no cover - prevented by duplicate suppression
                    c["repeated_destination_receptions"] += 1
                tok = int(tokens[mm, snd])
                if self.event_log:
                    self._log(t, "transfer", snd, rcv, mm, "destination", tok, tok, 0, "delivery")
                if not self.keep_after_delivery:
                    c["tokens_retired_after_delivery"] += store.remove(mm, snd)
                    c["replicas_removed_after_delivery"] += 1
                continue

            # Intermediate replication.
            give = keep = 0
            before = int(tokens[mm, snd])
            if uses_tokens:
                if before <= 1:
                    c["token_exhausted_in_step"] += 1
                    continue
                give, keep = algo.split_tokens(before)
            if store.is_full(rcv):
                victim = store.eviction_victim(rcv, mm, self.created, t)
                if victim < 0:
                    c["rejected_transfers"] += 1
                    continue
                self._drop(victim, rcv, t, cause="incoming_transfer")
            store.store(mm, rcv, give, available=t + 1, now=t, hops=int(hops[mm, snd]) + 1)
            if uses_tokens:
                tokens[mm, snd] = keep
            cap[snd] += 1
            cap[rcv] += 1
            c["completed_transfers"] += 1
            c["intermediate_transfers"] += 1
            self.msg_transfers[mm] += 1
            self.reason_xfers[reasons[k]] += 1
            self.msg_relays[mm] += 1
            if self.first_relay_time[mm] < 0:
                self.first_relay_time[mm] = t
            if (self.half_copies_target is not None and self.half_copies_time[mm] < 0
                    and 1 + self.msg_relays[mm] >= self.half_copies_target):
                self.half_copies_time[mm] = t
            if self.delivered_time[mm] < 0:
                self.relays_before_delivery[mm] += 1
            else:
                self.relays_after_delivery[mm] += 1
            if self.event_log:
                self._log(t, "transfer", snd, rcv, mm, "intermediate", before,
                          keep if uses_tokens else before, give, Reason(reasons[k]).name)

    def _log(self, t, event, snd, rcv, m, kind, before, after, recv_tokens, rule) -> None:
        motion = getattr(self.algo.ctx, "motion", None) if self.algo.ctx else None
        walking = bool(motion.walking(t, np.array([rcv]))[0]) if motion is not None else \
            bool(self.scen.mobility.walking[t, rcv])
        gs, gr = self.group_of[snd], self.group_of[rcv]
        friend = bool(gs >= 0 and gs == gr)
        self.events.append((t, event, snd, rcv, m, kind, before, after, recv_tokens, walking, friend,
                            t - int(self.created[m]), rule))


def run_simulation(cfg: dict, scenario: Scenario, event_log: bool = False) -> RunOutput:
    """Build the configured algorithm and run it on ``scenario``."""
    return RoutingEngine(cfg, scenario, event_log=event_log).run()
