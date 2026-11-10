"""Strike appeals (docs/APPEALS.md).

An RSO that believes it was flagged by mistake files the Appeal Form. Every appeal is reviewed by hand;
the engine only matches it to the strike, works out the 30-day window, lists what to check, and drafts
the emails. An admin records `appeal_grant` (removes the strike) or `appeal_deny`. An open appeal never
pauses the strike's consequence (Chair decision).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from ..ledger import LedgerState
from ..textnorm import org_key

OPEN, GRANTED, DENIED = "OPEN", "GRANTED", "DENIED"
APPEAL_VIEW_COLUMNS = [
    "appeal_id", "bill_id", "status", "submitted_at", "rso", "bill_rso", "appellant_name", "appellant_email",
    "reason", "explanation", "evidence", "strike_state", "strike_ordinal", "strike_notice_sent_at",
    "appeal_deadline", "timely", "checks", "decided_by", "decision_reason", "decided_at", "action",
]


def first_strike_notice(already_sent: list[dict]) -> dict[str, datetime]:
    """bill_id -> when its FIRST strike email was sent (the appeal window starts there)."""
    out: dict[str, datetime] = {}
    for n in already_sent:
        kind = n.get("notice", "")
        if kind.startswith("STRIKE_") and kind[-1].isdigit() and n.get("sent_at"):
            t = datetime.fromisoformat(n["sent_at"])
            if n["bill_id"] not in out or t < out[n["bill_id"]]:
                out[n["bill_id"]] = t
    return out


def build_appeals(appeals: pd.DataFrame | None, strikes: pd.DataFrame, bills: pd.DataFrame,
                  already_sent: list[dict], ledger: LedgerState, policy: dict) -> pd.DataFrame:
    if appeals is None or not len(appeals):
        return pd.DataFrame(columns=APPEAL_VIEW_COLUMNS)
    window = int(policy.get("appeals", {}).get("window_days", 30))
    notice_at = first_strike_notice(already_sent)
    stk = strikes.set_index("bill_id") if len(strikes) else pd.DataFrame()
    bill_rso = dict(zip(bills["bill_id"], bills["rso"], strict=True)) if len(bills) else {}

    rows = []
    for a in appeals.to_dict("records"):
        aid, bid = a["appeal_id"], a["bill_id"]
        checks = []
        s = stk.loc[bid] if bid and bid in stk.index else None
        if isinstance(s, pd.DataFrame):
            s = s.iloc[0]
        if not bid:
            checks.append("No 6-digit bill number on the appeal: find the bill and contact the appellant")
        elif bid not in bill_rso:
            checks.append(f"Bill {bid} is not in the Engage export (typo?)")
        elif s is None:
            checks.append("No strike (proposed or confirmed) on this bill")
        elif s["state"] == "proposed":
            checks.append("Strike is only PROPOSED: deciding the strike itself may settle this appeal")
        elif s["state"] in ("removed", "waived") and not s.get("via_appeal"):
            checks.append(f"Strike already {s['state']}")
        if bid in bill_rso and a["rso"] and org_key(a["rso"]) != org_key(bill_rso[bid]):
            checks.append(f"Appeal names RSO {a['rso']!r}, but the bill belongs to {bill_rso[bid]!r}")

        sent_at = notice_at.get(bid)
        deadline = (sent_at + timedelta(days=window)).date() if sent_at else None
        filed = pd.Timestamp(a["submitted_at"]).to_pydatetime()
        timely = deadline is None or filed.date() <= deadline
        if not timely:
            checks.append(f"Filed {(filed.date() - deadline).days} day(s) after the {window}-day window "
                          f"(deadline {deadline}); listed for review anyway")
        if deadline is None and s is not None and s["state"] == "confirmed":
            checks.append("Strike email not marked sent yet, so the window hasn't started")

        d = ledger.appeal_decisions.get((aid, bid))
        status = {"appeal_grant": GRANTED, "appeal_deny": DENIED}.get(d["type"]) if d else OPEN
        if d and d["type"] == "appeal_grant" and not d.get("strike_removed"):
            checks.append("Granted, but there was no confirmed strike to remove at the time")

        action = "" if d else (
            f"jfdc decide appeal_grant appeal_id={aid} bill_id={bid or '<ID>'} --reason '...' --actor <admin>  |  "
            f"jfdc decide appeal_deny appeal_id={aid} bill_id={bid or '<ID>'} --reason '...' --actor <admin>")
        rows.append({
            "appeal_id": aid, "bill_id": bid, "status": status, "submitted_at": filed,
            "rso": a["rso"], "bill_rso": bill_rso.get(bid, ""),
            "appellant_name": a["appellant_name"], "appellant_email": a["appellant_email"],
            "reason": a["reason"], "explanation": a["explanation"], "evidence": a.get("evidence", ""),
            "strike_state": s["state"] if s is not None else "", "strike_ordinal": s["ordinal"] if s is not None else None,
            "strike_notice_sent_at": sent_at, "appeal_deadline": deadline, "timely": timely,
            "checks": "; ".join(checks), "decided_by": (d or {}).get("actor", ""),
            "decision_reason": (d or {}).get("reason", ""), "decided_at": (d or {}).get("at", ""), "action": action,
        })
    out = pd.DataFrame(rows, columns=APPEAL_VIEW_COLUMNS)
    order = {OPEN: 0, GRANTED: 1, DENIED: 1}
    return out.sort_values(by=["status", "submitted_at"], key=lambda c: c.map(order) if c.name == "status" else c,
                           ignore_index=True)
