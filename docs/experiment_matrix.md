# Experiment matrix

Defined in `configs/experiments.json`; inspect with `python main.py matrix`. Equivalent configurations are
detected by the effective-configuration hash and run once.

| ID | Role | Purpose | Arms | New configs |
|---|---|---|---|---|
| E1 | confirmatory | H1-H4 main comparison | N = 50/100/200 x {Direct, Epidemic, BSW, MWS}; L = 8; r = 10 m; 0 % error; primary workload | 12 |
| E2 | supporting | copy budget | N = 100; BSW and MWS; L = 4, 8, 16 (L = 8 reused from E1) | 4 |
| E3 | supporting | rule ablation | N = 100, L = 8: BSW, R1, R2, R1+R2, R2+R3, Full (BSW, Full reused) | 4 |
| E4 | confirmatory | H5 motion signal | N = 100, L = 8: Full immediate (reused) vs historical 300 s | 1 |
| E5 | supporting | classification errors | N = 100, L = 8: BSW (reused), MWS 0 % (reused), 10 %, 20 % | 2 |
| E6 | supporting | generalisation | N = 100, L = 8: BSW, MWS x {separated friends (reused), random} | 2 |
| **Total** | | | | **25** |

At 30 confirmatory seeds: 750 runs. Priority if resources were limited: E1, E4, then E2, E3, E5, E6.
Measured runtime makes the full matrix feasible (see `results/benchmark/benchmark.md`).

Optional, exploratory extensions (excluded unless `--include-optional`): X1 radius 5/10/15 m (BSW, MWS),
X2 temporally correlated classification errors (10 %, 20 %, mean burst 5 s).

Full MWS at 100 nodes (immediate, 0 % error, L = 8, primary workload) is a single configuration shared by
E1, E2, E3, E4, E5 and E6; BSW at 100 nodes is shared by E1, E2, E3, E5 and E6.
