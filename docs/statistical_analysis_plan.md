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
* "Evidence is statistically inconclusive" is used when a test cannot be computed (n < 2, missing data).

### Pre-specified degenerate case (zero variance)
If all paired differences are identical, the t statistic is undefined. Rule (fixed before confirmatory data):
if the common value lies on the null side (or equals the null value), p = 1; if it lies strictly on the
alternative side, p = 0. Such results are flagged in every report. The pilot showed this case is likely for
H2 and H3 (see `validation_report.md`).

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

## Sample size
Target 30 seeds per configuration. The pilot reports, for candidate target effects of 1, 2, 3 and 5 pp,
the seeds needed for 80 % power (one-sided paired t) using the pilot SD and its 80 % upper confidence limit,
at alpha = 0.05 and the Holm worst case alpha/5, plus the minimal detectable effect at n = 30. Target effects
are researcher choices. A smaller n must be justified before confirmatory testing; seeds are never added or
removed after looking at results.
