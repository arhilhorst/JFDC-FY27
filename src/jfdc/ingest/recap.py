"""Post-Event Recap Form responses (Microsoft Forms Excel)."""

from __future__ import annotations

import pandas as pd

from ..parsing import extract_bill_refs, parse_attendees, parse_event_dates, parse_yes_no
from .detect import IngestError, resolve_columns


def parse_recaps(df: pd.DataFrame, spec: dict) -> tuple[pd.DataFrame, list[dict], list[str]]:
    """Returns (recaps, issues, warnings)."""
    mapping, missing = resolve_columns(df, spec)
    if missing:
        raise IngestError("Recap form export is missing columns: " + "; ".join(missing))
    warnings = []
    for opt in (spec.get("optional_columns") or {}):
        if opt not in mapping:
            warnings.append(
                f"Form has no {opt!r} question yet (pending form change, docs/PENDING_CHANGES.md); using fallback."
            )
    r = df[list(mapping.values())].rename(columns={v: k for k, v in mapping.items()}).copy()
    r["_row"] = range(2, len(r) + 2)
    issues: list[dict] = []

    r["recap_id"] = r["response_id"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    dup = r["recap_id"].duplicated(keep="last")
    for row in r.loc[dup, "_row"]:
        issues.append({"row": int(row), "code": "DUP_RESPONSE", "message": "Duplicate response ID; later row kept"})
    r = r.loc[~dup].copy()

    r["submitted_at"] = pd.to_datetime(r["submitted_at"], errors="coerce")
    for row in r.loc[r["submitted_at"].isna(), "_row"]:
        issues.append({"row": int(row), "code": "BAD_TIMESTAMP", "message": "Completion time unreadable"})
    r = r.loc[r["submitted_at"].notna()].copy()

    refs = r["bill_text"].map(extract_bill_refs)
    r["engage_refs"] = refs.map(lambda rs: [x.token for x in rs if x.kind == "engage"])
    r["budget_refs"] = refs.map(lambda rs: [x.token for x in rs if x.kind == "budget"])

    parsed = [parse_event_dates(t, s.date()) for t, s in zip(r["date_location"], r["submitted_at"], strict=True)]
    r["event_dates"] = [p.dates for p in parsed]
    r["event_last_date"] = [p.last for p in parsed]
    r["event_date_ambiguous"] = [p.ambiguous for p in parsed]

    att = r["attendees_text"].map(parse_attendees)
    r["attendees_gt"] = att.map(lambda a: a.gt)
    r["attendees_non_gt"] = att.map(lambda a: a.non_gt)
    r["attendees_total"] = att.map(lambda a: a.total)
    r["has_proof"] = r["proof"].astype(str).str.strip().ne("") & r["proof"].astype(str).str.lower().ne("nan")

    r["funds_used"] = r["funds_used"].map(parse_yes_no) if "funds_used" in r else None
    r["attendance_tracked"] = r["attendance_tracked"].map(parse_yes_no) if "attendance_tracked" in r else None

    # §9.5.1 completeness: bill/budget #, event date and location, attendee count, proof.
    def missing_items(row) -> list[str]:
        m = []
        if not row["engage_refs"] and not row["budget_refs"]:
            m.append("bill/budget number")
        if row["event_last_date"] is None:
            m.append("event date")
        if not str(row["date_location"]).strip():
            m.append("location")
        if row["attendees_total"] is None and row.get("attendance_tracked") is not False:
            m.append("number of attendees")
        if not row["has_proof"] and row.get("attendance_tracked") is not False:
            m.append("proof of attendance")
        return m

    r["missing_items"] = r.apply(missing_items, axis=1)
    return r.drop(columns=["_row"]).reset_index(drop=True), issues, warnings
