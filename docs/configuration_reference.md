# Configuration reference

Configs are JSON (`configs/`). `pilot.json` and `confirmatory.json` extend `default.json` (deep merge).
Experiment arms override keys with dotted paths (e.g. `"routing.copy_budget": 16`). Every value can be
changed without editing source code; `simulator/config.py::validate_config` rejects inconsistent settings
(e.g. a duration too short to observe every message lifetime).

| Key | Default | Meaning |
|---|---|---|
| `phase` | development/pilot/confirmatory | must match the file's phase |
| `seeds` | 1-3 / 101-105 / 1001-1030 | master seeds (phase-locked ranges) |
| `simulation.time_step_s` | 1 | only 1 s supported |
| `simulation.duration_s` | 1800 | simulated seconds |
| `simulation.warmup_s` | 300 | routing and validation statistics start here |
| `venue.width_m`, `venue.height_m` | 150, 100 | rectangle |
| `venue.zones.<name>.x/y` | spec values | zone rectangles (m) |
| `nodes.node_count` | 100 | participating smartphones |
| `mobility.speed_min_mps`, `speed_max_mps` | 0.5, 1.3 | trip speed range |
| `mobility.member_speed_variation` | 0.05 | member speed factor U(1-v, 1+v) |
| `mobility.member_offset_m` | [0.5, 3.0] | personal offset radius from group anchor |
| `mobility.dwell_s.<zone>` | spec ranges | uniform dwell range (s); entrance 30-120 is a proposed default |
| `mobility.destination_probabilities.<zone>` | .35/.30/.20/.10/.05 | must sum to 1 |
| `mobility.group_participation` | 0.7 | share of nodes in friend groups |
| `mobility.group_size_min/max` | 2 / 6 | group size range |
| `mobility.separation_hazard_per_s` | 1/1800 | per eligible member per second |
| `mobility.min_separation_s` | 300 | minimum separation before rejoining |
| `mobility.rejoin_distance_m` | 3.0 | rejoined when this close to the core centroid + offset |
| `mobility.rejoin_policy` | after_current_activity | or `immediate_after_minimum` |
| `mobility.zone_point_margin_m` | 2.0 | destination points kept off zone edges |
| `communication.radius_m` | 10 | contact radius (inclusive) |
| `communication.transfer_capacity_per_node_per_s` | 5 | completed transfers per node per second |
| `communication.transfer_failure_prob` | 0.0 | optional impairment (exploratory) |
| `communication.contact_setup_delay_s` | 0 | optional impairment (exploratory) |
| `traffic.generation_start_s/end_s` | 300 / 900 | generation window [start, end) |
| `traffic.mean_interarrival_s` | 10 | network-wide Poisson mean gap |
| `traffic.message_lifetime_s` | 900 | lifetime |
| `traffic.payload_bytes` | 512 | recorded only |
| `traffic.workload_type` | separated_friends | or `random` |
| `buffer.capacity_messages` | 50 | distinct replicas per node |
| `buffer.drop_policy` | drop_oldest_created | only policy implemented |
| `routing.algorithm` | BSW | DirectDelivery, Epidemic, BSW, MWS |
| `routing.copy_budget` | 8 | L (token algorithms) |
| `routing.carrier_keeps_replica_after_delivery` | true | no acknowledgements |
| `routing.mws.friend_exclusion` | true | R1 |
| `routing.mws.walker_preference` | true | R2 |
| `routing.mws.patience_fallback` | true | R3 (needs R2) |
| `routing.mws.fallback_s` | 60 | R3 age threshold |
| `routing.mws.motion_signal` | immediate | or `historical` |
| `routing.mws.history_window_s` | 300 | historical window |
| `routing.mws.history_threshold` | 0.5 | historical walking threshold |
| `motion_classification.error_rate` | 0.0 | flip probability per node-second |
| `motion_classification.error_model` | independent | or `correlated` (exploratory) |
| `motion_classification.mean_burst_s` | 5 | correlated model burst length |
| `metrics.d2/d5/d15_threshold_s` | 120/300/900 | delivery thresholds (inclusive) |
| `statistics.alpha` | 0.05 | significance level |
| `statistics.h2_noninferiority_margin_pp` | 5.0 | proposed delta - needs approval |
| `statistics.bootstrap_resamples` | 5000 | seed-block bootstrap |
| `statistics.bootstrap_seed` | 20240531 | separate reproducible bootstrap seed |
| `statistics.planned_repetitions` | 30 | must equal the number of confirmatory seeds when freezing |
| `statistics.h4_model` | independent_groups_welch | or `repeated_measures_gg` |
| `statistics.zero_variance_rule` | inconclusive | identical paired differences -> non-computable, no p-value |
| `statistics.meaningful_target_effects_pp` | {"H1": null, "H5": null} | smallest meaningful D5 differences; must be set before `freeze` |
| `output.event_log` | false | event logs for every run (large) |
| `output.save_scenarios` | true | save shared scenarios (.npz) |
| `output.save_positions` | true/false | include positions in saved scenarios |
| `output.message_results` | true | write per-message CSVs |

Fields that cannot affect a run (outputs, seeds, statistics) are excluded from the configuration id. Fields an
algorithm ignores are normalised (see `effective_routing`), e.g. BSW's id does not depend on the motion error
rate, and MWS without R2 does not depend on fallback or motion settings.
