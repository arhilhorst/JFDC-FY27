"""Strike appeals (docs/APPEALS.md): window, admin-only decisions, grant removes the strike, emails."""

from datetime import date, datetime

import pytest
from conftest import ADMIN, CONFIRMER, REVIEWER, write_appeals

from jfdc.ledger import PermissionDenied, record_decision
from jfdc.notify import build_queue
from jfdc.pipeline import run_pipeline

POLICY_APPEALS = {"window_days": 30, "form_url": ""}


def rerun(w, as_of):
    return run_pipeline(w.ws, w.cfg, as_of=as_of, allow_stale=True)


def _confirmed_strike(world, bid="100600"):
    world.bill(int(bid), event_date=date(2026, 8, 20))  # due 9/3, no recap -> OVERDUE
    world.write_and_run(datetime(2026, 9, 20))
    record_decision(world.ws, world.cfg, "strike_confirm", REVIEWER, bill_id=bid, confirmed_by=CONFIRMER)
    res = rerun(world, datetime(2026, 9, 20))
    q = build_queue(res, [], 3, POLICY_APPEALS)
    # Strike email marked sent on 9/21 -> appeal deadline 10/21
    sent = [{"bill_id": n["bill_id"], "notice": n["notice"], "ordinal": n["ordinal"], "ref": n["ref"],
             "sent_at": "2026-09-21T10:00:00"} for n in q.to_dict("records")]
    for n in sent:
        world.ws.mark_notice_sent(n)
    return q


def test_strike_email_explains_how_to_appeal(world):
    q = _confirmed_strike(world)
    body = q.set_index("notice").at["STRIKE_1", "body"]
    assert "HOW TO APPEAL" in body and "within 30 days" in body and "(by 2026-10-20)" in body
    assert "Appeal Form is coming soon" in body  # no form_url yet
    world.bills.clear()
    res = rerun(world, datetime(2026, 9, 20))
    q2 = build_queue(res, [], 3, {"window_days": 30, "form_url": "https://forms.office.com/r/abc"})
    assert "fill out the Strike Appeal Form: https://forms.office.com/r/abc" in q2.set_index("notice").at["STRIKE_1", "body"]


def test_open_appeal_is_matched_listed_and_acknowledged(world):
    _confirmed_strike(world)
    write_appeals(world, [{"id": 7, "bill": "Bill #100600", "submitted": datetime(2026, 9, 25, 12),
                           "email": "pat@gatech.edu"}], datetime(2026, 9, 26))
    res = rerun(world, datetime(2026, 9, 26))
    a = res.appeals.iloc[0]
    assert (a["status"], a["bill_id"], a["strike_state"], a["timely"]) == ("OPEN", "100600", "confirmed", True)
    assert a["appeal_deadline"] == date(2026, 10, 21)
    assert any(r["kind"] == "APPEAL_OPEN" for r in res.review)
    # consequence NOT paused while open
    assert res.standing.iloc[0]["standing"].startswith("STRIKE 1")
    q = build_queue(res, world.ws.notices_sent(), 3, POLICY_APPEALS)
    ack = q[q["notice"] == "APPEAL_RECEIVED"].iloc[0]
    assert ack["to"] == "pat@gatech.edu" and ack["ref"] == "7"


def test_only_admin_decides_and_reason_is_required(world):
    _confirmed_strike(world)
    with pytest.raises(PermissionDenied):
        record_decision(world.ws, world.cfg, "appeal_grant", REVIEWER, reason="x", appeal_id="7", bill_id="100600")
    with pytest.raises(ValueError, match="reason"):
        record_decision(world.ws, world.cfg, "appeal_grant", ADMIN, appeal_id="7", bill_id="100600")


def test_granted_appeal_removes_strike_and_sends_granted_not_removed(world):
    _confirmed_strike(world)
    write_appeals(world, [{"id": 7, "bill": "100600", "submitted": datetime(2026, 9, 25)}], datetime(2026, 9, 26))
    record_decision(world.ws, world.cfg, "appeal_grant", ADMIN, reason="Recap found in a different form",
                    appeal_id="7", bill_id="100600")
    res = rerun(world, datetime(2026, 9, 27))
    s = res.strikes.iloc[0]
    assert s["state"] == "removed" and s["via_appeal"] == "7" and s["decided_by"] == ADMIN
    assert res.standing.iloc[0]["standing"] == "GOOD"
    assert res.appeals.iloc[0]["status"] == "GRANTED"
    kinds = set(build_queue(res, world.ws.notices_sent(), 3, POLICY_APPEALS)["notice"])
    assert "APPEAL_GRANTED" in kinds and "STRIKE_REMOVED" not in kinds


def test_denied_appeal_keeps_strike(world):
    _confirmed_strike(world)
    write_appeals(world, [{"id": 8, "bill": "100600", "submitted": datetime(2026, 9, 25)}], datetime(2026, 9, 26))
    record_decision(world.ws, world.cfg, "appeal_deny", ADMIN, reason="Recap was filed 9/18, after the 9/3 deadline",
                    appeal_id="8", bill_id="100600")
    res = rerun(world, datetime(2026, 9, 27))
    assert res.strikes.iloc[0]["state"] == "confirmed" and res.appeals.iloc[0]["status"] == "DENIED"
    body = build_queue(res, world.ws.notices_sent(), 3, POLICY_APPEALS).set_index("notice").at["APPEAL_DENIED", "body"]
    assert "the strike stands" in body and "after the 9/3 deadline" in body


def test_late_or_unmatched_appeals_are_listed_with_checks(world):
    _confirmed_strike(world)
    write_appeals(world, [
        {"id": 9, "bill": "100600", "submitted": datetime(2026, 11, 1)},          # after 10/21
        {"id": 10, "bill": "we don't know it", "submitted": datetime(2026, 9, 25)},
        {"id": 11, "bill": "100600", "submitted": datetime(2026, 9, 25), "rso": "Beta Society"},
    ], datetime(2026, 11, 2))
    a = rerun(world, datetime(2026, 11, 2)).appeals.set_index("appeal_id")
    assert not a.at["9", "timely"] and "after the 30-day window" in a.at["9", "checks"]
    assert a.at["10", "bill_id"] == "" and "No 6-digit bill number" in a.at["10", "checks"]
    assert "belongs to 'Alpha Club'" in a.at["11", "checks"]
    assert set(a["status"]) == {"OPEN"}  # all still go to a human


def test_grant_without_confirmed_strike_changes_nothing(world):
    world.bill(100610, event_date=date(2026, 8, 20))
    world.write_and_run(datetime(2026, 9, 20))  # strike only PROPOSED
    write_appeals(world, [{"id": 12, "bill": "100610", "submitted": datetime(2026, 9, 21)}], datetime(2026, 9, 22))
    record_decision(world.ws, world.cfg, "appeal_grant", ADMIN, reason="x", appeal_id="12", bill_id="100610")
    res = rerun(world, datetime(2026, 9, 22))
    assert res.strikes.iloc[0]["state"] == "proposed"
    assert "no confirmed strike to remove" in res.appeals.iloc[0]["checks"]
