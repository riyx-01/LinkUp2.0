# Statistical analysis plan (DRAFT - requires approval before confirmatory runs)

Implemented in `analysis/hypothesis_tests.py`; parameters in `configs/*.json -> statistics`. Status: proposed.
It becomes binding when the researcher freezes the confirmatory configuration (`main.py freeze`).

## Definitions
* D5 / D15 / D2 = unique messages first delivered within 300 / 900 / 120 s (inclusive) / all generated x 100.
* T = completed payload transfers (intermediate + destination) / generated messages.
* dX = X(MWS) - X(BSW), paired by seed within the same scenario. Units: D-differences in percentage points (pp).

## Unit and pairing
One (scenario, seed) run = one observation. Pairing completeness is checked; incomplete pairs/blocks are
excluded from the affected test and reported (never imputed).

## Confirmatory family (alpha = 0.05, Holm across the five tests)

| H | Estimand | Test | Decision wording |
|---|---|---|---|
| H1 | mean over seeds of (dD5 at 50 + 100 + 200)/3 | one-sided paired t-test, H1: mean > 0 | Reject / Fail to reject the null hypothesis |
| H2 | same with dD15 | one-sided non-inferiority t-test, H1: mean > -delta, delta = 5 pp (proposed) | Non-inferiority established / not established |
| H3 | same with dT | one-sided paired t-test, H1: mean < 0 | Reject / Fail to reject |
| H4 | dD5 differs across densities | primary: Welch one-way ANOVA (independent groups, because density streams are independent); sensitivity: Kruskal-Wallis, RM-ANOVA with Greenhouse-Geisser, Friedman | Reject / Fail to reject |
| H5 | mean D5(immediate) - D5(historical) at 100 nodes | one-sided paired t-test, H1: mean > 0 | Reject / Fail to reject |

* H2: non-inferiority is declared only if the Holm-adjusted p < alpha, equivalently the one-sided lower
  confidence bound at the Holm step-down level exceeds -delta. Both the unadjusted 95 % one-sided bound and
  the bound at the Holm level are reported. Failure to find a difference is never treated as non-inferiority.
* H3: a lower T would not show lower energy use.
* H4: density differences are tested directly; an interaction is never inferred from one density being
  significant and another not. Pairwise density contrasts (Welch t, Holm within the set) are descriptive.
* "Evidence is statistically inconclusive" is used when a test cannot be computed (n < 2, missing data, or
  zero variance of the paired differences - see below).

### Zero-variance (degenerate) case - revised procedure
If all paired differences are identical, the paired t statistic and its p-value are undefined.

* The test is flagged **not computable**; **no p-value is assigned** (p is never set to 0 or 1 by rule).
* Decision: **"Evidence is statistically inconclusive"** - for H2 this applies even when every difference is
  exactly 0, i.e. non-inferiority is never declared merely because all observed differences are zero.
* Reported instead: the observed (common) difference, n, the zero-variance condition, and a data-derived
  structural explanation (`structural_note`: D15 ceiling; both bounded-copy algorithms using exactly L-1
  relays so T is fixed by the shared budget).
* Holm: a non-computable test keeps its place in the family (m = 5, conservative for the other tests) but
  receives no adjusted p-value of its own.
* Exploratory and secondary comparisons follow the same rule.

*History:* an earlier draft assigned p = 0 / p = 1 by rule; it was withdrawn after external review. Re-analysing
the existing confirmatory batch read-only with the revised rule leaves the five primary decisions unchanged
and changes the secondary H2 at 50 nodes from "Non-inferiority established" to "inconclusive".

**Possible alternative procedure (NOT active; requires researcher approval before any confirmatory use):** an
exact distribution-free bound for non-inferiority, e.g. a one-sided sign-test / binomial bound on the
proportion of seeds with dD15 < -delta, or a seed-block bootstrap lower bound compared with -delta. These
answer a different question (proportion or resampled bound, not the mean) and would be reported as a
separate, labelled analysis.

## Supporting (exploratory) metrics
Not hypotheses and not energy measurements; computed from transfer events: timely deliveries per 100
completed transfers; time to first relay; time until ceil(L/2) copies exist; time to complete the spray phase
(every remaining replica holds one token) and % of messages completing it; relays before / after first
delivery and on undelivered messages; copy-budget utilisation (relays / (L-1)); intermediate transfers per
delivered message (all relays / delivered messages, NaN if none delivered). Undefined values are NaN, never 0.
MWS rule counters (walking / fallback relays, friend and stationary exclusions, one-token waits, duplicates
prevented, capacity-blocked) are reported as counts and rates with explicit denominators
(`experiments/aggregate.py::RULE_RATES`). Workload diagnostics (destination in range at creation, first
direct source-destination contact, delivery before direct contact, delivery via relay) use the full contact
trace for evaluation only and never exclude messages from the primary analysis.

## Approval items (must be explicit before the confirmatory freeze)
H2 margin (5 pp proposed), meaningful target effects for H1 and H5
(`statistics.meaningful_target_effects_pp`; shipped as null so `freeze` refuses until set), repetition count
(30), H4 model (`independent_groups_welch`), zero-variance rule (`inconclusive`).

## Secondary family
Density-specific H1-H3 follow-ups (9 tests), Holm within the family, reported separately.

## Exploratory analyses (unadjusted, labelled)
E1 comparisons with Epidemic and Direct; E2 (MWS - BSW at each L); E3 (each variant - BSW); E4 secondary
metrics; E5 (MWS at each error rate - BSW, and - MWS 0 %); E6 (MWS - BSW per workload and the
difference-in-differences). Two-sided paired t-tests with 95 % CIs; never presented as confirmatory.

## Estimates and assumption checks
For each test: n, mean and median paired difference, SD, standardised effect size dz (mean/SD), 95 % t CI,
percentile bootstrap 95 % CI resampling complete seed blocks (5,000 resamples, seed 20240531), raw and Holm
p-values. Assumption checks: completeness of pairs, Shapiro-Wilk on differences, skewness/kurtosis, robust-z
outliers (|z| > 3.5), Wilcoxon signed-rank as a sensitivity analysis (not a test of the mean). Assumption
checks never change the primary test.

## Confidence intervals
95 % t intervals describe plausible values of the mean paired difference; a range excluding 0 favours one
direction, a range crossing 0 is compatible with no difference. They are reported unclipped (they may exceed
a metric's natural range with few seeds); seed-block bootstrap intervals are range-respecting. Confirmatory
decisions use the Holm-adjusted p-values; for H2 the matching one-sided bound at the Holm level is reported.

## Sample size
The repetition assessment is a planning tool and is computed only for pilot/development data; it is not
produced from confirmatory data (post-hoc power must not be used to interpret or extend a study).
Target 30 seeds per configuration. The pilot reports, for candidate target effects of 1, 2, 3 and 5 pp,
the seeds needed for 80 % power (one-sided paired t) using the pilot SD and its 80 % upper confidence limit,
at alpha = 0.05 and the Holm worst case alpha/5, plus the minimal detectable effect at n = 30. Target effects
are researcher choices. A smaller n must be justified before confirmatory testing; seeds are never added or
removed after looking at results.
