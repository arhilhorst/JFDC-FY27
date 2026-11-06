"""Bill details: the 3-page Engage bill (Request / Additional Information / Budget).

Two input shapes:
  * the PDF Engage exports from the bill page ("PDF" button), one bill per file
  * the Bill Scraper V2 CSV (columns configured in config/sources/bill_details.yaml)

The PDF has NO Request ID, so PDF rows carry match keys (RSO, title, submit time) that
consolidate.py uses to find the Engage Id.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..parsing import parse_attendees, parse_engage_long_datetime, parse_event_dates, parse_yes_no
from ..textnorm import squash
from .detect import IngestError, excel_serial_to_datetime, resolve_columns

_PAGE_FOOTER = re.compile(r"\|\s*Page\s*\d+\s*of\s*\d+\s*$", re.IGNORECASE)
_PAGE_MARK = re.compile(r"^\s*Page\s*\d+\s*$", re.IGNORECASE)
HEADER_LABELS = {
    "requested_total": "Requested Total",
    "adjusted_total": "Adjusted Total",
    "date_created": "Date Created",
    "submitted_by": "Submitted By",
    "organization": "Organization",
    "status_line": "Status",
    "process": "Process",
}


def pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join((p.extract_text(extraction_mode="layout") or "") for p in reader.pages)


def parse_bill_text(text: str, questions: dict[str, str]) -> dict:
    """Parse the text of one exported bill PDF (layout mode: answers are indented)."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    lines = [ln for ln in lines if not _PAGE_FOOTER.search(ln) and not _PAGE_MARK.match(ln)]
    out: dict = {"title": None}

    for ln in lines:
        s = ln.strip()
        if s.startswith("Budget Request:") and out["title"] is None:
            out["title"] = s.split(":", 1)[1].strip()
            continue
        for key, label in HEADER_LABELS.items():
            if key not in out and re.match(rf"^{re.escape(label)}\s{{2,}}\S", s):
                out[key] = s[len(label):].strip()

    # Additional Information: un-indented lines are question text, indented lines are answers.
    try:
        start = next(i for i, ln in enumerate(lines) if ln.strip() == "Additional Information")
    except StopIteration:
        start = None
    qa: list[tuple[str, str]] = []
    if start is not None:
        q_buf: list[str] = []
        a_buf: list[str] = []
        for ln in lines[start + 1:]:
            if ln.strip() == "Request History":
                break
            if not ln.strip():
                continue
            if ln.startswith((" ", "\t")):
                a_buf.append(ln.strip())
            else:
                if a_buf:
                    qa.append((" ".join(q_buf), " ".join(a_buf)))
                    q_buf, a_buf = [], []
                q_buf.append(ln.strip())
        if q_buf:
            qa.append((" ".join(q_buf), " ".join(a_buf)))

    answers = {}
    for field, key in questions.items():
        k = squash(key)
        answers[field] = next((a for q, a in qa if k in squash(q)), None)
    out.update(answers)
    out["qa_count"] = len(qa)
    return out


re_serial = re.compile(r"\d{5}(\.\d+)?")
re_iso = re.compile(r"\d{4}-\d{2}-\d{2}")


def _finish(row: dict) -> dict:
    """Derive typed fields from the raw answers (shared by PDF and CSV paths)."""
    ref = row.get("submitted_at")
    ref_d = ref.date() if ref is not None and not pd.isna(ref) else None
    raw_date = row.get("event_date_text")
    serial = excel_serial_to_datetime(raw_date) if re_serial.fullmatch(str(raw_date or "").strip()) else None
    if serial is not None:  # Excel turned "11/18/26" into 46344
        raw_date = serial.strftime("%m/%d/%Y")
    elif re_iso.match(str(raw_date or "").strip()):  # pandas read a real Excel date cell
        raw_date = str(raw_date).strip()[:10].replace("-", "/")
        raw_date = "{1}/{2}/{0}".format(*raw_date.split("/"))
    p = parse_event_dates(raw_date, ref_d)
    na = str(raw_date or "").strip().lstrip("-").strip().lower() in {"", "n/a", "na", "none"}
    row["event_dates"] = p.dates
    row["event_last_date"] = p.last
    row["event_date_unparsed"] = (not na) and not p.dates
    row["event_date_ambiguous"] = bool(p.dates) and p.ambiguous
    ie = str(row.get("is_event_text") or "")
    row["is_event"] = parse_yes_no(ie)
    row["attestation_all_recaps"] = parse_yes_no(row.get("attestation_text"))
    att = parse_attendees(row.get("expected_attendance_text"))
    row["expected_gt"], row["expected_non_gt"] = att.gt, att.non_gt
    return row


_WEEKDAY = re.compile(r"\s*on\s*(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)", re.IGNORECASE)


def _status_word(line: str | None) -> str | None:
    if not line:
        return None
    return _WEEKDAY.split(line, maxsplit=1)[0].strip() or None


def parse_bill_pdf(path: Path, spec: dict) -> dict:
    text = pdf_text(path)
    if "Budget Request:" not in text:
        raise IngestError(f"{path.name} does not look like an Engage bill PDF (no 'Budget Request:' title).")
    raw = parse_bill_text(text, spec.get("pdf_questions", {}))
    row = {
        "bill_id": None,
        "title": raw.get("title"),
        "rso_squashed": squash(raw.get("organization") or ""),
        "process_squashed": squash(raw.get("process") or ""),
        "submitted_at": parse_engage_long_datetime(raw.get("status_line"))
        or parse_engage_long_datetime(raw.get("date_created")),
        "status_word": _status_word(raw.get("status_line")),
        "is_event_text": raw.get("is_event"),
        "attestation_text": raw.get("attestation"),
        "event_date_text": raw.get("event_date_text"),
        "expected_attendance_text": raw.get("expected_attendance_text"),
        "engage_event_link": raw.get("engage_event_link"),
        "purchased_prior": raw.get("purchased_prior"),
        "source_file": path.name,
    }
    return _finish(row)


def _unguard(v: object) -> object:
    """campuslabs-scraper.js prefixes ' to cells starting with = + - @ (formula guard). Undo it."""
    if isinstance(v, str) and len(v) > 1 and v[0] == "'" and v[1] in "=+-@\t\r":
        return v[1:]
    return v


def parse_bill_csv(df: pd.DataFrame, spec: dict) -> tuple[pd.DataFrame, list[dict], list[str]]:
    """Returns (details, issues, warnings). Rows the scraper marked `Error` are quarantined;
    rows marked `Warnings` (tab timed out: data may belong to the previous bill) are quarantined too,
    because a wrong event date could create a false strike."""
    mapping, missing = resolve_columns(df, spec)
    if missing:
        raise IngestError("Bill details file is missing columns: " + "; ".join(missing))
    d = df[list(mapping.values())].rename(columns={v: k for k, v in mapping.items()})
    rows, issues = [], []
    for i, rec in enumerate(d.to_dict("records"), start=2):
        rec = {k: _unguard(v) for k, v in rec.items()}
        rec["bill_id"] = str(rec["bill_id"]).strip()
        for col in ("scraper_error", "scraper_warning"):
            msg = str(rec.get(col) or "").strip()
            if msg:
                issues.append({"row": i, "code": col.upper(), "message": f"Bill {rec['bill_id']}: {msg} (re-scrape)"})
                break
        else:
            rec.setdefault("submitted_at", None)
            rows.append(_finish(rec))
    warns = [f"{len(issues)} scraper rows flagged Warnings/Error were quarantined; re-run the scraper for them."] if issues else []
    return pd.DataFrame(rows), issues, warns
