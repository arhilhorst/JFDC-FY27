"""Fiscal-year helpers. FY27 = July 1 2026 - June 30 2027."""

from __future__ import annotations

from datetime import date, timedelta


def fiscal_year(d: date, start_month: int = 7, start_day: int = 1) -> int:
    """Two-digit FY number for a date (an FY is named for the year it ENDS in)."""
    end_year = d.year + 1 if (d.month, d.day) >= (start_month, start_day) else d.year
    return end_year % 100


def fy_bounds(fy: int, start_month: int = 7, start_day: int = 1) -> tuple[date, date]:
    """First and last day of a fiscal year."""
    end_year = 2000 + fy
    start = date(end_year - 1, start_month, start_day)
    return start, date(end_year, start_month, start_day) - timedelta(days=1)
