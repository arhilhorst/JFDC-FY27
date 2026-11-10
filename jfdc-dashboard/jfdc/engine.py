"""Turns the raw recap responses + bills sheet into the dashboard's data model."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from . import policy
from .parsing import (
    clean_bill_number,
    map_columns,
    norm_rso,
    parse_attendance,
    parse_bill_numbers,
    parse_date,
    parse_datetime,
    parse_int,
    parse_event_date_text,
    parse_money,
)
from .sources import Table


def fiscal_year(d: date, start_month: int = 7) -> int:
    """FY is named by the year it ends: July 2026 - June 2027 is FY2027."""
    return d.year + 1 if d.month >= start_month else d.year


def fy_bounds(fy: int, start_month: int = 7) -> tuple[date, date]:
    start = date(fy - 1, start_month, 1)
    end = date(fy, start_month, 1) - timedelta(days=1)
    return start, end


def _get(row: list, cols: dict, field: str) -> Any:
    i = cols.get(field)
    if i is None or i >= len(row):
        return None
    v = row[i]
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _iso(d: date | datetime | None) -> str | None:
    return d.isoformat() if d else None


def load_recaps(table: Table, spec: dict) -> tuple[list[dict], dict]:
    cols = map_columns(table.headers, spec)
    recaps = []
    for n, row in enumerate(table.rows):
        rso = _get(row, cols, "rso")
        bills_raw = _get(row, cols, "bill_numbers")
        att = parse_attendance(_get(row, cols, "attendees"))
        proof = _get(row, cols, "proof")
        submitted = parse_datetime(_get(row, cols, "submitted_at"))
        all_text = " ".join(str(_get(row, cols, f) or "") for f in ("attendees", "proof", "summary")).lower()
        said_not_tracked = "not tracked" in all_text or "did not track" in all_text or "didn't track" in all_text
        recaps.append(
            {
                "id": str(_get(row, cols, "response_id") or n + 1),
                "submitted_at": submitted.isoformat(timespec="minutes") if submitted else None,
                "_submitted": submitted,
                "email": _get(row, cols, "email"),
                "name": _get(row, cols, "name"),
                "rso": (str(rso).strip() if rso else "(No RSO given)"),
                "rso_key": norm_rso(rso) or "(no rso)",
                "event_name": _get(row, cols, "event_name"),
                "bill_raw": None if bills_raw is None else str(bills_raw),
                "bill_numbers": parse_bill_numbers(bills_raw),
                "event_date_location": _get(row, cols, "event_date_location"),
                "attendance": att,
                "proof": proof,
                "has_proof": bool(proof and str(proof).strip().lower() not in ("n/a", "na", "none", "-")),
                "summary": _get(row, cols, "summary"),
                "attendance_tracked": att["tracked"] and not said_not_tracked,
                "matched_bills": [],
            }
        )
    return recaps, cols


def _expected(v: Any) -> int | None:
    if v is None or isinstance(v, (int, float)):
        return parse_int(v)
    a = parse_attendance(v)
    return a["total"] if a["total"] else None


def load_bills(table: Table, spec: dict, cfg: dict) -> tuple[list[dict], dict]:
    cols = map_columns(table.headers, spec)
    rules = cfg["rules"]
    statuses = [s.lower() for s in rules.get("statuses_requiring_recap", [])]
    cats = [c.lower() for c in rules.get("categories_requiring_recap", [])]
    exempt = [c.lower() for c in rules.get("categories_exempt_from_recap", [])]
    template = cfg.get("engage_url_template")
    policy_start = parse_date(rules.get("recap_policy_start"))
    bills = []
    for row in table.rows:
        num = clean_bill_number(_get(row, cols, "bill_number"))
        rso = _get(row, cols, "rso")
        if not num and not rso:
            continue
        status = _get(row, cols, "status")
        category = _get(row, cols, "category")
        requires = True
        reason = None
        if statuses and "status" in cols:
            requires = bool(status) and str(status).strip().lower() in statuses
            reason = None if requires else "not_funded"
        if requires and cats and "category" in cols:
            requires = bool(category) and str(category).strip().lower() in cats
        if requires and exempt and category and str(category).strip().lower() in exempt:
            requires = False
        sub_d = parse_date(_get(row, cols, "submitted_date"))
        if requires and policy_start and sub_d and sub_d < policy_start:
            requires, reason = False, "before_policy"
        engage_id = clean_bill_number(_get(row, cols, "engage_id")) or num
        bills.append(
            {
                "bill_number": num,
                "rso": str(rso).strip() if rso else "(No RSO given)",
                "rso_key": norm_rso(rso) or "(no rso)",
                "title": _get(row, cols, "title"),
                "event_date": parse_date(_get(row, cols, "event_date")),
                "submitted_date": parse_date(_get(row, cols, "submitted_date")),
                "status": status,
                "category": category,
                "amount_requested": parse_money(_get(row, cols, "amount_requested")),
                "amount_approved": parse_money(_get(row, cols, "amount_approved")),
                "expected_attendance": _expected(_get(row, cols, "expected_attendance")),
                "in_queue": str(_get(row, cols, "in_queue") or "").strip().lower() in ("yes", "y", "true", "1", "x"),
                "review_step": _get(row, cols, "review_step"),
                "says_recaps_submitted": _get(row, cols, "says_recaps"),
                "submitter": _get(row, cols, "submitter"),
                "engage_url": template.format(engage_id=engage_id, bill_number=num) if template and engage_id else None,
                "requires_recap": requires,
                "not_required_reason": reason,
            }
        )
    return bills, cols


def load_adjustments(table: Table) -> list[dict]:
    spec = {
        "rso": ["RSO", "Organization"],
        "bill_number": ["Bill Number", "Bill"],
        "action": ["Action"],
        "date": ["Date"],
        "reason": ["Reason", "Note", "Notes"],
    }
    cols = map_columns(table.headers, spec)
    out = []
    for row in table.rows:
        action = str(_get(row, cols, "action") or "").strip().lower()
        if action not in ("waive", "add"):
            continue
        out.append(
            {
                "rso": _get(row, cols, "rso"),
                "rso_key": norm_rso(_get(row, cols, "rso")),
                "bill_number": clean_bill_number(_get(row, cols, "bill_number")),
                "action": action,
                "date": parse_date(_get(row, cols, "date")),
                "reason": _get(row, cols, "reason") or "",
            }
        )
    return out


def build(recap_table: Table, bills_table: Table, adj_table: Table, cfg: dict, today: date, fy: int | None = None) -> dict:
    rules = cfg["rules"]
    deadline_days = int(rules.get("recap_deadline_days", 14))
    freeze_days = int(rules.get("second_strike_freeze_days", 30))
    fy_month = int(rules.get("fiscal_year_start_month", 7))
    low_ratio = float(rules.get("low_attendance_ratio", 0.5))
    current_fy = fiscal_year(today, fy_month)
    fy = fy or current_fy
    fy_start, fy_end = fy_bounds(fy, fy_month)

    recaps, recap_cols = load_recaps(recap_table, cfg["recap_columns"])
    bills, bill_cols = load_bills(bills_table, cfg["bill_columns"], cfg)
    adjustments = load_adjustments(adj_table)
    waived = {(a["bill_number"]): a for a in adjustments if a["action"] == "waive" and a["bill_number"]}

    by_bill: dict[str, list[dict]] = defaultdict(list)
    for r in recaps:
        for b in r["bill_numbers"]:
            by_bill[b].append(r)
    bill_nums = {b["bill_number"] for b in bills}
    flags: list[dict] = []

    # ---- per-bill recap status -------------------------------------------------
    for b in bills:
        matched = sorted(by_bill.get(b["bill_number"], []), key=lambda r: r["_submitted"] or datetime.max)
        for r in matched:
            r["matched_bills"].append(b["bill_number"])
            if r["rso_key"] != b["rso_key"]:
                # Same bill number = same RSO, even if the name was typed differently.
                r["typed_rso_key"] = r["rso_key"]
                r["rso_key"] = b["rso_key"]
        first = matched[0] if matched else None
        b["recap_ids"] = [r["id"] for r in matched]
        b["event_date_source"] = "bills sheet" if b["event_date"] else None
        if b["event_date"] is None and first:
            sub0 = first["_submitted"].date() if first["_submitted"] else None
            guess = parse_event_date_text(first["event_date_location"], sub0)
            if guess:
                b["event_date"], b["event_date_source"] = guess, "recap form"
        b["due_date"] = b["event_date"] + timedelta(days=deadline_days) if b["event_date"] else None
        b["flags"] = []
        status = None
        strike_date = None
        if not b["requires_recap"]:
            status = b["not_required_reason"] or "not_required"
        elif first:
            sub = first["_submitted"].date() if first["_submitted"] else None
            if not any(r["attendance_tracked"] and r["has_proof"] for r in matched):
                status, strike_date = "not_tracked", sub or today
            elif b["due_date"] is None:
                status = "submitted_no_date"
            elif sub and sub > b["due_date"]:
                status, strike_date = "late", b["due_date"] + timedelta(days=1)
            else:
                status = "on_time"
        elif b["event_date"] is None:
            status = "no_date"
            if b["submitted_date"]:
                b["days_since_submitted"] = (today - b["submitted_date"]).days
        elif b["event_date"] > today:
            status = "upcoming"
        elif today <= b["due_date"]:
            status = "pending"
        else:
            status, strike_date = "missing", b["due_date"] + timedelta(days=1)

        if strike_date and b["bill_number"] in waived:
            b["waiver"] = waived[b["bill_number"]]["reason"]
            b["original_status"] = status
            status, strike_date = "waived", None

        b["recap_status"] = status
        b["recap_status_label"] = policy.RECAP_STATUSES[status]["label"]
        b["recap_color"] = policy.RECAP_STATUSES[status]["color"]
        b["strike"] = bool(strike_date)
        b["strike_date"] = strike_date
        b["submitted_recap_at"] = first["submitted_at"] if first else None
        b["days_until_due"] = (b["due_date"] - today).days if b["due_date"] and status == "pending" else None
        b["days_overdue"] = (today - b["due_date"]).days if b["due_date"] and status == "missing" else None

        # Attendance vs. what the bill expected (misuse signal).
        totals = [r["attendance"]["total"] for r in matched if r["attendance"]["total"] is not None]
        b["actual_attendance"] = max(totals) if totals else None
        if b["actual_attendance"] is not None and b["expected_attendance"]:
            b["attendance_ratio"] = round(b["actual_attendance"] / b["expected_attendance"], 2)
            if b["attendance_ratio"] < low_ratio:
                b["flags"].append(
                    f"Only {b['actual_attendance']} of {b['expected_attendance']} expected attendees "
                    f"({int(b['attendance_ratio'] * 100)}%)"
                )
        else:
            b["attendance_ratio"] = None
        if b["actual_attendance"] and b["amount_approved"]:
            b["cost_per_attendee"] = round(b["amount_approved"] / b["actual_attendance"], 2)
        else:
            b["cost_per_attendee"] = None
        if len(matched) > 1:
            b["flags"].append(f"{len(matched)} recap forms submitted for this bill")
        if first and first.get("typed_rso_key", b["rso_key"]) != b["rso_key"]:
            b["flags"].append(f"Recap filed under a different RSO name: “{first['rso']}”")

    # ---- RSO said "yes, all recaps submitted" on a bill, but some are overdue ----
    rso_missing: dict[str, list[str]] = defaultdict(list)
    for b in bills:
        if b["recap_status"] == "missing":
            rso_missing[b["rso_key"]].append(b["bill_number"])
    for b in bills:
        says = str(b.get("says_recaps_submitted") or "").strip().lower()
        if says.startswith("yes") and b["rso_key"] in rso_missing:
            b["flags"].append("Answered “Yes” to “Have you submitted Post-Event Recap Forms for ALL events?” "
                              "on this bill, but these recaps are overdue: " + ", ".join(rso_missing[b["rso_key"]]))

    # ---- recaps that don't line up with a bill ---------------------------------
    for r in recaps:
        r["unmatched_numbers"] = [n for n in r["bill_numbers"] if n not in bill_nums]
        problems = []
        if not r["bill_numbers"]:
            problems.append("No bill/budget number could be read")
        elif bills and r["unmatched_numbers"]:
            problems.append("Bill number(s) not in the bills sheet: " + ", ".join(r["unmatched_numbers"]))
        if r["attendance"]["issue"]:
            problems.append(r["attendance"]["issue"])
        if not r["has_proof"]:
            problems.append("No proof of attendance")
        r["problems"] = problems
        if problems:
            flags.append({"type": "recap", "recap_id": r["id"], "rso": r["rso"], "rso_key": r["rso_key"], "problems": problems})
    for b in bills:
        if b["flags"]:
            flags.append({"type": "bill", "bill_number": b["bill_number"], "rso": b["rso"], "rso_key": b["rso_key"], "problems": b["flags"]})

    # ---- RSOs -------------------------------------------------------------------
    names: dict[str, Counter] = defaultdict(Counter)
    for b in bills:
        names[b["rso_key"]][b["rso"]] += 3  # bills sheet names win
    for r in recaps:
        names[r["rso_key"]][r["rso"]] += 1

    rsos = []
    for key, cnt in names.items():
        rb = [b for b in bills if b["rso_key"] == key]
        rr = [r for r in recaps if r["rso_key"] == key]
        strikes = []
        for b in rb:
            if b["strike"] and fy_start <= b["strike_date"] <= fy_end:
                recap_date = None
                if b["recap_status"] in ("late", "not_tracked") and b["submitted_recap_at"]:
                    recap_date = datetime.fromisoformat(b["submitted_recap_at"]).date()
                strikes.append(
                    {
                        "bill_number": b["bill_number"],
                        "title": b["title"],
                        "reason": b["recap_status_label"],
                        "date": b["strike_date"],
                        "resolved_on": recap_date,
                        "manual": False,
                    }
                )
        for a in adjustments:
            if a["action"] == "add" and a["rso_key"] == key:
                d = a["date"] or today
                if fy_start <= d <= fy_end:
                    strikes.append(
                        {"bill_number": a["bill_number"], "title": None, "reason": a["reason"] or "Strike added by JFC",
                         "date": d, "resolved_on": d, "manual": True}
                    )
        strikes.sort(key=lambda s: s["date"])
        for i, s in enumerate(strikes, 1):
            s["number"] = i
        level_n = min(len(strikes), 3)
        level = dict(policy.LEVELS[level_n])
        level["count"] = len(strikes)

        # Can JFC review this RSO's bills right now? (SAF Policy §9.5.2)
        outstanding = [b for b in rb if b["recap_status"] == "missing" and fy_start <= b["strike_date"] <= fy_end]
        elig = {"eligible": True, "reason": "Eligible for bill review.", "until": None}
        if level_n == 3:
            elig = {"eligible": False, "until": fy_end + timedelta(days=1),
                    "reason": f"Third strike: bills can't be reviewed and the account is frozen until the fiscal year ends ({fy_end:%b %d, %Y})."}
        elif level_n == 2:
            s2 = strikes[1]
            if s2["resolved_on"] is None:
                elig = {"eligible": False, "until": None,
                        "reason": f"Second strike: frozen until the recap for bill {s2['bill_number']} is submitted, then for 30 more days."}
            else:
                until = s2["resolved_on"] + timedelta(days=freeze_days)
                if today < until:
                    elig = {"eligible": False, "until": until,
                            "reason": f"Second strike: frozen for 30 days after the recap was submitted, until {until:%b %d, %Y}."}
        if elig["eligible"] and outstanding:
            nums = ", ".join(b["bill_number"] for b in outstanding)
            elig = {"eligible": False, "until": None,
                    "reason": f"Bills can't be reviewed until the overdue recap(s) are submitted: {nums}."}
        if level_n == 1 and elig["eligible"]:
            elig["reason"] = "First strike recorded (written warning). Recap is now in, so bills can be reviewed."

        needs = [b for b in rb if b["requires_recap"] and b["recap_status"] not in ("upcoming", "not_required", "no_date", "pending")]
        on_time = sum(1 for b in needs if b["recap_status"] in ("on_time", "submitted_no_date", "waived"))
        rsos.append(
            {
                "key": key,
                "name": cnt.most_common(1)[0][0],
                "aliases": sorted(set(cnt) - {cnt.most_common(1)[0][0]}),
                "level": level,
                "strikes": strikes,
                "eligibility": elig,
                "bill_count": len(rb),
                "recap_count": len(rr),
                "counts": dict(Counter(b["recap_status"] for b in rb)),
                "compliance_rate": round(on_time / len(needs), 2) if needs else None,
                "total_approved": round(sum(b["amount_approved"] or 0 for b in rb), 2),
                "last_recap_at": max((r["submitted_at"] for r in rr if r["submitted_at"]), default=None),
                "contacts": sorted({f"{r['name']} <{r['email']}>" for r in rr if r["email"]}),
                "bill_numbers": [b["bill_number"] for b in sorted(rb, key=lambda b: b["event_date"] or date.min, reverse=True)],
                "recap_ids": [r["id"] for r in sorted(rr, key=lambda r: r["submitted_at"] or "", reverse=True)],
            }
        )
    rsos.sort(key=lambda r: (-r["level"]["level"], r["name"].lower()))
    level_by_key = {r["key"]: r for r in rsos}
    for b in bills:
        r = level_by_key.get(b["rso_key"])
        b["rso_level"] = r["level"]["level"] if r else 0
        b["rso_eligible"] = r["eligibility"]["eligible"] if r else True

    def ser(x: Any) -> Any:
        if isinstance(x, (date, datetime)):
            return x.isoformat()
        if isinstance(x, dict):
            return {k: ser(v) for k, v in x.items() if not k.startswith("_")}
        if isinstance(x, list):
            return [ser(v) for v in x]
        return x

    missing_bill_fields = [f for f in cfg["bill_columns"] if not f.startswith("_") and f not in bill_cols]
    warnings = []
    for f in ("bill_numbers", "rso", "submitted_at", "attendees", "proof"):
        if f not in recap_cols:
            warnings.append(f"The recap form sheet has no column for '{f}'. If a question on the form was renamed, "
                            f"add its new wording under recap_columns.{f} in config.json.")
    if not recaps:
        warnings.append("No recap form responses were found. Check that recap_source points at the Forms export.")
    if bills_table.headers:
        for f in ("bill_number", "rso"):
            if f not in bill_cols:
                warnings.append(f"The bills sheet has no column for '{f}'. Add its header name under bill_columns.{f} in config.json.")
    return ser(
        {
            "today": today,
            "fiscal_year": fy,
            "current_fiscal_year": current_fy,
            "fiscal_year_range": [fy_start, fy_end],
            "levels": policy.LEVELS,
            "recap_statuses": policy.RECAP_STATUSES,
            "citations": policy.CITATIONS,
            "bills": sorted(bills, key=lambda b: (b["event_date"] or date.min, b["bill_number"]), reverse=True),
            "rsos": rsos,
            "recaps": sorted(recaps, key=lambda r: r["submitted_at"] or "", reverse=True),
            "flags": flags,
            "warnings": warnings,
            "columns": {
                "bills_mapped": {k: bills_table.headers[v] for k, v in bill_cols.items()},
                "bills_unmapped": missing_bill_fields,
                "recaps_mapped": {k: recap_table.headers[v][:60] for k, v in recap_cols.items()},
            },
        }
    )
