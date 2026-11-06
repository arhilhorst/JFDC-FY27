"""Stage 2: consolidate uploads into the current Bill table, bill history, RSO registry, recaps."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
from rapidfuzz import fuzz, process

from .ledger import LedgerState
from .textnorm import org_key, squash


@dataclass
class RsoRegistry:
    by_key: dict[str, str]  # org_key -> canonical name

    @classmethod
    def build(cls, names: list[str], ledger: LedgerState) -> RsoRegistry:
        by_key: dict[str, str] = {}
        for n in names:
            if n and org_key(n):
                by_key.setdefault(org_key(n), n)
        for alias_key, canonical in ledger.aliases.items():
            by_key[alias_key] = canonical
        return cls(by_key)

    def resolve(self, raw: str) -> str | None:
        return self.by_key.get(org_key(raw))

    def suggest(self, raw: str, min_score: int) -> tuple[str, int] | None:
        if not self.by_key:
            return None
        hit = process.extractOne(org_key(raw), list(self.by_key), scorer=fuzz.token_sort_ratio)
        if hit and hit[1] >= min_score:
            return self.by_key[hit[0]], int(hit[1])
        return None


@dataclass
class Consolidated:
    bills: pd.DataFrame  # every bill in the latest export (all processes) + details
    history: pd.DataFrame  # status / amount changes across Engage snapshots
    rsos: RsoRegistry
    recaps: pd.DataFrame
    review: list[dict] = field(default_factory=list)  # alias suggestions, unmatched PDFs ...


def bill_history(snapshots: list[tuple[datetime, pd.DataFrame]]) -> pd.DataFrame:
    """Diff consecutive Engage snapshots. Engage keeps no request history; this rebuilds it."""
    rows = []
    prev: pd.DataFrame | None = None
    for as_of, bills in snapshots:
        cur = bills.set_index("bill_id")[["status", "step", "adjusted_c"]]
        if prev is not None:
            common = cur.index.intersection(prev.index)
            for col in ("status", "step", "adjusted_c"):
                a, b = prev.loc[common, col].astype(str), cur.loc[common, col].astype(str)
                for bid in common[a.values != b.values]:
                    rows.append({"bill_id": bid, "field": col, "old": a[bid], "new": b[bid], "seen_as_of": as_of})
            for bid in cur.index.difference(prev.index):
                rows.append({"bill_id": bid, "field": "created", "old": "", "new": cur.at[bid, "status"], "seen_as_of": as_of})
        prev = cur
    return pd.DataFrame(rows, columns=["bill_id", "field", "old", "new", "seen_as_of"])


def attach_details(bills: pd.DataFrame, details: pd.DataFrame, review: list[dict]) -> pd.DataFrame:
    """Join bill-details rows onto bills. PDF rows have no Id: match on RSO + title (+ submit time)."""
    cols = ["is_event", "event_last_date", "event_dates", "event_date_text", "event_date_unparsed", "event_date_ambiguous",
            "attestation_all_recaps", "expected_gt", "expected_non_gt", "engage_event_link"]
    out = bills.copy()
    for c in cols:
        out[c] = None
    if details is None or details.empty:
        return out

    keyed = out.assign(_rso=out["rso"].map(squash), _title=out["title"].map(squash))
    for rec in details.to_dict("records"):
        bid = rec.get("bill_id")
        if not bid:
            cand = keyed[(keyed["_rso"] == rec.get("rso_squashed")) & (keyed["_title"] == squash(rec.get("title") or ""))]
            if len(cand) > 1 and rec.get("submitted_at") is not None:
                delta = (cand["first_submitted"] - pd.Timestamp(rec["submitted_at"])).abs()
                cand = cand[delta <= pd.Timedelta(minutes=2)]
            if len(cand) != 1:
                review.append({
                    "kind": "BILL_PDF_UNMATCHED",
                    "detail": f"{rec.get('source_file')}: '{rec.get('title')}' ({rec.get('rso_squashed')}) "
                              f"matched {len(cand)} bills in the Engage export. Is the export older than the bill?",
                })
                continue
            bid = cand["bill_id"].iloc[0]
        idx = out.index[out["bill_id"] == bid]
        if len(idx) == 0:
            review.append({"kind": "BILL_DETAILS_UNKNOWN_ID", "detail": f"Bill details for {bid} not in Engage export"})
            continue
        for c in cols:
            if c in rec:
                out.at[idx[0], c] = rec[c]
    return out
