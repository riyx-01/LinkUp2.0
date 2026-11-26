# LinkUp Research Simulator

Research-grade, reproducible simulator for the MCA project **"A Mobile Ad Hoc Network Based Communication
System for High Density Network Environments" (LinkUp)**. It evaluates **Motion-aware Walker-preferential
Spray-and-Wait (MWS)** against Direct Delivery, Epidemic Routing and Binary Spray-and-Wait (BSW) for
infrastructure-independent smartphone messaging in a crowded festival venue.

The simulator is the primary research platform: a headless, configuration-driven engine with a resumable
batch runner, a pre-specified statistical analysis, publication figures, an Excel workbook and an automated
findings report. An optional Streamlit dashboard replays genuine simulator states. It is **not** an Android app.

> Integrity rule: parameters, mobility, seeds and statistics are never adjusted to make MWS win. Negative or
> inconclusive findings are valid outcomes. See `docs/research_methodology.md`.

## 1. Installation (Windows 11, PowerShell, VS Code)

Requires Python 3.11+ (tested with 3.12.6). From the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt              # core (simulation, analysis, tests)
pip install -r requirements-dashboard.txt    # optional Streamlit dashboard
pytest -q
```

Troubleshooting:

* **"running scripts is disabled on this system"** when activating: run
  `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` once, or call the interpreter directly:
  `.\.venv\Scripts\python.exe main.py ...`.
* **`python` opens the Microsoft Store**: install Python from python.org and tick "Add to PATH", or use `py -3.12`.
* **Wheel build errors** (numpy/scipy): upgrade pip first; all pinned versions ship Windows wheels.
  `requirements-lock.txt` reproduces the exact tested environment.
* **OneDrive folders**: results and scenario caches can be large and are synced by OneDrive. Pause syncing
  during big batches or move the project outside OneDrive.
* VS Code: select the interpreter `.venv\Scripts\python.exe` (Ctrl+Shift+P → "Python: Select Interpreter").

## 2. Commands

| Command | Purpose |
|---|---|
| `python main.py matrix` | Show the 25-configuration experiment matrix and configuration reuse |
| `python main.py smoke` | Tiny deterministic end-to-end test (N=50, seed 1, all four algorithms) |
| `python main.py simulate --algorithm MWS --nodes 100 --seed 1 --event-log` | One development run with an event log |
| `python main.py validate` | Mobility/contact/workload validation on pilot seeds (no routing) |
| `python main.py benchmark` | Measured runtime of 4 algorithms x 50/100/200 nodes + batch estimate |
| `python main.py pilot --workers 4` | E1-E6 on pilot seeds 101-105, then pilot analysis and exports |
| `python main.py freeze --approver "<name>"` | **Researcher only**: approve and freeze the confirmatory configuration |
| `python main.py run --all --workers 4` | Confirmatory batch E1-E6, seeds 1001-1030 (refuses without a valid freeze) |
| `python main.py run --experiment E1 E4 --resume` | Run/extend selected experiments; `--resume` continues an existing batch |
| `python main.py analyze --phase confirmatory` | Statistics + figures |
| `python main.py export --phase confirmatory` | Statistics + figures + Excel workbook + Markdown report + LaTeX tables |
| `python main.py explorer --nodes 100 --seed 1` | Write the plain-language **LinkUp Explorer** (one HTML file, opens offline in any browser) |
| `streamlit run dashboard/app.py` | Optional dashboard: choose settings, watch the Explorer, browse experiment results |

`--workers N` sets the number of processes (`1` = serial debug mode). `--include-optional` adds the optional
radius (X1) and correlated-error (X2) extensions. Seeds are phase-locked: development 1-9, pilot 101-105,
confirmatory 1001-1030; other seeds are refused.

## 3. Research workflow

1. `pytest -q` and `python main.py smoke`.
2. `python main.py validate` and `python main.py benchmark`.
3. `python main.py pilot --workers 4` → review `results/pilot/reports/findings_report.md`,
   `results/pilot/validation/mobility_validation.md` and `docs/decisions_for_approval.md`.
4. Researcher/mentor approves the final configuration (H2 margin, repetitions, H4 model, model choices) by
   editing `configs/confirmatory.json` if needed and then running `python main.py freeze --approver "<name>"`.
5. `python main.py run --all --workers 4` (resumable; re-run with `--resume` after an interruption).
6. `python main.py export --phase confirmatory`.

## 4. Outputs (per phase, `results/<phase>/`)

```
raw/runs/<run_id>.json        per-run metrics + full provenance (config, seed, scenario hash, code version)
raw/messages/<run_id>.csv     per-message outcomes
raw/events/<run_id>.csv       detailed event log (representative: first seed of each configuration)
raw/scenarios/<id>.json       per-scenario mobility/contact/workload validation
scenarios/<id>.npz            saved shared scenario (groups, mobility, contacts, workload, motion errors)
processed/run_results.csv     one row per run (ok and failed)          processed/message_results.csv
processed/mobility_validation.csv, experiment_matrix.csv, run_plan.csv, summary_E*.csv,
processed/hypothesis_tests.csv, secondary_tests.csv, exploratory_tests.csv, sample_size_assessment.csv
figures/fig01..fig15 (.png 300 dpi + .pdf) and figures/data/*.csv (plotted data)
reports/LinkUp_Master_Experimental_Data_Analysis.xlsx, findings_report.md, tables.tex
logs/runner.log, logs/failures.jsonl
```

## 5. Project structure

```
main.py                CLI
configs/               default.json, pilot.json, confirmatory.json, experiments.json
simulator/             config, rng, venue, node, groups, mobility, contacts, motion, workload, message,
                       scenario, buffers, scheduler, engine, metrics, validation, handcrafted
algorithms/            base, direct_delivery, epidemic, binary_spray_wait, mws, variants
experiments/           matrix, runner, aggregate, approval, provenance, benchmark, validate_mobility
analysis/              data, descriptive, confidence_intervals, hypothesis_tests, visualizations,
                       export_excel, research_summary, tables, pipeline
dashboard/             app.py (Streamlit), explorer_export.py + explorer/template.html (LinkUp Explorer),
                       replay.py (pure helpers)
tests/                 pytest suite (mobility, contacts, messages, buffers, baselines, mws, metrics,
                       statistics, reproducibility, dashboard)
docs/                  methodology, algorithm spec, assumptions, configuration reference, experiment matrix,
                       statistical analysis plan, data dictionary, validation report, limitations,
                       decisions for approval
```

The specification's per-experiment modules (`experiments/comparison.py`, ...) were consolidated: experiments are
data (`configs/experiments.json`) expanded by `experiments/matrix.py`, and per-experiment analyses live in
`analysis/`. This avoids duplicating experiment definitions in code.

## 6. Key design guarantees

* Mobility, contacts, workload and observed-motion traces are generated once per scenario from independent
  RNG streams and shared by every algorithm (verified by `scenario_hash` in every run record).
* Identical resource rules for all algorithms: 10 m unit-disc contacts, 5 transfers/node/s, 50-message
  buffers (drop oldest-created), 900 s lifetime, deliveries scheduled before replications, no multi-hop
  within a step, duplicate suppression, no global acknowledgements.
* Algorithms see only the carrier's tokens, message age/destination, stable friend groups and the advertised
  motion state at the current second - never delivery records or the future.
* Equivalent configurations are detected by an effective-configuration hash and executed once.
* Confirmatory runs require a freeze record whose config, experiment-matrix and source hashes still match.

## 7. User interface (LinkUp Explorer)

A replay for non-technical audiences: a festival map with walking and standing people, friend groups,
the sender (FROM) and the separated friend (TO), phones carrying copies, animated hand-overs, a plain-language
story of every step, an always-visible legend, a glossary, a guided tour, and side-by-side comparison of two
methods on the same crowd. Three switchable styles (Minimal, Brutalist, Cyberpunk; no glow, no gradients).
Everything shown comes from the simulator's own scenario and event log. Details, screenshots and the style
recommendation: `docs/user_interface.md` and `docs/ui_styles/`.

## 8. Documentation

Start with `docs/research_methodology.md`, then `docs/algorithm_specification.md`,
`docs/simulation_assumptions.md` and `docs/statistical_analysis_plan.md`.
