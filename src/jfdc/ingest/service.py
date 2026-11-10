"""`jfdc ingest`: validate a file fully BEFORE accepting it, then store it immutably.

A workbook (e.g. the JFC Data Sheet) can hold several sources; each recognized tab is validated
and registered as its own upload. Unrecognized tabs are listed and skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from ..config import Config
from ..workspace import Upload, Workspace, sha256_file
from .appeals import parse_appeals
from .bill_details import parse_bill_csv, parse_bill_pdf
from .budgets import parse_budgets
from .detect import IngestError, detect_sources, read_table
from .engage import newest_record, parse_engage
from .recap import parse_recaps


@dataclass
class IngestResult:
    upload: Upload | None
    source: str
    sheet: str | None = None
    duplicate_of: Upload | None = None
    warnings: list[str] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)


def parse_source(path: Path, source: str, cfg: Config, sheet: str | None = None):
    """Parse a stored or candidate file. Returns (parsed, issues, warnings, newest_record)."""
    spec = cfg.sources[source]
    if source == "engage_line_items":
        df = read_table(path, spec.get("encodings"), sheet)
        bills, items, issues = parse_engage(df, spec, cfg.policy["event_section_prefixes"])
        return (bills, items), issues, [], newest_record(bills)
    if source == "recap_form":
        df = read_table(path, spec.get("encodings"), sheet)
        recaps, issues, warns = parse_recaps(df, spec)
        newest = recaps["submitted_at"].max().to_pydatetime() if len(recaps) else None
        return recaps, issues, warns, newest
    if source == "bill_details":
        if path.suffix.lower() == ".pdf":
            row = parse_bill_pdf(path, spec)
            return pd.DataFrame([row]), [], [], row.get("submitted_at")
        details, issues, warns = parse_bill_csv(read_table(path, spec.get("encodings"), sheet), spec)
        return details, issues, warns, None
    if source == "appeals":
        appeals, issues, warns = parse_appeals(read_table(path, spec.get("encodings"), sheet), spec)
        newest = appeals["submitted_at"].max().to_pydatetime() if len(appeals) else None
        return appeals, issues, warns, newest
    if source == "jfc_budgets":
        return parse_budgets(read_table(path, spec.get("encodings"), sheet), spec), [], [], None
    raise IngestError(f"Unknown source {source!r}")


def _rows(parsed) -> int:
    return len(parsed[0]) if isinstance(parsed, tuple) else len(parsed)


def ingest_file(ws: Workspace, cfg: Config, path: Path, by: str, source: str | None = None,
                as_of: datetime | None = None) -> list[IngestResult]:
    path = Path(path)
    if not path.exists():
        raise IngestError(f"No such file: {path}")
    if source:
        targets, skipped = [(source, None)], []
    else:
        targets, skipped = detect_sources(path, cfg)
    sha = sha256_file(path)
    as_of = as_of or datetime.now().replace(microsecond=0)
    gap = cfg.policy["freshness"]["newest_record_gap_days"]

    # Parse every tab first: nothing is stored unless the whole file is readable.
    staged = []
    for src, sheet in targets:
        dup = ws.find_by_hash(sha, sheet)
        if dup:
            staged.append((src, sheet, dup, None))
            continue
        parsed, issues, warns, newest = parse_source(path, src, cfg, sheet)
        if newest is not None and as_of - newest > timedelta(days=gap) and src != "bill_details":
            warns.append(f"Newest record is {newest:%Y-%m-%d %H:%M}, {(as_of - newest).days} days before its "
                         f"as-of {as_of:%Y-%m-%d}. Is this really a fresh export?")
        if src == "engage_line_items":
            n = len(read_table(path, cfg.sources[src].get("encodings"), sheet))
            if 64_000 <= n <= 66_000:
                warns.append(f"{n:,} rows: close to Engage's ~65k export cap, so the file may be truncated.")
        staged.append((src, sheet, None, (parsed, issues, warns, newest)))

    results = []
    for src, sheet, dup, payload in staged:
        if dup:
            results.append(IngestResult(None, src, sheet, duplicate_of=dup,
                                        warnings=[f"Identical file already ingested as {dup.upload_id} ({dup.original_name})."]))
            continue
        parsed, issues, warns, newest = payload
        up = ws.store_upload(path, src, as_of, by, rows_ok=_rows(parsed), rows_quarantined=len(issues),
                             newest_record=newest.isoformat(timespec="seconds") if newest else None,
                             notes=" | ".join(warns), sheet=sheet)
        results.append(IngestResult(up, src, sheet, warnings=warns, issues=issues))
    if skipped and results:
        results[0].warnings.append(f"Skipped tabs with no matching source: {', '.join(skipped)}")
    return results
