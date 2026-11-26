"""Motion-aware Walker-preferential Spray-and-Wait (MWS).

MWS changes only *relay selection* of Binary Spray-and-Wait; the initial token
budget and the binary split are unchanged. Three independently switchable
rules (for ablation):

R1 Friend exclusion
    Never spray to a device in the carrier's stable friend group. Applies to
    intermediate forwarding only - the destination is always eligible for
    direct delivery even if a friend (handled by the engine before this code
    runs). Fallback never relaxes R1.
R2 Walker preference
    Spray only to peers whose *currently advertised* motion state is walking.
R3 Patience fallback (meaningful only with R2)
    Once the message age (measured from original creation, not from when the
    carrier acquired it) is >= ``fallback_s``, stationary non-friends also
    become eligible.

Decision order per opportunity (engine already handled expiry, destination
delivery and duplicate suppression - pseudocode steps 1-3):

4. carrier holds one token -> do not forward;
5. R1: peer is a friend -> do not replicate;
6-7. R2/R3: walking peer -> spray; else age >= fallback -> spray; else retain.

The motion signal is supplied through a :class:`~simulator.motion.MotionOracle`
(immediate advertised state, or the smoothed historical variant for H5).
"""

from __future__ import annotations

import numpy as np

from simulator.node import NO_GROUP

from .base import Reason, RoutingAlgorithm
from .binary_spray_wait import binary_split


class MotionAwareSprayAndWait(RoutingAlgorithm):
    name = "MWS"
    uses_tokens = True

    def __init__(self, copy_budget: int, friend_exclusion: bool = True, walker_preference: bool = True,
                 patience_fallback: bool = True, fallback_s: float = 60.0, motion_signal: str = "immediate"):
        super().__init__(copy_budget)
        self.r1 = bool(friend_exclusion)
        self.r2 = bool(walker_preference)
        self.r3 = bool(patience_fallback) and self.r2
        self.fallback_s = float(fallback_s)
        self.motion_signal = motion_signal

    def replication_decision(self, t, messages, senders, receivers, sender_tokens):
        ctx = self.ctx
        assert ctx is not None, "algorithm not bound to a context"
        allowed = sender_tokens > 1
        reason = np.where(allowed, Reason.MWS_NO_MOTION_RULE, Reason.BLOCK_ONE_TOKEN).astype(np.int64)

        if self.r1:
            gs, gr = ctx.friend_group[senders], ctx.friend_group[receivers]
            friend = (gs != NO_GROUP) & (gs == gr)
            block = allowed & friend
            reason[block] = Reason.BLOCK_FRIEND
            allowed &= ~friend

        if self.r2:
            assert ctx.motion is not None, "walker preference requires a motion oracle"
            walking = ctx.motion.walking(t, receivers)
            age = t - ctx.created[messages]
            fallback_ok = (age >= self.fallback_s) if self.r3 else np.zeros(messages.shape, dtype=bool)
            via_walker = allowed & walking
            via_fallback = allowed & ~walking & fallback_ok
            blocked = allowed & ~walking & ~fallback_ok
            reason[via_walker] = Reason.MWS_WALKER
            reason[via_fallback] = Reason.MWS_FALLBACK
            reason[blocked] = Reason.BLOCK_STATIONARY
            allowed = via_walker | via_fallback
        return allowed, reason

    def split_tokens(self, tokens: int) -> tuple[int, int]:
        return binary_split(tokens)

    def describe(self) -> dict:
        d = super().describe()
        d.update({"R1_friend_exclusion": self.r1, "R2_walker_preference": self.r2,
                  "R3_patience_fallback": self.r3, "fallback_s": self.fallback_s,
                  "motion_signal": self.motion_signal})
        return d
