# Decisions needing researcher / mentor approval before confirmatory runs

The confirmatory configuration (`configs/confirmatory.json`) is a **proposal**. Record each decision, edit the
config if needed, then freeze with `python main.py freeze --approver "<name>" --note "<summary>"`. Any later
change to the config, `configs/experiments.json` or the simulation source invalidates the freeze.

| # | Decision | Proposed default | Evidence / note |
|---|---|---|---|
| 1 | H2 non-inferiority margin delta | 5 pp | Proposed in the brief. Pilot dD15 was exactly 0 in every pair, so H2 will likely be decided by the zero-variance rule regardless of delta. |
| 2 | Number of confirmatory seeds | 30 (1001-1030) | MDE for H1 at n = 30 is about 2.3-4.7 pp depending on alpha level and SD assumption (`sample_size_assessment.csv`). Decide which effect is meaningful before running; do not change n afterwards. |
| 3 | H4 model | Welch one-way ANOVA (independent groups) | Density streams are independent, so blocks across densities are not correlated; RM-ANOVA (GG), Kruskal-Wallis and Friedman are reported as sensitivity. Alternative: `repeated_measures_gg`. |
| 4 | Zero-variance (degenerate) test rule | p = 1 on the null side, p = 0 strictly on the alternative side, flagged | Needed because pilot dD15 and dT had zero variance. |
| 5 | Rejoin policy for separated members | `after_current_activity` (mean separation ~610-650 s) | Alternative `immediate_after_minimum` (~300 s + walk back). Algorithm independent; decide on plausibility only, never on routing results. |
| 6 | Entrance dwell time | 30-120 s | Proposed default from the brief; flagged as such. |
| 7 | Buffer drop policy | drop oldest-created, incoming may be rejected | Identical for all algorithms; affects Epidemic mainly (buffer drops at every density). |
| 8 | Carrier keeps replica after delivering | yes (no acknowledgements) | Spec 13.7; configurable. |
| 9 | Acceptance of structural limits of H2/H3 | keep H2/H3 as specified and report the structural explanation | Pilot: D15 near ceiling and T identical by construction (equal budgets fully spent). Changing hypotheses or metrics after the pilot must be justified independently of MWS performance and documented before confirmatory data. |
| 10 | Optional extensions (X1 radius, X2 correlated errors) | not run in the confirmatory batch | Can be run as exploratory with `--include-optional`. |
| 11 | Scope | full E1-E6 (750 runs) | Measured runtime ~12 min serial, so no scope reduction is proposed. |
| 12 | Version control | commit the project before freezing | A git repository was initialised but nothing was committed. The run provenance always includes a source hash; a commit adds a git revision to `code_version`. |

Checklist before `freeze`: all tests pass; pilot report reviewed; mobility validation reviewed; decisions 1-12
recorded; `configs/confirmatory.json` final; code committed.
