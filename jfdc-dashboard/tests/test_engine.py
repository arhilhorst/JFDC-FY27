"""Run with:  python -m pytest -q"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jfdc import engine  # noqa: E402
from jfdc.parsing import norm_rso, parse_attendance, parse_bill_numbers  # noqa: E402
from jfdc.sources import FileSource  # noqa: E402

CFG = json.loads((ROOT / "config.json").read_text())


def build(today=date(2026, 11, 10)):
    s = ROOT / "sample_data"
    return engine.build(
        FileSource(s / "recap_responses_sample.xlsx").load(),
        FileSource(s / "bills_sample.xlsx").load(),
        FileSource(s / "strike_adjustments.csv").load(),
        CFG, today,
    )


def rso(d, name):
    return next(r for r in d["rsos"] if r["name"] == name)


def bill(d, num):
    return next(b for b in d["bills"] if b["bill_number"] == num)


def test_bill_number_parsing():
    assert parse_bill_numbers("Bill # 377345") == ["377345"]
    assert parse_bill_numbers("376684, 375615") == ["376684", "375615"]
    assert parse_bill_numbers("[Bill #26909], [Bill #26910]") == ["26909", "26910"]
    assert parse_bill_numbers("380761 AO1 Line 1 236.39") == ["380761"]
    assert parse_bill_numbers("N/A") == []


def test_attendance_parsing():
    a = parse_attendance("58 gt, 4 non-gt")
    assert (a["gt"], a["non_gt"], a["total"]) == (58, 4, 62)
    assert parse_attendance("64gt 6 non gt")["total"] == 70
    assert parse_attendance("N/A")["tracked"] is False
    assert parse_attendance("-7GT")["issue"] == "Negative attendance number"
    assert parse_attendance("September 24, 2026 · Student Center")["total"] is None


def test_rso_name_matching():
    assert norm_rso("Billiard Club at GT") == norm_rso("billiard club @ GT")
    assert norm_rso("ASHRAE at Georgia Tech ") == norm_rso("Ashrae at Georgia Tech")


def test_strike_levels():
    d = build()
    assert rso(d, "Robotics Collective")["level"]["level"] == 0
    assert rso(d, "Ceramics Guild")["level"]["level"] == 1
    assert rso(d, "Ceramics Guild")["eligibility"]["eligible"] is True
    assert rso(d, "Midnight Chess Society")["eligibility"]["eligible"] is False
    hike = rso(d, "Trailblazers Hiking Club")
    assert hike["level"]["level"] == 2 and hike["eligibility"]["until"] == "2026-11-29"
    assert rso(d, "Campus Film Society")["level"]["level"] == 3


def test_bill_statuses():
    d = build()
    assert bill(d, "500101")["recap_status"] == "on_time"
    assert bill(d, "500201")["recap_status"] == "late"
    assert bill(d, "500302")["recap_status"] == "missing"
    assert bill(d, "500403")["recap_status"] == "pending"
    assert bill(d, "500701")["recap_status"] == "not_tracked"
    assert bill(d, "500901")["recap_status"] == "waived"
    assert bill(d, "501101")["recap_status"] == "not_funded"  # denied bill
    assert bill(d, "501102")["recap_status"] == "not_required"  # equipment
    assert bill(d, "500601")["flags"]  # low attendance


def test_name_variant_merges_into_one_rso():
    d = build()
    assert not any(r["name"] == "Pre Law Circle @ GT" for r in d["rsos"])
    assert rso(d, "Pre-Law Circle")["recap_count"] == 1


def test_strikes_reset_next_fiscal_year():
    d = build(today=date(2027, 7, 15))
    assert rso(d, "Campus Film Society")["level"]["level"] == 0


def test_event_date_from_recap_text():
    from jfdc.parsing import parse_event_date_text as p
    sub = date(2026, 9, 14)
    assert p("8/28/2026, Whitaker 4101", sub) == date(2026, 8, 28)
    assert p("Thursday, September 10, 2026 at 6:00 PM", sub) == date(2026, 9, 10)
    assert p("8/21, Van Leer C456", sub) == date(2026, 8, 21)
    assert p("Thurs Aug 27, George Tower", sub) == date(2026, 8, 27)
    assert p("10-9-26 Student Center", date(2026, 10, 20)) == date(2026, 10, 9)
    assert p("Setpember 13 @ The Connector", sub) == date(2026, 9, 13)
    assert p("Instructional Center 105", sub) is None
