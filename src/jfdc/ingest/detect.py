"""Read CSV/XLSX/XLS and decide which source each file (or workbook TAB) is, from its HEADER ROW.

A workbook like the JFC Data Sheet holds several sources in different tabs; each recognized tab
becomes its own upload. Filenames are never trusted.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from ..config import Config
from ..textnorm import norm_header

EXCEL_SUFFIXES = {".xlsx", ".xlsm", ".xls"}
_PLACEHOLDER = re.compile(r"^column\d+$", re.IGNORECASE)


class IngestError(Exception):
    pass


def sheet_names(path: Path) -> list[str | None]:
    if path.suffix.lower() in EXCEL_SUFFIXES:
        return list(pd.ExcelFile(path).sheet_names)
    return [None]


def read_table(path: Path, encodings: list[str] | None = None, sheet: str | None = None) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in EXCEL_SUFFIXES:
        df = pd.read_excel(path, dtype=str, sheet_name=sheet if sheet is not None else 0)
    elif suffix in {".csv", ".txt"}:
        last: Exception | None = None
        for enc in encodings or ["utf-8-sig", "cp1252"]:
            try:
                df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding=enc, skipinitialspace=True)
                break
            except UnicodeDecodeError as e:
                last = e
        else:
            raise IngestError(f"Could not decode {path.name} as {encodings}: {last}")
    else:
        raise IngestError(f"Unsupported file type {suffix!r} ({path.name}). Upload CSV, XLSX, XLS or PDF.")
    df = df.fillna("")
    # Excel tables / Power Query pastes put "Column1, Column2, ..." above the real header row.
    if len(df) and len(df.columns) and all(_PLACEHOLDER.match(str(c)) for c in df.columns):
        df.columns = [str(c) for c in df.iloc[0]]
        df = df.iloc[1:].reset_index(drop=True)
    df = df.loc[~(df.astype(str).apply(lambda c: c.str.strip()) == "").all(axis=1)]  # drop blank rows
    return df


def _match_header(headers: list[str], pattern: str, mode: str) -> str | None:
    p = norm_header(pattern)
    for h in headers:
        nh = norm_header(h)
        if (mode == "exact" and nh == p) or (mode == "prefix" and nh.startswith(p)) or (mode == "contains" and p in nh):
            return h
    return None


def resolve_columns(df: pd.DataFrame, spec: dict) -> tuple[dict[str, str], list[str]]:
    """Map canonical field -> actual header. Returns (mapping, missing_required)."""
    headers = list(df.columns)
    mode = spec.get("match", "exact")
    mapping, missing = {}, []
    for canon, pattern in spec.get("columns", {}).items():
        h = _match_header(headers, pattern, mode)
        if h is None:
            missing.append(f"{canon} (expected header {pattern!r})")
        else:
            mapping[canon] = h
    for canon, pattern in (spec.get("optional_columns") or {}).items():
        h = _match_header(headers, pattern, mode)
        if h is not None:
            mapping[canon] = h
    return mapping, missing


def _sources_for(df: pd.DataFrame, cfg: Config) -> list[str]:
    headers = list(df.columns)
    return [key for key, spec in cfg.sources.items()
            if spec.get("fingerprint") and all(_match_header(headers, f, spec.get("match", "exact"))
                                               for f in spec["fingerprint"])]


def detect_sources(path: Path, cfg: Config) -> tuple[list[tuple[str, str | None]], list[str]]:
    """[(source, sheet)] for every recognized table in the file, plus names of skipped tabs."""
    if path.suffix.lower() == ".pdf":
        return [("bill_details", None)], []
    found, skipped = [], []
    for sheet in sheet_names(path):
        try:
            df = read_table(path, None, sheet)
        except IngestError:
            continue
        hits = _sources_for(df, cfg)
        if len(hits) == 1:
            found.append((hits[0], sheet))
        elif len(hits) > 1:
            raise IngestError(f"{path.name} [{sheet}]: header matches several sources {hits}. Pass --source.")
        elif sheet is not None:
            skipped.append(sheet)
    if not found:
        raise IngestError(
            f"{path.name}: no tab/header matches a known source. If Engage, the Form or the JFC sheet changed "
            "its columns, update config/sources/*.yaml. Pass --source to force."
        )
    return found, skipped


def detect_source(path: Path, cfg: Config) -> str:
    return detect_sources(path, cfg)[0][0][0]


_EXCEL_EPOCH = datetime(1899, 12, 30)


def excel_serial_to_datetime(v: object) -> datetime | None:
    """46344 -> 2026-11-18; 44064.7604 -> 2020-08-21 18:15. Only for plausible serials (1990-2060)."""
    try:
        f = float(str(v).strip())
    except ValueError:
        return None
    if not 32874 <= f <= 58440:
        return None
    return _EXCEL_EPOCH + timedelta(seconds=round(f * 86400))
