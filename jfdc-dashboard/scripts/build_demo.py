"""Builds a single, self-contained demo page (no server needed) from your data.

    python scripts/build_demo.py                       # uses config.json sources
    python scripts/build_demo.py --out demo.html --keep-names

Personal details (submitter names, emails, proof links) are removed unless you
pass --keep-names. The output can be opened by double-clicking it or shared.
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jfdc import engine  # noqa: E402
from jfdc.sources import make_source  # noqa: E402


def scrub(d: dict) -> dict:
    for r in d["recaps"]:
        r["name"] = "RSO officer"
        r["email"] = None
        if r.get("proof"):
            r["proof"] = "Proof on file (link hidden in demo)"
    for b in d["bills"]:
        b["submitter"] = None
    for r in d["rsos"]:
        r["contacts"] = []
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "demo.html"))
    ap.add_argument("--keep-names", action="store_true")
    ap.add_argument("--with-logo", action="store_true", help="embed static/logo.svg or logo.png")
    ap.add_argument("--fragment", action="store_true", help="omit <html>/<head>/<body> wrappers")
    a = ap.parse_args()

    cfg = json.loads((ROOT / "config.json").read_text())
    today = date.fromisoformat(os.environ["JFDC_TODAY"]) if os.environ.get("JFDC_TODAY") else date.today()
    srcs = [
        make_source(cfg["recap_source"], ROOT, "RECAP_SOURCE"),
        make_source(cfg["bills_source"], ROOT, "BILLS_SOURCE", optional=True),
        make_source(cfg.get("adjustments_source", {}), ROOT, "ADJUSTMENTS_SOURCE", optional=True),
    ]
    t = [s.load() for s in srcs]
    d = engine.build(t[0], t[1], t[2], cfg, today)
    # Keep the demo light: drop bills that can never matter for recaps unless they're in the queue.
    d["bills"] = [b for b in d["bills"] if b["in_queue"] or b["recap_status"] not in ("before_policy",)]
    d["sources"] = ["Demo snapshot built " + today.isoformat()]
    d["loaded_at"] = today.isoformat()
    d["error"] = None
    if not a.keep_names:
        d = scrub(d)

    css = (ROOT / "static/styles.css").read_text()
    js = (ROOT / "static/app.js").read_text()
    html = (ROOT / "static/index.html").read_text()
    body = html.split("<body>", 1)[1].split("<script", 1)[0]
    data = json.dumps(d, separators=(",", ":")).replace("</", "<\\/")
    logo = next((p for p in (ROOT / "static/logo.png", ROOT / "static/logo.svg") if p.exists()), None)
    if logo and a.with_logo:
        import base64
        mime = "image/svg+xml" if logo.suffix == ".svg" else "image/png"
        uri = f"data:{mime};base64," + base64.b64encode(logo.read_bytes()).decode()
        body = body.replace('src="/static/logo.png"', f'src="{uri}"')
    else:
        body = body.replace('<img class="logo" src="/static/logo.png" alt="SGA logo" onerror="this.nextElementSibling.hidden=false;this.remove()">', "")
        body = body.replace('<span class="wordmark" hidden>SGA</span>', '<span class="wordmark">JFC</span>')
        body = body.replace("Student Government Association · Joint Finance Committee", "Joint Finance Committee")
    fonts = ('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
             '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700;900&display=swap">\n')
    head = ('<title>JFC Recap Dashboard</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n'
            + fonts + f"<style>\n{css}\n</style>\n")
    scripts = f"<script>window.__DEMO_DATA__ = {data};</script>\n<script>\n{js}\n</script>\n"
    if a.fragment:
        out = head + body + scripts
    else:
        out = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
               '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
               + head + "</head>\n<body>" + body + scripts + "</body>\n</html>\n")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(out)
    print(f"Wrote {a.out} ({len(out) // 1024} KB, {len(d['bills'])} bills, {len(d['rsos'])} RSOs)")


if __name__ == "__main__":
    main()
