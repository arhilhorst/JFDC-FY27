"""Engage request export: one row per LINE ITEM -> one row per bill."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from ..parsing import to_cents
from .detect import IngestError, excel_serial_to_datetime, resolve_columns


def parse_engage(df: pd.DataFrame, spec: dict, event_prefixes: list[str]) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    """Returns (bills, line_items, issues)."""
    mapping, missing = resolve_columns(df, spec)
    if missing:
        raise IngestError("Engage export is missing columns: " + "; ".join(missing))
    li = df[list(mapping.values())].rename(columns={v: k for k, v in mapping.items()}).copy()
    li["_row"] = range(2, len(li) + 2)  # spreadsheet row numbers (header = 1)
    issues: list[dict] = []

    bad = ~li["bill_id"].str.strip().str.fullmatch(r"\d+")
    for r in li.loc[bad, "_row"]:
        issues.append({"row": int(r), "code": "BAD_ID", "message": "Id is empty or not numeric"})
    li = li.loc[~bad].copy()
    li["bill_id"] = li["bill_id"].str.strip()

    fmt = spec.get("datetime_format")
    for col in ("first_submitted", "last_submitted"):
        raw = li[col]
        parsed = pd.to_datetime(raw, format=fmt, errors="coerce")
        # The JFC Data Sheet's pasted copy stores Excel serials (44064.7604...) or ISO datetimes.
        miss = parsed.isna() & raw.astype(str).str.strip().ne("")
        if miss.any():
            alt = raw[miss].map(lambda v: excel_serial_to_datetime(v) or pd.to_datetime(v, errors="coerce"))
            parsed.loc[miss] = pd.to_datetime(alt, errors="coerce")
        li[col] = parsed
    for col in ("requested", "adjusted"):
        li[col + "_c"] = li[col].map(to_cents)
    for c in ("rso", "title", "status", "process", "submitter_email", "submitter_name", "section"):
        li[c] = li[c].astype(str).str.strip()

    li["is_event_section"] = li["section"].str.upper().str.startswith(tuple(p.upper() for p in event_prefixes))
    g = li.groupby("bill_id", sort=False)
    bills = g.agg(
        process=("process", "first"),
        title=("title", "first"),
        rso=("rso", "first"),
        submitter_name=("submitter_name", "first"),
        submitter_email=("submitter_email", "first"),
        first_submitted=("first_submitted", "first"),
        last_submitted=("last_submitted", "first"),
        status=("status", "first"),
        step=("step", "first"),
        requested_c=("requested_c", lambda s: int(s.fillna(0).sum())),
        adjusted_c=("adjusted_c", lambda s: int(s.fillna(0).sum())),
        line_items=("line_item", lambda s: int((s.str.strip() != "").sum())),
        has_event_section=("is_event_section", "any"),
    ).reset_index()
    return bills, li.drop(columns=["_row"]), issues


def newest_record(bills: pd.DataFrame) -> datetime | None:
    v = bills["last_submitted"].max()
    return None if pd.isna(v) else v.to_pydatetime()
