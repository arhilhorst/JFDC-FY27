"""Helpers for cleaning the free-text answers RSOs type into the recap form."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

_BILL_RE = re.compile(r"(?<![\d.])(\d{5,6})(?![\d.])")


def norm_header(h: Any) -> str:
    s = "" if h is None else str(h)
    s = s.replace("\xa0", " ").split("\n")[0]
    return re.sub(r"\s+", " ", s).strip().rstrip(":").strip().lower()


def map_columns(headers: list[str], spec: dict) -> dict[str, int]:
    """Return {field: column index} using exact match first, then 'starts with'."""
    normed = [norm_header(h) for h in headers]
    used: set[int] = set()
    out: dict[str, int] = {}
    for fld, candidates in spec.items():
        if fld.startswith("_"):
            continue
        cands = [norm_header(c) for c in candidates]
        idx = next((i for c in cands for i, h in enumerate(normed) if h == c and i not in used), None)
        if idx is None:
            idx = next((i for c in cands for i, h in enumerate(normed) if c and h.startswith(c) and i not in used), None)
        if idx is not None:
            out[fld] = idx
            used.add(idx)
    return out


def norm_rso(name: Any) -> str:
    """Key used to match the same RSO across the recap form and the bills sheet."""
    s = "" if name is None else str(name)
    s = s.lower().replace("&", " and ").replace("@", " at ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\b(the|inc|at georgia tech|at gt|georgia tech|gt)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_bill_number(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    m = re.search(r"\d{4,7}", s)
    return m.group(0) if m else s


def parse_bill_numbers(text: Any) -> list[str]:
    """'Bill #377345', '376684, 375615', '[Bill #26909], [Bill #26910]' -> numbers.

    Ignores dollar amounts like 236.39 and short numbers like line items.
    """
    if text is None:
        return []
    if isinstance(text, (int, float)):
        return [clean_bill_number(text)]
    seen: list[str] = []
    for m in _BILL_RE.finditer(str(text)):
        n = m.group(1)
        if n not in seen:
            seen.append(n)
    return seen


_NUM = r"(\d[\d,]*)"


def parse_attendance(text: Any) -> dict:
    """'58 gt, 4 non-gt' -> {'gt': 58, 'non_gt': 4, 'total': 62, 'tracked': True}."""
    raw = "" if text is None else str(text).strip()
    out = {"raw": raw, "gt": None, "non_gt": None, "total": None, "tracked": False, "issue": None}
    low = raw.lower()
    if not raw or re.fullmatch(r"n/?a\.?|none|-|0", low):
        out["issue"] = "No attendance number given"
        return out
    if re.search(r"-\s*\d", low) and not re.search(r"\d\s*-\s*\d", low):
        out["issue"] = "Negative attendance number"
    non = re.search(_NUM + r"\s*(?:non[\s-]*gt|non[\s-]*georgia|non[\s-]*students?|external|guests?)", low)
    gt = re.search(_NUM + r"\s*(?:gt|georgia tech|students?|ga tech)(?![\w-]*non)", low)
    nums = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", low)]
    if gt:
        out["gt"] = int(gt.group(1).replace(",", ""))
    if non:
        out["non_gt"] = int(non.group(1).replace(",", ""))
    looks_like_date = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d", low)
    if out["gt"] is None and out["non_gt"] is None and nums and not looks_like_date:
        # plain number like "52" or "~20"
        out["gt"] = nums[0]
        out["issue"] = out["issue"] or "GT / non-GT split not given"
    if out["gt"] is None and out["non_gt"] is None:
        out["issue"] = out["issue"] or "Could not read an attendance number"
        return out
    out["total"] = (out["gt"] or 0) + (out["non_gt"] or 0)
    m = re.search(r"=\s*" + _NUM + r"\s*total", low)
    if m:
        out["total"] = int(m.group(1).replace(",", ""))
    if re.search(r"approx|~|about|around|-\s*\d+\s*students passing|passing by", low):
        out["issue"] = out["issue"] or "Approximate count"
    out["tracked"] = True
    return out


_DATE_FORMATS = [
    "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p",
    "%m/%d/%y %H:%M", "%B %d, %Y", "%b %d, %Y", "%d-%b-%Y", "%m-%d-%Y", "%m-%d-%y",
]


def parse_date(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)):  # Excel serial date
        try:
            return (datetime(1899, 12, 30) + timedelta(days=float(v))).date()
        except (OverflowError, ValueError):
            return None
    s = str(v).strip()
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "")).date()
    except ValueError:
        return None


def parse_datetime(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v
    d = parse_date(v)
    if d is None:
        try:
            return datetime.fromisoformat(str(v))
        except (TypeError, ValueError):
            return None
    try:
        return datetime.fromisoformat(str(v).strip())
    except ValueError:
        return datetime(d.year, d.month, d.day, 12, 0)


def parse_money(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?[\d,]*\.?\d+", str(v).replace("$", ""))
    return float(m.group(0).replace(",", "")) if m else None


def parse_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"\d[\d,]*", str(v))
    return int(m.group(0).replace(",", "")) if m else None


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|set|oct|nov|dec)[a-z]*\.?"


def parse_event_date_text(text: Any, submitted: date | None) -> date | None:
    """Pull the event date out of the free-text 'Event Date and Location' answer.

    Handles '8/28/2026', '09/08/26', '10-9-26', '8/21', 'Thursday, September 10, 2026',
    'Thurs Aug 27', 'September 3rd'. A missing year is taken from the submission date,
    and a date that would land after the submission is moved back a year.
    """
    if text is None:
        return None
    if isinstance(text, (datetime, date)):
        return parse_date(text)
    s = str(text).lower()
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s)
    found: list[tuple[int, int, int | None]] = []
    for m in re.finditer(r"(?<![\d.])(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?(?![\d])", s):
        mo, dy, yr = int(m.group(1)), int(m.group(2)), m.group(3)
        found.append((mo, dy, int(yr) if yr else None))
        break
    if not found:
        m = re.search(_MONTH_RE + r"\s+(\d{1,2})(?:,?\s+(\d{4}))?", s)
        if m:
            key = "sep" if m.group(1) == "set" else m.group(1)[:3]
            found.append((_MONTHS[key], int(m.group(2)), int(m.group(3)) if m.group(3) else None))
    if not found:
        return None
    mo, dy, yr = found[0]
    if yr is not None and yr < 100:
        yr += 2000
    if yr is None:
        yr = submitted.year if submitted else date.today().year
        guess_ok = True
    else:
        guess_ok = False
    try:
        d = date(yr, mo, dy)
    except ValueError:
        return None
    if guess_ok and submitted and d > submitted + timedelta(days=1):
        try:
            d = date(yr - 1, mo, dy)
        except ValueError:
            return None
    if submitted and abs((submitted - d).days) > 400:
        return None  # typo like 09/24/2006
    return d
