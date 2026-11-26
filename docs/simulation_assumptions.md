# Simulation assumptions

All values are synthetic modelling assumptions, not calibrated festival measurements. IDs are referenced by the
findings report and the approval checklist. Items marked **(approval)** are material and need researcher
sign-off before confirmatory runs (see `decisions_for_approval.md`).

## Time and venue
* **A1** Discrete time, 1 s step, 1,800 s; routing from the end of the 300 s warm-up. `positions[t]` is the
  location at integer t; `walking[t]` is true when the node moves during [t, t+1).
* **A2** Venue 150 x 100 m, unobstructed 2-D rectangle with the five specified zones (checked: inside the venue,
  non-overlapping; coordinates unchanged). No buildings, obstacles or body attenuation.

## Mobility
* **A3** Mobility units: each friend group is a unit, each independent node its own unit. Units alternate
  DWELLING at a zone and MOVING to another zone; the zone just visited is excluded from the next choice.
  Destination point uniform inside the zone, 2 m from its edges.
* **A4** Dwell uniform in the zone range (main/second stage 300-600, food 120-300, facilities 60-180,
  **entrance 30-120 s - proposed default (approval)**).
* **A5** Initialisation: every unit starts part-way through a dwell at a zone (residual = U(0,1) x a sampled
  dwell), staggering departures.
* **A6** Trip speed U(0.5, 1.3) m/s per unit trip; members walk at unit speed x U(0.95, 1.05) (clipped to the
  range) to `anchor + personal offset` (offset radius U(0.5, 3) m), so members never overlap and arrive at
  slightly different times. A group's dwell timer starts when every member currently with it has arrived.
* **A7** Group assignment: round(0.70 N) nodes in groups of size U{2..6}; a leftover of one becomes independent.
* **A8** Separation: each eligible member (in a group, with it, and the group would keep at least one member)
  separates with probability 1 - exp(-1/1800) per second. It walks to a different zone (excluding the group's
  current target), dwells, and roams independently.
* **A9 (approval)** Rejoin policy `after_current_activity`: rejoining starts at the first end of the separated
  member's own dwell after at least 300 s of separation; the member then walks (no teleporting) towards the
  current centroid of the members still with the group and rejoins within 3 m. Pilot mean separation lasted
  ~610-650 s and ~24-25 % of grouped nodes were separated at any time. Alternative pre-built policy:
  `immediate_after_minimum` (rejoin begins as soon as 300 s have elapsed).
* **A10** Mobility is generated from four independent streams and never depends on routing.

## Contacts and link
* **A11** Contact iff Euclidean distance <= radius (10 m; inclusive boundary), via `cKDTree.query_pairs`,
  computed from the stored float32 positions.
* **A12** Abstract idealised link: in-range nodes discover each other immediately; transfers succeed unless
  resource limits block them. No interference, setup delay or loss by default (optional impairments:
  `transfer_failure_prob`, `contact_setup_delay_s`, reduced capacity - exploratory, no calibrated values).
* **A13** Capacity: at most 5 completed transfers per node per second, counted for sender and receiver.
  Link-failed attempts (only with the optional impairment) also consume capacity; buffer rejections do not.
* **A14** Scheduling: deliveries before replications; counter-hash random order within a class; replicas
  received at t are forwardable from t+1; a sender's tokens update immediately, so it may spray to several
  peers within one second, each time splitting its current tokens.

## Messages
* **A15** Poisson generation, rate 0.1/s for 300 <= t < 900, creation times floored to whole seconds;
  identical generation times for both workloads of a (seed, N).
* **A16** Primary workload: uniform over ordered same-group pairs where at least one member is currently
  SEPARATED or REJOINING; fallbacks (same-group pair, then random pair) logged per message. Separation status
  only - not radio range - defines eligibility, so a few pairs are in range at creation (reported).
* **A17** A message is forwardable by its source in its creation second; latency = first-delivery second -
  creation second (0 possible).
* **A18** Lifetime 900 s: deliveries allowed while t <= expiry (D15 inclusive), replications while t < expiry;
  expired messages are purged after the exchange of their expiry second; every lifetime ends before 1,800 s.
* **A19** Destination consumes the message (no replica stored) but remembers it; repeated destination
  receptions are therefore structurally zero and serve as an integrity check.
* **A20** Carriers keep their replica after delivering (no acknowledgement); configurable.
* **A21** Duplicate suppression: a node remembers every message it held or received until expiry, including
  after a buffer drop, so a dropped message is never re-replicated to that node.
* **A22** Buffer 50 distinct replicas; policy `drop_oldest_created`: oldest message creation time (ties:
  earlier storage, lower id) is dropped; if the incoming replica is the oldest it is rejected atomically (no
  token or replica cost to the sender). The source's own new message can evict a stored replica.
* **A23** Payload size (512 B) is recorded but unused by the abstract link model.

## Motion classification
* **A24** Observed state = true state XOR flips; flips independent per node-second with the configured rate,
  generated once per scenario and error condition and shared by all observers. Common random numbers: the 10 %
  flips are a subset of the 20 % flips. Optional correlated errors: two-state Markov chain (mean burst 5 s).
* **A25** Historical signal uses the observed (error-affected) trace.

## Metrics and counting
* **A26** Duplicate-prevented and rule-decision counts are opportunity-seconds (one per second of contact per
  message), not distinct events.
* **A27** Routing runtime excludes shared scenario generation (reported separately).
