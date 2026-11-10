"""Synthetic test world. NEVER put real Engage/recap data in tests (student PII)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest
import yaml

from jfdc.config import load_config
from jfdc.ingest.service import ingest_file
from jfdc.pipeline import run_pipeline
from jfdc.workspace import Workspace

ENGAGE_COLS = ["Id", "ProcessName", "Title", "SubmitterName", "SubmitterEmail", "FirstSubmitted", "LastSubmitted",
               "SubmittedOnBehalfOf", "Status", "CurrentStepName", "RequestedAmount", "AdjustedAmount",
               "BudgetName", "SectionName", "LineItemName"]
RECAP_COLS = {
    "id": "ID", "start": "Start time", "done": "Completion time", "email": "Email", "name": "Name",
    "rso": "Please select your RSO:\xa0\nIf you cannot find yourself please use other and put your club name exactly as it appears on Engage.",
    "event": "Name of Event:\nPlease provide the name of the event exactly as it appears on Engage.",
    "bill": "Bill/Budget Number:\xa0\nIf there is one bill/budget related to this event, please submit just that bill/budget number.",
    "dateloc": "Event Date and Location:\nPlease provide the date and location of this event.",
    "att": "Number of Attendees:\nPlease provide both the number of GT and non-GT attendees",
    "proof": "Proof of Attendance:\nPlease provide proof of the number of attendees given above.\n",
    "summary": "Event Summary and Fund Usage Recap:\nPlease provide a brief summary",
}

DATE_Q = ("Q8: For Events Only: Please state when your event is (for example, 06/26/26). "
          "Please note that you should only submit ONE event per bill if possible.")
ADMIN, REVIEWER, CONFIRMER, OPERATOR = "chair@gatech.edu", "lead@gatech.edu", "jvpf@gatech.edu", "member@gatech.edu"


@dataclass
class World:
    root: Path
    bills: list[dict] = field(default_factory=list)
    recaps: list[dict] = field(default_factory=list)
    details: list[dict] = field(default_factory=list)
    form_has_new_questions: bool = False

    @property
    def ws(self) -> Workspace:
        return Workspace(self.root / "data")

    @property
    def cfg(self):
        return load_config(self.ws.root)

    def bill(self, bid, rso="Alpha Club", status="Approved", adjusted=500, event=True, submitted="8/1/2026 12:00",
             title=None, event_date: date | None = None, process="SGA Bills Process FY27", email=None):
        self.bills.append(dict(Id=str(bid), ProcessName=process, Title=title or f"Event {bid}",
                               SubmitterName="Test Student", SubmitterEmail=email or f"s{bid}@gatech.edu",
                               FirstSubmitted=submitted, LastSubmitted=submitted, SubmittedOnBehalfOf=rso,
                               Status=status, CurrentStepName="", RequestedAmount=str(adjusted),
                               AdjustedAmount=str(adjusted), BudgetName="Bill Request",
                               SectionName="A01 - Food and Drinks" if event else "B03 - General Inventoried Goods",
                               LineItemName="Pizza"))
        if event_date:  # stored the way Excel stores it in the JFC Data Sheet: a date serial
            self.details.append({"Bill Number": str(bid), DATE_Q: str((event_date - date(1899, 12, 30)).days)})
        return self

    def recap(self, rid, bill_text, submitted: datetime, rso="Alpha Club", dateloc="9/1/2026, Skiles 249",
              attendees="40 GT, 2 non-GT", proof="https://gtvault.sharepoint.com/x", funds_used=None, tracked=None):
        self.recaps.append(dict(id=str(rid), start=submitted, done=submitted, email="r@gatech.edu", name="R",
                                rso=rso, event="Ev", bill=bill_text, dateloc=dateloc, att=attendees, proof=proof,
                                summary="ok", funds_used=funds_used, tracked=tracked))
        return self

    def write_and_run(self, as_of: datetime, recap_as_of: datetime | None = None, allow_stale=False):
        ws = self.ws
        ws.init()
        (ws.root / "roles.yaml").write_text(yaml.safe_dump(
            {"admin": [ADMIN], "reviewer": [REVIEWER], "confirmer": [CONFIRMER]}))
        files = self.root / "in"
        files.mkdir(exist_ok=True)
        n = len(ws.uploads()) + 1
        eng = files / f"engage{n}.csv"
        pd.DataFrame(self.bills, columns=ENGAGE_COLS).to_csv(eng, index=False, encoding="cp1252")
        rec = files / f"recap{n}.xlsx"
        cols = dict(RECAP_COLS)
        rows = []
        for r in self.recaps:
            row = {cols[k]: v for k, v in r.items() if k in cols}
            if self.form_has_new_questions:
                row["Did you use the funds?"] = {True: "Yes", False: "No", None: "Yes"}[r["funds_used"]]
                row["Did you track attendance?"] = {True: "Yes", False: "No", None: "Yes"}[r["tracked"]]
            rows.append(row)
        rdf = pd.DataFrame(rows, columns=list(cols.values()) + (
            ["Did you use the funds?", "Did you track attendance?"] if self.form_has_new_questions else []))
        rdf.to_excel(rec, index=False)
        cfg = self.cfg
        ingest_file(ws, cfg, eng, by=OPERATOR, as_of=as_of)
        ingest_file(ws, cfg, rec, by=OPERATOR, as_of=recap_as_of or as_of)
        if self.details:
            det = files / f"details{n}.csv"
            pd.DataFrame(self.details).to_csv(det, index=False)
            ingest_file(ws, cfg, det, by=OPERATOR, as_of=as_of)
        return run_pipeline(ws, cfg, as_of=as_of, allow_stale=allow_stale)


APPEAL_COLS = ["ID", "Start time", "Completion time", "Email", "Name", "RSO name", "Bill number", "Your name",
               "Your GT email", "Reason for appeal", "Explanation", "Supporting evidence"]


def write_appeals(world: World, rows: list[dict], as_of: datetime) -> None:
    """rows: {id, bill, submitted, rso?, reason?, email?}. Written as the Forms Excel export, then ingested."""
    out = []
    for r in rows:
        out.append({"ID": str(r["id"]), "Start time": r["submitted"], "Completion time": r["submitted"],
                    "Email": "appellant@gatech.edu", "Name": "Appellant", "RSO name": r.get("rso", "Alpha Club"),
                    "Bill number": r["bill"], "Your name": "Pat Appellant", "Your GT email": r.get("email", ""),
                    "Reason for appeal": r.get("reason", "Recap was submitted on time"),
                    "Explanation": "We filed it on time, see screenshot", "Supporting evidence": ""})
    f = world.root / "in" / f"appeals{len(world.ws.uploads()) + 1}.xlsx"
    pd.DataFrame(out, columns=APPEAL_COLS).to_excel(f, index=False)
    ingest_file(world.ws, world.cfg, f, by=OPERATOR, as_of=as_of)


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def status_of(res, bid) -> str:
    return res.requirements.set_index("bill_id").at[str(bid), "status"]
