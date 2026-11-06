"""SAF Policy §9.5.1: requirements and per-bill recap status."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pandas as pd

from ..ledger import LedgerState

# Status vocabulary (docs/ARCHITECTURE.md Stage 4b)
UPCOMING, DUE, COMPLIANT, LATE, OVERDUE = "UPCOMING", "DUE", "COMPLIANT", "LATE", "OVERDUE"
INCOMPLETE, NOT_TRACKED, NEEDS_REVIEW, EXEMPT, NO_EVENT_DATE = (
    "INCOMPLETE", "NOT_TRACKED", "NEEDS_REVIEW", "EXEMPT", "NO_EVENT_DATE")
ENFORCED, COMPLETENESS = "ENFORCED", "COMPLETENESS"
STRIKE_STATUSES = {LATE, OVERDUE, NOT_TRACKED, INCOMPLETE}  # INCOMPLETE = judgment call (C7)

RULE_ID = {
    LATE: "R-9.5.1-LATE", OVERDUE: "R-9.5.1-OVERDUE", INCOMPLETE: "R-9.5.1-INCOMPLETE",
    NOT_TRACKED: "R-9.5.2-NOT-TRACKED", NEEDS_REVIEW: "R-9.5-MATCH-REVIEW", NO_EVENT_DATE: "R-9.5-NO-EVENT-DATE",
}


def is_false(v) -> bool:
    """True only for an explicit "No" (None / NaN = unknown)."""
    return v is not None and not (isinstance(v, float) and pd.isna(v)) and not bool(v)


def is_event_bill(row) -> bool:
    if row.get("is_event") is not None and not pd.isna(row.get("is_event")):
        return bool(row["is_event"])
    return bool(row.get("has_event_section"))


def build_requirements(bills: pd.DataFrame, recaps: pd.DataFrame, links: pd.DataFrame, ledger: LedgerState,
                       policy: dict, scope: dict, as_of: datetime, fy_start: date) -> pd.DataFrame:
    due_days = policy["recap"]["due_days"]
    funded = set(policy["statuses"]["funded"])
    rec_by_id = recaps.set_index("recap_id") if len(recaps) else pd.DataFrame()
    eff = links[links["state"].isin(["auto", "confirmed"])]
    pending = links[links["state"] == "needs_review"]

    in_scope = bills[bills["process"].isin(scope["bill_processes"])]
    in_scope = in_scope[~(in_scope["first_submitted"] > pd.Timestamp(as_of))]  # not yet submitted as of this run
    earliest_plausible = fy_start - timedelta(days=60)
    rows = []
    for b in in_scope.to_dict("records"):
        if not is_event_bill(b):
            continue  # §9.5.1 applies to funding "for an event"
        bid = b["bill_id"]
        linked = eff.loc[eff["bill_id"] == bid, "recap_id"].tolist()
        linked_recaps = rec_by_id.loc[[r for r in linked if r in rec_by_id.index]] if linked else pd.DataFrame()
        first = linked_recaps.sort_values("submitted_at").iloc[0] if len(linked_recaps) else None

        # ---- enforcement class (Chair decision C2)
        funds_unused = bid in ledger.funds_not_used or (
            first is not None and is_false(first.get("funds_used")))
        is_funded = b["status"] in funded and (b["adjusted_c"] or 0) > 0
        klass = ENFORCED if (is_funded and not funds_unused) else COMPLETENESS
        class_note = ("funds not used" if funds_unused else
                      "" if is_funded else f"not approved ({b['status']})")

        # ---- event date (C3: last day; C8: bill details win)
        ev, ev_src = None, ""
        if bid in ledger.event_date_overrides:
            ev, ev_src = date.fromisoformat(ledger.event_date_overrides[bid]), "reviewer override"
        elif b.get("event_last_date") is not None and not pd.isna(b.get("event_last_date")):
            ev, ev_src = b["event_last_date"], "bill details"
            amb = b.get("event_date_ambiguous")
            if amb is not None and not (isinstance(amb, float) and pd.isna(amb)) and bool(amb):
                ev_src = "bill details (ambiguous)"
        elif first is not None and first["event_last_date"] is not None:
            ev, ev_src = first["event_last_date"], "recap (bill details missing)"

        today = as_of.date()
        implausible = None
        if ev is not None and ev_src != "reviewer override":
            # An event can't be long before the FY, or after its own recap was filed.
            upper = first["submitted_at"].date() + timedelta(days=1) if first is not None else today + timedelta(days=365)
            if not earliest_plausible <= ev <= upper:
                implausible, ev = ev, None  # typo like 09/24/2006: never strike on it (principle 1)

        due = ev + timedelta(days=due_days) if ev else None
        deadline = datetime.combine(due, time(23, 59, 59)) if due else None

        status, days_left, days_over, notes = None, None, None, []
        if bid in ledger.exemptions:
            status = EXEMPT
            notes.append(ledger.exemptions[bid].get("reason", ""))
        elif first is None and (pending["bill_id"] == bid).any():
            status = NEEDS_REVIEW
            notes.append("; ".join(pending.loc[pending["bill_id"] == bid, "note"]))
        elif ev is not None and first is None and ev_src == "bill details (ambiguous)" and ev < today:
            status = NEEDS_REVIEW  # e.g. "11/7-8/2026 with Backup: 11/14-15/2026"
            notes.append(f"Ambiguous event date {b.get('event_date_text')!r}; using last date {ev} only after review. "
                         f"Fix with: jfdc decide event_date_override bill_id={bid} event_date=YYYY-MM-DD")
        elif implausible is not None:
            status = NEEDS_REVIEW
            notes.append(f"Event date {implausible} from {ev_src} is implausible (typo?). "
                         f"Fix with: jfdc decide event_date_override bill_id={bid} event_date=YYYY-MM-DD")
        elif ev is None:
            status = NO_EVENT_DATE
            notes.append("No event date: need bill details (PDF/scraper) or a recap")
        elif first is not None:
            sub = first["submitted_at"].to_pydatetime()
            if sub > deadline:
                status, days_over = LATE, (sub.date() - due).days
            elif missing := [m for m in first["missing_items"] if not (
                    m == "bill/budget number" and ((eff["recap_id"] == first.name) & (eff["bill_id"] == bid)
                                                   & (eff["state"] == "confirmed")).any())]:
                status = INCOMPLETE  # (a reviewer-confirmed link resolves a missing bill number)
                notes.append("Missing: " + ", ".join(missing))
            elif is_false(first.get("attendance_tracked")):
                status = NOT_TRACKED
            else:
                status = COMPLIANT
        elif ev >= today:
            status = UPCOMING
        elif as_of <= deadline:
            status, days_left = DUE, (due - today).days
        else:
            status, days_over = OVERDUE, (today - due).days

        rows.append({
            "bill_id": bid, "rso": b["rso"], "title": b["title"], "process": b["process"],
            "engage_status": b["status"], "adjusted_c": b["adjusted_c"],
            "submitter_name": b["submitter_name"], "submitter_email": b["submitter_email"],
            "class": klass, "class_note": class_note,
            "event_date": ev, "event_date_source": ev_src, "due_date": due,
            "status": status, "days_left": days_left, "days_overdue": days_over,
            "recap_id": first.name if first is not None else None,
            "recap_submitted_at": first["submitted_at"] if first is not None else None,
            "recap_ids": ", ".join(linked),
            "rule_id": RULE_ID.get(status, ""),
            "notes": "; ".join(n for n in notes if n),
        })
    return pd.DataFrame(rows)
