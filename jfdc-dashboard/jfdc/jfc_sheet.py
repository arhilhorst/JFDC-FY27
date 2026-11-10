"""Reads Walker's "JFC Data Sheet" workbook directly.

That workbook has, among others:
  - "Data Pasting Site": the Engage (Campus Labs) budgeting export, one row per
    LINE ITEM (Id, ProcessName, Title, SubmittedOnBehalfOf, Status, amounts,
    SectionName like "A01 - Food and Drinks").
  - "CampusLabs_Budget_Requests": the bill form answers (Q8 event date, Q10
    expected attendance, Q3 "have you submitted all recap forms?").
  - "Bill Queue": bill numbers waiting for JFC review.

This module turns it into one row per bill with the standard column names the
rest of the app understands. If Walker renames a sheet or column, fix it here.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from datetime import date, datetime, timedelta
from typing import Any

from .parsing import clean_bill_number, norm_header

ENGAGE_SHEET = "Data Pasting Site"
ANSWERS_SHEET = "CampusLabs_Budget_Requests"
QUEUE_SHEET = "Bill Queue"

OUT_HEADERS = [
    "Bill Number", "Organization", "Bill Name", "Event Date", "Submitted Date", "Status", "Category",
    "Amount Requested", "Amount Approved", "Expected Attendance", "In Review Queue", "Review Step",
    "Says All Recaps Submitted", "Submitter", "Process", "Sections",
]


def is_jfc_workbook(sheetnames: list[str]) -> bool:
    return ENGAGE_SHEET in sheetnames


def _rows_with_header(ws, must_have: list[str]) -> tuple[list[str], list[tuple]]:
    """Some sheets have a dummy 'Column1, Column2...' row above the real header."""
    rows = ws.iter_rows(values_only=True)
    header: list[str] | None = None
    data = []
    for i, r in enumerate(rows):
        if header is None:
            normed = [norm_header(c) for c in r]
            if all(m in normed for m in must_have):
                header = normed
            elif i > 5:
                return [], []
            continue
        if r and any(c not in (None, "") for c in r):
            data.append(r)
    return header or [], data


def _excel_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if 20000 < f < 80000:
        return (datetime(1899, 12, 30) + timedelta(days=f)).date()
    return None


def _category(sections: set[str]) -> str:
    codes = {s.strip()[:1].upper() for s in sections if s}
    if "A" in codes:
        return "Event"
    if "C" in codes:
        return "Travel/Competition"
    if "B" in codes:
        return "Inventory/Operations"
    return "Other"


def _process_fy(name: str) -> int | None:
    m = re.search(r"FY\s*(\d{2,4})", name or "")
    if not m:
        return None
    y = int(m.group(1))
    return y + 2000 if y < 100 else y


def load_jfc_workbook(wb, process_pattern: str = r"Bills Process", min_fy: int | None = None):
    """Return (headers, rows) with one row per bill."""
    from .sources import Table  # local import to avoid a cycle

    # --- bill form answers (event date etc.) ---
    answers: dict[str, dict] = {}
    if ANSWERS_SHEET in wb.sheetnames:
        h, data = _rows_with_header(wb[ANSWERS_SHEET], ["bill number"])
        idx = {k: i for i, k in enumerate(h)}

        def col(prefix: str) -> int | None:
            return next((i for k, i in idx.items() if k.startswith(prefix)), None)

        q3, q4, q8, q10 = col("q3"), col("q4"), col("q8"), col("q10")
        for r in data:
            num = clean_bill_number(r[idx["bill number"]])
            if not num:
                continue
            answers[num] = {
                "event_date": r[q8] if q8 is not None else None,
                "expected": r[q10] if q10 is not None else None,
                "says_recaps": r[q3] if q3 is not None else None,
                "is_event": r[q4] if q4 is not None else None,
            }

    # --- review queue ---
    queue: dict[str, str] = {}
    if QUEUE_SHEET in wb.sheetnames:
        for r in wb[QUEUE_SHEET].iter_rows(min_row=2, values_only=True):
            if r and r[0] is not None:
                n = clean_bill_number(r[0])
                if n.isdigit():
                    queue[n] = str(r[1]).strip() if len(r) > 1 and r[1] else ""

    # --- Engage line items -> bills ---
    h, data = _rows_with_header(wb[ENGAGE_SHEET], ["id", "processname", "submittedonbehalfof"])
    ix = {k: i for i, k in enumerate(h)}
    g = lambda r, k: r[ix[k]] if k in ix and ix[k] < len(r) else None  # noqa: E731
    pat = re.compile(process_pattern, re.I)
    bills: "OrderedDict[str, dict]" = OrderedDict()
    submitter_rso: dict[str, tuple] = {}
    for r in data:
        who, org, when = g(r, "submittername"), g(r, "submittedonbehalfof"), _excel_date(g(r, "firstsubmitted"))
        if who and org and (who not in submitter_rso or (when and submitter_rso[who][1] and when > submitter_rso[who][1])):
            submitter_rso[str(who).strip()] = (org, when)
        proc = str(g(r, "processname") or "")
        if not pat.search(proc):
            continue
        pfy = _process_fy(proc)
        if min_fy and pfy and pfy < min_fy:
            continue
        num = clean_bill_number(g(r, "id"))
        b = bills.get(num)
        if b is None:
            b = bills[num] = {
                "num": num, "rso": g(r, "submittedonbehalfof"), "title": g(r, "title"),
                "submitted": _excel_date(g(r, "firstsubmitted")), "status": g(r, "status"),
                "step": g(r, "currentstepname") or "", "submitter": g(r, "submittername"), "process": proc,
                "req": 0.0, "adj": 0.0, "sections": set(),
            }
        b["req"] += float(g(r, "requestedamount") or 0)
        b["adj"] += float(g(r, "adjustedamount") or 0)
        if g(r, "sectionname"):
            b["sections"].add(str(g(r, "sectionname")))

    rows = []
    for num, b in bills.items():
        a = answers.get(num, {})
        ev = _excel_date(a.get("event_date"))
        ev_out: Any = ev if ev else (a.get("event_date") if a.get("event_date") not in (None, "N/A", "n/a") else None)
        approved = str(b["status"]).lower() == "approved"
        rows.append([
            num, b["rso"], b["title"], ev_out, b["submitted"], b["status"], _category(b["sections"]),
            round(b["req"], 2), round(b["adj"], 2) if approved else None, a.get("expected"),
            "Yes" if num in queue else "", b["step"], a.get("says_recaps"), b["submitter"], b["process"],
            "; ".join(sorted(b["sections"])),
        ])
    # Bills in the queue that aren't in the Engage export yet: guess the RSO from
    # the submitter's most recent other bill.
    for num in sorted(set(queue) - set(bills)):
        a = answers.get(num, {})
        who = queue[num]
        rso = submitter_rso.get(who, (None,))[0]
        is_event = str(a.get("is_event") or "").lower().startswith("yes")
        rows.append([num, rso, "Not in the Engage export yet (RSO matched by submitter)" if rso else "Not in the Engage export yet",
                     _excel_date(a.get("event_date")), None, "In review", "Event" if is_event else None, None, None,
                     a.get("expected"), "Yes", "", a.get("says_recaps"), who, "", ""])
    return Table(list(OUT_HEADERS), rows, "JFC Data Sheet")
