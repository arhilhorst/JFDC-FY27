"""Stages 2-4 for one run: rebuild everything from raw uploads + the decision ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd

from .config import Config
from .consolidate import RsoRegistry, attach_details, bill_history
from .fiscal import fiscal_year, fy_bounds
from .ingest.service import parse_source
from .ledger import LedgerState, load_ledger
from .link import link_recaps, resolve_recap_rsos
from .rules.flags import build_flags
from .rules.recap_rule import build_requirements
from .rules.strikes import build_strikes, rso_standing
from .workspace import Upload, Workspace


class StaleDataError(Exception):
    pass


@dataclass
class RunResult:
    as_of: datetime
    fy: int
    inputs: list[Upload]
    warnings: list[str]
    watermark: str
    bills: pd.DataFrame
    history: pd.DataFrame
    recaps: pd.DataFrame
    links: pd.DataFrame
    requirements: pd.DataFrame
    strikes: pd.DataFrame
    standing: pd.DataFrame
    flags: pd.DataFrame
    review: list[dict]
    quarantine: pd.DataFrame
    ledger: LedgerState = field(repr=False, default=None)


def run_pipeline(ws: Workspace, cfg: Config, as_of: datetime | None = None, allow_stale: bool = False) -> RunResult:
    pol = cfg.policy
    as_of = as_of or datetime.now().replace(microsecond=0)
    warnings: list[str] = []
    stale: list[str] = []
    fresh = pol["freshness"]

    engage_ups = sorted(ws.uploads("engage_line_items"), key=lambda u: u.as_of)
    recap_ups = sorted(ws.uploads("recap_form"), key=lambda u: u.as_of)
    detail_ups = sorted(ws.uploads("bill_details"), key=lambda u: u.as_of)
    budget_ups = sorted(ws.uploads("jfc_budgets"), key=lambda u: u.as_of)
    if not engage_ups or not recap_ups:
        raise SystemExit("Need at least one Engage export and one recap-form export. Run `jfdc ingest` first.")

    engage, recap = engage_ups[-1], recap_ups[-1]
    age_h = (as_of - recap.as_of_dt).total_seconds() / 3600
    if age_h > fresh["recap_max_age_hours"]:
        stale.append(f"Recap export is {age_h:.0f}h old (limit {fresh['recap_max_age_hours']}h): recaps filed "
                     "since then would show as OVERDUE.")
    if as_of - engage.as_of_dt > timedelta(days=fresh["engage_max_age_days"]):
        warnings.append(f"Engage export is {(as_of - engage.as_of_dt).days} days old.")
    if detail_ups and as_of - detail_ups[-1].as_of_dt > timedelta(hours=fresh["bill_details_max_age_hours"]):
        warnings.append("Newest bill details are older than "
                        f"{fresh['bill_details_max_age_hours']}h; new bills may lack event dates.")
    if stale and not allow_stale:
        raise StaleDataError(" ".join(stale) + " Upload a fresh export, or re-run with --allow-stale for a "
                             "watermarked DRAFT.")
    watermark = "DRAFT: STALE DATA. " + " ".join(stale) if stale else ""

    ledger = load_ledger(ws.decisions())
    review: list[dict] = []
    quarantine: list[dict] = []

    # ---- Engage snapshots -> current bills + history
    snapshots = []
    for up in engage_ups:
        (bills_u, _items), issues, _, _ = parse_source(ws.path_of(up), up.source, cfg, up.sheet)
        snapshots.append((up.as_of_dt, bills_u))
        if up is engage:
            quarantine += [{"upload": up.upload_id, **i} for i in issues]
    bills = snapshots[-1][1]
    history = bill_history(snapshots)

    # ---- bill details (later uploads win per bill)
    details = []
    for up in detail_ups:
        d, issues, _, _ = parse_source(ws.path_of(up), up.source, cfg, up.sheet)
        details.append(d)
        quarantine += [{"upload": up.upload_id, **i} for i in issues]
    det = pd.concat(details, ignore_index=True) if details else None
    if det is not None and "bill_id" in det:
        has_id = det["bill_id"].notna() & (det["bill_id"].astype(str) != "")
        det = pd.concat([det[has_id].drop_duplicates("bill_id", keep="last"), det[~has_id]], ignore_index=True)
    bills = attach_details(bills, det, review)

    # ---- RSOs
    budgets = parse_source(ws.path_of(budget_ups[-1]), "jfc_budgets", cfg, budget_ups[-1].sheet)[0] if budget_ups else None
    names = list(bills["rso"].unique()) + (list(budgets["rso"]) if budgets is not None else [])
    rsos = RsoRegistry.build(names, ledger)

    # ---- recaps
    recaps, issues, warns, _ = parse_source(ws.path_of(recap), recap.source, cfg, recap.sheet)
    quarantine += [{"upload": recap.upload_id, **i} for i in issues]
    warnings += warns
    recaps = resolve_recap_rsos(recaps, rsos, pol["matching"]["fuzzy_org_min_score"], review)

    # ---- link + evaluate
    links = link_recaps(recaps, bills, ledger, pol["matching"]["fallback_date_window_days"])
    fy = fiscal_year(as_of.date(), pol["fiscal_year"]["start_month"], pol["fiscal_year"]["start_day"])
    scope = cfg.scope_for_fy(fy)
    fy_start = fy_bounds(fy, pol["fiscal_year"]["start_month"], pol["fiscal_year"]["start_day"])[0]
    req = build_requirements(bills, recaps, links, ledger, pol, scope, as_of, fy_start)
    strikes = build_strikes(req, ledger, pol, as_of)
    standing = rso_standing(strikes, req, fy)
    flags = build_flags(bills, req, recaps, links, pol, scope)

    for lk in links[links["state"].isin(["needs_review", "orphan"])].to_dict("records"):
        rec = recaps.loc[recaps["recap_id"] == lk["recap_id"]].iloc[0]
        review.append({
            "kind": "LINK_" + lk["method"].upper() if lk["state"] == "needs_review" else "ORPHAN_RECAP",
            "detail": f"Recap {lk['recap_id']} ({rec['rso']}, '{rec['event_name']}', bill field {rec['bill_text']!r}) "
                      f"-> {lk['bill_id'] or 'no bill'}: {lk['note']}",
            "action": f"jfdc decide link_confirm recap_id={lk['recap_id']} bill_id={lk['bill_id']}" if lk["bill_id"] else
                      f"jfdc decide link_confirm recap_id={lk['recap_id']} bill_id=<ID>",
        })
    for r in req[req["status"] == "NEEDS_REVIEW"].to_dict("records") if len(req) else []:
        if "implausible" in (r["notes"] or "") or "Ambiguous event date" in (r["notes"] or ""):
            review.append({"kind": "CHECK_EVENT_DATE", "detail": f"Bill {r['bill_id']} ({r['rso']}): {r['notes']}",
                           "action": f"jfdc decide event_date_override bill_id={r['bill_id']} event_date=YYYY-MM-DD"})
    budget_links = links[links["state"] == "budget_ref"]
    if len(budget_links):
        warnings.append(f"{budget_links['recap_id'].nunique()} recaps cite 5-digit budget IDs; these can't be "
                        "checked until the JFC data sheet budget tab is a source (open item B2).")

    return RunResult(
        as_of=as_of, fy=fy, inputs=[engage, recap] + detail_ups + budget_ups[-1:], warnings=warnings,
        watermark=watermark, bills=bills, history=history, recaps=recaps, links=links, requirements=req,
        strikes=strikes, standing=standing, flags=flags, review=review,
        quarantine=pd.DataFrame(quarantine, columns=["upload", "row", "code", "message"]), ledger=ledger,
    )
