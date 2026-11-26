# Validation report (implementation and pilot stage)

Code version `1.0.0+src.5f0c2c3d5e`; Windows 11, Python 3.12.6, 20 logical CPUs. Generated outputs referenced
here are reproducible with the commands shown. The figures below are copied from those outputs (2026-11-26);
re-running regenerates them exactly.

## 1. Automated tests (`pytest -q`)

103 tests passed (about 90 s). Coverage by area:

| File | What is verified |
|---|---|
| test_mobility | nodes stay inside the venue; stationary nodes never move; speed <= 1.3 m/s; walking nodes move; friends never overlap; group sizes 2-6, 70 % participation; destination excludes current zone; separations occur, respect the 300 s minimum and keep >= 1 member with each group; identical seed -> identical trace; rejoin policies; routing never mutates the scenario |
| test_contacts | inclusive radius boundary (10 m exactly, 3-4-5 triangle); exclusion just beyond; agreement with brute force; trace storage and contact-event durations |
| test_messages | generation only in [300, 900); Poisson rate; full lifetime observed and config rejects truncation; primary pairs are separated friends; random workload distinct and shares generation times and mobility; reproducible workload; delivery exactly at expiry counts, no forwarding after expiry, no replication at the expiry second |
| test_buffers | buffer capacity never exceeded; 5 transfers/node/s never exceeded; delivery priority under capacity limits; drop-oldest-created with token loss; atomic rejection costs the sender nothing; source injection eviction |
| test_baselines | 8 -> 4/4, 5 -> 2/3 tokens; 1 token: no relay but delivery; tokens never created (random runs, L = 4/8/16); failed transfers cost no tokens; **store-carry-forward delivery without any end-to-end path** (Direct fails, Epidemic/BSW/MWS deliver via the carrier); no multi-hop within one step; expired messages never forwarded; known messages never re-replicated (also after a drop); identical scenario hash for all algorithms |
| test_mws | destination overrides friend exclusion; walking non-friend eligible; friend ineligible; stationary stranger ineligible at 59 s and eligible at exactly 60 s; friend still ineligible after 60 s; one-token carrier cannot spray; duplicate suppression precedes MWS rules; age measured from original creation; all rules off == BSW (identical metrics and configuration id); each ablation behaves as specified; immediate vs historical differ only in the motion signal; historical window uses only past samples; error flips shared, nested and at the configured rate; algorithms cannot access delivery records |
| test_metrics | D2/D5/D15 on known timestamps; undelivered messages stay in denominators; transfer counting; unique deliveries not double counted; prevented duplicates are not transfers; identical config + seed -> identical metrics |
| test_statistics | pairing by seed and missing-pair detection; t-test equals SciPy; non-inferiority decisions and bound/p-value agreement; Holm equals statsmodels and a hand calculation; restricted decision wording; zero-variance rule; full H1-H5 family on constructed data; H4 null case; failed/missing run detection; CI and bootstrap reproducibility |
| test_reproducibility | scenario independent of algorithm; density-specific independent streams; algorithm-free scheduling keys; scenario save/load round trip; equivalence detection (25 unique configurations, shared Full-MWS configuration); phase seed ranges enforced; confirmatory run refused without approval; approval detects config tampering; resumable batch and missing-run recovery |
| test_dashboard | replayed carriers equal the engine's replica counts; carriers respect the budget; LinkUp Explorer data equal the engine outputs (positions, walking, separation, every hand-over and delivery, counters, metrics); no gradients or glow in the page; the Explorer runs in headless Chrome in all three styles without script errors; Streamlit app renders headlessly |

`python main.py smoke` passes: N = 50, seed 1, all four algorithms reproduce identical metrics from two
independently generated scenarios, and token conservation holds.

## 2. Benchmark (`python main.py benchmark`, development seeds 1-2)

Mean routing wall-clock per run (s): Direct 0.21 / 0.35 / 0.85, Epidemic 0.25 / 0.53 / 1.53,
BSW 0.32 / 0.69 / 1.96, MWS 0.40 / 0.84 / 2.08 at 50 / 100 / 200 nodes. Scenario generation per (seed, N):
0.5 / 0.8 / 2.2 s. Estimated serial batch time from these measurements: pilot (125 runs) about 2 min;
confirmatory (750 runs) about 12 min. **Measured pilot: 125 runs in 30.2 s with 4 workers, 0 failures.**
Pilot output size: about 14 MB (scenarios saved without positions).

## 3. Mobility, contact and workload validation (pilot seeds 101-105, before routing)

Source: `results/pilot/validation/mobility_validation.md` and figure 15. Mean across seeds (N = 50 / 100 / 200):

* Time walking: 25.8 / 24.0 / 25.0 %; realised walking speed 0.81 / 0.84 / 0.84 m/s.
* Mean neighbours per node (r = 10 m): 4.3 / 7.6 / 13.5; node-time isolated 11.6 / 5.7 / 2.7 %.
* Contacts per node per hour: 142 / 290 / 582; median contact duration 25 / 22 / 22 s.
* Contact events whose first second involves >= 1 walker: 94 / 93 / 96 %.
* Separation events per run: 25 / 53 / 107; mean separation duration 652 / 609 / 613 s; about 24-25 % of
  grouped nodes separated at any time.
* Eligible separated pair available in 100 % of generation seconds; workload fallback share 0 %; 6-8 % of
  primary-workload pairs are within radio range at creation.
* Zone occupancy: main stage 35-38 %, second stage 31-33 %, food court 11-12 %, facilities 4-5 %, entrance 2 %,
  circulation 14-15 %.
* All pre-specified adequacy checks pass (integrity violations 0; fallback <= 5 %; eligible-pair coverage
  >= 95 %; grouped fraction 0.70).

## 4. Pilot routing observations (descriptive only; n = 5 seeds; not confirmatory)

Source: `results/pilot/reports/findings_report.md`.

* D5 (mean %): Direct 43 / 46 / 49; Epidemic 89 / 99 / 100; BSW 69 / 73 / 76; MWS 73 / 74 / 81.
* D15: BSW and MWS 100 / 100 / 99.7 %; Direct about 95-97 %; Epidemic 100 %.
* T: Direct about 0.95; BSW = MWS = 8.00 (exactly 7 relays + 1 delivery per message); Epidemic 49 / 99 / 199
  with buffer drops at all densities.
* Paired MWS - BSW: dD5 block mean +3.1 pp (SD 4.9); per density +4.3 / +0.8 / +4.2 pp. dD15 and dT were
  exactly 0 in every pilot pair.
* Immediate - historical D5 (100 nodes): +4.6 pp (SD 2.7).
* E2-E6 differences were small relative to their pilot variability (see report sections 8-12).

### Structural findings that affect the confirmatory plan
1. **D15 ceiling.** Spray-based algorithms deliver essentially every message within 900 s, partly because
   separated friends physically rejoin within the lifetime (Direct Delivery alone reaches ~95 %).
2. **Equal transfer counts.** With the same budget both BSW and MWS spend all tokens, so T is identical by
   construction. H2 and H3 are therefore expected to be degenerate (zero-variance differences); the
   pre-specified rule yields "Non-inferiority established" for H2 if all dD15 are 0, and "Fail to reject" for H3.
3. **Variability of dD5.** With the pilot SD the minimal detectable H1 effect at 30 seeds (80 % power) is
   about 2.3 pp (alpha 0.05) or 3.0 pp (Holm worst case alpha/5); using the 80 % upper confidence limit of
   the SD: 3.6 pp and 4.7 pp. See `sample_size_assessment.csv`.

These are reported, not corrected: nothing in the model was changed in response to pilot routing results.

## 5. Data-quality checks on the pilot batch
All 11 checks pass: 125/125 planned runs present, no failures, single code version, seeds in range, token
conservation, no repeated destination receptions, identical inputs across algorithms in all 20 scenarios,
complete seeds per configuration, mobility integrity, workload fallback <= 5 %, messages generated in every run.
