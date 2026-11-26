# Data dictionary

## run_results.csv (one row per run; ok and failed)

| Column | Meaning |
|---|---|
| experiment_id | experiments this configuration belongs to, `|`-separated (shared configurations list several) |
| run_id | `<configuration_id>_s<seed>` |
| configuration_id | hash of the effective configuration (equivalent configurations share it) |
| phase | development / pilot / confirmatory |
| algorithm, variant | effective algorithm and readable variant (e.g. `MWS[R1+R2+R3|immediate]@err10%`) |
| seed, node_count | master seed, participating smartphones |
| venue_width_m, venue_height_m, simulation_duration_s, communication_radius_m | scenario parameters |
| copy_budget | L (token algorithms only) |
| fallback_s, motion_error_rate, motion_signal | MWS parameters when relevant (blank otherwise) |
| workload_type | separated_friends or random |
| generated_messages | messages generated in the run |
| delivered_2min/5min/15min | unique messages first delivered within 120/300/900 s |
| d2_percent, d5_percent, d15_percent | the above / generated x 100 (%) |
| completed_transfers | intermediate_transfers + destination_transfers |
| intermediate_transfers | completed relay replications |
| destination_transfers | completed deliveries to destinations |
| repeated_destination_receptions | deliveries after the first (structurally 0; integrity check) |
| transfers_per_message | T = completed_transfers / generated_messages |
| mean/median/p90 (q25, q75)_latency_s | latency of delivered messages only (selection bias) |
| mean_delivery_hops | hops on the path of the first-delivering replica |
| undelivered_messages | generated - unique delivered (= undelivered at expiry) |
| expired_replicas | replicas still stored when their message expired |
| buffer_drops | replicas evicted from full buffers |
| duplicate_opportunities_prevented | opportunity-seconds where the peer already knew the message |
| runtime_s | routing wall-clock seconds (excludes scenario generation) |
| run_status | ok / failed |
| scenario_hash | fingerprint of groups, walking trace, contacts and workload (identical across algorithms) |
| code_version | `<version>+src.<source hash>[.git.<commit>]` |
| unique_delivered, source_replicas, created_replicas, peak_simultaneous_replicas | supporting counts |
| tokens_lost_buffer_drops, tokens_expired | token accounting |
| failed_transfers | link failures (only with the optional impairment) |
| rejected_transfers | incoming replicas rejected by drop-oldest-created |
| capacity_blocked_opportunities | candidates skipped because a node reached 5 transfers that second |
| token_exhausted_in_step, sender_replica_lost_in_step | within-second scheduling diagnostics |
| avg_buffer_occupancy, max_buffer_occupancy | replicas per node (time-averaged, maximum) |
| token_conservation_ok | tokens held + lost + expired == L x messages |
| avg_neighbour_count | mean neighbours per node in the scenario (algorithm independent) |
| workload_fallback_count | primary-workload messages using a fallback pair |
| scenario_generation_s | wall-clock of mobility + contacts + workload + validation (shared) |
| scenario_id, configuration_hash, full_config_sha256 | provenance keys |
| error_message | first line of the failure (failed runs) |
| decisions_<RULE> | opportunity-seconds per decision label (e.g. decisions_MWS_WALKER, decisions_BLOCK_FRIEND) |
| transfers_<RULE> | completed transfers by permitting rule (e.g. transfers_MWS_FALLBACK) |

| timely_deliveries_per_100_transfers | delivered_5min / completed_transfers x 100 (NaN if no transfer) |
| pct_messages_with_relay, mean_time_to_first_relay_s | share of messages with >= 1 relay; mean age at first relay (messages with a relay) |
| pct_messages_half_copies, mean_time_to_half_copies_s | ceil(L/2) copies exist (source + relays); token algorithms only |
| pct_messages_spray_complete, mean_time_to_spray_complete_s | every remaining replica holds one token; never reached if all replicas were dropped |
| copy_budget_utilization | mean over messages of relays / (L - 1) (NaN if not token-based or L = 1) |
| relays_before_first_delivery, relays_after_first_delivery | relays of delivered messages before / after their first delivery (run totals) |
| relays_on_undelivered_messages | relays of messages never delivered |
| intermediate_transfers_per_delivered_message | all relays / unique delivered messages (NaN if none delivered) |
| messages_dest_in_range_at_creation | messages whose destination was in contact with the source at creation (evaluation only) |
| d5_percent_dest_in_range, d5_percent_dest_out_of_range | D5 within these two subgroups (NaN if a subgroup is empty) |
| pct_messages_with_direct_contact | messages whose source and destination meet directly before expiry |
| pct_delivered_before_direct_contact, pct_delivered_via_relay | among delivered messages: delivered before any direct contact; first delivery hops > 1 |
| mean_interarrival_s, min_separation_s, rejoin_policy | traffic / mobility parameters varied by X3, X3b and X4 |
| walking_relay_transfers, fallback_relay_transfers | completed relays permitted by MWS R2 / R3 |
| walking_relay_share_of_relays, fallback_relay_share_of_relays | the above / intermediate_transfers |
| friend_exclusions_per_message, stationary_exclusions_per_message | R1 / R2 blocking decisions (opportunity-seconds) / generated messages |
| one_token_waits_per_message | opportunities skipped because the carrier held one token / generated messages |
| duplicates_prevented_per_message, capacity_blocked_per_message | opportunity-seconds / generated messages |

Full config, effective config and provenance (Python and dependency versions, git commit, timestamp) are in
`raw/runs/<run_id>.json`.

## message_results.csv
run_id, message_id, source_id, destination_id, source_destination_relationship (`separated_friends`,
`same_group_fallback`, `random_fallback`, `random_same_group`, `random_different_group`), creation_time_s,
expiry_time_s, first_delivery_time_s (blank if undelivered), delivery_latency_s, delivered_within_2min/5min/15min,
first_delivery_hops, completed_transfers_for_message, final_status (`delivered` / `undelivered_expired`),
relays_for_message, first_relay_age_s, half_copies_age_s, spray_complete_age_s, relays_before_first_delivery,
relays_after_first_delivery, dest_in_range_at_creation, first_direct_contact_age_s,
delivered_before_first_direct_contact, delivered_via_relay (the last four are evaluation-only diagnostics).

## raw/events/<run_id>.csv (optional, representative)
timestamp_s, event (`transfer`/`drop`/`expire`), sender, receiver, message_id, transfer_type
(`intermediate`/`destination`, or drop cause), sender_tokens_before, sender_tokens_after, receiver_tokens,
observed_receiver_walking (advertised state used by MWS; true state for other algorithms), friend_relationship,
message_age_s, rule (permitting rule or drop reason).

## mobility_validation.csv (one row per scenario)
Post-warm-up statistics: pct_time_walking/stationary, realised walking speed (mean, SD, percentiles,
histogram), zone_share_<zone>, avg_neighbours_per_node, neighbours_p50/p90/max, pct_node_time_isolated,
local_neighbours_<zone>, contact_events, contact_events_per_node_per_hour, contact_duration_mean/median/p90_s,
contact_events_censored, encounter_start_*_share (0/1/2 walkers at contact start), contact_seconds_*_share,
separation_events_total/post_warmup, rejoin_events_total, separation_duration_mean/median_s,
mean_separated_members, eligible_separated_pairs_mean_in_generation_window,
pct_generation_seconds_with_eligible_pair, messages_generated, workload_* counts, workload_fallback_share,
pairs_in_range_at_creation_share, initial_distance_median_m, integrity_* (must be 0).

## Analysis outputs
`summary_E*.csv` (mean/SD/CI/median per arm), `hypothesis_tests.csv`, `secondary_tests.csv`,
`exploratory_tests.csv`, `paired_differences_H*.csv`, `h4_details.json`, `sample_size_assessment.csv`,
`data_quality.csv`, `efficiency_metrics.csv`, `rule_diagnostics.csv`, `workload_diagnostics.csv`,
`sensitivity_X1_X4.csv`, `figures/data/*.csv` (exact plotted values).
