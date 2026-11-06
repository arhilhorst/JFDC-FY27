"""Secondary flags. Each cites its policy section; none of them create strikes."""

from __future__ import annotations

from datetime import datetime, time

import pandas as pd

from .recap_rule import ENFORCED, is_false


def _flag(rule, severity, rso, bill_id, message):
    return {"rule_id": rule, "severity": severity, "rso": rso, "bill_id": bill_id, "message": message}


def build_flags(bills: pd.DataFrame, req: pd.DataFrame, recaps: pd.DataFrame, links: pd.DataFrame,
                policy: dict, scope: dict) -> pd.DataFrame:
    out: list[dict] = []
    fcfg = policy.get("flags", {})
    funded = set(policy["statuses"]["funded"])
    fy_bills = bills[bills["process"].isin(scope["bill_processes"])]

    # §9.6 Bills Cap
    cap = fcfg.get("bills_cap", {})
    if cap.get("enabled"):
        tot = fy_bills[fy_bills["status"].isin(funded)].groupby("rso")["adjusted_c"].sum()
        for rso, c in tot[tot > cap["cents"]].items():
            out.append(_flag("R-9.6-BILLS-CAP", "high", rso, "",
                             f"Approved bills total ${c/100:,.2f} > ${cap['cents']/100:,.0f} cap"))

    # §9.5.3 multi-bill events (B4: flag, strikes still per bill)
    eff = links[links["state"].isin(["auto", "confirmed"])]
    flagged_sets = set()
    for rid, grp in eff.groupby("recap_id"):
        if len(grp) > 1:
            flagged_sets.add(frozenset(grp["bill_id"]))
            rso = req.loc[req["bill_id"].isin(grp["bill_id"]), "rso"]
            out.append(_flag("R-9.5.3-MULTI-BILL", "info", rso.iloc[0] if len(rso) else "", ", ".join(grp["bill_id"]),
                             f"One recap ({rid}) covers {len(grp)} bills"))
    if len(req) and req["event_date"].notna().any():
        g = req[req["event_date"].notna()].groupby(["rso", "event_date"])["bill_id"].apply(list)
        for (rso, d), ids in g.items():
            if len(ids) > 1 and not any(frozenset(ids) <= f for f in flagged_sets):
                out.append(_flag("R-9.5.3-MULTI-BILL", "info", rso, ", ".join(ids),
                                 f"{len(ids)} bills share event date {d}; strikes are per bill and can be walked back"))

    # Event date on the bill vs the recap
    if len(req) and len(recaps):
        rec = recaps.set_index("recap_id")
        for r in req[req["recap_id"].notna() & (req["event_date_source"] == "bill details")].to_dict("records"):
            rd = rec.at[r["recap_id"], "event_last_date"] if r["recap_id"] in rec.index else None
            if rd and r["event_date"] and abs((rd - r["event_date"]).days) > 1:
                out.append(_flag("R-9.5.1-DATE-MISMATCH", "warn", r["rso"], r["bill_id"],
                                 f"Bill says event {r['event_date']}, recap says {rd} (clock uses the bill)"))

    # Attestation on the bill ("submitted ALL recaps?") vs reality at submit time
    if fcfg.get("attestation", {}).get("enabled") and "attestation_all_recaps" in bills and len(req):
        enf = req[(req["class"] == ENFORCED) & req["due_date"].notna()]
        for b in fy_bills[fy_bills["attestation_all_recaps"] == True].to_dict("records"):  # noqa: E712
            t = b["first_submitted"]
            if pd.isna(t):
                continue
            mine = enf[enf["rso"] == b["rso"]]
            late_then = mine[mine["due_date"].map(lambda d, t=t: datetime.combine(d, time(23, 59, 59)) < t)
                             & (mine["recap_submitted_at"].isna() | (mine["recap_submitted_at"] > t))]
            if len(late_then):
                out.append(_flag("R-9.5-ATTESTATION", "high", b["rso"], b["bill_id"],
                                 f"Answered 'Yes, all recaps submitted' on {t:%m/%d} while bill(s) "
                                 f"{', '.join(late_then['bill_id'])} had overdue recaps"))

    # Recaps that say funds were NOT used on an approved bill (strike removal path, C2)
    if len(recaps) and "funds_used" in recaps:
        for r in recaps[recaps["funds_used"].map(is_false)].to_dict("records"):
            out.append(_flag("R-9.5-FUNDS-NOT-USED", "info", r.get("rso_canonical") or r["rso"],
                             ", ".join(r["engage_refs"]), "Recap reports funds were not used: no strike applies"))

    return pd.DataFrame(out, columns=["rule_id", "severity", "rso", "bill_id", "message"])
