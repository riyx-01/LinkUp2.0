"""LinkUp Research Simulator - optional Streamlit dashboard.

Run from the project root:  streamlit run dashboard/app.py

Tab 1 runs the real simulator for the chosen settings and shows the plain-language
LinkUp Explorer (the same page `python main.py explorer` writes). Tab 2 shows the saved
experiment results. The dashboard is NOT needed to run experiments; batch execution
lives in main.py and never depends on rendering.
"""

from __future__ import annotations

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

METHOD_NAMES = {"MWS": "Walker-first limited copies (MWS)", "BSW": "Limited copies (BSW)",
                "DirectDelivery": "Hand-delivery only", "Epidemic": "Copy to everyone"}
PLAIN_COLUMNS = {
    "d5_percent": "Delivered within 5 min (%)", "d15_percent": "Delivered within 15 min (%)",
    "transfers_per_message": "Hand-overs per message", "median_latency_s": "Typical delivery time (s)",
}


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


def results_tab() -> None:
    st.markdown("Averages over many simulated festivals, from the saved experiment runs. A single replay can be "
                "lucky or unlucky; these numbers are what conclusions are based on.")
    phase = st.radio("Which results?", ["pilot", "confirmatory", "development"], horizontal=True,
                     format_func=lambda x: {"pilot": "Pilot (5 festivals, trial run)",
                                            "confirmatory": "Final experiment (30 festivals)",
                                            "development": "Development"}[x])
    proc = ROOT / "results" / phase / "processed"
    runs_path = proc / "run_results.csv"
    if not runs_path.exists():
        st.info("No results saved for this stage yet.")
        return
    runs = pd.read_csv(runs_path)
    if phase != "confirmatory":
        st.warning("These are trial results, not the final experiment. They must not be used as evidence.")
    e1 = runs[runs["experiment_id"].astype(str).str.contains("E1") & (runs["run_status"] == "ok")]
    if not e1.empty:
        st.subheader("How each method did (main comparison)")
        table = (e1.groupby(["node_count", "algorithm"])[list(PLAIN_COLUMNS)].mean().round(1).reset_index()
                 .rename(columns={**PLAIN_COLUMNS, "node_count": "People using the app", "algorithm": "Method"}))
        table["Method"] = table["Method"].map(METHOD_NAMES)
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.caption(f"Each row averages {e1['seed'].nunique()} simulated festivals. Hand-overs measure phone "
                   "activity, not battery use.")
    tests = proc / "hypothesis_tests.csv"
    if tests.exists():
        st.subheader("Formal tests")
        df = pd.read_csv(tests)
        cols = ["hypothesis", "title", "n", "mean_diff", "ci95_low", "ci95_high", "p_holm", "decision"]
        st.dataframe(df[[c for c in cols if c in df.columns]], use_container_width=True, hide_index=True)
    figs = sorted((ROOT / "results" / phase / "figures").glob("fig*.png"))
    if figs:
        st.subheader("Charts")
        pick = st.selectbox("Chart", [f.name for f in figs])
        st.image(str(ROOT / "results" / phase / "figures" / pick))
    st.subheader("Downloads")
    for f in [runs_path, proc / "message_results.csv", proc / "hypothesis_tests.csv",
              ROOT / "results" / phase / "reports" / "LinkUp_Master_Experimental_Data_Analysis.xlsx",
              ROOT / "results" / phase / "reports" / "findings_report.md"]:
        if f.exists():
            st.download_button(f"Download {f.name}", f.read_bytes(), file_name=f.name)


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
