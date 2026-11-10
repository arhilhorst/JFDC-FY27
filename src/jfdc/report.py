"""Stage 6: the workbook for the JVPF, plus run metadata for reproducibility."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .pipeline import RunResult

FILL = {
    "OVERDUE": "F8CBAD", "LATE": "FCE4D6", "NOT_TRACKED": "FCE4D6", "INCOMPLETE": "FFF2CC",
    "NEEDS_REVIEW": "FFF2CC", "DUE": "DDEBF7", "COMPLIANT": "E2EFDA", "NO_EVENT_DATE": "EDEDED",
    "OPEN": "FFF2CC", "GRANTED": "E2EFDA", "DENIED": "EDEDED",
}


def _money(c):
    return None if c is None or pd.isna(c) else round(c / 100, 2)


def _previous_requirements(runs_dir: Path, current: str) -> pd.DataFrame | None:
    prev = sorted(p for p in runs_dir.glob("*/requirements.csv") if p.parent.name < current)
    return pd.read_csv(prev[-1], dtype=str) if prev else None


def build_sheets(res: RunResult, prev: pd.DataFrame | None) -> dict[str, pd.DataFrame]:
    req, st, strikes = res.requirements, res.standing, res.strikes
    enf = req[req["class"] == "ENFORCED"] if len(req) else req

    new_rows = []
    if prev is not None and len(req):
        before = dict(zip(prev["bill_id"], prev["status"], strict=True))
        for r in req.to_dict("records"):
            old = before.get(r["bill_id"])
            if old != r["status"] and r["status"] in {"OVERDUE", "LATE", "COMPLIANT", "NEEDS_REVIEW"}:
                new_rows.append({"bill_id": r["bill_id"], "rso": r["rso"], "was": old or "(new)", "now": r["status"]})

    summary_lines = [
        ("Report as of", res.as_of.strftime("%Y-%m-%d %H:%M")),
        ("Fiscal year", f"FY{res.fy}"),
        ("Status", res.watermark or "OK"),
    ]
    for u in res.inputs:
        summary_lines.append((f"Input: {u.source}", f"{u.upload_id} | as of {u.as_of} | newest record {u.newest_record} | {u.original_name}"))
    summary_lines += [
        ("RSOs not in good standing", int((st["standing"] != "GOOD").sum()) if len(st) else 0),
        ("Bills OVERDUE (enforced)", int((enf["status"] == "OVERDUE").sum()) if len(enf) else 0),
        ("Bills LATE (enforced)", int((enf["status"] == "LATE").sum()) if len(enf) else 0),
        ("Strikes awaiting confirmation", int((strikes["state"] == "proposed").sum()) if len(strikes) else 0),
        ("Review items", len(res.review)),
        ("Appeals open", int((res.appeals["status"] == "OPEN").sum()) if len(res.appeals) else 0),
    ]
    summary_lines += [("Warning", w) for w in res.warnings]
    summary = pd.DataFrame(summary_lines, columns=["Item", "Value"])

    noncompliant = st[(st["standing"] != "GOOD") | (st["overdue"] > 0) | (st["late"] > 0) | (st["proposed_strikes"] > 0)].copy() if len(st) else st
    if len(noncompliant):
        noncompliant["dollars_at_issue"] = noncompliant.pop("dollars_at_issue_c").map(_money)
        noncompliant = noncompliant.sort_values(["confirmed_strikes", "overdue", "max_days_overdue"], ascending=False)

    def bill_view(df):
        if not len(df):
            return df
        v = df[["rso", "bill_id", "title", "event_date", "due_date", "status", "days_overdue", "days_left",
                "adjusted_c", "recap_submitted_at", "class", "class_note", "submitter_name", "submitter_email",
                "event_date_source", "rule_id", "notes"]].copy()
        v["approved_$"] = v.pop("adjusted_c").map(_money)
        return v

    overdue = bill_view(enf[enf["status"].isin(["OVERDUE", "LATE", "NOT_TRACKED", "INCOMPLETE"])].sort_values("days_overdue", ascending=False)) if len(enf) else enf
    due = bill_view(req[req["status"] == "DUE"].sort_values("days_left")) if len(req) else req
    # "Compliant" = good standing and nothing outstanding; bills we can't check yet are shown, not hidden.
    compliant = st[(st["standing"] == "GOOD") & (st["overdue"] == 0) & (st["late"] == 0) & (st["needs_review"] == 0)
                   & (st["proposed_strikes"] == 0)][["rso", "compliant", "due", "unverified_no_event_date"]] if len(st) else st
    completeness = bill_view(req[(req["class"] == "COMPLETENESS") & req["status"].isin(["OVERDUE", "LATE", "NEEDS_REVIEW"])]) if len(req) else req

    conf = strikes[(strikes["state"] == "proposed") | ~strikes["supported"].astype(bool)].copy() if len(strikes) else strikes
    if len(conf):
        conf = conf[["bill_id", "rso", "title", "status", "event_date", "due_date", "days_overdue",
                     "recap_submitted_at", "state", "note"]].copy()
        conf.insert(0, "Action (Confirm / Waive / Remove)", "")
        conf["Reason"] = ""
        conf["Confirmed by (GT email)"] = ""

    strike_tracker = strikes[strikes["state"].isin(["confirmed", "waived", "removed"])][
        ["rso", "fy", "ordinal", "bill_id", "title", "violation_date", "state", "consequence", "active_until",
         "active", "decided_by", "decision_reason"]] if len(strikes) else strikes

    review = pd.DataFrame(res.review, columns=["kind", "detail", "action"])
    dq = res.quarantine.copy()
    nodate = req[req["status"] == "NO_EVENT_DATE"][["rso", "bill_id", "title", "class"]] if len(req) else req

    return {
        "Summary": summary,
        "Noncompliant RSOs": noncompliant,
        "Overdue & Late": overdue,
        "Strike Confirmation": conf,
        "Strike Tracker": strike_tracker,
        "Appeals": res.appeals,
        "Due Soon": due,
        "Compliant": compliant,
        "Completeness": completeness,
        "Needs Review": review,
        "Flags": res.flags,
        "Changes Since Last": pd.DataFrame(new_rows, columns=["bill_id", "rso", "was", "now"]),
        "No Event Date": nodate,
        "Data Quality": dq,
    }


def write_workbook(sheets: dict[str, pd.DataFrame], path: Path) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, df in sheets.items():
            (df if len(df.columns) else pd.DataFrame({"(none)": []})).to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            for cell in ws[1]:
                cell.font = Font(bold=True)
                cell.fill = PatternFill("solid", fgColor="D9D9D9")
                cell.alignment = Alignment(wrap_text=True, vertical="top")
            ws.freeze_panes = "A2"
            for i, col in enumerate(df.columns, start=1):
                width = max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) if len(df) else len(str(col))
                ws.column_dimensions[get_column_letter(i)].width = min(max(10, width + 2), 60)
            if "status" in df.columns:
                ci = list(df.columns).index("status") + 1
                for row in ws.iter_rows(min_row=2):
                    color = FILL.get(str(row[ci - 1].value))
                    if color:
                        for c in row:
                            c.fill = PatternFill("solid", fgColor=color)


def write_run(res: RunResult, runs_dir: Path) -> Path:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = runs_dir / run_id
    out.mkdir(parents=True, exist_ok=True)
    sheets = build_sheets(res, _previous_requirements(runs_dir, run_id))
    write_workbook(sheets, out / f"JFDC_Compliance_Report_{res.as_of:%Y-%m-%d}{'_DRAFT' if res.watermark else ''}.xlsx")
    res.requirements.to_csv(out / "requirements.csv", index=False)
    res.strikes.to_csv(out / "strikes.csv", index=False)
    res.appeals.to_csv(out / "appeals.csv", index=False)
    (out / "run.json").write_text(json.dumps({
        "run_id": run_id, "as_of": res.as_of.isoformat(), "fy": res.fy, "watermark": res.watermark,
        "inputs": [{"upload_id": u.upload_id, "sha256": u.sha256, "as_of": u.as_of} for u in res.inputs],
        "warnings": res.warnings,
    }, indent=2))
    return out
