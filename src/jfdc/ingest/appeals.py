"""Strike Appeal Form responses (Microsoft Forms Excel). See docs/APPEALS.md."""

from __future__ import annotations

import pandas as pd

from ..parsing import extract_bill_refs
from .detect import IngestError, resolve_columns

APPEAL_COLUMNS = ["appeal_id", "bill_id", "submitted_at", "rso", "bill_text", "appellant_name", "appellant_email",
                  "reason", "explanation", "evidence"]


def parse_appeals(df: pd.DataFrame, spec: dict) -> tuple[pd.DataFrame, list[dict], list[str]]:
    """One row per (appeal, bill). An appeal naming two bills becomes two rows, each decided on its own."""
    mapping, missing = resolve_columns(df, spec)
    # "name"/"email" prefixes would also match "Your name"/"Your GT email"; only trust exact Forms columns.
    for opt, header in (("form_email", "Email"), ("form_name", "Name")):
        mapping[opt] = header if header in df.columns else None
    mapping = {k: v for k, v in mapping.items() if v}
    if missing:
        raise IngestError("Appeal form export is missing columns: " + "; ".join(missing))
    a = df[list(mapping.values())].rename(columns={v: k for k, v in mapping.items()}).copy()
    a["_row"] = range(2, len(a) + 2)
    issues: list[dict] = []

    a["appeal_id"] = a["response_id"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    a["submitted_at"] = pd.to_datetime(a["submitted_at"], errors="coerce")
    for row in a.loc[a["submitted_at"].isna(), "_row"]:
        issues.append({"row": int(row), "code": "BAD_TIMESTAMP", "message": "Completion time unreadable"})
    a = a.loc[a["submitted_at"].notna()].copy()
    for c in ("evidence", "form_email", "form_name"):
        if c not in a:
            a[c] = ""
    # Reply to the GT account Forms recorded (authenticated) when there is one; the typed address is only a
    # fallback, and notify.py still checks it is a single allowed address before anything is sent.
    a["appellant_email"] = a["form_email"].where(a["form_email"].astype(str).str.strip() != "", a["appellant_email"])
    a["appellant_name"] = a["appellant_name"].where(a["appellant_name"].str.strip() != "", a["form_name"])
    a["appellant_email"] = a["appellant_email"].str.strip().str.lower()

    rows = []
    for r in a.to_dict("records"):
        bills = [x.token for x in extract_bill_refs(r["bill_text"]) if x.kind == "engage"] or [""]
        for b in dict.fromkeys(bills):
            rows.append({c: (b if c == "bill_id" else r.get(c, "")) for c in APPEAL_COLUMNS})
    out = pd.DataFrame(rows, columns=APPEAL_COLUMNS)
    return out, issues, []
