"""Stage 3: link recaps to bills (charter matching rules 1-3; SAF §9.5.3).

Tier 1  exact 6-digit Engage Id, same RSO          -> auto link
Tier 1x exact Id but a DIFFERENT RSO (joint event?)  -> needs_review
Tier 2  no usable number: same RSO, event date within +/-N days -> needs_review (never auto-credited)
Budget  5-digit budget IDs                           -> budget_ref (resolved once the JFC budget-event tab is a source)
Ledger link_confirm / link_reject always win.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from .consolidate import RsoRegistry
from .ledger import LedgerState

LINK_COLUMNS = ["recap_id", "bill_id", "method", "state", "note"]


def resolve_recap_rsos(recaps: pd.DataFrame, rsos: RsoRegistry, min_score: int, review: list[dict]) -> pd.DataFrame:
    r = recaps.copy()
    r["rso_canonical"] = r["rso"].map(rsos.resolve)
    for raw in r.loc[r["rso_canonical"].isna(), "rso"].unique():
        sug = rsos.suggest(raw, min_score)
        review.append({
            "kind": "RSO_ALIAS",
            "detail": f"Recap RSO {raw!r} is not an Engage org name"
                      + (f"; did you mean {sug[0]!r} ({sug[1]}%)?" if sug else "; no close match."),
            "action": f"jfdc decide alias_add alias={raw!r} rso={sug[0]!r}" if sug else "",
        })
    return r


def link_recaps(recaps: pd.DataFrame, bills: pd.DataFrame, ledger: LedgerState, window_days: int) -> pd.DataFrame:
    by_id = bills.set_index("bill_id")
    links: list[dict] = []
    for rec in recaps.to_dict("records"):
        rid, rso = rec["recap_id"], rec.get("rso_canonical")
        for tok in rec["engage_refs"]:
            if tok not in by_id.index:
                links.append(dict(recap_id=rid, bill_id=tok, method="exact", state="needs_review",
                                  note="Bill number not in the Engage export (typo, or export older than the recap?)"))
            elif rso and by_id.at[tok, "rso"] == rso:
                links.append(dict(recap_id=rid, bill_id=tok, method="exact", state="auto", note=""))
            else:
                links.append(dict(recap_id=rid, bill_id=tok, method="exact", state="needs_review",
                                  note=f"Bill belongs to {by_id.at[tok, 'rso']!r}, recap filed by {rec['rso']!r} "
                                       "(joint event? each RSO must file its own recap, §9.5.3)"))
        for tok in rec["budget_refs"]:
            links.append(dict(recap_id=rid, bill_id=tok, method="budget_ref", state="budget_ref",
                              note="5-digit budget ID - needs the JFC data sheet budget tab (open item B2)"))
        if not rec["engage_refs"] and not rec["budget_refs"]:
            d = rec.get("event_last_date")
            cands = pd.DataFrame()
            if rso and d is not None and "event_last_date" in bills:
                same = bills[(bills["rso"] == rso) & bills["event_last_date"].notna()]
                lo, hi = d - timedelta(days=window_days), d + timedelta(days=window_days)
                cands = same[same["event_last_date"].map(lambda x, lo=lo, hi=hi: lo <= x <= hi)]
            if len(cands):
                for bid in cands["bill_id"]:
                    links.append(dict(recap_id=rid, bill_id=bid, method="fallback", state="needs_review",
                                      note=f"No bill number on recap; same RSO, event date within {window_days} days"))
            else:
                links.append(dict(recap_id=rid, bill_id="", method="none", state="orphan",
                                  note="No bill number and no candidate bill (same RSO, nearby event date)"))

    df = pd.DataFrame(links, columns=LINK_COLUMNS)
    # Ledger decisions override, and confirmed links not produced above are added.
    if len(df):
        key = list(zip(df["recap_id"], df["bill_id"], strict=True))
        df.loc[[k in ledger.link_confirmed for k in key], "state"] = "confirmed"
        df.loc[[k in ledger.link_rejected for k in key], "state"] = "rejected"
    existing = set(zip(df["recap_id"], df["bill_id"], strict=True)) if len(df) else set()
    extra = [dict(recap_id=r, bill_id=b, method="manual", state="confirmed", note="Linked by reviewer")
             for r, b in ledger.link_confirmed if (r, b) not in existing]
    if extra:
        df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)
    return df


def effective_links(links: pd.DataFrame) -> pd.DataFrame:
    return links[links["state"].isin(["auto", "confirmed"])]
