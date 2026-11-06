"""Parsers for the free-text fields RSOs type: bill numbers, dates, attendees, money."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# ---------------------------------------------------------------- bill numbers

# Engage request IDs are 6 digits. 5-digit numbers are budget IDs from the
# JFC data sheet budget page (Chair, open item B2).
_REF = re.compile(r"(?<!\d)(\d{5,6})(?!\d)")


@dataclass(frozen=True)
class BillRef:
    token: str
    kind: str  # "engage" (6-digit Engage request ID) | "budget" (5-digit budget ID)


def extract_bill_refs(text: object) -> list[BillRef]:
    """Every bill/budget number in a recap's bill field, in order, de-duplicated.

    Handles "376684, 375615", "Bill # 377345", "[Bill #26909], [Bill #26910]",
    "Budget 338443 Line 17, Budget 338443 Line 18" (-> one ref), "N/Aa" (-> none).
    """
    if text is None:
        return []
    s = str(text)
    if s.strip().lower() in {"", "nan", "none"}:
        return []
    seen: dict[str, BillRef] = {}
    for tok in _REF.findall(s):
        if tok not in seen:
            seen[tok] = BillRef(tok, "engage" if len(tok) == 6 else "budget")
    return list(seen.values())


# ---------------------------------------------------------------- money

def to_cents(v: object) -> int | None:
    s = str(v if v is not None else "").strip().replace("$", "").replace(",", "")
    if s in {"", "nan", "None"}:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        c = round(float(s) * 100)
    except ValueError:
        return None
    return -c if neg else c


# ---------------------------------------------------------------- dates

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"), ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))

# 9/25/26, 09/04/2026, 10-9-26, 8/21 (same separator for the year; not preceded by ':' so
# "6:30-8 PM" is not read as a date).
_NUMERIC = re.compile(r"(?<![\d:/.])(\d{1,2})([/-])(\d{1,2})(?:\2(\d{4}|\d{2}))?(?![\d:])")
# "11/7-8/2026" (day range inside a numeric date)
_NUMERIC_RANGE = re.compile(r"(?<![\d:/.])(\d{1,2})/(\d{1,2})\s*-\s*(\d{1,2})/(\d{4}|\d{2})(?![\d:/])")
# "October 12, 2026", "Sept 3-5, 2026", "Aug 27", "October12,2026" (squashed PDF text)
_NAMED = re.compile(
    rf"(?<![a-z])({_MONTH_ALT})\.?\s*(\d{{1,2}})(?:st|nd|rd|th)?"
    rf"(?:\s*[-–]\s*(\d{{1,2}})(?:st|nd|rd|th)?)?(?:\s*,?\s*(\d{{4}}))?(?!\d)",
    re.IGNORECASE,
)


@dataclass
class DateParse:
    dates: list[date]
    ambiguous: bool  # year had to be inferred, or nothing usable found

    @property
    def last(self) -> date | None:
        return max(self.dates) if self.dates else None

    @property
    def first(self) -> date | None:
        return min(self.dates) if self.dates else None


def _year(y: str | None) -> int | None:
    if not y:
        return None
    n = int(y)
    return n + 2000 if n < 100 else n


def parse_event_dates(text: object, reference: date | None = None) -> DateParse:
    """Pull every date out of free text like '8/28/26, 11am-12pm, Kendeda 152'.

    Dates without a year take the year that puts them closest to (and not long after)
    `reference` (normally the recap submission date, or the bill submit date).
    """
    s = str(text or "")
    found: list[tuple[int, int, int | None]] = []  # (month, day, year|None)
    named_spans: list[tuple[int, int]] = []
    for m in _NAMED.finditer(s):
        named_spans.append(m.span())
        mo = _MONTHS[m.group(1).lower()]
        d1, d2, y = int(m.group(2)), m.group(3), _year(m.group(4))
        if 1 <= d1 <= 31:
            found.append((mo, d1, y))
        if d2 and 1 <= int(d2) <= 31:
            found.append((mo, int(d2), y))
    for m in _NUMERIC_RANGE.finditer(s):
        named_spans.append(m.span())
        mo, y = int(m.group(1)), _year(m.group(4))
        for d in (int(m.group(2)), int(m.group(3))):
            if 1 <= mo <= 12 and 1 <= d <= 31:
                found.append((mo, d, y))
    for m in _NUMERIC.finditer(s):
        if any(a <= m.start() < b for a, b in named_spans):
            continue  # "Sept 3-5" is a day range, not March 5
        mo, d, y = int(m.group(1)), int(m.group(3)), _year(m.group(4))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            found.append((mo, d, y))

    if not found:
        return DateParse([], ambiguous=True)

    known_years = [y for _, _, y in found if y]
    # "with Backup: 11/14-15" or dates weeks apart: a person must pick the real date.
    ambiguous = bool(re.search(r"backup|tbd|or\s+\d", s, re.IGNORECASE))
    out: list[date] = []
    for mo, d, y in found:
        if y is None:
            ambiguous = ambiguous or (not known_years and reference is None)
            y = known_years[-1] if known_years else _infer_year(mo, d, reference)
        try:
            out.append(date(y, mo, d))
        except ValueError:
            ambiguous = True
    out = sorted(set(out))
    if len(out) > 1 and (out[-1] - out[0]).days > 14:
        ambiguous = True
    return DateParse(out, ambiguous=ambiguous or not out)


def _infer_year(mo: int, d: int, reference: date | None) -> int:
    ref = reference or date.today()
    for y in (ref.year, ref.year - 1, ref.year + 1):
        try:
            cand = date(y, mo, d)
        except ValueError:
            continue
        if cand <= ref + timedelta(days=60) and cand >= ref - timedelta(days=300):
            return y
    return ref.year


_SQUASHED_DT = re.compile(
    rf"({_MONTH_ALT}),?\s*(\d{{1,2}}),\s*(\d{{4}})\s*(\d{{1,2}}):(\d{{2}})(?::(\d{{2}}))?\s*(AM|PM)",
    re.IGNORECASE,
)


def parse_engage_long_datetime(text: object) -> datetime | None:
    """'Thursday,November5,202610:32:46PM' or 'Thursday, November 5, 2026 10:32:46 PM'."""
    m = _SQUASHED_DT.search(str(text or ""))
    if not m:
        return None
    mo = _MONTHS[m.group(1).lower()]
    hh = int(m.group(4)) % 12 + (12 if m.group(7).upper() == "PM" else 0)
    return datetime(int(m.group(3)), mo, int(m.group(2)), hh, int(m.group(5)), int(m.group(6) or 0))


# ---------------------------------------------------------------- attendees

_NUM = re.compile(r"\d[\d,]*")


@dataclass
class Attendance:
    gt: int | None
    non_gt: int | None

    @property
    def total(self) -> int | None:
        if self.gt is None and self.non_gt is None:
            return None
        return (self.gt or 0) + (self.non_gt or 0)


def parse_attendees(text: object) -> Attendance:
    """'45 GT, 0 non-GT' / '58 gt, 4 non-gt' / '46 GT students' / '52' / '100 GT, 5 Non-GT'."""
    s = str(text or "").lower()
    if not s.strip() or s.strip() in {"nan", "n/a", "na", "none", "-n/a", "- n/a"}:
        return Attendance(None, None)
    gt = non = None
    for m in re.finditer(r"(\d[\d,]*)\s*(non[\s-]*gt|non[\s-]*georgia|gt|georgia tech)?", s):
        n = int(m.group(1).replace(",", ""))
        label = (m.group(2) or "").replace(" ", "").replace("-", "")
        if label.startswith("non"):
            non = n
        elif label and gt is None:
            gt = n
        elif not label and gt is None and non is None:
            gt = n  # bare number: treat as GT attendees
    return Attendance(gt, non)


# ---------------------------------------------------------------- yes / no

def parse_yes_no(text: object) -> bool | None:
    s = str(text or "").strip().lower().lstrip("-").strip()
    if s.startswith("yes"):
        return True
    if s.startswith("no"):
        return False
    return None
