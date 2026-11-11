"""Stage 6b: `dashboard.html`, a single self-contained page per run (no server, no external scripts).

It holds the same student data as the workbook, so it lives next to it in runs/<id>/ and is shared the
same way (never by public link). The page template is templates/dashboard.html; this module only builds
the data it embeds.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .config import REPO_ROOT
from .pipeline import RunResult

TEMPLATE = REPO_ROOT / "templates" / "dashboard.html"
SOURCE_LABEL = {"engage_line_items": "Engage export", "recap_form": "Recap Form", "bill_details": "Bill details",
                "jfc_budgets": "FY budgets", "appeals": "Appeal Form"}


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp | datetime):
        return v.strftime("%Y-%m-%d %H:%M") if (v.hour or v.minute) else v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.isoformat()
    if hasattr(v, "item"):  # numpy scalar
        return _clean(v.item())
    if isinstance(v, list | tuple):
        return ", ".join(str(x) for x in v)
    return v


def _rows(df: pd.DataFrame | None, cols: list[str]) -> list[dict]:
    if df is None or not len(df):
        return []
    have = [c for c in cols if c in df.columns]
    return [{k: _clean(v) for k, v in r.items()} for r in df[have].to_dict("records")]


def build_payload(res: RunResult) -> dict:
    req, strikes, appeals = res.requirements, res.strikes, res.appeals
    money = req["adjusted_c"].map(lambda c: None if pd.isna(c) else round(c / 100, 2)) if len(req) else None
    bills = req.assign(amount=money) if len(req) else req
    standing = res.standing
    st = strikes if len(strikes) else pd.DataFrame(columns=["state", "supported"])
    return {
        "meta": {
            "as_of": res.as_of.strftime("%Y-%m-%d %H:%M"), "fy": f"FY{res.fy}", "draft": res.watermark,
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "inputs": [{"source": SOURCE_LABEL.get(u.source, u.source), "as_of": u.as_of.replace("T", " ")[:16],
                        "file": u.original_name} for u in res.inputs],
            "warnings": res.warnings,
        },
        "counts": {
            "rsos_flagged": int((standing["standing"] != "GOOD").sum()) if len(standing) else 0,
            "strikes_to_confirm": int(((st["state"] == "proposed") | ~st["supported"].astype(bool)).sum()),
            "appeals_open": int((appeals["status"] == "OPEN").sum()) if len(appeals) else 0,
            "review": len(res.review),
            "overdue": int(((req["status"] == "OVERDUE") & (req["class"] == "ENFORCED")).sum()) if len(req) else 0,
        },
        "rsos": _rows(standing, ["rso", "standing", "confirmed_strikes", "proposed_strikes", "overdue", "late",
                                 "due", "compliant", "needs_review", "unverified_no_event_date"]),
        "bills": _rows(bills, ["bill_id", "rso", "title", "status", "event_date", "due_date", "days_overdue",
                               "days_left", "recap_submitted_at", "amount", "class", "class_note",
                               "submitter_name", "submitter_email", "event_date_source", "recap_ids", "notes"]),
        "strikes": _rows(strikes, ["bill_id", "rso", "title", "state", "ordinal", "status", "event_date", "due_date",
                                   "recap_submitted_at", "consequence", "active_until", "decided_by",
                                   "decision_reason", "supported", "note"]),
        "appeals": _rows(appeals, ["appeal_id", "bill_id", "rso", "status", "submitted_at", "appeal_deadline",
                                   "timely", "reason", "explanation", "evidence", "appellant_name",
                                   "appellant_email", "strike_state", "checks", "decided_by", "decision_reason",
                                   "action"]),
        "review": [{k: _clean(v) for k, v in r.items()} for r in res.review],
        "flags": _rows(res.flags, ["rule_id", "severity", "rso", "bill_id", "message"]),
        "quality": _rows(res.quarantine, ["upload", "row", "code", "message"]),
    }


def render(payload: dict) -> str:
    data = json.dumps(payload, default=str, ensure_ascii=False)
    # Embedded in a <script> block: neutralize any "</script>" or "<!--" inside student-entered text.
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    html = TEMPLATE.read_text().replace("/*__JFDC_DATA__*/null", data, 1)
    # Strict CSP: only THIS page's own script (by hash) may run, and nothing may load from or send to the
    # network. Even if student text ever slipped past the escaping, it could not run or exfiltrate data.
    scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.S)
    hashes = " ".join(f"'sha256-{base64.b64encode(hashlib.sha256(s.encode()).digest()).decode()}'" for s in scripts)
    csp = (f"default-src 'none'; script-src {hashes}; style-src 'unsafe-inline'; img-src data:; "
           "connect-src 'none'; form-action 'none'; base-uri 'none'")
    return html.replace("__JFDC_CSP__", csp, 1)


def write_dashboard(res: RunResult, out_dir: Path) -> Path:
    path = out_dir / "dashboard.html"
    path.write_text(render(build_payload(res)))
    return path
