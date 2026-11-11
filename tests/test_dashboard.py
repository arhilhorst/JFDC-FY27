"""Dashboard, demo workspace and CLI round trips."""

import re
from pathlib import Path

import pandas as pd

from jfdc.cli import main
from jfdc.dashboard import build_payload, render
from jfdc.demo import build_demo


def test_demo_builds_a_full_run_and_dashboard(tmp_path):
    out = build_demo(tmp_path / "demo")
    html = (out / "dashboard.html").read_text()
    data = re.search(r'<script id="jfdc-data" type="application/json">(.*?)</script>', html, re.S).group(1)
    assert data != "/*__JFDC_DATA__*/null" and '"bills"' in data
    csp = re.search(r'Content-Security-Policy" content="([^"]+)"', html).group(1)
    assert "default-src 'none'" in csp and "sha256-" in csp and "unsafe-eval" not in csp
    assert (out / "notices.csv").exists() and next(out.glob("*.xlsx"))


def test_payload_counts_match_the_run(tmp_path):
    out = build_demo(tmp_path / "demo")
    from jfdc.config import load_config
    from jfdc.pipeline import run_pipeline
    from jfdc.workspace import Workspace
    ws = Workspace(tmp_path / "demo" / "data")
    res = run_pipeline(ws, load_config(ws.root), as_of=pd.Timestamp("2026-10-20 09:00").to_pydatetime())
    p = build_payload(res)
    assert len(p["bills"]) == len(res.requirements) and p["counts"]["review"] == len(res.review)
    assert p["counts"]["appeals_open"] == int((res.appeals["status"] == "OPEN").sum())
    assert "</script>" not in render(p).split('application/json">', 1)[1].split("</script>", 1)[0]
    assert out.exists()


def test_import_confirmations_refuses_the_same_sheet_twice(tmp_path, capsys):
    out = build_demo(tmp_path / "demo")
    sheet = pd.read_excel(next(out.glob("*.xlsx")), sheet_name="Strike Confirmation", dtype=str).fillna("")
    a = next(c for c in sheet.columns if c.startswith("Action"))
    b = next(c for c in sheet.columns if c.startswith("Confirmed by"))
    sheet.loc[sheet.index[:1], a], sheet.loc[sheet.index[:1], b] = "Confirm", "jvpf@gatech.edu"
    f = tmp_path / "returned.xlsx"
    with pd.ExcelWriter(f) as w:
        sheet.to_excel(w, sheet_name="Strike Confirmation", index=False)
    data = str(tmp_path / "demo" / "data")
    assert main(["--data-dir", data, "import-confirmations", str(f), "--actor", "lead@gatech.edu"]) == 0
    assert main(["--data-dir", data, "import-confirmations", str(f), "--actor", "lead@gatech.edu"]) == 1
    assert "already imported" in capsys.readouterr().err
    assert Path(data).exists()
