"""SAF Policy §9.5.2: strikes, consequences, RSO standing.

Strikes are PROPOSED by the engine and only count once a confirmer signs off (C6).
One strike per bill (B4); RSOs may walk back same-event duplicates via strike_remove.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from ..fiscal import fiscal_year, fy_bounds
from ..ledger import LedgerState
from .recap_rule import ENFORCED, INCOMPLETE, STRIKE_STATUSES

STANDING_GOOD = "GOOD"


BASIS_MISSING = "BASIS_MISSING"


def build_strikes(req: pd.DataFrame, ledger: LedgerState, policy: dict, as_of: datetime,
                  bills: pd.DataFrame | None = None) -> pd.DataFrame:
    freeze_days = policy["strikes"]["strike2_freeze_days_after_submission"]
    fy_m, fy_d = policy["fiscal_year"]["start_month"], policy["fiscal_year"]["start_day"]
    rows = []
    eligible = req[(req["class"] == ENFORCED) & req["status"].isin(STRIKE_STATUSES)] if len(req) else req
    seen = set()
    for r in eligible.to_dict("records"):
        seen.add(r["bill_id"])
        rows.append(_strike_row(r, ledger, supported=True))
    # Confirmed strikes whose basis disappeared (recap linked later, funds not used...) -> propose removal.
    # A confirmed strike is NEVER dropped: it stays counted until a confirmer records strike_remove.
    for bid, d in ledger.strike_decisions.items():
        if bid in seen or d["type"] != "strike_confirm":
            continue
        match = req[req["bill_id"] == bid] if len(req) else req
        if len(match):
            rows.append(_strike_row(match.iloc[0].to_dict(), ledger, supported=False))
        else:  # bill no longer evaluated at all (non-event now, missing from export, out of scope)
            rows.append(_basis_missing_row(bid, d, bills, policy["recap"]["due_days"]))
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["bill_id", "rso", "fy", "state", "ordinal", "consequence", "active_until",
                                     "supported"])

    # C5: FY of the event (or of the confirmation, when the event date is no longer known)
    df["fy"] = [fiscal_year(e if e is not None and not pd.isna(e) else fb, fy_m, fy_d)
                for e, fb in zip(df["event_date"], df["fy_fallback_date"], strict=True)]
    df = df.drop(columns="fy_fallback_date")
    df["ordinal"] = None
    # Number in CONFIRMATION order, so confirming an older violation later never renumbers strikes that
    # were already noticed. Ties (one import confirming several) go by violation date.
    counted = df[df["state"] == "confirmed"].sort_values(["confirmed_seq", "violation_date", "bill_id"])
    for (_rso, _fy), grp in counted.groupby(["rso", "fy"], sort=False):
        for n, idx in enumerate(grp.index, start=1):
            df.at[idx, "ordinal"] = n

    today = as_of.date()
    cons, until, active = [], [], []
    for r in df.to_dict("records"):
        c, u, a = consequence(r["ordinal"], r["recap_submitted_at"], r["fy"], today, freeze_days, fy_m, fy_d)
        cons.append(c), until.append(u), active.append(a)
    df["consequence"], df["active_until"], df["active"] = cons, until, active
    return df.sort_values(["rso", "violation_date"]).reset_index(drop=True)


def _strike_row(r: dict, ledger: LedgerState, supported: bool) -> dict:
    d = ledger.strike_decisions.get(r["bill_id"])
    state = {"strike_confirm": "confirmed", "strike_waive": "waived", "strike_remove": "removed"}.get(
        d["type"] if d else "", "proposed")
    note = ""
    if r["status"] == INCOMPLETE:
        note = "Judgment call: recap incomplete (C7). " + (r.get("notes") or "")
    if not supported:
        note = f"REMOVAL PROPOSED: bill is now {r['status']} / {r['class']} ({r.get('class_note') or ''}). " \
               "Stays counted until a confirmer records strike_remove."
    return {
        "bill_id": r["bill_id"], "rso": r["rso"], "title": r["title"], "status": r["status"],
        "event_date": r["event_date"], "due_date": r["due_date"],
        "violation_date": r["due_date"] + timedelta(days=1) if r["due_date"] else None,
        "days_overdue": r.get("days_overdue"), "recap_submitted_at": r.get("recap_submitted_at"),
        "submitter_email": r["submitter_email"], "state": state,
        "decided_by": (d or {}).get("confirmed_by", ""), "decision_reason": (d or {}).get("reason", ""),
        "supported": supported, "note": note.strip(),
        "confirmed_seq": d["_seq"] if d else None, "fy_fallback_date": _as_date((d or {}).get("at")),
    }


def _as_date(v) -> date | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, date):
        return v.date() if isinstance(v, datetime) else v
    try:
        return date.fromisoformat(str(v).strip()[:10])
    except ValueError:
        return None


def _basis_missing_row(bid: str, d: dict, bills: pd.DataFrame | None, due_days: int) -> dict:
    """A confirmed strike on a bill the engine no longer evaluates. Kept (and counted) for review."""
    b = {}
    if bills is not None and len(bills):
        hit = bills[bills["bill_id"] == bid]
        b = hit.iloc[0].to_dict() if len(hit) else {}
    event = _as_date(d.get("event_date")) or _as_date(b.get("event_last_date"))
    due = _as_date(d.get("due_date")) or (event + timedelta(days=due_days) if event else None)
    why = ("still in the Engage export but no longer an in-scope event bill" if b.get("in_latest_export", True)
           else "missing from the latest Engage export") if b else "never seen in any Engage export"
    return {
        "bill_id": bid, "rso": d.get("rso") or b.get("rso") or "(unknown RSO)",
        "title": d.get("title") or b.get("title") or "", "status": BASIS_MISSING,
        "event_date": event, "due_date": due,
        "violation_date": due + timedelta(days=1) if due else _as_date(d.get("at")),
        "days_overdue": None, "recap_submitted_at": None, "submitter_email": b.get("submitter_email") or "",
        "state": "confirmed", "decided_by": d.get("confirmed_by", ""), "decision_reason": d.get("reason", ""),
        "supported": False,
        "note": f"BASIS MISSING: confirmed strike on a bill {why}. Stays counted until a confirmer records "
                "strike_remove (or the bill reappears).",
        "confirmed_seq": d["_seq"], "fy_fallback_date": _as_date(d.get("at")),
    }


def consequence(ordinal, submitted_at, fy: int, today: date, freeze_days: int, fy_m: int, fy_d: int):
    """(text, active_until, active_now) for a confirmed strike number."""
    if ordinal is None:
        return "", None, False
    sub = submitted_at.date() if submitted_at is not None and not pd.isna(submitted_at) else None
    if ordinal == 1:
        return ("Written warning; ineligible for Supplemental Bills review until the form is submitted",
                sub, sub is None)
    if ordinal == 2:
        until = sub + timedelta(days=freeze_days) if sub else None
        return (f"Ineligible; SGA allocation account frozen until form submitted + {freeze_days} days",
                until, until is None or today <= until)
    end = fy_bounds(fy, fy_m, fy_d)[1]
    return ("Ineligible; SGA allocation account frozen for the rest of the fiscal year", end, today <= end)


def rso_standing(strikes: pd.DataFrame, req: pd.DataFrame, current_fy: int) -> pd.DataFrame:
    # Include RSOs that only appear through a BASIS_MISSING strike.
    rsos = sorted((set(req["rso"]) if len(req) else set()) | (set(strikes["rso"]) if len(strikes) else set()))
    rows = []
    for rso in rsos:
        s = strikes[(strikes["rso"] == rso) & (strikes["fy"] == current_fy)] if len(strikes) else strikes
        conf = s[s["state"] == "confirmed"] if len(s) else s
        act = conf[conf["active"].astype(bool)] if len(conf) else conf
        worst = int(act["ordinal"].max()) if len(act) else 0
        if worst == 0:
            standing = STANDING_GOOD
        elif worst == 1:
            standing = "STRIKE 1: SUPP-INELIGIBLE"
        elif worst == 2:
            u = act.loc[act["ordinal"] == 2, "active_until"].iloc[0]
            standing = f"STRIKE 2: FROZEN until {u}" if u else "STRIKE 2: FROZEN (form not yet submitted)"
        else:
            standing = "STRIKE 3: FROZEN rest of FY"
        r = req[req["rso"] == rso] if len(req) else pd.DataFrame(columns=["status", "days_overdue", "class",
                                                                          "adjusted_c"])
        rows.append({
            "rso": rso, "standing": standing,
            "confirmed_strikes": len(conf), "proposed_strikes": int((s["state"] == "proposed").sum()) if len(s) else 0,
            "overdue": int((r["status"] == "OVERDUE").sum()), "late": int((r["status"] == "LATE").sum()),
            "due": int((r["status"] == "DUE").sum()), "compliant": int((r["status"] == "COMPLIANT").sum()),
            "needs_review": int((r["status"] == "NEEDS_REVIEW").sum()),
            "unverified_no_event_date": int((r["status"] == "NO_EVENT_DATE").sum()),
            "max_days_overdue": int(r["days_overdue"].max()) if r["days_overdue"].notna().any() else None,
            "dollars_at_issue_c": int(r.loc[r["status"].isin(["OVERDUE", "LATE"]) & (r["class"] == ENFORCED), "adjusted_c"].sum()),
        })
    return pd.DataFrame(rows)
