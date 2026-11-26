"""Dashboard / LinkUp Explorer: displayed data are genuine simulator outputs; the pages render."""

import base64
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from dashboard.explorer_export import build_payload, render_html
from dashboard.replay import holders_at, replicas_at, run_for_dashboard
from simulator.config import apply_overrides, load_config
from simulator.engine import RoutingEngine
from simulator.scenario import build_scenario


@pytest.fixture(scope="module")
def replay():
    return run_for_dashboard("MWS", 50, 8, 10, 1)


@pytest.fixture(scope="module")
def payload():
    return build_payload(nodes=50, seed=2, algorithms=("BSW", "MWS"))


def test_replayed_carriers_match_engine_replica_counts(replay):
    msgs = replay.scenario.messages
    expiries = set(msgs.expiry.tolist())
    checked = 0
    for t in range(300, 1800, 37):
        if t in expiries:
            continue
        total = sum(len(holders_at(replay, m, t)) for m in range(msgs.count))
        assert total == replicas_at(replay, t)
        checked += 1
    assert checked > 20


def test_carriers_respect_token_budget(replay):
    msgs = replay.scenario.messages
    for m in range(msgs.count):
        for t in (int(msgs.created[m]), int(msgs.created[m]) + 120, int(msgs.expiry[m]) - 1):
            assert 1 <= len(holders_at(replay, m, t)) <= 8
    assert holders_at(replay, 0, int(msgs.expiry[0])) == set()


def test_explorer_payload_is_the_genuine_run(payload):
    cfg = apply_overrides(load_config("default.json"), {"nodes.node_count": 50})
    scen = build_scenario(cfg, 2)
    meta = payload["meta"]
    assert meta["scenarioHash"] == scen.scenario_hash
    t0, t1, n = meta["t0"], meta["t1"], meta["nodes"]
    pos = np.frombuffer(base64.b64decode(payload["pos"]), dtype="<u2").reshape(t1 - t0, n, 2) / 100.0
    assert np.abs(pos - scen.mobility.positions[t0:t1]).max() <= 0.006          # centimetre precision
    walk = np.unpackbits(np.frombuffer(base64.b64decode(payload["walk"]), dtype=np.uint8))[: (t1 - t0) * n]
    assert np.array_equal(walk.reshape(t1 - t0, n).astype(bool), scen.mobility.walking[t0:t1])
    sep = np.frombuffer(base64.b64decode(payload["sep"]), dtype=np.int8).reshape(t1 - t0, n)
    assert np.array_equal(sep, scen.mobility.sep_state[t0:t1])
    assert payload["groups"] == scen.mobility.groups.group_of.tolist()
    assert [m[3] for m in payload["messages"]] == scen.messages.created.tolist()
    for run in payload["runs"]:
        out = RoutingEngine(apply_overrides(cfg, {"routing.algorithm": run["key"]}), scen, event_log=True).run()
        relays = sum(1 for e in run["events"] if e[1] == 1)
        deliveries = sum(1 for e in run["events"] if e[1] == 2)
        assert relays == out.metrics["intermediate_transfers"]
        assert deliveries == out.metrics["destination_transfers"]
        assert run["metrics"]["d5"] == out.metrics["d5_percent"]
        assert run["timeline"]["replicas"] == out.timeline["replicas"]
        expected = [r["first_delivery_time_s"] if r["first_delivery_time_s"] is not None else -1 for r in out.messages]
        assert run["delivered"] == expected


def test_explorer_html_embeds_data_safely(payload):
    html = render_html(payload)
    assert "/*__LINKUP_DATA__*/" not in html
    data = re.search(r"window\.LINKUP = (.*?);</script>", html, re.S).group(1)
    assert json.loads(data)["meta"]["nodes"] == 50
    assert html.count("</script>") == 2  # data cannot terminate its script tag early
    for banned in ("linear-gradient", "radial-gradient", "text-shadow", "shadowBlur", "drop-shadow"):
        assert banned not in html  # style rule: no gradients, no glow


def _browser() -> str | None:
    for cand in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                 shutil.which("chromium"), shutil.which("google-chrome"), shutil.which("chrome")):
        if cand and Path(cand).exists():
            return cand
    return None


@pytest.mark.skipif(_browser() is None, reason="no headless Chrome/Edge available")
@pytest.mark.parametrize("style", ["minimal", "brutalist", "cyberpunk"])
def test_explorer_runs_in_a_real_browser_without_errors(payload, tmp_path, style):
    page = tmp_path / "explorer.html"
    page.write_text(render_html(payload), encoding="utf-8")
    url = page.resolve().as_uri() + f"#tour=0&mode=compare&style={style}&t=420"
    dom = subprocess.run([_browser(), "--headless=new", "--disable-gpu", "--virtual-time-budget=4000",
                          "--dump-dom", url], capture_output=True, text=True, timeout=120).stdout
    assert 'data-ready="1"' in dom
    errors = re.search(r'<div id="errors"[^>]*>([^<]*)</div>', dom)
    assert errors is not None and errors.group(1).strip() == ""
    assert f'data-style="{style}"' in dom


@pytest.mark.skipif(importlib.util.find_spec("streamlit") is None, reason="streamlit not installed")
def test_streamlit_app_renders_without_exceptions():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("../dashboard/app.py", default_timeout=180)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("LinkUp" in t.value for t in at.title)
