# Validation report (implementation and pilot stage)

Revision 2 (after external methodological review). Code version `1.0.0+src.93e0046b68` (working tree on top
of git commit 743ce3f5); Windows 11, Python 3.12.6, 20 logical CPUs. Numbers below are copied from the
generated outputs (2026-11-27); re-running the commands regenerates them exactly. The previous pilot outputs
(code `src.5f0c2c3d5e`) were moved, not deleted, to `results/archive/pilot_src5f0c2c3d5e/`.

## 1. Automated tests (`pytest -q`)

110 tests passed (about 2 min). Coverage by area:

| File | What is verified |
|---|---|
| test_mobility | nodes stay inside the venue; stationary nodes never move; speed <= 1.3 m/s; walking nodes move; friends never overlap; group sizes 2-6, 70 % participation; destination excludes current zone; separations occur, respect the 300 s minimum and keep >= 1 member with each group; identical seed -> identical trace; rejoin policies; routing never mutates the scenario |
| test_contacts | inclusive radius boundary (10 m exactly, 3-4-5 triangle); exclusion just beyond; agreement with brute force; trace storage and contact-event durations |
| test_messages | generation only in [300, 900); Poisson rate; full lifetime observed and config rejects truncation; primary pairs are separated friends; random workload distinct and shares generation times and mobility; reproducible workload; delivery exactly at expiry counts, no forwarding after expiry, no replication at the expiry second |
| test_buffers | buffer capacity never exceeded; 5 transfers/node/s never exceeded; delivery priority under capacity limits; drop-oldest-created with token loss; atomic rejection costs the sender nothing; source injection eviction |
| test_baselines | 8 -> 4/4, 5 -> 2/3 tokens; 1 token: no relay but delivery; tokens never created (random runs, L = 4/8/16); failed transfers cost no tokens; **store-carry-forward delivery without any end-to-end path** (Direct fails, Epidemic/BSW/MWS deliver via the carrier); no multi-hop within one step; expired messages never forwarded; known messages never re-replicated (also after a drop); identical scenario hash for all algorithms |
| test_mws | destination overrides friend exclusion; walking non-friend eligible; friend ineligible; stationary stranger ineligible at 59 s and eligible at exactly 60 s; friend still ineligible after 60 s; one-token carrier cannot spray; duplicate suppression precedes MWS rules; age measured from original creation; all rules off == BSW (identical metrics and configuration id); each ablation behaves as specified; immediate vs historical differ only in the motion signal; historical window uses only past samples; error flips shared, nested and at the configured rate; algorithms cannot access delivery records |
| test_metrics | spray-efficiency metrics on a hand-computed chain (first relay, half copies, spray completion, utilisation, relays before/after delivery, timely deliveries per 100 transfers); undefined metrics are NaN, never 0; workload diagnostics are correct and evaluation-only; D2/D5/D15 on known timestamps; undelivered messages stay in denominators; transfer counting; unique deliveries not double counted; prevented duplicates are not transfers; identical config + seed -> identical metrics |
| test_statistics | zero-variance differences are flagged non-computable with no p-value and an inconclusive decision (H2 never declared non-inferior from all-zero differences); non-inferiority established with variable differences; Holm decisions consistent with adjusted p; sample-size assessment not produced from confirmatory data; pairing by seed and missing-pair detection; t-test equals SciPy; non-inferiority decisions and bound/p-value agreement; Holm equals statsmodels and a hand calculation; restricted decision wording; zero-variance rule; full H1-H5 family on constructed data; H4 null case; failed/missing run detection; CI and bootstrap reproducibility |
| test_reproducibility | freeze refuses unset meaningful target effects; forced re-approval archives the previous record; optional experiments extend the matrix without changing the 25 primary configurations; scenario independent of algorithm; density-specific independent streams; algorithm-free scheduling keys; scenario save/load round trip; equivalence detection (25 unique configurations, shared Full-MWS configuration); phase seed ranges enforced; confirmatory run refused without approval; approval detects config tampering; resumable batch and missing-run recovery |
| test_dashboard | replayed carriers equal the engine's replica counts; carriers respect the budget; LinkUp Explorer data equal the engine outputs (positions, walking, separation, every hand-over and delivery, counters, metrics); no gradients or glow in the page; the Explorer runs in headless Chrome in all three styles without script errors; Streamlit app renders headlessly |

`python main.py smoke` passes: N = 50, seed 1, all four algorithms reproduce identical metrics from two
independently generated scenarios, and token conservation holds.

## 2. Benchmark (`python main.py benchmark`, development seeds 1-2)

Mean routing wall-clock per run (s), 50 / 100 / 200 nodes: Direct 0.49 / 0.70 / 1.13, Epidemic 0.54 / 1.08 / 2.04,
BSW 0.79 / 1.35 / 2.45, MWS 1.10 / 1.50 / 2.59. Scenario generation per (seed, N): 1.2 / 2.3 / 3.6 s. These are
higher than in revision 1 (per-step spray-completion tracking and contact diagnostics, plus normal machine-load
variation). Estimated serial time for the 25-configuration confirmatory matrix: about 22 min.
**Measured pilot (45 configurations incl. X1-X4, 225 runs): 92 s with 6 workers, 0 failures.** The heaviest
single condition is X3 at a 2 s interval (about 300 messages per run, about 5 s per run).

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

Source: `results/pilot/reports/findings_report.md`. The primary pilot results are **identical** to revision 1
(e.g. block-mean dD5 +3.105 pp, immediate - historical +4.575 pp), confirming the added instrumentation did not
change routing behaviour.

* D5 (mean %): Direct 43 / 46 / 49; Epidemic 89 / 99 / 100; BSW 69 / 73 / 76; MWS 73 / 74 / 81.
* D15: BSW and MWS 99.7-100 % (ceiling). T: BSW = MWS = 8.00 (exactly 7 relays + 1 delivery per message).
* dD15 and dT were exactly 0 in every pilot pair, so H2 and H3 are flagged zero-variance and statistically
  inconclusive under the revised rule.
* Supporting efficiency metrics (100 nodes): MWS reaches its first relay later (18 s vs 3 s) and completes the
  spray phase later (82 s vs 33 s) than BSW; both use the whole budget (utilisation 1.00) and complete the
  spray phase for 100 % of messages; MWS makes more relays after the friend already has the message
  (75 vs 48 per run). Timely deliveries per 100 transfers: 9.2 (MWS) vs 9.1 (BSW).
* Rule counters (Full MWS, 100 nodes): 71 % of relays went to walkers, 29 % via the 60 s fallback.
* Workload diagnostics: 95-97 % of messages have a direct source-destination contact before expiry; 3-5
  messages per run start with the friend already in range (D5 = 100 % for that subgroup under every algorithm);
  about 67-72 % of BSW/MWS deliveries happen before any direct contact.
* Sensitivity (dD5 MWS - BSW, pp, 5 seeds; every 95 % CI includes 0): radius 5/10/15 m +0.8/+0.8/+2.9;
  interval 10/5/2 s +0.8/+0.9/+0.1 (resource pressure appears only at 2 s: buffer drops and capacity blocking);
  per-node-scaled load N=50/100/200 +3.7/+0.8/+3.3; separation rules: immediate rejoin -0.0 (D5 about 92 % for
  both), minimum 600 s -0.1, minimum 900 s +0.5. D15 remains at 99.4-100 % in every condition.

### Read-only re-analysis of the existing confirmatory batch under the revised SAP
No files were written. The five primary decisions are unchanged (H1 fail to reject, Holm p 0.072; H2
non-inferiority established, dD15 -0.02 pp, non-zero variance; H3 fail to reject; H4 fail to reject, p 0.89;
H5 reject, +6.0 pp, Holm p 3e-7). In the secondary family, H2 at 50 nodes (all 30 differences exactly 0) changes
from "Non-inferiority established" to "Evidence is statistically inconclusive".

## 5. Data-quality checks on the pilot batch
All 11 checks pass: 225/225 planned runs present, no failures, single code version, seeds in range, token
conservation, no repeated destination receptions, identical inputs across algorithms in all 20 scenarios,
complete seeds per configuration (65 scenarios), mobility integrity, workload fallback <= 5 %, messages generated in every run.

## 6. Statistical and experimental integrity audit (revision 2)

| Item | Result | Evidence |
|---|---|---|
| Complete, correctly matched seed pairs | PASS | `paired_frame` pairs by seed and reports missing pairs; pilot and confirmatory have 0 missing pairs; tested |
| Identical scenario inputs across compared algorithms | PASS | identical `scenario_hash` and message counts in all 65 pilot / 120 confirmatory scenarios |
| Effective-configuration reuse | PASS | 25 primary configurations unchanged; 20 optional ones added; X1/X3/X3b/X4 primary arms reuse E1 configurations; tested |
| No silent omission of failed runs | PASS | failed runs are recorded, counted and listed; 0 failures |
| Undefined metrics | PASS | NaN (never 0) for not-applicable or unreached metrics; reported with the number of runs where defined |
| Zero-variance tests | CORRECTED | now non-computable / inconclusive with no p-value (was p = 0/1 by rule) |
| H4 design | PASS (approval item) | Welch ANOVA for independent density streams; RM-ANOVA (GG), Kruskal-Wallis, Friedman as sensitivity |
| Holm decisions | PASS | decisions follow adjusted p; non-computable tests keep m = 5 but get no adjusted p; tested |
| Confidence intervals | CLARIFIED | t CIs unclipped (can exceed 0-100 % with few seeds); bootstrap CIs range-respecting; interpretation text added to reports and dashboard |
| Sample-size assessment | CORRECTED | produced for pilot/development only; no post-hoc power from confirmatory data |
| Consistency across reports | PASS | CSV, Excel, Markdown report and dashboard all read the same `hypothesis_tests.csv` values |
| No confirmatory execution without a valid freeze | PASS | the previous approval no longer verifies after the code change; `freeze` additionally requires meaningful target effects |
