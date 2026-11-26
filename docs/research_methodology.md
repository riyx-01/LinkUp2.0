# Research methodology

## Design

Applied quantitative, survey-informed comparative simulation experiment. The survey (O1/RQ1) motivates the
requirements - timely delivery, reliability, support for separated friends, controlled replication and
smartphone practicality - but **validates no simulation parameter, does not justify the 5-minute threshold and
does not show that MWS works**. No survey data are generated, merged with simulation data or used as targets.

The simulator addresses O3-O6 and RQ2-RQ6. The contribution under test is the controlled evaluation of
*immediate walking-state relay selection* in bounded-copy opportunistic forwarding (MWS vs Binary
Spray-and-Wait at the same copy budget).

## Phases and seeds

| Phase | Seeds | Purpose | Gate |
|---|---|---|---|
| development | 1-9 | coding, tests, smoke runs, benchmark, dashboard | none |
| pilot | 101-105 | runtime, mobility plausibility, workload validity, variability, repetition count | none |
| confirmatory | 1001-1030 | hypothesis tests H1-H5 and supporting experiments | `configs/confirmatory.approval.json` |

Seeds outside a phase's range are refused by the runner. Pilot seeds are never confirmatory observations.
Pilot results are used only for the purposes listed above and never to tune MWS.

## Scenario sharing and fairness

For each (seed, node count) the mobility trace is generated once; for each (radius, workload) the contact
trace and workload are derived once; for each motion-error condition the observed-motion trace is derived
once. Every algorithm runs on the same scenario object. Independent RNG streams (initial positions, group
assignment, mobility, separation, message generation, pair selection, motion errors, scheduling,
link failures) are derived from `SeedSequence([seed, stream_code, node_count, ...])`, so the routing algorithm
cannot alter movement or message randomness. Scheduling tie-breaks use a counter-based hash of
(t, message, sender, receiver), so the same candidate transfer receives the same random key under every
algorithm (common random numbers) and node-ID magnitude is irrelevant.

## Unit of analysis

One (scenario, seed) run is one observation. Messages within a run are not independent replicates. MWS and
BSW are paired by seed within the same scenario. For H1-H3 the per-seed observation is the equally weighted
mean of the three density-specific paired differences (so 200 nodes does not dominate).

## Blocking across densities

The master seed identifies a block across densities, but streams are density specific, so the three
density scenarios of a block are statistically independent draws. The pre-specified H4 model is therefore an
independent-groups model (Welch one-way ANOVA); repeated-measures ANOVA with Greenhouse-Geisser correction,
Kruskal-Wallis and Friedman tests are reported as sensitivity analyses. This choice is recorded in
`configs/*.json -> statistics.h4_model` and must be approved before confirmatory testing.

## Workflow and integrity rules

1. Tests and handcrafted scenarios before any batch (`pytest -q`).
2. Algorithm-independent mobility validation before routing evaluation (`main.py validate`).
3. Pilot (5 seeds) - runtime, plausibility, workload validity, variability, sample size.
4. Methodology freeze: final config, algorithm specification, statistical plan, H2 margin and repetitions,
   approved by the researcher/mentor (`main.py freeze`). Any later change to the confirmatory config, the
   experiment matrix or the simulation source invalidates the freeze.
5. Confirmatory execution, resumable, with every run's config, seed, scenario hash, code version and
   dependency versions stored. Failed runs are recorded and never silently omitted.
6. Analysis exactly as pre-specified; all valid runs are reported; no run is discarded unless it meets a
   previously documented technical-invalidity criterion (failed run, token-conservation violation, mixed code
   version - all detected by the data-quality checks).

Never: tuning mobility, destinations, fallback threshold, motion classification, seeds, transfer limits or
statistical methods to favour MWS; adding or removing confirmatory seeds until significance appears; choosing
the test with the smallest p-value; presenting exploratory results as confirmatory.

## Scope reduction

If resources are limited, E1 and E4 (formal hypotheses) take priority; E2, E3, E5 and E6 are supporting.
Measured runtime (`results/benchmark/benchmark.md`) shows the full 750-run matrix is feasible on a laptop, so
no scope reduction is proposed. Any reduction must be documented before confirmatory outcomes are inspected.
