"""Master Excel workbook: LinkUp_Master_Experimental_Data_Analysis.xlsx.

All values are static snapshots computed in Python from the saved per-run
observations (no live Excel formulas); each summary sheet names its source.
Percentages (``*_percent``, "%") are distinguished from percentage-point
differences ("pp", ``mean_diff`` of D-metrics).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .research_summary import LIMITATIONS, PLAIN_GUIDE, key_findings

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
TITLE_FONT = Font(bold=True, size=12, color="1F4E78")
SHEETS = ["01_Read_Me", "02_Configurations", "03_Run_Results", "04_Data_Quality", "05_Mobility_Validation",
          "06_Main_Comparison", "07_Density_Analysis", "08_Copy_Budget", "09_Ablation", "10_Motion_Comparison",
          "11_Robustness", "12_Generalization", "13_Statistical_Tests", "14_Confidence_Intervals", "15_Charts",
          "16_Key_Findings", "17_Limitations", "18_Provenance", "19_Efficiency_Metrics", "20_Rule_Diagnostics",
          "21_Workload_Diagnostics", "22_Sensitivity_X1_X4"]


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].map(lambda v: json.dumps(v, default=str) if isinstance(v, (dict, list)) else v)
    return df.replace([np.inf, -np.inf], np.nan)


class Book:
    def __init__(self, writer: pd.ExcelWriter):
        self.w = writer
        self.blocks: dict[str, list[tuple[int, int, int, str]]] = {}  # sheet -> (header_row, nrows, ncols, title)
        self.cursor: dict[str, int] = {}

    def table(self, sheet: str, df: pd.DataFrame, title: str) -> None:
        row = self.cursor.get(sheet, 0)
        df = _clean(df)
        pd.DataFrame([[title]]).to_excel(self.w, sheet_name=sheet, startrow=row, index=False, header=False)
        df.to_excel(self.w, sheet_name=sheet, startrow=row + 1, index=False)
        self.blocks.setdefault(sheet, []).append((row + 2, len(df), len(df.columns), title))
        self.cursor[sheet] = row + len(df) + 4


def _format(path: Path, book: Book, figures_dir: Path, figures: list[dict]) -> None:
    wb = load_workbook(path)
    for sheet, blocks in book.blocks.items():
        ws = wb[sheet]
        widths: dict[int, int] = {}
        for header_row, nrows, ncols, _ in blocks:
            ws.cell(row=header_row - 1, column=1).font = TITLE_FONT
            for c in range(1, ncols + 1):
                cell = ws.cell(row=header_row, column=c)
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = HEADER_FILL
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                header = str(cell.value or "")
                for r in range(header_row + 1, header_row + nrows + 1):
                    v = ws.cell(row=r, column=c)
                    if isinstance(v.value, float):
                        if "p_" in header or header.endswith("_p") or "pvalue" in header:
                            v.number_format = "0.0000"
                        elif "percent" in header or header.endswith("%"):
                            v.number_format = "0.00"
                        else:
                            v.number_format = "0.000"
                    widths[c] = max(widths.get(c, 8), min(len(str(v.value)) if v.value is not None else 0, 60))
                widths[c] = max(widths.get(c, 8), min(len(header), 40))
        for c, wdt in widths.items():
            ws.column_dimensions[get_column_letter(c)].width = wdt + 2
        first_header = blocks[0][0]
        ws.freeze_panes = ws.cell(row=first_header + 1, column=1)
        hr, nrows, ncols, _ = blocks[0]
        if nrows > 0:
            ws.auto_filter.ref = f"A{hr}:{get_column_letter(ncols)}{hr + nrows}"
    ws = wb["15_Charts"]
    row = 3
    for f in figures:
        png = figures_dir / f["png"]
        if png.exists():
            img = XLImage(str(png))
            scale = 620 / img.width
            img.width, img.height = int(img.width * scale), int(img.height * scale)
            ws.cell(row=row, column=1, value=f"{f['figure']}: {f['title']}").font = TITLE_FONT
            ws.cell(row=row + 1, column=1, value=f["caption"])
            ws.add_image(img, f"A{row + 2}")
            row += int(img.height / 20) + 5
    wb.save(path)


def write_workbook(res: dict, path: Path) -> Path:
    d = res["data"]
    fam = res["confirmatory"]["family"]
    prov_rec = {}
    sample = next(iter(sorted((d.root / "raw" / "runs").glob("*.json"))), None)
    if sample:
        prov_rec = json.loads(sample.read_text(encoding="utf-8")).get("provenance", {})
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        b = Book(writer)
        readme = pd.DataFrame([
            ("Workbook", "LinkUp Research Simulator - master experimental data and analysis"),
            ("Phase", d.phase + ("" if d.phase == "confirmatory" else " (NOT confirmatory - pilot/development data)")),
            ("Seeds", f"{d.seeds[0]}-{d.seeds[-1]} ({len(d.seeds)})"),
            ("Source", f"results/{d.phase}/processed/*.csv (per-run observations)"),
            ("Values", "Static snapshots computed in Python from saved observations; no Excel formulas are used."),
            ("Units", "*_percent and columns marked % are percentages of generated messages; differences of "
                      "D-metrics (mean_diff, ci95_*) are percentage points (pp); T = completed transfers per message."),
            ("Unit of analysis", "One (scenario, seed) run. MWS and BSW are paired by seed. Messages are not replicates."),
            ("Error bars / CIs", "95% CI of the mean across seeds (t) unless labelled SD or bootstrap."),
            ("Decisions", "Allowed wording only: Reject / Fail to reject the null hypothesis; Non-inferiority "
                          "established / not established; Evidence is statistically inconclusive."),
            ("Energy", "Completed transfers are an activity indicator, not battery consumption."),
        ], columns=["item", "description"])
        b.table("01_Read_Me", readme, "Read me")
        b.table("01_Read_Me", pd.DataFrame({"sheet": SHEETS}), "Sheets")
        b.table("01_Read_Me", pd.DataFrame(PLAIN_GUIDE, columns=["term", "plain-language meaning"]),
                "How to read the numbers (plain language)")
        b.table("02_Configurations", d.matrix, "Experiment arms -> configuration ids (reuse shown in 'reused_from')")
        cfg_cols = ["configuration_id", "algorithm", "variant", "node_count", "copy_budget", "communication_radius_m",
                    "fallback_s", "motion_error_rate", "motion_signal", "workload_type", "experiment_id"]
        b.table("02_Configurations", d.ok[[c for c in cfg_cols if c in d.ok]].drop_duplicates("configuration_id"),
                "Unique configurations executed")
        b.table("03_Run_Results", d.runs, "All runs (ok and failed) - run_results.csv")
        b.table("04_Data_Quality", pd.DataFrame(d.quality), "Data-quality checks")
        from .data import failed_runs_table, missing_runs_table
        b.table("04_Data_Quality", failed_runs_table(d), "Failed runs (never silently omitted)")
        b.table("04_Data_Quality", missing_runs_table(d), "Planned runs without results")
        b.table("05_Mobility_Validation", d.validation, "Per-scenario mobility/contact/workload validation "
                "(algorithm independent)")
        for key, title in (("d5_percent", "D5 (%)"), ("d15_percent", "D15 (%)"), ("transfers_per_message", "T"),
                           ("median_latency_s", "Median latency (s)"), ("buffer_drops", "Buffer drops"),
                           ("d2_percent", "D2 (%)")):
            b.table("06_Main_Comparison", res["e1"][key], f"E1 {title}: summary across seeds")
        b.table("06_Main_Comparison", res["summaries"]["E1"], "E1 full summary (source: summary_E1.csv)")
        for hid in ("H1", "H2", "H3"):
            b.table("07_Density_Analysis", res["confirmatory"]["per_seed"][hid].reset_index(),
                    f"{hid}: per-seed MWS-BSW differences by density and block mean (pp or transfers)")
        h4 = res["confirmatory"]["h4"]
        h4_tab = pd.DataFrame([{"density": k, "mean_dD5_pp": v, "sd": h4["density_sd"][k], "n": h4["density_n"][k]}
                               for k, v in h4["density_means"].items()])
        b.table("07_Density_Analysis", h4_tab, f"H4: dD5 by density; primary test {h4['primary_test']}")
        b.table("07_Density_Analysis", pd.DataFrame([{"welch_F": h4["welch"]["F"], "welch_df1": h4["welch"]["df1"],
                                                      "welch_df2": h4["welch"]["df2"], "welch_p": h4["welch"]["p"],
                                                      "eta_sq": h4.get("eta_sq"), "kruskal_p": h4.get("kruskal_p"),
                                                      "rm_anova_F": h4["rm_anova"].get("F"),
                                                      "rm_gg_epsilon": h4["rm_anova"].get("gg_epsilon"),
                                                      "rm_p_gg": h4["rm_anova"].get("p_gg"),
                                                      "friedman_p": h4.get("friedman_p")}]), "H4 test statistics")
        if h4.get("pairwise"):
            b.table("07_Density_Analysis", pd.DataFrame(h4["pairwise"]), "H4 pairwise density contrasts (Holm)")
        b.table("07_Density_Analysis", res["secondary"], "Density-specific H1-H3 (secondary Holm family)")
        ex = res["exploratory"]
        for sheet, exp in (("08_Copy_Budget", "E2"), ("09_Ablation", "E3"), ("10_Motion_Comparison", "E4"),
                           ("11_Robustness", "E5"), ("12_Generalization", "E6")):
            b.table(sheet, res["summaries"][exp], f"{exp} summary across seeds (source: summary_{exp}.csv)")
            b.table(sheet, ex[ex.experiment == exp], f"{exp} paired comparisons (exploratory, unadjusted)")
        dec_cols = ["configuration_id", "variant", "seed"] + [c for c in d.ok.columns
                                                              if c.startswith(("decisions_", "transfers_MWS",
                                                                               "transfers_BSW"))]
        e3_ids = set(d.arms("E3")["configuration_id"])
        b.table("09_Ablation", d.ok[d.ok.configuration_id.isin(e3_ids)][dec_cols],
                "Rule decision counts (opportunity-seconds) and completed transfers by permitting rule")
        b.table("10_Motion_Comparison", res["confirmatory"]["per_seed"]["H5"],
                "H5 per-seed paired D5 (a = immediate, b = historical, diff in pp)")
        wi = res["workload_interaction"]
        b.table("12_Generalization", pd.DataFrame([{k: wi[k] for k in ("n", "mean_diff", "sd", "ci95_low", "ci95_high",
                                                                        "p_raw")}]),
                "Difference-in-differences (random - separated) of dD5 (exploratory)")
        fam_x = fam.copy()
        fam_x["missing_pairs"] = fam_x["missing_pairs"].astype(str)
        b.table("13_Statistical_Tests", fam_x, "Confirmatory family H1-H5 (Holm-adjusted)")
        b.table("13_Statistical_Tests", res["secondary"], "Secondary family: density-specific follow-ups")
        b.table("13_Statistical_Tests", ex, "Exploratory comparisons (unadjusted)")
        if not res["sample_size"].empty:
            b.table("13_Statistical_Tests", res["sample_size"], "Repetition-count assessment from this phase's variability")
        ci = fam[["hypothesis", "metric", "n", "mean_diff", "ci95_low", "ci95_high", "boot_ci_low", "boot_ci_high",
                  "one_sided_bound", "bound_type", "holm_level", "one_sided_bound_holm_level"]]
        b.table("14_Confidence_Intervals", ci, "Confirmatory estimates: t-based and seed-block bootstrap CIs")
        b.table("14_Confidence_Intervals", res["secondary"][["hypothesis", "n", "mean_diff", "ci95_low", "ci95_high",
                                                              "one_sided_bound"]], "Density-specific CIs")
        b.table("15_Charts", pd.DataFrame(res.get("figures", [])), "Figures (images below; data CSVs in figures/data)")
        b.table("16_Key_Findings", key_findings(res), "Key findings with evidential status (auto-generated)")
        b.table("17_Limitations", pd.DataFrame({"limitation": LIMITATIONS}), "Limitations")
        prov = [{"item": k, "value": json.dumps(v) if isinstance(v, dict) else v} for k, v in prov_rec.items()]
        b.table("18_Provenance", pd.DataFrame(prov), "Provenance of the runs (from a run record)")
        flat = pd.json_normalize(d.cfg, sep=".").T.reset_index()
        flat.columns = ["parameter", "value"]
        flat["value"] = flat["value"].astype(str)
        b.table("18_Provenance", flat, f"Phase configuration ({d.phase})")
        versions = d.runs["code_version"].value_counts().reset_index()
        b.table("18_Provenance", versions, "Code versions present in the run table")
        from .diagnostics import EFFICIENCY_METRICS, WORKLOAD_METRICS
        from experiments.aggregate import RULE_RATES
        b.table("19_Efficiency_Metrics", res["efficiency"], "Supporting efficiency metrics, E1 (mean, SD, number of "
                "runs where defined). Activity indicators, not energy.")
        b.table("19_Efficiency_Metrics", pd.DataFrame(EFFICIENCY_METRICS, columns=["column", "definition"]),
                "Definitions and denominators")
        b.table("20_Rule_Diagnostics", res["rules"], "MWS/BSW rule counters and normalised rates (E1, E3, E5)")
        b.table("20_Rule_Diagnostics", pd.DataFrame([(c, n, dd or "(count)", desc) for c, n, dd, desc in RULE_RATES],
                                                    columns=["column", "numerator", "denominator", "meaning"]),
                "Definitions: numerators and explicit denominators")
        b.table("21_Workload_Diagnostics", res["workload_diag"], "Workload subgroups (evaluation only; no message "
                "excluded from the primary analysis)")
        b.table("21_Workload_Diagnostics", pd.DataFrame(WORKLOAD_METRICS, columns=["column", "definition"]),
                "Definitions")
        b.table("22_Sensitivity_X1_X4", res["sensitivity"] if not res["sensitivity"].empty
                else pd.DataFrame({"note": ["Optional experiments not executed in this batch"]}),
                "Exploratory sensitivity: radius (X1), traffic load (X3, X3b), separation duration (X4)")
    figures_dir = d.root / "figures"
    _format(path, b, figures_dir, res.get("figures", []))
    return path
