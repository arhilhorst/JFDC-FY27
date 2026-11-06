"""JFC data sheet: FY final budgets (per-RSO totals)."""

from __future__ import annotations

import pandas as pd

from ..parsing import to_cents
from .detect import IngestError, resolve_columns


def parse_budgets(df: pd.DataFrame, spec: dict) -> pd.DataFrame:
    df = df.rename(columns={c: c.strip() for c in df.columns})
    mapping, missing = resolve_columns(df, spec)
    if missing:
        raise IngestError("Budget sheet is missing columns: " + "; ".join(missing))
    b = df[list(mapping.values())].rename(columns={v: k for k, v in mapping.items()}).copy()
    b["rso"] = b["rso"].str.strip()
    b["requested_c"] = b["requested"].map(to_cents)
    b["allocated_c"] = b["allocated"].map(to_cents)
    return b.loc[b["rso"] != "", ["rso", "requested_c", "allocated_c"]].reset_index(drop=True)
