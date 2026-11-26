# Mobility, contact and workload validation (pilot)

Seeds: [101, 102, 103, 104, 105]. Code version: 1.0.0+src.93e0046b68.git.743ce3f5.dirty. Statistics use the post-warm-up period.
These outputs are algorithm-independent and were produced before any routing evaluation.

## Adequacy checks (pre-specified, algorithm-independent)

| criterion | rule | observed | pass |
|---|---|---|---|
| integrity | positions outside venue, stationary moves and speed violations are all zero | total violations = 0 | True |
| workload_fallback_share | <= 5 % of primary-workload messages use a fallback pair | max = 0.000 | True |
| eligible_pair_coverage | >= 95 % of generation-window seconds have an eligible separated pair | min = 100.0 % | True |
| grouped_fraction | within 5 percentage points of the configured group participation | range 0.700-0.700 | True |

## Key statistics across seeds (mean and SD across seeds)

| metric | N=50 mean (SD) | N=100 mean (SD) | N=200 mean (SD) |
|---|---|---|---|
| pct_time_walking | 25.822 (1.366) | 23.990 (0.441) | 24.978 (0.347) |
| walking_speed_realised_mean_mps | 0.813 (0.039) | 0.840 (0.019) | 0.839 (0.006) |
| avg_neighbours_per_node | 4.317 (0.563) | 7.605 (0.718) | 13.461 (0.258) |
| neighbours_p90 | 9.000 (1.581) | 14.600 (1.949) | 25.600 (0.894) |
| pct_node_time_isolated | 11.610 (1.868) | 5.727 (0.095) | 2.712 (0.208) |
| contact_events_per_node_per_hour | 141.754 (11.546) | 290.054 (18.641) | 582.408 (13.473) |
| contact_duration_median_s | 25.000 (3.536) | 22.400 (1.140) | 21.800 (0.447) |
| encounter_start_involving_walker_share | 0.938 (0.019) | 0.934 (0.014) | 0.958 (0.006) |
| contact_seconds_both_stationary_share | 0.740 (0.023) | 0.773 (0.012) | 0.762 (0.006) |
| separation_events_total | 24.600 (2.302) | 52.600 (3.209) | 106.600 (7.197) |
| separation_duration_mean_s | 652.227 (15.114) | 608.510 (23.857) | 612.971 (9.415) |
| mean_separated_members | 8.342 (1.175) | 17.267 (0.770) | 35.495 (4.527) |
| pct_generation_seconds_with_eligible_pair | 100.000 (0.000) | 100.000 (0.000) | 100.000 (0.000) |
| messages_generated | 58.600 (7.797) | 64.400 (9.889) | 61.000 (4.416) |
| workload_fallback_share | 0.000 (0.000) | 0.000 (0.000) | 0.000 (0.000) |
| pairs_in_range_at_creation_share | 0.057 (0.064) | 0.057 (0.043) | 0.075 (0.029) |
| grouped_fraction | 0.700 (0.000) | 0.700 (0.000) | 0.700 (0.000) |

## Share of node-time per zone (mean across seeds)

| node_count | main_stage | second_stage | food_court | facilities | entrance | circulation |
|---|---|---|---|---|---|---|
| 50 | 0.368 | 0.310 | 0.117 | 0.041 | 0.020 | 0.146 |
| 100 | 0.377 | 0.310 | 0.111 | 0.048 | 0.015 | 0.138 |
| 200 | 0.345 | 0.334 | 0.119 | 0.042 | 0.016 | 0.144 |

Interpretation notes:
- Densities are relative densities of participating smartphones, not total crowd density.
- 'encounter_start_involving_walker_share' is the share of contact events whose first second involves at least one walking node; contacts between two stationary nodes can only start when a node arrives, so this share is expected to be high under any mobility model with dwelling.
- Separated members rejoin their group physically, so many separated pairs are reunited within a message lifetime; this bounds how much any forwarding algorithm can improve D15.
