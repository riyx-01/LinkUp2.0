"""LinkUp Research Simulator core package.

The simulator is a discrete-time (1 s step) model of participating smartphones
moving through a synthetic festival venue. It is split into two strictly
separated layers:

1. *Scenario layer* (algorithm independent): venue, friend groups, festival
   mobility, contact trace, observed-motion trace and the message workload.
   A scenario is generated once per (seed, node count, radius, workload) and
   shared by every routing algorithm.
2. *Routing layer*: the forwarding engine replays a scenario's contact trace and
   applies one routing algorithm under identical buffer, capacity and lifetime
   constraints.
"""

__version__ = "1.0.0"
