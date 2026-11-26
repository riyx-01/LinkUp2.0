"""Node-level constants shared by the mobility model and the routing engine.

Nodes are *participating smartphones*, not all attendees. Per-node state is
stored in NumPy arrays (structure-of-arrays) for speed; this module defines the
codes used in those arrays.
"""

from __future__ import annotations

from enum import IntEnum

NO_GROUP = -1  # friend-group id for independent (ungrouped) nodes


class MotionState(IntEnum):
    STATIONARY = 0
    WALKING = 1


class SeparationState(IntEnum):
    """Group-separation status of a node (independent nodes are always WITH_GROUP)."""

    WITH_GROUP = 0   # moving with its friend group (or independent)
    SEPARATED = 1    # temporarily following its own destinations
    REJOINING = 2    # walking physically towards the group's current location
