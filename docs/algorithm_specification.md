# Algorithm specification

All algorithms share the engine (`simulator/engine.py`): identical mobility trace, contacts, workload,
buffers, transfer capacity, scheduling and lifetime. An algorithm only decides whether a carrier may create
an intermediate replica for a peer (`replication_decision`) and how tokens are split (`split_tokens`).

## Common engine procedure (per second t, after warm-up)

1. Inject messages created at t into their source's buffer (source holds L tokens for token algorithms).
2. For each contact pair and each live message held by one side (replica available, i.e. received before t):
   1. message must be unexpired (replication: t < expiry; delivery: t <= expiry);
   2. **peer is the destination -> direct delivery candidate** (always allowed, any algorithm, any tokens);
   3. **peer already knows the message -> no transfer** (duplicate prevented);
   4. otherwise ask the algorithm (`replication_decision`).
3. Schedule candidates: deliveries first, then replications; within a class, counter-hash random order.
4. Process sequentially: both nodes below 5 completed transfers this second; sender still holds the replica;
   receiver still does not know the message; token re-check (tokens may have been split earlier in the same
   second); buffer acceptance (drop oldest-created, or reject the incoming replica atomically).
5. After the exchange, purge messages whose expiry is t.

A replica received at t can be forwarded from t+1, so there is no multi-hop propagation within a second.
Destinations consume messages (no stored replica) but remember them for duplicate suppression. Carriers keep
their replica after delivering (no acknowledgement mechanism; configurable).

## Direct Delivery
The source holds the message until it meets the destination. `replication_decision` always refuses
(`BLOCK_NO_RELAY`). Minimal-transfer reference.

## Epidemic Routing (after Vahdat & Becker, 2000)
Every message the peer has not received is replicated (`EPIDEMIC`). No token budget; buffer, capacity,
duplicate suppression and lifetime still apply, so 100 % delivery is not assumed.

## Binary Spray-and-Wait (after Spyropoulos, Psounis & Raghavendra, 2005) - primary baseline
Source starts with L tokens (L = 8 primary; 4 and 16 in E2). A carrier with c > 1 tokens meeting a peer that
has not received the message gives floor(c/2) and keeps c - floor(c/2) (8 -> 4/4; 5 -> 2/3). With c = 1 the
carrier waits for the destination. Tokens are a replication budget, not stored copies. Failed or rejected
transfers cost no tokens; a dropped replica's tokens are lost (never recreated). The engine verifies token
conservation every second and at the end of each run.

## MWS - Motion-aware Walker-preferential Spray-and-Wait
Same initial budget and binary split as BSW; only relay selection changes. Rules (independently switchable):

* **R1 friend exclusion** - never spray to a member of the carrier's stable friend group. Intermediate
  forwarding only; the destination is always eligible for delivery even if a friend. Fallback never relaxes R1.
* **R2 walker preference** - spray only to peers whose *advertised motion state at the current second* is
  walking (ideal model: observed = true state).
* **R3 patience fallback** - when message age (from original creation) >= 60 s, stationary non-friends also
  become eligible. Meaningful only with R2; without R2 it is normalised away.

Per carrier, message and peer (engine performs 1-3):

```
1  message valid and unexpired?
2  peer is destination            -> attempt direct delivery
3  peer already knows message     -> no replication
4  carrier holds one token        -> do not forward                 (BLOCK_ONE_TOKEN)
5  R1 and peer is a friend        -> do not replicate               (BLOCK_FRIEND)
6  read peer's advertised motion at t and message age = t - created
7  R2: walking -> spray (MWS_WALKER); else R3 and age >= 60 -> spray (MWS_FALLBACK); else retain (BLOCK_STATIONARY)
   (no R2: spray to any eligible non-friend, MWS_NO_MOTION_RULE)
8  buffer and capacity checks (engine)
9  success: receiver gets floor(c/2), carrier keeps the rest; record transfer + rule
```

MWS with no rule enabled is canonicalised to BSW (same configuration id, same code path).

### Ablation variants (E3)
BSW (no rules), R1 only, R2 only, R1+R2, R2+R3, Full (R1+R2+R3).

### Motion-information variants (E4 / H5)
* **Immediate** - advertised walking state at t.
* **Historical** - proportion of advertised-walking samples in the trailing 300 s window (t-299 .. t, only
  samples at or before t); walking if the score >= 0.5. Warm-up provides the initial history.

The two variants receive identical inputs except the motion oracle (tested). This is an internal controlled
ablation, **not** a reproduction of Kawecki & Schoeneich (2016).

## Information available to algorithms
`AlgorithmContext` holds only: stable friend-group ids, message creation times, and a `MotionOracle` that
returns the advertised state at the queried (current) second. Global delivery records are never passed to
algorithms (tested).

## Optional published baselines - not implemented
Spray-and-Focus, Kawecki & Schoeneich mobility-based routing and Social Spray-and-Wait (Manole et al., 2021)
were not implemented because the original publications were not inspected and reproduced in this work. No
comparison with them is claimed. Any future approximation must use a distinct name and document differences.
