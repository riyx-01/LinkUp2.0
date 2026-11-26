# Decisions needing researcher / mentor approval

Record each decision, edit `configs/confirmatory.json` where needed, then freeze with
`python main.py freeze --approver "<name>" --note "<summary of decisions>"`. `freeze` refuses to run while the
meaningful target effects are unset, and any later change to the confirmatory config, `configs/experiments.json`
or the simulation source invalidates the freeze. A forced re-approval archives the previous record in
`configs/confirmatory.approval_history.jsonl`.

## A. Status of the existing confirmatory batch (decide first)

`results/confirmatory/` contains a complete batch (750 runs, 0 failures, code `1.0.0+src.5f0c2c3d5e`) produced
under the approval of 2026-11-26. Those results have already been inspected. The corrections in this revision
changed the source code, so that approval no longer verifies and `run --phase confirmatory` will refuse to mix
code versions. Nothing in that folder was modified. Options:

| Option | Meaning | Integrity note |
|---|---|---|
| A1 Keep it as the confirmatory result | Analyse the existing 750 runs under the revised SAP (zero-variance rule changes only the secondary H2 at 50 nodes) and report all new metrics/sensitivity work as exploratory | The revised analysis rules were written after the results were seen; this must be stated in the thesis |
| A2 Archive it and run a fresh confirmatory batch | Move the folder to `results/archive/`, re-freeze, run with the corrected code | Because the old seeds' results are known, using the same seeds 1001-1030 is not a blind replication; consider a new reserved seed range (requires changing `experiments/matrix.py::SEED_RANGES`, documented as a deviation) |

Recommendation: A1 for the primary hypotheses (honest, already complete, primary decisions unaffected), with all
additions labelled exploratory; A2 only if the mentor requires the revised SAP to be confirmatory.

## B. Items for the (re-)freeze

| # | Decision | Proposed default | Evidence / note |
|---|---|---|---|
| 1 | H2 non-inferiority margin delta | 5 pp | Proposed in the brief. D15 is at ceiling (about 99.9-100 % for both algorithms), so H2 is weakly informative whatever delta is. |
| 2 | Meaningful target effects (D5) | **unset - must be chosen** | e.g. H1: 2 pp, H5: 2 pp. Pilot SD of the H1 unit was 4.9 pp (5 seeds); the existing confirmatory SD was 2.2 pp, giving a minimal detectable effect of about 1-1.5 pp at n = 30. Choose on practical grounds, not from observed results. |
| 3 | Number of seeds | 30 | Keep unless option A2 with a new range is chosen. |
| 4 | H4 model | Welch one-way ANOVA (independent groups) | Density streams are independent; RM-ANOVA (GG), Kruskal-Wallis, Friedman as sensitivity. |
| 5 | Zero-variance rule | inconclusive (no p-value) | Required by the external review. An exact sign/binomial or bootstrap bound is documented in the SAP as a possible alternative; it is inactive unless approved. |
| 6 | Rejoin policy (primary) | after_current_activity | X4 shows this choice matters a lot for D5 (about 73 % vs 92 % with immediate rejoin, pilot). It is algorithm-independent; decide on plausibility only and keep the primary scenario unchanged. |
| 7 | Entrance dwell 30-120 s | keep | Proposed default from the brief. |
| 8 | Optional experiments in the confirmatory batch | X1, X3, X3b, X4 exploratory only | Run with `--include-optional`; never replace the primary scenario. |
| 9 | Published baseline | not implemented | Kawecki & Schoeneich (2016) could not be inspected (publisher login gate). If the PDF is supplied, a faithful-reproduction assessment can be redone; otherwise report as a limitation. |
| 10 | Commit before freezing | yes | Provenance records the git commit; current working tree is "dirty". |

Checklist before `freeze`: all tests pass; option A1/A2 chosen and written down; items 1-10 recorded;
`statistics.meaningful_target_effects_pp` filled; code committed.
