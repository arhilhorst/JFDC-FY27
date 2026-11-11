"""`jfdc demo`: a complete workspace built from FICTIONAL data, for trying the dashboard and training.

Every name, email and bill here is made up. Nothing is read from a real data directory.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yaml

from .config import load_config
from .ingest.service import ingest_file
from .ledger import record_decision
from .notify import build_queue, write_notices
from .pipeline import run_pipeline
from .report import write_run
from .workspace import Workspace

AS_OF = datetime(2026, 10, 20, 9, 0)
ADMIN, REVIEWER, CONFIRMER, OPERATOR = ("chair@gatech.edu", "lead@gatech.edu", "jvpf@gatech.edu",
                                        "member@gatech.edu")
RSOS = ["Aurora Robotics", "Birch Street Chess Club", "Cedar Film Society", "Delta Debate Union",
        "Ember Dance Collective", "Fjord Outdoors Club", "Granite Climbing Team", "Harbor Jazz Ensemble",
        "Iris Gardening Club", "Juniper Coding Circle", "Kestrel Astronomy Club", "Lumen Photography Guild"]
FIRST = ["Alex", "Blair", "Casey", "Devon", "Emery", "Finley", "Harper", "Jordan", "Kai", "Logan", "Morgan", "Quinn"]
LAST = ["Rivera", "Chen", "Okafor", "Novak", "Haddad", "Larsen", "Ibarra", "Mensah", "Sato", "Kowalski"]
EVENTS = ["Kickoff Social", "Workshop", "Game Night", "Speaker Panel", "Field Trip", "Showcase", "Info Session"]
ENGAGE_COLS = ["Id", "ProcessName", "Title", "SubmitterName", "SubmitterEmail", "FirstSubmitted", "LastSubmitted",
               "SubmittedOnBehalfOf", "Status", "CurrentStepName", "RequestedAmount", "AdjustedAmount",
               "BudgetName", "SectionName", "LineItemName"]
DATE_Q = ("Q8: For Events Only: Please state when your event is (for example, 06/26/26). "
          "Please note that you should only submit ONE event per bill if possible.")
RECAP_HEADERS = {
    "id": "ID", "start": "Start time", "done": "Completion time", "email": "Email", "name": "Name",
    "rso": "Please select your RSO:\nIf you cannot find yourself please use other.",
    "event": "Name of Event:\nPlease provide the name of the event exactly as it appears on Engage.",
    "bill": "Bill/Budget Number:\nIf there is one bill/budget related to this event, submit that number.",
    "dateloc": "Event Date and Location:\nPlease provide the date and location of this event.",
    "att": "Number of Attendees:\nPlease provide both the number of GT and non-GT attendees",
    "proof": "Proof of Attendance:\nPlease provide proof of the number of attendees given above.",
    "summary": "Event Summary and Fund Usage Recap:\nPlease provide a brief summary",
}
APPEAL_HEADERS = ["ID", "Start time", "Completion time", "Email", "Name", "RSO name", "Bill number", "Your name",
                  "Your GT email", "Reason for appeal", "Explanation", "Supporting evidence"]


def build_demo(root: Path, seed: int = 7) -> Path:
    """Create a demo workspace under `root` and return the run directory it produced."""
    rnd = random.Random(seed)
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"{root} already exists and isn't empty. Pick a new folder for the demo.")
    ws = Workspace(root / "data")
    ws.init()
    (ws.root / "roles.yaml").write_text(yaml.safe_dump(
        {"admin": [ADMIN], "reviewer": [REVIEWER], "confirmer": [CONFIRMER]}))
    inbox = root / "inbox"
    inbox.mkdir()

    bills, details, recaps = [], [], []
    bid = 400100
    for i, rso in enumerate(RSOS):
        for _ in range(rnd.randint(3, 6)):
            bid += rnd.randint(1, 9)
            person = f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"
            email = f"{person.split()[0][0].lower()}{person.split()[1].lower()}{rnd.randint(1, 99)}@gatech.edu"
            event = AS_OF.date() - timedelta(days=rnd.randint(-10, 60))
            amount = rnd.choice([150, 240, 380, 520, 900, 1450])
            status = "Approved" if rnd.random() > .08 else "Submitted"
            bills.append(dict(Id=str(bid), ProcessName="SGA Bills Process FY27",
                              Title=f"{rso.split()[0]} {rnd.choice(EVENTS)}", SubmitterName=person,
                              SubmitterEmail=email, FirstSubmitted=(event - timedelta(days=20)).strftime("%m/%d/%Y 12:00"),
                              LastSubmitted="", SubmittedOnBehalfOf=rso, Status=status, CurrentStepName="",
                              RequestedAmount=str(amount), AdjustedAmount=str(amount), BudgetName="Bill Request",
                              SectionName="A01 - Food and Drinks", LineItemName="Catering"))
            if rnd.random() > .1:  # ~10% have no bill details yet -> NO_EVENT_DATE
                details.append({"Bill Number": str(bid), DATE_Q: event.strftime("%m/%d/%y")})
            due = event + timedelta(days=14)
            roll = rnd.random()
            if event < AS_OF.date() and roll < .78 - i * .03:  # later RSOs are less compliant
                late = roll > .62 - i * .03
                filed = datetime.combine(due + timedelta(days=rnd.randint(2, 9)) if late
                                         else event + timedelta(days=rnd.randint(1, 12)), datetime.min.time()) + timedelta(hours=15)
                if filed > AS_OF:
                    continue
                attendees = "" if rnd.random() < .06 else f"{rnd.randint(8, 120)} GT, {rnd.randint(0, 9)} non-GT"
                recaps.append(dict(id=str(len(recaps) + 1), start=filed, done=filed, email=email, name=person, rso=rso,
                                   event="Event", bill=rnd.choice([str(bid), f"Bill #{bid}", f"{bid}"]) if rnd.random() > .05 else "n/a",
                                   dateloc=f"{event:%m/%d/%Y}, Student Center", att=attendees,
                                   proof="https://example.invalid/attendance.png", summary="Food for attendees."))

    files = {"engage": inbox / "Engage_export.csv", "recaps": inbox / "Post_Event_Recap_Form.xlsx",
             "details": inbox / "CampusLabs_Budget_Requests.csv"}
    pd.DataFrame(bills, columns=ENGAGE_COLS).to_csv(files["engage"], index=False, encoding="cp1252")
    pd.DataFrame([{RECAP_HEADERS[k]: v for k, v in r.items()} for r in recaps],
                 columns=list(RECAP_HEADERS.values())).to_excel(files["recaps"], index=False)
    pd.DataFrame(details).to_csv(files["details"], index=False)
    cfg = load_config(ws.root)
    for f in files.values():
        ingest_file(ws, cfg, f, by=OPERATOR, as_of=AS_OF)

    # Confirm about two thirds of the proposed strikes and mark their emails sent 12 days ago.
    res = run_pipeline(ws, cfg, as_of=AS_OF)
    proposed = sorted(res.strikes.loc[res.strikes["state"] == "proposed", "bill_id"]) if len(res.strikes) else []
    confirmed = [b for i, b in enumerate(proposed) if i % 3 != 2]
    for b in confirmed:
        record_decision(ws, cfg, "strike_confirm", REVIEWER, bill_id=b, confirmed_by=CONFIRMER)
    res = run_pipeline(ws, cfg, as_of=AS_OF)
    sent_at = (AS_OF - timedelta(days=12)).isoformat(timespec="seconds")
    for n in build_queue(res, [], 3, cfg.policy.get("appeals")).to_dict("records"):
        if n["notice"].startswith("STRIKE_") and not n["hold_reason"]:
            ws.mark_notice_sent({"bill_id": n["bill_id"], "notice": n["notice"], "to": n["to"], "run_id": "demo",
                                 "ordinal": n["ordinal"], "ref": "", "sent_by": OPERATOR, "sent_at": sent_at})

    # Three appeals: one granted, one denied, one still open.
    reasons = ["Recap was submitted on time", "Event was cancelled or funds were not used", "Wrong event date"]
    rows = []
    for k, b in enumerate(confirmed[:3]):
        rso = next(x["SubmittedOnBehalfOf"] for x in bills if x["Id"] == b)
        when = AS_OF - timedelta(days=6 - k * 2)
        rows.append({"ID": str(k + 1), "Start time": when, "Completion time": when, "Email": f"officer{k + 1}@gatech.edu",
                     "Name": f"Officer {k + 1}", "RSO name": rso, "Bill number": b, "Your name": f"Officer {k + 1}",
                     "Your GT email": f"officer{k + 1}@gatech.edu", "Reason for appeal": reasons[k],
                     "Explanation": "We believe this was flagged by mistake; details attached.", "Supporting evidence": ""})
    if rows:
        f = inbox / "Strike_Appeal_Form.xlsx"
        pd.DataFrame(rows, columns=APPEAL_HEADERS).to_excel(f, index=False)
        ingest_file(ws, cfg, f, by=OPERATOR, as_of=AS_OF)
        record_decision(ws, cfg, "appeal_grant", ADMIN, reason="Recap found under a different bill number",
                        appeal_id="1", bill_id=confirmed[0])
        if len(rows) > 1:
            record_decision(ws, cfg, "appeal_deny", ADMIN, reason="Recap was filed after the deadline",
                            appeal_id="2", bill_id=confirmed[1])

    res = run_pipeline(ws, cfg, as_of=AS_OF)
    out = write_run(res, ws.runs_dir)
    write_notices(build_queue(res, ws.notices_sent(), 3, cfg.policy.get("appeals")), out)
    return out
