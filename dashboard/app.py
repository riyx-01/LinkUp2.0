"""LinkUp Research Simulator - optional Streamlit dashboard.

Run from the project root:  streamlit run dashboard/app.py

Tab 1 runs the real simulator for the chosen settings and shows the plain-language
LinkUp Explorer (the same page `python main.py explorer` writes). Tab 2 shows the saved
experiment results. The dashboard is NOT needed to run experiments; batch execution
lives in main.py and never depends on rendering.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

from dashboard.explorer_export import build_payload, render_html  # noqa: E402

st.set_page_config(page_title="LinkUp Explorer", layout="wide")

@st.cache_data(show_spinner="Running the simulator for these settings (a few seconds)...", max_entries=6)
def explorer_html(nodes: int, seed: int, radius: float, budget: int, workload: str, style: str) -> str:
    payload = build_payload(nodes=nodes, seed=seed, radius=radius, copy_budget=budget, workload=workload,
                            default_style=style)
    return render_html(payload)


def sidebar() -> dict:
    st.sidebar.header("Choose a festival to replay")
    st.sidebar.caption("Every choice runs the real simulator. All four sharing methods use exactly the same crowd "
                       "and the same messages.")
    nodes = st.sidebar.radio("How many people use the app?", [50, 100, 200], index=1, horizontal=True,
                             help="More people means more chances to pass messages on.")
    radius = st.sidebar.radio("How far can phones reach? (metres)", [5, 10, 15], index=1, horizontal=True)
    budget = st.sidebar.radio("Copy limit for the limited-copy methods", [4, 8, 16], index=1, horizontal=True,
                              help="The most copies of one message that may exist.")
    workload = st.sidebar.radio("Who writes to whom?", ["separated_friends", "random"],
                                format_func=lambda w: "Friends who got separated" if w == "separated_friends"
                                else "Random strangers")
    seed = st.sidebar.number_input("Festival number (changes the crowd)", min_value=1, max_value=9, value=1,
                                   help="Development seeds 1-9. The same number always gives the same festival.")
    style = st.sidebar.radio("Starting style", ["minimal", "brutalist", "cyberpunk"],
                             format_func=str.capitalize, horizontal=True,
                             help="You can also switch style inside the explorer at any time.")
    return {"nodes": int(nodes), "seed": int(seed), "radius": float(radius), "budget": int(budget),
            "workload": workload, "style": style}


def explorer_tab(p: dict) -> None:
    st.markdown("Press **Play** in the explorer below. Click **How it works** for a 1-minute guided tour.")
    html = explorer_html(p["nodes"], p["seed"], p["radius"], p["budget"], p["workload"], p["style"])
    components.html(html, height=1750, scrolling=True)
    st.download_button("Download this replay as a single file (opens in any browser, works offline)", html,
                       file_name=f"linkup_explorer_N{p['nodes']}_s{p['seed']}.html", mime="text/html")


# ----------------------------------------------------------------------------- Experiment results tab
# Plain-language summary of the saved experiment runs. Every number shown is computed from the saved CSV files;
# nothing is typed in by hand.

METHOD_ORDER = ["MWS", "BSW", "Epidemic", "DirectDelivery"]
METHOD_NAMES = {"MWS": "Our method (MWS)", "BSW": "Spray-and-Wait (BSW)",
                "Epidemic": "Epidemic (copy to everyone)", "DirectDelivery": "Direct Delivery (sender only)"}
PHASES = {"confirmatory": "Final experiment (30 festivals)", "pilot": "Pilot (5 festivals, trial run)"}
OURS_STYLE = "background-color: rgba(244, 114, 48, 0.16); font-weight: 600"

TEST_QUESTIONS = {
    "H1": "Does our method deliver more messages within 5 minutes than Spray-and-Wait?",
    "H2": "Is our method just as reliable within 15 minutes (at most 5 points worse)?",
    "H3": "Does our method need fewer hand-overs per message than Spray-and-Wait?",
    "H4": "Does the 5-minute gain change with crowd size?",
    "H5": "Does 'walking right now' beat 'walked in the last 5 minutes'?",
}

GLOSSARY = """
| Number on this page | What it means in simple words |
|---|---|
| **Within 2 / 5 / 15 min** (D2, D5, D15) | Out of every 100 messages written, how many reached the friend within 2, 5 or 15 minutes. Messages that never arrived still count, so this cannot be gamed. |
| **Typical delivery time** (median latency) | Half of the delivered messages arrived faster than this, half slower. |
| **Copies per message** (copy budget L = 8) | How many phones ended up holding a copy of one message. This is the phone work and memory cost. Ours and Spray-and-Wait are both capped at 8. |
| **Phone-memory overflows** (buffer drops) | How many times, in one festival, a phone's message store (50 messages) was full and had to throw a copy away. |
| **Festivals** (seeds) | One festival is one complete simulated crowd. Every method plays the exact same festivals: same people, same movements, same messages. |
| **Ours ahead in / faster in** | Because both methods played the same festivals, we can count how many of them ours did better in. |
| **p (Holm)** | How likely a difference this big would be by pure luck if the methods were really equal. Below 0.05 = proven. "Holm" means it is corrected because we ran five tests together. |
| **Supported / Not proven** | Supported: the data prove it. Not proven: the data could not show a clear difference. This does not mean our method is worse. |
"""


def _pct(x) -> str:
    return "-" if pd.isna(x) else f"{x:.1f}%"


def _mmss(seconds) -> str:
    if pd.isna(seconds):
        return "-"
    m, s = divmod(int(round(float(seconds))), 60)
    return f"{m} min {s:02d} s" if m else f"{s} s"


def _p(x) -> str:
    if pd.isna(x):
        return "-"
    return "below 0.001" if x < 0.001 else f"{x:.3f}"


def _mean(g: pd.DataFrame, col: str) -> float:
    return g[col].mean() if col in g.columns else float("nan")


def _copies_per_message(g: pd.DataFrame) -> float:
    if {"created_replicas", "generated_messages"} <= set(g.columns):
        return (g["created_replicas"] / g["generated_messages"].where(g["generated_messages"] > 0)).mean()
    return _mean(g, "transfers_per_message")


def _highlight_ours(row: pd.Series) -> list[str]:
    return [OURS_STYLE if str(row.iloc[0]).startswith("Our") else ""] * len(row)


def _glance(e1: pd.DataFrame) -> None:
    sizes = sorted(e1["node_count"].unique())
    budget = e1.loc[e1["algorithm"] == "BSW", "copy_budget"].dropna()
    radius = e1["communication_radius_m"].dropna()
    c = st.columns(4)
    c[0].metric("Methods compared", e1["algorithm"].nunique())
    c[1].metric("Festivals per setting", e1["seed"].nunique())
    c[2].metric("Crowd sizes (people)", " / ".join(str(int(s)) for s in sizes))
    c[3].metric("Copy limit per message", f"{int(budget.mode()[0])} copies" if not budget.empty else "-")
    st.caption(f"Every method played exactly the same festivals: same crowd, same friends getting lost, same "
               f"messages. Only the rule for choosing who carries a copy changed. Phones reach "
               f"{int(radius.mode()[0]) if not radius.empty else 10} m; a message lives 15 minutes.")


def _method_table(e1: pd.DataFrame, n: int) -> pd.DataFrame:
    d = e1[e1["node_count"] == n]
    rows = []
    for alg in METHOD_ORDER:
        g = d[d["algorithm"] == alg]
        if g.empty:
            continue
        rows.append({
            "Method": METHOD_NAMES[alg],
            "Within 2 min": _pct(_mean(g, "d2_percent")),
            "Within 5 min": _pct(_mean(g, "d5_percent")),
            "Within 15 min": _pct(_mean(g, "d15_percent")),
            "Typical delivery time": _mmss(_mean(g, "median_latency_s")),
            "Copies per message": f"{_copies_per_message(g):.0f}",
            "Phone-memory overflows": f"{_mean(g, 'buffer_drops'):,.0f}",
        })
    return pd.DataFrame(rows)


def _takeaway(e1: pd.DataFrame, n: int) -> str:
    d = e1[e1["node_count"] == n]
    g = {a: d[d["algorithm"] == a] for a in METHOD_ORDER}
    if any(g[a].empty for a in METHOD_ORDER):
        return ""
    return (f"**At {n} people:** our method delivered **{_pct(_mean(g['MWS'], 'd5_percent'))}** within 5 minutes "
            f"vs {_pct(_mean(g['BSW'], 'd5_percent'))} for Spray-and-Wait, with the **same "
            f"{_copies_per_message(g['MWS']):.0f} copies** per message. Epidemic reached "
            f"{_pct(_mean(g['Epidemic'], 'd5_percent'))}, but only by making "
            f"{_copies_per_message(g['Epidemic']):.0f} copies of every message and overflowing phone memory "
            f"{_mean(g['Epidemic'], 'buffer_drops'):,.0f} times per festival. Direct Delivery costs almost "
            f"nothing but delivered only {_pct(_mean(g['DirectDelivery'], 'd5_percent'))}.")


def _head_to_head(e1: pd.DataFrame) -> pd.DataFrame:
    cols = ["node_count", "seed", "d2_percent", "median_latency_s"]
    if not set(cols) <= set(e1.columns):
        return pd.DataFrame()
    pairs = pd.merge(e1.loc[e1["algorithm"] == "MWS", cols], e1.loc[e1["algorithm"] == "BSW", cols],
                     on=["node_count", "seed"], suffixes=("_ours", "_bsw"))
    rows = []
    for n, g in pairs.groupby("node_count"):
        k = len(g)
        rows.append({
            "Crowd size": f"{int(n)} people",
            "Within 2 min (Spray-and-Wait → ours)": f"{_pct(g['d2_percent_bsw'].mean())} → "
                                                     f"{_pct(g['d2_percent_ours'].mean())}",
            "Gain": f"{g['d2_percent_ours'].mean() - g['d2_percent_bsw'].mean():+.1f} points",
            "Ours ahead in": f"{int((g['d2_percent_ours'] > g['d2_percent_bsw']).sum())} of {k} festivals",
            "Typical delivery time (Spray-and-Wait → ours)": f"{_mmss(g['median_latency_s_bsw'].mean())} → "
                                                              f"{_mmss(g['median_latency_s_ours'].mean())}",
            "Ours faster in": f"{int((g['median_latency_s_ours'] < g['median_latency_s_bsw']).sum())} of {k} "
                              "festivals",
        })
    return pd.DataFrame(rows)


def _test_result(row: pd.Series, h4: dict | None) -> str:
    h, note = row.get("hypothesis"), str(row.get("structural_note") or "")
    diff = row.get("mean_diff")
    if h == "H4":
        means = (h4 or {}).get("density_means")
        if means:
            sizes = sorted(means, key=lambda s: int(s))
            return (" / ".join(f"{means[s]:+.2f}" for s in sizes) + " points at " +
                    " / ".join(sizes) + " people")
        return "See the findings report"
    if pd.isna(diff):
        return "Could not be computed"
    if h == "H3":
        text = f"{diff:+.3f} hand-overs per message"
        return text + " (both use all 8 copies)" if "Budget" in note else text
    if h == "H2":
        text = f"{diff:+.2f} points (limit was -5)"
        return text + "; both reach about 100%" if "Ceiling" in note else text
    return f"{diff:+.2f} points on average"


def _verdict(row: pd.Series) -> str:
    cat = str(row.get("result_category") or "").lower()
    if cat == "statistically supported":
        return "✅ Supported"
    if cat == "not statistically supported":
        return "➖ Not proven"
    return "⚠️ Inconclusive"


def _tests_table(tests: pd.DataFrame, h4: dict | None) -> pd.DataFrame:
    rows = []
    for _, r in tests.iterrows():
        h = r.get("hypothesis")
        rows.append({"Test": h, "The question we asked": TEST_QUESTIONS.get(h, r.get("title", "")),
                     "What we found": _test_result(r, h4), "p (Holm)": _p(r.get("p_holm")),
                     "Verdict": _verdict(r)})
    return pd.DataFrame(rows)


def _color_verdict(v: str) -> str:
    return "color: #00875A; font-weight: 600" if v.startswith("✅") else ""


def results_tab() -> None:
    st.markdown("These are the saved experiment results: averages over many simulated festivals. A single replay "
                "can be lucky or unlucky; these numbers are what our conclusions are based on.")
    phase = st.radio("Which results?", list(PHASES), horizontal=True, format_func=PHASES.get)
    proc = ROOT / "results" / phase / "processed"
    runs_path = proc / "run_results.csv"
    if not runs_path.exists():
        st.info("No results saved for this stage yet.")
        return
    runs = pd.read_csv(runs_path)
    e1 = runs[runs["experiment_id"].astype(str).str.contains("E1") & (runs["run_status"] == "ok")]

    if not e1.empty:
        st.subheader("The experiment at a glance")
        _glance(e1)

        st.subheader("1 · How each method did")
        st.caption("The main comparison of all four methods. Pick a crowd size. Our method is highlighted.")
        sizes = sorted(int(s) for s in e1["node_count"].unique())
        n = st.radio("Crowd size", sizes, index=len(sizes) // 2, horizontal=True,
                     format_func=lambda s: f"{s} people")
        table = _method_table(e1, n)
        st.dataframe(table.style.apply(_highlight_ours, axis=1), hide_index=True, width="stretch",
                     column_config={
                         "Within 2 min": st.column_config.TextColumn(
                             help="Messages that reached the friend within 2 minutes (D2). Higher is better."),
                         "Within 5 min": st.column_config.TextColumn(
                             "Within 5 min ⭐", help="Our main score (D5): reached the friend within 5 minutes, "
                                                    "while they are still nearby. Higher is better."),
                         "Within 15 min": st.column_config.TextColumn(
                             help="Reliability (D15): reached the friend before the message expired."),
                         "Typical delivery time": st.column_config.TextColumn(
                             help="Median: half of delivered messages arrived faster than this. Lower is better."),
                         "Copies per message": st.column_config.TextColumn(
                             help="How many phones held a copy of one message: the phone work. Lower is lighter."),
                         "Phone-memory overflows": st.column_config.TextColumn(
                             help="Times per festival a full phone had to throw a copy away. 0 is best."),
                     })
        msg = _takeaway(e1, n)
        if msg:
            st.info(msg)

        h2h = _head_to_head(e1)
        if not h2h.empty:
            st.subheader("2 · Our method vs Spray-and-Wait: where it shines")
            st.caption("Both methods use the same 8 copies and played the same festivals, so we can compare them "
                       "festival by festival. This is an extra comparison on the same runs, not one of the five "
                       "planned tests below.")
            st.dataframe(h2h, hide_index=True, width="stretch")

    tests_path = proc / "hypothesis_tests.csv"
    if tests_path.exists():
        st.subheader("3 · The five planned tests (H1 to H5)")
        st.caption("Decided before the final experiment was run. Supported = proven with p (Holm) below 0.05. "
                   "Not proven = no clear difference, which is not the same as being worse.")
        h4_path = proc / "h4_details.json"
        h4 = json.loads(h4_path.read_text(encoding="utf-8")) if h4_path.exists() else None
        tests = _tests_table(pd.read_csv(tests_path), h4)
        st.table(tests.style.hide(axis="index").map(_color_verdict, subset=["Verdict"]))

    with st.expander("What every number on this page means"):
        st.markdown(GLOSSARY)

    with st.expander("Download the raw data files"):
        for f in [runs_path, proc / "message_results.csv", proc / "hypothesis_tests.csv",
                  ROOT / "results" / phase / "reports" / "LinkUp_Master_Experimental_Data_Analysis.xlsx",
                  ROOT / "results" / phase / "reports" / "findings_report.md"]:
            if f.exists():
                st.download_button(f"Download {f.name}", f.read_bytes(), file_name=f.name, key=f"dl_{f.name}")


def main() -> None:
    st.title("LinkUp Explorer")
    st.caption("How phones could pass messages at a crowded festival with no mobile signal. Synthetic venue and "
               "idealised radio; this is a research simulation, not a real festival.")
    params = sidebar()
    tab1, tab2 = st.tabs(["Watch a festival", "Experiment results"])
    with tab1:
        explorer_tab(params)
    with tab2:
        results_tab()


main()
