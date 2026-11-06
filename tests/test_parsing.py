from datetime import date

import pytest

from jfdc.ingest.bill_details import parse_bill_text
from jfdc.parsing import extract_bill_refs, parse_attendees, parse_event_dates
from jfdc.textnorm import org_key

REF = date(2026, 10, 1)


@pytest.mark.parametrize("text,expected", [
    ("376684, 375615", ["376684", "375615"]),
    ("Bill # 377345", ["377345"]),
    ("[Bill #26909], [Bill #26910]", ["26909", "26910"]),
    ("Budget 338443 Line 17, Budget 338443 Line 18", ["338443"]),
    ("380761 AO1 Line 1 236.39", ["380761"]),
    ("N/Aa", []),
    ("SGA Budget, A01 - Line 1, Pizza", []),
])
def test_bill_refs(text, expected):
    assert [r.token for r in extract_bill_refs(text)] == expected


@pytest.mark.parametrize("text,last", [
    ("8/28/2026, Whitaker 4101", date(2026, 8, 28)),
    ("Sunday, August 23, 2026 in Bobby Dodd Stadium", date(2026, 8, 23)),
    ("8/21, Van Leer C456", date(2026, 8, 21)),
    ("Monday, October 12, 2026; 6:00PM -7:30PM; IC 111", date(2026, 10, 12)),
    ("COC 050 September 10 2026 6:30 - 8 PM", date(2026, 9, 10)),
    ("10-9-26 Student Center", date(2026, 10, 9)),
    ("10/16-10/18/26 Atlanta", date(2026, 10, 18)),
    ("Sept 3-5, 2026", date(2026, 9, 5)),
    ("-October12,2026", date(2026, 10, 12)),
    ("6:30-8 pm, 9/17/26, Scheller 100", date(2026, 9, 17)),
    ("-N/A", None),
])
def test_event_dates(text, last):
    assert parse_event_dates(text, REF).last == last


@pytest.mark.parametrize("text,gt,non", [
    ("45 GT, 0 non-GT", 45, 0), ("58 gt, 4 non-gt", 58, 4), ("46 GT students", 46, None),
    ("52", 52, None), ("1,837 GT", 1837, None), ("-N/A", None, None),
])
def test_attendees(text, gt, non):
    a = parse_attendees(text)
    assert (a.gt, a.non_gt) == (gt, non)


def test_org_key():
    assert org_key("Graduate Women in Engineering (GWiE)") == org_key("Graduate Women in Engineering")
    assert org_key("Ramblin’ Reck Club") == org_key("Ramblin' Reck Club")
    assert org_key("Dungeons & Dragons Club") == org_key("Dungeons and Dragons Club")


SAMPLE_PDF_TEXT = """\
                                    Test Bill | Page 1 of 6
Budget Request: Spring Kickoff
Requested Total       $640.00
Date Created          Thursday,November5,202610:22:19PM
Organization          AlphaClub
Status                ApprovedonFriday,November6,202610:32:46PM
Process               SGABillsProcessFY27
Additional Information
Page 1
HaveyousubmittedPost-EventRecapFormsforALLeventsfundedbySGAthathavealreadyoccurredthisFiscalYear?
  Yes
Isthisrequestintendedtobeusedwithanevent(i.e.areyourequestingfundingfromsectionA)?
  Yes
ForEventsOnly:Pleasestatewhenyoureventis(forexample,06/26/26).PleasenotethatyoushouldonlysubmitONE
eventperbillifpossible.
  -11/20/26-11/22/26
ForEventsOnly:Ifyouarerequestingfundingforaneventorhostingaconference,pleasespecifytheexpectednumberof
attendees.(e.g.100GT,5Non-GT).
  -100GT,5Non-GT
Request History
"""


def test_bill_pdf_text():
    from jfdc.config import load_config

    q = load_config().sources["bill_details"]["pdf_questions"]
    out = parse_bill_text(SAMPLE_PDF_TEXT, q)
    assert out["title"] == "Spring Kickoff"
    assert out["organization"] == "AlphaClub"
    assert out["is_event"] == "Yes"
    assert out["attestation"] == "Yes"
    assert parse_event_dates(out["event_date_text"], REF).last == date(2026, 11, 22)
    assert parse_attendees(out["expected_attendance_text"]).non_gt == 5
